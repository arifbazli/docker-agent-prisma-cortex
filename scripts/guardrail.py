#!/usr/bin/env python3
"""Guardrail policy generator, pipeline mode.

usage: scripts/guardrail.py PROFILE.json [--dry-run | --no-llm] [--config agents/guardrail-policy-generator.yaml]

  1. validate + select-controls (script)  which catalog controls apply to the profile
  2. start pages (script)                 fetched once, cached; excerpts per category
  3. specialists (LLM, SPECIALIST_MODEL)  one per category WITH selected controls,
                                          up to GUARDRAIL_PARALLEL (4, max 7) at once;
                                          per control and key: value or null + quote
  4. value types (script)                 catalog value_types; numbers must be in the
                                          quote and the quote about the setting
  5. quote check (script)                 is each quote on the page it cites?
  6. judge (LLM, JUDGE_MODEL)             does the quote support the value?
  7. policy (script)                      policy.json; vendor values override the
                                          catalog recommended defaults per key
  8. assembler (LLM, REVIEWER_MODEL)      test cases; script fills any gaps
  9. reviewer (LLM, REVIEWER_MODEL)       advisory findings
 10. renderers + check-policy (script)    Bedrock / NeMo drafts; same checks as CI

Counting unit: controls. A control is "grounded" if at least one value is
vendor-grounded, otherwise "catalog-default" (opinionated baseline, NOT
vendor-backed); unselected controls are "excluded".

Only cloud models are allowed (see pipeline.enforce_cloud_models).
The profile must be SANITIZED: it is sent to the model provider.
Rate-limit and connection errors are retried 3 times with exponential
backoff; a specialist that still fails is retried once more.

Writes outputs/<run>/: policy.json (canonical, schema-validated),
exceptions.md (tiers, waivers, every dropped proposal and why), tests.jsonl
(>= 1 test per selected control), evidence.json, bedrock-guardrail.json /
nemo-config.yml with their reports; plus logs/<run>/.
--dry-run selects controls and prints the prompts without any model call.
--no-llm builds the policy from catalog defaults only (no model call).

Exit codes: 0 ok, 1 checks failed, 2 a step failed, 64 usage / invalid input.
Standard library only.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import html
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pipeline as P  # noqa: E402



def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SEL = _load("select_controls", "select-controls.py")
GEN = _load("gen_configs", "gen-configs.py")
RB = _load("render_bedrock", "render-bedrock.py")
RN = _load("render_nemo", "render-nemo.py")
CP = _load("check_policy", "check-policy.py")
import guardrail_policy as GP  # noqa: E402
import guardrail_values as GV  # noqa: E402

CONFIG = "agents/guardrail-policy-generator.yaml"
DEFAULTS = {
    "OLLAMA_BASE_URL": "http://localhost:11434/v1",
    "ROUTER_MODEL": "nemotron-3-super:cloud",
    "SPECIALIST_MODEL": "nemotron-3-nano:30b-cloud",
    "REVIEWER_MODEL": "nemotron-3-super:cloud",
    "JUDGE_MODEL": "gpt-oss:120b-cloud",
}
MODEL_VARS = ("ROUTER_MODEL", "SPECIALIST_MODEL", "REVIEWER_MODEL", "JUDGE_MODEL")
SOURCE_KINDS = {"documented-default", "documented-limit-or-enum", "example-config", "other"}
PARAM_NAME = re.compile(r"^[a-z][a-z0-9_]{0,59}$")
PARALLEL_DEFAULT, PARALLEL_MAX = 4, 7
RETRY_TRIES = 3
RETRYABLE = re.compile(r"429|rate.?limit|too many requests|connection|stalled|timed? ?out|timeout|"
                       r"temporar|unavailable|50[234]|EOF|reset by peer|no data received", re.I)


def clamp_parallel(n: int) -> int:
    return max(1, min(PARALLEL_MAX, n))


def is_retryable(run: "P.AgentRun") -> bool:
    """Cloud rate limits and connection problems are worth retrying."""
    return bool(RETRYABLE.search(" ".join(run.errors)))


def call_agent(config, agent, prompt, log_path, timeout, run=None, sleep=time.sleep):
    """run_agent with up to RETRY_TRIES tries and exponential backoff
    (GUARDRAIL_BACKOFF_SECONDS * 2**attempt) on rate-limit/connection errors."""
    run = run or P.run_agent
    base = float(os.environ.get("GUARDRAIL_BACKOFF_SECONDS", "5"))
    for attempt in range(RETRY_TRIES):
        path = log_path if attempt == 0 else log_path.with_suffix(f".try{attempt + 1}.ndjson")
        r = run(config, agent, prompt, path, timeout)
        if (r.rc == 0 and r.final) or not is_retryable(r) or attempt == RETRY_TRIES - 1:
            return r
        wait = base * 2 ** attempt
        log(f"{agent}: retryable error ({r.errors[-1][:80]}); retry {attempt + 2}/{RETRY_TRIES} in {wait:g}s")
        sleep(wait)
    return r


def log(msg: str) -> None:
    print(f"[guardrail] {msg}", file=sys.stderr, flush=True)


def load_dotenv(path: Path) -> None:
    """Export KEY=VALUE lines from .env without overriding the environment."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.removeprefix("export ").strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k) and k not in os.environ:
            os.environ[k] = v


