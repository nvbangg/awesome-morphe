package me.jman.parser

import com.android.tools.smali.smali.Smali
import com.android.tools.smali.smali.SmaliOptions
import java.io.File
import java.net.URLClassLoader
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.jar.JarEntry
import java.util.jar.JarFile
import java.util.jar.JarOutputStream
import kotlin.io.path.createTempDirectory
import kotlin.test.*
import kotlinx.serialization.json.*
import org.objectweb.asm.*

class DexPatchBundleTest {
    private fun dex(root: File, name: String, patch: Boolean, stringToken: Boolean = false): File {
        val source = File(root, "$name.smali").apply {
            writeText("""
                .class public Lfixture/$name;
                .super Ljava/lang/Object;
                ${if (stringToken) ".field public static final token:Ljava/lang/String; = \"Ljava/util/Object;\"" else ""}
                ${if (patch) """
                .annotation runtime Lapp/revanced/patcher/patch/annotation/Patch;
                    name = "DEX patch"
                .end annotation
                """ else ""}
                .method public static name-impl(Ljava/lang/Object;)Ljava/lang/Object;
                    .registers 1
                    return-object p0
                .end method
            """.trimIndent())
        }
        val target = File(root, "$name.dex")
        assertTrue(Smali.assemble(SmaliOptions().apply { outputDexFile = target.path }, source.path))
        return target
    }
    private fun archive(file: File, entries: Map<String, ByteArray>): File = file.apply {
        JarOutputStream(outputStream()).use { jar ->
            entries.forEach { (name, bytes) ->
                jar.putNextEntry(JarEntry(name)); jar.write(bytes); jar.closeEntry()
            }
        }
    }

    private fun jvmClass(name: String): ByteArray = ClassWriter(0).apply {
        visit(Opcodes.V1_8, Opcodes.ACC_PUBLIC, "fixture/$name", null, "java/lang/Object", null)
        visitEnd()
    }.toByteArray()

    private fun classWithPatchDependencies(dependencies: List<String>?, priorities: IntArray? = null): ByteArray = ClassWriter(0).apply {
        visit(Opcodes.V1_8, Opcodes.ACC_PUBLIC, "fixture/Annotated", null, "java/lang/Object", null)
        val annotation = visitAnnotation("Lapp/revanced/patcher/patch/annotation/Patch;", true)
        annotation.visit("name", "Annotated")
        if (dependencies != null) {
            val array = annotation.visitArray("dependencies")
            dependencies.forEach { array.visit(null, Type.getObjectType(it)) }
            array.visitEnd()
        }
        priorities?.let { annotation.visit("priorities", it) }
        annotation.visitEnd()
        visitEnd()
    }.toByteArray()

    @Test fun annotationArraysAreComparedInTheirOriginalOrder() {
        val first = classWithPatchDependencies(listOf("fixture/A", "fixture/B"))
        val reordered = classWithPatchDependencies(listOf("fixture/B", "fixture/A"))
        assertNotEquals(patchMetadataSignature(first), patchMetadataSignature(reordered))
        assertEquals(patchMetadataSignature(first), patchMetadataSignature(first.copyOf()))
        assertNotEquals(patchMetadataSignature(classWithPatchDependencies(null)),
            patchMetadataSignature(classWithPatchDependencies(emptyList())))
        assertEquals(patchMetadataSignature(classWithPatchDependencies(emptyList(), intArrayOf(1, 2))),
            patchMetadataSignature(classWithPatchDependencies(emptyList(), intArrayOf(1, 2))))
        assertNotEquals(patchMetadataSignature(classWithPatchDependencies(emptyList(), intArrayOf(1, 2))),
            patchMetadataSignature(classWithPatchDependencies(emptyList(), intArrayOf(2, 1))))
    }

    @Test fun overlappingJvmAndDexClassShapesMustMatch() {
        fun defined(superName: String, interfaces: Array<String> = emptyArray()): ByteArray = ClassWriter(0).apply {
            visit(Opcodes.V1_8, Opcodes.ACC_PUBLIC, "fixture/Shape", null, superName, interfaces)
            visitEnd()
        }.toByteArray()
        val original = defined("java/lang/Object")
        assertTrue(equivalentHybridClassShape(original, defined("java/lang/Object")))
        assertFalse(equivalentHybridClassShape(original, defined("fixture/Other")))
        assertFalse(equivalentHybridClassShape(original, defined("java/lang/Object", arrayOf("java/io/Serializable"))))
    }

