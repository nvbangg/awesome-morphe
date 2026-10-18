package me.jman.parser

import java.io.File
import java.io.IOException
import java.util.concurrent.ConcurrentLinkedQueue
import java.util.jar.JarFile
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.*

private const val LOCAL_EXTRACTION_WORKERS = 2
private val MANIFEST_VERSION_ATTRIBUTES = listOf("Version", "Bundle-Version", "Implementation-Version")
private val localPatchesJson = Json { prettyPrint = true }

internal fun processLocalBundles(targetsFile: File) {
    val outputDirectory = File("../../data/patches")
    val reportFile = File("parsed_files.txt")
    val targets = targetsFile.readLines().map(String::trim).filter(String::isNotEmpty).map(::File)
    check(outputDirectory.isDirectory || outputDirectory.mkdirs()) { "Cannot create $outputDirectory" }
    val successfulFiles = ConcurrentLinkedQueue<String>()
    val writeFailures = ConcurrentLinkedQueue<IOException>()
    processDirectories(targets, LOCAL_EXTRACTION_WORKERS, process = { target ->
        val outputName = target.nameWithoutExtension + ".json"
        if (!target.isFile || !target.extension.equals("mpp", ignoreCase = true)) {
            Logger.warning("${target.name}: Local Morphe bundle was not found")
        } else {
            val result = extractWithRuntimes(target.toURI(), false, "Morphe:V1")
            val patches = result.patches?.let(::publicMorphePatches)
            if (result.status != "verified" || patches.isNullOrEmpty()) {
                val reason = if (result.status == "verified") "No patches found" else result.status
                Logger.warning("${target.name}: $reason")
            } else {
                try {
                    val version = JarFile(target).use { archive ->
                        MANIFEST_VERSION_ATTRIBUTES.firstNotNullOfOrNull { name ->
                            archive.manifest?.mainAttributes?.getValue(name)?.trim()?.takeIf(String::isNotEmpty)
                        }.orEmpty()
                    }
                    val payload = buildJsonObject {
                        put("version", JsonPrimitive(version))
                        put("patches", patches)
                    }
                    atomicWriteText(File(outputDirectory, outputName), localPatchesJson.encodeToString(payload))
                    successfulFiles.add(outputName)
                    Logger.info("${target.name}: Parsed successfully")
                } catch (error: IOException) {
                    writeFailures.add(error)
                    throw error
                }
            }
        }
    })
    writeFailures.firstOrNull()?.let { throw it }
    atomicWriteText(reportFile, successfulFiles.sorted().joinToString("\n"))
    Logger.info("Parsed ${successfulFiles.size}/${targets.size} bundles successfully.")
}

private fun publicMorphePatches(patches: JsonArray): JsonArray = JsonArray(
    patches.map { it.jsonObject }
        .filter { it["loader_excluded"] != JsonPrimitive(true) }
        .sortedBy { it.getValue("name").jsonPrimitive.content }
        .map { patch ->
            buildJsonObject {
                put("name", patch.getValue("name"))
                put("description", patch.getValue("description"))
                put("default", patch.getValue("use"))
                put("category", patch.getValue("category"))
                put("compatiblePackages", patch.getValue("compatiblePackages"))
                put("options", patch.getValue("options"))
            }
        }
)
