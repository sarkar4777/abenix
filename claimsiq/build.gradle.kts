// Root config — keeps all subprojects on the same Java 21 toolchain
// + pins Jackson/SLF4J versions so the SDK and the Spring app don't
// drift into two copies.
plugins {
    java
}

allprojects {
    group = "com.abenix"
    version = "0.1.0"

    repositories {
        mavenCentral()
    }
}

subprojects {
    apply(plugin = "java")

    extensions.configure<JavaPluginExtension> {
        toolchain {
            languageVersion.set(JavaLanguageVersion.of(21))
        }
    }

    tasks.withType<Test> {
        useJUnitPlatform()
    }
}
