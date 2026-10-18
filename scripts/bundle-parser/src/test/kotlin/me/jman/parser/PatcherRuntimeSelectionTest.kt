package me.jman.parser

import java.io.File
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.json.Json
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class PatcherRuntimeSelectionTest {
    private fun definition(id: String, family: String, version: String,
                           fallback: Boolean = false, range: String? = null) =
        RuntimeDefinition(id, family, "morphe", "test:runtime:$version", emptyList(), range, fallback)
    private val configuration = RuntimeConfiguration(WorkerSettings(), listOf(
        definition("early", "Morphe:V1", "1.1.1", true, "<=1.2.0"),
        definition("v22", "ReVanced:v22", "22.1.0-dev.1"),
        definition("new", "Morphe:V1", "1.14.1", false, ">1.2.0"),
        definition("v21", "ReVanced:v21", "19.3.1")
    ))

    private fun shipped() = Json.decodeFromString<RuntimeConfiguration>(
        File("../config/patcher-runtimes.json").readText()
    )

    @Test fun shippedReVancedFamiliesKeepTheirOwnNewestFirstFallbacks() {
        val config = shipped().let { it.copy(runtimes = it.runtimes.reversed()) }
        for (declared in listOf(null, "legacy", "19.0.0", "22.1.0-dev.1")) {
            assertEquals(listOf("revanced-v3-19", "revanced-v3-15", "revanced-v3-11", "revanced-v3-bytecode"),
                selectRuntimes(config, "ReVanced:v21", declared).map { it.id })
            assertEquals(listOf("revanced-22", "revanced-21", "revanced-20"),
                selectRuntimes(config, "ReVanced:v22", declared).map { it.id })
        }
    }

    @Test fun shippedMorpheTriesDeclaredRuntimeThenNewestToOldest() {
        val config = shipped()
        val newestFirst = config.runtimes.filter { it.family == "Morphe:V1" }
            .sortedByDescending { PatcherVersion.parse(it.coordinate.substringAfterLast(':')) }
        assertTrue(newestFirst.isNotEmpty())
        for (runtime in newestFirst) {
            assertEquals(listOf(runtime) + newestFirst.filter { it.id != runtime.id },
                selectRuntimes(config, "Morphe:V1", runtime.coordinate.substringAfterLast(':')))
        }
        for (declaration in listOf(null, "", "legacy")) {
            assertEquals(newestFirst, selectRuntimes(config, "Morphe:V1", declaration))
        }
    }

    @Test fun versionOrderIsSemanticAndIndependentOfConfigOrderOrFallbackFlags() {
        val definitions = listOf(
            definition("dev2", "Morphe:V1", "1.14.1-dev.2", true),
            definition("stable", "Morphe:V1", "1.14.1"),
            definition("older", "Morphe:V1", "1.9.0", true),
            definition("dev10", "Morphe:V1", "1.14.1-dev.10"),
            definition("adapter", "Morphe:V1", "bytecode", true)
        )
        for (runtimes in listOf(definitions, definitions.reversed())) {
            assertEquals(listOf("stable", "dev10", "dev2", "older", "adapter"),
                selectRuntimes(configuration.copy(runtimes = runtimes), "Morphe:V1", null).map { it.id })
        }
    }

    @Test fun onlyTheRequestedFormatFamilyCanBeRetried() {
        assertEquals(listOf("new", "early"),
            selectRuntimes(configuration, "Morphe:V1", null).map { it.id })
        assertEquals("v22", selectRuntimes(configuration, "ReVanced:v22", "19.3.1").single().id)
        assertEquals("v21", selectRuntimes(configuration, "ReVanced:v21", "22.1.0").single().id)
        assertTrue(selectRuntimes(configuration, "Unknown:V1", null).isEmpty())
    }

    @Test fun additionalConfiguredVersionsBecomeFirstWithoutChangingSelectionCode() {
        val added = configuration.copy(runtimes = configuration.runtimes +
            definition("future", "Morphe:V1", "2.0.0"))
        assertEquals(listOf("future", "new", "early"),
            selectRuntimes(added, "Morphe:V1", null).map { it.id })
        assertEquals(listOf("early", "future", "new"),
            selectRuntimes(added, "Morphe:V1", "1.1.1").map { it.id })
    }

    @Test fun exactVersionTakesPriorityOverCompatibilityRanges() {
        val overlapping = configuration.copy(runtimes = configuration.runtimes +
            definition("middle", "Morphe:V1", "1.2.0", true, "*"))
        assertEquals(listOf("early", "new", "middle"),
            selectRuntimes(overlapping, "Morphe:V1", "1.1.1").map { it.id })
        assertFailsWith<IllegalArgumentException> {
            selectRuntimes(overlapping, "Morphe:V1", "1.0.0")
        }
    }

    @Test fun declaredReVancedVersionStaysFirstWithinItsFormatFamily() {
        val config = shipped()
        assertEquals(listOf("revanced-v3-15", "revanced-v3-19", "revanced-v3-11", "revanced-v3-bytecode"),
            selectRuntimes(config, "ReVanced:v21", "15.0.3").map { it.id })
        assertEquals(listOf("revanced-20", "revanced-22", "revanced-21"),
            selectRuntimes(config, "ReVanced:v22", "20.0.2").map { it.id })
    }

    @Test fun unmatchedDeclarationStartsWithNewestAndRetainsEveryCandidate() {
        val config = configuration.copy(runtimes = configuration.runtimes.map { it.copy(range = null) })
        for (declared in listOf(null, "legacy", "0.9.0", "9.0.0")) {
            assertEquals(listOf("new", "early"),
                selectRuntimes(config, "Morphe:V1", declared).map { it.id })
        }
    }

    @Test fun shippedReseamStartsWithLatestNativeEngineBeforeHistoricalAdapters() {
        val config = shipped()
        val newestNative = config.runtimes.filter { it.family == "Reseam" && it.loader == "reseam" }
            .maxBy { PatcherVersion.parse(it.coordinate.substringAfterLast(':')) }
        for (runtimes in listOf(config.runtimes, config.runtimes.reversed())) {
            val selected = selectRuntimes(config.copy(runtimes = runtimes), "Reseam", null)
            assertEquals(newestNative.id, selected.first().id)
            assertEquals("reseam-jvm-legacy", selected.last().id)
        }
    }

    @Test fun prereleaseOrderingIsSemantic() {
        assertTrue(matchesPatcherRange(">=21.1.0-dev.5 <22.0.0", "21.1.0-dev.10"))
        assertFalse(matchesPatcherRange(">=21.1.0", "21.1.0-dev.10"))
        assertTrue(matchesPatcherRange("=1.2.0", "1.2.0+build.4"))
        assertFailsWith<IllegalStateException> { matchesPatcherRange(">=1.0.0", "broken") }
    }

    @Test fun wildcardReaderRetainsLegacyManifestDeclarations() {
        assertTrue(matchesPatcherRange("*", "legacy"))
        assertEquals("v21", selectRuntimes(configuration, "ReVanced:v21", "legacy").single().id)
    }
}
