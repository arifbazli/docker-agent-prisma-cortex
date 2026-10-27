"""Step 1: guardrail catalog, schemas and the stdlib JSON Schema validator.

Run: python3 -m unittest discover -s tests -v
"""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import jsonschema_lite as V  # noqa: E402

CATALOG = json.loads((ROOT / "seeds" / "guardrail-catalog.json").read_text())
SCHEMAS = {p.stem.replace(".schema", ""): json.loads(p.read_text()) for p in (ROOT / "schemas").glob("*.schema.json")}

# The requirement, spelled out once: 7 categories x 10 controls, in order.
EXPECTED = {
    "input": ["Input validation", "File scanning", "Schema checks", "Content sanitization", "MIME validation",
              "Malware screening", "Size limits", "Rate limits", "Language checks", "Injection screening"],
    "prompt": ["System prompt isolation", "Prompt firewall", "Role separation", "Content boundaries", "Prompt templates",
               "Instruction locking", "Jailbreak detection", "Prompt rewriting", "Policy injection checks",
               "Hidden prompt protection"],
    "retrieval": ["Source filtering", "Freshness checks", "Trust scoring", "Chunk validation", "Metadata filtering",
                  "Duplicate removal", "Re-ranking", "Grounding rules", "Document allowlists", "Citation enforcement"],
    "tool": ["Tool allowlists", "Action approval", "Permission checks", "API scope control", "Transaction limits",
             "Tool sandboxing", "Execution logging", "Timeout controls", "Retry limits", "Human confirmation"],
    "output": ["Content moderation", "Toxicity checks", "PII masking", "Policy filters", "Hallucination checks",
               "Citation checks", "Safety disclaimers", "Restricted topics blocking", "Format enforcement",
               "Response validation"],
    "runtime": ["Session monitoring", "Anomaly detection", "Latency tracking", "Token limits", "Cost controls",
                "Loop detection", "Failure handling", "Fallback routing", "Concurrency control", "Abuse monitoring"],
    "memory": ["Memory retention", "Memory expiry", "Recall filtering", "Sensitive data blocking", "User separation",
               "Session boundaries", "Write controls", "Edit controls", "Deletion rules", "Audit history"],
}

SAMPLE_PROFILE = {
    "name": "support-chatbot", "uses_rag": True, "has_tools": False, "tool_list": [], "has_memory": False,
    "handles_pii": True, "user_facing": True, "autonomy_level": "none", "cloud": "aws",
    "data_classification": "internal", "regulatory_context": ["gdpr"],
}


class Catalog(unittest.TestCase):
    def test_validates_against_schema(self):
        self.assertEqual(V.validate(CATALOG, SCHEMAS["catalog"]), [])

    def test_seven_by_ten_unique_ids(self):
        controls = CATALOG["controls"]
        ids = [c["id"] for c in controls]
        self.assertEqual(len(controls), 70)
        self.assertEqual(len(set(ids)), 70, "duplicate control ids")
        self.assertEqual([c["id"] for c in CATALOG["categories"]], list(EXPECTED))
        for cat in CATALOG["categories"]:
            mine = [c for c in controls if c["category"] == cat["id"]]
            self.assertEqual([c["name"] for c in mine], EXPECTED[cat["id"]], cat["id"])
            self.assertEqual([c["id"] for c in mine], [f"{cat['prefix']}-{i:02d}" for i in range(1, 11)])

    def test_every_control_validates_on_its_own(self):
        item_schema = SCHEMAS["catalog"]["properties"]["controls"]["items"]
        for c in CATALOG["controls"]:
            self.assertEqual(V.validate(c, item_schema), [], c["id"])

    def test_threat_ids_resolve(self):
        index = {t["id"] for t in CATALOG["threats"]}
        used = {t for c in CATALOG["controls"] for t in c["threats"]}
        self.assertEqual(used - index, set(), "threat ids used but not in the index")
        self.assertEqual(index - used, set(), "threat ids in the index but unused")
        for c in CATALOG["controls"]:
            self.assertTrue(any(t.startswith("LLM") for t in c["threats"]), f"{c['id']} has no OWASP id")

    def test_generic_target_everywhere(self):
        for c in CATALOG["controls"]:
            self.assertIn("generic", c["supported_targets"], c["id"])

    def test_applies_when_values_match_profile_schema(self):
        props = SCHEMAS["app-profile"]["properties"]
        for c in CATALOG["controls"]:
            for cond in c["applies_when"]["conditions"]:
                field, op, value = cond["field"], cond["op"], cond.get("value")
                spec = props[field]
                where = f"{c['id']} {field} {op}"
                if op == "nonempty":
                    self.assertIsNone(value, where)
                    self.assertEqual(spec["type"], "array", where)
                    continue
                self.assertIsNotNone(value, where)
                if op in ("eq", "ne"):
                    self.assertEqual(V.validate(value, spec), [], where)
                elif op == "in":
                    self.assertIsInstance(value, list, where)
                    for v in value:
                        self.assertEqual(V.validate(v, spec), [], where)
                elif op == "contains_any":
                    self.assertEqual(spec["type"], "array", where)
                    self.assertEqual(V.validate(value, spec), [], where)


