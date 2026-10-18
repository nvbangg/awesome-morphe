package me.jman.parser

import java.io.File
import kotlinx.serialization.json.*

/** The parser already visits these lists; collect new app IDs without parsing history twice. */
internal object FreshAppPackages {
    private val packages = mutableMapOf<String, MutableMap<String, MutableSet<Pair<String, String>>>>()
    private val valid = Regex("[A-Za-z][A-Za-z0-9_]*(?:\\.[A-Za-z0-9_]+)+")
    @Synchronized fun reset() { packages.clear(); flush() }
    @Synchronized fun add(folder: String, version: String, download: String, patches: JsonArray) {
        val names = patches.filter { it.jsonObject["loader_excluded"] != JsonPrimitive(true) }.flatMap { patch ->
            when (val compatibility = patch.jsonObject["compatiblePackages"]) {
                is JsonObject -> compatibility.entries.filter { (_, versions) ->
                    versions !is JsonArray || versions.isNotEmpty()
                }.map { it.key }
                is JsonArray -> compatibility.mapNotNull { value ->
                    if (value is JsonPrimitive && value.isString) value.content
                    else (value as? JsonObject)?.let { entry ->
                        val versions = entry["versions"] ?: entry["targets"]
                        if (versions is JsonArray && versions.isEmpty()) null
                        else ((entry["name"] ?: entry["packageName"]) as? JsonPrimitive)?.contentOrNull
                    }
                }
                else -> emptyList()
            }
        }.filter(valid::matches).toSet()
        for (name in names) packages.getOrPut(folder) { mutableMapOf() }
            .getOrPut(name) { mutableSetOf() }.add(version to download)
    }
    @Synchronized fun flush() {
        val file = File(catalogProjectRoot(), "internal/fresh-app-packages.json")
        file.parentFile.mkdirs()
        atomicWriteText(file, buildJsonObject {
            put("folders", buildJsonObject {
                for ((folder, apps) in packages) put(folder, buildJsonObject {
                    for ((name, releases) in apps) put(name, releases.size)
                })
            })
        }.toString())
    }
}
