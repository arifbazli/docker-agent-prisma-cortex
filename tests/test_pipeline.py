"""Unit tests for scripts/pipeline.py and scripts/gen-configs.py (stdlib only).

Run: python3 -m unittest discover -s tests -v
"""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


P = load("pipeline", "pipeline.py")
G = load("gen_configs", "gen-configs.py")

PAGE_URL = "https://cortex-docs.paloaltonetworks.com/x/about-the-upgrade-helper.md"
PAGE = """# About the Upgrade Helper

The Upgrade Helper provides a **gradual and flexible** upgrade experience.

| Prisma Cloud | Cortex Cloud | Notes |
| --- | --- | --- |
| Enforcement rules | [Application Security policies](https://x/y) | converted |

* Any custom exception rules will not be carried over and will need to be reconfigured.
Cortex Cloud\u2019s data lake \u2014 one place for everything.
"""


def fact_line(quote, url=PAGE_URL, fact="A fact."):
    return f'FACT: {fact} | PRODUCT: Cortex Cloud | MODULE: Platform | QUOTE: "{quote}" | URL: {url} | MONTH: unknown'


class Normalisation(unittest.TestCase):
    def test_ascii(self):
        self.assertEqual(P.to_ascii("Cortex\u2019s \u201cnew\u201d \u2014 x \u2192 y"), "Cortex's \"new\" - x -> y")

    def test_markdown_bold_and_links(self):
        self.assertEqual(P.quote_on_page("provides a gradual and flexible upgrade", PAGE), "exact")

    def test_table_row_cells(self):
        self.assertEqual(P.quote_on_page("Enforcement rules Application Security policies converted", PAGE), "exact")

    def test_curly_quotes_and_dashes(self):
        self.assertEqual(P.quote_on_page("Cortex Cloud's data lake - one place", PAGE), "exact")

    def test_loose_punctuation(self):
        self.assertEqual(P.quote_on_page("will not be carried over, and will need", PAGE), "loose")

    def test_ellipsis_pieces_in_order(self):
        self.assertEqual(P.quote_on_page("Any custom exception rules ... need to be reconfigured", PAGE), "exact")
        self.assertIsNone(P.quote_on_page("need to be reconfigured ... Any custom exception rules", PAGE))

    def test_not_on_page(self):
        self.assertIsNone(P.quote_on_page("Cortex Cloud is free forever", PAGE))


class Facts(unittest.TestCase):
    def test_parse_variants(self):
        text = "\n".join([
            "Here are the facts:",
            "- " + fact_line("gradual and flexible"),
            "2. " + fact_line("x", url="<https://pan.dev/a/>"),
            fact_line("gradual and flexible"),  # duplicate
            "FACT: broken line without fields",
        ])
        facts = P.parse_facts(text)
        self.assertEqual(len(facts), 2)
        self.assertEqual(facts[0].quote, "gradual and flexible")
        self.assertEqual(facts[1].url, "https://pan.dev/a/")

    def test_quote_check_verdicts(self):
        pages = [
            P.Page(PAGE_URL, True, 200, PAGE),
            P.Page("https://cortex-docs.paloaltonetworks.com/x/missing.md", False, None, "", "unexpected status 404"),
        ]
        facts = P.parse_facts("\n".join([
            fact_line("gradual and flexible upgrade experience", url=PAGE_URL.removesuffix(".md")),
            fact_line("Cortex Cloud is free forever"),
            fact_line("anything", url="https://cortex-docs.paloaltonetworks.com/readme.md?ask=x&goal=y"),
            fact_line("anything", url="https://cortex-docs.paloaltonetworks.com/x/never-fetched.md"),
            fact_line("anything", url="https://cortex-docs.paloaltonetworks.com/x/missing.md"),
        ]))
        P.check_quotes(facts, pages)
        self.assertEqual([f.verdict for f in facts],
                         ["", "UNSUPPORTED", "UNSUPPORTED", "UNSUPPORTED", "UNVERIFIABLE"])
        self.assertEqual(facts[0].match, "exact")
        self.assertTrue(facts[2].dropped)
        self.assertEqual(len(P.verdict_lines(facts)), 4)

    def test_citation_corrected_when_quote_is_on_a_real_page(self):
        ask = "https://cortex-docs.paloaltonetworks.com/readme.md?ask=q"
        other = "https://cortex-docs.paloaltonetworks.com/x/other.md"
        pages = [P.Page(PAGE_URL, True, 200, PAGE), P.Page(ask, True, 200, PAGE),
                 P.Page(other, True, 200, "# Other\nNothing here.")]
        facts = P.parse_facts("\n".join([
            fact_line("gradual and flexible upgrade experience", url=ask),
            fact_line("gradual and flexible upgrade experience", url=other),
        ]))
        P.check_quotes(facts, pages)
        for f in facts:
            self.assertEqual(f.verdict, "")  # goes to the judge
            self.assertEqual(f.url, PAGE_URL)
            self.assertIn(PAGE_URL, f.line)
            self.assertFalse(f.dropped)
        self.assertEqual(facts[0].cited_url, ask)
        P.apply_judge(facts, "[1] | SUPPORTED | NOTE: none\n[2] | SUPPORTED | NOTE: ok")
        self.assertIn("generated answer", facts[0].note)
        self.assertIn("ok", facts[1].note)

    def test_judge_parsing_and_default(self):
        facts = P.parse_facts("\n".join(fact_line(q) for q in ("a", "b", "c")))
        n = P.apply_judge(facts, "[1] | SUPPORTED | NOTE: none\n2 | partly supported | NOTE: adds a claim\njunk")
        self.assertEqual(n, 2)
        self.assertEqual([f.verdict for f in facts], ["SUPPORTED", "PARTLY SUPPORTED", "PARTLY SUPPORTED"])
        self.assertIn("no verdict", facts[2].note)


