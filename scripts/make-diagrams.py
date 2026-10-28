#!/usr/bin/env python3
"""Generate the documentation diagrams as plain SVG (stdlib only).

Usage: python3 scripts/make-diagrams.py

Writes docs/images/*.svg. Output is deterministic: re-running produces
byte-identical files, so commit the result after any change here.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "images"
FONT = 'font-family="Arial, Helvetica, sans-serif"'
WIDTH = 1000
FILL = {"data": "#9ca3af", "script": "#2563eb", "ai": "#f59e0b"}
STROKE = {"data": "#6b7280", "script": "#1e40af", "ai": "#b45309"}
TEXT = {"data": "#000000", "script": "#ffffff", "ai": "#000000"}
FONT_SIZE = 13
LINE_H = 16
CHAR_W = 0.62  # conservative average glyph width, in font-size units


def esc(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fits(lines, w):
    return all(len(s) * FONT_SIZE * CHAR_W <= w - 12 for s in lines)


class Diagram:
    def __init__(self, height):
        self.height = height
        self.nodes = {}
        self.edges = []

    def node(self, key, kind, x, y, lines, w=140, h=None):
        if h is None:
            h = max(52, len(lines) * LINE_H + 20)
        if not fits(lines, w):
            raise SystemExit(f"text overflows box {key!r}: {lines}")
        self.nodes[key] = (kind, x, y, w, h, lines)

    def edge(self, a, b):
        self.edges.append((a, b))

    @staticmethod
    def clip(n, tx, ty):
        """Point on the border of node n on the line from its center to (tx, ty)."""
        _, x, y, w, h, _ = n
        cx, cy = x + w / 2, y + h / 2
        dx, dy = tx - cx, ty - cy
        t = min((w / 2) / abs(dx) if dx else 1e9, (h / 2) / abs(dy) if dy else 1e9)
        return cx + dx * t, cy + dy * t

    def svg(self):
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {self.height}" '
               f'width="{WIDTH}" height="{self.height}" role="img">',
               f'  <rect x="0" y="0" width="{WIDTH}" height="{self.height}" fill="#ffffff"/>',
               '  <defs>',
               '    <marker id="arrow" viewBox="0 0 10 10" refX="10" refY="5" '
               'markerWidth="8" markerHeight="8" orient="auto-start-reverse">',
               '      <path d="M 0 0 L 10 5 L 0 10 z" fill="#374151"/>',
               '    </marker>',
               '  </defs>']
        for a, b in self.edges:
            na, nb = self.nodes[a], self.nodes[b]
            ca = (na[1] + na[3] / 2, na[2] + na[4] / 2)
            cb = (nb[1] + nb[3] / 2, nb[2] + nb[4] / 2)
            x1, y1 = self.clip(na, *cb)
            x2, y2 = self.clip(nb, *ca)
            out.append(f'  <line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                       f'stroke="#374151" stroke-width="1.6" marker-end="url(#arrow)"/>')
        for key, (kind, x, y, w, h, lines) in self.nodes.items():
            out.append(f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" ry="8" '
                       f'fill="{FILL[kind]}" stroke="{STROKE[kind]}" stroke-width="1.5"/>')
            cx = x + w // 2
            top = y + (h - len(lines) * LINE_H) / 2 + LINE_H - 4
            for i, line in enumerate(lines):
                weight = ' font-weight="bold"' if i == 0 else ""
                out.append(f'  <text x="{cx}" y="{top + i * LINE_H:.1f}" text-anchor="middle" '
                           f'{FONT} font-size="{FONT_SIZE}"{weight} fill="{TEXT[kind]}">{esc(line)}</text>')
        ly = self.height - 30
        for i, (kind, label) in enumerate((("data", "data"), ("script", "script"),
                                           ("ai", "cloud LLM step (model setting)"))):
            lx = 20 + i * 130
            out.append(f'  <rect x="{lx}" y="{ly}" width="16" height="16" rx="3" ry="3" '
                       f'fill="{FILL[kind]}" stroke="{STROKE[kind]}" stroke-width="1"/>')
            out.append(f'  <text x="{lx + 22}" y="{ly + 13}" {FONT} font-size="12" '
                       f'fill="#000000">{label}</text>')
        out.append("</svg>")
        return "\n".join(out) + "\n"


def guardrail():
    # Row 1 runs left to right, row 2 runs right to left (the order of
    # scripts/guardrail.py: select, specialists, value check, quote check,
    # judge, assembler, reviewer, check-policy, outputs, renderers).
    d = Diagram(height=330)
    r1, r2 = 60, 190
    d.node("profile", "data", 20, 20, ["sanitized", "app profile"], w=130)
    d.node("catalog", "data", 20, 110, ["guardrail-", "catalog.json"], w=130)
    d.node("select", "script", 190, r1, ["select-controls.py"], w=165)
    d.node("spec", "ai", 395, r1, ["7 category", "specialists", "SPECIALIST_MODEL"], w=150)
    d.node("values", "script", 585, r1, ["value-type", "check"], w=120)
    d.node("quote", "script", 750, r1, ["quote check on", "fetched page"], w=140)
    d.node("judge", "ai", 750, r2, ["judge", "JUDGE_MODEL"], w=140)
    d.node("asm", "ai", 580, r2, ["assembler", "writes tests", "REVIEWER_MODEL"], w=130)
    d.node("reviewer", "ai", 410, r2, ["reviewer", "REVIEWER_MODEL"], w=130)
    d.node("check", "script", 235, r2, ["check-policy.py"], w=140)
    d.node("outputs", "data", 20, r2 - 12, ["policy.json", "exceptions.md", "tests.jsonl",
                                            "evidence.json"], w=130)
    for a, b in (("profile", "select"), ("catalog", "select"), ("select", "spec"),
                 ("spec", "values"), ("values", "quote"), ("quote", "judge"),
                 ("judge", "asm"), ("asm", "reviewer"), ("reviewer", "check"),
                 ("check", "outputs")):
        d.edge(a, b)
    return d


def guardrail_with_render():
    d = guardrail()
    d.height = 400
    d.node("render", "script", 200, 300, ["render-bedrock", "and render-nemo"], w=170)
    d.edge("outputs", "render")
    return d


def overview():
    d = Diagram(height=420)
    d.node("seeds", "data", 380, 20, ["seeds", "start pages"])
    d.node("question", "data", 600, 20, ["question"])
    d.node("templates", "data", 20, 120, ["templates", "and scopes"])
    d.node("gen", "script", 200, 120, ["gen configs"])
    d.node("agents", "data", 380, 120, ["agents yaml", "(generated)"])
    d.node("briefing", "script", 600, 120, ["docs briefing", "tool"])
    d.node("bout", "data", 820, 120, ["briefing and", "evidence"], w=160)
    d.node("guardrail", "script", 600, 220, ["guardrail", "generator"])
    d.node("pout", "data", 820, 220, ["policy, tests", "and drafts"], w=160)
    d.node("catalog", "data", 380, 300, ["catalog", "and schemas"])
    d.node("profile", "data", 600, 300, ["sanitized", "profile"])
    for a, b in (("templates", "gen"), ("gen", "agents"), ("agents", "briefing"),
                 ("agents", "guardrail"), ("seeds", "briefing"), ("question", "briefing"),
                 ("briefing", "bout"), ("catalog", "guardrail"), ("profile", "guardrail"),
                 ("guardrail", "pout")):
        d.edge(a, b)
    return d


def briefing():
    d = Diagram(height=170)
    steps = (("question", "data", ["question"]),
             ("researcher", "ai", ["researcher", "RESEARCH_MODEL"]),
             ("quote", "script", ["quote check", "on page"]),
             ("judge", "ai", ["judge", "JUDGE_MODEL"]),
             ("writer", "ai", ["writer", "WRITER_MODEL"]),
             ("check", "script", ["check briefing"]),
             ("out", "data", ["briefing and", "evidence"]))
    x = 5
    for key, kind, lines in steps:
        d.node(key, kind, x, 40, lines, w=130)
        x += 143
    for (a, *_), (b, *_) in zip(steps, steps[1:]):
        d.edge(a, b)
    return d


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, build in (("guardrail-pipeline.svg", guardrail_with_render),
                        ("repo-overview.svg", overview),
                        ("docs-briefing-pipeline.svg", briefing)):
        path = OUT_DIR / name
        path.write_text(build().svg(), encoding="ascii", newline="\n")
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
