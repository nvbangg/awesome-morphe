import java.util.Properties
import groovy.json.JsonSlurper
import groovy.json.JsonOutput

plugins {
    alias(libs.plugins.kotlin)
    alias(libs.plugins.kotlin.serialization)
    application
}

val hardcodedGprUser = ""
val hardcodedGprToken = ""
val gprUser: String? = providers.gradleProperty("gpr.user").orNull
val gprKey: String? = providers.gradleProperty("gpr.key").orNull
val localProperties = Properties().apply {
    val propertiesFile = sequenceOf(
        rootDir.resolve("local.properties"),
        rootDir.parentFile?.resolve("local.properties")
    ).firstOrNull { it?.isFile == true }

    if (propertiesFile != null) {
        propertiesFile.inputStream().use(::load)
    }
}
val localGprUser: String? = localProperties.getProperty("gpr.user")?.takeIf { it.isNotBlank() }
val localGprKey: String? = localProperties.getProperty("gpr.key")?.takeIf { it.isNotBlank() }
val resolvedGprUser: String? = when {
    hardcodedGprUser.isNotBlank() -> hardcodedGprUser
    !gprUser.isNullOrBlank() -> gprUser
    !localGprUser.isNullOrBlank() -> localGprUser
    else -> System.getenv("GITHUB_ACTOR")
}
val resolvedGprKey: String? = when {
    hardcodedGprToken.isNotBlank() -> hardcodedGprToken
    !gprKey.isNullOrBlank() -> gprKey
    !localGprKey.isNullOrBlank() -> localGprKey
    else -> sequenceOf("GITHUB_PACKAGES_TOKEN", "GITHUB_TOKEN", "GIT_TOKEN")
        .mapNotNull { System.getenv(it)?.takeIf(String::isNotBlank) }.firstOrNull()
}

repositories {
    mavenCentral()
    google()
    maven {
        url = uri("https://jitpack.io")
        content {
            includeGroup("com.github.iBotPeaches.smali")
            includeGroup("com.github.MorpheApp")
            includeGroup("com.github.MorpheApp.smali")
            includeGroup("com.github.REAndroid")
        }
    }

    maven {
        name = "GitHubPackages"
        url = uri("https://maven.pkg.github.com/revanced/registry")
        content {
            includeGroup("app.revanced")
        }
        credentials {
            username = resolvedGprUser
            password = resolvedGprKey
        }
        authentication {
            create<org.gradle.authentication.http.BasicAuthentication>("basic")
        }
    }
    maven {
        name = "ReVancedPatcherPackages"
        url = uri("https://maven.pkg.github.com/revanced/revanced-patcher")
        content {
            includeGroup("app.revanced")
        }
        credentials {
            username = resolvedGprUser
            password = resolvedGprKey
        }
        authentication {
            create<org.gradle.authentication.http.BasicAuthentication>("basic")
        }
    }
    maven {
        name = "ReVancedLibraryPackages"
        url = uri("https://maven.pkg.github.com/revanced/revanced-library")
        content {
            includeGroup("app.revanced")
        }
        credentials {
            username = resolvedGprUser
            password = resolvedGprKey
        }
        authentication {
            create<org.gradle.authentication.http.BasicAuthentication>("basic")
        }
    }
    // Older patchers used these repositories before the shared registry.
    // https://github.com/ReVanced/revanced-patcher/blob/cbfb9ba02f3bb3d30047332d1fbd9ed95dd7f06d/settings.gradle.kts
    listOf("multidexlib2", "apktool").forEach { legacyRepository ->
        maven {
            name = "ReVancedLegacy_" + legacyRepository
            url = uri("https://maven.pkg.github.com/revanced/" + legacyRepository)
            content {
                includeGroup("app.revanced")
            }
            credentials {
                username = resolvedGprUser
                password = resolvedGprKey
            }
            authentication {
                create<org.gradle.authentication.http.BasicAuthentication>("basic")
            }
        }
    }
    maven {
        name = "MorphePackages"
        url = uri("https://maven.pkg.github.com/MorpheApp/morphe-patcher")
        content {
            includeGroup("app.morphe")
        }
        credentials {
            username = resolvedGprUser
            password = resolvedGprKey
        }
        authentication {
            create<org.gradle.authentication.http.BasicAuthentication>("basic")
        }
    }
    maven {
        name = "MorpheRegistryPackages"
        url = uri("https://maven.pkg.github.com/MorpheApp/registry")
        content {
            includeGroup("app.morphe")
        }
        credentials {
            username = resolvedGprUser
            password = resolvedGprKey
        }
        authentication {
            create<org.gradle.authentication.http.BasicAuthentication>("basic")
        }
    }
}

