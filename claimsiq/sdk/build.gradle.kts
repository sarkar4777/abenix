// JVM SDK for Abenix. Deliberately stdlib-only public surface so
// Kotlin and Scala consumers get zero friction.
//   - JDK 21 `HttpClient` for HTTP + SSE
//   - Jackson for JSON (only runtime dep besides SLF4J)
//   - SLF4J API for logging (binding chosen by the consumer)
plugins {
    `java-library`
}

dependencies {
    api("com.fasterxml.jackson.core:jackson-databind:2.17.2")
    api("org.slf4j:slf4j-api:2.0.13")

    testImplementation("org.junit.jupiter:junit-jupiter:5.10.2")
    testImplementation("org.slf4j:slf4j-simple:2.0.13")
}

java {
    withSourcesJar()
    withJavadocJar()
}
