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
           "> ADVISORY. Generated from policy.json by a script, without a model. Review before use.", "",
           "## Mapped to real target fields", ""]
    if mapped:
        out += ["| Control | Tier | Parameter | Value | Target field |", "|---|---|---|---|---|"]
        out += [f"| `{m['control_id']}` | {m['tier']} | `{m['parameter']}` | `{json.dumps(m['value'])}` | `{m['field']}` |" for m in mapped]
    else:
        out.append("Nothing in this policy maps to a native field of the target.")
    out += ["", "## Not rendered (unsupported by the target or not grounded)", "",
            "| Control | Tier | Parameter | Reason |", "|---|---|---|---|"]
    out += [f"| `{u['control_id']}` | {u['tier']} | `{u['parameter']}` | {u['reason']} |" for u in unsupported] or ["| - | - | - | none |"]
    if notes:
        out += ["", "## Notes", "", *[f"- {n}" for n in notes]]
    return "\n".join(out) + "\n"


def walk(policy: dict):
    """Yield (control, parameter-or-None). Catalog-default controls yield None."""
    for c in policy["controls"]:
        if not c["parameters"]:
            yield c, None
        for p in c["parameters"]:
            yield c, p


def unsupported_row(c: dict, p, reason: str) -> dict:
    return {"control_id": c["control_id"], "tier": c["tier"], "parameter": p["name"] if p else "-",
            "reason": reason if p else "catalog-default control: no grounded parameters, NOT vendor-backed"}
