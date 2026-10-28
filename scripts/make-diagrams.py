#!/usr/bin/env python3
"""Generate deterministic SVG diagrams for the documentation.

Usage:
    python3 scripts/make-diagrams.py

Stdlib only. Output is written under docs/images/. Re-running must produce
byte-identical files (no timestamps, sorted/deterministic ordering).
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "images"
FONT = 'font-family="Arial, Helvetica, sans-serif"'
WIDTH = 1000


def esc(text):
    return (text.replace("&", "&amp;")
               .replace("<", "&lt;")
               .replace(">", "&gt;")
               .replace('"', "&quot;"))


def wrap(text, width_px, font_size=12):
    """Greedy word wrap using a conservative character-width estimate."""
    if isinstance(text, (list, tuple)):
        return list(text)
    text = str(text)
    max_chars = max(6, int(width_px / (font_size * 0.58)))
    lines = []
    for word in text.split():
        if not lines or len(lines[-1]) + 1 + len(word) <= max_chars:
            if lines:
                lines[-1] = lines[-1] + " " + word
            else:
                lines.append(word)
        else:
            lines.append(word)
    return lines or [text]


def box(cx, x, y, w, h, fill, text_color, lines, font_size=12, stroke="#333333"):
    out = []
    out.append(f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" '
               f'rx="8" ry="8" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
    line_height = int(font_size * 1.25)
    start_y = y + (h - len(lines) * line_height) // 2 + font_size
    for i, line in enumerate(lines):
        dy = ("" if i == 0 else f' dy="{line_height}"')
        out.append(f'  <text x="{cx}" y="{start_y + i * line_height}" '
                   f'text-anchor="middle" {FONT} font-size="{font_size}" '
                   f'fill="{text_color}">{esc(line)}</text>' if i == 0 else
                   f'  <tspan x="{cx}"{dy} {FONT} font-size="{font_size}" '
                   f'fill="{text_color}">{esc(line)}</tspan>')
    # Rebuild consistently: first text with tspan children is cleaner.
    return out


def text_block(x, y, w, h, lines, fill, font_size=12):
    line_height = int(font_size * 1.25)
    start_y = y + (h - len(lines) * line_height) // 2 + font_size
    attrs = f'x="{x + w // 2}" y="{start_y}" text-anchor="middle" {FONT} font-size="{font_size}" fill="{fill}"'
    if len(lines) == 1:
        return [f"  <text {attrs}>{esc(lines[0])}</text>"]
    parts = [f"  <text {attrs}>{esc(lines[0])}"]
    for line in lines[1:]:
        parts.append(f'    <tspan x="{x + w // 2}" dy="{line_height}">{esc(line)}</tspan>')
    parts.append("  </text>")
    return parts


def make_svg(nodes, edges, legend, height=420):
    parts = []
    parts.append(f'<svg viewBox="0 0 {WIDTH} {height}" '
                 f'width="{WIDTH}" height="{height}" role="img">')
    parts.append(f'  <rect width="{WIDTH}" height="{height}" fill="#ffffff"/>')
    # arrows first so boxes paint over
    marker = ('  <defs>'
              '    <marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="3.5" '
              'orient="auto" markerUnits="strokeWidth">'
              '      <path d="M0,0 L0,7 L9,3.5 z" fill="#555555"/>'
              '    </marker>'
              '  </defs>')
    parts.append(marker)
    for src, dst in edges:
        sx, sy, sw, sh = nodes[src]["rect"]
        dx, dy, dw, dh = nodes[dst]["rect"]
        x1 = sx + sw
        y1 = sy + sh // 2
        x2 = dx
        y2 = dy + dh // 2
        parts.append(f'  <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                     f'stroke="#555555" stroke-width="1.5" marker-end="url(#arrow)"/>')
    for name, info in nodes.items():
        x, y, w, h = info["rect"]
        lines = info["lines"]
        kind = info["kind"]
        fill = {"data": "#9ca3af", "script": "#2563eb", "ai": "#f59e0b"}[kind]
        color = "#ffffff" if kind == "script" else "#000000"
        radius = 8
        parts.append(f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" ry="{radius}" '
                     f'fill="{fill}" stroke="#333333" stroke-width="1.5"/>')
        parts.extend(text_block(x, y, w, h, lines, color, font_size=info.get("font", 12)))
    # legend
    lx, ly = 10, height - 42
    parts.append(f'  <rect x="{lx}" y="{ly}" width="16" height="16" rx="3" ry="3" fill="#9ca3af" stroke="#333333" stroke-width="1"/>')
    parts.append(f'  <text x="{lx + 22}" y="{ly + 13}" {FONT} font-size="12" fill="#000000">data</text>')
    parts.append(f'  <rect x="{lx + 70}" y="{ly}" width="16" height="16" rx="3" ry="3" fill="#2563eb" stroke="#333333" stroke-width="1"/>')
    parts.append(f'  <text x="{lx + 92}" y="{ly + 13}" {FONT} font-size="12" fill="#000000">script (blue)</text>')
    parts.append(f'  <rect x="{lx + 190}" y="{ly}" width="16" height="16" rx="3" ry="3" fill="#f59e0b" stroke="#333333" stroke-width="1"/>')
    parts.append(f'  <text x="{lx + 212}" y="{ly + 13}" {FONT} font-size="12" fill="#000000">cloud LLM step (amber)</text>')
    # extra legend note from param
    if legend:
        parts.append(f'  <text x="{lx + 430}" y="{ly + 13}" {FONT} font-size="12" fill="#000000">{esc(legend)}</text>')
    parts.append("</svg>\n")
    return "\n".join(parts)


def write(name, content):
    path = OUT_DIR / name
    path.write_text(content, encoding="ascii", newline="\n")
    return path


def guardrail():
    bw, bh = 100, 48
    y = 70
    nodes = {}
    nodes["profile"] = {"rect": (20, 20, bw, bh), "kind": "data",
                        "lines": ["sanitized", "app profile"]}
    nodes["catalog"] = {"rect": (20, 86, bw, bh), "kind": "data",
                        "lines": ["guardrail-", "catalog.json"]}
    x0 = 140
    step = 104
    labels = [
        ("select", "select-controls.py", "script", None),
        ("values", "value-type check", "script", None),
        ("quote", "quote check on", "script", ["quote check", "on fetched page"]),
        ("judge", "judge", "ai", ["judge", "JUDGE_MODEL"]),
        ("asm", "assembler writes", "ai", ["assembler writes", "tests", "REVIEWER_MODEL"]),
        ("reviewer", "reviewer", "ai", ["reviewer", "REVIEWER_MODEL"]),
        ("check", "check-policy.py", "script", None),
    ]
    # Specialists node before value check.
    spec_x = x0 + step
    nodes["spec"] = {"rect": (spec_x, y, bw, bh + 8), "kind": "ai",
                     "lines": ["7 category", "specialists", "SPECIALIST_MODEL"]}
    pos = x0
    for key, label, kind, lines in labels[:1]:
        nodes[key] = {"rect": (pos, y, bw, bh), "kind": kind,
                      "lines": lines or [label]}
        pos += step
    # insert spec then rest
    # rebuild ordered: select, spec, values, quote, judge, asm, reviewer, check
    nodes = {}
    nodes["profile"] = {"rect": (20, 20, bw, bh), "kind": "data",
                        "lines": ["sanitized", "app profile"]}
    nodes["catalog"] = {"rect": (20, 86, bw, bh), "kind": "data",
                        "lines": ["guardrail-", "catalog.json"]}
    ordered = [
        ("select", "select-controls.py", "script", None, 112),
        ("spec", "specialists", "ai", ["7 category", "specialists", "SPECIALIST_MODEL"], 100),
        ("values", "value-type check", "script", None, 100),
        ("quote", "quote check", "script", ["quote check", "on fetched page"], 100),
        ("judge", "judge", "ai", ["judge", "JUDGE_MODEL"], 76),
        ("asm", "assembler", "ai", ["assembler", "writes tests", "REVIEWER_MODEL"], 100),
        ("reviewer", "reviewer", "ai", ["reviewer", "REVIEWER_MODEL"], 100),
        ("check", "check-policy.py", "script", None, 112),
    ]
    pos = x0
    for key, label, kind, lines, w in ordered:
        nodes[key] = {"rect": (pos, y, w, bh + (6 if lines and len(lines) > 2 else 0)),
                      "kind": kind, "lines": lines or [label]}
        pos += w + 6
    # outputs
    out_y = 180
    outputs = [("policy", "policy.json"), ("exc", "exceptions.md"),
               ("tests", "tests.jsonl"), ("evidence", "evidence.json")]
    for i, (key, label) in enumerate(outputs):
        col = i % 2
        row = i // 2
        nodes[key] = {"rect": (740 + col * 112, out_y + row * 64, 100, bh),
                      "kind": "data", "lines": [label]}
    nodes["render"] = {"rect": (800, 330, 120, bh), "kind": "script",
                       "lines": ["render-bedrock", "and render-nemo"]}
    edges = [("profile", "select"), ("catalog", "select")]
    for a, b in zip([n[0] for n in ordered], [n[0] for n in ordered][1:]):
        edges.append((a, b))
    for key, _ in outputs:
        edges.append(("check", key))
    edges.append(("policy", "render"))
    legend = "Grey data, blue script, amber cloud LLM. Inputs/outputs are files."
    svg = make_svg(nodes, edges, legend, height=400)
    write("guardrail-pipeline.svg", svg)


def overview():
    bw, bh = 118, 46
    nodes = {}
    nodes["templates"] = {"rect": (20, 30, bw, bh), "kind": "data",
                          "lines": ["templates", "and scopes"]}
    nodes["gen"] = {"rect": (165, 30, bw, bh), "kind": "script",
                    "lines": ["gen configs"]}
    nodes["agents"] = {"rect": (310, 30, bw, bh), "kind": "data",
                       "lines": ["agents yaml"]}
    nodes["briefing"] = {"rect": (480, 20, 150, bh + 4), "kind": "data",
                         "lines": ["docs briefing", "tool"]}
    nodes["guardrail"] = {"rect": (480, 82, 150, bh + 4), "kind": "data",
                          "lines": ["guardrail", "generator"]}
    nodes["seeds"] = {"rect": (165, 110, bw, bh), "kind": "data",
                      "lines": ["seeds", "start pages"]}
    nodes["catalog"] = {"rect": (310, 110, bw, bh), "kind": "data",
                        "lines": ["catalog", "and schemas"]}
    nodes["q"] = {"rect": (660, 20, 120, bh), "kind": "data",
                  "lines": ["question"]}
    nodes["b_out"] = {"rect": (660, 82, 150, bh), "kind": "data",
                      "lines": ["briefing and", "evidence"]}
    nodes["profile"] = {"rect": (660, 144, 130, bh), "kind": "data",
                        "lines": ["sanitized", "profile"]}
    nodes["p_out"] = {"rect": (810, 144, 120, bh), "kind": "data",
                      "lines": ["policy and", "drafts"]}
    edges = [("templates", "gen"), ("gen", "agents"),
             ("agents", "briefing"), ("agents", "guardrail"),
             ("seeds", "briefing"), ("catalog", "guardrail"),
             ("q", "briefing"), ("briefing", "b_out"),
             ("profile", "guardrail"), ("guardrail", "p_out")]
    legend = "Shared conventions: cloud models, stdlib, JSON data."
    svg = make_svg(nodes, edges, legend, height=230)
    write("repo-overview.svg", svg)


def briefing():
    bw, bh = 120, 48
    y = 75
    nodes = {}
    seq = [
        ("question", "question", "data", None),
        ("researcher", "researcher", "ai", ["researcher", "RESEARCH_MODEL"]),
        ("quote", "quote check", "script", ["quote check", "on fetched page"]),
        ("judge", "judge", "ai", ["judge", "JUDGE_MODEL"]),
        ("writer", "writer", "ai", ["writer", "WRITER_MODEL"]),
        ("check", "check briefing", "script", None),
        ("out", "briefing and", "data", ["briefing and", "evidence"]),
    ]
    x = 30
    step = 132
    for key, label, kind, lines in seq:
        nodes[key] = {"rect": (x, y, bw, bh), "kind": kind,
                      "lines": lines or [label]}
        x += step
    # MODE note as data-ish text not node
    edges = []
    keys = [n[0] for n in seq]
    for a, b in zip(keys, keys[1:]):
        edges.append((a, b))
    legend = "Blue script, amber cloud LLM, grey data."
    svg = make_svg(nodes, edges, legend, height=200)
    write("docs-briefing-pipeline.svg", svg)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    guardrail()
    overview()
    briefing()
    for f in ("guardrail-pipeline.svg", "repo-overview.svg",
              "docs-briefing-pipeline.svg"):
        print(f"wrote {OUT_DIR / f}")


if __name__ == "__main__":
    main()
