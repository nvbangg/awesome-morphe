package me.jman.parser

import java.io.File
import java.security.KeyPairGenerator
import java.security.MessageDigest
import java.security.Signature
import java.util.jar.JarEntry
import java.util.jar.JarOutputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream
import javax.tools.ToolProvider
import kotlin.io.path.createTempDirectory
import kotlin.test.*
import kotlinx.serialization.json.*

class LegacyReseamParserTest {
    private fun artifact(root: File, tampered: Boolean = false, laterSdk: Boolean = false,
                         empty: Boolean = false, unnamedDependency: Boolean = false,
                         oversizedClass: Boolean = false): File {
        val api = File(root, "src/app/reseam/patch/ReseamPatch.java").apply {
            parentFile.mkdirs()
            writeText("""
                package app.reseam.patch;
                import java.util.List;
                public interface ReseamPatch {
                  String getName(); String getDescription(); boolean getEnabled();
                  List<Object> getCompatibleWith(); List<?> getDependencies(); List<Object> getOptions();
                }
            """.trimIndent())
        }
        val source = File(root, "src/fixture/Patches.java").apply {
            parentFile.mkdirs()
            writeText("""
                package fixture;
                import java.util.List; import app.reseam.patch.ReseamPatch;
                public class Patches {
                  private static final ReseamPatch patch = new Impl();
                  public static ReseamPatch getPatch() { return patch; }
                  private static class Impl implements ReseamPatch {
                    public String getName() { return "Old patch"; }
                    public String getDescription() { return "Historical metadata"; }
                    public boolean getEnabled() { return false; }
                    public List<Object> getCompatibleWith() { return List.of(new Compatible()); }
                    public List<String> getDependencies() { return List.of("Dependency"); }
                    public List<Object> getOptions() { return List.of(new Option()); }
                  }
                  public static class Compatible {
                    public String getName() { return "com.older"; }
                    public List<String> getVersions() { return List.of("1.0"); }
                  }
                  public static class Option {
                    public String getKey() { return "setting"; }
                    public String getTitle() { return "Setting"; }
                    public String getDescription() { return "Old option"; }
                    public String getType() { return "String"; }
                    public String getDefaultString() { return "old-value"; }
                    public List<String> getValidValues() { return List.of("old-value"); }
                    public boolean getRequired() { return false; }
                  }
                }
            """.trimIndent().let { code ->
                if (!empty) code else code
                    .replace("private static final ReseamPatch patch = new Impl();", "")
                    .replace("public static ReseamPatch getPatch() { return patch; }", "")
            }.let { code ->
                if (!laterSdk) code else code
                    .replace("public List<String> getDependencies() { return List.of(\"Dependency\"); }",
                        "public List<ReseamPatch> getDependencies() { return List.of(new Dependency()); }")
                    .replace("public static class Compatible {", """
                        private static class Dependency extends Impl {
                          public String getName() { return "Dependency"; }
                          public boolean getHidden() { return true; }
                          public List<ReseamPatch> getDependencies() { return List.of(); }
                          public List<Object> getOptions() { return List.of(); }
                        }
                        public static class Compatible {
                    """.trimIndent())
                    .replace("getType()", "getKind()")
                    .replace("getDefaultString()", "getDefault()")
            }.let { code ->
                if (!unnamedDependency) code else code.replace(
                    "public String getName() { return \"Dependency\"; }",
                    "public String getName() { return null; }")
            })
        }
        val classes = File(root, "classes").apply { mkdirs() }
        assertEquals(0, ToolProvider.getSystemJavaCompiler().run(null, null, null,
            "-d", classes.path, api.path, source.path))
        val jar = File(root, "patches.jar")
        JarOutputStream(jar.outputStream()).use { output ->
            classes.walkTopDown().filter { it.isFile }.forEach { file ->
                output.putNextEntry(JarEntry(file.relativeTo(classes).invariantSeparatorsPath))
                output.write(file.readBytes())
                output.closeEntry()
            }
            if (oversizedClass) {
                output.putNextEntry(JarEntry("fixture/Oversized.class"))
                output.write(ByteArray(MAX_PATCH_CLASS_BYTES + 1))
                output.closeEntry()
            }
        }
        val hash = MessageDigest.getInstance("SHA-256").digest(jar.readBytes())
            .joinToString("") { "%02x".format(it) }
        val manifest = """
            [bundle]
            name = "fixture"
            author = "Example"
            description = "Old patches"
            format_version = 1
            [files]
            "patches.jar" = "$hash"
        """.trimIndent().toByteArray()
        val keys = KeyPairGenerator.getInstance("Ed25519").generateKeyPair()
        val signature = Signature.getInstance("Ed25519").run {
            initSign(keys.private); update(manifest); sign()
        }
        if (tampered) signature[0] = (signature[0].toInt() xor 1).toByte()
        return File(root, "bundle.reseam").also { file ->
            ZipOutputStream(file.outputStream()).use { zip ->
                for ((name, bytes) in mapOf("manifest.toml" to manifest,
                    "manifest.pubkey" to keys.public.encoded.takeLast(32).toByteArray(),
                    "manifest.sig" to signature, "patches.jar" to jar.readBytes())) {
                    zip.putNextEntry(ZipEntry(name)); zip.write(bytes); zip.closeEntry()
                }
            }
        }
    }

