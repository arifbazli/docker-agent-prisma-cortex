import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ArchitectureDoc(unittest.TestCase):
    def test_mermaid_fences(self):
        text = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
        fences = [ln for ln in text.splitlines() if ln.strip().startswith("```mermaid")]
        self.assertGreaterEqual(len(fences), 2, "expected at least two mermaid diagrams")
        # each fenced mermaid block must close
        blocks = text.split("```mermaid")
        self.assertEqual(len(blocks) - 1, len(fences))
        for b in blocks[1:]:
            self.assertIn("```", b, "unclosed mermaid fence")

    def test_every_named_file_exists(self):
        for rel in ("scripts/guardrail.py", "scripts/check-policy.py", "bench/guardrail/check-golden.sh",
                    "bench/guardrail/run-live.sh", "bench/guardrail/record.py", "schemas/policy.schema.json",
                    "seeds/guardrail-catalog.json"):
            self.assertTrue((ROOT / rel).exists(), rel)


if __name__ == "__main__":
    unittest.main()
