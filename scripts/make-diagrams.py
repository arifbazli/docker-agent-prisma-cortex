#!/usr/bin/env python3
"""Generate the documentation diagrams as plain SVG (stdlib only).

Usage: python3 scripts/make-diagrams.py

Writes docs/images/*.svg. Output is deterministic: re-running produces
byte-identical files, so commit the result after any change here.
Each diagram is laid out in stage panels; cards are colored by kind:
blue = script, amber = cloud LLM step, grey = data.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "images"
WIDTH = 1000
SANS = 'font-family="Arial, Helvetica, sans-serif"'
MONO = 'font-family="Consolas, Menlo, monospace"'

KIND = {
    #          card fill  border     badge      badge text  label
    "script": ("#eff6ff", "#2563eb", "#2563eb", "#ffffff", "SCRIPT"),
    "ai":     ("#fffbeb", "#f59e0b", "#f59e0b", "#1f2937", "CLOUD LLM"),
    "data":   ("#f9fafb", "#9ca3af", "#9ca3af", "#1f2937", "DATA"),
}
INK = "#111827"
MUTED = "#4b5563"
EDGE = "#64748b"


def esc(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text_w(text, size, mono=False):
    return len(text) * size * (0.62 if mono else 0.58)


class Diagram:
    def __init__(self, title, subtitle, height):
        self.title, self.subtitle, self.height = title, subtitle, height
        self.panels, self.cards, self.edges = [], {}, []

    def panel(self, x, y, w, h, label):
        self.panels.append((x, y, w, h, label))

    def card(self, key, kind, x, y, w, title, lines=(), h=None):
        lines = list(lines)
        if h is None:
            h = 46 + 15 * len(lines)
        for t, size, mono in [(title, 13, False)] + [(s, 11, True) for s in lines]:
            if text_w(t, size, mono) > w - 24:
                raise SystemExit(f"text overflows card {key!r}: {t!r}")
        self.cards[key] = (kind, x, y, w, h, title, lines)

    def edge(self, a, b, label=None):
        self.edges.append((a, b, label))

    # -- rendering ---------------------------------------------------------
    def _anchor(self, a, b):
        _, ax, ay, aw, ah, *_ = self.cards[a]
        _, bx, by, bw, bh, *_ = self.cards[b]
        if bx >= ax + aw:                       # target to the right
            return (ax + aw, ay + ah / 2), (bx, by + bh / 2), "h"
        if bx + bw <= ax:                       # target to the left
            return (ax, ay + ah / 2), (bx + bw, by + bh / 2), "h"
        if by >= ay + ah:                       # target below
            return (ax + aw / 2, ay + ah), (bx + bw / 2, by), "v"
        return (ax + aw / 2, ay), (bx + bw / 2, by + bh), "v"

    def svg(self):
        o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {self.height}" '
             f'width="{WIDTH}" height="{self.height}" role="img">',
             f'  <title>{esc(self.title)}</title>',
             '  <defs>',
             '    <filter id="shadow" x="-10%" y="-10%" width="120%" height="140%">',
             '      <feDropShadow dx="0" dy="2" stdDeviation="2.5" flood-color="#0f172a" '
             'flood-opacity="0.12"/>',
             '    </filter>',
             '    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
             'markerHeight="7" orient="auto">',
             f'      <path d="M 0 1 L 9 5 L 0 9 z" fill="{EDGE}"/>',
             '    </marker>',
             '  </defs>',
             f'  <rect x="0" y="0" width="{WIDTH}" height="{self.height}" fill="#ffffff"/>',
             f'  <text x="24" y="34" {SANS} font-size="20" font-weight="bold" fill="{INK}">'
             f'{esc(self.title)}</text>',
             f'  <text x="24" y="54" {SANS} font-size="12" fill="{MUTED}">{esc(self.subtitle)}</text>']
        for x, y, w, h, label in self.panels:
            o.append(f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" ry="14" '
                     f'fill="#f8fafc" stroke="#e2e8f0" stroke-width="1"/>')
            o.append(f'  <text x="{x + 14}" y="{y + 22}" {SANS} font-size="11" font-weight="bold" '
                     f'letter-spacing="1" fill="#64748b">{esc(label)}</text>')
        for a, b, label in self.edges:
            (x1, y1), (x2, y2), d = self._anchor(a, b)
            if d == "h":
                mx = (x1 + x2) / 2
                path = f"M {x1:.1f} {y1:.1f} C {mx:.1f} {y1:.1f}, {mx:.1f} {y2:.1f}, {x2 - 2:.1f} {y2:.1f}"
            else:
                my = (y1 + y2) / 2
                path = f"M {x1:.1f} {y1:.1f} C {x1:.1f} {my:.1f}, {x2:.1f} {my:.1f}, {x2:.1f} {y2 - 2:.1f}"
            o.append(f'  <path d="{path}" fill="none" stroke="{EDGE}" stroke-width="1.8" '
                     f'stroke-linecap="round" marker-end="url(#arrow)"/>')
            if label:
                o.append(f'  <text x="{(x1 + x2) / 2:.1f}" y="{(y1 + y2) / 2 - 6:.1f}" '
                         f'text-anchor="middle" {SANS} font-size="10" fill="{MUTED}">{esc(label)}</text>')
        for kind, x, y, w, h, title, lines in self.cards.values():
            fill, border, badge, badge_ink, badge_text = KIND[kind]
            o.append(f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" ry="10" '
                     f'fill="{fill}" stroke="{border}" stroke-width="1.5" filter="url(#shadow)"/>')
            o.append(f'  <rect x="{x}" y="{y + 10}" width="4" height="{h - 20}" rx="2" ry="2" fill="{border}"/>')
            bw = int(text_w(badge_text, 9) + 14)
            o.append(f'  <rect x="{x + 12}" y="{y + 9}" width="{bw}" height="15" rx="7.5" ry="7.5" fill="{badge}"/>')
            o.append(f'  <text x="{x + 12 + bw / 2:.1f}" y="{y + 20}" text-anchor="middle" {SANS} '
                     f'font-size="9" font-weight="bold" letter-spacing="0.5" fill="{badge_ink}">{badge_text}</text>')
            o.append(f'  <text x="{x + 12}" y="{y + 41}" {SANS} font-size="13" font-weight="bold" '
                     f'fill="{INK}">{esc(title)}</text>')
            for i, line in enumerate(lines):
                o.append(f'  <text x="{x + 12}" y="{y + 58 + 15 * i}" {MONO} font-size="11" '
                         f'fill="{MUTED}">{esc(line)}</text>')
        lx, ly = 24, self.height - 22
        for kind in ("data", "script", "ai"):
            _, border, badge, badge_ink, badge_text = KIND[kind]
            bw = int(text_w(badge_text, 9) + 14)
            o.append(f'  <rect x="{lx}" y="{ly - 11}" width="{bw}" height="15" rx="7.5" ry="7.5" fill="{badge}"/>')
            o.append(f'  <text x="{lx + bw / 2:.1f}" y="{ly}" text-anchor="middle" {SANS} font-size="9" '
                     f'font-weight="bold" letter-spacing="0.5" fill="{badge_ink}">{badge_text}</text>')
            lx += bw + 10
        o.append(f'  <text x="{lx + 6}" y="{ly}" {SANS} font-size="11" fill="{MUTED}">'
                 'grey = data, blue = script, amber = cloud LLM step (with its model setting)</text>')
        o.append("</svg>")
        return "\n".join(o) + "\n"


def stage_columns(d, top, height, labels, x0=16, gap=12):
    """Equal-width stage panels across the canvas; returns their x and width."""
    w = (WIDTH - 2 * x0 - gap * (len(labels) - 1)) // len(labels)
    cols = []
    for i, label in enumerate(labels):
        x = x0 + i * (w + gap)
        d.panel(x, top, w, height, label)
        cols.append((x, w))
    return cols


def guardrail():
    d = Diagram("Guardrail policy generator",
                "scripts/guardrail.py: sanitized profile in, advisory policy out. "
                "Models propose; scripts and a cross-family judge verify.", 470)
    top, ph = 72, 360
    cols = stage_columns(d, top, ph, ["1  INPUTS", "2  SELECT AND PROPOSE", "3  VERIFY",
                                      "4  ASSEMBLE AND CHECK", "5  OUTPUTS"])
    cy = top + 36

    def col(i):
        x, w = cols[i]
        return x + 10, w - 20

    x, w = col(0)
    d.card("profile", "data", x, cy, w, "App profile", ["sanitized JSON", "no secrets"])
    d.card("catalog", "data", x, cy + 110, w, "Control catalog", ["guardrail-", "catalog.json", "70 controls"])
    x, w = col(1)
    d.card("select", "script", x, cy, w, "Select controls", ["select-controls.py"])
    d.card("spec", "ai", x, cy + 110, w, "7 specialists", ["one per category", "SPECIALIST_MODEL"])
    x, w = col(2)
    d.card("values", "script", x, cy, w, "Value check", ["type, range, enum"])
    d.card("quote", "script", x, cy + 92, w, "Quote check", ["quote on fetched", "vendor page"])
    d.card("judge", "ai", x, cy + 199, w, "Judge", ["other model family", "JUDGE_MODEL"])
    x, w = col(3)
    d.card("asm", "ai", x, cy, w, "Assembler", ["writes tests", "REVIEWER_MODEL"])
    d.card("rev", "ai", x, cy + 107, w, "Reviewer", ["review.json", "REVIEWER_MODEL"])
    d.card("check", "script", x, cy + 214, w, "Policy check", ["check-policy.py"])
    x, w = col(4)
    d.card("files", "data", x, cy, w, "Run folder",
           ["policy.json", "exceptions.md", "tests.jsonl", "evidence.json"])
    d.card("render", "script", x, cy + 152, w, "Renderers",
           ["render-bedrock", "render-nemo"])
    for a, b in (("profile", "select"), ("catalog", "select"), ("select", "spec"),
                 ("spec", "values"), ("values", "quote"), ("quote", "judge"),
                 ("judge", "asm"), ("asm", "rev"), ("rev", "check"),
                 ("check", "files"), ("files", "render")):
        d.edge(a, b)
    return d


def briefing():
    d = Diagram("Docs briefing",
                "scripts/run.sh: a Prisma Cloud / Cortex Cloud question in, "
                "a source-cited briefing out.", 330)
    top, ph = 72, 220
    cols = stage_columns(d, top, ph, ["1  ASK", "2  RESEARCH", "3  VERIFY", "4  WRITE",
                                      "5  OUTPUT"])
    cy = top + 36

    def col(i):
        x, w = cols[i]
        return x + 10, w - 20

    x, w = col(0)
    d.card("question", "data", x, cy, w, "Question", ["run.sh \"...\""])
    d.card("seeds", "data", x, cy + 92, w, "Start pages", ["seeds/*.txt"])
    x, w = col(1)
    d.card("researcher", "ai", x, cy, w, "researcher", ["facts + quotes", "RESEARCH_MODEL"])
    x, w = col(2)
    d.card("quote", "script", x, cy, w, "quote check", ["quote on page"])
    d.card("judge", "ai", x, cy + 92, w, "judge", ["supported?", "JUDGE_MODEL"])
    x, w = col(3)
    d.card("writer", "ai", x, cy, w, "writer", ["supported facts", "WRITER_MODEL"])
    d.card("check", "script", x, cy + 107, w, "check briefing", ["check-briefing.sh"])
    x, w = col(4)
    d.card("out", "data", x, cy, w, "Briefing", ["outputs/<run>.md", "evidence.json"])
    for a, b in (("question", "researcher"), ("seeds", "researcher"), ("researcher", "quote"),
                 ("quote", "judge"), ("judge", "writer"), ("writer", "check"), ("check", "out")):
        d.edge(a, b)
    return d


def overview():
    d = Diagram("How the repository works",
                "Templates build the agent configs; two tools share one verification engine.", 520)
    lanes = (("BUILD (no model calls)", 72, 124), ("GUARDRAIL POLICY GENERATOR", 208, 124),
             ("DOCS BRIEFING", 344, 124))
    for label, y, h in lanes:
        d.panel(16, y, WIDTH - 32, h, label)
    cx = (36, 266, 526, 776)
    cw = 200
    d.card("templates", "data", cx[0], 104, cw, "templates", ["templates/", "scopes, seeds"], h=84)
    d.card("gen", "script", cx[1], 104, cw, "gen configs", ["gen-configs.py"], h=84)
    d.card("agents", "data", cx[2], 104, cw, "agents yaml", ["agents/ (generated)"], h=84)
    d.card("gin", "data", cx[0], 240, cw, "profile + catalog", ["*.profile.json", "guardrail-catalog.json"], h=84)
    d.card("gtool", "script", cx[1], 240, cw, "guardrail", ["guardrail.py"], h=84)
    d.card("gout", "data", cx[3], 240, cw, "policy + drafts", ["policy.json, tests", "Bedrock, NeMo"], h=84)
    d.card("bin", "data", cx[0], 376, cw, "question + pages", ["seeds/*.txt"], h=84)
    d.card("btool", "script", cx[1], 376, cw, "docs briefing", ["run.sh, pipeline.py"], h=84)
    d.card("bout", "data", cx[3], 376, cw, "briefing", ["outputs/<run>.md", "evidence.json"], h=84)
    d.card("engine", "ai", cx[2], 240, cw, "shared engine",
           ["docker-agent", "Ollama cloud models", "quote check", "cross-family judge",
            "cloud-only guard"], h=220)
    for a, b in (("templates", "gen"), ("gen", "agents"), ("agents", "engine"),
                 ("gin", "gtool"), ("gtool", "engine"), ("engine", "gout"),
                 ("bin", "btool"), ("btool", "engine"), ("engine", "bout")):
        d.edge(a, b)
    return d


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, build in (("repo-overview.svg", overview),
                        ("guardrail-pipeline.svg", guardrail),
                        ("docs-briefing-pipeline.svg", briefing)):
        path = OUT_DIR / name
        path.write_text(build().svg(), encoding="ascii", newline="\n")
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
