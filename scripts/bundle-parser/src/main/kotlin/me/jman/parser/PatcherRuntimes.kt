package me.jman.parser

import kotlinx.serialization.Serializable
import kotlinx.serialization.decodeFromString
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import java.io.File
import java.net.URI
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import java.util.jar.JarFile

@Serializable
internal data class WorkerSettings(
    val timeout_seconds: Long = 90, val max_heap: String = "512m", val restart_attempts: Int = 1
)
@Serializable
internal data class RuntimeExecutable(val url: String, val sha256: String)
@Serializable
internal data class RuntimeDefinition(
    val id: String, val family: String, val loader: String, val coordinate: String,
    val dependencies: List<String>, val range: String? = null, val fallback: Boolean = false,
    val executables: Map<String, RuntimeExecutable> = emptyMap(),
    val trust_publisher_for_inspection: Boolean = false
)
@Serializable
internal data class RuntimeConfiguration(
    val worker: WorkerSettings, val runtimes: List<RuntimeDefinition>,
    val extraction_policy_version: Int = 1,
    val bundle_support: List<BundleSupport> = emptyList()
)
@Serializable
internal data class InstalledRuntime(val classpath: String = "", val available: Boolean = false,
                                     val executable: String = "")
@Serializable
internal data class ExtractionRecord(
    val version: String, val download_url: String, val status: String,
    val file_hash: String? = null, val runtime: String? = null,
    val patch_list_hash: String? = null,
    val attempted_at: String? = null, val failure_fingerprint: String? = null,
    val provider_digest: String? = null,
    val terminal: Boolean = false, val bundle_type: String? = null,
    val runtime_config_hash: String? = null, val reseam_bundle: JsonObject? = null,
    val parser_revision: String? = null, val completeness_version: Int = 0,
    val runtime_attempts: List<RuntimeAttempt> = emptyList(),
    val fallback_patch_count: Int? = null
)
internal data class RuntimeResult(val patches: JsonArray?, val status: String,
                                  val hash: String? = null, val runtime: String? = null,
                                  val terminal: Boolean = false, val paused: Boolean = false,
                                  val reseamBundle: JsonObject? = null,
                                  val requiredEngine: String? = null,
                                  val attempts: List<RuntimeAttempt> = emptyList(),
                                  val cause: String? = null,
                                  val completenessVersion: Int = 0,
                                  val embeddedMetadata: EmbeddedPatchMetadata? = null,
                                  val fallbackPatchCount: Int? = null)

private val runtimeJson = Json { ignoreUnknownKeys = true; prettyPrint = true }
private val runtimeResults = RuntimeResultCache()
private val runtimeLocks = Array(64) { Any() }

/** A deliberately bounded range language: whitespace-separated semver comparators. */
internal data class PatcherVersion(val numbers: List<Int>, val prerelease: List<String>) :
    Comparable<PatcherVersion> {
    override fun compareTo(other: PatcherVersion): Int {
        numbers.zip(other.numbers).forEach { (left, right) ->
            if (left != right) return left.compareTo(right)
        }
        if (prerelease.isEmpty() || other.prerelease.isEmpty()) {
            return when {
                prerelease.isEmpty() && other.prerelease.isEmpty() -> 0
                prerelease.isEmpty() -> 1
                else -> -1
            }
        }
        prerelease.zip(other.prerelease).forEach { (left, right) ->
            if (left != right) {
                val l = left.toIntOrNull()
                val r = right.toIntOrNull()
                return when {
                    l != null && r != null -> l.compareTo(r)
                    l != null -> -1
                    r != null -> 1
                    else -> left.compareTo(right)
                }
            }
        }
        return prerelease.size.compareTo(other.prerelease.size)
    }
    companion object {
        fun parse(value: String): PatcherVersion {
            val match = Regex("^(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z.-]+))?(?:\\+[0-9A-Za-z.-]+)?$")
                .matchEntire(value) ?: error("Invalid patcher semantic version")
            val pre = match.groupValues[4].takeIf(String::isNotEmpty)?.split('.') ?: emptyList()
            require(pre.all { it.isNotEmpty() && !(it.all(Char::isDigit) && it.length > 1 && it[0] == '0') })
            return PatcherVersion((1..3).map { match.groupValues[it].toInt() }, pre)
        }
    }
}
internal fun matchesPatcherRange(range: String, version: String): Boolean {
    if (range == "*") return true
    val current = PatcherVersion.parse(version)
    require(range.isNotBlank())
    return range.trim().split(Regex("\\s+")).all { term ->
        val match = Regex("^(>=|<=|>|<|=)?(.+)$").matchEntire(term) ?: error("Invalid range")
        val compared = current.compareTo(PatcherVersion.parse(match.groupValues[2]))
        when (match.groupValues[1]) {
            ">" -> compared > 0
            ">=" -> compared >= 0
            "<" -> compared < 0
            "<=" -> compared <= 0
            "", "=" -> compared == 0
            else -> error("Invalid range comparator")
        }
    }
}

