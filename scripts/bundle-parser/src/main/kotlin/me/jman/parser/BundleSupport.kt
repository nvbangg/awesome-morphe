package me.jman.parser

import java.io.File
import java.io.IOException
import java.net.URL
import kotlinx.serialization.Serializable

@Serializable
internal data class BundleSupport(val artifacts: List<String>, val files: List<RuntimeExecutable>)

private val supportLocks = Array(32) { Any() }

/** Exact artifact hashes select compiler-declared support libraries, never a guessed latest bundle. */
internal fun supportArtifacts(
    config: RuntimeConfiguration, hash: String, root: File = catalogProjectRoot(),
    download: (URL, File) -> Unit = ::downloadToFile
): List<File> = config.bundle_support.filter { hash in it.artifacts }.flatMap { it.files }
    .distinctBy { it.sha256 }.map { asset ->
        require(Regex("[a-f0-9]{64}").matches(asset.sha256))
        require(URL(asset.url).protocol == "https")
        synchronized(supportLocks[Math.floorMod(asset.sha256.hashCode(), supportLocks.size)]) {
            val directory = File(root,"internal/cache/runtimes/support").apply { mkdirs() }
            val target = File(directory,asset.sha256+".jar")
            if (!target.isFile || sha256(target) != asset.sha256) {
                val temporary = File.createTempFile("support-", ".part", directory)
                try {
                    download(URL(asset.url),temporary)
                    if (sha256(temporary) != asset.sha256) throw IOException("Support artifact checksum mismatch")
                    java.nio.file.Files.move(temporary.toPath(),target.toPath(),
                        java.nio.file.StandardCopyOption.REPLACE_EXISTING)
                } finally {temporary.delete()}
            }
            target
        }
    }
