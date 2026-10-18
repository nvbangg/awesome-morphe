package me.jman.parser

import com.googlecode.d2j.Method
import com.googlecode.d2j.dex.Dex2jar
import com.googlecode.d2j.dex.DexExceptionHandler
import com.googlecode.d2j.node.DexMethodNode
import com.googlecode.d2j.reader.BaseDexFileReader
import com.googlecode.d2j.reader.DexFileReader
import com.googlecode.d2j.reader.MultiDexFileReader
import com.googlecode.d2j.visitors.DexFileVisitor
import java.io.File
import java.util.jar.JarEntry
import java.util.jar.JarFile
import java.util.jar.JarOutputStream
import org.objectweb.asm.*

private val rootDex = Regex("classes(?:[2-9]|[1-9][0-9]+)?\\.dex")
private const val MAX_DEX_BYTES = 32 * 1024 * 1024
private const val MAX_CONVERTED_BYTES = 32 * 1024 * 1024

/** Only root patch DEX files qualify; extensions/classes.dex is application code. */
internal fun hasRootPatchDex(file: File): Boolean = JarFile(file).use { jar ->
    jar.entries().asSequence().any { entry ->
        rootDex.matches(entry.name) && entry.size in 112..MAX_DEX_BYTES.toLong() &&
            jar.getInputStream(entry).use { it.readNBytes(4).contentEquals(byteArrayOf(100, 101, 120, 10)) }
    }
}

/**
 * Runs inside the existing heap/deadline-limited runtime worker. The downloaded
 * artifact and its proof hash stay unchanged; the temporary JAR is inspection-only.
 */