internal fun selectRuntimes(config: RuntimeConfiguration, family: String, declared: String?):
    List<RuntimeDefinition> {
    require(config.runtimes.map { it.id }.distinct().size == config.runtimes.size)
    require(config.worker.timeout_seconds in 1..600)
    require(config.worker.restart_attempts in 0..3)
    require(Regex("^[1-9][0-9]*[mMgG]$").matches(config.worker.max_heap))
    require(config.runtimes.all { it.loader in setOf("revanced-modern", "revanced-legacy",
                                                   "morphe", "revanced-v3", "legacy-bytecode", "reseam", "reseam-jvm") })
    // Family describes the bundle format, not the patcher's Maven major version.
    // After the declared runtime, retry newest to oldest within this format only.
    val candidates = config.runtimes.filter { it.family == family }.sortedWith(
        compareByDescending<RuntimeDefinition> {
            runCatching { PatcherVersion.parse(it.coordinate.substringAfterLast(':')) }.getOrNull()
        }
    )
    val declaration = declared ?: return candidates
    val version = runCatching { PatcherVersion.parse(declaration) }.getOrNull() ?: return candidates
    val exact = candidates.firstOrNull {
        runCatching { PatcherVersion.parse(it.coordinate.substringAfterLast(':')) }.getOrNull() == version
    }
    val preferred = exact ?: if (family == "Morphe:V1") {
        val matches = candidates.filter { it.range?.let { range -> matchesPatcherRange(range, declaration) } == true }
        require(matches.size <= 1) { "Overlapping runtime compatibility ranges" }
        matches.singleOrNull()
    } else null
    return if (preferred == null) candidates else
        listOf(preferred) + candidates.filter { it.id != preferred.id }
}

/** Use the inspector's SDK requirement to avoid launching unrelated historical engines first. */
internal fun prioritizeReseamEngine(candidates: List<RuntimeDefinition>, required: String?): List<RuntimeDefinition> {
    if (required == null) return candidates
    val wanted = if (required.isBlank()) null else {
        runCatching { PatcherVersion.parse(required) }.getOrNull() ?: return candidates
    }
    if (wanted == null || wanted < PatcherVersion.parse("0.8.0")) {
        candidates.firstOrNull { it.loader == "reseam-jvm" }?.let { preferred ->
            return listOf(preferred) + candidates.filter { it.id != preferred.id }
        }
    }
    val versions = candidates.filter { it.family == "Reseam" }.mapNotNull { runtime ->
        runCatching { PatcherVersion.parse(runtime.coordinate.substringAfterLast(':')) }
            .getOrNull()?.let { runtime to it }
    }
    val preferred = if (wanted == null) versions.minByOrNull { it.second }?.first else
        versions.firstOrNull { it.second == wanted }?.first ?: versions.filter { (_, version) ->
            version.numbers.take(2) == wanted.numbers.take(2) && version >= wanted
        }.maxByOrNull { it.second }?.first
    return if (preferred == null) candidates else
        listOf(preferred) + candidates.filter { it.id != preferred.id }
}

private fun loadRuntimeConfiguration(): RuntimeConfiguration {
    val path = System.getProperty("catalog.runtime.config")
        ?: File("..", "config/patcher-runtimes.json").absolutePath
    return runtimeJson.decodeFromString(File(path).readText())
}
private fun installedRuntimes(): Map<String, InstalledRuntime> {
    val path = System.getProperty("catalog.runtime.manifest")
        ?: File("build", "runtime-classpaths.json").absolutePath
    return runtimeJson.decodeFromString(File(path).readText())
}
internal fun sha256(file: File): String {
    val hash = MessageDigest.getInstance("SHA-256")
    file.inputStream().use { input ->
        val buffer = ByteArray(65536)
        while (true) {
            val count = input.read(buffer)
            if (count < 0) break
            hash.update(buffer, 0, count)
        }
    }
    return hash.digest().joinToString("") { "%02x".format(it) }
}

