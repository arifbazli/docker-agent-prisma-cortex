# grounded-ai-guardrails

Source-grounded AI guardrail policies, plus source-cited Prisma Cloud / Cortex Cloud briefings. Runs on [docker-agent](https://github.com/docker/docker-agent) with Ollama cloud models.

> Independent project; not affiliated with Palo Alto Networks, Docker, NVIDIA, AWS, OWASP or MITRE. Formerly `docker-agent-prisma-cortex` (old links redirect).

![How the repository works](docs/images/repo-overview.svg)

| Tool | In | Out |
|---|---|---|
| Guardrail policy generator | sanitized app profile | `policy.json`, tests, exceptions report, Bedrock and NeMo drafts |
| Docs briefing | Prisma Cloud / Cortex Cloud question | short briefing, every statement cites an official page |

Models only propose. A script checks every quote on the fetched page, and a judge from a different model family checks that it supports the value. Anything unverified is labeled `catalog-default` (not vendor-backed).

## Quick start

Needs `bash`, `curl`, `python3` 3.9+, [docker-agent](https://github.com/docker/docker-agent/releases) 1.152+ and [Ollama](https://ollama.com/download) with `ollama signin`. Cloud models only (`:cloud` / `-cloud`); local models are refused unless `ALLOW_LOCAL_MODELS=1`. Inputs go to ollama.com, so use sanitized profiles only.

```bash
git clone https://github.com/arifbazli/grounded-ai-guardrails.git
cd grounded-ai-guardrails
cp .env.example .env
python3 scripts/guardrail.py --no-llm bench/guardrail/rag-chatbot.profile.json   # no model calls
python3 scripts/guardrail.py bench/guardrail/rag-chatbot.profile.json            # with models
scripts/run.sh "Why migrate from Prisma Cloud to Cortex Cloud?"                  # docs briefing
```

Results land in `outputs/`; `outputs/.last-guardrail` holds the latest guardrail run.

## Guardrail pipeline

![Guardrail pipeline](docs/images/guardrail-pipeline.svg)

| Tier | Meaning |
|---|---|
| `grounded` | vendor quote found on the page and judged SUPPORTED |
| `catalog-default` | catalog baseline, not vendor-backed |
| `excluded` | not applicable to the profile (reason recorded) |

Measured over 12 runs: 3-12 grounded controls per profile; most of a policy is `catalog-default`. Output is advisory and needs human review.

## More

- [docs/guardrail-generator.md](docs/guardrail-generator.md): steps, outputs, example, measured results, checks
- [docs/docs-briefing.md](docs/docs-briefing.md): briefing tool, Docker, tenant assistant (experimental)
- [docs/settings.md](docs/settings.md): all variables and default models
- [docs/architecture.md](docs/architecture.md): diagrams

Development: edit `templates/`, `seeds/` or `schemas/` (never `agents/*.yaml`), then run `python3 scripts/gen-configs.py`, `python3 -m unittest discover -s tests` and `bench/guardrail/check-golden.sh`.

## License

[MIT](LICENSE)