dependencies {
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.kotlin.stdlib)
    implementation(libs.asm)
    implementation(libs.dex.translator)
    implementation(libs.smali)
    compileOnly(libs.jsr305)
    testImplementation(kotlin("test"))
}

kotlin {
    jvmToolchain(21)
    compilerOptions {
        freeCompilerArgs.add("-Xskip-prerelease-check")
    }
}

java {
    targetCompatibility = JavaVersion.VERSION_21
    sourceCompatibility = JavaVersion.VERSION_21
}

application {
    mainClass.set("me.jman.parser.MainKt")
}

tasks.register("assembleRelease") {
    group = "build"
    description = "Alias for assemble to support CI validation on this JVM application module."
    dependsOn(tasks.named("assemble"))
}

// Each configuration resolves independently; an unavailable runtime is recorded, not fatal.
val morphePatcher = libs.morphe.patcher.get().toString()
val configuredRuntimes = listOf(mapOf(
    "id" to "morphe-latest",
    "family" to "Morphe:V1",
    "loader" to "morphe",
    "coordinate" to morphePatcher,
    "dependencies" to listOf(morphePatcher, "com.google.code.gson:gson:2.14.0")
))
val runtimeConfiguration = layout.buildDirectory.file("patcher-runtimes.json")
val runtimeConfigurationJson = JsonOutput.prettyPrint(JsonOutput.toJson(mapOf(
    "worker" to mapOf("restart_attempts" to 0),
    "runtimes" to configuredRuntimes
)))
val generateRuntimeConfiguration = tasks.register("generateRuntimeConfiguration") {
    inputs.property("configuration", runtimeConfigurationJson)
    outputs.file(runtimeConfiguration)
    doLast {
        runtimeConfiguration.get().asFile.apply {
            parentFile.mkdirs()
            writeText(runtimeConfigurationJson)
        }
    }
}
val configurableRuntimeDependencies = configuredRuntimes.associate { runtime ->
    val id = runtime["id"] as String
    require(id.matches(Regex("[a-z0-9-]+"))) { "Invalid runtime id" }
    val configuration = configurations.create("catalogRuntime_" + id.replace("-", "_")) {
        isCanBeConsumed = false
        isCanBeResolved = true
        if (id == "revanced-v3-11") {
            // Patcher 11 published the smali version as a nonexistent multidexlib2 version.
            // The original multidexlib2 uses the same org.jf API as this smali fork:
            // https://github.com/ReVanced/multidexlib2/blob/81179c643007e10b2885c63945da93090cc176d4/build.gradle
            resolutionStrategy.dependencySubstitution {
                substitute(module("app.revanced:multidexlib2:2.5.3-a3836654"))
                    .using(module("com.github.lanchon.dexpatcher:multidexlib2:2.3.4.r2"))
                    .because("Use the published original multidexlib2 for patcher 11")
                substitute(module("org.smali:dexlib2"))
                    .using(module("app.revanced:dexlib2:2.5.3-a3836654"))
                    .because("Keep multidexlib2 on patcher 11's smali fork")
            }
        }
    }
    (runtime["dependencies"] as List<*>).forEach { coordinate ->
        dependencies.add(configuration.name, coordinate as String)
    }
    id to configuration
}
val runtimeManifest = layout.buildDirectory.file("runtime-classpaths.json")
val prepareCatalogRuntimes = tasks.register("prepareCatalogRuntimes") {
    dependsOn(generateRuntimeConfiguration)
    inputs.file(runtimeConfiguration)
    outputs.file(runtimeManifest)
    outputs.upToDateWhen { false } // Retry runtime artifact outages on the next workflow run.
    doLast {
        val installed = configurableRuntimeDependencies.mapValues { (id, configuration) ->
            try {
                mapOf("available" to true,
                      "classpath" to configuration.files.joinToString(File.pathSeparator) { it.absolutePath })
            } catch (failure: Exception) {
                // Report coordinates, not raw exception messages that may contain credentials.
                val unresolved = runCatching {
                    configuration.incoming.resolutionResult.allDependencies
                        .filterIsInstance<org.gradle.api.artifacts.result.UnresolvedDependencyResult>()
                }.getOrDefault(emptyList())
                val coordinates = unresolved.map { it.attempted.displayName }.distinct()
                val httpStatuses = (listOf(failure) + unresolved.map { it.failure })
                    .flatMap { problem -> generateSequence(problem as Throwable) { it.cause }.take(10).toList() }
                    .flatMap { problem -> Regex("status code (\\d{3})", RegexOption.IGNORE_CASE)
                        .findAll(problem.message.orEmpty()).map { it.groupValues[1] }.toList() }.distinct()
                val hint = if (resolvedGprKey.isNullOrBlank()) {
                    "No package token configured; set GITHUB_PACKAGES_TOKEN or gpr.key with read:packages."
                } else {
                    "Check artifact availability, repository access and transitive dependencies; " +
                        "a resolution failure does not necessarily mean the token is invalid."
                }
                logger.warn("Runtime {} unavailable ({}). Unresolved dependencies: {}. HTTP status: {}. {}",
                    id, failure.javaClass.simpleName,
                    coordinates.ifEmpty { listOf("artifact download or variant selection") }.joinToString(),
                    httpStatuses.ifEmpty { listOf("not reported") }.joinToString(), hint)
                mapOf("available" to false, "classpath" to "")
            }
        }
        check(installed.values.any { it["available"] == true }) { "No Morphe runtime is available" }
        runtimeManifest.get().asFile.apply {
            parentFile.mkdirs()
            writeText(JsonOutput.prettyPrint(JsonOutput.toJson(installed)))
        }
    }
}
tasks.named<JavaExec>("run") {
    dependsOn(prepareCatalogRuntimes)
    doFirst {
        systemProperty("catalog.runtime.config", runtimeConfiguration.get().asFile)
        systemProperty("catalog.runtime.manifest", runtimeManifest.get().asFile)
    }
}
tasks.named<Test>("test") {
    dependsOn(tasks.named("installDist"), generateRuntimeConfiguration)
    inputs.file(runtimeConfiguration)
    systemProperty("catalog.runtime.config", runtimeConfiguration.get().asFile)
    filter {
        excludeTestsMatching("me.jman.parser.LegacyReseamParserTest")
        excludeTestsMatching("me.jman.parser.ReseamPatchParserTest.engineRequirementReordersRemainingRuntimesWithoutDroppingFallbacks")
        excludeTestsMatching("me.jman.parser.ReseamPatchParserTest.configuredNativeLoaderAndLegacyFamilyMigration")
        excludeTestsMatching("me.jman.parser.PatcherRuntimeSelectionTest.shippedReVancedFamiliesKeepTheirOwnNewestFirstFallbacks")
        excludeTestsMatching("me.jman.parser.PatcherRuntimeSelectionTest.shippedReseamStartsWithLatestNativeEngineBeforeHistoricalAdapters")
        excludeTestsMatching("me.jman.parser.PatcherRuntimeSelectionTest.declaredReVancedVersionStaysFirstWithinItsFormatFamily")
    }
}
val runtimeSmoke = tasks.register<Exec>("runtimeSmoke") {
    group = "verification"
    description = "Validate runtime isolation, deadlines and extraction failure handling."
    dependsOn(tasks.named("installDist"), prepareCatalogRuntimes)
    workingDir(rootDir.parentFile)
    commandLine(providers.environmentVariable("PYTHON").orElse("python").get(), "scripts/runtime_smoke.py")
}
tasks.named("assembleRelease") {
    dependsOn(tasks.named("test"))
}
