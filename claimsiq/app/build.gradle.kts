// Spring Boot + Vaadin Flow — single process serves both the UI and
// the REST API at /api/claimsiq/*. One port (3005), one Docker image,
// one k8s Deployment — matches the pattern the other standalone apps
// use (example_app/sauditourism/…) without the Python+Node duo.
plugins {
    id("org.springframework.boot") version "3.2.5"
    id("io.spring.dependency-management") version "1.1.4"
    id("com.vaadin") version "24.3.13"
    java
}

springBoot {
    mainClass.set("com.abenix.claimsiq.ClaimsIqApplication")
}

dependencies {
    implementation(project(":sdk"))

    implementation("org.springframework.boot:spring-boot-starter-web")
    implementation("org.springframework.boot:spring-boot-starter-validation")
    implementation("org.springframework.boot:spring-boot-starter-actuator")
    implementation("org.springframework.boot:spring-boot-starter-data-jpa")
    implementation("org.springframework.boot:spring-boot-starter-webflux")   // for SSE server + non-blocking client
    // Jackson modules used by the SSE bridge — DagSnapshot has Instant
    // fields, JsonNullable on optional payloads. Without these on the
    // classpath the ObjectMapper that serialises snapshots into SSE
    // events 500s with "Java 8 date/time type not supported".
    implementation("com.fasterxml.jackson.datatype:jackson-datatype-jsr310")
    runtimeOnly("org.postgresql:postgresql")
    implementation("com.vaadin:vaadin-spring-boot-starter:24.3.13")
    implementation("com.vaadin:vaadin-core:24.3.13")

    testImplementation("org.springframework.boot:spring-boot-starter-test")
}

// Vaadin production bundle — built on `gradle bootJar` when -Pvaadin.productionMode=true
vaadin {
    productionMode = (project.findProperty("vaadin.productionMode") ?: "false").toString().toBoolean()
}
