# shellcheck shell=bash
# Sourced by the scripts: export variables from .env WITHOUT overriding
# ones already set, so `CFG=... scripts/run.sh` beats CFG in .env.
load_env() {
  local file="${1:-.env}" k v
  [ -f "$file" ] || return 0
  while IFS='=' read -r k v || [ -n "$k" ]; do
    k="${k#export }"
    [[ "$k" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    [ -n "${!k+x}" ] && continue
    v="${v%$'\r'}"
    if [[ "$v" =~ ^\"(.*)\"$ || "$v" =~ ^\'(.*)\'$ ]]; then v="${BASH_REMATCH[1]}"; fi
    export "$k=$v"
  done < "$file"
}
