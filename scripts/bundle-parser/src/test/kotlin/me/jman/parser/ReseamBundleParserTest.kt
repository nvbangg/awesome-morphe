package me.jman.parser

import java.io.File
import kotlin.io.path.createTempDirectory
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.json.*
import kotlin.test.*

class ReseamPatchParserTest {
    private fun inspection(patches: String = "[]", problem: String = "null") = """
        {"bundles":[{"name":"patches","author":"Example","description":"Apps",
          "public_key":"${"a".repeat(64)}","problem":$problem}],"patches":$patches}
    """.trimIndent()
    private val patch = """
        {"bundle":"patches","id":"example.ads","name":"Hide ads","description":"Remove ads",
         "hidden":false,"enabled_by_default":true,"dependencies":["patches/example.shared"],
         "compatibility":{"kind":"packages","packages":[
            {"package":"com.example","versions":[]},
            {"package":"com.other","versions":["1.0","2.0"]}]},
         "options":[{"key":"enabled","title":"Enabled","description":"Enable feature",
             "option_type":"bool","default_value":{"type":"bool","value":true},
             "valid_values":null,"required":false}]}
    """.trimIndent()

    @Test fun signedMetadataMapsPackagesOptionsAndPublisher() {
        val result = parseReseamInspection(inspection("[$patch]"), "hash", "runtime")
        assertEquals("verified", result.status)
        assertEquals("a".repeat(64), result.reseamBundle?.get("public_key")?.jsonPrimitive?.content)
        val mapped = result.patches!!.single().jsonObject
        assertEquals("Hide ads", mapped["name"]?.jsonPrimitive?.content)
        val packages = mapped.getValue("compatiblePackages").jsonObject
        assertEquals(JsonNull, packages["com.example"])
        assertEquals(listOf("1.0", "2.0"), packages["com.other"]?.jsonArray?.map { it.jsonPrimitive.content })
        assertEquals(true, mapped["use"]?.jsonPrimitive?.boolean)
        val option = mapped.getValue("options").jsonArray.single().jsonObject
        assertEquals(true, option["default"]?.jsonPrimitive?.boolean)
    }

    @Test fun emptyCatalogAndHiddenDependenciesAreHandled() {
        assertEquals(0, parseReseamInspection(inspection(), "hash", "runtime").patches?.size)
        val hidden = patch.replace("\"hidden\":false", "\"hidden\":true").replace("example.ads", "example.hidden")
        assertEquals(2, parseReseamInspection(inspection("[$patch,$hidden]"), "hash", "runtime").patches?.size)
        val universal = JsonObject(Json.parseToJsonElement(patch).jsonObject +
            ("compatibility" to buildJsonObject { put("kind", "universal") })).toString()
        val mapped = parseReseamInspection(inspection("[$universal]"), "hash", "runtime").patches!!.single()
        assertEquals(JsonNull, mapped.jsonObject["compatiblePackages"])
    }

    @Test fun unnamedLegacyDependenciesRemainInTheVerifiedInventory() {
        val hidden = patch.replace("\"name\":\"Hide ads\"", "\"name\":null")
            .replace("\"description\":\"Remove ads\"", "\"description\":null")
            .replace("\"hidden\":false", "\"hidden\":true")
        val result = parseReseamInspection(inspection("[$hidden]"), "hash", "legacy")
        assertEquals("verified", result.status)
        val mapped = result.patches!!.single().jsonObject
        assertEquals(JsonNull, mapped["name"])
        assertEquals(JsonNull, mapped["description"])
        assertEquals(JsonPrimitive(true), mapped["hidden"])
        assertEquals("Ads", mapped["display_name"]?.jsonPrimitive?.content)
        assertTrue(isUsablePatchArray(result.patches!!))
        assertFails {
            parseReseamInspection(inspection("[" + hidden.replace("\"name\":null", "\"name\":7") + "]"), "hash", "legacy")
        }
    }

    @Test fun technicalReseamInternalNamesGetReadableLabelsWithoutLosingPublishedNames() {
        val original = Json.parseToJsonElement(patch).jsonObject
        val settingsId = "app.reseam.patches.tiktok.core.tiktokSettings"
        val filterId = "app.reseam.patches.tiktok.feed.feedFilter"
        val settings = JsonObject(original + mapOf(
            "id" to JsonPrimitive(settingsId), "name" to JsonPrimitive(settingsId),
            "hidden" to JsonPrimitive(true)))
        val filter = JsonObject(original + mapOf(
            "id" to JsonPrimitive(filterId), "name" to JsonPrimitive(filterId),
            "hidden" to JsonPrimitive(true)))
        val result = parseReseamInspection(inspection("[$settings,$filter]"), "hash", "reseam")
        val patches = result.patches!!.map { it.jsonObject }
        assertEquals(listOf(settingsId, filterId), patches.map { it["name"]?.jsonPrimitive?.content })
        assertEquals(listOf("TikTok Settings", "Feed Filter"),
            patches.map { it["display_name"]?.jsonPrimitive?.content })
        assertEquals(listOf(true, true), patches.map { it["hidden"]?.jsonPrimitive?.boolean })
        val blank = JsonObject(original + mapOf(
            "id" to JsonPrimitive(filterId), "name" to JsonPrimitive("  "),
            "hidden" to JsonPrimitive(true)))
        val blankMapped = parseReseamInspection(inspection("[$blank]"), "hash", "reseam")
            .patches!!.single().jsonObject
        assertEquals("  ", blankMapped["name"]?.jsonPrimitive?.content)
        assertEquals("Feed Filter", blankMapped["display_name"]?.jsonPrimitive?.content)
        val public = parseReseamInspection(inspection("[$patch]"), "hash", "reseam").patches!!.single().jsonObject
        assertEquals("Hide ads", public["name"]?.jsonPrimitive?.content)
        assertNull(public["display_name"])
    }

