package me.jman.parser

import java.io.File
import java.util.jar.JarEntry
import java.util.jar.JarOutputStream
import kotlin.io.path.createTempDirectory
import kotlin.test.*
import kotlinx.serialization.json.*

class NonJvmBundleTest {
    @Test fun dexAndMetadataOnlyArchivesCannotBecomeVerifiedEmptyInventories() {
        val root = createTempDirectory("non-jvm-bundle-").toFile()
        try {
            for (entry in listOf("classes.dex", "extensions/classes.dex", "patches-list.json")) {
                val file = File(root, "patches.mpp")
                JarOutputStream(file.outputStream()).use {
                    it.putNextEntry(JarEntry(entry))
                    it.write("fixture".toByteArray())
                    it.closeEntry()
                }
                assertFailsWith<IncompletePatchInventory> {
                    completePatchMetadata(file, javaClass.classLoader, "app/morphe/patcher", emptyList()) {
                        error("No JVM patch should be converted")
                    }
                }
                assertFailsWith<IncompletePatchInventory> { parseLegacyPatchBundle(file) }
            }
        } finally { root.deleteRecursively() }
    }

    @Test fun emptyJvmProofIsRecheckedWithoutInvalidatingHealthyMetadata() {
        val empty = JsonArray(emptyList())
        val nonempty = Json.parseToJsonElement("""[{"name":"Patch"}]""").jsonArray
        for (family in listOf("Morphe:V1", "ReVanced:v21", "ReVanced:v22")) {
            assertFalse(hasCurrentPatchCompleteness(family, empty, 1))
            assertTrue(hasCurrentPatchCompleteness(family, empty, 2))
            assertTrue(hasCurrentPatchCompleteness(family, nonempty, 0))
        }
        assertTrue(hasCurrentPatchCompleteness("Reseam", empty, 1))
    }

    @Test fun releaseFallbackPrefersPatchListOverBundleDescription() {
        val release = Json.parseToJsonElement("""
            {"assets":[
              {"name":"patches-bundle.json","browser_download_url":"https://test/bundle.json"},
              {"name":"patches-list.json","browser_download_url":"https://test/list.json"}
            ]}
        """).jsonObject
        assertEquals("https://test/list.json", findPatchMetadataAsset(release))
        val onlyBundle = buildJsonObject { put("assets", JsonArray(release.getValue("assets").jsonArray.take(1))) }
        assertNull(findPatchMetadataAsset(onlyBundle))
    }

    @Test fun cachedProductionArchivesRecoverDexButRejectMissingImplementations() {
        val directory = System.getenv("CATALOG_NON_JVM_AUDIT") ?: return
        for (name in listOf("dumketo", "anxyis", "pixel100", "pixel101", "ang3lo")) {
            val file = File(directory, "$name.mpp")
            assertTrue(file.isFile, name)
            if (name == "ang3lo") {
                // v0.4.4 publishes JVM patches, but omits a required compatibility class.
                requireJvmPatchClasses(file)
            } else {
                assertFailsWith<IncompletePatchInventory>(name) { requireJvmPatchClasses(file) }
            }
            val result = extractWithRuntimes(file.toURI(), false, "Morphe:V1")
            if (name.startsWith("pixel")) {
                assertEquals("verified", result.status, result.attempts.toString())
                assertEquals(sha256(file), result.hash)
                assertEquals(241, result.patches!!.size, name)
                assertTrue(result.patches.any {
                    it.jsonObject["name"]?.jsonPrimitive?.content == "Camera Looks Backport"
                }, name)
            } else if (name == "ang3lo") {
                assertNull(result.patches)
                assertEquals("runtime_missing_dependency", result.status, result.attempts.toString())
                assertTrue(result.attempts.any { it.cause?.contains("app.template.patches.shared.Constants") == true })
            } else {
                assertEquals("incomplete_patch_inventory", result.status, name)
                assertTrue(result.terminal, name)
                assertEquals(listOf("artifact"), result.attempts.map { it.runtime }, name)
            }
        }
    }
}