    @Test fun patchExportSignaturesIncludeFullReturnTypes() {
        val root = createTempDirectory("patch-typed-exports-").toFile()
        fun patchSubclass(name: String): ByteArray = ClassWriter(0).apply {
            visit(Opcodes.V1_8, Opcodes.ACC_PUBLIC, "fixture/$name", null,
                "app/revanced/patcher/patch/Patch", null)
            visitEnd()
        }.toByteArray()
        fun owner(returnType: String): ByteArray = ClassWriter(0).apply {
            visit(Opcodes.V1_8, Opcodes.ACC_PUBLIC, "fixture/Owner", null, "java/lang/Object", null)
            visitMethod(Opcodes.ACC_PUBLIC or Opcodes.ACC_STATIC, "getPatch", "()Lfixture/$returnType;", null, null)
                .apply { visitCode(); visitInsn(Opcodes.ACONST_NULL); visitInsn(Opcodes.ARETURN); visitMaxs(1, 0); visitEnd() }
            visitEnd()
        }.toByteArray()
        try {
            val shared = mapOf("fixture/BytecodePatch.class" to patchSubclass("BytecodePatch"),
                "fixture/ResourcePatch.class" to patchSubclass("ResourcePatch"))
            val jvm = archive(File(root, "jvm.jar"), shared +
                ("fixture/Owner.class" to owner("BytecodePatch")))
            val dex = archive(File(root, "dex.jar"), shared +
                ("fixture/Owner.class" to owner("ResourcePatch")))
            val namespace = "app/revanced/patcher"
            val jvmExports = declaredPatchExportSignatures(jvm, namespace)
            val dexExports = declaredPatchExportSignatures(dex, namespace)
            assertEquals(1, declaredPatchExportCount(jvm, namespace))
            assertNotEquals(jvmExports, dexExports)
            assertTrue(jvmExports.getValue("fixture/Owner.class").single().contains("BytecodePatch"))
            assertTrue(dexExports.getValue("fixture/Owner.class").single().contains("ResourcePatch"))
        } finally { root.deleteRecursively() }
    }

    @Test fun malformedClassDataCannotPassAsAnIncompleteTranslation() {
        val root = createTempDirectory("malformed-dex-class-").toFile()
        try {
            val bytes = dex(root, "Broken", true).readBytes()
            val data = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
            val classDefinitions = data.getInt(100)
            // Keep the class identity/annotations intact, but point its method
            // data beyond EOF. dex2jar's default reader logs and suppresses this.
            data.putInt(classDefinitions + 24, bytes.size + 16)
            val input = archive(File(root, "broken.mpp"), mapOf("classes.dex" to bytes))
            assertFailsWith<IncompletePatchInventory> {
                jvmInspectionArtifact(input, File(root, "work"))
            }
        } finally { root.deleteRecursively() }
    }

    @Test fun multidexPreservesInventoryResourcesAndKotlinMethodNames() {
        val root = createTempDirectory("dex-patch-").toFile()
        try {
            val first = dex(root, "First", true).readBytes()
            val second = dex(root, "Second", false).readBytes()
            val input = archive(File(root, "patches.mpp"), mapOf(
                "classes.dex" to first, "classes2.dex" to second,
                "fixture/resource.txt" to "preserved".toByteArray()))
            val originalHash = sha256(input)
            val converted = jvmInspectionArtifact(input, File(root, "work"))
            assertEquals(originalHash, sha256(input))
            assertNotEquals(input, converted)
            assertFailsWith<IncompletePatchInventory> {
                jvmInspectionArtifact(input, File(root, "wrong-family"), "app/morphe/patcher")
            }
            JarFile(converted).use {
                assertNotNull(it.getJarEntry("fixture/First.class"))
                assertNotNull(it.getJarEntry("fixture/Second.class"))
                assertEquals("preserved", it.getInputStream(it.getJarEntry("fixture/resource.txt")).reader().readText())
            }
            assertEquals("DEX patch", parseLegacyPatchBundle(converted)[0].jsonObject["name"]!!.jsonPrimitive.content)
            URLClassLoader(arrayOf(converted.toURI().toURL()), javaClass.classLoader).use {
                for (name in listOf("First", "Second")) {
                    val method = it.loadClass("fixture.$name").getMethod("name-impl", Any::class.java)
                    assertEquals("value", method.invoke(null, "value"))
                }
            }
            val duplicate = archive(File(root, "duplicate.mpp"),
                mapOf("classes.dex" to first, "classes2.dex" to first))
            assertFailsWith<IllegalArgumentException> { jvmInspectionArtifact(duplicate, File(root, "duplicate")) }
            val helpers = archive(File(root, "helpers.mpp"), mapOf("classes.dex" to second))
            assertFailsWith<IncompletePatchInventory> { jvmInspectionArtifact(helpers, File(root, "helpers")) }
            val extension = archive(File(root, "extension.mpp"), mapOf("extensions/classes.dex" to first))
            assertFalse(hasRootPatchDex(extension))
            assertFailsWith<IncompletePatchInventory> { jvmInspectionArtifact(extension, File(root, "extension")) }
        } finally { root.deleteRecursively() }
    }

