"""Fair frozen inputs, explicit accounting, and comparison execution boundaries."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jev_scout.comparison import compare
from jev_scout.jev import JevPolicy, TransportResponse
from jev_scout.models import RulePolicy
from jev_scout.repository import SafeRepository


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.repo = self.workspace / "repo"
        self.repo.mkdir()
        self.output = self.workspace / "output"
        self.original = {}
        for index in range(3):
            path = self.repo / f"source{index}.py"
            text = f"def cancel_callback_{index}():\n    return {index}\n"
            path.write_text(text, encoding="utf-8")
            self.original[path.name] = text

    def summary(self, output=None):
        return json.loads(((output or self.output) / "comparison.json").read_text())

    def bundle(self, name, output=None):
        return json.loads(((output or self.output) / name / "evidence.json").read_text())

    @staticmethod
    def response(payload, usage=True):
        request = json.loads(payload)
        ids = list(request["questions"]["next_action"]["criteria"])
        response = {
            "model": "jev-1.13.0",
            "answers": {
                "next_action": {
                    "type": "choice",
                    "choice": ids[-1],
                    "confidence": 1.0,
                    "probabilities": {key: float(key == ids[-1]) for key in ids},
                }
            },
        }
        if usage:
            response["usage"] = {"input_tokens": 5, "output_tokens": 2}
        return TransportResponse(200, json.dumps(response).encode())

    def test_default_offline_pair_is_reproducible_and_read_only(self):
        with patch("jev_scout.jev._post", side_effect=AssertionError("Network was used.")):
            result = compare(self.repo, "cancel callback", self.output)
        summary = self.summary()
        self.assertEqual(result.comparison_path, self.output.resolve() / "comparison.json")
        self.assertEqual(result.report_path, self.output.resolve() / "report.md")
        self.assertEqual(summary["snapshot_id"], result.snapshot_id)
        self.assertEqual(summary["arm_order"], ["rule", "challenger"])
        self.assertEqual(summary["agreement"]["positional_action_agreement"], 1.0)
        self.assertEqual(summary["agreement"]["observed_candidate_jaccard"], 1.0)
        for name in ("rule", "challenger"):
            self.assertEqual(summary["arms"][name]["transport"], "none")
            self.assertEqual(summary["arms"][name]["policy_accounting"]["provider_attempts"], 0)
        self.assertEqual(
            {path.name: path.read_text() for path in self.repo.iterdir()}, self.original
        )

    def test_discovery_occurs_once_and_both_arms_receive_the_exact_frontier(self):
        original_discover = SafeRepository.discover
        calls = []

        def discover(repository, task):
            calls.append(task)
            return original_discover(repository, task)

        with patch.object(SafeRepository, "discover", discover):
            compare(self.repo, "cancel callback", self.output)
        self.assertEqual(calls, ["cancel callback"])
        first = self.bundle("rule")
        second = self.bundle("challenger")
        self.assertEqual(first["candidates"], second["candidates"])
        self.assertEqual(first["terms"], second["terms"])
        self.assertEqual(first["scan"], second["scan"])
        self.assertEqual(first["limits"], second["limits"])
        self.assertEqual(first["snapshot_id"], second["snapshot_id"])

    def test_original_checkout_changes_do_not_change_frozen_inputs(self):
        def challenger_factory():
            (self.repo / "source0.py").write_text("def different():\n    return 99\n")
            (self.repo / "source1.py").unlink()
            return RulePolicy()

        compare(self.repo, "cancel callback", self.output, challenger_factory=challenger_factory)
        first = self.bundle("rule")
        second = self.bundle("challenger")
        self.assertEqual(first["observations"], second["observations"])
        self.assertEqual(second["source_mode"], "frozen")
        for observation in second["observations"]:
            self.assertEqual(observation["validity"], "matched_frozen_snapshot")
            self.assertIsNone(observation["current_sha256"])
            self.assertEqual(observation["text"], self.original[observation["path"]])
        summary = self.summary()
        self.assertEqual(
            summary["original_source_revalidation"]["status_counts"],
            {"current_at_final_check": 1, "changed": 1, "unavailable": 1},
        )
        self.assertTrue(summary["original_source_revalidation"]["performed_after_both_arms"])

    def test_source_change_during_capture_fails_before_policy_creation(self):
        original_discover = SafeRepository.discover
        factory = Mock(side_effect=AssertionError("Policy was created."))

        def discover(repository, task):
            frontier = original_discover(repository, task)
            (repository.root / frontier[0][0].args.path).write_text("def changed(): pass\n")
            return frontier

        with patch.object(SafeRepository, "discover", discover):
            with self.assertRaisesRegex(ValueError, "changed during capture"):
                compare(self.repo, "cancel callback", self.output, challenger_factory=factory)
        factory.assert_not_called()
        self.assertFalse((self.output / "rule" / "events.jsonl").exists())
        self.assertFalse((self.output / "comparison.json").exists())

    def test_missing_source_during_capture_fails_before_policy_creation(self):
        original_discover = SafeRepository.discover
        factory = Mock(side_effect=AssertionError("Policy was created."))

        def discover(repository, task):
            frontier = original_discover(repository, task)
            (repository.root / frontier[0][0].args.path).unlink()
            return frontier

        with patch.object(SafeRepository, "discover", discover):
            with self.assertRaisesRegex(ValueError, "unavailable during capture"):
                compare(self.repo, "cancel callback", self.output, challenger_factory=factory)
        factory.assert_not_called()

    def test_capture_byte_limit_fails_before_policy_creation(self):
        factory = Mock(side_effect=AssertionError("Policy was created."))
        with patch("jev_scout.comparison.MAX_SCAN_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "capture byte budget"):
                compare(self.repo, "cancel callback", self.output, challenger_factory=factory)
        factory.assert_not_called()

    def test_output_conflicts_fail_before_discovery_or_policy_creation(self):
        for name in ("comparison.json", "report.md", "rule", "challenger"):
            with self.subTest(name=name):
                output = self.workspace / ("conflict-" + name)
                output.mkdir()
                (output / name).write_text("existing")
                factory = Mock(side_effect=AssertionError("Policy was created."))
                with patch.object(SafeRepository, "discover") as discover:
                    with self.assertRaises(ValueError):
                        compare(self.repo, "cancel callback", output, challenger_factory=factory)
                discover.assert_not_called()
                factory.assert_not_called()
                self.assertEqual((output / name).read_text(), "existing")

    def test_output_inside_source_fails_without_creating_files(self):
        factory = Mock(side_effect=AssertionError("Policy was created."))
        output = self.repo / "comparison-output"
        with self.assertRaisesRegex(ValueError, "outside"):
            compare(self.repo, "cancel callback", output, challenger_factory=factory)
        self.assertFalse(output.exists())
        factory.assert_not_called()

    def test_snapshot_identity_is_stable_across_output_and_repository_paths(self):
        other_repo = self.workspace / "copied-repo"
        shutil.copytree(self.repo, other_repo)
        first = compare(self.repo, "cancel callback", self.output)
        second_output = self.workspace / "second-output"
        second = compare(other_repo, "cancel callback", second_output)
        self.assertEqual(first.snapshot_id, second.snapshot_id)
        first_snapshot = self.summary()["snapshot"]
        self.assertEqual(first_snapshot, self.summary(second_output)["snapshot"])
        self.assertNotIn(str(self.repo), json.dumps(first_snapshot))
        self.assertNotIn("timestamp", first_snapshot)

    def test_snapshot_identity_changes_with_source_task_or_limits(self):
        original = compare(self.repo, "cancel callback", self.output).snapshot_id
        changed_task = compare(
            self.repo, "cancel callback investigation", self.workspace / "changed-task"
        ).snapshot_id
        changed_limits = compare(
            self.repo, "cancel callback", self.workspace / "changed-limits", max_steps=1
        ).snapshot_id
        (self.repo / "source0.py").write_text("def cancel_callback_0():\n    return 77\n")
        changed_source = compare(
            self.repo, "cancel callback", self.workspace / "changed-source"
        ).snapshot_id
        self.assertEqual(len({original, changed_task, changed_limits, changed_source}), 4)

    def test_snapshot_manifest_contains_hashes_not_an_additional_full_source_archive(self):
        compare(self.repo, "cancel callback", self.output)
        summary = self.summary()
        sources = summary["snapshot"]["sources"]
        self.assertEqual(len(sources), 3)
        self.assertEqual(summary["captured_bytes"], sum(source["byte_size"] for source in sources))
        self.assertTrue(all(set(source) == {"path", "sha256", "byte_size"} for source in sources))
        self.assertTrue(all(len(source["sha256"]) == 64 for source in sources))
        self.assertEqual(
            {path.name for path in self.output.iterdir()},
            {"comparison.json", "report.md", "rule", "challenger"},
        )

    def test_empty_frontier_produces_null_diagnostics(self):
        compare(self.repo, "no_unrelated_symbol_matches", self.output)
        summary = self.summary()
        self.assertEqual(summary["snapshot"]["sources"], [])
        self.assertEqual(summary["agreement"]["action_positions"], 0)
        self.assertIsNone(summary["agreement"]["positional_action_agreement"])
        self.assertIsNone(summary["agreement"]["observed_candidate_jaccard"])
        self.assertEqual(summary["arms"]["rule"]["stop_reason"], "no_candidates")

    def test_partial_discovery_is_preserved_and_disclosed_in_both_arms(self):
        with (
            patch("jev_scout.repository.MAX_SCAN_FILES", 1),
            patch("jev_scout.comparison.MAX_SCAN_FILES", 1),
        ):
            compare(self.repo, "cancel callback", self.output)
        summary = self.summary()
        self.assertTrue(summary["snapshot"]["scan"]["truncated"])
        self.assertEqual(summary["snapshot"]["limits"]["max_scan_files"], 1)
        self.assertEqual(len(summary["snapshot"]["candidates"]), 1)
        for name in ("rule", "challenger"):
            self.assertTrue(self.bundle(name)["scan"]["truncated"])
        self.assertIn("not an atomic snapshot", (self.output / "report.md").read_text())

    def test_injected_jev_is_distinguished_and_unknown_usage_is_not_zero(self):
        calls = []
        secret = "credential-sentinel-must-not-persist"

        def transport(payload, key, timeout, max_response_bytes):
            calls.append(payload)
            self.assertEqual(key, secret)
            return self.response(payload, usage=False)

        compare(
            self.repo,
            "cancel callback",
            self.output,
            max_steps=1,
            challenger_factory=lambda: JevPolicy(secret, transport=transport),
        )
        summary = self.summary()
        arm = summary["arms"]["challenger"]
        self.assertEqual(arm["transport"], "injected")
        self.assertEqual(arm["reported_response_models"], ["jev-1.13.0"])
        self.assertEqual(arm["policy_accounting"]["provider_attempts"], 1)
        self.assertEqual(arm["policy_accounting"]["unknown_input_usage_attempts"], 1)
        self.assertEqual(arm["policy_accounting"]["unknown_output_usage_attempts"], 1)
        self.assertEqual(summary["agreement"]["positional_action_agreement"], 0.0)
        self.assertEqual(summary["agreement"]["observed_candidate_jaccard"], 0.0)
        self.assertEqual(len(calls), 1)
        for path in self.output.rglob("*"):
            if path.is_file():
                self.assertNotIn(secret, path.read_text())

    def test_provider_fallback_and_known_usage_remain_visible(self):
        def transport(payload, key, timeout, max_response_bytes):
            return self.response(payload)

        compare(
            self.repo,
            "cancel callback",
            self.output,
            max_steps=3,
            challenger_factory=lambda: JevPolicy("fixture", max_calls=1, transport=transport),
        )
        accounting = self.summary()["arms"]["challenger"]["policy_accounting"]
        self.assertEqual(accounting["provider_attempts"], 1)
        self.assertEqual(accounting["fallback_decisions"], 2)
        self.assertEqual(accounting["backend_decisions"], {"jev": 1, "rule": 2})
        self.assertEqual(accounting["reported_input_tokens"], 5)
        self.assertEqual(accounting["reported_output_tokens"], 2)
        self.assertEqual(accounting["unknown_input_usage_attempts"], 0)

    def test_factory_is_called_once_per_comparison_with_fresh_policy_state(self):
        instances = []

        class CountingRule(RulePolicy):
            def __init__(self):
                self.calls = 0

            def choose(self, state, candidates):
                self.calls += 1
                return super().choose(state, candidates)

        def factory():
            policy = CountingRule()
            instances.append(policy)
            return policy

        compare(self.repo, "cancel callback", self.output, challenger_factory=factory)
        compare(
            self.repo,
            "cancel callback",
            self.workspace / "another-comparison",
            challenger_factory=factory,
        )
        self.assertEqual(len(instances), 2)
        self.assertIsNot(instances[0], instances[1])
        self.assertEqual([instance.calls for instance in instances], [3, 3])

    def test_custom_stopping_policy_has_no_executed_actions(self):
        class StopPolicy:
            def choose(self, state, candidates):
                return None

        compare(self.repo, "cancel callback", self.output, challenger_factory=StopPolicy)
        challenger = self.summary()["arms"]["challenger"]
        self.assertEqual(challenger["transport"], "custom")
        self.assertEqual(challenger["actions"], 0)
        self.assertEqual(challenger["action_candidate_ids"], [])
        self.assertEqual(challenger["stop_reason"], "policy_stopped")
        self.assertEqual(self.summary()["agreement"]["action_positions"], 3)

    def test_invalid_policy_choice_is_not_recorded_as_an_executed_action(self):
        class InvalidPolicy:
            def choose(self, state, candidates):
                return "execute-shell-command"

        compare(self.repo, "cancel callback", self.output, challenger_factory=InvalidPolicy)
        challenger = self.summary()["arms"]["challenger"]
        self.assertEqual(challenger["actions"], 0)
        self.assertEqual(challenger["action_candidate_ids"], [])
        self.assertEqual(challenger["stop_reason"], "invalid_policy_choice")

    def test_whole_timing_and_measurement_boundary_are_explicit(self):
        compare(self.repo, "cancel callback", self.output)
        summary = self.summary()
        timing = summary["timing"]
        measured_parts = timing["capture_elapsed_ms"] + sum(
            arm["elapsed_ms"] for arm in summary["arms"].values()
        )
        self.assertGreaterEqual(timing["whole_elapsed_ms"] + 0.01, measured_parts)
        self.assertIn(
            "excludes final comparison-summary publication", timing["measurement_boundary"]
        )
        report = (self.output / "report.md").read_text()
        self.assertIn("not evidence quality", report)
        self.assertIn("not a live-provider validation", report)
        self.assertIn("exclude unknown usage", report)

    def test_invalid_limits_and_task_fail_before_output_creation(self):
        invalid = (
            {"max_steps": 0},
            {"max_steps": True},
            {"max_steps": 1.5},
            {"max_context_chars": 0},
            {"max_context_chars": True},
        )
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    compare(self.repo, "cancel callback", self.output, **kwargs)
        with self.assertRaises(ValueError):
            compare(self.repo, " ", self.output)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
