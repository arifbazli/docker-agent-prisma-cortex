# Architecture

Back to the [README](../README.md). The guardrail pipeline diagram is in the README;
step details are in [guardrail-generator.md](guardrail-generator.md).

Both tools share the same conventions: Ollama cloud models only, standard-library
Python, source pages fetched by scripts, JSON data files, generated agent configs.

## Repository overview

```mermaid
flowchart TB
    Tmp[templates and scopes]
    Gen[gen configs]
    Agents[agents yaml]
    Seeds[start pages]
    Quest[question]
    Brief[briefing and evidence]
    Catalog[guardrail catalog and schemas]
    Prof[sanitized profile]
    Pol[policy and drafts]

    Tmp --> Gen
    Gen --> Agents
    Agents --> Brief
    Agents --> Pol
    Seeds --> Brief
    Catalog --> Pol
    Quest --> Brief
    Prof --> Pol

    classDef script fill:#2563eb,color:#fff,stroke:#1e40af
    classDef data fill:#9ca3af,color:#000,stroke:#6b7280
    class Gen script
    class Tmp,Agents,Seeds,Quest,Catalog,Prof,Pol,Brief data
```

## Docs briefing pipeline

Blue = script, amber = LLM step (with its model variable), grey = data.

```mermaid
flowchart LR
    Quest[question]
    Res[researcher]
    Qc[quote check]
    Judge[judge]
    Writer[writer]
    Chk[check briefing]
    Out[briefing and evidence]

    Quest --> Res
    Res --> Qc
    Qc --> Judge
    Judge --> Writer
    Writer --> Chk
    Chk --> Out

    classDef script fill:#2563eb,color:#fff,stroke:#1e40af
    classDef ai fill:#f59e0b,color:#000,stroke:#b45309
    classDef data fill:#9ca3af,color:#000,stroke:#6b7280
    class Qc,Chk script
    class Res,Judge,Writer ai
    class Quest,Out data
```

Amber steps (LLM) and their model settings:

| Amber step | Model setting |
|---|---|
| researcher | `RESEARCH_MODEL` |
| judge | `JUDGE_MODEL` |
| writer | `WRITER_MODEL` |

`MODE=agent` replaces the scripted steps with a root agent on `ROUTER_MODEL` inside
docker-agent. Details: [docs-briefing.md](docs-briefing.md).
