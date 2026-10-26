# docker-agent-prisma-cortex

> Independent project. Not affiliated with Palo Alto Networks or Docker.

Ask about **Prisma Cloud** or **Cortex Cloud** (especially migrating from Prisma Cloud to Cortex Cloud) and get a short briefing built only from official documentation. Every statement cites a page, and a script checks that the quote is really on it. Built on [docker-agent](https://github.com/docker/docker-agent) with [Ollama](https://ollama.com) models.

![Example run: Prisma Cloud to Cortex Cloud migration briefing](docs/images/example-run.png)

## How it works

```
question -> researcher (LLM) -> quote check (script) -> judge (LLM) -> writer (LLM) -> briefing
```

The researcher (`nemotron-3-super:cloud`) fetches docs and extracts facts with quotes. A script checks each quote against the fetched page. The judge (`gpt-oss:120b-cloud`, a different model family) decides if the quote supports the fact. The writer uses supported facts only. About 1-3 minutes per question.

| Agent | Scope |
|---|---|
| `agents/prisma-cortex-hub.yaml` (default) | Palo Alto Networks products, focus on Prisma Cloud and Cortex Cloud |
| `agents/cortex-cloud-hub.yaml` | Cortex Cloud only |

## Quick start

Needs `bash`, `curl`, `python3` 3.9+, [docker-agent](https://github.com/docker/docker-agent/releases) 1.152+ and [Ollama](https://ollama.com/download).

```bash
ollama signin                                   # default models are ":cloud" (run on ollama.com, need internet)
git clone https://github.com/arifbazli/docker-agent-prisma-cortex.git && cd docker-agent-prisma-cortex
cp .env.example .env                            # models and Ollama URL
python3 -m unittest discover -s tests           # optional: check setup, no model calls
scripts/run.sh "Why migrate from Prisma Cloud to Cortex Cloud?"
```

More examples:

```bash
CFG=agents/cortex-cloud-hub.yaml scripts/run.sh "What does Cortex Cloud AI-SPM monitor?"
JUDGE_MODEL=qwen3:32b scripts/run.sh "How do I authenticate to the Cortex Cloud API?"
```

**Output:** the briefing is printed and saved to `outputs/<run>.md`. `outputs/<run>.evidence.json` holds each fact, quote and verdict. Check **To confirm** items yourself. One-line results: `OUT OF SCOPE`, `NO FACTS FOUND`, `BRIEFING FAILED` (see `logs/`). Exit codes: `0` ok, `1` failed checks, `2` step failed.

## Docker

```bash
cp .env.example .env && printf 'HOST_UID=%s\nHOST_GID=%s\n' "$(id -u)" "$(id -g)" >> .env
mkdir -p outputs logs fetched
docker compose run --rm --build agent "Why migrate from Prisma Cloud to Cortex Cloud?"
```

Uses Ollama on the host. Prebuilt image: `ghcr.io/arifbazli/docker-agent-prisma-cortex:latest`. See [`compose.yaml`](compose.yaml) to run Ollama in a container.

## Making changes

`agents/*.yaml` are generated; do not edit them. Edit `templates/agent.yaml.tmpl` (shared prompts), `templates/scopes/*.txt` (per-agent scope) or `seeds/*.txt` (start pages), then:

```bash
git checkout -b my-change
python3 scripts/gen-configs.py                  # regenerate agents/*.yaml
python3 -m unittest discover -s tests && scripts/check-seeds.sh
bench/run-all.sh                                # ~25 min, appends to bench/results.tsv
git commit -am "..." && git push -u origin my-change   # open a PR; CI must pass
```

Compare new `bench/results.tsv` rows with the previous ones before merging. Put expected answers in `bench/questions.txt`, not in prompts.

## Settings

Set in `.env` or on the command line (the command line wins).

| Variable | Default |
|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` |
| `RESEARCH_MODEL` / `WRITER_MODEL` / `ROUTER_MODEL` | `nemotron-3-super:cloud` |
| `JUDGE_MODEL` | `gpt-oss:120b-cloud` |
| `CFG` | `agents/prisma-cortex-hub.yaml` |
| `MODE` | `pipeline` (`agent` = run everything inside docker-agent) |
| `SAFETY` | `restricted` |

## Tenant assistant (experimental)

Read-only questions about your own Prisma Cloud / Cortex Cloud tenants. Fill the `PRISMA_*` and `CORTEX_*` values in `.env` with **read-only** keys, then:

```bash
scripts/gen-tenant-config.sh && eval "$(scripts/prisma-login.sh)"
docker-agent run --exec --env-from-file .env agents/tenant-readonly.local.yaml "List my cloud accounts in both tenants"
```

Not yet tested against a live tenant. Tenant data is sent to the model provider.

## Layout

```
agents/     generated configs        templates/  prompt template and scopes
seeds/      start pages              scripts/    pipeline, checks, generators
bench/      benchmark + results      tests/      unit tests
examples/   old experiments          docs/images README image (scripts/make-example-image.py)
```

## Safety and limitations

- Agents can only fetch pages from `cortex-docs.paloaltonetworks.com`, `docs.paloaltonetworks.com`, `www.paloaltonetworks.com`, `docs.prismacloud.io` and `pan.dev`. Write, exec and shell tools are denied.
- Answers are only as current as the docs. Broad questions can give thin briefings; ask narrower ones.
- If a run fails, rerun once (models vary). Connection errors: check Ollama and `OLLAMA_BASE_URL`. `401` from a `:cloud` model: `ollama signin`.

## License

[MIT](LICENSE)
