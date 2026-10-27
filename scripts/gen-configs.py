#!/usr/bin/env python3
"""Generate agents/<scope>.yaml from one template plus a per-scope overlay.

    templates/agent.yaml.tmpl      shared prompts and agent graph (hub agents)
    templates/scopes/<scope>.txt   per-scope text ("=== NAME ===" sections)
    seeds/<name>.txt               seed URLs, exposed as {{SEEDS_<NAME>}}

The guardrail policy generator is built separately: one file,
agents/guardrail-policy-generator.yaml, from templates/guardrail-agent.yaml.tmpl.
The block between "#>>> specialist" and "#<<< specialist" is repeated once
per templates/scopes/guardrail-<category>.txt, in catalog category order.

Placeholders are written {{NAME}}. A placeholder alone on a line is
replaced by a block: every line of the value is indented like the
placeholder. A placeholder inside other text must have a one-line value.

Usage:
    python3 scripts/gen-configs.py           # write agents/*.yaml
    python3 scripts/gen-configs.py --check   # exit 1 if any file is stale (CI)

Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "agent.yaml.tmpl"
SCOPES = ROOT / "templates" / "scopes"
SEEDS = ROOT / "seeds"
OUT = ROOT / "agents"
GUARD_TEMPLATE = ROOT / "templates" / "guardrail-agent.yaml.tmpl"
GUARD_PREFIX = "guardrail-"
GUARD_TARGET = OUT / "guardrail-policy-generator.yaml"
GUARD_CATALOG = SEEDS / "guardrail-catalog.json"
BLOCK = re.compile(r"^[ \t]*#>>> specialist[ \t]*\n(.*?)^[ \t]*#<<< specialist[ \t]*\n", re.M | re.S)

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
SECTION = re.compile(r"^=== ([A-Z0-9_]+) ===\s*$")


def read_seeds(path: Path) -> list[str]:
    urls = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    if not urls:
        raise SystemExit(f"{path}: no URLs")
    return urls


def load_seeds() -> dict[str, str]:
    values = {}
    for path in sorted(SEEDS.glob("*.txt")):
        urls = read_seeds(path)
        key = "SEEDS_" + path.stem.upper().replace("-", "_")
        if path.stem == "migration":
            values[key] = "\n".join(f"{i}. {u}" for i, u in enumerate(urls, 1))
        else:
            values[key] = "\n".join(urls)
    return values


def load_scope(path: Path) -> dict[str, str]:
    values: dict[str, list[str]] = {}
    current = None
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        m = SECTION.match(line)
        if m:
            current = m.group(1)
            if current in values:
                raise SystemExit(f"{path}:{n}: duplicate section {current}")
            values[current] = []
            continue
        if current is None:
            if line.strip() and not line.startswith("#"):
                raise SystemExit(f"{path}:{n}: text before first section")
            continue
        values[current].append(line)
    out = {}
    for key, lines in values.items():
        while lines and not lines[-1].strip():
            lines.pop()
        out[key] = "\n".join(lines)
    return out


def render(text: str, values: dict[str, str], where: str) -> str:
    out = []
    for n, line in enumerate(text.split("\n"), 1):
        stripped = line.strip()
        m = PLACEHOLDER.fullmatch(stripped)
        if m:
            key = m.group(1)
            if key not in values:
                raise SystemExit(f"{where}:{n}: no value for {{{{{key}}}}}")
            indent = line[: len(line) - len(line.lstrip())]
            for vline in values[key].split("\n"):
                out.append(indent + vline if vline.strip() else "")
            continue

        def sub(match: re.Match) -> str:
            key = match.group(1)
            if key not in values:
                raise SystemExit(f"{where}:{n}: no value for {{{{{key}}}}}")
            if "\n" in values[key]:
                raise SystemExit(
                    f"{where}:{n}: {{{{{key}}}}} is multi-line; put it alone on a line"
                )
            return values[key]

        out.append(PLACEHOLDER.sub(sub, line))
    return "\n".join(out)


def build(scope_path: Path, template: str, seeds: dict[str, str]) -> str:
    values = dict(seeds)
    values["SCOPE_NAME"] = scope_path.stem
    scope = load_scope(scope_path)
    # Scope fragments may reference seeds ({{SEEDS_NATIVE}}); expand them first.
    for key, val in scope.items():
        values[key] = render(val, values, f"{scope_path}[{key}]")
    text = render(template, values, str(TEMPLATE))
    left = PLACEHOLDER.findall(text)
    if left:
        raise SystemExit(f"{scope_path}: unresolved placeholders {sorted(set(left))}")
    unused = set(scope) - set(PLACEHOLDER.findall(template))
    unused -= {k for k in scope if any(f"{{{{{k}}}}}" in v for v in scope.values())}
    if unused:
        raise SystemExit(f"{scope_path}: sections not used by template: {sorted(unused)}")
    if not text.endswith("\n"):
        text += "\n"
    return text


def build_guardrail(seeds: dict[str, str]) -> str:
    template = GUARD_TEMPLATE.read_text(encoding="utf-8")
    m = BLOCK.search(template)
    if not m:
        raise SystemExit(f"{GUARD_TEMPLATE}: missing '#>>> specialist' ... '#<<< specialist' block")
    block = m.group(1)
    categories = [c["id"] for c in json.loads(GUARD_CATALOG.read_text())["categories"]]
    files = {p.stem[len(GUARD_PREFIX):]: p for p in SCOPES.glob(f"{GUARD_PREFIX}*.txt")}
    if set(files) != set(categories):
        raise SystemExit(f"guardrail scope files {sorted(files)} != catalog categories {categories}")
    blocks, names = [], []
    for cat in categories:
        path = files[cat]
        values = dict(seeds)
        scope = load_scope(path)
        for key, val in scope.items():
            values[key] = render(val, values, f"{path}[{key}]")
        if values.get("CATEGORY") != cat:
            raise SystemExit(f"{path}: CATEGORY must be {cat!r}")
        unused = set(scope) - set(PLACEHOLDER.findall(block))
        if unused:
            raise SystemExit(f"{path}: sections not used by the specialist block: {sorted(unused)}")
        blocks.append(render(block.rstrip("\n"), values, f"{GUARD_TEMPLATE}[specialist:{cat}]"))
        names.append(f"{cat}_specialist")
    values = dict(seeds)
    values["SPECIALIST_NAMES"] = ", ".join(names)
    values["SPECIALIST_LIST"] = "\n".join(f"- {c}: {n}" for c, n in zip(categories, names))
    head, tail = template[: m.start()], template[m.end():]
    text = render(head, values, str(GUARD_TEMPLATE)) + "\n\n".join(blocks) + "\n" + render(tail, values, str(GUARD_TEMPLATE))
    left = PLACEHOLDER.findall(text)
    if left:
        raise SystemExit(f"{GUARD_TEMPLATE}: unresolved placeholders {sorted(set(left))}")
    return text if text.endswith("\n") else text + "\n"


def targets(seeds: dict[str, str]) -> list[tuple[Path, str]]:
    template = TEMPLATE.read_text(encoding="utf-8")
    out = []
    for scope_path in sorted(SCOPES.glob("*.txt")):
        if scope_path.name.startswith(GUARD_PREFIX):
            continue  # specialist overlays, used by build_guardrail()
        out.append((OUT / f"{scope_path.stem}.yaml", build(scope_path, template, seeds)))
    out.append((GUARD_TARGET, build_guardrail(seeds)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if generated files are stale")
    args = ap.parse_args()

    seeds = load_seeds()
    stale = []
    for target, text in targets(seeds):
        try:
            text.encode("ascii")
        except UnicodeEncodeError as e:
            raise SystemExit(f"{target}: non-ASCII output ({e})")
        current = target.read_text(encoding="utf-8") if target.exists() else None
        if current == text:
            continue
        if args.check:
            stale.append(str(target.relative_to(ROOT)))
        else:
            target.write_text(text, encoding="utf-8")
            print(f"wrote {target.relative_to(ROOT)}")
    if stale:
        print("stale generated configs (run python3 scripts/gen-configs.py):", *stale, sep="\n  ")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
