#!/usr/bin/env bash
# usage: bench/guardrail/run-live.sh [profile-name ...]   (uses cloud models)
#   SPECIALIST_MODEL=... JUDGE_MODEL=... to compare models.
# Runs scripts/guardrail.py on the golden profiles, checks each policy
# against its expected control set and appends per-control counts to
# bench/guardrail/results.tsv (committed as the baseline).
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 2
[ $# -eq 0 ] && set -- rag-chatbot tool-agent memory-assistant
fail=0
for name in "$@"; do
  profile="bench/guardrail/$name.profile.json"
  python3 scripts/guardrail.py "$profile" </dev/null >/dev/null 2>&1; rc=$?
  run=$(cat "${OUT_DIR:-outputs}/.last-guardrail")
  python3 scripts/check-policy.py "$run/policy.json" --tests "$run/tests.jsonl" \
    --expected "bench/guardrail/$name.expected.json" >/dev/null 2>&1 || rc=1
  python3 bench/guardrail/record.py "$run" "run-live"
  [ $rc -eq 0 ] || fail=1
done
exit $fail