internal fun jvmInspectionArtifact(file: File, workspace: File, namespace: String? = null): File {
    // Even an invalid root DEX must be inspected or rejected when JVM classes
    // are present. Otherwise a broken hybrid archive could pass as JVM-only.
    val containsRootDex = JarFile(file).use { jar ->
        jar.entries().asSequence().any { !it.isDirectory && rootDex.matches(it.name) }
    }
    if (!containsRootDex) {
        requireJvmPatchClasses(file)
        return file
    }
    workspace.mkdirs()
    val expected = mutableSetOf<String>()
    // Supply dex2jar only the validated root DEX entries. Its ZIP reader also
    // recognizes names such as classes-extra.dex, which are not patch roots.
    val inspectedDex = File(workspace, "patch-dex.jar")
    JarFile(file).use { jar ->
        var total = 0
        val entries = jar.entries().asSequence().filter { rootDex.matches(it.name) }.toList()
        require(entries.size <= 32) { "Too many patch DEX files" }
        JarOutputStream(inspectedDex.outputStream()).use { out ->
            for (entry in entries) {
                require(entry.size in 112..MAX_DEX_BYTES.toLong()) { "Patch DEX exceeds inspection budget" }
                val bytes = jar.getInputStream(entry).use { it.readNBytes(MAX_DEX_BYTES + 1) }
                if (!bytes.take(4).toByteArray().contentEquals(byteArrayOf(100, 101, 120, 10)))
                    throw IncompletePatchInventory("Patch DEX has an invalid header")
                total += bytes.size
                require(total <= MAX_DEX_BYTES) { "Patch DEX exceeds inspection budget" }
                for (name in DexFileReader(bytes).classNames) {
                    val path = name.removePrefix("L").removeSuffix(";") + ".class"
                    require(expected.add(path)) { "Duplicate class across patch DEX files" }
                }
                out.putNextEntry(JarEntry(entry.name))
                out.write(bytes)
                out.closeEntry()
            }
        }
    }
    require(expected.isNotEmpty()) { "Patch DEX contains no classes" }
    val translated = File(workspace, "translated.jar")
    val reader = MultiDexFileReader.open(inspectedDex.readBytes())
    // dex2jar normally suppresses class-reader exceptions. A partially read
    // class still appears in its output, so checking class names cannot prove
    // that every patch export was inspected. Reject those errors instead.
    val strictReader = object : BaseDexFileReader by reader {
        override fun accept(visitor: DexFileVisitor, flags: Int) {
            reader.accept(visitor, flags and DexFileReader.IGNORE_READ_EXCEPTION.inv())
        }
    }
    Dex2jar.from(strictReader).dontSanitizeNames(true).computeFrames(true)
        .withExceptionHandler(object : DexExceptionHandler {
            override fun handleFileException(error: Exception) {
                throw IncompletePatchInventory("Could not translate patch DEX").apply { initCause(error) }
            }
            override fun handleMethodTranslateException(method: Method, node: DexMethodNode,
                                                        visitor: MethodVisitor, error: Exception) {
                throw IncompletePatchInventory("Could not translate patch DEX method $method")
                    .apply { initCause(error) }
            }
        }).to(translated.toPath())
    require(translated.length() <= MAX_CONVERTED_BYTES) { "Translated patches exceed inspection budget" }
    val converted = File(workspace, "inspection.jar")
    JarFile(translated).use { classes ->
        val actual = classes.entries().asSequence().filter { it.name.endsWith(".class") }
            .map { it.name }.toSet()
        if (!actual.containsAll(expected))
            throw IncompletePatchInventory("DEX translation omitted patch classes")
        JarFile(file).use { original ->
            // Hybrid Android/JVM releases can publish the same patch class in
            // both formats. The JVM class was the original loader's choice;
            // retain it and add only classes absent from the JVM archive.
            val jvmClasses = original.entries().asSequence()
                .filter { !it.isDirectory && it.name.endsWith(".class") && !it.name.startsWith("META-INF/") }
                .map { it.name }.toSet()
            val overlaps = jvmClasses.intersect(expected)
            if (overlaps.isNotEmpty()) {
                val namespaces = namespace?.let(::listOf)
                    ?: listOf("app/morphe/patcher", "app/revanced/patcher")
                for (patcher in namespaces) {
                    val originalExports = declaredPatchExportSignatures(file, patcher)
                    val dexExports = declaredPatchExportSignatures(translated, patcher)
                    for (path in overlaps) {
                        if (originalExports[path].orEmpty() != dexExports[path].orEmpty())
                            throw IncompletePatchInventory("Conflicting JVM/DEX patch exports in $path")
                    }
                }
                var comparedBytes = 0L
                for (path in overlaps) {
                    val jvm = readPatchClass(original, original.getJarEntry(path))
                    val dex = readPatchClass(classes, classes.getJarEntry(path))
                    comparedBytes += jvm.size.toLong() + dex.size
                    require(comparedBytes <= MAX_CONVERTED_BYTES.toLong() * 2) {
                        "Overlapping classes exceed inspection budget"
                    }
                    if (!equivalentHybridClassShape(jvm, dex))
                        throw IncompletePatchInventory("Conflicting JVM/DEX class hierarchy in $path")
                    if (patchMetadataSignature(jvm) != patchMetadataSignature(dex))
                        throw IncompletePatchInventory("Conflicting JVM/DEX patch annotations in $path")
                }
            }
            JarOutputStream(converted.outputStream()).use { out ->
                var total = 0
                val written = mutableSetOf<String>()
                for (entry in classes.entries().asSequence().filter {
                    !it.isDirectory && it.name.endsWith(".class") && it.name !in jvmClasses
                }) {
                    val bytes = classes.getInputStream(entry).use { it.readNBytes(MAX_CONVERTED_BYTES + 1) }
                    total += bytes.size
                    require(total <= MAX_CONVERTED_BYTES) { "Translated patches exceed inspection budget" }
                    require(written.add(entry.name)) { "Duplicate translated patch class" }
                    out.putNextEntry(JarEntry(entry.name))
                    out.write(correctTranslatorFrames(bytes))
                    out.closeEntry()
                }
                // Retain original resources, including extension DEX files that
                // are not patch roots. The inspection copy is never published.
                var resources = 0L
                for (entry in original.entries().asSequence().filter {
                    !it.isDirectory && !rootDex.matches(it.name) && !isJarSignature(it.name)
                }) {
                    require(entry.size >= 0 && entry.size <= 256L * 1024 * 1024 - resources) {
                        "Patch resources exceed inspection budget"
                    }
                    require(written.add(entry.name)) { "Duplicate class or resource in patch archive" }
                    out.putNextEntry(JarEntry(entry.name))
                    original.getInputStream(entry).use { input ->
                        val buffer = ByteArray(8192)
                        while (true) {
                            val count = input.read(buffer)
                            if (count < 0) break
                            resources += count
                            require(resources <= 256L * 1024 * 1024) { "Patch resources exceed inspection budget" }
                            out.write(buffer, 0, count)
                        }
                    }
                    out.closeEntry()
                }
            }
        }
    }
    val namespaces = namespace?.let(::listOf) ?: listOf("app/morphe/patcher", "app/revanced/patcher")
    if (namespaces.all { declaredPatchExportCount(converted, it) == 0 } &&
        (namespace != null || parseLegacyPatchBundle(converted).isEmpty()))
        throw IncompletePatchInventory("Root DEX contains no declared patch exports")
    return converted
}

/** Preserve the source JVM class only if its DEX counterpart has the same type shape. */
internal fun equivalentHybridClassShape(jvm: ByteArray, dex: ByteArray): Boolean {
    val a = ClassReader(jvm)
    val b = ClassReader(dex)
    val kindMask = Opcodes.ACC_INTERFACE or Opcodes.ACC_ANNOTATION or Opcodes.ACC_ENUM
    return a.className == b.className &&
        (a.access and kindMask) == (b.access and kindMask) &&
        a.superName == b.superName && a.interfaces.toSet() == b.interfaces.toSet()
}

