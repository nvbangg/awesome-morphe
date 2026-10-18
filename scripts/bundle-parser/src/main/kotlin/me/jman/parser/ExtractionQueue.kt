package me.jman.parser

import java.io.File
import java.util.concurrent.ExecutorCompletionService
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/** At most workers folders are in flight; the deadline stops dispatch, not active workers. */
internal fun processDirectories(
    directories: List<File>, workers: Int, maxSeconds: Long? = null,
    process: (File) -> Unit = { processBundle(it) }
): Int {
    require(workers in 1..4)
    if (directories.isEmpty()) return 0
    val number = AtomicInteger()
    val pool = Executors.newFixedThreadPool(workers) { action ->
        Thread(action, "catalog-extractor-${number.incrementAndGet()}")
    }
    val completion = ExecutorCompletionService<Unit>(pool)
    val started = System.nanoTime()
    var dispatched = 0
    var active = 0
    try {
        while (dispatched < directories.size || active > 0) {
            while (active < workers && dispatched < directories.size &&
                (maxSeconds == null || System.nanoTime() - started < TimeUnit.SECONDS.toNanos(maxSeconds))) {
                val directory = directories[dispatched++]
                completion.submit(java.util.concurrent.Callable {
                    try { process(directory) }
                    catch (error: Exception) {
                        if (error is InterruptedException) {
                            Thread.currentThread().interrupt()
                            throw error
                        }
                        Logger.error("Failed processing ${directory.name}: ${error.javaClass.simpleName}")
                    }
                    Unit
                })
                active++
            }
            if (active == 0) break
            completion.take().get()
            active--
        }
        return dispatched
    } finally {
        pool.shutdownNow()
        pool.awaitTermination(10, TimeUnit.SECONDS)
    }
}
