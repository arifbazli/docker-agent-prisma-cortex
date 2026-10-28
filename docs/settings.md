# Settings

Set in `.env` (copy from [.env.example](../.env.example)) or on the command line;
the command line wins. Back to the [README](../README.md).

## Models

All model names must end in `:cloud` or `-cloud`.

| Variable | Default | Used by |
|---|---|---|
| `RESEARCH_MODEL` | `nemotron-3-super:cloud` | briefing researcher |
| `WRITER_MODEL` | `nemotron-3-super:cloud` | briefing writer |
| `ROUTER_MODEL` | `nemotron-3-super:cloud` | root agents (`MODE=agent`) |
| `JUDGE_MODEL` | `gpt-oss:120b-cloud` | judge in both tools |
| `SPECIALIST_MODEL` | `nemotron-3-nano:30b-cloud` | guardrail category specialists |
| `REVIEWER_MODEL` | `nemotron-3-super:cloud` | guardrail assembler and reviewer |
| `ALLOW_LOCAL_MODELS` | unset (off) | `1` disables the cloud-only guard |

## Connection

| Variable | Default |
|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` |
| `CONTAINER_OLLAMA_BASE_URL` | `http://host.docker.internal:11434/v1` (compose only) |
| `HOST_UID` / `HOST_GID` | `10001` (compose only; set to `id -u` / `id -g`) |

## Docs briefing

| Variable | Default |
|---|---|
| `CFG` | `agents/prisma-cortex-hub.yaml` |
| `MODE` | `pipeline` (`agent` runs everything inside docker-agent) |
| `SAFETY` | `restricted` (docker-agent `--safety` level) |
| `OUT_DIR` | `outputs` (also used by the guardrail generator; `--out-dir`) |

## Guardrail generator

| Variable | Default |
|---|---|
| `GUARDRAIL_PARALLEL` | `4` specialists at once (max 7); also `--parallel` |
| `GUARDRAIL_BACKOFF_SECONDS` | `5` (rate-limit / connection retries, 3 tries, exponential) |
| `GUARDRAIL_CONTEXT_CHARS` | `24000` characters of source text per specialist |
| `GUARDRAIL_CACHE_DAYS` | `7` (start-page cache under `fetched/guardrail/`) |
| `GUARDRAIL_CFG` | `agents/guardrail-policy-generator.yaml`; also `-c` |
| `STAGE_TIMEOUT` | `900` seconds per model step; also `--timeout` |

## Tenant assistant (experimental)

`PRISMA_API_URL`, `PRISMA_ACCESS_KEY`, `PRISMA_SECRET_KEY`, `PRISMA_TOKEN`,
`CORTEX_FQDN`, `CORTEX_API_KEY`, `CORTEX_API_KEY_ID`. Use read-only keys and never
commit real values.
