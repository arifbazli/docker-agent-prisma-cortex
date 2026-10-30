# Guardrail policy generator

`scripts/guardrail.py` turns a sanitized app profile into an advisory guardrail
policy. Back to the [README](../README.md); diagrams in [architecture.md](architecture.md).

## Usage

```bash
python3 scripts/guardrail.py --dry-run  bench/guardrail/tool-agent.profile.json   # selection + prompts, no model calls
python3 scripts/guardrail.py --no-llm   bench/guardrail/tool-agent.profile.json   # catalog defaults only, no model calls
python3 scripts/guardrail.py            bench/guardrail/tool-agent.profile.json   # live run
```

Options: `-c/--config`, `--out-dir`, `--timeout`, `--parallel` (see
[settings.md](settings.md)).

## App profile

A JSON file validated against [app-profile.schema.json](../schemas/app-profile.schema.json).
Required fields: `uses_rag`, `has_tools`, `tool_list`, `has_memory`, `handles_pii`,
`user_facing`, `autonomy_level`, `cloud`, `data_classification`,
`regulatory_context`; `name` is an optional short label. Describe the app's shape
only. Never put secrets, customer or tenant data in a profile.

Golden profiles: [rag-chatbot](../bench/guardrail/rag-chatbot.profile.json),
[tool-agent](../bench/guardrail/tool-agent.profile.json),
[memory-assistant](../bench/guardrail/memory-assistant.profile.json).

## Steps

1. **Select** (script). [select-controls.py](../scripts/select-controls.py) evaluates
   each rule in [guardrail-catalog.json](../seeds/guardrail-catalog.json) (70 controls,
   7 categories of 10) against the profile. Each control is selected or excluded with
   a reason; a category with no applicable control is waived with a reason.
2. **Fetch** (script). The vendor start pages are fetched once and cached under
   `fetched/guardrail/`.
3. **Propose** (LLM, `SPECIALIST_MODEL`). One specialist per category proposes a value
   per allowed key, with a source URL, an exact quote and a `source_kind`, or null.
4. **Check values** (script). Type, range and enum checks per key; numbers must
   appear in the quote.
5. **Check quotes** (script). The quote must be on the cited page.
6. **Judge** (LLM, `JUDGE_MODEL`, a different model family). Only SUPPORTED values
   are kept; a partly supported proposal is dropped.
7. **Assemble** (script plus LLM, `REVIEWER_MODEL`). Writes `policy.json`, tests and
   reviewer findings.
8. **Check and render** (script). [check-policy.py](../scripts/check-policy.py)
   validates the policy; [render-bedrock.py](../scripts/render-bedrock.py) and
   [render-nemo.py](../scripts/render-nemo.py) write drafts.

## Output files

Each run writes `outputs/<timestamp>-guardrail-<profile>/`; `outputs/.last-guardrail` holds the latest path.

| File | Content |
|---|---|
| `policy.json` | Controls with tiers, values, sources and source kinds |
| `exceptions.md` | Tier counts, waivers, catalog-default controls, dropped proposals |
| `tests.jsonl` | At least one test case per selected control |
| `evidence.json` | Counts, verdicts, timings and the `check-policy.py` result |
| `review.json` | Reviewer findings (empty with `--no-llm`) |
| `bedrock-guardrail.json`, `bedrock-report.md` | Amazon Bedrock Guardrails draft and what could not be rendered |
| `nemo-config.yml`, `nemo-report.md` | NVIDIA NeMo Guardrails draft and what could not be rendered |

## Example output

Trimmed from a live run on the `rag-chatbot` golden profile. One control from `policy.json`:

```json
{
  "control_id": "INPUT-10",
  "name": "Injection screening",
  "tier": "grounded",
  "parameters": [
    {
      "name": "prompt_attack_strength",
      "value": "LOW",
      "basis": "vendor-grounded",
      "source_kind": "documented-limit-or-enum",
      "source_url": "https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-content-filters.html",
      "source_quote": "Select None, Low, Medium, or High for the level of filtration you want to apply to each category."
    },
    {
      "name": "injection_action",
      "value": "reject",
      "basis": "catalog-default",
      "label": "opinionated baseline, not vendor-backed"
    }
  ]
}
```

The summary from the same run's `exceptions.md`:

```text
| Tier | Controls |
|---|---|
| grounded (quote verified on the vendor page and judged SUPPORTED) | 9 |
| catalog-default (catalog baseline values only, NOT vendor-backed) | 38 |
| excluded (not applicable to this profile) | 23 |
```

## Measured results

Grounded controls out of selected controls across all 12 runs in [bench/guardrail/results.tsv](../bench/guardrail/results.tsv) (4 per golden profile, default models):

| Golden profile | Selected | Grounded (min-max) |
|---|---|---|
| `rag-chatbot` | 47 of 70 | 4-12 |
| `tool-agent` | 36 of 70 | 3-7 |
| `memory-assistant` | 45 of 70 | 3-11 |

Results vary between runs, and most of every policy is `catalog-default`.

## Evidence tiers

- **grounded**: at least one value is vendor-grounded (quote on the page, judged
  SUPPORTED). A vendor value overrides the catalog default for the same key.
- **catalog-default**: every value comes from the catalog's `recommended_defaults`
  (opinionated baseline, not vendor-backed), or the control has none. Controls without
  defaults are listed in `exceptions.md` for manual configuration.
- **excluded**: not applicable to this profile, with a reason.

## Source kinds

Each vendor-grounded value has one `source_kind`:

| `source_kind` | Meaning |
|---|---|
| `documented-default` | The page states the default for the setting. |
| `documented-limit-or-enum` | The page lists limits or options, and one was chosen. |
| `example-config` | The value appears only in an example or sample block. A script forces this kind when the quote is in such a block. These values are examples, not recommendations. |
| `other` | None of the above. |

## check-policy.py

Runs at the end of every `guardrail.py` run and in CI. It checks the schema, catalog
IDs, duplicates, that every catalog control is selected or excluded, category waivers,
value keys and types, source rules per tier, and test coverage; with `--expected` it
also compares against a golden expected set. Exit codes: `0` pass, `1` checks failed,
`64` usage or unreadable input.

```bash
d="$(cat outputs/.last-guardrail)"
python3 scripts/check-policy.py "$d/policy.json" --tests "$d/tests.jsonl" \
  --expected bench/guardrail/rag-chatbot.expected.json
```

## Renderers

Bedrock and NeMo drafts contain only values that map to a real target field. Each
report lists the mapped values and everything that was not rendered. Bedrock denied
topics need human-written definitions.

## Benchmarks

- [check-golden.sh](../bench/guardrail/check-golden.sh): no model calls. Builds each
  golden profile with `--no-llm`, checks it against its `*.expected.json`, and runs
  mutation checks (removed control, duplicated control, mistyped value, catalog default
  claiming a source) that must fail.
- [run-live.sh](../bench/guardrail/run-live.sh) and [record.py](../bench/guardrail/record.py):
  live runs; one row per run in [results.tsv](../bench/guardrail/results.tsv).
## Limitations

- Output is advisory. A human must review every control, value and test before use.
- Grounding varies between runs; treat a run as a draft.
- The judge can pass weak values; the value checks reduce this but do not remove it.
- A partly supported proposal is dropped, not partly applied.
- Bedrock denied topics need human-written definitions.
- MITRE ATLAS links point to the site root.
- Prisma AIRS grounding is thin.

Roadmap: extract enums and ranges from vendor API schemas; make the tenant assistant template cloud-only.

