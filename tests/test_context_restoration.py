"""In-run restoration preserves evidence, source checks, and shared action budgets."""

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jev_scout import JevPolicy, investigate, recover
from jev_scout.cli import main
from jev_scout.investigator import _restore_context
from jev_scout.jev import TransportResponse
from jev_scout.models import ActionCandidate, ContextEntry, RestoreObservationArgs, RulePolicy
from jev_scout.repository import SafeRepository


class ContextRestorationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.repo = self.workspace / "repo"
        self.repo.mkdir()
        self.output = self.workspace / "output"
        self.task = "cancel callback"
        self.original = {}
        for index in range(2):
            self.add_source(index)

    def add_source(self, index, text=None):
        name = f"source{index:03}.py"
        text = text if text is not None else f"def cancel_callback_{index}():\n    return {index}\n"
        (self.repo / name).write_text(text, encoding="utf-8")
        self.original[name] = text
        return self.repo / name

    def bundle(self, output=None):
        return json.loads(((output or self.output) / "evidence.json").read_text())

    def events(self):
        return [
            json.loads(line) for line in (self.output / "events.jsonl").read_text().splitlines()
        ]

    def run_investigation(self, **kwargs):
        settings = {"max_steps": 8, "max_context_chars": 10, "max_restores": 2}
        settings.update(kwargs)
        return investigate(self.repo, self.task, self.output, **settings)

    def assert_sources_unchanged(self):
        for name, text in self.original.items():
            self.assertEqual((self.repo / name).read_text(), text)

    def test_disabled_default_preserves_the_read_only_offline_baseline(self):
        with patch("jev_scout.jev._post", side_effect=AssertionError("Unexpected network.")):
            self.run_investigation(max_restores=0)
            explicit = self.workspace / "explicit"
            investigate(self.repo, self.task, explicit, max_context_chars=10)
        first, second = self.bundle(), self.bundle(explicit)
        for key in ("candidates", "observations", "decisions", "context", "action_counts"):
            self.assertEqual(first[key], second[key])
        self.assertEqual(first["schema_version"], 3)
        self.assertFalse(first["restoration"]["enabled"])
        self.assertEqual(first["restoration_checks"], [])
        self.assertEqual(first["action_counts"], {"read_snippet": 2, "restore_observation": 0})
        self.assertFalse(any("restoration" in event["type"] for event in self.events()))
        self.assert_sources_unchanged()

    def test_restore_keeps_original_observations_and_bounded_context(self):
        result = self.run_investigation(max_restores=1)
        bundle = self.bundle()
        self.assertEqual((result.steps, result.observations), (3, 2))
        self.assertEqual(result.stop_reason, "candidates_exhausted")
        self.assertEqual(bundle["action_counts"], {"read_snippet": 2, "restore_observation": 1})
        self.assertEqual(bundle["restoration"]["generated_candidates"], 1)
        self.assertEqual(bundle["restoration"]["restore_limit_suppressed_proposals"], 1)
        check = bundle["restoration_checks"][0]
        self.assertEqual(check["observation_id"], "o0001")
        self.assertEqual(check["outcome"], "restored")
        self.assertEqual(check["validity"], "current_at_restore_check")
        self.assertEqual(check["source_mode"], "live")
        original = bundle["observations"][0]
        self.assertEqual(
            bundle["context"]["active"],
            [
                {
                    "observation_id": original["id"],
                    "text": original["text"][:10],
                    "truncated": True,
                }
            ],
        )
        self.assertEqual(bundle["context"]["characters"], 10)
        self.assertEqual(
            len([event for event in self.events() if event["type"] == "observation_recorded"]), 2
        )
        for observation in bundle["observations"]:
            self.assertEqual(observation["text"], self.original[observation["path"]])
            self.assertEqual(observation["validity"], "current_at_final_check")
            self.assertFalse(observation["excerpt_truncated"])
        self.assert_sources_unchanged()

    def test_restoration_cascade_is_one_shot_and_cannot_loop(self):
        result = self.run_investigation(max_steps=100, max_restores=100)
        bundle = self.bundle()
        self.assertEqual((result.steps, result.observations), (4, 2))
        self.assertEqual(result.stop_reason, "candidates_exhausted")
        restores = [
            candidate
            for candidate in bundle["candidates"]
            if candidate["kind"] == "restore_observation"
        ]
        self.assertEqual(
            [candidate["args"]["observation_id"] for candidate in restores], ["o0001", "o0002"]
        )
        self.assertEqual(
            [check["outcome"] for check in bundle["restoration_checks"]], ["restored", "restored"]
        )
        self.assertEqual(bundle["context"]["evicted_ids"], ["o0001", "o0002", "o0001"])
        self.assertEqual(
            [entry["observation_id"] for entry in bundle["context"]["active"]], ["o0002"]
        )
        self.assertEqual(len(bundle["observations"]), 2)
        self.assertEqual(len({candidate["id"] for candidate in bundle["candidates"]}), 4)

    def test_offered_restore_can_remain_deferred_at_the_shared_step_limit(self):
        result = self.run_investigation(max_steps=2)
        bundle = self.bundle()
        self.assertEqual((result.steps, result.observations), (2, 2))
        self.assertEqual(result.stop_reason, "step_budget_exhausted")
        self.assertEqual(bundle["restoration"]["generated_candidates"], 1)
        self.assertEqual(bundle["restoration_checks"], [])
        self.assertEqual(bundle["deferred_candidate_ids"], ["c0003"])
        self.assertEqual(bundle["action_counts"]["restore_observation"], 0)

    def test_no_eviction_does_not_generate_restore_offers(self):
        result = self.run_investigation(max_context_chars=12000, max_restores=100)
        self.assertEqual(result.steps, 2)
        bundle = self.bundle()
        self.assertEqual(bundle["context"]["evicted_ids"], [])
        self.assertEqual(bundle["restoration"]["generated_candidates"], 0)
        self.assertEqual(bundle["restoration"]["suppressed_proposals"], 0)

    def test_invalid_restore_budgets_fail_before_source_access_or_outputs(self):
        for value in (True, False, -1, 101, 1.5, "2", None):
            with self.subTest(value=value):
                with patch(
                    "jev_scout.investigator.SafeRepository",
                    side_effect=AssertionError("Sources must not be opened."),
                ) as repository:
                    with self.assertRaisesRegex(ValueError, "Restoration candidate budget"):
                        self.run_investigation(max_restores=value)
                repository.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_unoffered_restore_id_cannot_execute(self):
        class FuturePolicy:
            def choose(self, state, candidates):
                return "c0003"

        result = self.run_investigation(policy=FuturePolicy())
        self.assertEqual(result.stop_reason, "invalid_policy_choice")
        self.assertEqual((result.steps, result.observations), (0, 0))
        self.assertEqual(self.bundle()["restoration"]["generated_candidates"], 0)
        self.assertFalse(any(event["type"] == "action_selected" for event in self.events()))

    def test_repeated_restore_id_cannot_execute_twice(self):
        class RepeatedPolicy(RulePolicy):
            def choose(self, state, candidates):
                return "c0003" if state.step == 3 else super().choose(state, candidates)

        result = self.run_investigation(policy=RepeatedPolicy())
        self.assertEqual(result.stop_reason, "invalid_policy_choice")
        self.assertEqual((result.steps, result.observations), (3, 2))
        self.assertEqual(len(self.bundle()["restoration_checks"]), 1)
        self.assertEqual(
            len([event for event in self.events() if event["type"] == "action_selected"]), 3
        )

    def test_changed_source_omits_restore_and_consumes_one_action(self):
        repo = self.repo

        class MutatingPolicy(RulePolicy):
            def choose(self, state, candidates):
                chosen = super().choose(state, candidates)
                if state.step == 2:
                    target = next(candidate for candidate in candidates if candidate.id == chosen)
                    (repo / target.args.path).write_text("def changed_after_eviction(): pass\n")
                return chosen

        result = self.run_investigation(policy=MutatingPolicy(), max_restores=1)
        bundle = self.bundle()
        self.assertEqual((result.steps, result.observations), (3, 2))
        check = bundle["restoration_checks"][0]
        self.assertEqual((check["outcome"], check["validity"]), ("omitted", "changed"))
        self.assertEqual(check["source_check_reason"], "source_hash_changed")
        self.assertNotEqual(check["current_sha256"], bundle["observations"][0]["source_sha256"])
        self.assertEqual(bundle["context"]["active"][0]["observation_id"], "o0002")
        self.assertEqual(bundle["context"]["evicted_ids"], ["o0001"])
        self.assertEqual(bundle["observations"][0]["text"], self.original["source000.py"])
        self.assertEqual(bundle["observations"][0]["validity"], "changed")

    def test_deleted_source_cannot_reenter_active_context(self):
        repo = self.repo

        class DeletingPolicy(RulePolicy):
            def choose(self, state, candidates):
                chosen = super().choose(state, candidates)
                if state.step == 2:
                    target = next(candidate for candidate in candidates if candidate.id == chosen)
                    (repo / target.args.path).unlink()
                return chosen

        result = self.run_investigation(policy=DeletingPolicy(), max_restores=1)
        self.assertEqual(result.steps, 3)
        bundle = self.bundle()
        check = bundle["restoration_checks"][0]
        self.assertEqual((check["outcome"], check["validity"]), ("omitted", "unavailable"))
        self.assertIsNone(check["current_sha256"])
        self.assertEqual(bundle["context"]["active"][0]["observation_id"], "o0002")
        self.assertEqual(bundle["observations"][0]["validity"], "unavailable")

    def test_successful_restore_does_not_claim_validity_after_a_later_source_change(self):
        path = self.repo / "source000.py"

        class LaterMutatingPolicy(RulePolicy):
            def choose(self, state, candidates):
                if state.step == 3:
                    path.write_text("def later_revision(): pass\n")
                    return None
                return super().choose(state, candidates)

        result = self.run_investigation(policy=LaterMutatingPolicy())
        bundle = self.bundle()
        self.assertEqual((result.steps, result.observations), (3, 2))
        self.assertEqual(result.stop_reason, "policy_stopped")
        check = bundle["restoration_checks"][0]
        self.assertEqual(
            (check["outcome"], check["validity"]), ("restored", "current_at_restore_check")
        )
        observation = bundle["observations"][0]
        self.assertEqual(check["current_sha256"], observation["source_sha256"])
        self.assertEqual(observation["validity"], "changed")
        self.assertNotEqual(observation["current_sha256"], check["current_sha256"])
        self.assertEqual(observation["text"], self.original["source000.py"])
        self.assertEqual(bundle["context"]["active"][0]["observation_id"], "o0001")

    def test_truncated_utf8_raw_excerpt_is_revalidated_before_context_projection(self):
        for index in range(2):
            self.add_source(index, f"# cancel callback {index}: " + "é" * 5000 + "\n")
        result = self.run_investigation(max_context_chars=30, max_restores=1)
        bundle = self.bundle()
        self.assertEqual((result.steps, result.observations), (3, 2))
        original = bundle["observations"][0]
        self.assertEqual(len(original["text"]), 4000)
        self.assertTrue(original["excerpt_truncated"])
        self.assertEqual(original["text"], self.original["source000.py"][:4000])
        self.assertEqual(bundle["restoration_checks"][0]["outcome"], "restored")
        self.assertEqual(
            bundle["context"]["active"],
            [
                {
                    "observation_id": "o0001",
                    "text": original["text"][:30],
                    "truncated": True,
                }
            ],
        )
        self.assertEqual(bundle["context"]["characters"], 30)
        self.assert_sources_unchanged()

    def test_symlink_replacement_does_not_read_outside_source(self):
        outside = self.workspace / "private.py"
        sentinel = "outside-restore-target-must-not-be-read"
        outside.write_text(sentinel)
        repo = self.repo

        class SymlinkPolicy(RulePolicy):
            def choose(self, state, candidates):
                chosen = super().choose(state, candidates)
                if state.step == 2:
                    target = next(candidate for candidate in candidates if candidate.id == chosen)
                    path = repo / target.args.path
                    path.unlink()
                    path.symlink_to(outside)
                return chosen

        self.run_investigation(policy=SymlinkPolicy(), max_restores=1)
        check = self.bundle()["restoration_checks"][0]
        self.assertEqual((check["outcome"], check["validity"]), ("omitted", "unavailable"))
        self.assertEqual(self.bundle()["context"]["active"][0]["observation_id"], "o0002")
        for path in self.output.iterdir():
            self.assertNotIn(sentinel, path.read_text())
        self.assertEqual(outside.read_text(), sentinel)

    def test_exact_excerpt_checks_reject_tampering_despite_matching_source_hash(self):
        path, text = "source000.py", self.original["source000.py"]
        source_hash = hashlib.sha256(text.encode()).hexdigest()
        original = {
            "id": "o0001",
            "path": path,
            "start_line": 1,
            "end_line": 2,
            "source_sha256": source_hash,
            "text": text,
            "excerpt_truncated": False,
        }
        args = RestoreObservationArgs("o0001", path, 1, 2, source_hash)
        candidate = ActionCandidate("c0003", "restore_observation", args, -1, (), text[:240])

        class Events:
            def emit(self, kind, **payload):
                pass

        for change in ({"text": "forged source excerpt"}, {"excerpt_truncated": True}):
            with self.subTest(change=change), SafeRepository(self.repo) as repository:
                observation = {**original, **change}
                active = [ContextEntry("o0002", "safe", False)]
                evicted = []
                check = _restore_context(
                    candidate,
                    {"o0001": observation},
                    active,
                    10,
                    repository,
                    "live",
                    Events(),
                    evicted,
                )
                self.assertEqual(check["current_sha256"], source_hash)
                self.assertEqual(
                    (check["outcome"], check["validity"]), ("omitted", "excerpt_mismatch")
                )
                self.assertEqual(active, [ContextEntry("o0002", "safe", False)])
                self.assertEqual(evicted, [])
                self.assertEqual(observation, {**original, **change})

    def test_restore_and_followup_offers_share_ids_and_the_last_capacity(self):
        lines = [f"value_{index} = {index}\n" for index in range(30)]
        lines[14] = "def cancel_callback_2(): pass\n"
        self.add_source(2, "".join(lines))
        for index in range(3, 98):
            self.add_source(index)
        result = self.run_investigation(max_steps=3, max_followups=100, max_restores=100)
        bundle = self.bundle()
        self.assertEqual((result.steps, result.observations), (3, 3))
        self.assertEqual(len(bundle["initial_candidate_ids"]), 98)
        self.assertEqual(len(bundle["candidates"]), 100)
        self.assertEqual(len({candidate["id"] for candidate in bundle["candidates"]}), 100)
        self.assertEqual(bundle["candidates"][98]["id"], "c0099")
        self.assertEqual(bundle["candidates"][98]["kind"], "restore_observation")
        self.assertEqual(bundle["candidates"][99]["id"], "c0100")
        self.assertEqual(bundle["candidates"][99]["kind"], "read_snippet")
        self.assertEqual(bundle["restoration"]["generated_candidates"], 1)
        self.assertEqual(bundle["restoration"]["candidate_limit_suppressed_proposals"], 1)
        self.assertEqual(bundle["expansion"]["generated_candidates"], 1)
        self.assertEqual(bundle["expansion"]["candidate_limit_suppressed_proposals"], 1)
        kinds = [event["type"] for event in self.events()]
        self.assertLess(
            kinds.index("candidate_generated"),
            len(kinds) - 1 - kinds[::-1].index("restoration_frontier_checked"),
        )
        self.assert_sources_unchanged()

    def test_many_evictions_cannot_exceed_the_global_action_cap(self):
        for index in range(2, 51):
            self.add_source(index)
        result = self.run_investigation(max_steps=200, max_restores=100)
        bundle = self.bundle()
        self.assertEqual((result.steps, result.observations), (100, 51))
        self.assertEqual(result.stop_reason, "candidates_exhausted")
        self.assertEqual(len(bundle["candidates"]), 100)
        self.assertEqual(bundle["restoration"]["generated_candidates"], 49)
        self.assertGreater(bundle["restoration"]["candidate_limit_suppressed_proposals"], 0)
        self.assertEqual(len(bundle["restoration_checks"]), 49)
        self.assertEqual(bundle["action_counts"], {"read_snippet": 51, "restore_observation": 49})
        self.assertLessEqual(bundle["context"]["characters"], 10)
        self.assert_sources_unchanged()

    def _provider_response(self, request, chosen):
        ids = request["questions"]["next_action"]["criteria"]
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

    def test_injected_jev_can_choose_a_restore_from_a_mixed_menu(self):
        self.add_source(2)
        requests = []
        secret = "mixed-menu-credential-must-not-be-persisted"

        def transport(payload, key, timeout, response_limit):
            self.assertEqual(key, secret)
            request = json.loads(payload)
            requests.append(request)
            offered = request["questions"]["next_action"]["criteria"]
            restores = [
                identifier
                for identifier, value in offered.items()
                if value["kind"] == "restore_observation"
            ]
            return self._provider_response(
                request, restores[0] if restores else next(iter(offered))
            )

        result = self.run_investigation(
            max_steps=5, policy=JevPolicy(secret, max_calls=3, transport=transport)
        )
        bundle = self.bundle()
        self.assertEqual((result.steps, result.observations), (5, 3))
        self.assertEqual(len(requests), 3)
        offered = requests[2]["questions"]["next_action"]["criteria"]
        self.assertEqual(
            {value["kind"] for value in offered.values()}, {"read_snippet", "restore_observation"}
        )
        self.assertEqual(offered["c0004"]["observation_id"], "o0001")
        self.assertEqual(requests[2]["state"]["active_context"][0]["observation_id"], "o0002")
        self.assertEqual(bundle["decisions"][2]["candidate_id"], "c0004")
        self.assertEqual(bundle["decisions"][2]["backend"], "jev")
        self.assertEqual(bundle["decisions"][3]["fallback_reason"], "call_budget_exhausted")
        self.assertEqual(bundle["decisions"][4]["fallback_reason"], "call_budget_exhausted")
        self.assertEqual(bundle["action_counts"], {"read_snippet": 3, "restore_observation": 2})
        self.assertEqual(
            [check["outcome"] for check in bundle["restoration_checks"]], ["restored", "restored"]
        )
        self.assertEqual(bundle["policy_accounting"]["provider_attempts"], 3)
        for artifact in self.output.iterdir():
            self.assertNotIn(secret, artifact.read_text())
        self.assert_sources_unchanged()

    def test_invalid_mixed_menu_choice_falls_back_without_losing_restores(self):
        self.add_source(2)
        requests = []

        def transport(payload, key, timeout, response_limit):
            request = json.loads(payload)
            requests.append(request)
            offered = request["questions"]["next_action"]["criteria"]
            chosen = "unoffered-action" if len(requests) == 3 else next(iter(offered))
            return self._provider_response(request, chosen)

        result = self.run_investigation(
            max_steps=5, policy=JevPolicy("fixture", max_calls=3, transport=transport)
        )
        bundle = self.bundle()
        self.assertEqual((result.steps, result.observations), (5, 3))
        self.assertEqual(bundle["decisions"][2]["fallback_reason"], "invalid_response")
        self.assertEqual(bundle["decisions"][2]["candidate_id"], "c0003")
        self.assertEqual(bundle["action_counts"]["restore_observation"], 2)
        self.assertEqual(
            [check["outcome"] for check in bundle["restoration_checks"]], ["restored", "restored"]
        )
        self.assertFalse(
            any(
                event.get("candidate_id") == "unoffered-action"
                and event["type"] == "action_selected"
                for event in self.events()
            )
        )

    def test_schema_three_observations_still_support_manual_recovery(self):
        result = self.run_investigation()
        recovered = recover(
            result.evidence_path,
            self.repo,
            ["o0001"],
            self.workspace / "recovery",
            max_context_chars=7,
        )
        self.assertEqual((recovered.requested, recovered.recovered), (1, 1))
        recovery = json.loads(recovered.recovery_path.read_text())
        self.assertEqual(
            recovery["context"]["active"],
            [
                {
                    "observation_id": "o0001",
                    "text": self.original["source000.py"][:7],
                    "truncated": True,
                }
            ],
        )
        self.assertEqual(recovery["observations"][0]["text"], self.original["source000.py"])
        self.assertEqual(recovery["observations"][0]["validity"], "current_at_recovery_check")

    def test_cli_restoration_remains_offline_and_reports_total_actions(self):
        stdout = io.StringIO()
        with (
            patch.dict(os.environ, {"TYPESAFE_API_KEY": "unused-fixture-key"}),
            patch(
                "jev_scout.cli.JevPolicy", side_effect=AssertionError("Remote policy needs opt-in.")
            ),
            contextlib.redirect_stdout(stdout),
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
                    "--max-restores",
                    "1",
                    "--max-context-chars",
                    "10",
                ]
            )
        self.assertEqual(code, 0)
        self.assertIn("2 observations in 3 total actions", stdout.getvalue())
        self.assertEqual(self.bundle()["policy_accounting"]["provider_attempts"], 0)
        self.assertEqual(self.bundle()["restoration_checks"][0]["outcome"], "restored")
        report = (self.output / "report.md").read_text()
        self.assertIn("Total actions: 3 / 3", report)
        self.assertIn("Restored observations: 1", report)
        self.assert_sources_unchanged()


if __name__ == "__main__":
    unittest.main()