private val diagnosticsGuard = Any()

internal fun sanitizedWorkerLog(text: String, environment: Map<String, String> = System.getenv()): String {
    var safe = text
    environment.filter { (name, _) ->
        Regex("(?i)token|secret|password|credential|access.key").containsMatchIn(name)
    }.values.flatMap { value ->
        val entries = runCatching {
            (runtimeJson.parseToJsonElement(value) as? kotlinx.serialization.json.JsonObject)
                ?.values?.mapNotNull { (it as? kotlinx.serialization.json.JsonPrimitive)?.content }
                ?: emptyList()
        }.getOrDefault(emptyList())
        listOf(value) + entries
    }.filter { it.length >= 4 }.sortedByDescending(String::length)
        .forEach { safe = safe.replace(it, "[redacted]") }
    safe = safe.replace(Regex("(?i)(bearer\\s+|basic\\s+|token[=: ]+|password[=: ]+|secret[=: ]+)[^\\s]+"), "$1[redacted]")
    safe = safe.replace(Regex("https?://[^\\s]+")) { match ->
        runCatching { java.net.URI(match.value).let { uri ->
            java.net.URI(uri.scheme, null, uri.host, uri.port, uri.path, null, null).toString()
        } }.getOrDefault("[redacted URL]")
    }
    return safe.filter { it == '\n' || it == '\t' || it.code >= 32 }.replace("::", ": :")
}

private fun retainWorkerLog(log: File, hash: String, runtime: String) = synchronized(diagnosticsGuard) {
    runCatching {
        val directory = File(System.getProperty("catalog.diagnostics.directory", File(catalogProjectRoot(), "internal/cache/extraction-diagnostics").path))
        directory.mkdirs()
        val tail = java.io.RandomAccessFile(log, "r").use { file ->
            file.seek((file.length() - 65536).coerceAtLeast(0))
            ByteArray((file.length() - file.filePointer).toInt()).also { file.readFully(it) }.toString(Charsets.UTF_8)
        }
        val name = runtime.replace(Regex("[^a-zA-Z0-9_-]"), "_")
        val safe = sanitizedWorkerLog(if (log.length() > 65536) tail.substringAfter('\n', "") else tail)
            .toByteArray(Charsets.UTF_8)
        File(directory, "$hash-$name-${System.nanoTime()}.log").writeBytes(safe.copyOf(minOf(safe.size, 65536)))
        directory.listFiles()?.filter { it.isFile && it.extension == "log" }
            ?.sortedByDescending(File::lastModified)?.drop(100)?.forEach { it.delete() }
    }
    Unit
}

/** Independently implements upstream worker restart/deadline behavior.
 * Reference: https://github.com/brosssh/revanced-external-bundles/blob/3a59398d667c83cd7033f859f3cb59237da92b3f/src/main/kotlin/me/brosssh/bundles/workers/PatchWorkerClient.kt
 */
