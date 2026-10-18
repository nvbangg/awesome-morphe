package me.jman.parser

import java.io.File
import java.net.URLClassLoader
import java.util.jar.JarEntry
import java.util.jar.JarOutputStream
import javax.tools.ToolProvider
import kotlinx.serialization.json.*
import kotlin.io.path.createTempDirectory
import kotlin.test.*

class PatchExportsTest {
    private fun fixture(
        broken: Boolean = false, identicalHidden: Boolean = false,
        action: (File, ClassLoader) -> Unit
    ) {
        val folder = createTempDirectory("patch-exports").toFile()
        try {
            val sources = mapOf(
                "app/morphe/patcher/patch/Patch.java" to """
                    package app.morphe.patcher.patch;
                    public class Patch {
                        public final String name;
                        public Patch(String name) { this.name = name; }
                    }
                """,
                "example/Exports.java" to """
                    package example;
                    import app.morphe.patcher.patch.Patch;
                    public class Exports {
                        private static final Patch HIDDEN = new Patch(null);
                        private static final Patch SECOND_HIDDEN = new Patch(null);
                        public static Patch getVisible() { return new Patch("Visible"); }
                        public static Patch getHidden() {
                            if ($broken) throw new IllegalStateException("broken export");
                            return HIDDEN;
                        }
                        public static Patch getHiddenAlias() { return HIDDEN; }
                        public static Patch getSecondHidden() {
                            return $identicalHidden ? SECOND_HIDDEN : HIDDEN;
                        }
                    }
                """
            )
            val files = sources.map { (name, source) -> File(folder,name).apply {
                parentFile.mkdirs(); writeText(source)
            } }
            val classes = File(folder,"classes").apply { mkdirs() }
            assertEquals(0, ToolProvider.getSystemJavaCompiler().run(null,null,null,
                "-d",classes.path,*files.map { it.path }.toTypedArray()))
            val jar = File(folder,"patches.mpp")
            JarOutputStream(jar.outputStream()).use { output ->
                classes.walkTopDown().filter { it.isFile }.forEach { file ->
                    output.putNextEntry(JarEntry(file.relativeTo(classes).invariantSeparatorsPath))
                    output.write(file.readBytes()); output.closeEntry()
                }
            }
            URLClassLoader(arrayOf(jar.toURI().toURL()),ClassLoader.getPlatformClassLoader()).use {
                action(jar,it)
            }
        } finally { folder.deleteRecursively() }
    }

    @Test fun unnamedExportsAreRetainedAndAliasesDoNotDuplicatePatches() = fixture { jar, loader ->
        val visible = loader.loadClass("example.Exports").getMethod("getVisible").invoke(null)
        val result = completePatchMetadata(jar,loader,"app/morphe/patcher",listOf(visible)) {
            val name = it.javaClass.getField("name").get(it) as? String
            buildJsonObject { put("name",name?.let(::JsonPrimitive) ?: JsonNull) }
        }
        assertEquals(2,result.size)
        assertTrue(result.any { it.jsonObject["name"] == JsonNull })
    }

    @Test fun distinctPatchesWithIdenticalMetadataKeepTheirInventoryCounts() =
        fixture(identicalHidden = true) { jar, loader ->
            val exports = loader.loadClass("example.Exports")
            val visible = exports.getMethod("getVisible").invoke(null)
            val hidden = exports.getMethod("getHidden").invoke(null)
            val second = exports.getMethod("getSecondHidden").invoke(null)
            assertFailsWith<IncompletePatchInventory> {
                completePatchMetadata(jar,loader,"app/morphe/patcher",listOf(visible,hidden,second)) {
                    val name = it.javaClass.getField("name").get(it) as? String
                    buildJsonObject { put("name",name?.let(::JsonPrimitive) ?: JsonNull) }
                }
            }
            val result = completePatchMetadata(jar, loader, "app/morphe/patcher", listOf(visible)) {
                val name = it.javaClass.getField("name").get(it) as? String
                buildJsonObject { put("name", name?.let(::JsonPrimitive) ?: JsonNull) }
            }
            assertEquals(3, result.size)
            assertEquals(2, result.count { it.jsonObject["loader_excluded"] == JsonPrimitive(true) })
        }

    @Test fun modernExportsCannotBecomeAnEmptyVerifiedLegacyList() = fixture { jar, _ ->
        assertFailsWith<IncompletePatchInventory> { parseLegacyPatchBundle(jar) }
    }

    @Test fun aFailedExportCannotBecomeAVerifiedPartialList() = fixture(true) { jar, loader ->
        assertFailsWith<IncompletePatchInventory> {
            completePatchMetadata(jar,loader,"app/morphe/patcher",emptyList()) {
                buildJsonObject { put("name","Patch") }
            }
        }
    }

    @Test fun parserRevisionIsPortableAndChangesWithAdapterCode() {
        val root = createTempDirectory("parser-revision").toFile()
        try {
            val source = File(root,"bundle-parser/src/main/kotlin/me/jman/parser/Adapter.kt")
            source.parentFile.mkdirs()
            source.writeText("line\r\n")
            val first = parserRevision(root)
            source.writeText("line\n")
            assertEquals(first,parserRevision(root))
            source.writeText("changed\n")
            assertNotEquals(first,parserRevision(root))
        } finally {root.deleteRecursively()}
    }

    @Test fun failuresKeepActionableCategoriesAndCauseTypes() {
        assertEquals("runtime_java_incompatible",workerFailure(UnsupportedClassVersionError("65")).first)
        assertEquals("runtime_incompatible_api",workerFailure(NoSuchMethodError("method")).first)
        assertEquals("runtime_missing_dependency",workerFailure(ClassNotFoundException("missing")).first)
        assertEquals("incomplete_patch_inventory",workerFailure(IncompletePatchInventory("partial")).first)
        val error = IllegalStateException("token=secret",NoSuchFieldError("field"))
        assertFalse(workerFailure(error).second.contains("secret"))
    }
}
