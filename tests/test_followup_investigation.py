"""Policy-visible follow-ups preserve action, evidence, and source boundaries."""

import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jev_scout import JevPolicy, investigate, recover
from jev_scout.cli import main
from jev_scout.jev import TransportResponse
from jev_scout.models import RulePolicy


class FollowupInvestigationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.repo = self.workspace / "repo"
        self.repo.mkdir()
        self.source = self.repo / "request.cpp"
        lines = [f"int value_{index} = {index};\n" for index in range(1, 51)]
        lines[9] = "int before_only_marker = 1;\n"
        lines[19] = "void Request::cancel() { cancelled_ = true; }\n"
        lines[29] = "int after_only_marker = 1;\n"
        self.text = "".join(lines)
        self.source.write_text(self.text)
        self.output = self.workspace / "output"
        self.task = "Investigate Request::cancel"

    def bundle(self, output=None):
        return json.loads(((output or self.output) / "evidence.json").read_text())

    def events(self):
        return [
            json.loads(line) for line in (self.output / "events.jsonl").read_text().splitlines()
        ]

    def test_default_mode_retains_fixed_frontier_and_offline_behavior(self):
        with patch("jev_scout.jev._post", side_effect=AssertionError("Unexpected network.")):
            investigate(self.repo, self.task, self.output)
            explicit = self.workspace / "explicit"
            investigate(self.repo, self.task, explicit, max_followups=0)
        first, second = self.bundle(), self.bundle(explicit)
        self.assertEqual(first["observations"], second["observations"])
        self.assertEqual(first["candidates"], second["candidates"])
        self.assertEqual(first["decisions"], second["decisions"])
        self.assertEqual(len(first["observations"]), 1)
        self.assertFalse(first["expansion"]["enabled"])
        self.assertEqual(first["generated_candidate_lineage"], [])
        self.assertFalse(any(e["type"] == "candidate_generated" for e in self.events()))

    def test_policy_can_read_evidence_outside_the_initial_window(self):
        investigate(self.repo, self.task, self.output, max_steps=3, max_followups=2)
        bundle = self.bundle()
        self.assertEqual(bundle["schema_version"], 2)
        self.assertEqual(bundle["initial_candidate_ids"], ["c0001"])
        self.assertEqual(len(bundle["observations"]), 3)
        self.assertNotIn("before_only_marker", bundle["observations"][0]["text"])
        self.assertIn("before_only_marker", bundle["observations"][1]["text"])
        self.assertIn("after_only_marker", bundle["observations"][2]["text"])
        self.assertEqual(bundle["expansion"]["generated_candidates"], 2)
        self.assertGreater(bundle["expansion"]["suppressed_proposals"], 0)
        self.assertEqual(
            [entry["direction"] for entry in bundle["generated_candidate_lineage"]],
            ["before", "after"],
        )
        for entry in bundle["generated_candidate_lineage"]:
            self.assertEqual(entry["parent_candidate_id"], "c0001")
            self.assertEqual(entry["parent_observation_id"], "o0001")
        generated = [event for event in self.events() if event["type"] == "candidate_generated"]
        self.assertEqual([event["candidate"]["id"] for event in generated], ["c0002", "c0003"])
        self.assertEqual(self.source.read_text(), self.text)

    def test_generated_offers_and_executed_reads_have_distinct_budgets(self):
        result = investigate(self.repo, self.task, self.output, max_steps=1, max_followups=2)
        bundle = self.bundle()
        self.assertEqual(result.steps, 1)
        self.assertEqual(result.observations, 1)
        self.assertEqual(result.stop_reason, "step_budget_exhausted")
        self.assertEqual(bundle["expansion"]["generated_candidates"], 2)
        self.assertEqual(bundle["deferred_candidate_ids"], ["c0002", "c0003"])

    def test_invalid_followup_budgets_fail_before_any_source_access(self):
        for value in (-1, 101, True, False, 1.5, "2", None):
            with self.subTest(value=value):
                with patch(
                    "jev_scout.investigator.SafeRepository",
                    side_effect=AssertionError("Invalid settings must not read sources."),
                ) as repository:
                    with self.assertRaisesRegex(ValueError, "Follow-up candidate budget"):
                        investigate(self.repo, self.task, self.output, max_followups=value)
                repository.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_a_future_candidate_id_cannot_execute_before_it_is_offered(self):
        class FuturePolicy:
            def choose(self, state, candidates):
                return "c0002"

        result = investigate(
            self.repo, self.task, self.output, policy=FuturePolicy(), max_followups=2
        )
        self.assertEqual(result.stop_reason, "invalid_policy_choice")
        self.assertEqual(result.steps, 0)
        self.assertEqual(result.observations, 0)
        self.assertEqual(self.bundle()["expansion"]["generated_candidates"], 0)

    def test_changed_initial_read_cannot_expand_the_frontier(self):
        source = self.source

        class MutatingPolicy(RulePolicy):
            def choose(self, state, candidates):
                source.write_text("void changed() {}\n")
                return super().choose(state, candidates)

        investigate(self.repo, self.task, self.output, policy=MutatingPolicy(), max_followups=2)
        bundle = self.bundle()
        self.assertEqual(bundle["observations"], [])
        self.assertEqual(bundle["expansion"]["generated_candidates"], 0)
        self.assertTrue(any(e.get("reason") == "source_changed" for e in self.events()))

    def test_followup_reads_recheck_hash_and_preserve_original_observation(self):
        source = self.source

        class MutatingPolicy(RulePolicy):
            def choose(self, state, candidates):
                if state.step == 1:
                    source.write_text("void changed() {}\n")
                return super().choose(state, candidates)

        investigate(
            self.repo, self.task, self.output, max_steps=2, policy=MutatingPolicy(), max_followups=2
        )
        bundle = self.bundle()
        self.assertEqual(bundle["steps"], 2)
        self.assertEqual(len(bundle["observations"]), 1)
        self.assertIn("Request::cancel", bundle["observations"][0]["text"])
        self.assertEqual(bundle["observations"][0]["validity"], "changed")
        checks = [e for e in self.events() if e["type"] == "frontier_expansion_checked"]
        self.assertEqual(len(checks), 1)
        self.assertTrue(any(e.get("reason") == "source_changed" for e in self.events()))

    def test_global_candidate_bound_preserves_recovery_compatibility(self):
        lines = [f"int value_{index} = {index};\n" for index in range(1, 2001)]
        lines[999] = "void Request::cancel() {}\n"
        text = "".join(lines)
        self.source.write_text(text)
        result = investigate(self.repo, self.task, self.output, max_steps=200, max_followups=100)
        bundle = self.bundle()
        self.assertEqual(len(bundle["candidates"]), 100)
        self.assertEqual(result.steps, 100)
        self.assertEqual(result.observations, 100)
        self.assertEqual(bundle["expansion"]["generated_candidates"], 99)
        self.assertTrue(bundle["expansion"]["candidate_limit_reached"])
        self.assertGreater(bundle["expansion"]["candidate_limit_suppressed_proposals"], 0)
        recovery = recover(result.evidence_path, self.repo, ["o0100"], self.workspace / "recovery")
        self.assertEqual(recovery.recovered, 1)
        self.assertEqual(self.source.read_text(), text)

    def test_injected_jev_can_select_followups_and_fallback_keeps_them_eligible(self):
        sentinel = "followup-fixture-key-must-not-be-persisted"
        requests = []

        def transport(payload, key, timeout, response_limit):
            request = json.loads(payload)
            requests.append(request)
            ids = list(request["questions"]["next_action"]["criteria"])
            chosen = ids[0]
            return TransportResponse(
                200,
                json.dumps(
                    {
                        "model": "jev-1.13.0",
                        "answers": {
                            "next_action": {
                                "type": "choice",
                                "choice": chosen,
                                "confidence": 1.0,
                                "probabilities": {
                                    identifier: float(identifier == chosen) for identifier in ids
                                },
                            }
                        },
                        "usage": {"input_tokens": 5, "output_tokens": 2},
                    }
                ).encode(),
            )

        policy = JevPolicy(sentinel, max_calls=2, transport=transport)
        investigate(self.repo, self.task, self.output, max_steps=3, policy=policy, max_followups=2)
        bundle = self.bundle()
        self.assertEqual(len(requests), 2)
        self.assertEqual(
            set(requests[1]["questions"]["next_action"]["criteria"]), {"c0002", "c0003"}
        )
        self.assertEqual(bundle["decisions"][1]["backend"], "jev")
        self.assertEqual(bundle["decisions"][2]["fallback_reason"], "call_budget_exhausted")
        self.assertEqual(len(bundle["observations"]), 3)
        self.assertEqual(bundle["policy_accounting"]["provider_attempts"], 2)
        for artifact in self.output.iterdir():
            self.assertNotIn(sentinel, artifact.read_text())

    def test_cli_followups_remain_offline_and_context_bounded(self):
        with (
            patch("jev_scout.cli.JevPolicy", side_effect=AssertionError("Remote opt-in required.")),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            code = main(
                [
                    "investigate",
                    "--repo",
                    str(self.repo),
                    "--task",
                    self.task,
                    "--output",
                    str(self.output),
                    "--max-steps",
                    "3",
                    "--max-followups",
                    "2",
                    "--max-context-chars",
                    "40",
                ]
            )
        self.assertEqual(code, 0)
        bundle = self.bundle()
        self.assertEqual(bundle["expansion"]["generated_candidates"], 2)
        self.assertLessEqual(bundle["context"]["characters"], 40)
        self.assertEqual(bundle["policy_accounting"]["provider_attempts"], 0)
        self.assertEqual(
            hashlib.sha256(self.source.read_bytes()).hexdigest(),
            bundle["observations"][0]["source_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
