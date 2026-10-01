"""Frozen restoration inputs, action identities, and bounded comparison accounting."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jev_scout.comparison import _action_identity, _agreement, compare
from jev_scout.models import RulePolicy
from jev_scout.repository import SafeRepository


class OrderedReadRestorePolicy(RulePolicy):
    """Read three sources in a specified order, then restore one specified path."""

    def __init__(self, order=("source0.py", "source1.py", "source2.py"), target="source0.py"):
        self.order = order
        self.target = target

    def choose(self, state, candidates):
        available = [
            candidate for candidate in candidates if candidate.id not in state.seen_candidate_ids
        ]
        for path in self.order:
            read = next(
                (
                    candidate
                    for candidate in available
                    if candidate.kind == "read_snippet" and candidate.args.path == path
                ),
                None,
            )
            if read is not None:
                return read.id
        restoration = next(
            (
                candidate
                for candidate in available
                if candidate.kind == "restore_observation" and candidate.args.path == self.target
            ),
            None,
        )
        return restoration.id if restoration is not None else None


class RestorationComparisonTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.repo = self.workspace / "repo"
        self.repo.mkdir()
        self.output = self.workspace / "comparison"
        self.original = {}
        for index in range(3):
            name = f"source{index}.py"
            text = f"def cancel_callback_{index}():\n    return {index}\n"
            (self.repo / name).write_text(text, encoding="utf-8")
            self.original[name] = text

    def summary(self, output=None):
        return json.loads(((output or self.output) / "comparison.json").read_text())

    def bundle(self, arm):
        return json.loads((self.output / arm / "evidence.json").read_text())

    def test_default_remains_offline_without_restore_candidates_or_actions(self):
        with patch("jev_scout.jev._post", side_effect=AssertionError("Network was used.")):
            compare(self.repo, "cancel callback", self.output, max_context_chars=20)
        summary = self.summary()
        self.assertEqual(summary["schema_version"], 3)
        self.assertEqual(summary["snapshot"]["limits"]["max_restores"], 0)
        self.assertEqual(summary["snapshot"]["restoration"]["max_restores"], 0)
        self.assertTrue(summary["agreement"]["exact_action_sequence_match"])
        for name in ("rule", "challenger"):
            arm = summary["arms"][name]
            self.assertFalse(arm["restoration"]["enabled"])
            self.assertEqual(arm["generated_restore_candidate_count"], 0)
            self.assertEqual(arm["action_counts"], {"read_snippet": 3, "restore_observation": 0})
            self.assertEqual(arm["successful_restores"], 0)
            self.assertEqual(arm["restoration_checks"], [])
            self.assertEqual(arm["policy_accounting"]["provider_attempts"], 0)

    def test_same_restored_source_matches_despite_different_local_observation_ids(self):
        with patch("jev_scout.comparison.RulePolicy", OrderedReadRestorePolicy):
            compare(
                self.repo,
                "cancel callback",
                self.output,
                max_steps=4,
                max_context_chars=20,
                max_restores=4,
                challenger_factory=lambda: OrderedReadRestorePolicy(
                    order=("source1.py", "source0.py", "source2.py")
                ),
            )
        summary = self.summary()
        first, second = summary["arms"]["rule"], summary["arms"]["challenger"]
        self.assertEqual(first["restoration_checks"][0]["observation_id"], "o0001")
        self.assertEqual(second["restoration_checks"][0]["observation_id"], "o0002")
        self.assertNotEqual(first["action_candidate_ids"][-1], second["action_candidate_ids"][-1])
        self.assertEqual(first["action_identities"][-1], second["action_identities"][-1])
        self.assertEqual(first["action_identities"][-1]["kind"], "restore_observation")
        self.assertNotIn("observation_id", first["action_identities"][-1])
        self.assertEqual(summary["agreement"]["matching_action_positions"], 2)
        self.assertEqual(summary["agreement"]["positional_action_agreement"], 0.5)
        self.assertEqual(summary["agreement"]["observed_candidate_jaccard"], 1.0)
        self.assertEqual(summary["agreement"]["distinct_observed_candidates"], 3)
        for arm in (first, second):
            self.assertEqual(arm["actions"], 4)
            self.assertEqual(arm["action_counts"], {"read_snippet": 3, "restore_observation": 1})
            self.assertEqual(arm["successful_restores"], 1)
            self.assertEqual(arm["observations"], 3)
            self.assertEqual(arm["generated_candidate_count"], 0)
            self.assertEqual(arm["generated_followup_candidate_count"], 0)
            self.assertGreater(arm["generated_restore_candidate_count"], 0)
            self.assertEqual(
                arm["total_candidate_count"],
                arm["initial_candidate_count"] + arm["generated_restore_candidate_count"],
            )

    def test_read_and_restore_actions_are_distinct_but_targets_ignore_local_ids(self):
        args = {
            "path": "source0.py",
            "expected_sha256": "a" * 64,
            "start_line": 1,
            "end_line": 2,
            "max_chars": 4000,
        }
        read = _action_identity({"kind": "read_snippet", "args": args})
        first_restore = _action_identity(
            {"kind": "restore_observation", "args": {**args, "observation_id": "o0001"}}
        )
        second_restore = _action_identity(
            {"kind": "restore_observation", "args": {**args, "observation_id": "o0002"}}
        )
        self.assertEqual(first_restore, second_restore)
        self.assertNotEqual(read, first_restore)
        agreement = _agreement(
            {"action_identities": [read], "observed_action_identities": [read]},
            {"action_identities": [second_restore], "observed_action_identities": [read]},
        )
        self.assertEqual(agreement["positional_action_agreement"], 0.0)
        self.assertEqual(agreement["observed_candidate_jaccard"], 1.0)

    def test_frozen_restoration_survives_checkout_mutation_and_deletion(self):
        original_read = SafeRepository.read
        reads_after_factory = []
        challenger_started = False

        def read(repository, relative, max_bytes=None):
            if challenger_started:
                reads_after_factory.append(relative)
            return original_read(repository, relative, max_bytes)

        def factory():
            nonlocal challenger_started
            challenger_started = True
            (self.repo / "source0.py").write_text("def changed(): pass\n")
            (self.repo / "source1.py").unlink()
            return OrderedReadRestorePolicy()

        with (
            patch.object(SafeRepository, "read", read),
            patch("jev_scout.comparison.RulePolicy", OrderedReadRestorePolicy),
        ):
            compare(
                self.repo,
                "cancel callback",
                self.output,
                max_steps=4,
                max_context_chars=20,
                challenger_factory=factory,
                max_restores=3,
            )
        first, second = self.bundle("rule"), self.bundle("challenger")
        self.assertEqual(first["observations"], second["observations"])
        self.assertEqual(first["restoration_checks"], second["restoration_checks"])
        self.assertEqual(reads_after_factory, ["source0.py", "source1.py", "source2.py"])
        for bundle in (first, second):
            self.assertEqual(len(bundle["observations"]), 3)
            self.assertEqual(bundle["context"]["active"][0]["observation_id"], "o0001")
            self.assertEqual(
                bundle["context"]["active"][0]["text"], self.original["source0.py"][:20]
            )
            check = bundle["restoration_checks"][0]
            self.assertEqual(check["validity"], "matched_frozen_snapshot")
            self.assertEqual(check["outcome"], "restored")
            self.assertEqual(check["source_mode"], "frozen")
            self.assertIsNone(check["current_sha256"])
            self.assertEqual(
                check["checked_snapshot_sha256"], bundle["observations"][0]["source_sha256"]
            )
        summary = self.summary()
        self.assertEqual(
            summary["original_source_revalidation"]["status_counts"],
            {"current_at_final_check": 1, "changed": 1, "unavailable": 1},
        )
        self.assertTrue(summary["agreement"]["exact_action_sequence_match"])

    def test_snapshot_identity_includes_restoration_configuration(self):
        identities = []
        for maximum in (0, 1, 4):
            output = self.workspace / f"restore-{maximum}"
            result = compare(self.repo, "cancel callback", output, max_restores=maximum)
            identities.append(result.snapshot_id)
            snapshot = self.summary(output)["snapshot"]
            self.assertEqual(snapshot["limits"]["max_restores"], maximum)
            self.assertEqual(
                snapshot["restoration"],
                {
                    "algorithm": "evicted-observations-v1",
                    "max_restores": maximum,
                    "max_candidates": 100,
                },
            )
        self.assertEqual(len(set(identities)), 3)

    def test_invalid_restore_limits_fail_before_outputs_discovery_or_factory(self):
        factory = Mock(side_effect=AssertionError("Policy was constructed."))
        for value in (-1, True, 1.5, None, 101):
            with self.subTest(value=value), patch.object(SafeRepository, "discover") as discover:
                with self.assertRaises(ValueError):
                    compare(
                        self.repo,
                        "cancel callback",
                        self.output,
                        challenger_factory=factory,
                        max_restores=value,
                    )
                discover.assert_not_called()
                factory.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_restore_menu_and_selected_actions_have_separate_budget_accounting(self):
        with patch("jev_scout.comparison.RulePolicy", OrderedReadRestorePolicy):
            compare(
                self.repo,
                "cancel callback",
                self.output,
                max_steps=2,
                max_context_chars=20,
                max_restores=1,
                challenger_factory=OrderedReadRestorePolicy,
            )
        for arm in self.summary()["arms"].values():
            self.assertEqual(arm["generated_restore_candidate_count"], 1)
            self.assertEqual(arm["action_counts"], {"read_snippet": 2, "restore_observation": 0})
            self.assertEqual(arm["successful_restores"], 0)
            self.assertEqual(arm["stop_reason"], "step_budget_exhausted")
            self.assertLessEqual(arm["active_context_chars"], 20)

    def test_report_explains_restore_semantics_and_observation_overlap(self):
        compare(self.repo, "cancel callback", self.output, max_restores=2)
        report = (self.output / "report.md").read_text()
        self.assertIn("same frozen capture", report)
        self.assertIn("does not reopen the original checkout", report)
        self.assertIn("quota counts offered actions", report)
        self.assertIn("observation IDs are also local trace references", report)
        self.assertIn("Reads and restores remain distinct actions", report)
        self.assertIn("original read observations once", report)
        self.assertIn("Successful restores", report)


if __name__ == "__main__":
    unittest.main()
