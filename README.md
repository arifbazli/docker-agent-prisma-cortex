# docker-agent-prisma-cortex

> Independent research project. Not affiliated with or endorsed by Palo Alto Networks or Docker.

A Docker Agent pipeline that answers Palo Alto Networks product questions, mainly Prisma Cloud to Cortex Cloud migration, using only official documentation. Every claim in the output is tied to a quote that a second agent re-checks against the cited page.

CLI only, no Docker Desktop, small disk footprint. Developed on Debian (WSL2) with Ollama cloud models.

## Quick start

```bash
# from the repo root
scripts/run.sh "Why migrate from Prisma Cloud to Cortex Cloud?"
```

A run takes about 5-8 minutes. Answer `a` at the first fetch prompt, or use `YOLO=1 scripts/run.sh "..."` to skip prompts.

To run the Cortex Cloud-only agent instead (see [Agents](#agents) below):

```bash
CFG='agents/#2Cortex-Cloud-Hub.yaml' scripts/run.sh "What does Cortex Cloud AI-SPM monitor?"
```

Without the wrapper:

```bash
docker-agent run --exec 'agents/#1Prisma-Cortex-Product-Hub.yaml' "your question"
```

The filename contains `#`. Always quote it, and URL-encode it as `%23` in web links.

### Prerequisites

- `docker-agent` CLI
- [Ollama](https://ollama.com) on `http://localhost:11434` with access to `nemotron-3-super:cloud` and `nemotron-3-ultra:cloud`
- `bash`, `curl`, `python3` with PyYAML (`sudo apt-get install -y python3-yaml`)

## Example run

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/images/docker-agent-run-dark.svg">
  <img alt="Docker Agent run: Prisma Cloud to Cortex Cloud migration briefing" src="docs/images/docker-agent-run-light.svg">
</picture>

## How it works

```
question -> researcher -> verifier -> writer -> briefing
```

| Agent | Model | Job |
|---|---|---|
| root | nemotron-3-super | Passes each step's output to the next, unchanged |
| researcher | nemotron-3-super | Fetches documentation pages, extracts facts with exact quotes |
| verifier | nemotron-3-ultra | Re-fetches each URL, confirms the quote, assigns a verdict |
| writer | nemotron-3-super | Writes the briefing from SUPPORTED facts only |

Rules enforced in the config:

- Quotes come only from real documentation pages. Any URL containing `?` is rejected, including the docs `?ask=` endpoint, which returns generated answers.
- Fetched content is treated as data. Instructions inside pages are ignored.
- Migration questions start from fixed seed pages and must produce reasons, Prisma-to-Cortex mappings and manual-work caveats.
- Output is ASCII only.

## Output

```
# PANW Briefing: <topic>
**Bottom line:** ...
**Why move** / **How migration works** / **Mapping** / **Manual work** / **To confirm** / **Sources**
```

Special results: `OUT OF SCOPE: ...`, `NO FACTS FOUND: ...`, `BRIEFING FAILED: ...`, or a briefing whose bottom line says no claims could be verified.

## Testing

| Command | What it checks | Model calls |
|---|---|---|
| `scripts/check-seeds.sh` | Seed URLs in the config still return real pages | no |
| `scripts/check-briefing.sh <briefing> [log]` | No `?` URLs, ASCII only, length, sections, cited URLs were fetched, not all claims rejected | no |
| `bench/run-all.sh [id ...]` | Runs the questions in `bench/questions.txt`, appends pass/fail and timing to `bench/results.tsv` | yes |

`CFG=path/to.yaml bench/run-all.sh` runs the same questions against another config, for comparing models or prompts.

## Layout

```
agents/    agent configs
scripts/   run wrapper and checks
bench/     question set and results
docs/      notes
```

`logs/` and `outputs/` are generated and git-ignored.

## Agents

| File | Purpose |
|---|---|
| `agents/#1Prisma-Cortex-Product-Hub.yaml` | Main pipeline (above): broad PANW scope, deepest on Prisma Cloud + Cortex Cloud |
| `agents/#2Cortex-Cloud-Hub.yaml` | Cortex Cloud only (CSPM, CWPP, CIEM, AppSec, AI-SPM, Platform/data lake); Prisma Cloud appears only as migration context. Run with `CFG='agents/#2Cortex-Cloud-Hub.yaml' scripts/run.sh "..."` |
| `agents/20-pan-research.yaml` | Earlier version, kept for comparison |
| `agents/local.yaml`, `02-*`, `03-*`, `04-*` | Earlier experiments: single agent, file reader, team, writer/critic |

## Safety

- `write_*` and `exec_*` tools are denied.
- Fetching is limited to `paloaltonetworks.com`, `prismacloud.io`, `pan.dev` and `cortex-docs.paloaltonetworks.com`.
- Nothing is written outside this repo's `logs/` and `outputs/`.

## Known limitations

- Small models vary between runs. If a run fails the checks, run it again before changing prompts.
- The docs Upgrade Helper table is flattened from merged cells, so some rows are easy to misread. Check mapping rows against the page.
- Briefings reflect vendor documentation, not independent testing, and are only as current as the pages at fetch time.