/** Compare publisher patch annotations independent of bytecode and Kotlin compiler metadata. */
internal fun patchMetadataSignature(bytes: ByteArray): List<String> {
    val result = mutableListOf<String>()
    fun normalize(value: Any?): String = when (value) {
        is Type -> "type:${value.descriptor}"
        is ByteArray -> value.joinToString(",", "bytes:[", "]")
        is BooleanArray -> value.joinToString(",", "booleans:[", "]")
        is ShortArray -> value.joinToString(",", "shorts:[", "]")
        is IntArray -> value.joinToString(",", "ints:[", "]")
        is LongArray -> value.joinToString(",", "longs:[", "]")
        is CharArray -> value.joinToString(",", "chars:[", "]") { it.code.toString() }
        is FloatArray -> value.joinToString(",", "floats:[", "]") { it.toRawBits().toString() }
        is DoubleArray -> value.joinToString(",", "doubles:[", "]") { it.toRawBits().toString() }
        is Array<*> -> value.joinToString(",", "objects:[", "]") { normalize(it) }
        else -> "${value?.javaClass?.name}:${value.toString()}"
    }
    // Attribute order is immaterial, but dependencies and other annotation
    // arrays are positional. Include each element's index before sorting.
    fun visitor(path: String, array: Boolean = false): AnnotationVisitor = object : AnnotationVisitor(Opcodes.ASM9) {
        private var index = 0
        private fun location(name: String?): String =
            if (array) "$path[${index++}]" else "$path/${name.orEmpty()}"
        override fun visit(name: String?, value: Any?) {
            result += "${location(name)}=${normalize(value)}"
        }
        override fun visitEnum(name: String?, descriptor: String, value: String) {
            result += "${location(name)}=enum:$descriptor:$value"
        }
        override fun visitAnnotation(name: String?, descriptor: String): AnnotationVisitor {
            val location = location(name)
            result += "$location=annotation:$descriptor"
            return visitor(location)
        }
        override fun visitArray(name: String?): AnnotationVisitor {
            val location = location(name)
            result += "$location=array"
            return visitor(location, array = true)
        }
    }
    fun annotation(path: String, descriptor: String, visible: Boolean): AnnotationVisitor? {
        if (!descriptor.contains("/patcher/")) return null
        val marker = "$path:$descriptor:$visible"
        result += marker
        return visitor(marker)
    }
    ClassReader(bytes).accept(object : ClassVisitor(Opcodes.ASM9) {
        override fun visitAnnotation(descriptor: String, visible: Boolean): AnnotationVisitor? =
            annotation("class", descriptor, visible)
        override fun visitField(access: Int, name: String, descriptor: String, signature: String?,
                                value: Any?): FieldVisitor = object : FieldVisitor(Opcodes.ASM9) {
            override fun visitAnnotation(descriptor: String, visible: Boolean): AnnotationVisitor? =
                annotation("field:$name", descriptor, visible)
        }
        override fun visitMethod(access: Int, name: String, descriptor: String, signature: String?,
                                 exceptions: Array<out String>?): MethodVisitor = object : MethodVisitor(Opcodes.ASM9) {
            override fun visitAnnotation(descriptor: String, visible: Boolean): AnnotationVisitor? =
                annotation("method:$name$descriptor", descriptor, visible)
        }
    }, ClassReader.SKIP_CODE or ClassReader.SKIP_DEBUG or ClassReader.SKIP_FRAMES)
    return result.sorted()
}

/** Signatures cannot attest to the modified inspection JAR; the source hash is kept separately. */
private fun isJarSignature(path: String): Boolean {
    if (!path.startsWith("META-INF/", ignoreCase = true)) return false
    val name = path.substringAfter('/').uppercase(java.util.Locale.ROOT)
    return name.endsWith(".SF") || name.endsWith(".RSA") || name.endsWith(".DSA") ||
        name.endsWith(".EC") || name.startsWith("SIG-")
}

/** Repair known dex2jar JVM metadata issues without changing patch logic. */
internal fun correctTranslatorFrames(bytes: ByteArray): ByteArray {
    val output = ClassWriter(0)
    ClassReader(bytes).accept(object : ClassVisitor(Opcodes.ASM9, output) {
        override fun visit(version: Int, access: Int, name: String, signature: String?,
                           superName: String?, interfaces: Array<out String>?) {
            // Older Android DEX can contain interface static/default methods, but
            // dex2jar emits a Java 6 interface version. Java 8 is required to
            // load those methods even when the translated bytecode is otherwise valid.
            val updatedVersion = if (access and Opcodes.ACC_INTERFACE != 0 && version < Opcodes.V1_8)
                Opcodes.V1_8 else version
            super.visit(updatedVersion, access, name, signature, superName, interfaces)
        }
        override fun visitMethod(access: Int, name: String, descriptor: String, signature: String?,
                                 exceptions: Array<out String>?): MethodVisitor =
            object : MethodVisitor(Opcodes.ASM9, super.visitMethod(access, name, descriptor, signature, exceptions)) {
                override fun visitFrame(type: Int, numLocal: Int, local: Array<out Any>?,
                                        numStack: Int, stack: Array<out Any>?) {
                    fun corrected(values: Array<out Any>?) =
                        values?.map { if (it == "java/util/Object") "java/lang/Object" else it }?.toTypedArray()
                    super.visitFrame(type, numLocal, corrected(local), numStack, corrected(stack))
                }
            }
    }, 0)
    return output.toByteArray()
}
