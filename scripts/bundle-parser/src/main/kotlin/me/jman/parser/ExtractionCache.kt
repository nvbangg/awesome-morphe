package me.jman.parser

import java.io.File
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull

/** Repair mixed Morphe public/helper inventories; retain healthy named checkpoints. */
internal fun hasCurrentPatchCompleteness(family: String, patches: JsonArray, version: Int): Boolean {
    if (family == "Morphe:V1" && patches.any {
        val patch = it as? JsonObject
        (patch?.get("name") as? JsonPrimitive)?.contentOrNull.isNullOrBlank() &&
            patch?.get("loader_excluded") != JsonPrimitive(true)
    }) return false
    return version >= when {
        family == "Reseam" -> 1
        family == "Morphe:V1" && patches.any {
            ((it as? JsonObject)?.get("name") as? JsonPrimitive)?.contentOrNull.isNullOrBlank()
        } -> 4
        patches.isEmpty() -> 2
        else -> 0
    }
}

/** Bound retained JSON as well as entry count; eviction only causes normal extraction. */
internal class RuntimeResultCache(
    private val maxEntries: Int = 128, private val maxBytes: Long = 16L * 1024 * 1024
) {
    private val entries = LinkedHashMap<String, Pair<RuntimeResult, Long>>(16, 0.75f, true)
    private var bytes = 0L
    @Synchronized operator fun get(key: String): RuntimeResult? = entries[key]?.first
    @Synchronized operator fun set(key: String, result: RuntimeResult) {
        val weight = 256L + 2L * (result.patches?.toString()?.length ?: 0) +
            2L * (result.reseamBundle?.toString()?.length ?: 0) +
            result.attempts.sumOf { 128L + 2L * (it.runtime.length + it.status.length + (it.cause?.length ?: 0)) }
        entries.remove(key)?.let { bytes -= it.second }
        if (weight > maxBytes) return
        entries[key] = result to weight
        bytes += weight
        while (entries.size > maxEntries || bytes > maxBytes) {
            val oldest = entries.entries.iterator().next()
            bytes -= oldest.value.second
            entries.remove(oldest.key)
        }
    }
    @Synchronized fun clear() { entries.clear(); bytes = 0 }
}

/** Successful metadata remains owned by its source's existing checkpoint files. */
internal object ExtractionCache {
    private val results = RuntimeResultCache()
    private val locks = Array(64) { Any() }
    private fun key(family: String, hash: String) =
        "$family:$hash:${PATCH_METADATA_SCHEMA_VERSION}:${runtimeConfigHash()}"

    fun <T> withArtifact(family: String, hash: String, action: () -> T): T =
        synchronized(locks[Math.floorMod(key(family, hash).hashCode(), locks.size)]) { action() }

    fun get(family: String, hash: String,
            force: Boolean = System.getenv("CATALOG_FORCE") == "true"): RuntimeResult? =
        if (force) null else results[key(family, hash)]

    fun put(family: String, result: RuntimeResult) {
        if (result.status == "verified" && result.hash != null && result.runtime != null &&
            result.patches != null && isUsablePatchArray(result.patches))
            results[key(family, result.hash)] = result
    }

    fun seed(family: String, record: ExtractionRecord?, list: File, content: LocalPatchesFile?) {
        if (System.getenv("CATALOG_FORCE") == "true" || record?.status != "verified" ||
            record.file_hash == null || record.runtime == null ||
            canonicalBundleFamily(record.bundle_type) != family ||

            content == null || content.version != record.version ||
            content.metadata_schema_version != PATCH_METADATA_SCHEMA_VERSION ||
            !isUsablePatchArray(content.patches) ||
            !hasCurrentPatchCompleteness(family, content.patches, record.completeness_version) || !list.isFile ||
            record.patch_list_hash != sha256(list)) return
        put(family, RuntimeResult(content.patches, "verified", record.file_hash, record.runtime,
            reseamBundle = record.reseam_bundle, completenessVersion = record.completeness_version))
    }

    internal fun clear() = results.clear()
}
