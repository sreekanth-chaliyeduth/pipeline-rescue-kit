# Sanitized copy of the Gate 3A experimental JDK 11 agent Dockerfile.
# Historical build used local image tag prk-v11-agent:local.
ARG AGENT_IMAGE=jenkins/inbound-agent:jdk21@sha256:4cdc9b77a15b2e04949bece53129e0f3cb142d4589f38ed5229abaf2d37641dc
ARG TEMURIN11_IMAGE=eclipse-temurin:11-jdk@sha256:9d369f804a33762f34b24cd9d1b9722fd810c16001da58bd63d0919f19a712c3
ARG MAVEN_IMAGE=maven:3.9.16-eclipse-temurin-11@sha256:7bb84a451705605a47d24eb844d4d9ab03e33e131a507db76aafe25db3907f64

FROM ${TEMURIN11_IMAGE} AS jdk11
FROM ${MAVEN_IMAGE} AS maven
FROM ${AGENT_IMAGE}

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl unzip \
    && rm -rf /var/lib/apt/lists/*
COPY --from=jdk11 /opt/java/openjdk /opt/java/jdk11
COPY --from=maven /usr/share/maven /opt/maven
RUN ln -sf /opt/maven/bin/mvn /usr/local/bin/mvn

USER jenkins
