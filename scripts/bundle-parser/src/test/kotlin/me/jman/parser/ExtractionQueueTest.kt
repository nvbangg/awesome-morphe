package me.jman.parser

import java.io.File
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.*

class ExtractionQueueTest {
    @Test fun queueProcessesEachFolderOnceWithinWorkerLimit() {
        val active = AtomicInteger()
        val peak = AtomicInteger()
        val seen = ConcurrentHashMap.newKeySet<String>()
        val folders = (1..12).map { File("folder-$it") }
        val count = processDirectories(folders, 2) { folder ->
            val running = active.incrementAndGet()
            peak.updateAndGet { maxOf(it, running) }
            try {
                Thread.sleep(20)
                assertTrue(seen.add(folder.name))
            } finally { active.decrementAndGet() }
        }
        assertEquals(folders.size, count)
        assertEquals(folders.map { it.name }.toSet(), seen)
        assertEquals(2, peak.get())
    }

    @Test fun deadlineDefersUnstartedFoldersWithoutKillingActiveWorkers() {
        val seen = ConcurrentHashMap.newKeySet<String>()
        val count = processDirectories((1..10).map { File("folder-$it") }, 2, 1) {
            Thread.sleep(1100)
            seen.add(it.name)
        }
        assertEquals(2, count)
        assertEquals(setOf("folder-1", "folder-2"), seen)
    }

    @Test fun failedFolderDoesNotPreventRemainingWork() {
        val seen = mutableListOf<String>()
        assertEquals(3, processDirectories((1..3).map { File("$it") }, 1) {
            if (it.name == "2") error("Malformed folder")
            seen.add(it.name)
        })
        assertEquals(listOf("1", "3"), seen)
    }
}
