import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
CODE_PATH = re.compile(r"`((?:scripts|bench|agents|docs|tests|seeds|templates|schemas)/[^`\s]+)`")
GENERATED = {"agents/tenant-readonly.local.yaml"}


def anchors(md: str) -> set[str]:
    out = set()
    for line in md.splitlines():
        if line.startswith("#"):
            title = line.lstrip("#").strip().lower()
            out.add(re.sub(r"[^a-z0-9 -]", "", title).replace(" ", "-"))
    return out


class DocsLinks(unittest.TestCase):
    def test_relative_links_exist(self):
        for doc in DOCS:
            for target in LINK.findall(doc.read_text(encoding="utf-8")):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                path, _, frag = target.partition("#")
                dest = (doc.parent / path).resolve() if path else doc
                self.assertTrue(dest.exists(), f"{doc.name}: missing {target}")
                if frag and dest.suffix == ".md":
                    self.assertIn(frag, anchors(dest.read_text(encoding="utf-8")), f"{doc.name}: bad anchor {target}")

    def test_code_paths_exist(self):
        for doc in DOCS:
            for p in CODE_PATH.findall(doc.read_text(encoding="utf-8")):
                if any(ch in p for ch in "*<") or p in GENERATED:
                    continue
                self.assertTrue((ROOT / p.rstrip("/")).exists(), f"{doc.name}: missing path {p}")

    def test_mermaid_fences_close(self):
        for doc in DOCS:
            blocks = doc.read_text(encoding="utf-8").split("```mermaid")[1:]
            for b in blocks:
                self.assertIn("```", b, f"{doc.name}: unclosed mermaid fence")


if __name__ == "__main__":
    unittest.main()
