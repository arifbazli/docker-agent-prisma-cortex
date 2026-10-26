#!/usr/bin/env python3
"""Render the last briefing as a PNG for the README.

usage: scripts/make-example-image.py [--chrome PATH] [--out docs/images/example-run.png]

Reads outputs/.last (written by scripts/run.sh) and its evidence file,
builds an HTML card and, if Chrome/Chromium is found, screenshots it.
Without Chrome it writes the HTML only (open it and screenshot by hand).
"""
import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIDTH = 1200

CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html{background:#0f172a}
body{width:%(w)dpx;min-height:100vh;font-family:'Segoe UI',Inter,-apple-system,Helvetica,Arial,sans-serif;
 background:linear-gradient(135deg,#0f172a 0%%,#1e1b4b 45%%,#0e7490 100%%);padding:48px 56px;color:#0f172a}
.top{display:flex;align-items:center;gap:14px;margin-bottom:22px;color:#e2e8f0}
.logo{width:40px;height:40px;border-radius:10px;background:linear-gradient(135deg,#f97316,#ec4899);
 display:flex;align-items:center;justify-content:center;font-weight:800;color:#fff;font-size:20px}
.top h2{font-size:22px;font-weight:700;letter-spacing:-.2px}
.top span{font-size:14px;color:#94a3b8;margin-left:auto}
.cmd{font-family:'Cascadia Code',Consolas,ui-monospace,monospace;font-size:15px;color:#a7f3d0;
 background:rgba(15,23,42,.65);border:1px solid rgba(148,163,184,.25);border-radius:12px;padding:14px 18px;margin-bottom:18px}
.cmd b{color:#64748b;font-weight:400}
.steps{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:22px}
.step{background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.14);border-radius:12px;padding:12px 14px;color:#e2e8f0}
.step .n{font-size:12px;text-transform:uppercase;letter-spacing:.8px;color:#94a3b8}
.step .t{font-size:16px;font-weight:600;margin:3px 0}
.step .d{font-size:13px;color:#cbd5e1}
.step .d em{font-style:normal;color:#5eead4}
.card{background:#fff;border-radius:16px;box-shadow:0 30px 60px rgba(0,0,0,.35);padding:30px 36px}
.card h1{font-size:24px;letter-spacing:-.3px;margin-bottom:14px}
.bl{background:#f0fdfa;border-left:4px solid #14b8a6;border-radius:8px;padding:12px 16px;font-size:15.5px;line-height:1.5;margin-bottom:18px}
.bl b{color:#0f766e}
h3{font-size:13px;text-transform:uppercase;letter-spacing:.9px;color:#6366f1;margin:16px 0 8px}
ul{list-style:none}
li{position:relative;padding-left:18px;font-size:15px;line-height:1.55;margin:4px 0;color:#1e293b}
li:before{content:'';position:absolute;left:2px;top:9px;width:7px;height:7px;border-radius:50%%;background:#a5b4fc}
code{font-family:'Cascadia Code',Consolas,monospace;font-size:13.5px;background:#f1f5f9;padding:1px 6px;border-radius:5px}
.ref{display:inline-block;font-size:11.5px;font-weight:700;color:#4338ca;background:#e0e7ff;border-radius:6px;padding:0 6px;margin-left:4px;vertical-align:1px}
.src li{font-size:13px;color:#475569}
.src li:before{display:none}
.src li{padding-left:0}
.foot{display:flex;gap:10px;margin-top:20px;flex-wrap:wrap}
.pill{font-size:12.5px;border-radius:999px;padding:5px 12px;background:#f1f5f9;color:#334155}
.pill.ok{background:#dcfce7;color:#166534;font-weight:600}
"""


def short_url(url: str) -> str:
    m = re.match(r"https?://([^/]+)/(.*)", url)
    if not m:
        return url
    host, path = m.groups()
    parts = [p for p in path.split("/") if p]
    tail = parts[-1] if parts else ""
    return f"{host}/&hellip;/{html.escape(tail)}" if len(parts) > 1 else f"{host}/{html.escape(tail)}"


def inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\s*\[(\d+)\]", r'<span class="ref">\1</span>', text)
    return text.replace("-&gt;", "&rarr;")


def briefing_html(md: str) -> str:
    out, in_list, sources = [], False, False
    for line in md.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("# "):
            out.append(f"<h1>{inline(s[2:])}</h1>")
            continue
        m = re.match(r"\*\*Bottom line:\*\*\s*(.*)", s)
        if m:
            out.append(f'<div class="bl"><b>Bottom line</b> &nbsp;{inline(m.group(1))}</div>')
            continue
        m = re.match(r"\*\*([^*]+)\*\*(.*)", s)
        if m and not s.startswith("-"):
            if in_list:
                out.append("</ul>")
                in_list = False
            title = m.group(1)
            sources = title.lower() == "sources"
            out.append(f"<h3>{html.escape(title)}</h3>")
            continue
        if s.startswith("- "):
            if not in_list:
                out.append('<ul class="src">' if sources else "<ul>")
                in_list = True
            item = s[2:]
            if sources:
                m = re.match(r"\[(\d+)\]\s*(\S+)", item)
                if m:
                    out.append(f'<li><span class="ref">{m.group(1)}</span> {short_url(m.group(2))}</li>')
                    continue
            out.append(f"<li>{inline(item.strip('`'))}</li>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def build(md_path: Path) -> str:
    md = md_path.read_text(encoding="utf-8")
    ev_path = md_path.with_name(md_path.name[:-3] + ".evidence.json")
    ev = json.loads(ev_path.read_text()) if ev_path.exists() else {}
    st = ev.get("stages", {})
    facts = ev.get("facts", [])
    vc = ev.get("verdict_counts", {})
    models = ev.get("models", {})
    found = sum(1 for f in facts if f.get("match"))
    pages = sum(1 for p in st.get("researcher", {}).get("pages", []) if p.get("ok"))

    def sec(name):
        return f"{st.get(name, {}).get('seconds', 0):.0f}s"

    steps = [
        ("1 &middot; Researcher", models.get("RESEARCH_MODEL", ""), f"<em>{pages}</em> pages read &middot; {sec('researcher')}"),
        ("2 &middot; Quote check", "Python, no LLM", f"<em>{found}/{len(facts)}</em> quotes found on page"),
        ("3 &middot; Judge", models.get("JUDGE_MODEL", ""), f"<em>{vc.get('SUPPORTED', 0)}</em> supported &middot; {sec('judge')}"),
        ("4 &middot; Writer", models.get("WRITER_MODEL", ""), f"briefing &middot; {sec('writer')}"),
    ]
    steps_html = "".join(
        f'<div class="step"><div class="n">{n}</div><div class="t">{html.escape(t)}</div><div class="d">{d}</div></div>'
        for n, t, d in steps)
    q = html.escape(ev.get("question", ""))
    total = ev.get("seconds_total")
    foot = ['<span class="pill ok">&#10003; checks passed</span>' if ev.get("exit_code", 0) == 0 else "",
            f'<span class="pill">{len(facts)} facts &middot; {vc.get("SUPPORTED", 0)} supported</span>',
            f'<span class="pill">total {total:.0f}s</span>' if total else "",
            '<span class="pill">sources: official Palo Alto Networks docs only</span>']
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS % {'w': WIDTH}}</style></head><body>
<div class="top"><div class="logo">&#9670;</div><h2>docker-agent &middot; Prisma Cloud &rarr; Cortex Cloud</h2><span>multi-model, quote-verified</span></div>
<div class="cmd"><b>$</b> scripts/run.sh "{q}"</div>
<div class="steps">{steps_html}</div>
<div class="card">{briefing_html(md)}<div class="foot">{''.join(foot)}</div></div>
</body></html>"""


def find_chrome(arg):
    if arg:
        return arg
    for c in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        if shutil.which(c):
            return shutil.which(c)
    win = "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe"
    return win if os.path.exists(win) else None


def to_native(path: Path, chrome: str) -> str:
    if chrome.endswith(".exe") and shutil.which("wslpath"):
        return subprocess.check_output(["wslpath", "-w", str(path)], text=True).strip()
    return str(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chrome")
    ap.add_argument("--out", default="docs/images/example-run.png")
    ap.add_argument("--height", type=int, default=0, help="image height in CSS px (default: estimate)")
    a = ap.parse_args()
    os.chdir(ROOT)
    md_path = Path(Path("outputs/.last").read_text().strip())
    page = build(md_path)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    html_path = out.with_suffix(".html")
    chrome = find_chrome(a.chrome)
    if not chrome:
        html_path.write_text(page, encoding="utf-8")
        print(f"no Chrome found; wrote {html_path} (screenshot it at {WIDTH}px wide)")
        return
    # Chrome on Windows (WSL) can only read Windows-visible paths.
    tmpdir = Path(tempfile.mkdtemp(dir="/mnt/c/Users/Public" if chrome.endswith(".exe") else None))
    src, png = tmpdir / "page.html", tmpdir / "shot.png"
    src.write_text(page, encoding="utf-8")
    lines = len(md_path.read_text().splitlines())
    height = a.height or 420 + lines * 30
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=2", f"--window-size={WIDTH},{height}",
                    f"--screenshot={to_native(png, chrome)}", "file:///" + to_native(src, chrome).replace("\\", "/")],
                   check=False, capture_output=True, timeout=120)
    if not png.exists():
        sys.exit("screenshot failed")
    shutil.copyfile(png, out)
    shutil.rmtree(tmpdir, ignore_errors=True)
    print(f"wrote {out} ({out.stat().st_size} bytes, {WIDTH}x{height} @2x)")


if __name__ == "__main__":
    main()