# --------------------------------------------------------------------------
# Sources: start pages are fetched ONCE by this script (cached), and the
# specialists get relevant excerpts. This bounds cost and time, and the
# quote check runs against exactly the text the specialist was given.
# --------------------------------------------------------------------------
USER_AGENT = "grounded-ai-guardrails guardrail-policy-generator (+https://github.com/arifbazli/grounded-ai-guardrails)"
SKIP_TAGS = {"script", "style", "nav", "header", "footer", "noscript", "svg", "form", "aside", "button", "template"}
BLOCK_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "div", "tr", "br", "section", "pre",
              "td", "th", "dd", "dt", "table", "ul", "ol", "article", "main", "blockquote"}
STOP = set("""about above after again against also because been before being below between both
could does doing down during each from further have having here into itself just more most other
over same should some such than that their them then there these they this those through under
until very what when where which while with would your input output before reach""".split())
HINT_WORDS = ["threshold", "strength", "limit", "filter", "block", "mask", "rail", "timeout", "maximum",
              "minimum", "deny", "allow", "configure", "detect", "policy", "score", "level", "action"]


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self.skip += 1
        elif tag in BLOCK_TAGS:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS and self.skip:
            self.skip -= 1
        elif tag in BLOCK_TAGS:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(raw: str) -> str:
    p = _Text()
    p.feed(raw)
    lines = (re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in "".join(p.out).splitlines())
    return "\n".join(ln for ln in lines if ln)


def category_sources(cat: str) -> list[str]:
    """Start pages for a category, from its scope file's SOURCES section."""
    scope = GEN.load_scope(ROOT / "templates" / "scopes" / f"guardrail-{cat}.txt")
    text = GEN.render(scope["SOURCES"], GEN.load_seeds(), f"guardrail-{cat}.txt[SOURCES]")
    return [u.strip() for u in text.splitlines() if u.strip().startswith("https://")]


def fetch_page(url: str, cache: Path, max_age_days: float) -> P.Page:
    reason = P.banned_url(url)
    if reason:
        return P.Page(url, False, None, "", reason)
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".txt")
    if path.exists() and time.time() - path.stat().st_mtime < max_age_days * 86400:
        return P.Page(url, True, 200, path.read_text(encoding="utf-8"))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/markdown,text/plain"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read(3_000_000).decode(resp.headers.get_content_charset() or "utf-8", "replace")
            status, ctype = resp.status, resp.headers.get_content_type()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return P.Page(url, False, getattr(e, "code", None), "", str(e)[:200])
    text = html_to_text(raw) if "html" in ctype or raw.lstrip()[:15].lower().startswith(("<!doctype", "<html")) else raw
    if re.search(r"(?m)^#?\s*Page Not Found", text[:500]):
        return P.Page(url, False, 404, "", "page not found")
    path.write_text(text, encoding="utf-8")
    return P.Page(url, True, status, text)


