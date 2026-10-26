#!/usr/bin/env bash
# usage: scripts/gen-tenant-config.sh      (reads .env)
# Renders templates/tenant-readonly.yaml.tmpl -> agents/tenant-readonly.local.yaml
# (git-ignored). docker-agent needs literal hosts in api endpoints, so the
# tenant host names are written into the file; credentials are not.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=scripts/env.sh
. scripts/env.sh
load_env .env
: "${PRISMA_API_URL:?set PRISMA_API_URL in .env (e.g. https://api.prismacloud.io)}"
: "${CORTEX_FQDN:?set CORTEX_FQDN in .env (tenant FQDN without api-)}"
prisma_host=${PRISMA_API_URL#https://}; prisma_host=${prisma_host%%/*}
cortex_fqdn=${CORTEX_FQDN#https://}; cortex_fqdn=${cortex_fqdn#api-}; cortex_fqdn=${cortex_fqdn%%/*}
for h in "$prisma_host" "$cortex_fqdn"; do
  [[ "$h" =~ ^[A-Za-z0-9.-]+$ ]] || { echo "invalid host: $h" >&2; exit 1; }
done
seeds=$(grep -vE '^\s*(#|$)' seeds/migration.txt | sed 's/^/             - /')
out=agents/tenant-readonly.local.yaml
python3 - "$prisma_host" "$cortex_fqdn" "$seeds" > "$out" <<'PY'
import sys
prisma, cortex, seeds = sys.argv[1:4]
t = open("templates/tenant-readonly.yaml.tmpl", encoding="utf-8").read()
t = t.replace("{{PRISMA_API_HOST}}", prisma).replace("{{CORTEX_FQDN}}", cortex)
t = t.replace("             {{SEEDS_MIGRATION}}", seeds)
sys.stdout.write(t)
PY
echo "wrote $out" >&2
