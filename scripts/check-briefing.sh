#!/usr/bin/env bash
# usage: scripts/check-briefing.sh <briefing.md> [evidence.json]
# Format checks on a briefing. With the evidence file written by
# scripts/pipeline.py it also checks that every cited URL was fetched in
# that run and, in pipeline mode, that every cited URL backs a SUPPORTED fact.
f="${1:?usage: $0 briefing.md [evidence.json]}"; ev="${2:-}"
fail=0
bad() { echo "FAIL: $*"; fail=1; }
ok()  { echo "ok:   $*"; }

[ -s "$f" ] || { echo "FAIL: briefing missing or empty"; exit 1; }

first=$(head -1 "$f")
case "$first" in
  "OUT OF SCOPE:"*|"NO FACTS FOUND:"*|"NO SUPPORTED FACTS AVAILABLE FOR BRIEFING"*)
    ok "valid sentinel: $first"; exit 0;;
  "BRIEFING FAILED:"*) bad "$first"; exit 1;;
esac

if [[ "$first" =~ ^#\ .*Briefing:\ .+ ]]; then ok "heading: $first"; else bad "first line is not a '# ... Briefing: <topic>' heading"; fi

if grep -Eq 'https?://[^ )]*\?' "$f"; then bad "URL containing '?'"; else ok "no query-string URLs"; fi

if LC_ALL=C grep -q '[^[:print:][:space:]]' "$f"; then
  bad "non-ASCII characters"; LC_ALL=C grep -n '[^[:print:][:space:]]' "$f" | head -3
else ok "ASCII only"; fi

words=$(sed -E 's#https?://[^ )]+##g' "$f" | wc -w)
max=170
grep -qE '^\*\*(Mapping|Manual work)\*\*' "$f" && max=260
if [ "$words" -le "$max" ]; then ok "$words words (max $max)"; else bad "$words words (max $max)"; fi

for s in '**Bottom line:**' '**Sources**'; do
  grep -qF -- "$s" "$f" || bad "missing section: $s"
done

if grep -qF 'No claims could be verified' "$f"; then bad "all claims rejected by verifier"; fi

if [ -n "$ev" ] && [ -s "$ev" ]; then
  python3 - "$f" "$ev" <<'PY' || fail=1
import json, re, sys
brief = open(sys.argv[1], encoding="utf-8").read()
ev = json.load(open(sys.argv[2], encoding="utf-8"))
key = lambda u: re.sub(r"^https?://", "", u.split("#")[0]).rstrip("/.,;)").removesuffix(".md")
fetched = {key(p["url"]) for s in ev.get("stages", {}).values() for p in s.get("pages", []) if p.get("ok")}
supported = {key(x["url"]) for x in ev.get("facts", []) if x.get("verdict") == "SUPPORTED"}
cited = sorted({key(u) for u in re.findall(r"https?://[^\s)`>]+", brief)})
bad = 0
for u in cited:
    if u not in fetched:
        print(f"FAIL: cited but never fetched: {u}"); bad = 1
    elif ev.get("mode") == "pipeline" and supported and u not in supported and "**To confirm**" not in brief:
        print(f"FAIL: cited URL backs no SUPPORTED fact: {u}"); bad = 1
if not bad:
    print(f"ok:   all {len(cited)} cited URL(s) were fetched in this run")
c = ev.get("verdict_counts")
if c:
    print("info: verdicts " + ", ".join(f"{k}={v}" for k, v in c.items()))
sys.exit(bad)
PY
fi

[ $fail -eq 0 ] && echo "PASS" || echo "FAILED"
exit $fail
