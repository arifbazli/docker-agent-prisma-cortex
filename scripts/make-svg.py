import sys, pathlib
from xml.sax.saxutils import escape
theme = sys.argv[1] if len(sys.argv) > 1 else "dark"
C = {"dark": dict(bg="#0d1117", bar="#161b22", fg="#c9d1d9", dim="#8b949e", acc="#3fb950", line="#30363d"),
     "light": dict(bg="#ffffff", bar="#f6f8fa", fg="#24292f", dim="#57606a", acc="#1a7f37", line="#d0d7de")}[theme]
last = pathlib.Path("outputs/.last").read_text().strip()
body = [l.replace("**", "") for l in pathlib.Path(last).read_text().splitlines()][:30]
import textwrap
wrapped = []
for l in body:
    wrapped += textwrap.wrap(l, 108, subsequent_indent="  ") or [""]
body = wrapped
rows = [("acc", "$ scripts/run.sh \\"),
        ("acc", "    \"Why migrate from Prisma Cloud to Cortex Cloud?\""),
        ("fg", "")]
rows += [("acc" if l.startswith("# ") else "fg", l) for l in body]
lh, top, w = 18, 52, 960
h = top + lh * len(rows) + 16
out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="Docker Agent run: Prisma Cloud to Cortex Cloud migration briefing">',
       f'<rect width="{w}" height="{h}" rx="8" fill="{C["bg"]}" stroke="{C["line"]}"/>',
       f'<path d="M0 8a8 8 0 0 1 8-8h{w-16}a8 8 0 0 1 8 8v28H0z" fill="{C["bar"]}"/>',
       '<circle cx="20" cy="18" r="6" fill="#ff5f56"/><circle cx="40" cy="18" r="6" fill="#ffbd2e"/><circle cx="60" cy="18" r="6" fill="#27c93f"/>',
       f'<text x="{w//2}" y="22" fill="{C["dim"]}" font-family="monospace" font-size="12" text-anchor="middle">docker-agent</text>']
for i, (k, t) in enumerate(rows):
    y = top + lh * i
    out.append(f'<text x="20" y="{y}" fill="{C[k]}" font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="13" xml:space="preserve">{escape(t)}</text>')
out.append("</svg>")
dst = pathlib.Path("docs/images"); dst.mkdir(parents=True, exist_ok=True)
f = dst / f"docker-agent-run-{theme}.svg"
f.write_text("\n".join(out) + "\n")
print(f, f.stat().st_size, "bytes")
