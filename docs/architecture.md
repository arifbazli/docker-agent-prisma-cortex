# Architecture

This repository holds two related things:

1. **Docs briefing pipeline** (`scripts/run.sh` + `scripts/pipeline.py` +
   docker-agent): turn a question into a cited research brief.
2. **Guardrail policy generator** (`scripts/guardrail.py` and friends): turn a
   sanitized app profile into an advisory `policy.json`, tests and renderer reports.

Both share the same conventions: cloud-only Ollama models, stdlib Python only,
script-fetched sources, JSON data files.

## Repository overview

```mermaid
flowchart TB
    subgraph Config["Configuration"]
        T["templates/*.yaml.tmpl"]
        G["scripts/gen-configs.py"]
        A["agents/*.yaml (generated)"]
        T --> G --> A
    end

    subgraph Briefing["Docs briefing pipeline (pipeline.py)"]
        Q["Question"]
        P1["fetch + excerpt"]
        D["docker-agent (config)"]
        B["briefing.md + evidence.json"]
        Q --> P1 --> D --> B
    end

    subgraph Guardrail["Guardrail policy generator (guardrail.py)"]
        Prof["sanitized profile (JSON)"]
        Sel["select-controls.py (script)"]
        Sp["specialists (LLM)"]
        Qc["quote check (script)"]
        J["judge (LLM)"]
        Pol["policy.json + tests + renderers"]
        Prof --> Sel --> Sp --> Qc --> J --> Pol
    end

    Cat["guardrail-catalog.json (70 controls, 7 categories)"]
    Cat --> Sel
```

## Guardrail policy pipeline

Steps are colour coded: blue = script, amber = LLM, grey = data.

```mermaid
flowchart LR
    Profile["sanitized app profile"]:::data
    Catalog["guardrail-catalog.json"]:::data
    Profile --> Select["select-controls.py"]:::script
    Catalog --> Select
    Select --> Special["category specialists<br/>SPECIALIST_MODEL"]:::llm
    Special --> SourceKind["classify source_kind"]:::script
    SourceKind --> Quote["quote check on the page"]:::script
    Quote --> Judge["judge (cross-family)<br/>JUDGE_MODEL"]:::llm
    Judge --> Policy["policy.json<br/>tier: grounded / catalog-default / excluded<br/>source_kind per vendor value"]:::data
    Policy --> Assembler["assembler<br/>REVIEWER_MODEL"]:::llm
    Policy --> Render["render-bedrock / render-nemo"]:::script
    Assembler --> Tests["tests.jsonl"]
    Policy --> Check["check-policy.py"]:::script
    Check --> Render

    classDef script fill:#2563eb,color:#fff,stroke:#1e40af
    classDef llm fill:#f59e0b,color:#000,stroke:#b45309
    classDef data fill:#9ca3af,color:#000,stroke:#6b7280
```

## Evidence tiers

- **grounded**: at least one parameter is vendor-grounded (quote verified on the
  cited page and judged SUPPORTED). Vendor values override the catalog default
  for the same key.
- **catalog-default**: every parameter is a catalog `recommended_defaults`
  entry (opinionated baseline, NOT vendor-backed) or there are none.
- **excluded**: catalog control not selected for this profile, with a reason.

## Source kinds (per vendor value)

- `documented-default`: page states the default for the setting
- `documented-limit-or-enum`: page lists limits or allowed options and one was chosen
- `example-config`: value only appears inside an example/sample config block (forced by
  script when the quote sits in such a block). These are examples, not recommendations.
- `other`: none of the above