def keywords(controls: list[dict]) -> set[str]:
    words = set(HINT_WORDS)
    for c in controls:
        for k in c.get("allowed_parameter_keys", []):
            words.update(w for w in k.split("_") if len(w) >= 4 and w not in STOP)
        for w in re.findall(r"[a-z][a-z-]{3,}", (c["name"] + " " + c["description"]).lower()):
            if w not in STOP:
                words.add(w.rstrip("s"))
    return words


def excerpt(text: str, words: set[str], budget: int) -> str:
    """Highest-scoring paragraphs (by distinct keyword hits) within budget,
    kept in page order."""
    paras = [(i, ln) for i, ln in enumerate(text.splitlines()) if len(ln) >= 30]
    scored = []
    for i, ln in paras:
        low = ln.lower()
        score = sum(1 for w in words if w in low)
        if score:
            scored.append((score, i, ln))
    keep, used = [], 0
    for score, i, ln in sorted(scored, key=lambda t: (-t[0], t[1])):
        if used + len(ln) > budget:
            continue
        keep.append((i, ln))
        used += len(ln) + 1
    return "\n".join(ln for _, ln in sorted(keep))


def sources_block(pages: list[P.Page], controls: list[dict], budget: int) -> tuple[str, list[dict]]:
    good = [p for p in pages if p.ok and p.body]
    if not good:
        return "", []
    per_page = max(1500, budget // len(good))
    words = keywords(controls)
    parts, meta = [], []
    for p in good:
        ex = excerpt(p.body, words, per_page)
        if ex:
            parts.append(f"=== SOURCE {p.url} ===\n{ex}")
        meta.append({"url": p.url, "chars": len(p.body), "excerpt_chars": len(ex)})
    return "\n\n".join(parts), meta


# --------------------------------------------------------------------------
# Source kind classification (guardrail vendor values)
# --------------------------------------------------------------------------
EXAMPLE_MARKERS = ("example", "sample", "```")


def classify_source_kind(quote: str, page_text: str | None, specialist_kind: str | None) -> str:
    """Return a source_kind. A quote that sits in an example/sample config block
    on the page is forced to "example-config" regardless of the specialist's claim."""
    kind = specialist_kind if specialist_kind in SOURCE_KINDS else "other"
    if page_text:
        idx = page_text.find(quote)
        if idx >= 0:
            before = page_text[:idx]
            # fenced code block detection: odd number of ``` before the quote
            if before.count("```") % 2 == 1:
                return "example-config"
            window = before[-600:] + page_text[idx:idx + max(60, len(quote))]
            low = window.lower()
            if any(m in low for m in ("example", "sample")):
                return "example-config"
    return kind


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------
control_line = SEL.control_line


def specialist_prompt(profile: dict, controls: list[dict], sources: str = "") -> str:
    text = ("PROFILE: " + json.dumps(profile, sort_keys=True) + "\nCONTROLS:\n"
            + "\n".join(control_line(c) for c in controls))
    return text + ("\n\nSOURCES:\n" + sources if sources else "")


# --------------------------------------------------------------------------
# Parsing specialist output
# --------------------------------------------------------------------------
def extract_json(text: str, opener: str):
    """Return the first JSON value starting with `opener` ('[' or '{') in text."""
    text = re.sub(r"```(?:json)?", "", text)
    dec = json.JSONDecoder()
    for m in re.finditer(re.escape(opener), text):
        try:
            value, _ = dec.raw_decode(text[m.start():])
            return value
        except ValueError:
            continue
    return None


def extract_objects(text: str) -> list:
    """Every top-level JSON object in text that has a control_id."""
    dec, out, i = json.JSONDecoder(), [], 0
    text = re.sub(r"```(?:json)?", "", text)
    while True:
        i = text.find("{", i)
        if i < 0:
            return out
        try:
            obj, end = dec.raw_decode(text[i:])
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict) and "control_id" in obj:
            out.append(obj)
            i += end
        else:
            i += 1