    @Test fun mixedJvmAndDexBundlesIncludeBothWithoutTranslatingUnapprovedDexEntries() {
        val root = createTempDirectory("mixed-dex-patch-").toFile()
        try {
            val patchDex = dex(root, "Patch", true).readBytes()
            val unrelatedDex = dex(root, "Unapproved", true).readBytes()
            val input = archive(File(root, "mixed.mpp"), mapOf(
                "fixture/Helper.class" to jvmClass("Helper"),
                "classes.dex" to patchDex,
                "classes2.dex" to dex(root, "Helper", false).readBytes(),
                "classes-extra.dex" to unrelatedDex,
                "extensions/classes.dex" to unrelatedDex))
            val hash = sha256(input)
            val converted = jvmInspectionArtifact(input, File(root, "converted"))
            assertEquals(hash, sha256(input))
            JarFile(converted).use { jar ->
                assertNotNull(jar.getJarEntry("fixture/Helper.class"))
                assertNotNull(jar.getJarEntry("fixture/Patch.class"))
                assertNull(jar.getJarEntry("fixture/Unapproved.class"))
                assertContentEquals(unrelatedDex,
                    jar.getInputStream(jar.getJarEntry("extensions/classes.dex")).readBytes())
            }
            assertEquals(1, parseLegacyPatchBundle(converted).size)
            val collision = archive(File(root, "collision.mpp"), mapOf(
                "classes.dex" to patchDex, "classes2.dex" to unrelatedDex,
                "fixture/Patch.class" to jvmClass("Patch"),
                "META-INF/EXAMPLE.SF" to "old signature".toByteArray(),
                "META-INF/EXAMPLE.RSA" to "old certificate".toByteArray()))
            assertFailsWith<IncompletePatchInventory> {
                jvmInspectionArtifact(collision, File(root, "collision"))
            }
            val signedResources = archive(File(root, "signed-resources.mpp"), mapOf(
                "classes.dex" to patchDex,
                "META-INF/EXAMPLE.SF" to "old signature".toByteArray(),
                "META-INF/EXAMPLE.RSA" to "old certificate".toByteArray()))
            val unsigned = jvmInspectionArtifact(signedResources, File(root, "signed"))
            JarFile(unsigned).use { jar ->
                assertNull(jar.getJarEntry("META-INF/EXAMPLE.SF"))
                assertNull(jar.getJarEntry("META-INF/EXAMPLE.RSA"))
            }
            val malformed = archive(File(root, "malformed.mpp"), mapOf(
                "fixture/Helper.class" to jvmClass("Helper"),
                "classes.dex" to ByteArray(112) { 1 }))
            assertFailsWith<IncompletePatchInventory> {
                jvmInspectionArtifact(malformed, File(root, "malformed"))
            }
            val compressedOversize = archive(File(root, "expanded.mpp"), mapOf(
                "classes.dex" to patchDex,
                "fixture/Patch.class" to ByteArray(MAX_PATCH_CLASS_BYTES + 1)))
            assertTrue(compressedOversize.length() < 100_000)
            assertFailsWith<IllegalArgumentException> {
                jvmInspectionArtifact(compressedOversize, File(root, "expanded"))
            }
        } finally { root.deleteRecursively() }
    }

    @Test fun productionHybridBundleRetainsJvmClassesAndDexOnlyHelpers() {
        val fixtures = System.getenv("CATALOG_NON_JVM_AUDIT") ?: return
        val source = File(fixtures, "ang3lo043.mpp")
        assertTrue(source.isFile, "Missing ang3lo043.mpp production audit fixture")
        val root = createTempDirectory("production-hybrid-").toFile()
        try {
            val converted = jvmInspectionArtifact(source, File(root, "converted"), "app/morphe/patcher")
            JarFile(source).use { original ->
                JarFile(converted).use { hybrid ->
                    val overlap = "app/template/patches/aaad/premium/AAADPremiumPatchKt.class"
                    assertContentEquals(original.getInputStream(original.getJarEntry(overlap)).readBytes(),
                        hybrid.getInputStream(hybrid.getJarEntry(overlap)).readBytes())
                    assertNotNull(hybrid.getJarEntry("app/template/patches/aaad/premium/AAADPremiumPatchKt\$0.class"))
                    assertTrue(hybrid.entries().asSequence().count { it.name.endsWith(".class") } >
                        original.entries().asSequence().count { it.name.endsWith(".class") })
                }
            }
        } finally { root.deleteRecursively() }
    }