    @Test fun legacySdkExportsAreCompleteAndSigned() {
        val root = createTempDirectory("legacy-reseam-test-").toFile()
        try {
            val file = artifact(root)
            val body = inspectLegacyReseam(file, File(root, "inspection"))
            val result = parseReseamInspection(body.toString(), sha256(file), "builtin:reseam-jvm-inspector:1")
            assertEquals("verified", result.status)
            val patch = result.patches!!.single().jsonObject
            assertEquals("Old patch", patch.getValue("name").jsonPrimitive.content)
            assertFalse(patch.getValue("use").jsonPrimitive.boolean)
            assertEquals(listOf("1.0"), patch.getValue("compatiblePackages").jsonObject
                .getValue("com.older").jsonArray.map { it.jsonPrimitive.content })
            assertEquals("old-value", patch.getValue("options").jsonArray.single().jsonObject
                .getValue("default").jsonPrimitive.content)
        } finally { root.deleteRecursively() }
    }

    @Test fun laterJvmSdkRetainsObjectDependenciesAndGenericOptionDefaults() {
        val root = createTempDirectory("legacy-reseam-later-sdk-").toFile()
        try {
            val file = artifact(root, laterSdk = true)
            val body = inspectLegacyReseam(file, File(root, "inspection"))
            assertEquals(2, body.getValue("patches").jsonArray.size)
            val mapped = parseReseamInspection(body.toString(), sha256(file), "legacy").patches!!
            assertEquals(2, mapped.size)
            val patch = mapped.first { !it.jsonObject.getValue("hidden").jsonPrimitive.boolean }.jsonObject
            assertTrue(mapped.any { it.jsonObject.getValue("hidden").jsonPrimitive.boolean })
            assertEquals(listOf("Dependency"), patch.getValue("dependencies").jsonArray.map { it.jsonPrimitive.content })
            assertEquals("old-value", patch.getValue("options").jsonArray.single().jsonObject
                .getValue("default").jsonPrimitive.content)
        } finally { root.deleteRecursively() }
    }

    @Test fun unnamedLegacyObjectDependenciesReceiveStableInternalLabels() {
        val root = createTempDirectory("legacy-reseam-unnamed-").toFile()
        try {
            val file = artifact(root, laterSdk = true, unnamedDependency = true)
            val inspected = inspectLegacyReseam(file, File(root, "inspection"))
            val patches = parseReseamInspection(inspected.toString(), sha256(file), "legacy").patches!!
            val internal = patches.single { it.jsonObject["hidden"] == JsonPrimitive(true) }.jsonObject
            assertEquals(JsonNull, internal["name"])
            assertEquals("Dependency", internal["display_name"]?.jsonPrimitive?.content)
            assertEquals(2, patches.size)
        } finally { root.deleteRecursively() }
    }

