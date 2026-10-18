package me.jman.parser

import java.io.File
import java.util.jar.JarEntry
import java.util.jar.JarOutputStream
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.json.*
import kotlin.io.path.createTempDirectory
import kotlin.test.*

class EmbeddedPatchMetadataTest {
    private val payload = """
        {"version":"1.0.1","patches":[{"name":"Camera Looks","compatiblePackages":[
          {"name":"Pixel Camera","packageName":"com.google.android.GoogleCamera",
           "targets":[{"version":"11.0"}]}]}]}
    """.trimIndent()

    private fun archive(file: File, content: String = payload) {
        JarOutputStream(file.outputStream()).use {
            it.putNextEntry(JarEntry("classes.dex"))
            it.write("fixture".toByteArray())
            it.closeEntry()
            it.putNextEntry(JarEntry("patches-list.json"))
            it.write(content.toByteArray())
            it.closeEntry()
        }
    }

    @Test fun unsupportedArchiveKeepsEmbeddedMetadataWithoutVerifyingIt() {
        val root = createTempDirectory("embedded-metadata-").toFile()
        try {
            val artifact = File(root, "pixel.mpp").also { archive(it) }
            val result = extractWithRuntimes(artifact.toURI(), false, "Morphe:V1")
            assertEquals("incomplete_patch_inventory", result.status)
            assertNull(result.patches)
            val metadata = assertNotNull(result.embeddedMetadata)
            assertEquals("1.0.1", metadata.version)
            val patches = assertNotNull(embeddedFallbackPatches(metadata, "v1.0.1"))
            val compatibility = patches.single().jsonObject.getValue("compatiblePackages").jsonObject
            assertEquals(JsonArray(listOf(JsonPrimitive("11.0"))), compatibility["com.google.android.GoogleCamera"])
            assertFalse("Pixel Camera" in compatibility)
            assertNull(embeddedFallbackPatches(metadata, "1.0.0"))
        } finally { root.deleteRecursively() }
    }

    @Test fun fallbackPublicationRetainsFailureStatusAndRejectsDigestMismatch() {
        val root = createTempDirectory("embedded-publication-").toFile()
        try {
            val artifact = File(root, "pixel.mpp").also { archive(it) }
            for (mismatch in listOf(false, true)) {
                val folder = File(root, if (mismatch) "bad-patch-bundles" else "demo-patch-bundles").apply { mkdir() }
                val alias = folder.name.removeSuffix("-patch-bundles")
                val digest = if (mismatch) ",\"provider_digest\":\"sha256:${"b".repeat(64)}\"" else ""
                File(folder, "$alias-latest-patches-bundle.json").writeText(
                    """{"version":"v1.0.1","download_url":"${artifact.toURI()}","bundle_type":"Morphe:V1"$digest}"""
                )
                var fallbacks = 0
                processBundle(folder, fallback = { _, _ -> fallbacks++; null })
                val record = Json.decodeFromString<ExtractionRecord>(
                    File(folder, "$alias-latest-extraction.json").readText())
                assertNull(record.patch_list_hash)
                val output = File(folder, "$alias-latest-patches-list.json")
                if (mismatch) {
                    assertEquals("artifact_digest_mismatch", record.status)
                    assertNull(record.fallback_patch_count)
                    assertFalse(output.exists())
                    assertEquals(1, fallbacks)
                } else {
                    assertEquals("incomplete_patch_inventory", record.status)
                    assertEquals(1, record.fallback_patch_count)
                    assertEquals(0, fallbacks)
                    val list = Json.decodeFromString<LocalPatchesFile>(output.readText())
                    assertEquals("v1.0.1", list.version)
                    assertEquals(1, list.patches.size)
                }
            }
        } finally { root.deleteRecursively() }
    }

    @Test fun malformedAndOversizedEmbeddedListsDoNotStopExtraction() {
        val root = createTempDirectory("embedded-invalid-").toFile()
        try {
            for (content in listOf("{", "[\"invalid\"]", " ".repeat(1024 * 1024 + 1),
                    """{"version":{},"patches":[]}""")) {
                val artifact = File(root, "pixel.mpp").also { archive(it, content) }
                assertNull(embeddedPatchMetadata(artifact))
            }
            val artifact = File(root, "array.mpp").also { archive(it, """[{"name":"Patch"}]""") }
            assertEquals(1, embeddedFallbackPatches(embeddedPatchMetadata(artifact), "v1")?.size)
        } finally { root.deleteRecursively() }
    }

    @Test fun productionPixelCameraArchiveRecoversNamesAndPackageIds() {
        val directory = System.getenv("CATALOG_EMBEDDED_METADATA_AUDIT") ?: return
        val metadata = assertNotNull(embeddedPatchMetadata(File(directory, "pixel101.mpp")))
        val patches = assertNotNull(embeddedFallbackPatches(metadata, "1.0.1"))
        assertTrue(patches.isNotEmpty())
        assertTrue(patches.all {
            "com.google.android.GoogleCamera" in it.jsonObject.getValue("compatiblePackages").jsonObject
        })
    }

    @Test fun currentReseamInspectionMapsItsEntireNativeInventory() {
        val path = System.getenv("CATALOG_RESEAM_026_AUDIT") ?: return
        val payload = File(path).readText()
        val original = Json.parseToJsonElement(payload).jsonObject.getValue("patches").jsonArray
        val result = parseReseamInspection(payload, "hash", "app.reseam:reseam:0.26.0")
        assertEquals("verified", result.status)
        assertEquals(256, original.size)
        assertEquals(original.size, result.patches?.size)
        assertEquals(original.map { it.jsonObject["name"] }, result.patches!!.map { it.jsonObject["name"] })
    }
}
