package me.jman.parser

import java.io.File
import java.net.URI
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger
import kotlin.io.path.createTempDirectory
import kotlin.test.*
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.*

class ExtractionCacheTest {
    private fun isolated(action: (File) -> Unit) {
        val root = createTempDirectory("extraction-cache-").toFile()
        val previous = System.getProperty("catalog.runtime.config")
        val previousManifest = System.getProperty("catalog.runtime.manifest")
        try {
            val config = File(root, "config.json")
            config.writeText("""{"worker":{},"runtimes":[]}""")
            System.setProperty("catalog.runtime.config", config.path)
            val manifest = File(root, "installed.json").apply { writeText("{}") }
            System.setProperty("catalog.runtime.manifest", manifest.path)
            ExtractionCache.clear()
            action(root)
        } finally {
            ExtractionCache.clear()
            if (previous == null) System.clearProperty("catalog.runtime.config")
            else System.setProperty("catalog.runtime.config", previous)
            if (previousManifest == null) System.clearProperty("catalog.runtime.manifest")
            else System.setProperty("catalog.runtime.manifest", previousManifest)
            root.deleteRecursively()
        }
    }

    private val patches = Json.parseToJsonElement("""[{"name":"Cached patch","description":"Old"}]""").jsonArray

    @Test fun verifiedCheckpointAvoidsWorkersOnlyForMatchingDownloadedBytes() = isolated { root ->
        val artifact = File(root, "bundle.rvp").apply { writeText("matching artifact") }
        val list = File(root, "patches.json")
        val content = LocalPatchesFile("v1", patches, PATCH_METADATA_SCHEMA_VERSION)
        list.writeText(Json.encodeToString(content))
        val record = ExtractionRecord("v1", artifact.toURI().toString(), "verified",
            file_hash = sha256(artifact), runtime = "test:patcher:1",
            patch_list_hash = sha256(list), bundle_type = "ReVanced:v22",
            runtime_config_hash = runtimeConfigHash())
        ExtractionCache.seed("ReVanced:v22", record, list, content)
        val hit = extractWithRuntimes(artifact.toURI(), false)
        assertEquals("verified", hit.status)
        assertEquals(patches, hit.patches)
        // Different URL and bytes represent a replaced upstream artifact on a later run.
        val changed = File(root, "changed.rvp").apply { writeText("replacement") }
        assertNotEquals("verified", extractWithRuntimes(changed.toURI(), false).status)
        assertNull(ExtractionCache.get("Morphe:V1", record.file_hash!!))
        assertNull(ExtractionCache.get("ReVanced:v22", record.file_hash, force = true))
    }

    @Test fun corruptStaleAndUnverifiedProofCannotSeedExtraction() = isolated { root ->
        val list = File(root, "list.json")
        val content = LocalPatchesFile("v1", patches, PATCH_METADATA_SCHEMA_VERSION)
        list.writeText(Json.encodeToString(content))
        val good = ExtractionRecord("v1", URI("https://test/bundle.rvp").toString(), "verified",
            file_hash = "a".repeat(64), runtime = "test:patcher:1", patch_list_hash = sha256(list),
            bundle_type = "ReVanced:v22", runtime_config_hash = runtimeConfigHash())
        for (record in listOf(good.copy(status = "fallback"), good.copy(patch_list_hash = "bad"),
            good.copy(bundle_type = "Morphe:V1"))) {
            ExtractionCache.seed("ReVanced:v22", record, list, content)
            assertNull(ExtractionCache.get("ReVanced:v22", good.file_hash!!))
        }
        ExtractionCache.seed("ReVanced:v22", good, list, content.copy(metadata_schema_version = 0))
        assertNull(ExtractionCache.get("ReVanced:v22", good.file_hash!!))
    }

    @Test fun verifiedNonemptyMetadataSurvivesAddingAnotherRuntime() = isolated { root ->
        val list = File(root, "list.json")
        val content = LocalPatchesFile("v1", patches, PATCH_METADATA_SCHEMA_VERSION)
        list.writeText(Json.encodeToString(content))
        val record = ExtractionRecord("v1","https://test/bundle.rvp","verified",
            file_hash = "a".repeat(64), runtime = "test:patcher:1", patch_list_hash = sha256(list),
            bundle_type = "ReVanced:v22", runtime_config_hash = "previous-config")
        ExtractionCache.seed("ReVanced:v22",record,list,content)
        assertNotNull(ExtractionCache.get("ReVanced:v22",record.file_hash!!))
    }

    @Test fun memoryCacheEvictionPreservesRecentResultsAndRejectsOversizedEntries() {
        val cache = RuntimeResultCache(maxEntries = 2, maxBytes = 1024)
        val result = RuntimeResult(patches, "verified", "hash", "runtime")
        cache["one"] = result
        cache["two"] = result
        assertEquals(result, cache["one"])
        cache["three"] = result
        assertNull(cache["two"])
        assertEquals(result, cache["one"])
        val huge = JsonArray(listOf(JsonPrimitive("x".repeat(2000))))
        cache["huge"] = result.copy(patches = huge)
        assertNull(cache["huge"])
        assertEquals(result, cache["one"])
    }

    @Test fun identicalArtifactsShareOneConcurrentExtraction() = isolated {
        val workers = Executors.newFixedThreadPool(4)
        val attempts = AtomicInteger()
        try {
            val futures = (1..20).map {
                workers.submit(java.util.concurrent.Callable {
                    ExtractionCache.withArtifact("ReVanced:v22", "hash") {
                        ExtractionCache.get("ReVanced:v22", "hash") ?: run {
                            attempts.incrementAndGet()
                            Thread.sleep(10)
                            RuntimeResult(patches, "verified", "hash", "runtime").also {
                                ExtractionCache.put("ReVanced:v22", it)
                            }
                        }
                    }
                })
            }
            assertTrue(futures.all { it.get().status == "verified" })
            assertEquals(1, attempts.get())
        } finally { workers.shutdownNow() }
    }
}
