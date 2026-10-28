import hashlib
import subprocess
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SVG_DIR = ROOT / "docs" / "images"
SVG_FILES = [
    "guardrail-pipeline.svg",
    "repo-overview.svg",
    "docs-briefing-pipeline.svg",
]


class DiagramFiles(unittest.TestCase):
    def read(self, name):
        path = SVG_DIR / name
        self.assertTrue(path.exists(), f"missing {path}")
        return path.read_bytes()

    def test_each_svg_parses_and_has_viewbox(self):
        for name in SVG_FILES:
            data = self.read(name).decode("ascii")
            self.assertTrue(data.isascii(), f"{name}: non-ASCII")
            root = ET.fromstring(data)
            self.assertEqual(root.tag.split("}")[-1], "svg")
            vb = root.get("viewBox")
            self.assertTrue(vb, f"{name}: no viewBox")
            parts = vb.split()
            self.assertEqual(len(parts), 4, f"{name}: bad viewBox")
            self.assertAlmostEqual(float(parts[2]), 1000.0, delta=1.0, msg=f"{name}: width not ~1000")
            # white background rect
            rects = [e for e in root.iter() if e.tag.split("}")[-1] == "rect"]
            self.assertTrue(any(e.get("fill") in ("#ffffff", "white", "#FFFFFF")
                                and e.get("width") and e.get("height")
                                for e in rects), f"{name}: no white background rect")
            text = data.lower()
            # The standard SVG namespace declaration is allowed; any other
            # http(s) reference is not.
            check = text.replace('xmlns="http://www.w3.org/2000/svg"', "")
            self.assertNotIn("<script", check)
            self.assertNotIn("<foreignobject", check)
            self.assertNotIn("http://", check)
            self.assertNotIn("https://", check)

    def test_guardrail_labels(self):
        data = self.read("guardrail-pipeline.svg").decode("ascii")
        for label in ("select-controls.py", "judge", "check-policy.py", "policy.json",
                      "SPECIALIST_MODEL", "JUDGE_MODEL", "REVIEWER_MODEL",
                      "exceptions.md", "tests.jsonl", "evidence.json", "render-bedrock"):
            self.assertIn(label, data, f"guardrail svg missing {label}")

    def test_briefing_labels(self):
        data = self.read("docs-briefing-pipeline.svg").decode("ascii")
        for label in ("question", "researcher", "quote check", "judge", "writer",
                      "check briefing", "RESEARCH_MODEL", "JUDGE_MODEL", "WRITER_MODEL"):
            self.assertIn(label, data, f"briefing svg missing {label}")

    def test_overview_labels(self):
        data = self.read("repo-overview.svg").decode("ascii")
        for label in ("templates", "gen configs", "agents yaml", "docs briefing",
                      "guardrail", "catalog"):
            self.assertIn(label, data, f"overview svg missing {label}")

    def test_regeneration_is_deterministic(self):
        before = {name: hashlib.sha256(self.read(name)).digest() for name in SVG_FILES}
        proc = subprocess.run(
            ["python3", "scripts/make-diagrams.py"],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for name in SVG_FILES:
            after = hashlib.sha256((SVG_DIR / name).read_bytes()).digest()
            self.assertEqual(before[name], after, f"{name} not reproducible")


if __name__ == "__main__":
    unittest.main()