    @Test fun validDexStringConstantCannotBeMistakenForAnInvalidType() {
        val root = createTempDirectory("dex-string-").toFile()
        try {
            val input = archive(File(root, "string.mpp"), mapOf(
                "classes.dex" to dex(root, "Literal", true, stringToken = true).readBytes()))
            val converted = jvmInspectionArtifact(input, File(root, "converted"))
            assertEquals(1, parseLegacyPatchBundle(converted).size)
        } finally { root.deleteRecursively() }
    }

    @Test fun productionDexClassesHaveValidJvmClassFileStructure() {
        val fixtures = System.getenv("CATALOG_NON_JVM_AUDIT") ?: return
        val root = createTempDirectory("production-dex-").toFile()
        try {
            for (version in listOf("pixel100", "pixel101")) {
                val source = File(fixtures, "$version.mpp")
                assertTrue(source.isFile)
                val converted = jvmInspectionArtifact(source, File(root, version))
                URLClassLoader(arrayOf(converted.toURI().toURL()), javaClass.classLoader).use { loader ->
                    JarFile(converted).use { jar ->
                        for (entry in jar.entries().asSequence().filter { it.name.endsWith(".class") }) {
                            try {
                                loader.loadClass(entry.name.removeSuffix(".class").replace('/', '.'))
                            } catch (error: ClassFormatError) {
                                fail("Invalid $version class ${entry.name}: ${error.message}")
                            } catch (_: NoClassDefFoundError) {
                                // Android and patcher dependencies are supplied by the runtime worker.
                            }
                        }
                    }
                }
            }
        } finally { root.deleteRecursively() }
    }

    @Test fun translatorFallbackFramesUseTheRealObjectType() {
        val writer = ClassWriter(0)
        writer.visit(Opcodes.V1_8, Opcodes.ACC_PUBLIC, "fixture/Frames", null, "java/lang/Object", null)
        val method = writer.visitMethod(Opcodes.ACC_PUBLIC or Opcodes.ACC_STATIC, "identity",
            "(Ljava/lang/Object;)Ljava/lang/Object;", null, null)
        method.visitCode()
        val branch = Label()
        method.visitVarInsn(Opcodes.ALOAD, 0); method.visitJumpInsn(Opcodes.IFNONNULL, branch)
        method.visitInsn(Opcodes.ACONST_NULL); method.visitInsn(Opcodes.ARETURN)
        method.visitLabel(branch)
        method.visitFrame(Opcodes.F_FULL, 1, arrayOf("java/util/Object"), 0, emptyArray())
        method.visitVarInsn(Opcodes.ALOAD, 0); method.visitInsn(Opcodes.ARETURN)
        method.visitMaxs(1, 1); method.visitEnd(); writer.visitEnd()
        val fixed = correctTranslatorFrames(writer.toByteArray())
        val loader = object : ClassLoader(javaClass.classLoader) {
            fun load() = defineClass("fixture.Frames", fixed, 0, fixed.size)
        }
        assertEquals("value", loader.load().getMethod("identity", Any::class.java).invoke(null, "value"))
    }

    @Test fun translatedLegacyInterfaceStaticMethodsRequireJava8ClassVersion() {
        val writer = ClassWriter(0)
        writer.visit(Opcodes.V1_6, Opcodes.ACC_PUBLIC or Opcodes.ACC_INTERFACE or Opcodes.ACC_ABSTRACT,
            "fixture/LegacyInterface", null, "java/lang/Object", null)
        val method = writer.visitMethod(
            Opcodes.ACC_PUBLIC or Opcodes.ACC_STATIC or Opcodes.ACC_SYNTHETIC, "value", "()I", null, null)
        method.visitCode()
        method.visitInsn(Opcodes.ICONST_1)
        method.visitInsn(Opcodes.IRETURN)
        method.visitMaxs(1, 0)
        method.visitEnd()
        writer.visitEnd()
        val fixed = correctTranslatorFrames(writer.toByteArray())
        assertEquals(Opcodes.V1_8, ClassReader(fixed).readShort(6).toInt())
        val loader = object : ClassLoader(javaClass.classLoader) {
            fun load() = defineClass("fixture.LegacyInterface", fixed, 0, fixed.size)
        }
        assertEquals(1, (loader.load().getMethod("value").invoke(null) as Number).toInt())
    }
}
