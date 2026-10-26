# docker-agent-prisma-cortex

> Independent research project. Not affiliated with or endorsed by Palo Alto Networks or Docker.

Ask a question about **Prisma Cloud** or **Cortex Cloud** (especially migrating from Prisma Cloud to Cortex Cloud) and get a short briefing built only from official Palo Alto Networks documentation. Every statement in the briefing cites a page, and a script checks that the quoted text really is on that page.

It is a multi-model workflow built on [docker-agent](https://github.com/docker/docker-agent), with models served by [Ollama](https://ollama.com).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/docker-agent-run-dark.svg">
  <img alt="Example run: Prisma Cloud to Cortex Cloud migration briefing" src="docs/images/docker-agent-run-light.svg">
</picture>

## Contents

1. [How it works](#how-it-works)
2. [Getting started](#getting-started) - set up once, in 5 steps
3. [Everyday use](#everyday-use)
4. [Run with Docker](#run-with-docker)
5. [Changing the agents](#changing-the-agents) - the development workflow
6. [Read-only tenant assistant (experimental)](#read-only-tenant-assistant-experimental)
7. [Reference](#reference)
8. [Troubleshooting](#troubleshooting)

---

## How it works

```
question
   |
   v
researcher (LLM)    fetches official docs pages, writes FACT lines with exact quotes
   |
   v
quote check (script) is each quote really on the page the researcher fetched?
   |
   v
judge (LLM)         does the quote actually support the fact?
   |
   v
writer (LLM)        writes the briefing from SUPPORTED facts only
   |
   v
outputs/<run>.md + outputs/<run>.evidence.json
```

| Step | Default model | Why |
|---|---|---|
| researcher | `nemotron-3-super:cloud` | Reads documentation, extracts facts |
| quote check | none (Python) | String matching is done by code, not by an LLM, so it is exact and fast |
| judge | `gpt-oss:120b-cloud` | A different model family from the researcher, so it does not share the same blind spots |
| writer | `nemotron-3-super:cloud` | Turns verified facts into a short briefing |

Each step is a separate `docker-agent run` call driven by [`scripts/pipeline.py`](scripts/pipeline.py). A run takes about 1-3 minutes.

Two agents are included:

| Agent config | Answers |
|---|---|
| `agents/prisma-cortex-hub.yaml` (default) | Palo Alto Networks products, deepest on Prisma Cloud and Cortex Cloud: migration, features, release notes, APIs |
| `agents/cortex-cloud-hub.yaml` | Cortex Cloud only; Prisma Cloud only as migration context |

---

## Getting started

Do this once. It assumes Linux, macOS or WSL2 with `bash`, `git`, `curl` and `python3` (3.9 or later; no extra Python packages are needed).

### Step 1 - Install docker-agent

Either use Docker Desktop (it includes `docker agent`), or install the standalone binary (version 1.152.0 or later):

```bash
mkdir -p ~/.local/bin
curl -fsSL -o ~/.local/bin/docker-agent \
  https://github.com/docker/docker-agent/releases/download/v1.152.0/docker-agent-linux-amd64   # or -linux-arm64 / -darwin-arm64
chmod +x ~/.local/bin/docker-agent
export PATH="$HOME/.local/bin:$PATH"     # add this line to ~/.bashrc
docker-agent version
```

### Step 2 - Set up Ollama

Install Ollama from <https://ollama.com/download>, then:

```bash
ollama signin                                   # the default models are ":cloud" models
ollama run gpt-oss:120b-cloud "Say hello"       # quick test
ollama run nemotron-3-super:cloud "Say hello"
```

`:cloud` models run on ollama.com, not on your machine. They need `ollama signin` and an internet connection, and your questions and the fetched pages are sent to ollama.com. To work fully offline, pull local models and set them in `.env` (Step 3).

### Step 3 - Clone the repo and create `.env`

```bash
git clone https://github.com/arifbazli/docker-agent-prisma-cortex.git
cd docker-agent-prisma-cortex
cp .env.example .env
```

The defaults in `.env` work if Ollama runs on `localhost:11434`. Edit it to change models or the Ollama URL. `.env` is git-ignored; never commit it.

### Step 4 - Check the setup (no model calls)

```bash
python3 -m unittest discover -s tests     # unit tests
scripts/check-seeds.sh                    # the documentation start pages are reachable
```

Both should end with `OK` / `ok` lines and no `FAIL`.

### Step 5 - Ask your first question

```bash
scripts/run.sh "Why migrate from Prisma Cloud to Cortex Cloud?"
```

You should see the pipeline steps, the briefing, then `=== checks ===` ending in `PASS`. Done.

---

## Everyday use

### Ask a question

```bash
scripts/run.sh "How do I link a Prisma Cloud tenant to Cortex Cloud?"
scripts/run.sh "What is new in the latest Cortex Cloud Posture Management release?"
scripts/run.sh "How do I authenticate to the Cortex Cloud API?"
```

Use the Cortex Cloud-only agent:

```bash
CFG=agents/cortex-cloud-hub.yaml scripts/run.sh "What does Cortex Cloud AI-SPM monitor?"
```

Try another model for one run, without editing `.env`:

```bash
JUDGE_MODEL=qwen3:32b scripts/run.sh "..."
```

### Read the result

Each run writes:

| File | Contains |
|---|---|
| `outputs/<run>.md` | The briefing (also printed) |
| `outputs/<run>.evidence.json` | Every fact, its quote, the verdict and why, the pages fetched, timings and models |
| `fetched/` | The exact page text the quotes were checked against |
| `logs/<run>/` | Raw docker-agent event streams, for debugging |

A briefing looks like this:

```
# PANW Briefing: <topic>          ("Cortex Cloud Briefing" for cortex-cloud-hub)
**Bottom line:** ...
**Why move** / **How migration works** / **Mapping** / **Manual work** / **Capabilities**
**To confirm**   facts that could not be fully verified - check these yourself
**Sources**
```

Instead of a briefing you may get one line:

| Result | Meaning |
|---|---|
| `OUT OF SCOPE: ...` | The question is not about the agent's products |
| `NO FACTS FOUND: ...` / `NO SUPPORTED FACTS AVAILABLE FOR BRIEFING.` | The documentation pages found did not answer it; rephrase or ask something narrower |
| `BRIEFING FAILED: ...` | A step crashed (model unreachable, timeout); see `logs/` |

`scripts/run.sh` exit codes: `0` passed checks (or a valid one-line result above), `1` briefing failed checks, `2` a step failed. Useful in scripts and CI.

Always check **To confirm** items and the **Mapping** rows against the cited page before acting on them.

---

## Run with Docker

The image contains docker-agent, the agents and the scripts; the models stay in Ollama.

```bash
cp .env.example .env
printf 'HOST_UID=%s\nHOST_GID=%s\n' "$(id -u)" "$(id -g)" >> .env   # lets the container write ./outputs
mkdir -p outputs logs fetched
docker compose build
docker compose run --rm agent "Why migrate from Prisma Cloud to Cortex Cloud?"
```

By default the container uses Ollama on your host (`host.docker.internal:11434`). To run Ollama in a container as well:

```bash
docker compose --profile ollama up -d ollama
docker compose exec ollama ollama signin
CONTAINER_OLLAMA_BASE_URL=http://ollama:11434/v1 docker compose run --rm agent "..."
```

A prebuilt image is published to `ghcr.io/arifbazli/docker-agent-prisma-cortex:latest` on every push to `main` (set `IMAGE=` in `.env` to use it instead of building).

---

## Changing the agents

Follow this loop for any change to prompts, start pages, models or scripts.

```
1. branch  ->  2. edit sources  ->  3. regenerate  ->  4. fast checks  ->  5. benchmark  ->  6. commit + PR
```

**1. Create a branch**

```bash
git checkout main && git pull
git checkout -b my-change
```

**2. Edit the sources, never `agents/*.yaml`**

The two agent configs are generated. Edit what they are generated from:

| To change | Edit |
|---|---|
| Prompts, agent steps, rules shared by both agents | `templates/agent.yaml.tmpl` |
| Scope, headings, allowed domains, out-of-scope text for one agent | `templates/scopes/<agent>.txt` |
| Start pages for a question type | `seeds/migration.txt`, `seeds/native.txt`, `seeds/release.txt`, `seeds/api.txt` |
| Default models | `.env` (local) and `.env.example` (for everyone) |
| Checks, pipeline logic | `scripts/` (add a test in `tests/`) |
| Benchmark questions | `bench/questions.txt` |

Keep prompts generic. Do not write expected answers into prompts; put them in `bench/questions.txt` as `must_include` patterns.

**3. Regenerate the configs**

```bash
python3 scripts/gen-configs.py
```

**4. Run the fast checks (no model calls, seconds)**

```bash
python3 scripts/gen-configs.py --check
python3 -m unittest discover -s tests
scripts/check-seeds.sh
for f in agents/*.yaml; do docker-agent debug config "$f" > /dev/null && echo "ok $f"; done
```

CI also runs `shellcheck -x scripts/*.sh bench/*.sh` and `yamllint -s agents/ compose.yaml .github/` if you have them.

**5. Run the benchmark (uses models, about 20-30 minutes per agent)**

```bash
bench/run-all.sh                                      # all questions, default agent
bench/run-all.sh migrate-why link-tenants             # selected questions
CFG=agents/cortex-cloud-hub.yaml bench/run-all.sh     # the other agent
```

Each question is checked for the right outcome and required content, and one row is appended to `bench/results.tsv` with the commit and models. Compare the new rows with the earlier ones: the change should not lower the pass count. Models vary between runs, so rerun a failing question once before blaming the change.

**6. Commit and open a pull request**

```bash
git add -A
git commit -m "Describe the change"
git push -u origin my-change
gh pr create --fill            # or open the PR on github.com
```

Commit `bench/results.tsv` together with the change so the next person has a baseline. Merge when CI is green.

---

## Read-only tenant assistant (experimental)

Answers questions about **your own** tenants, for example "Which Prisma Cloud accounts are not yet onboarded in Cortex Cloud, and what needs manual migration?". It calls read-only Prisma Cloud CSPM and Cortex Cloud APIs and reads the official migration pages.

1. Create a **read-only** Prisma Cloud access key and a read-only Cortex Cloud standard API key.
2. Fill in `PRISMA_API_URL`, `PRISMA_ACCESS_KEY`, `PRISMA_SECRET_KEY`, `CORTEX_FQDN`, `CORTEX_API_KEY`, `CORTEX_API_KEY_ID` in `.env`.
3. Run:

```bash
scripts/gen-tenant-config.sh           # writes agents/tenant-readonly.local.yaml (git-ignored)
eval "$(scripts/prisma-login.sh)"      # sets PRISMA_TOKEN, valid about 10 minutes
docker-agent run --exec --env-from-file .env agents/tenant-readonly.local.yaml \
  "List my cloud accounts in both tenants"
```

Keys stay in the environment; only the tenant host names are written into the generated file. Tenant data is sent to the model provider (ollama.com for `:cloud` models); use local models if that is not allowed. So far tested only against the API's error path, not a live tenant.

---

## Reference

### Settings (`.env` or environment)

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Ollama endpoint |
| `RESEARCH_MODEL` | `nemotron-3-super:cloud` | Researcher |
| `JUDGE_MODEL` | `gpt-oss:120b-cloud` | Judge; keep it a different family from the researcher |
| `WRITER_MODEL` | `nemotron-3-super:cloud` | Writer |
| `ROUTER_MODEL` | `nemotron-3-super:cloud` | Root agent (agent-only mode) |
| `CFG` | `agents/prisma-cortex-hub.yaml` | Agent config |
| `MODE` | `pipeline` | `agent` runs the self-contained root agent instead |
| `SAFETY` | `restricted` | docker-agent safety level |
| `OUT_DIR` | `outputs` | Where briefings go |
| `DOCKER_AGENT` | auto | Command to run docker-agent, e.g. `docker agent` |

Variables set on the command line win over `.env`.

### Scripts

| Command | Does | Model calls |
|---|---|---|
| `scripts/run.sh "<question>"` | Run the pipeline, then check the briefing | yes |
| `scripts/check-briefing.sh <briefing.md> [evidence.json]` | Heading, ASCII, length, sections, no `?` URLs, every cited URL was fetched and backs a SUPPORTED fact | no |
| `scripts/check-seeds.sh` | Start pages still exist | no |
| `scripts/gen-configs.py [--check]` | Generate (or verify) `agents/*.yaml` | no |
| `bench/run-all.sh [id ...]` | Benchmark; appends to `bench/results.tsv` | yes |
| `scripts/gen-tenant-config.sh`, `scripts/prisma-login.sh` | Tenant assistant setup | no |
| `scripts/make-svg.py dark\|light` | Render the last briefing as the README screenshot | no |

### Agent-only mode and sharing

Each config also contains a self-contained agent team (root -> researcher -> verifier -> writer), so it can run without this repo's scripts:

```bash
docker-agent run --exec --env-from-file .env agents/prisma-cortex-hub.yaml "your question"
MODE=agent scripts/run.sh "your question"           # same, plus the output checks
docker agent share push agents/prisma-cortex-hub.yaml ghcr.io/<you>/prisma-cortex-hub:latest
```

It is slower and less reliable than the pipeline (an LLM does the quote checking), but it is a single shareable file. Whoever runs it needs the model variables from `.env.example`.

### CI ([`.github/workflows`](.github/workflows))

| Workflow | When | Runs |
|---|---|---|
| `ci` | every push and PR | shellcheck, yamllint, unit tests, generated-config drift, `docker-agent debug config`, Docker build (amd64 + arm64), push to GHCR on `main` |
| `seed-urls` | nightly | `scripts/check-seeds.sh`, to catch moved documentation pages |
| `bench` | manual, or weekly if repo variable `BENCH_ENABLED=true` | benchmark on a self-hosted runner labelled `ollama` |

### Repository layout

```
agents/      generated agent configs (do not edit)
templates/   config template, per-agent scope files, tenant template
seeds/       documentation start pages per question type
scripts/     pipeline, run wrapper, checks, generators
bench/       benchmark questions and results baseline
tests/       unit tests
docs/images/ README screenshot
examples/    earlier experiments, not maintained
```

`outputs/`, `logs/` and `fetched/` are created by runs and git-ignored.

### Safety

- Agents can only fetch web pages. File writing, command execution and shell tools are denied, and runs use `--safety restricted`, so anything not allowed is refused rather than prompting.
- Fetching is limited to `cortex-docs.paloaltonetworks.com`, `docs.paloaltonetworks.com`, `www.paloaltonetworks.com`, `docs.prismacloud.io` and `pan.dev` (the broad agent also allows `docs-cortex.paloaltonetworks.com`). Exact hosts are listed because allowing `paloaltonetworks.com` would also allow its forums and blogs, which are not official documentation.
- Instructions found inside fetched pages are ignored.
- The Docker container runs as a non-root user, with a read-only filesystem and no Linux capabilities.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `docker-agent: command not found` | Step 1; check `PATH`, or set `DOCKER_AGENT="docker agent"` |
| `BRIEFING FAILED` with connection errors | Ollama is not running or `OLLAMA_BASE_URL` is wrong: `curl $OLLAMA_BASE_URL/models` |
| `401` / `unauthorized` from a `:cloud` model | Run `ollama signin` |
| `The following environment variables must be set` | `.env` is missing or incomplete: `cp .env.example .env` |
| Briefing `FAIL` in the checks | Rerun once (models vary). If it keeps failing, read `outputs/<run>.evidence.json` to see which facts were rejected and why |
| A start page fails `check-seeds.sh` | The docs page moved: find the new URL, update `seeds/*.txt`, regenerate |
| Docker: `permission denied` writing `outputs/` | Set `HOST_UID` / `HOST_GID` in `.env` and `mkdir -p outputs logs fetched` |
| Docker: cannot reach Ollama | Ollama on the host must listen on all interfaces for containers: `OLLAMA_HOST=0.0.0.0 ollama serve` |

## Known limitations

- Answers are only as good and current as the documentation pages at fetch time; they are not independent testing.
- Broad questions ("what does X cover") sometimes produce thin briefings when the researcher does not open enough content pages. Ask narrower questions.
- The Upgrade Helper mapping table on the docs site is flattened from merged cells; check mapping rows against the page.
- Benchmark baseline (`bench/results.tsv`, default models): 12/12 for both agents after the latest fixes.

## License

[MIT](LICENSE)
