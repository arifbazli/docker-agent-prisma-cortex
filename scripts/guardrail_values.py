"""Value-type checks for guardrail parameters (stdlib only, deterministic).

Each catalog control declares `value_types[key]`:
    {"type": "boolean" | "number" | "string" | "enum" | "list",
     "enum": [...], "items_enum": [...], "min": n, "max": n,
     "quote_terms": [[word, ...], ...]}

check_value() returns (normalized_value, None) or (None, reason). With a
quote (vendor proposals) two extra rules apply to numbers: the number must
appear in the quote, and every quote_terms group must match at least one
word, so a number lifted from an unrelated sentence is rejected.
"""
from __future__ import annotations

import re


def _number_forms(v) -> set[str]:
    forms = {str(v)}
    if isinstance(v, float) and v.is_integer():
        v = int(v)
        forms.add(str(v))
    if isinstance(v, int):
        forms.add(f"{v:,}")
    if isinstance(v, float):
        forms.add(f"{v:g}")
        if 0 < v < 1:
            forms.add(f"{v:g}".lstrip("0"))  # .7
    return forms


def number_in_quote(v, quote: str) -> bool:
    text = quote.replace("\u202f", " ").replace("\u00a0", " ")
    for form in _number_forms(v):
        if re.search(r"(?<![\d.])" + re.escape(form) + r"(?![\d])", text):
            return True
    return False


def check_value(spec: dict, value, quote: str | None = None):
    t = spec["type"]
    if t == "boolean":
        if not isinstance(value, bool):
            return None, f"expected true/false, got {value!r}"
        return value, None
    if t == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None, f"expected a number, got {value!r}"
        if "min" in spec and value < spec["min"] or "max" in spec and value > spec["max"]:
            return None, f"{value} is outside the allowed range {spec.get('min')}..{spec.get('max')}"
        if quote is not None:
            if not number_in_quote(value, quote):
                return None, f"the number {value} does not appear in the quote"
            low = quote.lower()
            for group in spec.get("quote_terms", []):
                if not any(w.lower() in low for w in group):
                    return None, f"the quote does not mention {' / '.join(group)}, so {value} is not about this setting"
        return value, None
    if t == "enum":
        options = {o.lower(): o for o in spec["enum"]}
        if not isinstance(value, str) or value.strip().lower() not in options:
            return None, f"expected one of {spec['enum']}, got {value!r}"
        return options[value.strip().lower()], None
    if t == "string":
        if not isinstance(value, str) or not value.strip() or len(value) > 300:
            return None, f"expected a non-empty string of at most 300 characters, got {value!r}"
        return value.strip(), None
    if t == "list":
        if not isinstance(value, list) or not all(isinstance(x, str) and x.strip() for x in value):
            return None, f"expected a list of names, got {value!r}"
        if not value:
            return None, "an empty list is not a setting"
        if "items_enum" in spec:
            options = {o.lower(): o for o in spec["items_enum"]}
            bad = [x for x in value if x.strip().lower() not in options]
            if bad:
                return None, f"list items {bad} are not in {spec['items_enum']}"
            return [options[x.strip().lower()] for x in value], None
        return [x.strip() for x in value], None
    return None, f"unknown value type {t!r}"


def type_label(spec: dict) -> str:
    """Short form for prompts: enum[NONE|LOW], number 0..0.99, boolean, ..."""
    t = spec["type"]
    if t == "enum":
        return "enum[" + "|".join(spec["enum"]) + "]"
    if t == "number":
        return f"number {spec.get('min', '')}..{spec.get('max', '')}"
    if t == "list" and "items_enum" in spec:
        return "list of [" + "|".join(spec["items_enum"]) + "]"
    if t == "list":
        return "list of names"
    return t
