#!/usr/bin/env python3
"""Render policy.json as an Amazon Bedrock Guardrails CreateGuardrail request body.

usage: scripts/render-bedrock.py outputs/<run>/policy.json [--out DIR]

Writes bedrock-guardrail.json and bedrock-report.md next to the policy (or
into --out). Only grounded parameters that map to a real CreateGuardrail
field are emitted; everything else is listed as not rendered, with its
evidence tier. No model calls.

Exit codes: 0 ok, 64 usage error or invalid policy.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import render_common as R  # noqa: E402

STRENGTH = {s.lower(): s for s in ("NONE", "LOW", "MEDIUM", "HIGH")}
CATEGORIES = {s.lower(): s for s in ("SEXUAL", "VIOLENCE", "HATE", "INSULTS", "MISCONDUCT")}
PII_ACTION = {"block": "BLOCK", "anonymize": "ANONYMIZE", "mask": "ANONYMIZE", "redact": "ANONYMIZE"}
# PiiEntityType values accepted by CreateGuardrail, plus common aliases.
PII_TYPES = {t.lower(): t for t in (
    "ADDRESS", "AGE", "AWS_ACCESS_KEY", "AWS_SECRET_KEY", "CA_HEALTH_NUMBER", "CA_SOCIAL_INSURANCE_NUMBER",
    "CREDIT_DEBIT_CARD_CVV", "CREDIT_DEBIT_CARD_EXPIRY", "CREDIT_DEBIT_CARD_NUMBER", "DRIVER_ID", "EMAIL",
    "INTERNATIONAL_BANK_ACCOUNT_NUMBER", "IP_ADDRESS", "LICENSE_PLATE", "MAC_ADDRESS", "NAME", "PASSWORD",
    "PHONE", "PIN", "SWIFT_CODE", "UK_NATIONAL_HEALTH_SERVICE_NUMBER", "UK_NATIONAL_INSURANCE_NUMBER",
    "UK_UNIQUE_TAXPAYER_REFERENCE_NUMBER", "URL", "USERNAME", "US_BANK_ACCOUNT_NUMBER", "US_BANK_ROUTING_NUMBER",
    "US_INDIVIDUAL_TAX_IDENTIFICATION_NUMBER", "US_PASSPORT_NUMBER", "US_SOCIAL_SECURITY_NUMBER",
    "VEHICLE_IDENTIFICATION_NUMBER")}
PII_TYPES.update({"email_address": "EMAIL", "phone_number": "PHONE", "person": "NAME", "credit_card": "CREDIT_DEBIT_CARD_NUMBER",
                  "us_ssn": "US_SOCIAL_SECURITY_NUMBER", "ssn": "US_SOCIAL_SECURITY_NUMBER", "iban_code": "INTERNATIONAL_BANK_ACCOUNT_NUMBER",
                  "us_passport": "US_PASSPORT_NUMBER", "us_bank_number": "US_BANK_ACCOUNT_NUMBER", "us_itin": "US_INDIVIDUAL_TAX_IDENTIFICATION_NUMBER"})


def _list(v):
    return v if isinstance(v, list) else [v]


def render(policy: dict):
    body = {
        "name": f"advisory-{policy['profile'].get('name', 'profile')}"[:50],
        "description": f"ADVISORY draft generated from policy {policy.get('run_id', '')}; review before use.",
        "blockedInputMessaging": "Sorry, I can't help with that request.",
        "blockedOutputsMessaging": "Sorry, I can't provide that response.",
    }
    content, words, managed, pii, grounding = {}, [], False, {}, {}
    mapped, unsupported = [], []

    def ok(c, p, field, value=None):
        mapped.append({"control_id": c["control_id"], "tier": c["tier"], "parameter": p["name"],
                       "value": p["value"] if value is None else value, "field": field})

    for c in policy["controls"]:
        params = {p["name"]: p for p in c["parameters"]}
        if not params:
            unsupported.append(R.unsupported_row(c, None, ""))
            continue
        for name, p in params.items():
            v = p["value"]
            if name == "prompt_attack_strength":
                s = R.norm_enum(v, STRENGTH)
                if s:
                    content["PROMPT_ATTACK"] = {"type": "PROMPT_ATTACK", "inputStrength": s, "outputStrength": "NONE"}
                    ok(c, p, "contentPolicyConfig.filtersConfig[PROMPT_ATTACK].inputStrength", s)
                else:
                    unsupported.append(R.unsupported_row(c, p, f"value {v!r} is not NONE/LOW/MEDIUM/HIGH"))
            elif name == "content_filter_strength":
                s = R.norm_enum(v, STRENGTH)
                cats = [R.norm_enum(x, CATEGORIES) for x in _list(params.get("content_filter_categories", {}).get("value", []))]
                if not s:
                    unsupported.append(R.unsupported_row(c, p, f"value {v!r} is not NONE/LOW/MEDIUM/HIGH"))
                elif not cats or None in cats:
                    unsupported.append(R.unsupported_row(c, p, "needs grounded content_filter_categories from SEXUAL, VIOLENCE, HATE, INSULTS, MISCONDUCT in the same control"))
                else:
                    for cat in cats:
                        content[cat] = {"type": cat, "inputStrength": s, "outputStrength": s}
                    ok(c, p, f"contentPolicyConfig.filtersConfig[{','.join(cats)}].input/outputStrength", s)
            elif name == "content_filter_categories":
                if "content_filter_strength" not in params:
                    unsupported.append(R.unsupported_row(c, p, "needs a grounded content_filter_strength in the same control"))
                else:
                    ok(c, p, "contentPolicyConfig.filtersConfig[].type")
            elif name == "profanity_filter":
                if v is True:
                    managed = True
                    ok(c, p, "wordPolicyConfig.managedWordListsConfig[PROFANITY]")
                else:
                    unsupported.append(R.unsupported_row(c, p, "only profanity_filter=true maps to a managed word list"))
            elif name == "blocked_words":
                vals = [str(x) for x in _list(v) if str(x).strip()]
                if vals:
                    words += [w for w in vals if w not in words]
                    ok(c, p, "wordPolicyConfig.wordsConfig[].text", vals)
                else:
                    unsupported.append(R.unsupported_row(c, p, "no words given"))
            elif name == "pii_entities":
                action = R.norm_enum(params.get("pii_action", {}).get("value", ""), PII_ACTION)
                types = [PII_TYPES.get(str(x).strip().lower()) for x in _list(v)]
                if not action:
                    unsupported.append(R.unsupported_row(c, p, "needs a grounded pii_action (block or anonymize/mask) in the same control"))
                elif None in types:
                    bad = [x for x, t in zip(_list(v), types) if t is None]
                    unsupported.append(R.unsupported_row(c, p, f"not Bedrock PII types: {bad}"))
                else:
                    for t in types:
                        pii[t] = {"type": t, "action": action}
                    ok(c, p, "sensitiveInformationPolicyConfig.piiEntitiesConfig[]", types)
            elif name == "pii_action":
                if "pii_entities" not in params:
                    unsupported.append(R.unsupported_row(c, p, "needs grounded pii_entities in the same control"))
                elif R.norm_enum(v, PII_ACTION):
                    ok(c, p, "sensitiveInformationPolicyConfig.piiEntitiesConfig[].action", R.norm_enum(v, PII_ACTION))
                else:
                    unsupported.append(R.unsupported_row(c, p, f"value {v!r} is not block/anonymize"))
            elif name in ("grounding_threshold", "relevance_threshold"):
                kind = "GROUNDING" if name == "grounding_threshold" else "RELEVANCE"
                if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 0.99:
                    grounding[kind] = {"type": kind, "threshold": v}
                    ok(c, p, f"contextualGroundingPolicyConfig.filtersConfig[{kind}].threshold")
                else:
                    unsupported.append(R.unsupported_row(c, p, f"threshold must be a number from 0 to 0.99, got {v!r}"))
            elif name == "denied_topics":
                unsupported.append(R.unsupported_row(c, p, "topicPolicyConfig needs a definition per topic, which only a human can write"))
            else:
                unsupported.append(R.unsupported_row(c, p, "no Bedrock Guardrails field for this parameter (implement in your gateway/app)"))

    if content:
        body["contentPolicyConfig"] = {"filtersConfig": list(content.values())}
    if words or managed:
        body["wordPolicyConfig"] = {}
        if words:
            body["wordPolicyConfig"]["wordsConfig"] = [{"text": w} for w in words]
        if managed:
            body["wordPolicyConfig"]["managedWordListsConfig"] = [{"type": "PROFANITY"}]
    if pii:
        body["sensitiveInformationPolicyConfig"] = {"piiEntitiesConfig": list(pii.values())}
    if grounding:
        body["contextualGroundingPolicyConfig"] = {"filtersConfig": list(grounding.values())}
    notes = ["`name`, `description`, `blockedInputMessaging` and `blockedOutputsMessaging` are required by "
             "CreateGuardrail; their text is a placeholder, not grounded. Edit it."]
    return body, mapped, unsupported, notes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Render policy.json for Amazon Bedrock Guardrails (no LLM).")
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
    body, mapped, unsupported, notes = render(policy)
    out = Path(args.out or Path(args.policy).parent)
    out.mkdir(parents=True, exist_ok=True)
    (out / "bedrock-guardrail.json").write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    (out / "bedrock-report.md").write_text(R.report_md("Amazon Bedrock Guardrails", policy, mapped, unsupported, notes), encoding="utf-8")
    print(f"bedrock: {len(mapped)} mapped, {len(unsupported)} not rendered -> {out}/bedrock-guardrail.json, bedrock-report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
