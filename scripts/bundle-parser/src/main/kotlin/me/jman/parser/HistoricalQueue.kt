package me.jman.parser

import kotlinx.serialization.decodeFromString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.booleanOrNull
import java.io.File
import java.security.MessageDigest

private val historyJson = Json { ignoreUnknownKeys = true }

/** A changed runtime configuration or availability retries old failures promptly. */
internal fun runtimeFingerprint(): String {
    val files = listOf(
        File(System.getProperty("catalog.runtime.config") ?: "../config/patcher-runtimes.json"),
        File(System.getProperty("catalog.runtime.manifest") ?: "build/runtime-classpaths.json")
    )
    val digest = MessageDigest.getInstance("SHA-256")
    files.forEach { if (it.isFile) digest.update(it.readBytes()) }
    digest.update(parserRevision().toByteArray(Charsets.UTF_8))
    digest.update(workerJavaHome().toByteArray(Charsets.UTF_8))
    return digest.digest().joinToString("") { "%02x".format(it) }
}

internal fun runtimeConfigHash(): String {
    val config = File(System.getProperty("catalog.runtime.config") ?: "../config/patcher-runtimes.json")
    val digest = MessageDigest.getInstance("SHA-256")
    if (config.isFile) digest.update(config.readBytes())
    return digest.digest().joinToString("") { "%02x".format(it) }
}

internal fun pausedFailure(
    record: ExtractionRecord?, version: String?, download: String?, family: String?,
    providerDigest: String?, fingerprint: String
): Boolean = record?.terminal == true && record.status != "verified" && record.file_hash != null &&
    record.version == version && record.download_url == download &&
    canonicalBundleFamily(record.bundle_type) == family && record.failure_fingerprint == fingerprint &&
    matchesProviderDigest(providerDigest, record.file_hash, record.provider_digest)

internal const val DEFAULT_HISTORICAL_BATCH_SIZE = 1000
internal const val MAX_HISTORICAL_BATCH_SIZE = 10000

internal data class HistoricalWork(
    val latest: List<File>, val historical: List<File>, val deferred: Int = 0
)

internal fun historicalCandidates(root: File, limit: Int, fingerprint: String, disabledFolders: Set<String> = emptySet()): List<File> =
    historicalWork(root, limit, fingerprint, disabledFolders).let { it.latest + it.historical }

internal fun historicalWork(root: File, limit: Int, fingerprint: String, disabledFolders: Set<String> = emptySet()): HistoricalWork {
    require(limit in 1..MAX_HISTORICAL_BATCH_SIZE) { "Historical batch size must be between 1 and $MAX_HISTORICAL_BATCH_SIZE" }
    val registry = File(root, "sources.json")
    val settings = if (registry.isFile) {
        historyJson.parseToJsonElement(registry.readText()).jsonObject.values.mapNotNull { item ->
            val obj = item.jsonObject
            obj["cache_path"]?.jsonPrimitive?.contentOrNull?.let {
                File(it).parentFile?.name?.let { folder ->
                    folder to ((obj["is_latest"] as? JsonPrimitive)?.booleanOrNull == true)
                }
            }
        }.toMap()
    } else null
    val active = settings?.keys
    val candidates = root.listFiles()?.filter {
        it.isDirectory && it.name !in disabledFolders && (active == null || it.name in active)
    }?.mapNotNull { folder ->
        val input = folder.listFiles()?.firstOrNull { it.name.endsWith("-patches-bundle.json") }
            ?: return@mapNotNull null
        val stem = input.name.removeSuffix("-patches-bundle.json")
        val record = runCatching {
            historyJson.decodeFromString<ExtractionRecord>(File(folder, "$stem-extraction.json").readText())
        }.getOrNull()
        val patches = File(folder, "$stem-patches-list.json")
        val content = runCatching { historyJson.decodeFromString<LocalPatchesFile>(patches.readText()) }.getOrNull()
        val metadata = runCatching { historyJson.parseToJsonElement(input.readText()).jsonObject }.getOrNull()
        val version = runCatching {
            metadata?.get("version")?.jsonPrimitive?.contentOrNull
                ?: metadata?.get("patches")?.jsonObject?.get("version")?.jsonPrimitive?.contentOrNull
        }.getOrNull()
        val download = runCatching {
            metadata?.get("download_url")?.jsonPrimitive?.contentOrNull
                ?: metadata?.get("patches")?.jsonObject?.get("url")?.jsonPrimitive?.contentOrNull
        }.getOrNull()
        val providerDigest = (metadata?.get("provider_digest") as? JsonPrimitive)?.contentOrNull
        val family = canonicalBundleFamily((metadata?.get("bundle_type") as? JsonPrimitive)?.contentOrNull)
            ?: if (metadata?.get("patches") != null) "ReVanced:v21"
            else if (download?.substringBefore('?')?.endsWith(".reseam", ignoreCase = true) == true) "Reseam"
            else if (download?.substringBefore('?')?.endsWith(".mpp", ignoreCase = true) == true) "Morphe:V1"
            else "ReVanced:v22"
        val verified = record?.status == "verified" &&
            record.file_hash?.matches(Regex("[a-f0-9]{64}")) == true &&
            record.runtime != null && canonicalBundleFamily(record.bundle_type) == family &&
            record.version == version && record.download_url == download &&
            matchesProviderDigest(providerDigest, record.file_hash, record.provider_digest) &&
            content != null && content.version == version && isUsablePatchArray(content.patches) &&
            content.metadata_schema_version == PATCH_METADATA_SCHEMA_VERSION &&
            patches.isFile && record.patch_list_hash == sha256(patches) &&
            hasCurrentPatchCompleteness(family, content.patches, record.completeness_version)
        if (verified || pausedFailure(record, version, download, family,
                providerDigest, fingerprint))
            return@mapNotNull null
        // Never-attempted work and failures under a changed runtime get priority.
        val attempted = if (record?.failure_fingerprint == fingerprint) record.attempted_at else null
        Triple(folder, attempted ?: "", input.name)
    }?.sortedWith(compareBy({ it.second }, { it.third })) ?: emptyList()
    val (latest, historical) = candidates.partition { settings?.get(it.first.name) == true }
    return HistoricalWork(latest.map { it.first }, historical.take(limit).map { it.first },
        (historical.size - limit).coerceAtLeast(0))
}
