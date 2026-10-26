#!/usr/bin/env python3
"""Run the research pipeline for one question.

Pipeline mode (default), each step a separate docker-agent call:

  1. researcher (LLM, fetch tool)  -> FACT lines + the exact pages it fetched
  2. quote check (this script)     -> is each QUOTE really on its cited page?
  3. judge (LLM, no tools)         -> does the quote support the FACT?
  4. writer (LLM, no tools)        -> compact briefing

Orchestration and string matching are deterministic; LLMs only extract,
judge meaning and write. Quotes are checked against the page text the
researcher actually received (read from docker-agent's --json event
stream), so nothing is fetched twice and every verdict is reproducible
from outputs/<run>.evidence.json and fetched/.

Agent mode (--mode agent) runs the self-contained root agent instead
(root -> researcher -> verifier -> writer inside docker-agent).

Exit codes: 0 briefing or a valid sentinel (OUT OF SCOPE, NO FACTS FOUND,
NO SUPPORTED FACTS), 2 BRIEFING FAILED (a step crashed or returned
nothing usable), 64 usage error.

Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "OLLAMA_BASE_URL": "http://localhost:11434/v1",
    "RESEARCH_MODEL": "nemotron-3-super:cloud",
    "JUDGE_MODEL": "gpt-oss:120b-cloud",
    "WRITER_MODEL": "nemotron-3-super:cloud",
    "ROUTER_MODEL": "nemotron-3-super:cloud",
}
DEFAULT_CONFIG = "agents/prisma-cortex-hub.yaml"

OOS_PREFIX = "OUT OF SCOPE:"
NOT_FOUND = "NOT FOUND IN FETCHED PAGES"
NO_FACTS = "NO FACTS FOUND: the official sources did not answer this question."
NO_SUPPORTED = "NO SUPPORTED FACTS AVAILABLE FOR BRIEFING."
FAILED_PREFIX = "BRIEFING FAILED:"
VERDICTS = ("PARTLY SUPPORTED", "UNSUPPORTED", "UNVERIFIABLE", "SUPPORTED")


def log(msg: str) -> None:
    print(f"[pipeline] {msg}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------
# Text normalisation (used for quote matching and for the ASCII output rule)
# --------------------------------------------------------------------------
_ASCII_MAP = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u201f": '"', "\u2033": '"',
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
    "\u2015": "-", "\u2212": "-", "\u2192": "->", "\u2190": "<-", "\u2026": "...",
    "\u00a0": " ", "\u202f": " ", "\u2009": " ", "\u200b": "", "\u2022": "-",
    "\u00ab": '"', "\u00bb": '"',
}


def to_ascii(text: str) -> str:
    """Map typographic characters to ASCII; drop anything still non-ASCII."""
    for k, v in _ASCII_MAP.items():
        text = text.replace(k, v)
    text = unicodedata.normalize("NFKD", text)
    return text.encode("ascii", "ignore").decode("ascii")


_MD_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_HTML_TAG = re.compile(r"<[^>\n]{1,200}>")
_LINE_PREFIX = re.compile(r"(?m)^\s*(?:#{1,6}\s+|>\s*|[-*+]\s+|\d+[.)]\s+)")
_WS = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^0-9a-z]+")


def norm_strict(text: str) -> str:
    """Strip markdown syntax and typography, keep words and punctuation."""
    text = to_ascii(text)
    text = _MD_IMAGE.sub(r"\1", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _HTML_TAG.sub(" ", text)
    text = _LINE_PREFIX.sub("", text)
    text = text.replace("|", " ")
    text = re.sub(r"[*_`]+", "", text)
    text = text.replace("\\", "")
    return _WS.sub(" ", text).strip().casefold()


def norm_loose(text: str) -> str:
    """Words only: ignores every punctuation difference."""
    return _WS.sub(" ", _NON_WORD.sub(" ", norm_strict(text))).strip()


def quote_on_page(quote: str, page: str) -> str | None:
    """Return 'exact', 'loose' or None. '...' in a quote splits it into
    pieces that must appear in order."""
    pieces = [p for p in re.split(r"\.\.\.|\u2026", quote) if p.strip()]
    if not pieces:
        return None
    for mode, fn in (("exact", norm_strict), ("loose", norm_loose)):
        hay = fn(page)
        pos, ok = 0, True
        for piece in pieces:
            needle = fn(piece).strip(" .,;:")
            if not needle:
                continue
            i = hay.find(needle, pos)
            if i < 0:
                ok = False
                break
            pos = i + len(needle)
        if ok:
            return mode
    return None


# --------------------------------------------------------------------------
# docker-agent invocation and event-stream parsing
# --------------------------------------------------------------------------
def docker_agent_cmd() -> list[str]:
    override = os.environ.get("DOCKER_AGENT")
    if override:
        return override.split()
    if shutil.which("docker-agent"):
        return ["docker-agent"]
    return ["docker", "agent"]


@dataclass
class Page:
    url: str
    ok: bool
    status: int | None
    body: str
    error: str = ""


@dataclass
class AgentRun:
    agent: str
    rc: int
    seconds: float
    final: str
    pages: list[Page] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    fetch_calls: int = 0


_SUCCESS = re.compile(r"^Successfully fetched (\S+) \(Status: (\d+), Length: \d+ bytes\):\n\n", re.S)
_FAILURE = re.compile(r"^Error fetching (\S+?): (.*)$", re.S)


def parse_fetch_output(output: str, requested: list[str]) -> list[Page]:
    m = _SUCCESS.match(output)
    if m:
        return [Page(m.group(1), True, int(m.group(2)), output[m.end():])]
    m = _FAILURE.match(output)
    if m:
        return [Page(m.group(1), False, None, "", m.group(2).strip())]
    try:
        items = json.loads(output)
    except (ValueError, TypeError):
        url = requested[0] if requested else "?"
        return [Page(url, False, None, "", output[:300])]
    pages = []
    for it in items if isinstance(items, list) else []:
        err = it.get("error") or ""
        status = it.get("statusCode")
        ok = not err and status == 200
        pages.append(Page(it.get("url", "?"), ok, status, it.get("body") or "", err))
    return pages


def parse_events(lines, agent: str) -> tuple[str, list[Page], list[str], int]:
    """Return (final answer of `agent`, fetched pages, error messages, fetch calls)."""
    messages: dict[str, list[str]] = {}
    order: list[str] = []
    calls: dict[str, list[str]] = {}
    pages: list[Page] = []
    errors: list[str] = []
    for raw in lines:
        raw = raw.strip()
        if not raw.startswith("{"):
            continue
        try:
            ev = json.loads(raw)
        except ValueError:
            continue
        t = ev.get("type")
        if t == "agent_choice" and ev.get("agent_name") == agent:
            mid = ev.get("message_id") or "_"
            if mid not in messages:
                messages[mid] = []
                order.append(mid)
            messages[mid].append(ev.get("content") or "")
        elif t == "tool_call":
            fn = (ev.get("tool_call") or {}).get("function") or {}
            if fn.get("name") == "fetch":
                try:
                    urls = json.loads(fn.get("arguments") or "{}").get("urls") or []
                except ValueError:
                    urls = []
                calls[(ev.get("tool_call") or {}).get("id", "")] = urls
        elif t == "tool_call_response" and ev.get("tool_call_id") in calls:
            res = ev.get("result")
            out = res.get("output") if isinstance(res, dict) else None
            if out is None:
                out = ev.get("response") or ""
            pages.extend(parse_fetch_output(str(out), calls[ev["tool_call_id"]]))
        elif t == "error":
            errors.append(str(ev.get("error") or ev))
    final = "".join(messages[order[-1]]).strip() if order else ""
    return final, pages, errors, len(calls)


def run_agent(config: str, agent: str, prompt: str, log_path: Path, timeout: int) -> AgentRun:
    cmd = docker_agent_cmd() + [
        "run", "--exec", "--json",
        "--safety", os.environ.get("SAFETY", "restricted"),
        "-a", agent, config, prompt,
    ]
    log(f"{agent}: starting")
    t0 = time.time()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout,
            env=os.environ.copy(),
        )
        rc, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        rc = 124
        out = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = f"timeout after {timeout}s"
    except FileNotFoundError as e:
        rc, out, err = 127, "", str(e)
    log_path.write_text(out + ("\n# STDERR\n" + err if err else ""), encoding="utf-8")
    final, pages, errors, n_calls = parse_events(out.splitlines(), agent)
    if rc != 0 and err.strip():
        errors.append(err.strip().splitlines()[-1])
    secs = round(time.time() - t0, 1)
    log(f"{agent}: rc={rc} {secs}s, {len(pages)} page(s) fetched, {len(errors)} error(s)")
    return AgentRun(agent, rc, secs, final, pages, errors, n_calls)


# --------------------------------------------------------------------------
# Facts, quote check, judge
# --------------------------------------------------------------------------
_FACT = re.compile(
    r"FACT:\s*(?P<fact>.*?)\s*\|\s*PRODUCT:\s*(?P<product>.*?)\s*\|\s*MODULE:\s*(?P<module>.*?)"
    r"\s*\|\s*QUOTE:\s*(?P<quote>.*?)\s*\|\s*URL:\s*(?P<url>\S+?)\s*"
    r"(?:\|\s*MONTH:\s*(?P<month>.*?))?\s*$"
)


@dataclass
class Fact:
    n: int
    line: str
    fact: str
    product: str
    module: str
    quote: str
    url: str
    month: str
    verdict: str = ""
    note: str = ""
    match: str = ""
    dropped: bool = False  # never shown to the writer (banned URL)


def clean_url(url: str) -> str:
    url = url.strip().strip("<>()[]`'\"")
    m = re.match(r"\[[^\]]*\]\((\S+)\)", url)
    return m.group(1) if m else url.rstrip(".,;")


def url_key(url: str) -> str:
    url = clean_url(url).split("#", 1)[0]
    url = re.sub(r"^https?://", "", url).rstrip("/")
    return url[:-3] if url.endswith(".md") else url


def parse_facts(text: str) -> list[Fact]:
    facts, seen = [], set()
    for raw in text.splitlines():
        line = raw.strip().lstrip("-*0123456789.) ").strip()
        m = _FACT.search(line)
        if not m:
            continue
        line = line[m.start():]
        if line in seen:
            continue
        seen.add(line)
        q = m.group("quote").strip()
        if len(q) >= 2 and q[0] in "\"'\u201c\u2018" and q[-1] in "\"'\u201d\u2019":
            q = q[1:-1].strip()
        facts.append(Fact(
            n=len(facts) + 1, line=line, fact=m.group("fact"), product=m.group("product"),
            module=m.group("module"), quote=q, url=clean_url(m.group("url")),
            month=(m.group("month") or "unknown").strip(),
        ))
    return facts


def banned_url(url: str) -> str | None:
    if "?" in url or "&goal=" in url:
        return "URL is a generated ?ask= answer, not a content page"
    low = url.lower().rstrip("/")
    if low.endswith("/readme") or low.endswith("/readme.md"):
        return "URL is an index page, not a content page"
    if re.fullmatch(r"https?://[^/]+", low):
        return "URL is a site root, not a content page"
    return None


def check_quotes(facts: list[Fact], pages: list[Page]) -> None:
    by_url: dict[str, Page] = {}
    for p in pages:
        k = url_key(p.url)
        if k not in by_url or (p.ok and not by_url[k].ok):
            by_url[k] = p
    for f in facts:
        reason = banned_url(f.url)
        if reason:
            f.verdict, f.note, f.dropped = "UNSUPPORTED", reason, True
            continue
        page = by_url.get(url_key(f.url))
        if page is None:
            f.verdict, f.note = "UNSUPPORTED", "URL was not fetched in this run"
            continue
        if not page.ok or re.search(r"(?m)^#\s*Page Not Found", page.body):
            f.verdict, f.note = "UNVERIFIABLE", f"page fetch failed: {page.error or page.status}"
            continue
        if not f.quote:
            f.verdict, f.note = "UNSUPPORTED", "no quote given"
            continue
        if len(f.quote.split()) > 40:
            f.verdict, f.note = "UNSUPPORTED", "quote longer than allowed"
            continue
        found = quote_on_page(f.quote, page.body)
        if found:
            f.match = found
            continue  # judge decides
        elsewhere = [u for k, p in by_url.items() if p.ok and quote_on_page(f.quote, p.body)
                     for u in [p.url]]
        f.verdict = "UNSUPPORTED"
        f.note = ("quote is on a different page than cited" if elsewhere
                  else "quote not found on the cited page")


_JUDGE_LINE = re.compile(
    r"^\s*\[?(\d+)\]?\s*\|\s*(PARTLY SUPPORTED|UNSUPPORTED|UNVERIFIABLE|SUPPORTED)\s*(?:\|\s*NOTE:\s*(.*))?$",
    re.I,
)


def apply_judge(facts: list[Fact], text: str) -> int:
    pending = {f.n: f for f in facts if not f.verdict}
    applied = 0
    for line in text.splitlines():
        m = _JUDGE_LINE.match(line.strip())
        if not m:
            continue
        f = pending.get(int(m.group(1)))
        if f is None or f.verdict:
            continue
        f.verdict = m.group(2).upper()
        note = (m.group(3) or "").strip()
        f.note = "none" if not note or note.lower() in ("none", "none.") else note
        applied += 1
    for f in pending.values():
        if not f.verdict:
            f.verdict, f.note = "PARTLY SUPPORTED", "judge returned no verdict for this line"
    return applied


def verdict_lines(facts: list[Fact]) -> list[str]:
    """Writer input. Facts citing a banned URL are left out entirely: the
    writer would otherwise list a ?ask= URL under To confirm / Sources."""
    return [f"{f.verdict} | {f.line} | NOTE: {f.note or 'none'}" for f in facts if not f.dropped]


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", to_ascii(text).lower()).strip("-")
    return s[:50].rstrip("-") or "question"


def save_pages(pages: list[Page], cache: Path) -> dict[str, str]:
    cache.mkdir(parents=True, exist_ok=True)
    index = {}
    for p in pages:
        if not p.ok:
            continue
        name = hashlib.sha1(p.url.encode()).hexdigest()[:16] + ".md"
        (cache / name).write_text(f"<!-- {p.url} -->\n{p.body}", encoding="utf-8")
        index[p.url] = str((cache / name).relative_to(ROOT))
    return index


def clean_output(text: str) -> str:
    text = to_ascii(text).strip()
    # Writers sometimes wrap the briefing in a code fence.
    m = re.fullmatch(r"```(?:markdown|md)?\n(.*)\n```", text, re.S)
    return (m.group(1) if m else text).strip()


def extract_briefing(text: str) -> str:
    """Drop any chatter before the briefing heading or a sentinel."""
    m = re.search(r"(?m)^# .*Briefing:.*$", text)
    if m:
        return text[m.start():].strip()
    for s in (OOS_PREFIX, "NO FACTS FOUND:", NO_SUPPORTED, FAILED_PREFIX):
        i = text.find(s)
        if i >= 0:
            return text[i:].splitlines()[0].strip()
    return text.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description="Research briefing pipeline")
    ap.add_argument("question", nargs="+")
    ap.add_argument("-c", "--config", default=os.environ.get("CFG", DEFAULT_CONFIG))
    ap.add_argument("--mode", choices=["pipeline", "agent"], default=os.environ.get("MODE", "pipeline"))
    ap.add_argument("--out-dir", default=os.environ.get("OUT_DIR", "outputs"))
    ap.add_argument("--timeout", type=int, default=int(os.environ.get("STAGE_TIMEOUT", "900")))
    args = ap.parse_args()

    question = " ".join(args.question).strip()
    if not question:
        ap.error("empty question")
    if not (ROOT / args.config).exists() and not Path(args.config).exists():
        print(f"config not found: {args.config}", file=sys.stderr)
        return 64
    for k, v in DEFAULTS.items():
        os.environ.setdefault(k, v)
    os.environ.setdefault("TELEMETRY_ENABLED", "false")

    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"{stamp}-{slugify(question)}"
    out_dir = ROOT / args.out_dir
    logs = ROOT / "logs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    evidence: dict = {
        "run_id": run_id, "question": question, "config": args.config, "mode": args.mode,
        "models": {k: os.environ[k] for k in DEFAULTS if k != "OLLAMA_BASE_URL"},
        "stages": {}, "facts": [], "pages": {},
    }
    t_start = time.time()

    def stage(r: AgentRun) -> None:
        evidence["stages"][r.agent] = {
            "rc": r.rc, "seconds": r.seconds, "fetch_calls": r.fetch_calls,
            "pages": [{"url": p.url, "ok": p.ok, "status": p.status, "error": p.error} for p in r.pages],
            "errors": r.errors,
        }

    def finish(text: str, code: int) -> int:
        text = clean_output(text)
        evidence["result"] = text.splitlines()[0] if text else ""
        evidence["exit_code"] = code
        evidence["seconds_total"] = round(time.time() - t_start, 1)
        (out_dir / f"{run_id}.md").write_text(text + "\n", encoding="utf-8")
        (out_dir / f"{run_id}.evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        (out_dir / ".last").write_text(f"{args.out_dir}/{run_id}.md\n", encoding="utf-8")
        print(text)
        log(f"saved {args.out_dir}/{run_id}.md and .evidence.json ({evidence['seconds_total']}s)")
        return code

    def failed(step: str, r: AgentRun | None = None) -> int:
        why = f" ({r.errors[-1][:200]})" if r and r.errors else ""
        return finish(f"{FAILED_PREFIX} {step} returned no usable output.{why}", 2)

    # ---------------- agent mode ----------------
    if args.mode == "agent":
        r = run_agent(args.config, "root", question, logs / "root.ndjson", args.timeout)
        stage(r)
        evidence["pages"] = save_pages(r.pages, ROOT / "fetched")
        if r.rc != 0 or not r.final:
            return failed("root", r)
        return finish(extract_briefing(r.final), 2 if r.final.startswith(FAILED_PREFIX) else 0)

    # ---------------- pipeline mode ----------------
    # 1. researcher
    res = run_agent(args.config, "researcher", question, logs / "researcher.ndjson", args.timeout)
    stage(res)
    evidence["pages"] = save_pages(res.pages, ROOT / "fetched")
    if res.rc != 0 and not res.final:
        return failed("researcher", res)
    text = to_ascii(res.final)
    oos = next((ln.strip() for ln in text.splitlines() if ln.strip().startswith(OOS_PREFIX)), None)
    facts = parse_facts(res.final)
    if oos and not facts:
        return finish(oos, 0)
    if not facts:
        if NOT_FOUND in text or res.pages:
            return finish(NO_FACTS, 0)
        return failed("researcher", res)
    log(f"researcher: {len(facts)} fact line(s)")

    # 2. deterministic quote check
    check_quotes(facts, res.pages)
    to_judge = [f for f in facts if not f.verdict]
    log(f"quote check: {len(to_judge)} found on page, {len(facts) - len(to_judge)} rejected")

    # 3. judge (meaning only)
    if to_judge:
        prompt = "\n".join(f"[{f.n}] {f.line}" for f in to_judge)
        jr = run_agent(args.config, "judge", prompt, logs / "judge.ndjson", args.timeout)
        stage(jr)
        if jr.rc != 0 or not jr.final:
            return failed("judge", jr)
        applied = apply_judge(facts, jr.final)
        log(f"judge: {applied}/{len(to_judge)} verdict(s) parsed")
    evidence["facts"] = [asdict(f) for f in facts]
    counts = {v: sum(f.verdict == v for f in facts) for v in VERDICTS}
    evidence["verdict_counts"] = counts
    log("verdicts: " + ", ".join(f"{k}={v}" for k, v in counts.items()))

    # 4. writer
    if not any(not f.dropped for f in facts):
        return finish(NO_FACTS, 0)
    prompt = f"QUESTION: {question}\n\n" + "\n".join(verdict_lines(facts))
    wr = run_agent(args.config, "writer", prompt, logs / "writer.ndjson", args.timeout)
    stage(wr)
    if wr.rc != 0 or not wr.final:
        return failed("writer", wr)
    return finish(extract_briefing(wr.final), 0)


if __name__ == "__main__":
    sys.exit(main())
