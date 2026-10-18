package me.jman.parser

import kotlin.test.*

class ExtractionDiagnosticsTest {
    @Test fun missingDependencyNamesAreRecordedWithoutArbitraryErrorMessages() {
        val failure = workerFailure(IllegalStateException("load failed",
            ClassNotFoundException("app.template.patches.shared.Constants")))
        assertEquals("runtime_missing_dependency", failure.first)
        assertTrue(failure.second.endsWith("app.template.patches.shared.Constants"))
        val invalid = workerFailure(NoClassDefFoundError("https://example.test/?token=secret"))
        assertFalse(invalid.second.contains("secret"))
        assertTrue(workerFailure(NoClassDefFoundError("app/template/Example")).second.endsWith("app.template.Example"))
    }
}