def parse_proposals(text: str, value_types: dict[str, dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (valid proposals, rejected items with reason, null answers).

    `value_types` maps each control id assigned to this specialist to its
    {key: value_type} (the allowed keys). Accepts per-key items
    {"control_id", "key", "value", ...} and the older
    {"control_id", "parameters": {...}, ...}. Every proposal returned holds
    exactly one parameter whose value passed the catalog value-type check
    (before any judge sees it)."""
    data = extract_json(text, "[")
    if not isinstance(data, list) or not data:
        # Fall back to every well-formed object that has a control_id, so one
        # broken item (or a truncated array) does not lose the others.
        data = extract_objects(text)
        if not data:
            return [], ([] if re.fullmatch(r"\s*(```(json)?\s*)?\[\s*\](\s*```)?\s*", text) else
                        [{"item": text[:200], "reason": "output contains no JSON proposal objects"}]), []
    ok, bad, nulls = [], [], []
    unparsed = text.count('"control_id"') - len(data)
    if unparsed > 0:
        bad.append({"item": text[:200], "reason": f"{unparsed} proposal(s) in the output were not valid JSON"})
    for item in data:
        if not isinstance(item, dict):
            bad.append({"item": item, "reason": "not an object"})
            continue
        cid = item.get("control_id")
        if cid not in value_types:
            bad.append({"item": item, "reason": f"control_id {cid!r} was not assigned to this specialist"})
            continue
        if "key" in item:
            pairs = [(item.get("key"), item.get("value"))]
        elif isinstance(item.get("parameters"), dict) and item["parameters"]:
            pairs = list(item["parameters"].items())
        else:
            bad.append({"item": item, "reason": "no parameters"})
            continue
        url, quote = item.get("source_url"), item.get("source_quote")
        for key, value in pairs:
            one = dict(item, key=key, value=value)
            one.pop("parameters", None)
            if not isinstance(key, str) or not PARAM_NAME.match(key):
                bad.append({"item": one, "reason": "parameter name must be snake_case"})
                continue
            if key not in value_types[cid]:
                bad.append({"item": one, "reason": f"parameter key(s) ['{key}'] not in allowed_parameter_keys for {cid}"})
                continue
            if value is None:
                nulls.append({"control_id": cid, "key": key})
                continue
            if not isinstance(url, str) or not url.startswith("https://"):
                bad.append({"item": one, "reason": "missing or non-https source_url"})
                continue
            if not isinstance(quote, str) or not quote.strip():
                bad.append({"item": one, "reason": "missing source_quote"})
                continue
            quote_clean = quote.strip().strip('"')
            norm, why = GV.check_value(value_types[cid][key], value, quote_clean)
            if why:
                bad.append({"item": one, "reason": f"value type check: {why}"})
                continue
            sk = item.get("source_kind")
            if sk not in SOURCE_KINDS:
                sk = "other"
            ok.append({"control_id": cid, "parameters": {key: norm}, "source_kind": sk,
                       "rationale": str(item.get("rationale") or "").strip(),
                       "source_url": P.clean_url(url), "source_quote": quote_clean})
    return ok, bad, nulls


def to_fact(n: int, prop: dict, name: str) -> P.Fact:
    params = json.dumps(prop["parameters"], sort_keys=True)
    line = (f"CONTROL: {prop['control_id']} {name} | PARAMETERS: {params} | "
            f"RATIONALE: {prop['rationale'] or 'none'} | QUOTE: \"{prop['source_quote']}\" | URL: {prop['source_url']}")
    return P.Fact(n=n, line=line, fact=params, product="guardrail", module=prop["control_id"],
                  quote=prop["source_quote"], url=prop["source_url"], month="unknown")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate an advisory guardrail policy from a sanitized app profile.")
    ap.add_argument("profile")
    ap.add_argument("-c", "--config", default=os.environ.get("GUARDRAIL_CFG", CONFIG))
    ap.add_argument("--out-dir", default=os.environ.get("OUT_DIR", "outputs"))
    ap.add_argument("--timeout", type=int, default=int(os.environ.get("STAGE_TIMEOUT", "900")))
    ap.add_argument("--parallel", type=int, default=int(os.environ.get("GUARDRAIL_PARALLEL", str(PARALLEL_DEFAULT))),
                    help=f"specialists run at once (default {PARALLEL_DEFAULT}, max {PARALLEL_MAX})")
    ap.add_argument("--dry-run", action="store_true", help="select controls and print prompts; no model calls")
    ap.add_argument("--no-llm", action="store_true",
                    help="no model calls: policy from catalog recommended defaults only (all catalog-default), "
                         "script-generated tests, renderers and checks")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 64 if e.code else 0

    load_dotenv(ROOT / ".env")
    for k, v in DEFAULTS.items():
        os.environ.setdefault(k, v)
    os.environ.setdefault("TELEMETRY_ENABLED", "false")
    rc = P.enforce_cloud_models({k: os.environ[k] for k in MODEL_VARS})
    if rc:
        return rc

    try:
        profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
        catalog = SEL.load_catalog()
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 64
    errors = SEL.validate_profile(profile)
    if errors:
        print("invalid profile:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 64
    if not (ROOT / args.config).exists():
        print(f"config not found: {args.config}", file=sys.stderr)
        return 64

    by_id = {c["id"]: c for c in catalog["controls"]}
    selection = SEL.select(profile, catalog)
    work = {cat: [by_id[i] for i in ids] for cat, ids in selection["by_category"].items() if ids}
    log(f"selected {len(selection['selected'])}/{len(by_id)} controls in {len(work)} categories")

    if args.dry_run:
        for cat, ctls in work.items():
            urls = "\n".join(f"  {u}" for u in category_sources(cat))
            print(f"===== {cat}_specialist =====\n{specialist_prompt(profile, ctls)}\nSTART PAGES:\n{urls}\n")
        return 0

    name = P.slugify(profile.get("name") or Path(args.profile).stem)
    run_id = f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-guardrail-{name}"
    out = ROOT / args.out_dir / run_id
    logs = ROOT / "logs" / run_id
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    evidence = {
        "run_id": run_id, "question": f"guardrail policy for profile {name}", "config": args.config,
        "mode": "guardrail-pipeline", "models": {k: os.environ[k] for k in MODEL_VARS},
        "catalog_version": catalog["catalog_version"], "selection": selection,
        "stages": {}, "facts": [], "pages": {}, "rejected": [], "no_vendor_value": [],
    }

    def stage(r: P.AgentRun) -> None:
        evidence["stages"][r.agent] = {
            "rc": r.rc, "seconds": r.seconds, "fetch_calls": r.fetch_calls,
            "pages": [{"url": p.url, "ok": p.ok, "status": p.status, "error": p.error} for p in r.pages],
            "errors": r.errors,
        }

    def finish(code: int, result: str) -> int:
        evidence["result"] = result
        evidence["exit_code"] = code
        evidence["seconds_total"] = round(time.time() - t0, 1)
        (out / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        (ROOT / args.out_dir / ".last-guardrail").write_text(f"{args.out_dir}/{run_id}\n", encoding="utf-8")
        log(f"{result} -> {args.out_dir}/{run_id}/ ({evidence['seconds_total']}s)")
        return code

    def finalize(proposals, grounded, dropped, failed, stage_failures, use_llm):
        """Policy, tests, exceptions, renderers and checks. Shared by the
        model pipeline and --no-llm (catalog defaults only)."""
        # canonical policy
        policy, conflicts = GP.build_policy(profile, catalog, selection, grounded, run_id)
        dropped += conflicts
        errors = GP.validate_policy(policy)
        (out / "policy.json").write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
        if errors:
            evidence["policy_errors"] = errors
            return finish(1, "CHECKS FAILED: policy.json does not match schemas/policy.schema.json")

        # assembler: test cases (script fallback for any control without one)
        controls_in = [{"control_id": c["control_id"], "name": c["name"], "category": c["category"], "tier": c["tier"],
                        "parameters": {p["name"]: p["value"] for p in c["parameters"]}} for c in policy["controls"]]
        assembled = {}
        if use_llm:
            ar = call_agent(args.config, "assembler", json.dumps({"controls": controls_in}, indent=1),
                            logs / "assembler.ndjson", args.timeout)
            stage(ar)
            assembled = extract_json(ar.final, "{") if ar.rc == 0 else None
            if not isinstance(assembled, dict):
                stage_failures.append("assembler")
                assembled = {}
        tests, bad_tests = GP.build_tests(policy, assembled.get("tests", []))
        dropped += bad_tests

        # reviewer: advisory findings
        review = {"findings": []}
        if use_llm:
            rr = call_agent(args.config, "reviewer",
                            json.dumps({"profile": profile, "controls": controls_in, "tests": tests}, indent=1),
                            logs / "reviewer.ndjson", args.timeout)
            stage(rr)
            review = extract_json(rr.final, "{") if rr.rc == 0 else None
            if not isinstance(review, dict):
                stage_failures.append("reviewer")
                review = {"findings": []}

        (out / "tests.jsonl").write_text("".join(json.dumps(t) + "\n" for t in tests), encoding="utf-8")
        (out / "exceptions.md").write_text(
            GP.exceptions_md(policy, catalog, dropped, failed, review.get("findings", []), tests), encoding="utf-8")
        (out / "review.json").write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
        for renderer in (RB, RN):
            renderer.main([str(out / "policy.json")])
        evidence["counts"] = GP.counts(policy)  # counting unit: controls
        evidence["counts"]["proposals_total"] = len(proposals)
        evidence["counts"]["proposals_supported"] = len(grounded)
        evidence["counts"]["proposals_dropped"] = len(dropped)

        # check-policy: the same deterministic checks CI runs
        problems = CP.check(policy, catalog, tests)
        evidence["check_policy"] = problems or "PASS"
        if problems:
            return finish(1, f"CHECKS FAILED: check-policy found {len(problems)} problem(s), see evidence.json")
        if stage_failures:
            return finish(2, f"BRIEFING FAILED: {', '.join(stage_failures)} returned no usable output (other outputs written)")
        n = evidence["counts"]
        return finish(0, f"OK (controls): {n['grounded']} grounded, {n['catalog_default']} catalog-default, "
                         f"{n['excluded']} excluded")

    if args.no_llm:
        evidence["mode"] = "guardrail-no-llm"
        return finalize([], [], [], [], [], use_llm=False)

    # 2. start pages, fetched once by this script (cached under fetched/guardrail/)
    budget = int(os.environ.get("GUARDRAIL_CONTEXT_CHARS", "24000"))
    cache_days = float(os.environ.get("GUARDRAIL_CACHE_DAYS", "7"))
    page_cache: dict[str, P.Page] = {}
    prompts, evidence["sources"] = {}, {}
    for cat, ctls in work.items():
        cat_pages = []
        for url in category_sources(cat):
            if url not in page_cache:
                page_cache[url] = fetch_page(url, ROOT / "fetched" / "guardrail", cache_days)
            cat_pages.append(page_cache[url])
        block, meta = sources_block(cat_pages, ctls, budget)
        evidence["sources"][cat] = meta + [{"url": p.url, "error": p.error} for p in cat_pages if not p.ok]
        prompts[cat] = specialist_prompt(profile, ctls, block)
    bad_pages = [u for u, p in page_cache.items() if not p.ok]
    log(f"sources: {len(page_cache) - len(bad_pages)}/{len(page_cache)} start pages available")

    # 3. specialists, in parallel (one retry each)
    def run_specialist(cat: str):
        agent = f"{cat}_specialist"
        r = call_agent(args.config, agent, prompts[cat], logs / f"{agent}.ndjson", args.timeout)
        if r.rc != 0 or not r.final:
            log(f"{agent}: retrying once")
            r = call_agent(args.config, agent, prompts[cat], logs / f"{agent}.retry.ndjson", args.timeout)
        return cat, r

    runs: dict[str, P.AgentRun] = {}
    with cf.ThreadPoolExecutor(max_workers=clamp_parallel(args.parallel)) as pool:
        for cat, r in pool.map(run_specialist, list(work)):
            runs[cat] = r
            stage(r)
    failed = [c for c, r in runs.items() if r.rc != 0 or not r.final]
    evidence["failed_specialists"] = failed
    if failed and len(failed) == len(runs):
        return finish(2, "BRIEFING FAILED: every specialist returned no usable output")
    runs = {c: r for c, r in runs.items() if c not in failed}

    # Quote check uses the provided pages (full text) plus anything a
    # specialist fetched itself despite the instructions.
    pages = [p for p in page_cache.values() if p.ok] + [p for r in runs.values() for p in r.pages]
    text_by_url = {p.url: p.body for p in pages if p.ok and getattr(p, "body", None)}
    evidence["pages"] = P.save_pages([p for r in runs.values() for p in r.pages], ROOT / "fetched")
    proposals = []
    for cat, r in runs.items():
        ok, bad, nulls = parse_proposals(r.final, {c["id"]: c["value_types"] for c in work[cat]})
        evidence["no_vendor_value"] += nulls
        proposals += ok
        evidence["rejected"] += [dict(b, category=cat) for b in bad]
    for pr in proposals:
        pr["source_kind"] = classify_source_kind(pr.get("source_quote", ""), text_by_url.get(pr.get("source_url", "")), pr.get("source_kind"))
    (out / "specialists.json").write_text(json.dumps(proposals, indent=2) + "\n", encoding="utf-8")
    log(f"specialists: {len(proposals)} proposal(s), {len(evidence['rejected'])} rejected as malformed")

    # 4. quote check, 5. judge
    facts = [to_fact(i, p, by_id[p["control_id"]]["name"]) for i, p in enumerate(proposals, 1)]
    P.check_quotes(facts, pages)
    pending = [f for f in facts if not f.verdict]
    judged = {f.n for f in pending}
    log(f"quote check: {len(pending)} found on page, {len(facts) - len(pending)} rejected")
    stage_failures = list(failed)
    if pending:
        jr = call_agent(args.config, "judge", "\n".join(f"[{f.n}] {f.line}" for f in pending),
                         logs / "judge.ndjson", args.timeout)
        stage(jr)
        if jr.rc != 0 or not jr.final:
            return finish(2, "BRIEFING FAILED: judge returned no usable output")
        P.apply_judge(facts, jr.final)
    evidence["facts"] = [dict(asdict(f), control_id=p["control_id"], parameters=p["parameters"],
                              rationale=p["rationale"]) for f, p in zip(facts, proposals)]
    evidence["verdict_counts"] = {v: sum(f.verdict == v for f in facts) for v in P.VERDICTS}
    grounded = [dict(p, source_url=f.url) for f, p in zip(facts, proposals) if f.verdict == "SUPPORTED"]
    log("verdicts: " + ", ".join(f"{k}={v}" for k, v in evidence["verdict_counts"].items()))

    # Every proposal that is not used is listed in exceptions.md with its reason.
    dropped = [{"control_id": r["item"].get("control_id", "?") if isinstance(r["item"], dict) else "?",
                "stage": f"{r['category']} specialist output", "reason": r["reason"],
                "detail": json.dumps(r["item"])[:200] if isinstance(r["item"], dict) else str(r["item"])[:200]}
               for r in evidence["rejected"]]
    for f, p in zip(facts, proposals):
        if f.verdict != "SUPPORTED":
            dropped.append({"control_id": p["control_id"],
                            "stage": "judge" if f.n in judged else "quote check",
                            "reason": f"{f.verdict}: {f.note}",
                            "detail": f"{json.dumps(p['parameters'])} from {f.url}"})

    return finalize(proposals, grounded, dropped, failed, stage_failures, use_llm=True)


if __name__ == "__main__":
    sys.exit(main())
