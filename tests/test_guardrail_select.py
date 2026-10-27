"""Step 2: deterministic control selection (no LLM)."""
import contextlib
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "bench" / "guardrail"

spec = importlib.util.spec_from_file_location("select_controls", ROOT / "scripts" / "select-controls.py")
S = importlib.util.module_from_spec(spec)
sys.modules["select_controls"] = S
spec.loader.exec_module(S)

CATALOG = S.load_catalog()
ALL_IDS = [c["id"] for c in CATALOG["controls"]]


def profile(name):
    return json.loads((GOLDEN / f"{name}.profile.json").read_text())


def ids(result, category):
    return set(result["by_category"][category])


def cat_ids(prefix):
    return {f"{prefix}-{i:02d}" for i in range(1, 11)}


class Golden(unittest.TestCase):
    """The three golden profiles match their committed expected sets, and the
    sets make sense for what each profile describes."""

    def test_expected_files(self):
        for name in ("rag-chatbot", "tool-agent", "memory-assistant"):
            with self.subTest(name=name):
                p = profile(name)
                self.assertEqual(S.validate_profile(p), [])
                expected = json.loads((GOLDEN / f"{name}.expected.json").read_text())
                self.assertEqual(S.select(p, CATALOG)["selected"], expected["expected_selected"])

    def test_rag_chatbot(self):
        r = S.select(profile("rag-chatbot"), CATALOG)
        self.assertEqual(ids(r, "retrieval"), cat_ids("RETRIEVAL"))
        self.assertEqual(ids(r, "tool"), set())
        self.assertEqual(ids(r, "memory"), set())
        self.assertIn("OUTPUT-03", r["selected"])   # PII masking: handles_pii
        self.assertIn("OUTPUT-06", r["selected"])   # citation checks: uses_rag
        self.assertNotIn("RUNTIME-06", r["selected"])  # loop detection needs tools

    def test_tool_agent(self):
        r = S.select(profile("tool-agent"), CATALOG)
        self.assertEqual(ids(r, "tool"), cat_ids("TOOL"))  # incl. transaction limits (payments), sandboxing (code_exec)
        self.assertEqual(ids(r, "retrieval"), set())
        self.assertEqual(ids(r, "memory"), set())
        self.assertNotIn("OUTPUT-01", r["selected"])  # not user facing
        self.assertNotIn("OUTPUT-03", r["selected"])  # no PII, SOX is not a privacy regime
        self.assertIn("RUNTIME-06", r["selected"])    # loop detection

    def test_memory_assistant(self):
        r = S.select(profile("memory-assistant"), CATALOG)
        self.assertEqual(ids(r, "memory"), cat_ids("MEMORY"))
        self.assertEqual(ids(r, "tool"), set())
        self.assertEqual(ids(r, "retrieval"), set())
        self.assertIn("PROMPT-09", r["selected"])  # policy injection checks: memory


class Behaviour(unittest.TestCase):
    def test_partition_and_reasons(self):
        for name in ("rag-chatbot", "tool-agent", "memory-assistant"):
            r = S.select(profile(name), CATALOG)
            excluded = [e["control_id"] for e in r["excluded"]]
            self.assertEqual(sorted(r["selected"] + excluded), sorted(ALL_IDS))
            self.assertFalse(set(r["selected"]) & set(excluded))
            for e in r["excluded"]:
                self.assertTrue(e["reason"].startswith("not applicable: requires"), e)

    def test_flipping_a_field_changes_selection(self):
        p = profile("rag-chatbot")
        self.assertNotIn("TOOL-01", S.select(p, CATALOG)["selected"])
        p.update(has_tools=True, tool_list=["payments"], autonomy_level="autonomous")
        sel = S.select(p, CATALOG)["selected"]
        for cid in ("TOOL-01", "TOOL-02", "TOOL-05", "TOOL-10"):
            self.assertIn(cid, sel)
        self.assertNotIn("TOOL-06", sel)  # no code-executing tool

    def test_ops(self):
        prof = {"a": True, "l": ["x", "y"], "s": "act_with_approval"}
        self.assertTrue(S.holds({"field": "a", "op": "eq", "value": True}, prof))
        self.assertTrue(S.holds({"field": "s", "op": "ne", "value": "none"}, prof))
        self.assertTrue(S.holds({"field": "s", "op": "in", "value": ["act_with_approval"]}, prof))
        self.assertTrue(S.holds({"field": "l", "op": "contains_any", "value": ["y", "z"]}, prof))
        self.assertFalse(S.holds({"field": "l", "op": "contains_any", "value": ["z"]}, prof))
        self.assertTrue(S.holds({"field": "l", "op": "nonempty"}, prof))
        self.assertEqual(S.applies({"match": "all", "conditions": []}, prof), (True, ""))

    def test_cli(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = S.main(["--ids", str(GOLDEN / "tool-agent.profile.json")])
        self.assertEqual(rc, 0)
        self.assertIn("TOOL-05", out.getvalue().split())
        bad = ROOT / "tests" / "_bad_profile.json"
        bad.write_text(json.dumps({"uses_rag": "yes"}))
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(S.main([str(bad)]), 64)
                self.assertEqual(S.main([str(ROOT / "nope.json")]), 64)
                self.assertEqual(S.main([]), 64)
        finally:
            bad.unlink()


if __name__ == "__main__":
    unittest.main()
