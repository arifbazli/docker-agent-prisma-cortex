#!/usr/bin/env python3
"""Check a generated guardrail policy (no model calls).

usage: scripts/check-policy.py outputs/<run>/policy.json [--tests outputs/<run>/tests.jsonl]
                               [--expected bench/guardrail/<profile>.expected.json]

Checks:
  - policy.json matches schemas/policy.schema.json
  - every control id exists in the catalog; no id appears twice; every
    catalog control is either selected (controls) or excluded, exactly once
  - each of the 7 categories has controls or exactly one waiver, never both
  - control category matches the catalog
  - parameters: allowed key, value type (catalog value_types), no duplicate
    keys; vendor-grounded values need an https source_url outside banned
    paths, a source_quote, any number in the quote and the quote about the
    setting; catalog-default values need the "not vendor-backed" label
  - tier is "grounded" exactly when a vendor-grounded parameter exists
  - with --tests: at least one test per selected control, none for others
  - with --expected: the selected set equals the golden expected set

Exit codes: 0 ok, 1 checks failed, 64 usage / unreadable input.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import guardrail_policy as GP  # noqa: E402
import guardrail_values as GV  # noqa: E402
import pipeline as P  # noqa: E402

CATALOG = ROOT / "seeds" / "guardrail-catalog.json"


def check(policy: dict, catalog: dict, tests: list | None = None, expected: dict | None = None) -> list[str]:
    errors = [f"schema: {e}" for e in GP.validate_policy(policy)]
    if errors:
        return errors  # the rest assumes the schema holds
    by_id = {c["id"]: c for c in catalog["controls"]}
    selected = [c["control_id"] for c in policy["controls"]]
    excluded = [e["control_id"] for e in policy["excluded"]]
    for cid in selected + excluded:
        if cid not in by_id:
            errors.append(f"{cid}: not in the catalog")
    for cid in sorted({c for c in selected + excluded if (selected + excluded).count(c) > 1}):
        errors.append(f"{cid}: appears more than once")
    missing = sorted(set(by_id) - set(selected) - set(excluded))
    if missing:
        errors.append(f"catalog controls neither selected nor excluded: {missing}")

    waived = [w["category"] for w in policy["waivers"]]
    for cat in [c["id"] for c in catalog["categories"]]:
        has = any(by_id.get(cid, {}).get("category") == cat for cid in selected)
        n_waivers = waived.count(cat)
        if not has and n_waivers != 1:
            errors.append(f"category {cat}: no controls and no waiver")
        if has and n_waivers:
            errors.append(f"category {cat}: has controls but is also waived")
        if n_waivers > 1:
            errors.append(f"category {cat}: waived more than once")

    for c in policy["controls"]:
        cid = c["control_id"]
        cat = by_id.get(cid)
        if not cat:
            continue
        if c["category"] != cat["category"]:
            errors.append(f"{cid}: category {c['category']} != catalog {cat['category']}")
        names = [p["name"] for p in c["parameters"]]
        for dup in sorted({n for n in names if names.count(n) > 1}):
            errors.append(f"{cid}.{dup}: parameter appears more than once")
        vendor = False
        for p in c["parameters"]:
            where = f"{cid}.{p['name']}"
            spec = cat["value_types"].get(p["name"])
            if spec is None:
                errors.append(f"{where}: key not in allowed_parameter_keys")
                continue
            if p["basis"] == "vendor-grounded":
                vendor = True
                url, quote = p.get("source_url", ""), p.get("source_quote", "")
                if not url or not quote:
                    errors.append(f"{where}: vendor-grounded value without source_url and source_quote")
                    continue
                if p.get("source_kind") not in {"documented-default", "documented-limit-or-enum", "example-config", "other"}:
                    errors.append(f"{where}: vendor-grounded value needs a valid source_kind")
                    continue
                if P.banned_url(url):
                    errors.append(f"{where}: {P.banned_url(url)}")
                _, why = GV.check_value(spec, p["value"], quote)
            else:
                if p.get("label") != GP.DEFAULT_LABEL:
                    errors.append(f"{where}: catalog-default value must be labelled '{GP.DEFAULT_LABEL}'")
                if p.get("source_url") or p.get("source_quote"):
                    errors.append(f"{where}: catalog-default value must not cite a vendor source")
                if "source_kind" in p:
                    errors.append(f"{where}: catalog-default value must not carry a source_kind")
                _, why = GV.check_value(spec, p["value"])
            if why:
                errors.append(f"{where}: value type: {why}")
        if (c["tier"] == "grounded") != vendor:
            errors.append(f"{cid}: tier {c['tier']} but vendor-grounded parameters: {vendor}")

    if tests is not None:
        covered = {}
        for i, t in enumerate(tests, 1):
            if not isinstance(t, dict) or not all(isinstance(t.get(k), str) and t[k].strip()
                                                  for k in ("control_id", "input", "expected_behavior")):
                errors.append(f"tests.jsonl line {i}: needs control_id, input, expected_behavior")
                continue
            covered[t["control_id"]] = covered.get(t["control_id"], 0) + 1
        for cid in selected:
            if not covered.get(cid):
                errors.append(f"{cid}: no test case")
        for cid in sorted(set(covered) - set(selected)):
            errors.append(f"{cid}: test case for a control that is not selected")

    if expected is not None:
        want = expected["expected_selected"]
        if sorted(selected) != sorted(want):
            errors.append(f"selected controls differ from expected: missing {sorted(set(want) - set(selected))}, "
                          f"unexpected {sorted(set(selected) - set(want))}")
    return errors


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check a generated guardrail policy (no LLM).")
    ap.add_argument("policy")
    ap.add_argument("--tests")
    ap.add_argument("--expected")
    ap.add_argument("--catalog", default=str(CATALOG))
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 64 if e.code else 0
    try:
        policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
        catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
        tests = None
        if args.tests:
            tests = [json.loads(ln) for ln in Path(args.tests).read_text(encoding="utf-8").splitlines() if ln.strip()]
        expected = json.loads(Path(args.expected).read_text(encoding="utf-8")) if args.expected else None
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 64
    errors = check(policy, catalog, tests, expected)
    for e in errors:
        print(f"FAIL: {e}")
    if errors:
        print(f"FAILED ({len(errors)} problem(s))")
        return 1
    n = GP.counts(policy)
    print(f"PASS (controls): {n['grounded']} grounded, {n['catalog_default']} catalog-default, {n['excluded']} excluded; "
          f"parameters: {n['parameters_vendor_grounded']} vendor-grounded, {n['parameters_catalog_default']} catalog-default")
    return 0


if __name__ == "__main__":
    sys.exit(main())
