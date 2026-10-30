#!/usr/bin/env bash
# usage: scripts/check-seeds.sh [seeds/*.txt ...]
# Checks every seed URL still resolves (HTTP 200 and not a GitBook soft 404).
# CI runs this nightly so moved documentation pages are caught early.
cd "$(dirname "$0")/.." || exit 2
[ $# -eq 0 ] && set -- seeds/*.txt
bad=0
while read -r u; do
  body=$(curl -sL --max-time 25 -A 'grounded-ai-guardrails seed check' -w '\n%{http_code}' "$u") \
    || { echo "FAIL (curl) $u"; bad=1; continue; }
  code=${body##*$'\n'}
  if [ "$code" != 200 ]; then echo "FAIL $code $u"; bad=1
  elif printf '%s' "$body" | grep -qE '^# Page Not Found|<title>Page Not Found'; then echo "FAIL soft-404 $u"; bad=1
  else echo "ok   $u"; fi
done < <(grep -hvE '^\s*(#|$)' "$@" | sort -u)
exit $bad
