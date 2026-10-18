package me.jman.parser

import java.io.File
import java.security.MessageDigest
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.*

@Serializable
internal data class RuntimeAttempt(val runtime: String, val status: String, val cause: String? = null)

internal fun catalogProjectRoot(): File = when {
    File("src/main/kotlin/me/jman/parser").isDirectory -> File("..").absoluteFile
    File("bundle-parser/src/main/kotlin/me/jman/parser").isDirectory -> File(".").absoluteFile
    else -> System.getProperty("catalog.runtime.config")?.let { File(it).absoluteFile.parentFile.parentFile } ?: File(".")
}
private val activeParserRevision by lazy { parserRevision(catalogProjectRoot()) }
internal fun parserRevision(): String = activeParserRevision

internal fun parserRevision(root: File): String {
    val directory = File(root, "bundle-parser/src/main/kotlin/me/jman/parser")
    val digest = MessageDigest.getInstance("SHA-256")
    directory.listFiles()?.filter { it.isFile && it.extension == "kt" }?.sortedBy { it.name }?.forEach {
        digest.update(it.name.toByteArray(Charsets.UTF_8))
        digest.update(0.toByte())
        digest.update(it.readText(Charsets.UTF_8).replace("\r\n", "\n").toByteArray(Charsets.UTF_8))
    }
    val script = File(root, "scripts/reseam_legacy.py")
    if (script.isFile) digest.update(script.readText(Charsets.UTF_8).replace("\r\n", "\n").toByteArray(Charsets.UTF_8))
    return digest.digest().joinToString("") { "%02x".format(it) }
}

internal fun workerJavaHome(): String =
    System.getProperty("catalog.worker.java_home")?.takeIf(String::isNotBlank)
        ?: System.getenv("CATALOG_WORKER_JAVA_HOME")?.takeIf(String::isNotBlank)
        ?: System.getenv("JAVA_HOME_21_X64")?.takeIf(String::isNotBlank)
        ?: System.getProperty("java.home")

internal fun workerFailure(error: Throwable): Pair<String, String> {
    val chain = generateSequence(error) { it.cause }.take(10).toList()
    val status = when {
        chain.any { it is UnsupportedClassVersionError } -> "runtime_java_incompatible"
        chain.any { it is NoSuchMethodError || it is NoSuchFieldError || it is AbstractMethodError } -> "runtime_incompatible_api"
        chain.any { it is ClassNotFoundException || it is NoClassDefFoundError } -> "runtime_missing_dependency"
        chain.any { it is IncompletePatchInventory } -> "incomplete_patch_inventory"
        else -> "runtime_parsing_failure"
    }
    val missing = chain.filter { it is ClassNotFoundException || it is NoClassDefFoundError }
        .mapNotNull { it.message }.map(::sanitizedWorkerLog).firstOrNull {
            Regex("[A-Za-z_$][A-Za-z0-9_$./]*").matches(it)
        }?.replace('/', '.')
    val cause = chain.joinToString(" <- ") { it.javaClass.simpleName }
    return status to (cause + (missing?.let { " " + it } ?: "")).take(500)
}

internal class IncompletePatchInventory(message: String) : IllegalStateException(message)

internal fun reportWorkerFailure(output: File, error: Throwable) {
    val (status, cause) = workerFailure(error)
    output.writeText(buildJsonObject {
        put("failure_kind", status)
        put("cause", cause)
    }.toString())
    System.err.println("Patcher rejected bundle: " + sanitizedWorkerLog(
        generateSequence(error) { it.cause }.take(8)
            .joinToString(" <- ") { it.javaClass.simpleName + ": " + it.message.orEmpty() }
    ).take(2000))
}
