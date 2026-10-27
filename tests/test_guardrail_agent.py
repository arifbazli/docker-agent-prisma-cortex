"""Step 3: guardrail agent generation, model guard, URL rules and pipeline parsing (no model calls)."""
import contextlib
import importlib.util
import io
import json
import os
import re
import sys
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


P = load("pipeline", "pipeline.py")
G = load("gen_configs", "gen-configs.py")
GR = load("guardrail", "guardrail.py")

CFG = (ROOT / "agents" / "guardrail-policy-generator.yaml").read_text()
CATS = ["input", "prompt", "retrieval", "tool", "output", "runtime", "memory"]


class Generation(unittest.TestCase):
    def test_up_to_date(self):
        self.assertEqual(CFG, G.build_guardrail(G.load_seeds()))

    def test_agent_graph(self):
        agents = re.findall(r"(?m)^  ([a-z_]+):\n", CFG.split("\nagents:\n", 1)[1])
        self.assertEqual(agents, ["root"] + [f"{c}_specialist" for c in CATS] + ["judge", "assembler", "reviewer"])
        self.assertIn("sub_agents: [" + ", ".join(f"{c}_specialist" for c in CATS) + ", assembler, reviewer]", CFG)

    def test_models_from_env_and_cloud_defaults(self):
        for var in ("ROUTER_MODEL", "SPECIALIST_MODEL", "JUDGE_MODEL", "REVIEWER_MODEL"):
            self.assertIn(f'model: "${{env.{var}}}"', CFG)
        self.assertEqual(CFG.count("    model: specialist\n"), 7)
        self.assertNotIn("{{", CFG)

    def test_tools_fetch_only_with_allowlist(self):
        for deny in ('- "write_*"', '- "exec_*"', '- "shell"', '- "shell_*"'):
            self.assertIn(deny, CFG)
        self.assertEqual(CFG.count("- type: fetch"), 7)  # specialists only
        self.assertNotIn("type: shell", CFG)
        self.assertNotIn("type: filesystem", CFG)
        domains = set(re.findall(r"(?m)^          - ([a-z0-9.-]+)$", CFG))
        self.assertEqual(domains, {"docs.aws.amazon.com", "docs.nvidia.com", "genai.owasp.org",
                                   "atlas.mitre.org", "docs.paloaltonetworks.com", "pan.dev"})

    def test_sources_come_from_seed_files(self):
        for f in ("guardrail-bedrock", "guardrail-nemo", "guardrail-owasp", "guardrail-airs"):
            for url in G.read_seeds(ROOT / "seeds" / f"{f}.txt"):
                self.assertIn(url, CFG, f)
        self.assertNotIn("guardrails-content-filters", CFG.split("tool_specialist:")[1].split("output_specialist:")[0])

    def test_every_scope_file_is_used_and_hubs_unaffected(self):
        names = sorted(t.name for t, _ in G.targets(G.load_seeds()))
        self.assertNotIn("guardrail-input.yaml", names)
        for cat in CATS:
            self.assertTrue((ROOT / "templates" / "scopes" / f"guardrail-{cat}.txt").exists())
            self.assertIn(f"You are the {cat.capitalize()} guardrail specialist.", CFG)


class ModelGuard(unittest.TestCase):
    def test_names(self):
        for ok in ("nemotron-3-super:cloud", "gpt-oss:120b-cloud", "nemotron-3-nano:30b-cloud"):
            self.assertTrue(P.is_cloud_model(ok), ok)
        for bad in ("qwen3:32b", "llama3", "gpt-oss:120b", "", "cloud", "my-cloudy:1b"):
            self.assertFalse(P.is_cloud_model(bad), bad)

    def test_enforce(self):
        with mock.patch.dict(os.environ, {"ALLOW_LOCAL_MODELS": "0"}):
            with contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(P.enforce_cloud_models({"JUDGE_MODEL": "qwen3:32b"}), 64)
            self.assertIn("local models are disabled; use a cloud model", err.getvalue())
            self.assertEqual(P.enforce_cloud_models({"JUDGE_MODEL": "gpt-oss:120b-cloud"}), 0)
        with mock.patch.dict(os.environ, {"ALLOW_LOCAL_MODELS": "1"}):
            self.assertEqual(P.enforce_cloud_models({"JUDGE_MODEL": "qwen3:32b"}), 0)

    def test_defaults_and_env_example_are_cloud(self):
        self.assertEqual(P.local_models({k: v for k, v in P.DEFAULTS.items() if k.endswith("_MODEL")}), [])
        self.assertEqual(P.local_models({k: v for k, v in GR.DEFAULTS.items() if k.endswith("_MODEL")}), [])
        env = dict(re.findall(r"(?m)^([A-Z_]+_MODEL)=(.*)$", (ROOT / ".env.example").read_text()))
        self.assertEqual(set(env), {"RESEARCH_MODEL", "JUDGE_MODEL", "WRITER_MODEL", "ROUTER_MODEL",
                                    "SPECIALIST_MODEL", "REVIEWER_MODEL"})
        self.assertEqual(P.local_models(env), [])
        self.assertNotEqual(env["JUDGE_MODEL"].split(":")[0].split("-")[0],
                            env["SPECIALIST_MODEL"].split(":")[0].split("-")[0], "judge must be another family")

    def test_guardrail_cli_refuses_local(self):
        with mock.patch.dict(os.environ, {"SPECIALIST_MODEL": "llama3", "ALLOW_LOCAL_MODELS": "0"}):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(GR.main(["--dry-run", str(ROOT / "bench/guardrail/rag-chatbot.profile.json")]), 64)