class Schemas(unittest.TestCase):
    def test_all_schemas_use_supported_keywords_only(self):
        self.assertEqual(set(SCHEMAS), {"catalog", "app-profile", "policy"})
        for name, schema in SCHEMAS.items():
            V.check_schema(schema)  # raises on anything unsupported

    def test_sample_profile(self):
        self.assertEqual(V.validate(SAMPLE_PROFILE, SCHEMAS["app-profile"]), [])
        bad = dict(SAMPLE_PROFILE, autonomy_level="yolo", customer_name="ACME")
        errors = V.validate(bad, SCHEMAS["app-profile"])
        self.assertTrue(any("autonomy_level" in e for e in errors))
        self.assertTrue(any("customer_name" in e for e in errors), "unknown fields must be rejected")

    def test_policy_schema(self):
        policy = {
            "schema_version": "1.0", "generator": "guardrail-policy-generator", "advisory": True,
            "catalog_version": "1.0", "profile": SAMPLE_PROFILE,
            "controls": [{
                "control_id": "INPUT-10", "category": "input", "name": "Injection screening", "severity": "high",
                "enforcement_point": "pre_model", "targets": ["generic", "bedrock"], "status": "grounded",
                "parameters": [{"name": "prompt_attack_strength", "value": "HIGH", "rationale": "Documented filter strength.",
                                "source_url": "https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html",
                                "source_quote": "prompt attack"}],
            }],
            "waivers": [{"category": "memory", "reason": "The application keeps no memory."}],
            "excluded": [{"control_id": "TOOL-01", "reason": "has_tools is false"}],
        }
        self.assertEqual(V.validate(policy, SCHEMAS["policy"]), [])
        policy["advisory"] = False
        policy["controls"][0]["parameters"][0]["source_url"] = "https://x/readme.md?ask=q"
        errors = V.validate(policy, SCHEMAS["policy"])
        self.assertTrue(any("advisory" in e for e in errors))
        self.assertTrue(any("source_url" in e for e in errors))


class Validator(unittest.TestCase):
    def test_rejects_unsupported_keywords(self):
        for kw, val in [("oneOf", []), ("$ref", "#/x"), ("maxItems", 3), ("const", 1), ("format", "uri"),
                        ("patternProperties", {}), ("minimum", 0)]:
            with self.subTest(kw=kw):
                with self.assertRaises(V.UnsupportedKeyword):
                    V.validate({}, {"type": "object", kw: val})
        nested = {"type": "object", "properties": {"a": {"type": "array", "items": {"allOf": []}}}}
        with self.assertRaises(V.UnsupportedKeyword):
            V.validate({"a": []}, nested)
        with self.assertRaises(V.UnsupportedKeyword):
            V.validate(1, {"type": "float"})

    def test_keywords(self):
        s = {"type": "object", "required": ["a"], "additionalProperties": False,
             "properties": {"a": {"type": ["string", "null"], "minLength": 2, "pattern": "^x"},
                            "b": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"enum": [1, 2]}},
                            "c": {"type": "integer"}}}
        self.assertEqual(V.validate({"a": "xy", "b": [1, 2], "c": 3}, s), [])
        self.assertEqual(V.validate({"a": None}, s), [])
        errs = V.validate({"b": [1, 1, 3], "c": True, "d": 0}, s)
        joined = " | ".join(errs)
        for needle in ("missing required property 'a'", "duplicate", "not in", "expected integer", "unexpected property 'd'"):
            self.assertIn(needle, joined)
        self.assertTrue(V.validate({"a": "yy"}, s))  # pattern
        self.assertTrue(V.validate({"a": "x"}, s))   # minLength
        self.assertTrue(V.validate({"a": "xy", "b": []}, s))  # minItems
        with self.assertRaises(V.ValidationError):
            V.check({}, s)


if __name__ == "__main__":
    unittest.main()