class Events(unittest.TestCase):
    def test_parse_ndjson(self):
        multi = json.dumps([
            {"url": "https://a/1", "statusCode": 200, "body": "one"},
            {"url": "https://a/2", "statusCode": 0, "error": "request failed"},
        ])
        events = [
            {"type": "tool_call", "tool_call": {"id": "c1", "function": {"name": "fetch", "arguments": json.dumps({"urls": [PAGE_URL]})}}},
            {"type": "tool_call_response", "tool_call_id": "c1",
             "result": {"output": f"Successfully fetched {PAGE_URL} (Status: 200, Length: 9 bytes):\n\n{PAGE}"}},
            {"type": "tool_call", "tool_call": {"id": "c2", "function": {"name": "fetch", "arguments": json.dumps({"urls": ["https://a/1", "https://a/2"]})}}},
            {"type": "tool_call_response", "tool_call_id": "c2", "result": {"output": multi}},
            {"type": "tool_call", "tool_call": {"id": "c3", "function": {"name": "fetch", "arguments": json.dumps({"urls": ["https://b"]})}}},
            {"type": "tool_call_response", "tool_call_id": "c3", "result": {"output": "Error fetching https://b: unexpected status 404"}},
            {"type": "agent_choice", "agent_name": "researcher", "message_id": "m1", "content": "thinking"},
            {"type": "agent_choice", "agent_name": "researcher", "message_id": "m2", "content": "FACT: "},
            {"type": "agent_choice", "agent_name": "researcher", "message_id": "m2", "content": "done"},
            {"type": "agent_choice", "agent_name": "other", "message_id": "m3", "content": "ignored"},
            {"type": "error", "error": "boom"},
        ]
        final, pages, errors, calls = P.parse_events([json.dumps(e) for e in events] + ["not json"], "researcher")
        self.assertEqual(final, "FACT: done")
        self.assertEqual(calls, 3)
        self.assertEqual([(p.url, p.ok) for p in pages],
                         [(PAGE_URL, True), ("https://a/1", True), ("https://a/2", False), ("https://b", False)])
        self.assertTrue(pages[0].body.startswith("# About the Upgrade Helper"))
        self.assertEqual(errors, ["boom"])


class Output(unittest.TestCase):
    def test_extract_briefing(self):
        self.assertEqual(P.extract_briefing("chatter\n# PANW Briefing: X\n\nbody"), "# PANW Briefing: X\n\nbody")
        self.assertEqual(P.extract_briefing("ok so OUT OF SCOPE: only PANW.\nmore"), "OUT OF SCOPE: only PANW.")

    def test_clean_output_fence(self):
        self.assertEqual(P.clean_output("```markdown\n# A Briefing: b\n```"), "# A Briefing: b")


class Generator(unittest.TestCase):
    def test_render_block_indent(self):
        out = G.render("a:\n  {{X}}\nb: {{Y}}", {"X": "one\n\ntwo", "Y": "y"}, "t")
        self.assertEqual(out, "a:\n  one\n\n  two\nb: y")

    def test_inline_multiline_rejected(self):
        with self.assertRaises(SystemExit):
            G.render("b: {{X}} tail", {"X": "1\n2"}, "t")

    def test_generated_configs_up_to_date(self):
        template = G.TEMPLATE.read_text()
        seeds = G.load_seeds()
        for scope in sorted(G.SCOPES.glob("*.txt")):
            target = G.OUT / f"{scope.stem}.yaml"
            self.assertEqual(target.read_text(), G.build(scope, template, seeds),
                             f"{target} is stale: run python3 scripts/gen-configs.py")


if __name__ == "__main__":
    unittest.main()