class Urls(unittest.TestCase):
    def test_bedrock_path_prefix(self):
        self.assertIsNone(P.banned_url("https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-prompt-attack.html"))
        self.assertIn("outside", P.banned_url("https://docs.aws.amazon.com/lambda/latest/dg/welcome.html"))
        self.assertIn("outside", P.banned_url("https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html"))
        self.assertIsNone(P.banned_url("https://docs.nvidia.com/nemo/guardrails/configure-guardrails/guardrail-catalog/pii-detection.md"))


class Parsing(unittest.TestCase):
    def test_extract_json(self):
        self.assertEqual(GR.extract_json('thinking...\n```json\n[{"a": 1}]\n```', "["), [{"a": 1}])
        self.assertEqual(GR.extract_json('x [not json] {"k": [1]}', "{"), {"k": [1]})
        self.assertIsNone(GR.extract_json("no json here", "["))

    def test_parse_proposals(self):
        url = "https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-prompt-attack.html"
        vt = {"INPUT-10": {"prompt_attack_strength": {"type": "enum", "enum": ["NONE", "LOW", "MEDIUM", "HIGH"]},
                           "x": {"type": "boolean"}}}
        text = json.dumps([
            {"control_id": "INPUT-10", "parameters": {"prompt_attack_strength": "high"}, "rationale": "r",
             "source_url": url, "source_quote": '"set the strength"'},
            {"control_id": "TOOL-01", "parameters": {"x": True}, "source_url": url, "source_quote": "q"},
            {"control_id": "INPUT-10", "parameters": {}, "source_url": url, "source_quote": "q"},
            {"control_id": "INPUT-10", "parameters": {"Bad Name": True}, "source_url": url, "source_quote": "q"},
            {"control_id": "INPUT-10", "parameters": {"x": {"nested": 1}}, "source_url": url, "source_quote": "q"},
            {"control_id": "INPUT-10", "parameters": {"x": True}, "source_url": "http://x", "source_quote": "q"},
            {"control_id": "INPUT-10", "parameters": {"x": True}, "source_url": url},
            {"control_id": "INPUT-10", "key": "x", "value": None, "source_url": url, "source_quote": ""},
        ])
        ok, bad, nulls = GR.parse_proposals(text, vt)
        self.assertEqual([o["parameters"] for o in ok], [{"prompt_attack_strength": "HIGH"}])  # normalised enum
        self.assertEqual(ok[0]["source_quote"], "set the strength")
        self.assertEqual(len(bad), 6, bad)
        self.assertIn("not assigned", bad[0]["reason"])
        self.assertIn("value type check", bad[3]["reason"])
        self.assertEqual(nulls, [{"control_id": "INPUT-10", "key": "x"}])
        ok, bad, _ = GR.parse_proposals(json.dumps([{"control_id": "INPUT-10", "parameters": {"made_up_key": 1},
                                                     "source_url": url, "source_quote": "q"}]), vt)
        self.assertEqual(ok, [])
        self.assertIn("not in allowed_parameter_keys", bad[0]["reason"])
        broken = ('[{"control_id": "INPUT-10", "key": "x", "value": true, "source_url": "https://a", "source_quote": "q"},'
                  '{"control_id": "INPUT-10", "key": "x", "value": false, "source_url": "https://a", "source_quote": "q",}]')
        ok, bad, _ = GR.parse_proposals(broken, vt)
        self.assertEqual([o["parameters"] for o in ok], [{"x": True}])
        self.assertIn("1 proposal(s) in the output were not valid JSON", bad[0]["reason"])
        self.assertEqual(GR.parse_proposals("```json\n[]\n```", vt), ([], [], []))
        ok, bad, _ = GR.parse_proposals("I could not find anything.", vt)
        self.assertEqual((ok, len(bad)), ([], 1))

    def test_known_bad_values_rejected_before_the_judge(self):
        """The three bad values that passed the judge in the Step 4 runs."""
        cat = {c["id"]: c for c in json.loads((ROOT / "seeds/guardrail-catalog.json").read_text())["controls"]}
        vt = {cid: cat[cid]["value_types"] for cid in ("OUTPUT-04", "PROMPT-01", "INPUT-07", "RUNTIME-04")}
        bedrock = "https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-word-filters.html"
        nemo = "https://docs.nvidia.com/nemo/guardrails/configure-guardrails/guardrail-catalog/fact-checking.md"
        text = json.dumps([
            {"control_id": "OUTPUT-04", "key": "profanity_filter", "value": "BLOCK", "source_url": bedrock,
             "source_quote": "Choose BLOCK to block content and replace with blocked messaging"},
            {"control_id": "PROMPT-01", "key": "input_tagging", "value": "input tags for guardrails", "source_url": bedrock,
             "source_quote": "With input tags for guardrails, the prompt attack filter will detect malicious intents"},
            {"control_id": "INPUT-07", "key": "max_input_tokens", "value": 1024, "source_url": nemo,
             "source_quote": "if unset, the action falls back to 1024 tokens."},
            {"control_id": "RUNTIME-04", "key": "max_input_tokens", "value": 1024, "source_url": nemo,
             "source_quote": "if unset, the action falls back to 1024 tokens."},
            # A good one for contrast: number in the quote and about input size.
            {"control_id": "INPUT-07", "key": "max_input_chars", "value": 10000, "source_url": nemo,
             "source_quote": "Prompt: supports a maximum of 10,000 characters"},
        ])
        ok, bad, _ = GR.parse_proposals(text, vt)
        self.assertEqual([o["parameters"] for o in ok], [{"max_input_chars": 10000}])
        reasons = [b["reason"] for b in bad]
        self.assertIn("expected true/false, got 'BLOCK'", reasons[0])
        self.assertIn("expected true/false, got 'input tags for guardrails'", reasons[1])
        self.assertIn("does not mention input / prompt / request / context", reasons[2])
        self.assertIn("does not mention input / prompt / request / context", reasons[3])

    def test_fact_line_goes_through_quote_check(self):
        url = "https://docs.nvidia.com/nemo/guardrails/x.md"
        page = P.Page(url, True, 200, "Jailbreak detection uses **heuristics** to block attacks.")
        props = [{"control_id": "PROMPT-07", "parameters": {"jailbreak_heuristics": True}, "rationale": "r",
                  "source_url": url, "source_quote": "uses heuristics to block attacks"},
                 {"control_id": "PROMPT-07", "parameters": {"threshold": 0.9}, "rationale": "r",
                  "source_url": url, "source_quote": "threshold of 0.9"}]
        facts = [GR.to_fact(i, p, "Jailbreak detection") for i, p in enumerate(props, 1)]
        P.check_quotes(facts, [page])
        self.assertEqual([f.verdict for f in facts], ["", "UNSUPPORTED"])
        P.apply_judge(facts, "[1] | SUPPORTED | NOTE: none")
        self.assertEqual(facts[0].verdict, "SUPPORTED")

    def test_dry_run(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = GR.main(["--dry-run", str(ROOT / "bench/guardrail/tool-agent.profile.json")])
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("===== tool_specialist =====", text)
        self.assertNotIn("retrieval_specialist", text)  # no RAG -> no retrieval specialist
        self.assertNotIn("memory_specialist", text)
        self.assertIn("TOOL-05 | tool | Transaction limits", text)
        self.assertIn("START PAGES:", text)


class Retry(unittest.TestCase):
    def fake(self, outcomes):
        calls = []

        def run(config, agent, prompt, path, timeout):
            calls.append(path.name)
            rc, final, errors = outcomes[len(calls) - 1]
            return P.AgentRun(agent, rc, 0.1, final, [], errors, 0)
        return run, calls

    def test_backoff_on_rate_limit_then_success(self):
        run, calls = self.fake([(1, "", ["429 Too Many Requests"]), (1, "", ["connection reset by peer"]), (0, "[]", [])])
        slept = []
        with contextlib.redirect_stderr(io.StringIO()), mock.patch.dict(os.environ, {"GUARDRAIL_BACKOFF_SECONDS": "2"}):
            r = GR.call_agent("c", "judge", "p", Path("/tmp/judge.ndjson"), 1, run=run, sleep=slept.append)
        self.assertEqual((r.rc, r.final), (0, "[]"))
        self.assertEqual(slept, [2.0, 4.0])
        self.assertEqual(calls, ["judge.ndjson", "judge.try2.ndjson", "judge.try3.ndjson"])

    def test_gives_up_after_three_tries_and_skips_non_retryable(self):
        run, calls = self.fake([(1, "", ["model stream stalled: no data received"])] * 3)
        with contextlib.redirect_stderr(io.StringIO()):
            r = GR.call_agent("c", "x", "p", Path("/tmp/x.ndjson"), 1, run=run, sleep=lambda s: None)
        self.assertEqual((r.rc, len(calls)), (1, 3))
        run, calls = self.fake([(1, "", ["invalid config: unknown field"])])
        r = GR.call_agent("c", "x", "p", Path("/tmp/x.ndjson"), 1, run=run, sleep=lambda s: None)
        self.assertEqual(len(calls), 1)

    def test_parallel_clamped(self):
        self.assertEqual([GR.clamp_parallel(n) for n in (0, 4, 7, 20)], [1, 4, 7, 7])
        self.assertEqual(GR.PARALLEL_DEFAULT, 4)


class Sources(unittest.TestCase):
    def test_category_sources_follow_scope_files(self):
        tool = GR.category_sources("tool")
        self.assertTrue(tool)
        self.assertFalse(any("docs.aws.amazon.com" in u for u in tool))  # tool scope lists no Bedrock pages
        self.assertTrue(any("guardrails-content-filters" in u for u in GR.category_sources("output")))
        for cat in CATS:
            for u in GR.category_sources(cat):
                self.assertIsNone(P.banned_url(u), u)
                self.assertNotIn("atlas.mitre.org", u)  # ATLAS is not a quote source

    def test_html_to_text(self):
        raw = ("<html><head><style>x{}</style><script>var a=1</script></head><body><nav>Menu Home</nav>"
               "<main><h1>Prompt attack</h1><p>Set the filter strength to <b>HIGH</b>.</p>"
               "<ul><li>Jailbreak</li><li>Prompt injection</li></ul></main><footer>Copyright</footer></body></html>")
        text = GR.html_to_text(raw)
        self.assertEqual(text.splitlines(), ["Prompt attack", "Set the filter strength to HIGH.", "Jailbreak", "Prompt injection"])

    def test_excerpt_keeps_relevant_paragraphs_in_order(self):
        text = "\n".join([
            "This paragraph is about cookies and site navigation only.",
            "Configure the jailbreak detection threshold to block attacks.",
            "Unrelated legal notice text that is long enough to count here.",
            "Prompt injection screening uses a classifier with a strength level.",
        ])
        words = GR.keywords([{"name": "Jailbreak detection", "description": "Detect prompt injection."}])
        ex = GR.excerpt(text, words, 1000)
        self.assertEqual(ex.splitlines(), [text.splitlines()[1], text.splitlines()[3]])
        self.assertLessEqual(len(GR.excerpt(text, words, 70)), 70)

    def test_prompt_contains_sources_block(self):
        page = P.Page("https://docs.nvidia.com/nemo/guardrails/x.md", True, 200,
                      "Jailbreak detection heuristics block adversarial prompts with a threshold.")
        block, meta = GR.sources_block([page, P.Page("https://x/y", False, 404, "", "gone")],
                                       [{"name": "Jailbreak detection", "description": "Detect jailbreaks."}], 5000)
        self.assertIn("=== SOURCE https://docs.nvidia.com/nemo/guardrails/x.md ===", block)
        self.assertEqual(len(meta), 1)
        prompt = GR.specialist_prompt({"name": "p"}, [], block)
        self.assertIn("\nSOURCES:\n=== SOURCE", prompt)


if __name__ == "__main__":
    unittest.main()
