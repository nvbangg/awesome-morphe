package me.jman.parser

import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.net.URL
import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertFails
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class DownloadBoundsTest {
    private fun withProperty(name: String, value: String, action: () -> Unit) {
        val previous = System.getProperty(name)
        System.setProperty(name, value)
        try { action() } finally {
            if (previous == null) System.clearProperty(name) else System.setProperty(name, previous)
        }
    }

    @Test fun oversizedFilesAreRejectedAndPartialOutputIsDeleted() {
        val input = Files.createTempFile("download-source", ".bin").toFile()
        val output = Files.createTempFile("download-target", ".bin").toFile()
        try {
            input.writeBytes(ByteArray(32))
            withProperty("catalog.download.max_bytes", "8") {
                assertFails { downloadToFile(input.toURI().toURL(), output) }
                assertFalse(output.exists())
            }
        } finally { input.delete(); output.delete() }
    }

    @Test fun continuouslyStreamingResponsesCannotBypassTheOverallDeadline() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/") { exchange ->
            runCatching {
                exchange.sendResponseHeaders(200, 0)
                exchange.responseBody.use { stream ->
                    repeat(12) {
                        stream.write(1)
                        stream.flush()
                        Thread.sleep(200)
                    }
                }
            }
            exchange.close()
        }
        val output = Files.createTempFile("download-deadline", ".bin").toFile()
        server.start()
        try {
            withProperty("catalog.download.timeout_seconds", "1") {
                val started = System.nanoTime()
                assertFails { downloadToFile(URL("http://127.0.0.1:${server.address.port}/"), output) }
                assertTrue(System.nanoTime() - started < 3_000_000_000L)
                assertFalse(output.exists())
            }
        } finally { server.stop(0); output.delete() }
    }

    @Test fun retainedDiagnosticsRemoveTokensAndUrlCredentials() {
        val safe = sanitizedWorkerLog("Bearer private-token\nhttps://user:password@example.test/file?token=secret\n::warning::hello")
        assertFalse(safe.contains("private-token"))
        assertFalse(safe.contains("user:password"))
        assertFalse(safe.contains("?token"))
        assertFalse(safe.contains("::warning::"))
        assertTrue(safe.contains("example.test/file"))
        val configured = sanitizedWorkerLog("raw-secret Basic encoded-credential",
            mapOf("GIT_HOST_TOKENS" to """{"host":"raw-secret"}"""))
        assertFalse(configured.contains("raw-secret"))
        assertFalse(configured.contains("encoded-credential"))
    }
}