private fun extractWithRuntime(
    artifact: File, hash: String, runtime: RuntimeDefinition,
    installation: InstalledRuntime, settings: WorkerSettings
): RuntimeResult {
    val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(settings.timeout_seconds)
    var failure = "runtime_initialization_failure"
    for (attempt in 0..settings.restart_attempts) {
        if (System.nanoTime() >= deadline) return RuntimeResult(null, "runtime_timeout", hash)
        val output = File.createTempFile("catalog-result", ".json")
        val log = File.createTempFile("catalog-worker", ".log")
        val workspace = File(output.parentFile, output.name + ".jars")
        var process: Process? = null
        var successful = false
        try {
            val java = File(workerJavaHome(), "bin/java").absolutePath
            // Some patchers use the system loader as parent; isolate one runtime per JVM.
            val builder = if (runtime.loader == "reseam") {
                require(installation.executable.isNotBlank())
                val arguments = mutableListOf(installation.executable, "bundle", "list", artifact.absolutePath, "--json")
                if (runtime.trust_publisher_for_inspection) {
                    reseamSigningKey(artifact)?.let { arguments += listOf("--trust", it) }
                }
                ProcessBuilder(arguments).redirectOutput(output).redirectError(log)
            } else {
                // Repeating a long classpath for unrelated loaders can exceed
                // Windows' process command limit before the worker even starts.
                val property = when (runtime.loader) {
                    "revanced-modern" -> "revanced.patcher22.classpath"
                    "revanced-v3", "revanced-legacy" -> "revanced.patcher21.classpath"
                    "morphe" -> "morphe.patcher.classpath"
                    else -> null
                }
                val command = mutableListOf(java, "-Xmx${settings.max_heap}")
                for (key in listOf("catalog.download.max_bytes", "catalog.download.timeout_seconds"))
                    System.getProperty(key)?.let { command += "-D$key=$it" }
                if (property != null) command += "-D$property=${installation.classpath}"
                command += listOf(
                    "-cp", listOf(System.getProperty("java.class.path"), installation.classpath, artifact.absolutePath)
                        .filter(String::isNotBlank).joinToString(File.pathSeparator),
                    "me.jman.parser.MainKt", "--runtime-worker", runtime.loader,
                    artifact.absolutePath, output.absolutePath
                )
                ProcessBuilder(command).redirectErrorStream(true).redirectOutput(log)
            }
            process = builder.start()
            while (true) {
                val remaining = deadline - System.nanoTime()
                if (remaining <= 0) return RuntimeResult(null, "runtime_timeout", hash)
                if (output.length() > 32L * 1024 * 1024 || log.length() > 1024L * 1024)
                    return RuntimeResult(null, "runtime_output_limit", hash)
                if (process.waitFor(minOf(remaining, TimeUnit.MILLISECONDS.toNanos(200)), TimeUnit.NANOSECONDS)) break
            }
            if (output.length() > 32L * 1024 * 1024 || log.length() > 1024L * 1024)
                return RuntimeResult(null, "runtime_output_limit", hash)
            if (runtime.loader == "reseam" || runtime.loader == "reseam-jvm") {
                // Native startup failures can recover; the JVM adapter uses the
                // worker's explicit rejection exit codes handled below.
                if (process.exitValue() != 0 && runtime.loader == "reseam") continue
                if (process.exitValue() == 0) {
                    if (output.length() > 32L * 1024 * 1024)
                        return RuntimeResult(null, "invalid_patch_metadata", hash, terminal = true)
                    return try {
                        parseReseamInspection(output.readText(), hash, runtime.coordinate).also {
                            successful = it.status == "verified"
                        }
                    } catch (_: Exception) {
                        RuntimeResult(null, "invalid_patch_metadata", hash, terminal = true)
                    }
                }
            }
            when (process.exitValue()) {
                // Explicit responses mean the worker ran and rejected this bundle.
                2 -> {
                    val problem = runCatching { runtimeJson.parseToJsonElement(output.readText()).jsonObject }.getOrNull()
                    val allowed = setOf("runtime_java_incompatible", "runtime_incompatible_api",
                        "runtime_missing_dependency", "incomplete_patch_inventory", "runtime_parsing_failure")
                    val kind = (problem?.get("failure_kind") as? kotlinx.serialization.json.JsonPrimitive)?.content
                        ?.takeIf { it in allowed } ?: "runtime_parsing_failure"
                    val cause = (problem?.get("cause") as? kotlinx.serialization.json.JsonPrimitive)?.content
                        ?.takeIf { Regex("[A-Za-z0-9_$ .<\\-]{1,500}").matches(it) }
                    return RuntimeResult(null, kind, hash, terminal = true, cause = cause)
                }
                3 -> return RuntimeResult(null, "invalid_patch_metadata", hash, terminal = true)
                0 -> {
                    val patches = runtimeJson.decodeFromString<JsonArray>(output.readText())
                    if (!isUsablePatchArray(patches))
                        return RuntimeResult(null, "invalid_patch_metadata", hash, terminal = true)
                    successful = true
                    return RuntimeResult(patches, "verified", hash, runtime.coordinate, completenessVersion = 4)
                }
                else -> failure = "runtime_initialization_failure"
            }
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            return RuntimeResult(null, "runtime_initialization_failure", hash)
        } catch (_: Exception) {
            // Startup/transport failures can recover in a fresh JVM within the same deadline.
            failure = "runtime_initialization_failure"
        } finally {
            if (process?.isAlive == true) {
                process.destroyForcibly()
                try { process.waitFor(5, TimeUnit.SECONDS) }
                catch (_: InterruptedException) { Thread.currentThread().interrupt() }
            }
            if (workspace.exists() && !java.nio.file.Files.isSymbolicLink(workspace.toPath()) &&
                workspace.canonicalFile.parentFile == output.parentFile.canonicalFile)
                workspace.deleteRecursively()
            if (!successful) retainWorkerLog(log, hash, runtime.id)
            output.delete()
            log.delete()
        }
    }
    return RuntimeResult(null, failure, hash)
}

