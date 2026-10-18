package me.jman.parser

import kotlinx.serialization.json.*

/** Keep Reseam's stable patch name/id unchanged while labeling unnamed internal helpers. */
internal fun reseamInternalDisplayName(id: String?): String? {
    if (id.isNullOrBlank() || id.length > 512 ||
        !Regex("[A-Za-z0-9_.$/:-]+").matches(id)) return null
    val symbol = id.substringAfterLast('/').substringAfterLast('.').substringAfterLast(':')
    if (symbol.isBlank()) return null
    val words = symbol.replace(Regex("([a-z0-9])([A-Z])"), "$1 $2")
        .replace(Regex("([A-Z])([A-Z][a-z])"), "$1 $2")
        .replace(Regex("[_$-]+"), " ").trim()
    if (words.isEmpty()) return null
    return words.replaceFirstChar { it.uppercaseChar() }
        .replace(Regex("(?i)\\bTik Tok\\b|\\bTiktok\\b"), "TikTok")
        .replace(Regex("(?i)\\bYou Tube\\b|\\bYoutube\\b"), "YouTube")
}

/**
 * Independent adapter for Reseam's published CLI JSON protocol; no upstream code is copied.
 * https://git.reseam.app/reseam/reseam/src/commit/b0f1fcba5f4e681e5526c267eae453242c21ca8f/crates/model/src/sdk.rs
 * https://git.reseam.app/reseam/reseam/src/commit/b0f1fcba5f4e681e5526c267eae453242c21ca8f/crates/model/src/patch.rs
 */
internal fun parseReseamInspection(payload: String, hash: String, runtime: String): RuntimeResult {
    val response = Json.parseToJsonElement(payload).jsonObject
    val bundles = response.getValue("bundles").jsonArray
    require(bundles.size == 1) { "Expected one inspected bundle" }
    val bundle = bundles.single().jsonObject
    if (bundle["problem"] != null && bundle["problem"] != JsonNull) {
        val problem = bundle["problem"] as? JsonObject
        val kind = (problem?.get("type") as? JsonPrimitive)?.contentOrNull
        val required = if (kind in setOf("bundle_too_old", "bundle_too_new", "engine_too_old"))
            (problem?.get("built") as? JsonPrimitive)?.contentOrNull else null
        return RuntimeResult(null, "runtime_parsing_failure", hash, terminal = true, requiredEngine = required,
            cause = kind?.takeIf { Regex("[a-z0-9_]{1,80}").matches(it) })
    }
    fun JsonObject.text(key: String): String {
        val value = getValue(key).jsonPrimitive
        require(value.isString)
        return value.content
    }
    val publisher = buildJsonObject {
        for (key in listOf("name", "author", "description", "public_key"))
            put(key, bundle.text(key))
    }
    require(Regex("[a-fA-F0-9]{64}").matches(publisher.getValue("public_key").jsonPrimitive.content))
    val inventory = response.getValue("patches").jsonArray.map { it.jsonObject }
    val expected = (bundle["patch_count"] as? JsonPrimitive)?.intOrNull
    if (expected != null && expected != inventory.size)
        throw IncompletePatchInventory("Inspector patch count does not match its inventory")
    val ids = inventory.mapNotNull { (it["id"] as? JsonPrimitive)?.contentOrNull }
    if (ids.size != ids.distinct().size)
        throw IncompletePatchInventory("Inspector repeated a patch ID")
    fun JsonObject.patchText(key: String): JsonElement {
        val value = getValue(key)
        require(value == JsonNull || value is JsonPrimitive && value.isString) {
            "Invalid Reseam patch $key"
        }
        return value
    }
    val patches = inventory.map { patch ->
            val name = patch.patchText("name")
            val hidden = patch.getValue("hidden").jsonPrimitive.boolean
            val id = (patch["id"] as? JsonPrimitive)?.takeIf { it.isString }?.contentOrNull
            val officialLabel = (patch["display_name"] as? JsonPrimitive)
                ?.takeIf { it.isString }?.contentOrNull?.takeIf { it.isNotBlank() }
            val publishedName = (name as? JsonPrimitive)?.contentOrNull
            val fallbackLabel = if (hidden && (publishedName.isNullOrBlank() || publishedName == id))
                reseamInternalDisplayName(id) else null
            val compatibility = patch.getValue("compatibility").jsonObject
            val packages = when (compatibility.text("kind")) {
                "universal" -> JsonNull
                "packages" -> compatibilityJson(compatibility.getValue("packages").jsonArray.map {
                    val entry = it.jsonObject
                    val versions = entry.getValue("versions").jsonArray
                    require(versions.all { version -> version is JsonPrimitive && version.isString })
                    entry.text("package") to if (versions.isEmpty()) JsonNull else versions
                })
                else -> error("Unsupported Reseam compatibility")
            }
            buildJsonObject {
                put("name", name)
                (officialLabel ?: fallbackLabel)?.let { put("display_name", it) }
                put("hidden", hidden)
                if (hidden) put("loader_excluded", true)
                put("description", patch.patchText("description"))
                put("use", patch.getValue("enabled_by_default").jsonPrimitive.boolean)
                put("dependencies", patch.getValue("dependencies").jsonArray)
                put("compatiblePackages", packages)
                put("options", JsonArray(patch.getValue("options").jsonArray.map { value ->
                    val option = value.jsonObject
                    buildJsonObject {
                        for (key in listOf("key", "title", "description")) put(key, option.text(key))
                        put("required", option.getValue("required").jsonPrimitive.boolean)
                        put("type", option.text("option_type"))
                        put("default", (option["default_value"] as? JsonObject)?.get("value") ?: JsonNull)
                        val values = option["valid_values"] as? JsonArray
                        put("values", values?.let {
                            buildJsonObject { it.forEach { value -> put(value.jsonPrimitive.content, value) } }
                        } ?: JsonNull)
                    }
                }))
            }
        }
    return RuntimeResult(JsonArray(patches), "verified", hash, runtime, reseamBundle = publisher, completenessVersion = 1)
}

/** Supply an explicit key to older inspectors without changing their global trust store. */
internal fun reseamSigningKey(artifact: java.io.File): String? = runCatching {
    java.util.zip.ZipFile(artifact).use { archive ->
        val entry = archive.getEntry("manifest.pubkey") ?: return@use null
        require(entry.size == 32L)
        archive.getInputStream(entry).use { input ->
            val bytes = input.readNBytes(33)
            require(bytes.size == 32)
            bytes.joinToString("") { "%02x".format(it) }
        }
    }
}.getOrNull()

internal fun canonicalBundleFamily(value: String?): String? = when (value) {
    "ReVanced:V3" -> "ReVanced:v21"
    "ReVanced:V4" -> "ReVanced:v22"
    "ReSeam" -> "Reseam"
    else -> value
}
