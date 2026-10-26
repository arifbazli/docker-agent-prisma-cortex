#!/usr/bin/env bash
# usage: scripts/run.sh "question"            (run from the repo root)
#
#   CFG=agents/cortex-cloud-hub.yaml   config (default agents/prisma-cortex-hub.yaml)
#   MODE=agent                         run the self-contained root agent instead
#                                      of the scripted pipeline
#   SAFETY=restricted                  docker-agent --safety level (default
#                                      restricted: fetch is allowed by the
#                                      config, anything else is refused)
#   RESEARCH_MODEL / JUDGE_MODEL / WRITER_MODEL / ROUTER_MODEL / OLLAMA_BASE_URL
#                                      override models (see .env.example)
#
# Exit codes: 0 = briefing passed checks (or a valid sentinel),
#             1 = briefing produced but failed checks,
#             2 = a pipeline step failed, 64 = usage.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 64
q="${1:?usage: $0 \"question\"}"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

start=$(date +%s)
python3 scripts/pipeline.py --config "${CFG:-agents/prisma-cortex-hub.yaml}" \
  --mode "${MODE:-pipeline}" -- "$q"
rc=$?
out=$(cat outputs/.last 2>/dev/null || true)

echo
echo "=== checks ==="
if [ "$rc" -ne 0 ] && [ "$rc" -ne 2 ]; then
  echo "FAIL: pipeline exited with code $rc"
  exit "$rc"
fi
scripts/check-briefing.sh "$out" "${out%.md}.evidence.json"
crc=$?
echo "elapsed: $(( $(date +%s) - start ))s   output: $out"
[ "$rc" -eq 2 ] && exit 2
exit "$crc"
