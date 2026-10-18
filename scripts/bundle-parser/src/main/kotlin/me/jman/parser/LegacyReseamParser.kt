package me.jman.parser

import java.io.File
import java.net.URLClassLoader
import java.security.KeyFactory
import java.security.Signature
import java.security.spec.X509EncodedKeySpec
import java.util.Base64
import java.util.IdentityHashMap
import java.util.concurrent.TimeUnit
import java.util.jar.JarFile
import java.util.zip.ZipFile
import kotlinx.serialization.json.*
import org.objectweb.asm.*

private data class ReseamExport(val owner: String, val name: String, val method: Boolean)

/** Early containers embed their matching JVM SDK, before the native CLI supported JSON inspection. */
internal fun inspectLegacyReseam(artifact: File, workspace: File): JsonObject {
    workspace.mkdirs()
    val script = sequenceOf(File("scripts/reseam_legacy.py"), File("../scripts/reseam_legacy.py"))
        .firstOrNull { it.isFile } ?: error("Legacy Reseam container reader is missing")
    val headerFile = File(workspace, "manifest.json")
    val process = ProcessBuilder(System.getenv("PYTHON") ?: "python", script.absolutePath, artifact.absolutePath)
        .redirectOutput(headerFile).redirectError(File(workspace, "manifest-error.log")).start()
    try {
        require(process.waitFor(15, TimeUnit.SECONDS) && process.exitValue() == 0) {
            "Legacy Reseam container validation failed"
        }
    } finally {
        if (process.isAlive) {
            process.destroyForcibly()
            process.waitFor(5, TimeUnit.SECONDS)
        }
    }
    val header = Json.parseToJsonElement(headerFile.readText()).jsonObject
    val publisher = header.getValue("publisher").jsonObject
    val keyHex = publisher.getValue("public_key").jsonPrimitive.content
    val keyBytes = keyHex.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
    val prefix = byteArrayOf(0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x03, 0x21, 0x00)
    val key = KeyFactory.getInstance("Ed25519").generatePublic(X509EncodedKeySpec(prefix + keyBytes))
    val verifier = Signature.getInstance("Ed25519")
    verifier.initVerify(key)
    verifier.update(Base64.getDecoder().decode(header.getValue("manifest").jsonPrimitive.content))
    require(verifier.verify(Base64.getDecoder().decode(header.getValue("signature").jsonPrimitive.content))) {
        "Legacy Reseam manifest signature is invalid"
    }
    val jars = ZipFile(artifact).use { archive ->
        header.getValue("jars").jsonArray.mapIndexed { index, value ->
            File(workspace, "$index.jar").also { target ->
                archive.getInputStream(archive.getEntry(value.jsonPrimitive.content)).use { input ->
                    target.outputStream().use { output -> input.copyTo(output) }
                }
            }
        }
    }
    val patches = mutableListOf<JsonElement>()
    URLClassLoader(jars.map { it.toURI().toURL() }.toTypedArray(), ClassLoader.getPlatformClassLoader()).use { loader ->
        val oldContext = Thread.currentThread().contextClassLoader
        Thread.currentThread().contextClassLoader = loader
        try {
            val seen = IdentityHashMap<Any, Boolean>()
            val patchType = loader.loadClass("app.reseam.patch.ReseamPatch")
            fun visit(patch: Any, exportLabel: String? = null) {
                require(patchType.isInstance(patch)) { "Invalid legacy Reseam dependency" }
                if (seen.put(patch, true) != null) return
                require(seen.size <= 50000) { "Legacy Reseam patch graph exceeds its budget" }
                patches += legacyReseamPatch(patch, exportLabel)
                for (dependency in patch.property("getDependencies") as Iterable<*>) {
                    if (dependency != null && dependency !is String) visit(dependency)
                }
            }
            for (jar in jars) {
                for (export in reseamExports(jar)) {
                    val owner = loader.loadClass(export.owner)
                    val patch = if (export.method) owner.getDeclaredMethod(export.name).invoke(null)
                        else owner.getDeclaredField(export.name).apply { isAccessible = true }.get(null)
                    require(patch != null) { "Legacy Reseam patch export is null" }
                    visit(patch, export.name.removePrefix("get"))
                }
            }
        } finally { Thread.currentThread().contextClassLoader = oldContext }
    }
    return buildJsonObject {
        put("bundles", JsonArray(listOf(JsonObject(publisher + ("problem" to JsonNull)))))
        put("patches", JsonArray(patches))
    }
}

