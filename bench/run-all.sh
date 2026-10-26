#!/usr/bin/env bash
# usage: bench/run-all.sh [id ...]      (no ids = all questions)
#   CFG=agents/cortex-cloud-hub.yaml    config to benchmark (default prisma-cortex-hub)
#   MODE=agent                          benchmark the self-contained root agent
#   OUT_DIR=outputs/x                   separate output dir (to run benches in parallel)
#
# Appends one row per question to bench/results.tsv (committed, so model or
# prompt changes can be compared against a baseline). A question PASSes when
# scripts/run.sh passes, the outcome matches `expect`, and every
# `must_include` pattern appears in the briefing.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
cfg="${CFG:-agents/prisma-cortex-hub.yaml}"
name=$(basename "$cfg" .yaml)
res=bench/results.tsv
[ -f "$res" ] || printf 'date\tcommit\tconfig\tmode\tresearch_model\tjudge_model\twriter_model\tid\tseconds\tresult\tverdicts\tnote\n' > "$res"
rev=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
pass=0; total=0

while IFS='|' read -r id expect must q; do
  case "$id" in ''|\#*) continue;; esac
  if [ $# -gt 0 ]; then printf '%s\n' "$@" | grep -qxF "$id" || continue; fi
  # per-config expectation, e.g. prisma-cortex-hub:briefing,cortex-cloud-hub:oos
  if [[ "$expect" == *:* ]]; then
    e=$(printf '%s' "$expect" | tr ',' '\n' | awk -F: -v n="$name" '$1==n{print $2}')
    expect="${e:-any}"
  fi
  start=$(date +%s)
  CFG="$cfg" scripts/run.sh "$q" </dev/null >/dev/null 2>&1; rc=$?
  secs=$(( $(date +%s) - start ))
  out=$(cat "${OUT_DIR:-outputs}/.last" 2>/dev/null); first=$(head -1 "$out" 2>/dev/null); note=""
  case "$expect" in
    oos)      [[ "$first" == "OUT OF SCOPE"* ]] || { rc=1; note="expected OUT OF SCOPE, got: ${first:0:40}"; } ;;
    briefing) [[ "$first" =~ ^#\ .*Briefing: ]] || { rc=1; note="no briefing: ${first:0:40}"; }
              if [ $rc -eq 0 ]; then
                IFS=';' read -ra pats <<< "$must"
                for p in "${pats[@]}"; do
                  [ -z "$p" ] && continue
                  grep -qiE -- "$p" "$out" || { rc=1; note="${note:+$note; }missing /$p/"; }
                done
              fi ;;
    any)      [[ "$first" == "BRIEFING FAILED"* ]] && { rc=1; note="$first"; } ;;
  esac
  meta=$(python3 - "${out%.md}.evidence.json" <<'PY' 2>/dev/null
import json, sys
e = json.load(open(sys.argv[1]))
m = e.get("models", {})
c = " ".join(f"{k.replace(' ', '_')}={v}" for k, v in (e.get("verdict_counts") or {}).items() if v)
print("\t".join([m.get("RESEARCH_MODEL", "-"), m.get("JUDGE_MODEL", "-"), m.get("WRITER_MODEL", "-"), c or "-"]))
PY
)
  [ -n "$meta" ] || meta=$'-\t-\t-\t-'
  [ $rc -eq 0 ] && { r=PASS; pass=$((pass+1)); } || r=FAIL
  total=$((total+1))
  IFS=$'\t' read -r rm jm wm verdicts <<< "$meta"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(date +%F)" "$rev" "$name" "${MODE:-pipeline}" \
    "$rm" "$jm" "$wm" "$id" "$secs" "$r" "$verdicts" "$note" | tee -a "$res"
done < bench/questions.txt
echo "passed $pass/$total"
[ "$pass" -eq "$total" ]
