#!/usr/bin/env bash
# usage: eval "$(scripts/prisma-login.sh)"
# Exchanges PRISMA_ACCESS_KEY / PRISMA_SECRET_KEY (from .env or the
# environment) for a Prisma Cloud CSPM token and prints
# `export PRISMA_TOKEN=...`. Tokens are valid for about 10 minutes.
# See https://pan.dev/prisma-cloud/api/cspm/app-login/
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/env.sh
. scripts/env.sh
load_env .env
: "${PRISMA_API_URL:?set PRISMA_API_URL}"
: "${PRISMA_ACCESS_KEY:?set PRISMA_ACCESS_KEY}"
: "${PRISMA_SECRET_KEY:?set PRISMA_SECRET_KEY}"
body=$(python3 -c 'import json,os; print(json.dumps({"username": os.environ["PRISMA_ACCESS_KEY"], "password": os.environ["PRISMA_SECRET_KEY"]}))')
resp=$(curl -fsS --max-time 30 -X POST "${PRISMA_API_URL%/}/login" \
  -H 'Content-Type: application/json' -H 'Accept: application/json' --data-binary @- <<<"$body")
token=$(printf '%s' "$resp" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
printf 'export PRISMA_TOKEN=%q\n' "$token"
