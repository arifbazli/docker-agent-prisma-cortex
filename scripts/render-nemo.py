#!/usr/bin/env python3
"""Render policy.json as a NVIDIA NeMo Guardrails config.yml (rails section).

usage: scripts/render-nemo.py outputs/<run>/policy.json [--out DIR]

Writes nemo-config.yml and nemo-report.md next to the policy (or into
--out). Only grounded parameters that map to a real NeMo Guardrails flow or
config field are emitted; everything else is listed as not rendered, with
its evidence tier. No model calls.

Exit codes: 0 ok, 64 usage error or invalid policy.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_common as R  # noqa: E402
import yamldump  # noqa: E402

BOOL_FLOWS = {
    "jailbreak_heuristics": ("input", "jailbreak detection heuristics"),
    "self_check_input": ("input", "self check input"),
    "content_safety_input": ("input", "content safety check input $model=content_safety"),
    "self_check_output": ("output", "self check output"),
    "content_safety_output": ("output", "content safety check output $model=content_safety"),
    "fact_checking": ("output", "self check facts"),
    "hallucination_check": ("output", "self check hallucination"),
}
MASK_FLOWS = {
    "mask_sensitive_data_on_input": "input",
    "mask_sensitive_data_on_output": "output",
    "mask_sensitive_data_on_retrieval": "retrieval",
}
INJECTIONS = {"sqli", "template", "code", "xss"}
INJECTION_ACTIONS = {"reject", "omit", "sanitize"}
# Presidio entity names used by NeMo sensitive data detection, plus aliases.
PRESIDIO = {e.lower(): e for e in (
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "IBAN_CODE", "IP_ADDRESS", "LOCATION",
    "DATE_TIME", "NRP", "MEDICAL_LICENSE", "URL", "US_SSN", "US_BANK_NUMBER", "US_DRIVER_LICENSE",
    "US_ITIN", "US_PASSPORT", "UK_NHS", "CRYPTO")}
PRESIDIO.update({"email": "EMAIL_ADDRESS", "phone": "PHONE_NUMBER", "name": "PERSON",
                 "credit_debit_card_number": "CREDIT_CARD", "us_social_security_number": "US_SSN",
                 "ssn": "US_SSN", "address": "LOCATION", "us_passport_number": "US_PASSPORT",
                 "uk_national_health_service_number": "UK_NHS"})
NOTES = [
    "Only the `rails` section is generated. Add your `models` section, and the prompts that the "
    "`self check ...` flows need (`self_check_input`, `self_check_output`, `self_check_facts`, ...).",
    "`content safety check ... $model=content_safety` expects a model named `content_safety` in `models`.",
    "Sensitive data detection uses Presidio entity names; Bedrock-style names are translated where an equivalent exists.",
]


TAKEN = "target field already set by a vendor-grounded value or an earlier control"


def _list(v):
    return v if isinstance(v, list) else [v]


def render(policy: dict):
    flows = {"input": [], "output": [], "retrieval": []}
    cfg, mapped, unsupported = {}, [], []

    def add_flow(direction, flow):
        if flow not in flows[direction]:
            flows[direction].append(flow)

    def ok(c, p, field, value=None):
        mapped.append(R.mapped_row(c, p, field, value))

    # Vendor-grounded values are placed first; a catalog default never
    # overwrites a target field that a vendor value (or an earlier control) set.
    for basis in ("vendor-grounded", "catalog-default"):
        for c in policy["controls"]:
            params = {p["name"]: p for p in c["parameters"]}
            if not params:
                if basis == "vendor-grounded":
                    unsupported.append(R.unsupported_row(c, None, ""))
                continue
            for name, p in params.items():
                if p["basis"] != basis:
                    continue
                v = p["value"]
                if name in BOOL_FLOWS:
                    direction, flow = BOOL_FLOWS[name]
                    if v is True:
                        add_flow(direction, flow)
                        ok(c, p, f"rails.{direction}.flows: {flow}")
                    else:
                        unsupported.append(R.unsupported_row(c, p, f"only {name}=true enables the '{flow}' rail"))
                elif name in ("length_per_perplexity_threshold", "prefix_suffix_perplexity_threshold"):
                    if name in cfg.get("jailbreak_detection", {}):
                        unsupported.append(R.unsupported_row(c, p, TAKEN))
                    elif isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                        cfg.setdefault("jailbreak_detection", {})[name] = v
                        ok(c, p, f"rails.config.jailbreak_detection.{name}")
                    else:
                        unsupported.append(R.unsupported_row(c, p, "threshold must be a number greater than 0"))
                elif name == "injection_detection_types":
                    vals = [str(x).strip().lower() for x in _list(v)]
                    if vals and all(x in INJECTIONS for x in vals):
                        inj = cfg.setdefault("injection_detection", {})
                        inj["injections"] = sorted(set(inj.get("injections", [])) | set(vals))
                        add_flow("output", "injection detection")
                        ok(c, p, "rails.config.injection_detection.injections + rails.output.flows: injection detection", vals)
                    else:
                        unsupported.append(R.unsupported_row(c, p, f"injection types must be from {sorted(INJECTIONS)}, got {v!r}"))
                elif name == "injection_action":
                    a = str(v).strip().lower()
                    if "action" in cfg.get("injection_detection", {}):
                        unsupported.append(R.unsupported_row(c, p, TAKEN))
                    elif a in INJECTION_ACTIONS and "injection_detection_types" in params:
                        cfg.setdefault("injection_detection", {})["action"] = a
                        ok(c, p, "rails.config.injection_detection.action", a)
                    else:
                        unsupported.append(R.unsupported_row(c, p, f"needs injection_detection_types in the same control and one of {sorted(INJECTION_ACTIONS)}"))
                elif name in MASK_FLOWS:
                    direction = MASK_FLOWS[name]
                    ents = [PRESIDIO.get(str(x).strip().lower()) for x in _list(params.get("pii_entities", {}).get("value", []))]
                    if v is not True:
                        unsupported.append(R.unsupported_row(c, p, f"only {name}=true enables masking"))
                    elif not ents or None in ents:
                        unsupported.append(R.unsupported_row(c, p, "needs grounded pii_entities with Presidio-compatible names in the same control"))
                    else:
                        sdd = cfg.setdefault("sensitive_data_detection", {}).setdefault(direction, {})
                        sdd["entities"] = sorted(set(sdd.get("entities", [])) | set(ents))
                        add_flow(direction, f"mask sensitive data on {direction}")
                        ok(c, p, f"rails.{direction}.flows: mask sensitive data on {direction} + sensitive_data_detection.{direction}.entities", ents)
                elif name == "pii_entities":
                    if any(k in params for k in MASK_FLOWS):
                        ok(c, p, "rails.config.sensitive_data_detection.<direction>.entities")
                    else:
                        unsupported.append(R.unsupported_row(c, p, "NeMo masking needs mask_sensitive_data_on_input/output/retrieval=true in the same control"))
                elif name == "pii_score_threshold":
                    dirs = [d for k, d in MASK_FLOWS.items() if params.get(k, {}).get("value") is True]
                    if isinstance(v, (int, float)) and 0 <= v <= 1 and dirs:
                        for d in dirs:
                            cfg.setdefault("sensitive_data_detection", {}).setdefault(d, {})["score_threshold"] = v
                        ok(c, p, "rails.config.sensitive_data_detection.<direction>.score_threshold")
                    else:
                        unsupported.append(R.unsupported_row(c, p, "needs a 0-1 number and a mask_sensitive_data_on_* rail in the same control"))
                else:
                    unsupported.append(R.unsupported_row(c, p, "no NeMo Guardrails flow or config field for this parameter (implement in your gateway/app)"))

    rails = {}
    if cfg:
        rails["config"] = cfg
    for d in ("input", "output", "retrieval"):
        if flows[d]:
            rails[d] = {"flows": flows[d]}
    return {"rails": rails} if rails else {}, mapped, unsupported, NOTES


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Render policy.json for NVIDIA NeMo Guardrails (no LLM).")
    ap.add_argument("policy")
    ap.add_argument("--out")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 64 if e.code else 0
    try:
        policy = R.load_policy(args.policy)
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 64
    config, mapped, unsupported, notes = render(policy)
    out = Path(args.out or Path(args.policy).parent)
    out.mkdir(parents=True, exist_ok=True)
    header = (f"# ADVISORY NeMo Guardrails rails generated from {Path(args.policy).name} (run {policy.get('run_id', '')}).\n"
              "# Review before use; see nemo-report.md for what was not rendered.\n")
    (out / "nemo-config.yml").write_text(header + (yamldump.dump(config) if config else "{}\n"), encoding="utf-8")
    (out / "nemo-report.md").write_text(R.report_md("NVIDIA NeMo Guardrails", policy, mapped, unsupported, notes), encoding="utf-8")
    print(f"nemo: {len(mapped)} mapped, {len(unsupported)} not rendered -> {out}/nemo-config.yml, nemo-report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
