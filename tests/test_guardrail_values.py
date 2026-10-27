"""Value-type checks (scripts/guardrail_values.py)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import guardrail_values as GV  # noqa: E402

NUM = {"type": "number", "min": 0, "max": 0.99, "quote_terms": [["grounding"], ["threshold"]]}


class Values(unittest.TestCase):
    def test_boolean(self):
        self.assertEqual(GV.check_value({"type": "boolean"}, True), (True, None))
        for bad in ("true", "BLOCK", 1, None):
            self.assertIsNotNone(GV.check_value({"type": "boolean"}, bad)[1], bad)

    def test_enum_is_case_insensitive_and_canonical(self):
        spec = {"type": "enum", "enum": ["NONE", "LOW", "MEDIUM", "HIGH"]}
        self.assertEqual(GV.check_value(spec, "high"), ("HIGH", None))
        self.assertIn("expected one of", GV.check_value(spec, "filter strength")[1])

    def test_number_range_and_quote(self):
        self.assertEqual(GV.check_value(NUM, 0.7), (0.7, None))
        self.assertIn("outside", GV.check_value(NUM, 1.5)[1])
        self.assertIn("expected a number", GV.check_value(NUM, True)[1])
        q = "set the grounding threshold to 0.7 or higher"
        self.assertEqual(GV.check_value(NUM, 0.7, q), (0.7, None))
        self.assertIn("does not appear", GV.check_value(NUM, 0.8, q)[1])
        self.assertIn("does not mention threshold", GV.check_value(NUM, 0.7, "grounding score 0.7")[1])
        self.assertTrue(GV.number_in_quote(10000, "a maximum of 10,000 characters"))
        self.assertTrue(GV.number_in_quote(0.7, "between .7 and 1"))
        self.assertFalse(GV.number_in_quote(10, "100 requests"))
        self.assertFalse(GV.number_in_quote(1, "0.1 seconds"))

    def test_lists_and_strings(self):
        spec = {"type": "list", "items_enum": ["HATE", "INSULTS"]}
        self.assertEqual(GV.check_value(spec, ["hate"]), (["HATE"], None))
        self.assertIn("not in", GV.check_value(spec, ["hate", "spam"])[1])
        self.assertIn("list of names", GV.check_value({"type": "list"}, "hate")[1])
        self.assertIn("empty list", GV.check_value({"type": "list"}, [])[1])  # e.g. a documented default of []
        self.assertEqual(GV.check_value({"type": "string"}, " ok "), ("ok", None))
        self.assertIsNotNone(GV.check_value({"type": "string"}, "")[1])

    def test_type_label(self):
        self.assertEqual(GV.type_label({"type": "enum", "enum": ["A", "B"]}), "enum[A|B]")
        self.assertEqual(GV.type_label(NUM), "number 0..0.99")


if __name__ == "__main__":
    unittest.main()
