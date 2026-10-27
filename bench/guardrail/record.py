#!/usr/bin/env python3
"""Append one row per guardrail run to bench/guardrail/results.tsv.

usage: bench/guardrail/record.py outputs/<run>/ [note]
Counts are per CONTROL (grounded / catalog-default / excluded); vendor
parameters are counted separately and labelled as such."""
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "bench" / "guardrail" / "results.tsv"
HEADER = ["date", "commit", "profile", "specialist_model", "judge_model", "seconds", "exit",
          "controls_selected", "controls_grounded", "controls_catalog_default", "controls_excluded",
          "params_vendor_grounded", "check_policy", "note"]


def main() -> int:
    run = Path(sys.argv[1])
    note = sys.argv[2] if len(sys.argv) > 2 else ""
    ev = json.loads((run / "evidence.json").read_text())
    n = ev.get("counts", {})
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    row = [date.today().isoformat(), commit or "unknown", ev["question"].rsplit(" ", 1)[-1],
           ev["models"].get("SPECIALIST_MODEL", "-"), ev["models"].get("JUDGE_MODEL", "-"),
           str(ev.get("seconds_total", "")), str(ev.get("exit_code", "")),
           *(str(n.get(k, "")) for k in ("selected", "grounded", "catalog_default", "excluded", "parameters_vendor_grounded")),
           {None: "not-run"}.get(ev.get("check_policy"), "PASS" if ev.get("check_policy") == "PASS" else "FAIL"), note]
    if not RESULTS.exists():
        RESULTS.write_text("\t".join(HEADER) + "\n")
    with RESULTS.open("a") as f:
        f.write("\t".join(row) + "\n")
    print("\t".join(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
