#!/usr/bin/env bash
# usage: bench/guardrail/check-golden.sh        (no model calls; CI runs it)
#
# For each golden profile in bench/guardrail/*.profile.json:
#   1. build the policy without models (scripts/guardrail.py --no-llm)
#   2. scripts/check-policy.py must PASS against <profile>.expected.json
#   3. mutation checks must FAIL: a removed control, a duplicated control,
#      a mistyped value and a catalog default claiming a vendor source.
# Expected answers live in the *.expected.json files, never in prompts.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 2
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
fail=0
for profile in bench/guardrail/*.profile.json; do
  name=$(basename "$profile" .profile.json)
  OUT_DIR="${out#"$PWD"/}" python3 scripts/guardrail.py --no-llm "$profile" >/dev/null 2>"$out/$name.err" \
    || { echo "FAIL $name: guardrail.py --no-llm"; cat "$out/$name.err"; fail=1; continue; }
  run=$(cat "$out/.last-guardrail")
  policy="$run/policy.json"
  if python3 scripts/check-policy.py "$policy" --tests "$run/tests.jsonl" \
       --expected "bench/guardrail/$name.expected.json" >"$out/$name.check" 2>&1; then
    echo "ok   $name: $(tail -n 1 "$out/$name.check")"
  else
    echo "FAIL $name:"; cat "$out/$name.check"; fail=1
  fi
  for mutation in remove_control duplicate_control bad_value default_with_source; do
    python3 - "$policy" "$out/$name.$mutation.json" "$mutation" <<'PY'
import json, sys
src, dst, kind = sys.argv[1:4]
p = json.load(open(src))
c = p["controls"]
if kind == "remove_control":
    c.pop(0)
elif kind == "duplicate_control":
    c.append(json.loads(json.dumps(c[0])))
elif kind == "bad_value":
    target = next(x for x in c for q in x["parameters"] if isinstance(q["value"], bool))
    next(q for q in target["parameters"] if isinstance(q["value"], bool))["value"] = "BLOCK"
elif kind == "default_with_source":
    q = next(q for x in c for q in x["parameters"] if q["basis"] == "catalog-default")
    q["source_url"], q["source_quote"] = "https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html", "made up"
json.dump(p, open(dst, "w"))
PY
    if python3 scripts/check-policy.py "$out/$name.$mutation.json" \
         --expected "bench/guardrail/$name.expected.json" >/dev/null 2>&1; then
      echo "FAIL $name: mutation '$mutation' was not caught"; fail=1
    else
      echo "ok   $name: mutation '$mutation' caught"
    fi
  done
done
exit $fail
