package me.jman.parser

import java.io.File
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.json.*
import kotlin.io.path.createTempDirectory
import kotlin.test.*

class TaggedFallbackMetadataTest {
    private val payload = """[{"name":"Publisher patch","compatiblePackages":[
        {"name":"Example app","packageName":"com.example.app","versions":["1.0"]}]}]"""

    @Test fun unversionedArraysAreAcceptedOnlyAtTheMatchingReleaseTag() {
        val patches = assertNotNull(parseRepositoryPatchListPayload(payload, "0.4.4", "v0.4.4"))
        assertEquals("Publisher patch", patches.single().jsonObject["name"]?.jsonPrimitive?.content)
        assertTrue("com.example.app" in patches.single().jsonObject.getValue("compatiblePackages").jsonObject)
        assertNull(parseRepositoryPatchListPayload(payload, "v0.4.4"))
        assertNull(parseRepositoryPatchListPayload(payload, "v0.4.4", "v0.4.3"))
        assertNull(parseRepositoryPatchListPayload(payload, "v0.4.4", "main"))
        assertNull(parseRepositoryPatchListPayload("""["bad"]""", "v1", "v1"))
    }

    @Test fun explicitVersionsStillNeedToMatchWhenTheTagMatches() {
        val wrapped = """{"version":"v0.4.3","patches":$payload}"""
        assertNull(parseRepositoryPatchListPayload(wrapped, "v0.4.4", "v0.4.4"))
        assertNotNull(parseRepositoryPatchListPayload(wrapped, "v0.4.3"))
    }

    @Test fun productionTaggedListRetainsThePublishersNameAndAppId() {
        val path = System.getenv("CATALOG_TAGGED_FALLBACK_AUDIT") ?: return
        val patches = assertNotNull(parseRepositoryPatchListPayload(File(path).readText(), "v0.4.4", "v0.4.4"))
        assertEquals(1, patches.size)
        val patch = patches.single().jsonObject
        assertEquals("Unlock FirePass Premium", patch.getValue("name").jsonPrimitive.content)
        assertTrue("com.findthefirellc.findthefire" in patch.getValue("compatiblePackages").jsonObject)
    }

    @Test fun recoveredTaggedMetadataIsPersistedWithoutBinaryVerification() {
        val root = createTempDirectory("tagged-fallback-").toFile()
        val folder = File(root, "demo-patch-bundles").apply { mkdir() }
        try {
            File(folder, "demo-latest-patches-bundle.json").writeText(
                """{"version":"v0.4.4","download_url":"https://example.test/patches.mpp","bundle_type":"Morphe:V1"}"""
            )
            processBundle(folder,
                extract = { _, _ -> RuntimeResult(null, "runtime_missing_dependency", "a".repeat(64), terminal = true) },
                fallback = { _, version -> parseRepositoryPatchListPayload(payload, version, "v0.4.4") })
            val record = Json.decodeFromString<ExtractionRecord>(
                File(folder, "demo-latest-extraction.json").readText())
            assertEquals("runtime_missing_dependency", record.status)
            assertEquals(1, record.fallback_patch_count)
            assertNull(record.patch_list_hash)
            val list = Json.decodeFromString<LocalPatchesFile>(
                File(folder, "demo-latest-patches-list.json").readText())
            assertEquals("v0.4.4", list.version)
            assertEquals(1, list.patches.size)
        } finally { root.deleteRecursively() }
    }
}
