"""Step 5: check-policy.py, --no-llm pipeline and counting unit (no model calls)."""
import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


SEL = load("select_controls", "select-controls.py")
GP = load("guardrail_policy", "guardrail_policy.py")
CP = load("check_policy", "check-policy.py")
GR = load("guardrail", "guardrail.py")
CATALOG = json.loads((ROOT / "seeds" / "guardrail-catalog.json").read_text())
URL = "https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-contextual-grounding-check.html"


def policy_for(name="rag-chatbot", grounded=()):
    p = json.loads((ROOT / "bench" / "guardrail" / f"{name}.profile.json").read_text())
    return GP.build_policy(p, CATALOG, SEL.select(p, CATALOG), list(grounded), "t")[0]


def mutate(policy, fn):
    p = json.loads(json.dumps(policy))
    fn(p)
    return CP.check(p, CATALOG)


class CheckPolicy(unittest.TestCase):
    def test_clean_policy_passes(self):
        policy = policy_for(grounded=[{"control_id": "OUTPUT-05", "parameters": {"grounding_threshold": 0.7},
                                       "rationale": "r", "source_url": URL,
                                       "source_quote": "set the grounding threshold to 0.7"}])
        tests, _ = GP.build_tests(policy, [])
        expected = json.loads((ROOT / "bench/guardrail/rag-chatbot.expected.json").read_text())
        self.assertEqual(CP.check(policy, CATALOG, tests, expected), [])

    def test_failures(self):
        policy = policy_for()
        cases = {
            "removed control": (lambda p: p["controls"].pop(0), "neither selected nor excluded"),
            "duplicate id": (lambda p: p["controls"].append(p["controls"][0]), "more than once"),
            "unknown id": (lambda p: p["excluded"][0].update(control_id="TOOL-11"), "schema"),
            "missing waiver": (lambda p: p["waivers"].pop(0), "no controls and no waiver"),
            "bad value": (lambda p: p["controls"][0]["parameters"][0].update(value="BLOCK"), "value type"),
            "unknown key": (lambda p: p["controls"][0]["parameters"][0].update(name="made_up"), "allowed_parameter_keys"),
            "unlabelled default": (lambda p: p["controls"][0]["parameters"][0].pop("label"), "must be labelled"),
            "default with a source": (lambda p: p["controls"][0]["parameters"][0].update(source_url=URL, source_quote="q"),
                                      "must not cite"),
            "wrong tier": (lambda p: p["controls"][0].update(tier="grounded"), "tier grounded"),
            "vendor value without quote": (lambda p: p["controls"][0]["parameters"][0].update(basis="vendor-grounded"),
                                           "without source_url"),
        }
        for label, (fn, needle) in cases.items():
            with self.subTest(label):
                errors = mutate(policy, fn)
                self.assertTrue(any(needle in e for e in errors), errors)

    def test_vendor_number_rules_rechecked(self):
        bad = [{"control_id": "RUNTIME-04", "parameters": {"max_input_tokens": 1024}, "rationale": "r",
                "source_url": URL, "source_quote": "if unset, the action falls back to 1024 tokens."}]
        errors = CP.check(policy_for(grounded=bad), CATALOG)
        self.assertTrue(any("does not mention input" in e for e in errors), errors)

    def test_tests_and_expected(self):
        policy = policy_for()
        tests, _ = GP.build_tests(policy, [])
        errors = CP.check(policy, CATALOG, tests[1:] + [{"control_id": "TOOL-01", "input": "x", "expected_behavior": "y"}],
                          {"expected_selected": ["INPUT-01"]})
        joined = " | ".join(errors)
        self.assertIn(f"{tests[0]['control_id']}: no test case", joined)
        self.assertIn("TOOL-01: test case for a control that is not selected", joined)
        self.assertIn("selected controls differ from expected", joined)

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            good = Path(d) / "p.json"
            good.write_text(json.dumps(policy_for()))
            bad = Path(d) / "bad.json"
            p = policy_for()
            p["controls"].pop()
            bad.write_text(json.dumps(p))
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(CP.main([str(good)]), 0)
                self.assertEqual(CP.main([str(bad)]), 1)
                self.assertEqual(CP.main([str(Path(d) / "missing.json")]), 64)


class NoLlmRunAndCounting(unittest.TestCase):
    """One counting unit (controls) in evidence.json, exceptions.md and check-policy."""

    def test_no_llm_outputs_agree(self):
        with tempfile.TemporaryDirectory() as d:
            self._check(d)

    def _check(self, d):
        with mock.patch.dict(os.environ, {"ALLOW_LOCAL_MODELS": "0"}), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = GR.main(["--no-llm", "--out-dir", d, str(ROOT / "bench/guardrail/tool-agent.profile.json")])
        run = Path((Path(d) / ".last-guardrail").read_text().strip())
        self.assertEqual(rc, 0)
        # .last-guardrail holds a path relative to the repo unless out-dir is absolute
        run = run if run.is_absolute() else ROOT / run
        self.assertTrue(run.exists(), run)
        for f in ("policy.json", "exceptions.md", "tests.jsonl", "evidence.json", "bedrock-guardrail.json", "nemo-config.yml"):
            self.assertTrue((run / f).exists(), f)
        ev = json.loads((run / "evidence.json").read_text())
        policy = json.loads((run / "policy.json").read_text())
        n = ev["counts"]
        self.assertEqual(n, {**GP.counts(policy), **{k: n[k] for k in n if k.startswith("proposals")}})
        self.assertEqual(n["unit"], "control")
        self.assertEqual((n["grounded"], n["catalog_default"], n["excluded"]), (0, 36, 34))
        md = (run / "exceptions.md").read_text()
        self.assertRegex(md, r"\| grounded .* \| 0 \|")
        self.assertRegex(md, r"\| catalog-default .* \| 36 \|")
        self.assertIn("Summary (counting unit: controls)", md)
        self.assertEqual(ev["check_policy"], "PASS")
        self.assertEqual(len((run / "tests.jsonl").read_text().splitlines()), 36)


class Repo(unittest.TestCase):
    def test_no_model_downloads_anywhere(self):
        needle = "ollama " + "pull"
        out = subprocess.run(["git", "grep", "-n", "-i", needle, "--", ".", ":!.github/workflows/ci.yml"],
                             cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.stdout, "", out.stdout)
        for f in ("Dockerfile", "compose.yaml"):
            self.assertNotRegex((ROOT / f).read_text(), re.compile(needle, re.I))


if __name__ == "__main__":
    unittest.main()
