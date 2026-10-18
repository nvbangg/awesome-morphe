package me.jman.parser

import java.io.File
import java.net.URLClassLoader
import java.util.jar.JarEntry
import java.util.jar.JarOutputStream
import javax.tools.ToolProvider
import kotlin.io.path.createTempDirectory
import kotlin.test.*
import kotlinx.serialization.json.*

class PatchDisplayNameTest {
    @Test fun internalExportsHaveLabelsWhilePublisherNamesAndDistinctPatchesArePreserved() {
        val root = createTempDirectory("patch-display-").toFile()
        try {
            val sources = mapOf(
                "app/morphe/patcher/patch/Patch.java" to """
                    package app.morphe.patcher.patch;
                    public class Patch {
                        public final String name;
                        public Patch(String name) { this.name = name; }
                    }
                """,
                "fixture/Exports.java" to """
                    package fixture;
                    import app.morphe.patcher.patch.Patch;
                    public class Exports {
                        public static final Patch enableAndroidDebuggingPatch = new Patch(null);
                        public static Patch getNamedPatch() { return new Patch("Publisher title"); }
                        public static Patch getOtherInternalPatch() { return new Patch(null); }
                    }
                """
            )
            val files = sources.map { (path,source) ->
                File(root,path).apply { parentFile.mkdirs();writeText(source) }
            }
            val classes = File(root,"classes").apply { mkdir() }
            assertEquals(0,ToolProvider.getSystemJavaCompiler().run(null,null,null,
                "-d",classes.path,*files.map { it.path }.toTypedArray()))
            val jar = File(root,"patches.mpp")
            JarOutputStream(jar.outputStream()).use { output ->
                classes.walkTopDown().filter { it.isFile }.forEach { file ->
                    output.putNextEntry(JarEntry(file.relativeTo(classes).invariantSeparatorsPath))
                    output.write(file.readBytes());output.closeEntry()
                }
            }
            URLClassLoader(arrayOf(jar.toURI().toURL()),ClassLoader.getPlatformClassLoader()).use { loader ->
                val named = loader.loadClass("fixture.Exports").getMethod("getNamedPatch").invoke(null)
                val helper = loader.loadClass("fixture.Exports").getMethod("getOtherInternalPatch").invoke(null)
                val convert: (Any) -> JsonObject = { patch ->
                    buildJsonObject { put("name", (patch.javaClass.getField("name").get(patch) as? String)?.let(::JsonPrimitive) ?: JsonNull) }
                }
                assertFailsWith<IncompletePatchInventory> {
                    completePatchMetadata(jar,loader,"app/morphe/patcher",listOf(named,helper),convert)
                }
                assertFailsWith<IncompletePatchInventory> {
                    completePatchMetadata(jar,loader,"app/morphe/patcher",emptyList(),convert)
                }
                val patches = completePatchMetadata(jar,loader,"app/morphe/patcher",listOf(named)) { patch ->
                    buildJsonObject { put("name", (patch.javaClass.getField("name").get(patch) as? String)?.let(::JsonPrimitive) ?: JsonNull) }
                }.map { it.jsonObject }
                assertEquals(3,patches.size)
                assertEquals("Publisher title",patches.single { it["name"] != JsonNull }["name"]?.jsonPrimitive?.content)
                val helpers = patches.filter { it["name"] == JsonNull }
                assertTrue(helpers.all { it["loader_excluded"] == JsonPrimitive(true) && it["hidden"] == null })
                assertTrue(patches.filter { it["name"] != JsonNull }.all { it["loader_excluded"] == null })
                assertEquals(setOf("Enable Android Debugging Patch","Other Internal Patch"),
                    helpers.map { it.getValue("display_name").jsonPrimitive.content }.toSet())
            }
        } finally { root.deleteRecursively() }
    }

    @Test fun excludedHelpersDoNotTriggerAppEnrichment() {
        val file = File(catalogProjectRoot(),"internal/fresh-app-packages.json")
        val previous = file.takeIf { it.isFile }?.readBytes()
        try {
            FreshAppPackages.reset()
            FreshAppPackages.add("fixture","v1","https://example.test/patches.mpp",
                Json.parseToJsonElement("""[
                    {"name":"Public patch","compatiblePackages":{"com.public.app":null}},
                    {"name":null,"loader_excluded":true,"compatiblePackages":{"com.helper.app":null}},
                    {"name":"Reseam hidden","hidden":true,"compatiblePackages":{"com.reseam.hidden":null}}
                ]""").jsonArray)
            FreshAppPackages.flush()
            val apps = Json.parseToJsonElement(file.readText()).jsonObject
                .getValue("folders").jsonObject.getValue("fixture").jsonObject
            assertEquals(setOf("com.public.app"),apps.keys)
        } finally {
            FreshAppPackages.reset()
            if (previous == null) file.delete() else file.writeBytes(previous)
        }
    }

