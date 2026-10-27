"""Tiny dump-only YAML writer (stdlib). Block style; every string is written
as a JSON double-quoted scalar, which YAML 1.2 reads back unchanged. There is
deliberately no YAML parser in this repository: data files are JSON."""
from __future__ import annotations

import json


def _scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return json.dumps(v)
    return json.dumps(str(v), ensure_ascii=False)


def dump(value, indent: int = 0) -> str:
    pad = "  " * indent
    lines = []
    if isinstance(value, dict):
        if not value:
            return pad + "{}\n"
        for k, v in value.items():
            key = k if isinstance(k, str) and k.replace("_", "").isalnum() else json.dumps(str(k))
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{pad}{key}:\n" + dump(v, indent + 1))
            else:
                lines.append(f"{pad}{key}: " + (("{}" if isinstance(v, dict) else "[]") if isinstance(v, (dict, list)) else _scalar(v)) + "\n")
        return "".join(lines)
    if isinstance(value, list):
        if not value:
            return pad + "[]\n"
        for v in value:
            if isinstance(v, (dict, list)) and v:
                body = dump(v, indent + 1)
                lines.append(f"{pad}- " + body.lstrip())
            else:
                lines.append(f"{pad}- {_scalar(v) if not isinstance(v, (dict, list)) else ('{}' if isinstance(v, dict) else '[]')}\n")
        return "".join(lines)
    return pad + _scalar(value) + "\n"