private fun reseamExports(file: File): List<ReseamExport> {
    val exports = mutableListOf<ReseamExport>()
    JarFile(file).use { jar ->
        var totalClassBytes = 0L
        for (entry in jar.entries().asSequence().filter { it.name.endsWith(".class") &&
            !it.name.startsWith("META-INF/") && !it.name.startsWith("app/reseam/patch/") }) {
            val bytes = readPatchClass(jar, entry)
            totalClassBytes += bytes.size
            require(totalClassBytes <= 128L * 1024 * 1024) { "Legacy Reseam classes exceed inspection budget" }
            ClassReader(bytes).accept(object : ClassVisitor(Opcodes.ASM9) {
                    private lateinit var owner: String
                    override fun visit(version: Int, access: Int, name: String, signature: String?,
                                       superName: String?, interfaces: Array<out String>?) {
                        owner = name.replace('/', '.')
                    }
                    override fun visitField(access: Int, name: String, descriptor: String,
                                            signature: String?, value: Any?): FieldVisitor? {
                        if (access and Opcodes.ACC_STATIC != 0 &&
                            descriptor == "Lapp/reseam/patch/ReseamPatch;")
                            exports += ReseamExport(owner, name, false)
                        return null
                    }
                    override fun visitMethod(access: Int, name: String, descriptor: String,
                                             signature: String?, exceptions: Array<out String>?): MethodVisitor? {
                        if (access and Opcodes.ACC_STATIC != 0 && access and Opcodes.ACC_PUBLIC != 0 &&
                            descriptor == "()Lapp/reseam/patch/ReseamPatch;")
                            exports += ReseamExport(owner, name, true)
                        return null
                    }
            }, ClassReader.SKIP_CODE or ClassReader.SKIP_DEBUG or ClassReader.SKIP_FRAMES)
        }
    }
    return exports.sortedWith(compareBy({ it.owner }, { it.name }, { it.method }))
}

private fun Any.property(name: String): Any? = javaClass.methods.first { it.name == name && it.parameterCount == 0 }
    .apply { isAccessible = true }.invoke(this)
private fun Any.optionalProperty(name: String): Any? =
    javaClass.methods.firstOrNull { it.name == name && it.parameterCount == 0 }?.apply { isAccessible = true }?.invoke(this)
private fun Any?.jsonValue(): JsonElement = when (this) {
    null -> JsonNull
    is Boolean -> JsonPrimitive(this)
    is Number -> JsonPrimitive(this)
    is String -> JsonPrimitive(this)
    is Iterable<*> -> JsonArray(map { it.jsonValue() })
    else -> if (javaClass.name == "app.reseam.patch.OptionPath") property("getPath").jsonValue()
        else error("Unsupported legacy Reseam metadata value: ${javaClass.name}")
}

private fun legacyReseamPatch(patch: Any, exportLabel: String? = null): JsonObject = buildJsonObject {
    val name = patch.property("getName") as? String
    val hidden = patch.optionalProperty("getHidden") as? Boolean ?: false
    put("name", name.jsonValue())
    if (hidden && name.isNullOrBlank()) {
        reseamInternalDisplayName(exportLabel ?: patch.javaClass.simpleName)?.let {
            put("display_name", it)
        }
    }
    put("description", patch.property("getDescription").jsonValue())
    put("hidden", hidden)
    put("enabled_by_default", patch.property("getEnabled").jsonValue())
    put("dependencies", JsonArray((patch.property("getDependencies") as Iterable<*>).map { dependency ->
        if (dependency is String) JsonPrimitive(dependency)
        else requireNotNull(dependency).property("getName").jsonValue()
    }))
    val packages = patch.property("getCompatibleWith") as Iterable<*>
    val compatible = packages.map { item ->
        requireNotNull(item)
        buildJsonObject {
            put("package", item.property("getName").jsonValue())
            put("versions", item.property("getVersions").jsonValue())
        }
    }
    val universal = patch.optionalProperty("getUniversal") as? Boolean ?: compatible.isEmpty()
    put("compatibility", buildJsonObject {
        put("kind", if (universal) "universal" else "packages")
        if (!universal) put("packages", JsonArray(compatible))
    })
    put("options", JsonArray((patch.property("getOptions") as Iterable<*>).map { item ->
        requireNotNull(item)
        val type = (item.optionalProperty("getType") ?: item.property("getKind")).toString()
        val normalized = when (type.lowercase()) {
            "stringlist", "string_list" -> "string_list"
            else -> type.lowercase()
        }
        val default = item.optionalProperty("getDefault") ?: sequenceOf("getDefaultString", "getDefaultBool", "getDefaultInt",
            "getDefaultFloat", "getDefaultStringList").map { item.optionalProperty(it) }.firstOrNull { it != null }
        buildJsonObject {
            put("key", item.property("getKey").jsonValue())
            put("title", item.property("getTitle").jsonValue())
            put("description", item.property("getDescription").jsonValue())
            put("option_type", normalized)
            put("required", item.property("getRequired").jsonValue())
            put("valid_values", item.property("getValidValues").jsonValue())
            put("default_value", if (default == null) JsonNull else buildJsonObject {
                put("type", normalized)
                put("value", default.jsonValue())
            })
        }
    }))
}
