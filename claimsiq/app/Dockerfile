# ClaimsIQ — Spring Boot + Vaadin Flow container
#
# Multi-stage: build the fat JAR with Gradle (Vaadin production mode
# triggers the frontend bundle compile during bootJar), then run it on
# a slim JRE. Java 21 matches the toolchain declared in the root
# build.gradle.kts so the bytecode the Gradle container emits will
# match what the runtime JRE can execute.

# ── stage 1: build ──────────────────────────────────────────────────
# Use the official gradle image so we don't need to commit a wrapper.
# `gradle:8.7-jdk21` ships Gradle 8.7 + OpenJDK 21 which matches the
# Spring Boot 3.2.5 + Vaadin 24.3 baseline.
FROM gradle:8.7-jdk21 AS build
WORKDIR /build

# Copy build config first so Docker caches the dep download when only
# Java source changes.
COPY settings.gradle.kts build.gradle.kts gradle.properties ./
COPY sdk/build.gradle.kts sdk/build.gradle.kts
COPY app/build.gradle.kts app/build.gradle.kts

# Warm the Gradle cache (best-effort — fails gracefully if the build
# script references source that isn't copied yet).
RUN gradle --no-daemon :sdk:dependencies :app:dependencies >/dev/null 2>&1 || true

# Copy source last — changes here bust the cache, but the expensive
# dependency resolution from the previous layer is preserved.
COPY sdk/ sdk/
COPY app/ app/

# Real build. -Pvaadin.productionMode=true makes the Vaadin plugin
# emit a production frontend bundle into the jar (no dev server).
RUN gradle --no-daemon :app:bootJar -Pvaadin.productionMode=true

# ── stage 2: runtime ────────────────────────────────────────────────
FROM eclipse-temurin:21-jre

WORKDIR /app

# Non-root user — Spring Boot doesn't need privileged ports (we listen
# on 3005), and unprivileged execution matches the cluster's default
# securityContext.
RUN useradd --create-home --uid 1001 claimsiq

COPY --from=build /build/app/build/libs/*.jar /app/claimsiq.jar
RUN chown claimsiq:claimsiq /app/claimsiq.jar

# wget is already present on temurin-jre; no extra install needed for
# the HEALTHCHECK.

USER claimsiq

EXPOSE 3005

# JVM flags: -XX:MaxRAMPercentage honours the k8s memory limit
# automatically instead of the JVM assuming it owns the host.
ENV JAVA_OPTS="-XX:MaxRAMPercentage=75.0 -XX:InitialRAMPercentage=50.0 -Djava.security.egd=file:/dev/./urandom"

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD wget -qO- http://localhost:3005/actuator/health/liveness || exit 1

ENTRYPOINT ["sh", "-c", "exec java $JAVA_OPTS -jar /app/claimsiq.jar"]
