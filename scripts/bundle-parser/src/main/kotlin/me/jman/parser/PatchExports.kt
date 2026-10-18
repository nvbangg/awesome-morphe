package me.jman.parser

import java.io.File
import java.util.IdentityHashMap
import java.util.jar.JarFile
import kotlinx.serialization.json.*
import org.objectweb.asm.*

internal const val MAX_PATCH_CLASS_BYTES = 8 * 1024 * 1024
private const val MAX_PATCH_CLASSES_TOTAL_BYTES = 256L * 1024 * 1024

/** Bound expanded ZIP class contents before giving a class to ASM. */
internal fun readPatchClass(jar: JarFile, entry: java.util.jar.JarEntry): ByteArray {
    require(entry.size in 1..MAX_PATCH_CLASS_BYTES.toLong()) { "Patch class exceeds inspection budget" }
    return jar.getInputStream(entry).use { input ->
        input.readNBytes(MAX_PATCH_CLASS_BYTES + 1).also {
            require(it.size in 1..MAX_PATCH_CLASS_BYTES) { "Patch class exceeds inspection budget" }
        }
    }
}

internal fun requireJvmPatchClasses(file: File) {
    JarFile(file).use { jar ->
        if (jar.entries().asSequence().none {
            !it.isDirectory && it.name.endsWith(".class") && !it.name.startsWith("META-INF/")
        }) throw IncompletePatchInventory("Bundle contains no loadable JVM patch classes")
    }
}

private data class PatchExport(val owner: String, val member: String, val method: Boolean,
                               val descriptor: String)

/** Enumerate declared JVM patch exports independently of loaders that filter unnamed patches. */
private fun patchExports(file: File, namespace: String): List<PatchExport> {
    val parents = mutableMapOf<String, String?>()
    val members = mutableListOf<Pair<PatchExport, String>>()
    JarFile(file).use { jar ->
        var totalBytes = 0L
        for (entry in jar.entries().asSequence()) {
            if (!entry.name.endsWith(".class") || entry.name.startsWith("META-INF/")) continue
            val bytes = readPatchClass(jar, entry)
            totalBytes += bytes.size
            require(totalBytes <= MAX_PATCH_CLASSES_TOTAL_BYTES) { "Patch classes exceed inspection budget" }
            ClassReader(bytes).accept(object : ClassVisitor(Opcodes.ASM9) {
                    private lateinit var owner: String
                    override fun visit(version: Int, access: Int, name: String, signature: String?,
                                       superName: String?, interfaces: Array<out String>?) {
                        owner = name
                        parents[name] = superName
                    }
                    private fun add(access: Int, name: String, type: Type, method: Boolean,
                                    descriptor: String) {
                        if (access and Opcodes.ACC_PUBLIC != 0 && access and Opcodes.ACC_STATIC != 0 &&
                            type.sort == Type.OBJECT)
                            members += PatchExport(owner.replace('/', '.'), name, method, descriptor) to type.internalName
                    }
                    override fun visitField(access: Int, name: String, descriptor: String,
                                            signature: String?, value: Any?): FieldVisitor? {
                        add(access, name, Type.getType(descriptor), false, descriptor)
                        return null
                    }
                    override fun visitMethod(access: Int, name: String, descriptor: String,
                                             signature: String?, exceptions: Array<out String>?): MethodVisitor? {
                        if (Type.getArgumentTypes(descriptor).isEmpty())
                            add(access, name, Type.getReturnType(descriptor), true, descriptor)
                        return null
                    }
            }, ClassReader.SKIP_CODE or ClassReader.SKIP_DEBUG or ClassReader.SKIP_FRAMES)
        }
    }
    val base = namespace + "/patch/"
    fun patchType(name: String): Boolean {
        var current: String? = name
        val seen = mutableSetOf<String>()
        while (current != null && seen.add(current)) {
            if (current in setOf(base+"Patch", base+"BytecodePatch", base+"ResourcePatch", base+"RawResourcePatch")) return true
            current = parents[current]
        }
        return false
    }
    return members.filter { patchType(it.second) }.map { it.first }
}

internal fun declaredPatchExportCount(file: File, namespace: String): Int = patchExports(file, namespace).size

/** Class-owned exports for comparing JVM/DEX representations of hybrid bundles. */
internal fun declaredPatchExportSignatures(file: File, namespace: String): Map<String, Set<String>> =
    patchExports(file, namespace).groupBy { it.owner.replace('.', '/') + ".class" }
        .mapValues { (_, exports) -> exports.map {
            (if (it.method) "method:" else "field:") + it.member + it.descriptor
        }.toSet() }

internal fun completePatchMetadata(
    file: File, loader: ClassLoader, namespace: String, loaded: List<Any>,
    convert: (Any) -> JsonObject
): JsonArray {
    requireJvmPatchClasses(file)
    val patches = mutableListOf<JsonObject>()
    val labels = IdentityHashMap<Any, String>()
    val exports = patchExports(file, namespace).map { export ->
        try {
            val owner = loader.loadClass(export.owner)
            val patch = if (export.method) owner.getMethod(export.member).invoke(null)
                else owner.getField(export.member).get(null)
            if (patch == null) throw IncompletePatchInventory("Patch export returned null")
            val member = if (export.method && export.member.startsWith("get")) export.member.drop(3) else export.member
            labels.putIfAbsent(patch, member.replace(Regex("([a-z0-9])([A-Z])"), "$1 $2")
                .replaceFirstChar { it.uppercaseChar() })
            patch
        } catch (error: Exception) {
            throw IncompletePatchInventory("Could not inspect " + export.owner + "." + export.member).apply { initCause(error) }
        }
    }
    val rawConverted = IdentityHashMap<Any, JsonObject>()
    fun rawMetadata(patch: Any) = rawConverted.getOrPut(patch) { convert(patch) }
    fun helperMetadata(patch: Any): JsonObject {
        val value = rawMetadata(patch)
        // Only exports excluded by the public loader belong to this separate inventory.
        // A named export omitted by a runtime is an incomplete extraction, not a helper.
        if (!(value["name"] as? JsonPrimitive)?.contentOrNull.isNullOrBlank())
            throw IncompletePatchInventory("Public loader omitted a named patch export")
        return buildJsonObject {
            value.forEach { (key, field) -> put(key, field) }
            put("loader_excluded", true)
            labels[patch]?.let { put("display_name", it) }
        }
    }
    val converted = IdentityHashMap<Any, JsonObject>()
    val unmatchedLoaded = mutableMapOf<JsonObject, ArrayDeque<Int>>()
    for (patch in loaded) {
        if (!converted.containsKey(patch)) {
            val raw = rawMetadata(patch)
            unmatchedLoaded.getOrPut(raw) { ArrayDeque() }.addLast(patches.size)
            if (namespace == "app/morphe/patcher" &&
                (raw["name"] as? JsonPrimitive)?.contentOrNull.isNullOrBlank())
                throw IncompletePatchInventory("Morphe public loader returned a patch without a name")
            converted[patch] = raw
            patches += raw
        }
    }
    // Match raw publisher metadata by occurrence. Getters may return new instances;
    // derived display labels must not turn those instances into duplicate patches.
    val seenExports = IdentityHashMap<Any, Boolean>()
    for (patch in exports) {
        if (seenExports.put(patch, true) != null) continue
        val matches = unmatchedLoaded[rawMetadata(patch)]
        if (!matches.isNullOrEmpty()) matches.removeFirst()
        else if (!converted.containsKey(patch)) patches += helperMetadata(patch)
    }
    return JsonArray(patches)
}
