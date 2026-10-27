"""Turn grounded proposals into the canonical policy and its companion files.

Pure functions, no I/O except where noted, no model calls. Used by
scripts/guardrail.py and by the unit tests.

Evidence tiers (also in schemas/policy.schema.json):
  grounded         at least one parameter whose quote the script found on the
                   cited page AND the judge marked SUPPORTED
  catalog-default  selected control filled from the catalog by the script;
                   no vendor source and no parameters
  excluded         catalog control not selected for this profile
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY_SCHEMA = ROOT / "schemas" / "policy.schema.json"
TIER_TEXT = {
    "grounded": "grounded (quote verified on the vendor page and judged SUPPORTED)",
    "catalog-default": "catalog-default (from the catalog only, NOT vendor-backed)",
    "excluded": "excluded (not applicable to this profile)",
}


# --------------------------------------------------------------------------
# Policy
# --------------------------------------------------------------------------
def build_policy(profile: dict, catalog: dict, selection: dict, grounded: list[dict], run_id: str = ""):
    """Return (policy, conflicts). `grounded` holds proposals that passed the
    quote check and the judge. When two proposals give the same parameter a
    different value, the first is kept and the other is reported."""
    by_id = {c["id"]: c for c in catalog["controls"]}
    conflicts = []
    controls = []
    for cid in selection["selected"]:
        c = by_id[cid]
        params, seen = [], {}
        for g in (g for g in grounded if g["control_id"] == cid):
            for name, value in g["parameters"].items():
                if name in seen:
                    if seen[name] != value:
                        conflicts.append({"control_id": cid, "stage": "assembly",
                                          "reason": f"conflicting value for {name}: kept {seen[name]!r}, dropped {value!r}",
                                          "source_url": g["source_url"]})
                    continue
                seen[name] = value
                params.append({"name": name, "value": value, "rationale": g["rationale"] or "Documented setting.",
                               "source_url": g["source_url"], "source_quote": g["source_quote"]})
        controls.append({
            "control_id": cid, "category": c["category"], "name": c["name"], "description": c["description"],
            "severity": c["default_severity"], "enforcement_point": c["enforcement_point"],
            "targets": c["supported_targets"], "threats": c["threats"],
            "tier": "grounded" if params else "catalog-default", "parameters": params,
        })
    waivers = []
    for cat in catalog["categories"]:
        if not selection["by_category"][cat["id"]]:
            reasons = sorted({e["reason"].removeprefix("not applicable: ") for e in selection["excluded"]
                              if by_id[e["control_id"]]["category"] == cat["id"]})
            waivers.append({"category": cat["id"],
                            "reason": "No control in this category applies to the profile: " + "; ".join(reasons)})
    policy = {
        "schema_version": "1.0", "generator": "guardrail-policy-generator", "advisory": True,
        "catalog_version": catalog["catalog_version"], "run_id": run_id or "unknown", "profile": profile,
        "controls": controls, "waivers": waivers,
        "excluded": [{"control_id": e["control_id"], "tier": "excluded", "reason": e["reason"]} for e in selection["excluded"]],
    }
    return policy, conflicts


def validate_policy(policy: dict) -> list[str]:
    import jsonschema_lite as V
    return V.validate(policy, json.loads(POLICY_SCHEMA.read_text()))


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------
def fallback_test(c: dict) -> dict:
    return {
        "control_id": c["control_id"],
        "input": f"[synthetic] A request or event that violates '{c['name']}': {c['description']}",
        "expected_behavior": f"The {c['enforcement_point'].replace('_', ' ')} guardrail enforces '{c['name']}' "
                             f"(block, mask, require approval or alert) and records the decision.",
        "source": "catalog-fallback",
        "tier": c["tier"],
    }


def build_tests(policy: dict, proposed: list) -> tuple[list[dict], list[dict]]:
    """Return (tests, dropped). Keeps valid assembler tests for selected
    controls; adds a script-generated test for every control left without one."""
    ids = {c["control_id"]: c for c in policy["controls"]}
    tests, dropped = [], []
    for t in proposed if isinstance(proposed, list) else []:
        cid = t.get("control_id") if isinstance(t, dict) else None
        ok = (cid in ids and isinstance(t.get("input"), str) and t["input"].strip()
              and isinstance(t.get("expected_behavior"), str) and t["expected_behavior"].strip())
        if not ok:
            dropped.append({"control_id": cid if isinstance(cid, str) else "?", "stage": "assembler",
                            "reason": "test case malformed or for a control that is not selected",
                            "detail": json.dumps(t)[:200]})
            continue
        tests.append({"control_id": cid, "input": t["input"].strip(), "expected_behavior": t["expected_behavior"].strip(),
                      "source": "assembler", "tier": ids[cid]["tier"]})
    covered = {t["control_id"] for t in tests}
    tests += [fallback_test(c) for cid, c in ids.items() if cid not in covered]
    order = list(ids)
    tests.sort(key=lambda t: order.index(t["control_id"]))
    return tests, dropped


# --------------------------------------------------------------------------
# exceptions.md
# --------------------------------------------------------------------------
def _cell(text) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def exceptions_md(policy: dict, catalog: dict, dropped: list[dict], failed: list[str],
                  findings: list, tests: list[dict]) -> str:
    cats = [c["id"] for c in catalog["categories"]]
    names = {c["id"]: c["name"] for c in catalog["categories"]}
    tiers = {t: [c for c in policy["controls"] if c["tier"] == t] for t in ("grounded", "catalog-default")}
    waived = {w["category"]: w["reason"] for w in policy["waivers"]}
    out = [
        f"# Guardrail policy exceptions - {policy['profile'].get('name', 'profile')}",
        "",
        "> ADVISORY OUTPUT. A human must review every control, parameter and test before use.",
        "> Only **grounded** parameters are backed by a vendor page; **catalog-default** controls are",
        "> placeholders from the catalog and are NOT vendor-backed.",
        "",
        "## Summary",
        "",
        "| Tier | Controls |",
        "|---|---|",
        f"| {TIER_TEXT['grounded']} | {len(tiers['grounded'])} |",
        f"| {TIER_TEXT['catalog-default']} | {len(tiers['catalog-default'])} |",
        f"| {TIER_TEXT['excluded']} | {len(policy['excluded'])} |",
        f"| dropped proposals | {len(dropped)} |",
        f"| test cases (catalog-fallback) | {len(tests)} ({sum(t['source'] == 'catalog-fallback' for t in tests)}) |",
        "",
        "## Coverage by category",
        "",
        "| Category | Grounded | Catalog-default | Excluded | Status |",
        "|---|---|---|---|---|",
    ]
    by_cat = {c["control_id"]: c["category"] for c in policy["controls"]}
    excl_cat = {e["control_id"]: next(c["category"] for c in catalog["controls"] if c["id"] == e["control_id"])
                for e in policy["excluded"]}
    for cat in cats:
        g = sum(1 for c in tiers["grounded"] if c["category"] == cat)
        d = sum(1 for c in tiers["catalog-default"] if c["category"] == cat)
        x = sum(1 for v in excl_cat.values() if v == cat)
        status = "WAIVED" if cat in waived else "covered"
        out.append(f"| {names[cat]} | {g} | {d} | {x} | {status} |")
    out += ["", "## Waivers", ""]
    out += [f"- **{names[c]}**: {_cell(waived[c])}" for c in cats if c in waived] or ["None: every category has selected controls."]
    if failed:
        out += ["", "## Failed specialists", "",
                *[f"- **{c}**: the specialist returned no usable output; its controls are catalog-default." for c in failed]]
    out += ["", "## Catalog-default controls (not vendor-backed)", "",
            "No proposal for these controls survived the quote check and the judge. They keep the catalog's",
            "severity and enforcement point but have no parameters. Configure them by hand.", ""]
    out += [f"- `{c['control_id']}` {c['name']} ({c['category']})" for c in tiers["catalog-default"]] or ["None."]
    out += ["", "## Dropped proposals", "",
            "Every proposal that did not make it into policy.json, and why.", ""]
    if dropped:
        out += ["| Control | Stage | Reason | Detail |", "|---|---|---|---|"]
        out += [f"| `{_cell(d.get('control_id', '?'))}` | {_cell(d['stage'])} | {_cell(d['reason'])} | {_cell(d.get('detail', ''))[:160]} |"
                for d in dropped]
    else:
        out.append("None.")
    out += ["", "## Excluded controls", "", "| Control | Reason |", "|---|---|"]
    out += [f"| `{e['control_id']}` | {_cell(e['reason'])} |" for e in policy["excluded"]] or ["| - | none |"]
    out += ["", "## Reviewer findings (advisory)", ""]
    good = [f for f in findings if isinstance(f, dict)]
    out += [f"- **{_cell(f.get('severity', '?'))}** `{_cell(f.get('scope', '?'))}`: {_cell(f.get('issue', ''))} "
            f"Recommendation: {_cell(f.get('recommendation', ''))}" for f in good] or ["None."]
    return "\n".join(out) + "\n"