internal fun extractWithRuntimes(
    uri: URI, legacy: Boolean, familyHint: String? = null, previous: ExtractionRecord? = null
): RuntimeResult {
    val hint = canonicalBundleFamily(familyHint)
    val family = when {
        legacy -> "ReVanced:v21"
        hint in setOf("Morphe:V1", "ReVanced:v22", "Reseam") -> hint!!
        uri.path.lowercase().endsWith(".reseam") -> "Reseam"
        uri.path.lowercase().endsWith(".mpp") -> "Morphe:V1"
        uri.path.lowercase().endsWith(".rvp") -> "ReVanced:v22"
        else -> return RuntimeResult(null, "unsupported_format")
    }
    val cacheKey = "$family:$uri"
    return synchronized(runtimeLocks[Math.floorMod(cacheKey.hashCode(), runtimeLocks.size)]) {
        runtimeResults[cacheKey] ?: extractArtifact(uri, family, previous).also {
            if (it.status == "verified") runtimeResults[cacheKey] = it
        }
    }
}

private fun extractArtifact(uri: URI, family: String, previous: ExtractionRecord?): RuntimeResult {
    val artifact = File.createTempFile("catalog-bundle", ".jar")
    return try {
        try {
            downloadToFile(uri.toURL(), artifact)
        } catch (error: Exception) {
            val status = when {
                error is java.net.SocketTimeoutException || error.message == "Bundle download deadline exceeded" -> "artifact_download_timeout"
                error.message == "Bundle exceeds download size limit" -> "artifact_size_limit"
                else -> "artifact_unavailable"
            }
            return RuntimeResult(null, status)
        }
        val hash = sha256(artifact)
        // Still download and hash to detect replacements at unchanged URLs.
        if (previous?.terminal == true && previous.status != "verified" && previous.file_hash == hash &&
            canonicalBundleFamily(previous.bundle_type) == family &&
            previous.failure_fingerprint == runtimeFingerprint()) {
            return RuntimeResult(null, previous.status, hash, terminal = true, paused = true)
        }
        ExtractionCache.withArtifact(family, hash) {
            ExtractionCache.get(family, hash) ?: extractDownloadedArtifact(artifact, hash, family).also {
                ExtractionCache.put(family, it)
            }
        }
    } catch (_: Exception) {
        RuntimeResult(null, "runtime_initialization_failure")
    } finally {
        artifact.delete()
    }
}

private fun extractDownloadedArtifact(artifact: File, hash: String, family: String): RuntimeResult {
    val declared = if (family == "Reseam") null else try {
        JarFile(artifact).use { it.manifest?.mainAttributes?.getValue("Patcher-Version") }
            ?.trim()?.takeIf(String::isNotEmpty)
    } catch (_: Exception) {
        return RuntimeResult(null, "runtime_parsing_failure", hash, terminal = true)
    }
    if (family != "Reseam") {
        try { requireJvmPatchClasses(artifact) }
        catch (_: IncompletePatchInventory) {
            // Root DEX patches can be inspected inside the isolated runtime worker.
            // Extension-only and metadata-only archives still cannot prove an inventory.
            if (!hasRootPatchDex(artifact)) {
                return RuntimeResult(null, "incomplete_patch_inventory", hash, terminal = true,
                    attempts = listOf(RuntimeAttempt("artifact", "incomplete_patch_inventory", "No JVM patch classes")),
                    embeddedMetadata = embeddedPatchMetadata(artifact))
            }
        }
    }
    val config = loadRuntimeConfiguration()
    val candidates = try {
        selectRuntimes(config, family, declared)
    } catch (_: Exception) {
        return RuntimeResult(null, "runtime_configuration_failure", hash, terminal = true)
    }
    if (candidates.isEmpty()) return RuntimeResult(null, "missing_compatible_runtime", hash, terminal = true)
    val support = try { supportArtifacts(config,hash) }
        catch (_: IllegalArgumentException) {
            return RuntimeResult(null,"runtime_configuration_failure",hash,terminal=true)
        } catch (_: Exception) {
            return RuntimeResult(null,"runtime_support_unavailable",hash,
                attempts=listOf(RuntimeAttempt("bundle-support","runtime_support_unavailable")))
        }
    val installed = installedRuntimes()
    var failure = "runtime_initialization_failure"
    var allRejected = true
    val attempts = mutableListOf<RuntimeAttempt>()
    var remaining = candidates
    while (remaining.isNotEmpty()) {
        val runtime = remaining.first()
        remaining = remaining.drop(1)
        val installation = installed[runtime.id]
        if (installation?.available != true) {
            allRejected = false
            attempts += RuntimeAttempt(runtime.coordinate, "runtime_unavailable")
            continue
        }
        val ready = if (support.isEmpty()) installation else installation.copy(
            classpath = (listOf(installation.classpath) + support.map { it.absolutePath })
                .filter(String::isNotBlank).joinToString(File.pathSeparator))
        val result = extractWithRuntime(artifact, hash, runtime, ready, config.worker)
        attempts += RuntimeAttempt(runtime.coordinate, result.status, result.cause)
        if (result.status == "verified") return result.copy(attempts = attempts)
        if (Thread.currentThread().isInterrupted) return result
        if (family == "Reseam") remaining = prioritizeReseamEngine(remaining, result.requiredEngine)
        allRejected = allRejected && result.terminal
        failure = result.status
    }
    return RuntimeResult(null, failure, hash, terminal = allRejected, attempts = attempts,
        embeddedMetadata = if (family == "Reseam") null else embeddedPatchMetadata(artifact))
}