    @Test fun validSignedEmptyBundleProducesVerifiedEmptyPatchList() {
        val root = createTempDirectory("legacy-reseam-empty-").toFile()
        try {
            val file = artifact(root, empty = true)
            val body = inspectLegacyReseam(file, File(root, "inspection"))
            val result = parseReseamInspection(body.toString(), sha256(file), "legacy")
            assertEquals("verified", result.status)
            assertEquals(JsonArray(emptyList()), result.patches)
        } finally { root.deleteRecursively() }
    }

    @Test fun invalidManifestSignatureCannotProduceVerifiedPatches() {
        val root = createTempDirectory("legacy-reseam-tamper-").toFile()
        try {
            assertFails {
                inspectLegacyReseam(artifact(root, true), File(root, "inspection"))
            }
        } finally { root.deleteRecursively() }
    }

    @Test fun signedLegacyJarCannotExpandAnOversizedClassDuringInspection() {
        val root = createTempDirectory("legacy-reseam-oversized-class-").toFile()
        try {
            // The outer container remains small and correctly signed, but the
            // nested JVM ZIP entry expands past the class-inspection limit.
            val file = artifact(root, oversizedClass = true)
            val failure = assertFailsWith<IllegalArgumentException> {
                inspectLegacyReseam(file, File(root, "inspection"))
            }
            assertContains(failure.message.orEmpty(), "Patch class exceeds inspection budget")
        } finally { root.deleteRecursively() }
    }

    @Test fun cachedHistoricalReseamArtifactsAllRetainTheirPatchMetadata() {
        val manifest = System.getenv("CATALOG_RESEAM_AUDIT") ?: return
        val rows = Json.parseToJsonElement(File(manifest).readText()).jsonArray
        assertTrue(rows.isNotEmpty())
        val root = createTempDirectory("historical-reseam-test-").toFile()
        val report = mutableListOf<JsonElement>()
        try {
            for ((index, value) in rows.withIndex()) {
                val row = value.jsonObject
                val status = row.getValue("status").jsonPrimitive.content
                println("Historical Reseam ${row.getValue("version")}: ${row.getValue("url")}")
                val body = if (status == "legacy_jvm_required") {
                    inspectLegacyReseam(File(row.getValue("path").jsonPrimitive.content), File(root, "$index"))
                } else {
                    assertEquals("verified", status, row.getValue("url").jsonPrimitive.content)
                    Json.parseToJsonElement(File(row.getValue("inspection").jsonPrimitive.content).readText()).jsonObject
                }
                val expected = body.getValue("patches").jsonArray.count {
                    it.jsonObject["hidden"]?.jsonPrimitive?.booleanOrNull != true
                }
                if (status == "legacy_jvm_required") {
                    assertEquals(row.getValue("expected_patches").jsonPrimitive.int, expected,
                        row.getValue("url").jsonPrimitive.content)
                }
                val result = parseReseamInspection(body.toString(), "hash", "historical-audit")
                assertEquals("verified", result.status, row.getValue("url").jsonPrimitive.content)
                assertEquals(body.getValue("patches").jsonArray.size, result.patches?.size)
                assertEquals(body.getValue("patches").jsonArray.map { it.jsonObject["name"] },
                    result.patches!!.map { it.jsonObject["name"] }, "Publisher names must pass through unchanged")
                assertTrue(expected > 0)
                report += buildJsonObject {
                    put("url", row.getValue("url")); put("version", row.getValue("version"))
                    put("patches", result.patches!!.size); put("status", "verified")
                }
            }
            File(File(manifest).parentFile, "catalog-results.json").writeText(JsonArray(report).toString())
        } finally { root.deleteRecursively() }
    }
}
