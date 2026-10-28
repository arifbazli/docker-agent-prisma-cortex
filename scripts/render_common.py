"""Shared helpers for the policy renderers (no LLM, stdlib only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import guardrail_policy as GP  # noqa: E402


def load_policy(path: str) -> dict:
    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    errors = GP.validate_policy(policy)
    if errors:
        raise ValueError("invalid policy: " + "; ".join(errors[:5]))
    return policy


def norm_enum(value, allowed: dict):
    """Case-insensitive enum lookup. `allowed` maps lower-case aliases to the
    target spelling. Returns None if the value is not allowed."""
    return allowed.get(str(value).strip().lower()) if isinstance(value, (str, bool)) else None


def report_md(target: str, policy: dict, mapped: list[dict], unsupported: list[dict], notes: list[str]) -> str:
    out = [f"# {target} rendering report - {policy['profile'].get('name', 'profile')}", "",
           "> ADVISORY. Generated from policy.json by a script, without a model. Review before use.",
           "> Values with basis catalog-default are an opinionated baseline, NOT vendor-backed.", "",
           "## Mapped to real target fields", ""]
    if mapped:
        out += ["| Control | Tier | Parameter | Basis | Source kind | Value | Target field |", "|---|---|---|---|---|---|---|"]
        out += [f"| `{m['control_id']}` | {m['tier']} | `{m['parameter']}` | {basis_text(m['basis'])} | {source_kind_text(m.get('source_kind'))} | `{json.dumps(m['value'])}` | `{m['field']}` |"
                for m in mapped]
    else:
        out.append("Nothing in this policy maps to a native field of the target.")
    out += ["", "## Not rendered (unsupported by the target or not grounded)", "",
            "| Control | Tier | Parameter | Basis | Reason |", "|---|---|---|---|---|"]
    out += [f"| `{u['control_id']}` | {u['tier']} | `{u['parameter']}` | {basis_text(u['basis'])} | {u['reason']} |"
            for u in unsupported] or ["| - | - | - | - | none |"]
    if notes:
        out += ["", "## Notes", "", *[f"- {n}" for n in notes]]
    return "\n".join(out) + "\n"


def source_kind_text(kind) -> str:
    if not kind:
        return "-"
    if kind == "example-config":
        return "example-config (example from vendor docs, not a recommendation)"
    return kind


def basis_text(basis: str) -> str:
    return {"vendor-grounded": "vendor-grounded",
            "catalog-default": "catalog-default (opinionated baseline, NOT vendor-backed)"}.get(basis, basis)


def mapped_row(c: dict, p: dict, field: str, value=None) -> dict:
    return {"control_id": c["control_id"], "tier": c["tier"], "parameter": p["name"], "basis": p["basis"],
            "source_kind": p.get("source_kind"), "value": p["value"] if value is None else value, "field": field}


def walk(policy: dict):
    """Yield (control, parameter-or-None). Catalog-default controls yield None."""
    for c in policy["controls"]:
        if not c["parameters"]:
            yield c, None
        for p in c["parameters"]:
            yield c, p


def unsupported_row(c: dict, p, reason: str) -> dict:
    return {"control_id": c["control_id"], "tier": c["tier"], "parameter": p["name"] if p else "-",
            "basis": p["basis"] if p else "-",
            "reason": reason if p else "no parameters at all (no vendor value and no catalog default): configure by hand"}