internal fun recordExtraction(
    output: File, list: File, version: String, uri: URI, result: RuntimeResult,
    providerDigest: String? = null, family: String? = null
) {
    val record = ExtractionRecord(version, uri.toString(), result.status, result.hash,
                                  result.runtime, if (result.status == "verified") sha256(list) else null,
                                  java.time.Instant.now().toString(),
                                  if (result.status == "verified") null else runtimeFingerprint(), providerDigest,
                                  result.terminal, family, runtimeConfigHash(), result.reseamBundle,
                                  parserRevision(), result.completenessVersion, result.attempts.take(40), result.fallbackPatchCount)
    atomicWriteText(output, runtimeJson.encodeToString(record) + "\n")
}

internal fun runtimeWorker(args: Array<String>) {
    if (args[1] == "reseam-jvm") {
        try {
            File(args[3]).writeText(inspectLegacyReseam(File(args[2]), File(args[3] + ".jars")).toString())
        } catch (error: Exception) {
            reportWorkerFailure(File(args[3]), error)
            kotlin.system.exitProcess(2)
        } catch (error: LinkageError) {
            reportWorkerFailure(File(args[3]), error)
            kotlin.system.exitProcess(2)
        }
        return
    }
    val patches = try {
        val namespace = when (args[1]) {
            "morphe" -> "app/morphe/patcher"
            "revanced-modern" -> "app/revanced/patcher"
            else -> null
        }
        val artifact = jvmInspectionArtifact(File(args[2]), File(args[3] + ".jars"), namespace)
        val uri = artifact.toURI()
        when (args[1]) {
            "legacy-bytecode" -> parseLegacyPatchBundle(artifact)
            "revanced-v3" -> generateV3PatchList(artifact)
            "revanced-modern" -> runtimeJson.decodeFromString<JsonArray>(generatePatchesFromUrl(uri))
            "revanced-legacy" -> runtimeJson.decodeFromString<JsonArray>(generatePatchesFromUrlWithLegacyPatcher(uri))
            "morphe" -> generateMorphePatchList(uri) ?: error("Morphe runtime rejected bundle")
            else -> error("Unsupported worker loader")
        }
    } catch (error: Exception) {
        reportWorkerFailure(File(args[3]), error)
        kotlin.system.exitProcess(2)
    } catch (error: LinkageError) {
        reportWorkerFailure(File(args[3]), error)
        kotlin.system.exitProcess(2)
    }
    if (!isUsablePatchArray(patches)) kotlin.system.exitProcess(3)
    File(args[3]).writeText(patches.toString())
}

/** Provider SHA-256 hashes invalidate proof when an artifact changes at its URL. */
internal fun matchesProviderDigest(expected: String?, actual: String?, recorded: String? = null): Boolean {
    val normalized = expected?.trim()?.lowercase() ?: return true
    if (normalized.isEmpty()) return true
    val value = normalized.removePrefix("sha256:")
    if (!Regex("[a-f0-9]{64}").matches(value)) return expected == recorded
    return value == actual?.lowercase()
}
