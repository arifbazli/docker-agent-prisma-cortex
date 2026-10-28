import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
CODE_PATH = re.compile(r"`((?:scripts|bench|agents|docs|tests|seeds|templates|schemas)/[^`\s]+)`")
GENERATED = {"agents/tenant-readonly.local.yaml"}

FORBIDDEN_MERMAID = ("-- >", ":::", "<br",)


def anchors(md: str) -> set[str]:
    out = set()
    for line in md.splitlines():
        if line.startswith("#"):
            title = line.lstrip("#").strip().lower()
            out.add(re.sub(r"[^a-z0-9 -]", "", title).replace(" ", "-"))
    return out


def mermaid_blocks(md: str):
    out = []
    parts = md.split("```mermaid")
    for part in parts[1:]:
        code = part.split("```", 1)[0]
        out.append(code)
    return out


def class_names(code: str):
    names = []
    for line in code.splitlines():
        s = line.strip()
        if s.startswith("classDef "):
            names.append(s[len("classDef "):].split()[0])
        elif s.startswith("class "):
            left = s[len("class "):]
            if " " in left:
                left = left.split(" ", 1)[0]
            names.extend(x.strip() for x in left.split(",") if x.strip())
    return names


def mermaid_violations(md: str) -> list[str]:
    errors = []
    for code in mermaid_blocks(md):
        if "-- >" in code or re.search(r"--\s+>", code):
            errors.append("-- > (spaced arrow)")
        if ": : :" in code or re.search(r":\s+:\s+:", code):
            errors.append("spaced colons")
        if "<br" in code:
            errors.append("<br")
        if ":::" in code:
            errors.append(":::")
        if any(ord(ch) > 127 for ch in code):
            errors.append("non-ASCII")
        for name in class_names(code):
            if not name.isalpha():
                errors.append(f"class name {name!r} is not letters only")
        # labels must not contain asterisks or slashes (conservative syntax)
        for label in re.findall(r"\[([^\]]*)\]", code):
            if "*" in label or "/" in label:
                errors.append(f"label {label!r} has * or /")
    return errors


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

    def test_mermaid_syntax_is_conservative(self):
        for doc in DOCS:
            violations = mermaid_violations(doc.read_text(encoding="utf-8"))
            self.assertEqual(violations, [], f"{doc.name}: {violations}")

    def test_mermaid_rules_trigger_on_bad_samples(self):
        bad_samples = {
            "spaced arrow": "```mermaid\nflowchart LR\n    A --> B\n    X -- > Y\n    classDef data fill:#9ca3af\n```",
            "spaced colons": "```mermaid\nflowchart LR\n    A --> B\n    classDef x fill : : : red\n```",
            "br": "```mermaid\nflowchart LR\n    A[a<br/>b] --> B\n```",
            "shorthand": "```mermaid\nflowchart LR\n    A:::x --> B\n```",
            "non-ascii": "```mermaid\nflowchart LR\n    A[café] --> B\n```",
            "digit class name": "```mermaid\nflowchart LR\n    A --> B\n    classDef 1x fill:#fff\n```",
            "slash in label": "```mermaid\nflowchart LR\n    A[a/b] --> B\n```",
            "asterisk in label": "```mermaid\nflowchart LR\n    A[a*b] --> B\n```",
        }
        for name, sample in bad_samples.items():
            violations = mermaid_violations(sample)
            self.assertTrue(violations, f"rule did not trigger for {name}: {sample}")


if __name__ == "__main__":
    unittest.main()
