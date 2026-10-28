# Architecture

Back to the [README](../README.md). The guardrail pipeline diagram is in the README;
step details are in [guardrail-generator.md](guardrail-generator.md).

Both tools share the same conventions: Ollama cloud models only, standard-library
Python, source pages fetched by scripts, JSON data files, generated agent configs.

## Repository overview

![Repository overview](images/repo-overview.svg)

<details>
<summary>Mermaid source</summary>

```mermaid
flowchart TB
    subgraph Config["Configuration"]
        T["templates/*.yaml.tmpl + templates/scopes/*.txt"]
        G["scripts/gen-configs.py"]
        A["agents/*.yaml (generated)"]
        T --> G --> A
    end

    subgraph Briefing["Docs briefing (scripts/run.sh, scripts/pipeline.py)"]
        Q["question"] --> B["briefing.md + evidence.json"]
    end

    subgraph Guardrail["Guardrail generator (scripts/guardrail.py)"]
        Prof["sanitized profile"] --> Pol["policy.json + tests + renderer drafts"]
    end

    Seeds["seeds/*.txt (start pages)"] --> Briefing
    Cat["seeds/guardrail-catalog.json + schemas/*.json"] --> Guardrail
    A --> Briefing
    A --> Guardrail
```

</details>

## Docs briefing pipeline

Blue = script, amber = LLM step (with its model variable), grey = data.

![Docs briefing pipeline](images/docs-briefing-pipeline.svg)

Amber steps (LLM) and their model settings:

| Amber step | Model setting |
|---|---|
| Researcher | RESEARCH_MODEL |
| Judge | JUDGE_MODEL |
| Writer | WRITER_MODEL |

Legend: amber = cloud LLM step, blue = script, grey = data.

<details>
<summary>Mermaid source</summary>

```mermaid
flowchart LR
    Q["question"]:::data --> R["researcher<br/>RESEARCH_MODEL"]:::llm
    R --> QC["quote check on fetched page"]:::script
    QC --> J["judge<br/>JUDGE_MODEL"]:::llm
    J --> W["writer<br/>WRITER_MODEL"]:::llm
    W --> C["check-briefing.sh"]:::script
    C --> B["outputs/run.md + evidence.json"]:::data

    classDef script fill:#2563eb,color:#fff,stroke:#1e40af
    classDef llm fill:#f59e0b,color:#000,stroke:#b45309
    classDef data fill:#9ca3af,color:#000,stroke:#6b7280
```

</details>

`MODE=agent` replaces the scripted steps with a root agent on `ROUTER_MODEL` inside
docker-agent. Details: [docs-briefing.md](docs-briefing.md).
