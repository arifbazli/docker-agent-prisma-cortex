#!/usr/bin/env python3
"""Select the guardrail controls that apply to an app profile.

usage: scripts/select-controls.py PROFILE.json [--ids | --lines] [--catalog seeds/guardrail-catalog.json]

Deterministic: evaluates each control's `applies_when` rule from the
catalog against the profile. No model is involved.

Output (stdout, JSON): {"selected": [ids], "excluded": [{"control_id", "reason"}],
"by_category": {category: [ids]}}. With --ids, one selected id per line.
With --lines, the PROFILE: line and SELECTED CONTROLS: block the agent-only
mode root agent expects.

Exit codes: 0 ok, 64 usage error or invalid profile/catalog.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import jsonschema_lite as V  # noqa: E402
import guardrail_values as GV  # noqa: E402

CATALOG = ROOT / "seeds" / "guardrail-catalog.json"
PROFILE_SCHEMA = ROOT / "schemas" / "app-profile.schema.json"
CATALOG_SCHEMA = ROOT / "schemas" / "catalog.schema.json"


def load_catalog(path: Path = CATALOG) -> dict:
    catalog = json.loads(path.read_text(encoding="utf-8"))
    V.check(catalog, json.loads(CATALOG_SCHEMA.read_text()))
    return catalog


def validate_profile(profile: dict) -> list[str]:
    return V.validate(profile, json.loads(PROFILE_SCHEMA.read_text()))


def _fmt(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(map(str, value)) + "]"
    return str(value)


def describe(cond: dict) -> str:
    f, op, v = cond["field"], cond["op"], cond.get("value")
    return {
        "eq": f"{f} == {_fmt(v)}",
        "ne": f"{f} != {_fmt(v)}",
        "in": f"{f} in {_fmt(v)}",
        "contains_any": f"{f} contains any of {_fmt(v)}",
        "nonempty": f"{f} is not empty",
    }[op]


def holds(cond: dict, profile: dict) -> bool:
    actual = profile[cond["field"]]
    op, value = cond["op"], cond.get("value")
    if op == "eq":
        return actual == value
    if op == "ne":
        return actual != value
    if op == "in":
        return actual in value
    if op == "contains_any":
        return bool(set(actual) & set(value))
    if op == "nonempty":
        return len(actual) > 0
    raise ValueError(f"unknown op {op!r}")


def applies(rule: dict, profile: dict) -> tuple[bool, str]:
    """Return (applies, reason-if-not)."""
    conds = rule["conditions"]
    if not conds:
        return True, ""
    results = [(c, holds(c, profile)) for c in conds]
    if rule["match"] == "all":
        failed = [describe(c) for c, ok in results if not ok]
        return (not failed), "requires " + " and ".join(failed)
    ok = any(r for _, r in results)
    return ok, "requires one of: " + "; ".join(describe(c) for c in conds)


def control_line(c: dict) -> str:
    """One control as the specialists receive it."""
    keys = ", ".join(f"{k} ({GV.type_label(c['value_types'][k])})" for k in c["allowed_parameter_keys"])
    return f"{c['id']} | {c['category']} | {c['name']} | {c['description']} | keys: {keys}"


def select(profile: dict, catalog: dict) -> dict:
    selected, excluded = [], []
    by_category = {c["id"]: [] for c in catalog["categories"]}
    for ctl in catalog["controls"]:
        ok, reason = applies(ctl["applies_when"], profile)
        if ok:
            selected.append(ctl["id"])
            by_category[ctl["category"]].append(ctl["id"])
        else:
            excluded.append({"control_id": ctl["id"], "reason": f"not applicable: {reason}"})
    return {"selected": selected, "excluded": excluded, "by_category": by_category}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Select guardrail controls for an app profile (no LLM).")
    ap.add_argument("profile")
    ap.add_argument("--ids", action="store_true", help="print selected ids only, one per line")
    ap.add_argument("--lines", action="store_true", help="print the message for agent-only mode")
    ap.add_argument("--catalog", default=str(CATALOG))
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 64 if e.code else 0
    try:
        profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
        catalog = load_catalog(Path(args.catalog))
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 64
    errors = validate_profile(profile)
    if errors:
        print("invalid profile:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 64
    result = select(profile, catalog)
    if args.ids:
        print("\n".join(result["selected"]))
    elif args.lines:
        by_id = {c["id"]: c for c in catalog["controls"]}
        print("PROFILE: " + json.dumps(profile, sort_keys=True))
        print("SELECTED CONTROLS:")
        print("\n".join(control_line(by_id[i]) for i in result["selected"]))
    else:
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
