# syntax=docker/dockerfile:1
# Image with docker-agent, the agent configs and the pipeline scripts.
# Models are NOT inside the image: point OLLAMA_BASE_URL at an Ollama server
# (on the host, or the `ollama` compose profile). See compose.yaml.
#
#   docker build -t grounded-ai-guardrails .
#   docker run --rm --env-file .env -v "$PWD/outputs:/app/outputs" \
#     --add-host=host.docker.internal:host-gateway \
#     grounded-ai-guardrails "Why migrate from Prisma Cloud to Cortex Cloud?"

FROM python:3.12-slim

ARG DOCKER_AGENT_VERSION=v1.152.0
# sha256 of the release binaries for DOCKER_AGENT_VERSION (update together).
ARG DOCKER_AGENT_SHA256_AMD64=bb591b3b73e6ce06b24a19732371fefb5a99f001813c94e146a4b1474135c8e8
ARG DOCKER_AGENT_SHA256_ARM64=a048a1b5da4d57b1e9669e72460e16153ea7185722b74a411ea0a9b5341ec94f

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
      amd64) sum="$DOCKER_AGENT_SHA256_AMD64" ;; \
      arm64) sum="$DOCKER_AGENT_SHA256_ARM64" ;; \
      *) echo "unsupported arch $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /usr/local/bin/docker-agent \
      "https://github.com/docker/docker-agent/releases/download/${DOCKER_AGENT_VERSION}/docker-agent-linux-${arch}"; \
    echo "${sum}  /usr/local/bin/docker-agent" | sha256sum -c -; \
    chmod +x /usr/local/bin/docker-agent; \
    docker-agent version

RUN useradd --create-home --uid 10001 agent
WORKDIR /app
COPY --chown=agent:agent agents/ agents/
COPY --chown=agent:agent seeds/ seeds/
COPY --chown=agent:agent templates/ templates/
COPY --chown=agent:agent scripts/ scripts/
COPY --chown=agent:agent bench/ bench/
RUN mkdir -p outputs logs fetched && chown agent:agent outputs logs fetched
USER agent

ENV TELEMETRY_ENABLED=false \
    OLLAMA_BASE_URL=http://host.docker.internal:11434/v1 \
    RESEARCH_MODEL=nemotron-3-super:cloud \
    JUDGE_MODEL=gpt-oss:120b-cloud \
    WRITER_MODEL=nemotron-3-super:cloud \
    ROUTER_MODEL=nemotron-3-super:cloud \
    CFG=agents/prisma-cortex-hub.yaml \
    SAFETY=restricted

VOLUME ["/app/outputs", "/app/logs", "/app/fetched"]
ENTRYPOINT ["scripts/run.sh"]
CMD ["What does Cortex Cloud Posture Management cover?"]