    @Test fun morpheRepairExpiresOnlyInventoriesWithUnnamedHelpers() {
        val helper = Json.parseToJsonElement("""[{"name":null}]""").jsonArray
        assertFalse(hasCurrentPatchCompleteness("Morphe:V1",helper,2))
        assertFalse(hasCurrentPatchCompleteness("Morphe:V1",helper,3))
        assertFalse(hasCurrentPatchCompleteness("Morphe:V1",helper,4))
        val classified = Json.parseToJsonElement("""[{"name":null,"loader_excluded":true}]""").jsonArray
        assertFalse(hasCurrentPatchCompleteness("Morphe:V1",classified,3))
        assertTrue(hasCurrentPatchCompleteness("Morphe:V1",classified,4))
        assertTrue(hasCurrentPatchCompleteness("Morphe:V1",
            Json.parseToJsonElement("""[{"name":"Named"}]""").jsonArray,0))
        assertTrue(hasCurrentPatchCompleteness("Reseam",helper,1))
    }

    @Test fun officialMorpheSampleKeepsAllNamedPatchesAndLabelsItsInternalHelpers() {
        val path = System.getenv("CATALOG_MORPHE_ARTIFACT") ?: return
        val artifact = File(path)
        assertEquals("1f4b80cf8d8913cbfa5008f8fd4f99326eeed44b0e3f9baccf3e0adc1afff351",sha256(artifact))
        val result = extractWithRuntimes(artifact.toURI(),false,"Morphe:V1")
        assertEquals("verified",result.status,result.attempts.toString())
        val patches = result.patches!!.map { it.jsonObject }
        assertEquals(287,patches.size)
        val helpers = patches.filter { (it["name"] as? JsonPrimitive)?.contentOrNull.isNullOrBlank() }
        assertEquals(106,helpers.size)
        assertTrue(helpers.all { it["loader_excluded"] == JsonPrimitive(true) &&
            !(it["display_name"] as? JsonPrimitive)?.contentOrNull.isNullOrBlank() })
        val public = patches.filter { it["loader_excluded"] != JsonPrimitive(true) }
        assertEquals(181,public.size)
        assertTrue(public.all { !(it["name"] as? JsonPrimitive)?.contentOrNull.isNullOrBlank() })
        assertTrue(public.any { it["name"] == JsonPrimitive("Add to queue") })
        val configuration = Json.parseToJsonElement(File(System.getProperty("catalog.runtime.config")
            ?: "../config/patcher-runtimes.json").readText()).jsonObject
        val runtimeId = configuration.getValue("runtimes").jsonArray.map { it.jsonObject }
            .single { it["coordinate"] == JsonPrimitive(result.runtime) }.getValue("id").jsonPrimitive.content
        val installed = Json.parseToJsonElement(File(System.getProperty("catalog.runtime.manifest")
            ?: "build/runtime-classpaths.json").readText()).jsonObject.getValue(runtimeId).jsonObject
        val probe = createTempDirectory("morphe-public-inventory-").toFile()
        try {
            val source = File(probe,"MorpheLoaderProbe.java").apply { writeText("""
                import java.io.File;
                import java.util.*;
                import java.nio.charset.StandardCharsets;
                public class MorpheLoaderProbe {
                    public static void main(String[] args) throws Exception {
                        var getter = Class.forName("app.morphe.patcher.patch.Patch").getMethod("getName");
                        var patches = (Iterable<?>) Class.forName("app.morphe.patcher.patch.PatchKt")
                            .getMethod("loadPatchesFromJar", Set.class).invoke(null, Set.of(new File(args[0])));
                        for (var patch : patches) System.out.println(Base64.getEncoder().encodeToString(
                            ((String) getter.invoke(patch)).getBytes(StandardCharsets.UTF_8)));
                    }
                }
            """) }
            val output = File(probe,"names.txt")
            val workerHome = System.getenv("CATALOG_WORKER_JAVA_HOME")
                ?: System.getenv("JAVA_HOME_21_X64") ?: System.getProperty("java.home")
            val javaExecutable = File(workerHome,"bin/" + if (System.getProperty("os.name").startsWith("Windows")) "java.exe" else "java")
            val process = ProcessBuilder(javaExecutable.path,"-cp",
                installed.getValue("classpath").jsonPrimitive.content + File.pathSeparator + artifact.absolutePath,
                source.path,artifact.absolutePath).redirectError(File(probe,"errors.txt")).redirectOutput(output).start()
            try {
                assertTrue(process.waitFor(60,java.util.concurrent.TimeUnit.SECONDS),"Upstream inventory timed out")
                assertEquals(0,process.exitValue(),File(probe,"errors.txt").readText())
            } finally { if (process.isAlive) process.destroyForcibly().waitFor() }
            val expected = output.readLines().map { String(java.util.Base64.getDecoder().decode(it),Charsets.UTF_8) }
            assertEquals(expected.groupingBy { it }.eachCount(),
                public.map { it.getValue("name").jsonPrimitive.content }.groupingBy { it }.eachCount())
        } finally { probe.deleteRecursively() }
    }
}