    @Test fun normalizationOmitsNullDependencyReferencesAndRetainsUnnamedPatches() {
        val original = Json.parseToJsonElement(patch).jsonObject
        val visible = JsonObject(original + ("dependencies" to JsonArray(listOf(
            JsonNull, JsonPrimitive("patches/example.shared@source"), JsonPrimitive("null")
        ))))
        val hidden = JsonObject(original + mapOf(
            "id" to JsonPrimitive("example.shared"), "name" to JsonNull,
            "description" to JsonNull, "hidden" to JsonPrimitive(true),
            "dependencies" to JsonArray(emptyList())
        ))
        val result = parseReseamInspection(inspection("[$visible,$hidden]"), "a".repeat(64), "legacy")
        val root = createTempDirectory("reseam-null-dependencies-").toFile()
        try {
            val folder = File(root, "demo-patch-bundles").apply { mkdir() }
            File(folder, "demo-stable-patches-bundle.json").writeText("""
                {"version":"v1","download_url":"https://example.test/patches.reseam",
                 "bundle_type":"Reseam"}
            """.trimIndent())
            processBundle(folder, extract = { _, _ -> result },
                fallback = { _, _ -> error("Binary extraction should succeed") })
            val output = Json.decodeFromString<LocalPatchesFile>(
                File(folder, "demo-stable-patches-list.json").readText())
            assertEquals(2, output.patches.size)
            assertTrue(output.patches.any { it.jsonObject["name"] == JsonNull })
            val exported = output.patches.single {
                it.jsonObject["name"] == JsonPrimitive("Hide ads")
            }.jsonObject
            // A dependency explicitly named "null" remains a legitimate string.
            assertEquals(listOf("patches/example.shared", "null"),
                exported.getValue("dependencies").jsonArray.map { it.jsonPrimitive.content })
            val record = Json.decodeFromString<ExtractionRecord>(
                File(folder, "demo-stable-extraction.json").readText())
            assertEquals("verified", record.status)
        } finally { root.deleteRecursively() }
    }

    @Test fun failedInspectionIsNeverASuccessfulEmptyCatalog() {
        val rejected = parseReseamInspection(inspection(problem = "{\"kind\":\"invalid_signature\"}"), "hash", "runtime")
        assertEquals("runtime_parsing_failure", rejected.status)
        assertTrue(rejected.terminal)
        assertNull(rejected.patches)
        assertFails { parseReseamInspection("{\"patches\":[]}", "hash", "runtime") }
        assertFails { parseReseamInspection(inspection().replace("a".repeat(64), "bad"), "hash", "runtime") }
    }

    @Test fun engineRequirementReordersRemainingRuntimesWithoutDroppingFallbacks() {
        val config = Json.decodeFromString<RuntimeConfiguration>(
            java.io.File("../config/patcher-runtimes.json").readText())
        val candidates = selectRuntimes(config, "Reseam", null).drop(1)
        val selected = prioritizeReseamEngine(candidates, "0.18.1")
        assertEquals("app.reseam:reseam:0.18.3", selected.first().coordinate)
        assertEquals("app.reseam:reseam:0.12.0",
            prioritizeReseamEngine(candidates, "0.12.0").first().coordinate)
        assertEquals(candidates.map { it.id }.toSet(), selected.map { it.id }.toSet())
        assertEquals(candidates.size, selected.size)
        for (required in listOf("", "0.1.0", "0.7.0")) {
            assertEquals("reseam-jvm", prioritizeReseamEngine(candidates, required).first().loader)
        }
        assertEquals(candidates, prioritizeReseamEngine(candidates, "broken"))
        val problem = """{"type":"bundle_too_old","built":"0.18.1","running":"0.23.1"}"""
        val rejected = parseReseamInspection(inspection(problem = problem), "hash", "runtime")
        assertEquals("0.18.1", rejected.requiredEngine)
        assertNull(rejected.patches)
    }

    @Test fun configuredNativeLoaderAndLegacyFamilyMigration() {
        val config = Json.decodeFromString<RuntimeConfiguration>(
            java.io.File("../config/patcher-runtimes.json").readText())
        val runtimes = selectRuntimes(config, "Reseam", null)
        val native = runtimes.first()
        assertEquals("reseam", native.loader)
        assertEquals(setOf("linux-x64", "windows-x64"), native.executables.keys)
        assertTrue(runtimes.any { it.loader == "reseam-jvm" })
        assertTrue(runtimes.filter { it.loader == "reseam" }.all { "linux-x64" in it.executables })
        for (version in listOf("0.8.1", "0.12.1", "0.16.0", "0.18.3", "0.20.2", "0.22.0")) {
            assertTrue(runtimes.any { it.coordinate == "app.reseam:reseam:$version" })
        }
        assertEquals("ReVanced:v21", canonicalBundleFamily("ReVanced:V3"))
        assertEquals("ReVanced:v22", canonicalBundleFamily("ReVanced:V4"))
        assertEquals("Morphe:V1", canonicalBundleFamily("Morphe:V1"))
        assertEquals("Reseam", canonicalBundleFamily("ReSeam"))
    }
}
