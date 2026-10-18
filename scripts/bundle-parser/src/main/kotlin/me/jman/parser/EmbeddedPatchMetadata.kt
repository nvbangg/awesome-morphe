package me.jman.parser

import java.io.File
import java.util.jar.JarFile
import kotlinx.serialization.json.*

internal data class EmbeddedPatchMetadata(val version: String?, val patches: JsonArray)

/** Published JSON can describe an unsupported archive, but cannot verify its runtime inventory. */
internal fun embeddedPatchMetadata(artifact: File): EmbeddedPatchMetadata? = runCatching {
    JarFile(artifact).use { archive ->
        for (name in listOf("patches-list.json", "patches.json")) {
            val entry = archive.getJarEntry(name) ?: continue
            val maximum = 1024 * 1024
            if (entry.size > maximum) continue
            val bytes = archive.getInputStream(entry).use { it.readNBytes(maximum + 1) }
            if (bytes.size > maximum) continue
            val payload = bytes.toString(Charsets.UTF_8)
            val value = runCatching { Json.parseToJsonElement(payload) }.getOrNull() ?: continue
            val version = (value as? JsonObject)?.get("version")
            if (version != null && (version !is JsonPrimitive || !version.isString)) continue
            val patches = runCatching { convertPatchMetadataPayload(payload) }.getOrNull() ?: continue
            return@use EmbeddedPatchMetadata((version as? JsonPrimitive)?.content, patches)
        }
        null
    }
}.getOrNull()

internal fun embeddedFallbackPatches(metadata: EmbeddedPatchMetadata?, version: String): JsonArray? =
    metadata?.takeIf { it.version == null || versionsMatch(it.version, version) }?.patches
