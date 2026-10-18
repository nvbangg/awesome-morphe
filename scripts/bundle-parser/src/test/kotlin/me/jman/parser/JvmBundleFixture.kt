package me.jman.parser

/** Compiled marker for loader/selection tests whose patch objects come from a fake runtime. */
internal fun fixtureJvmClass(): ByteArray = org.objectweb.asm.ClassWriter(0).apply {
    visit(org.objectweb.asm.Opcodes.V1_8, org.objectweb.asm.Opcodes.ACC_PUBLIC,
        "fixture/BundleMarker", null, "java/lang/Object", null)
    visitEnd()
}.toByteArray()
