"""Frozen follow-up inputs and comparisons across arm-local candidate IDs."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jev_scout.comparison import compare
from jev_scout.models import RulePolicy
from jev_scout.recovery import recover
from jev_scout.repository import SafeRepository


class SeedFirstPolicy(RulePolicy):
    """Choose both seeds, then one generated window in a controlled order."""

    def __init__(self, reverse=False, followup_path=None):
        self.reverse = reverse
        self.followup_path = followup_path
        self.initial_ids = None

    def choose(self, state, candidates):
        if self.initial_ids is None:
            self.initial_ids = tuple(candidate.id for candidate in candidates)
        seeds = [
            candidate
            for candidate in candidates
            if candidate.id in self.initial_ids and candidate.id not in state.seen_candidate_ids
        ]
        if seeds:
            ordered = sorted(seeds, key=lambda candidate: candidate.id, reverse=self.reverse)
            return ordered[0].id
        followups = [
            candidate
            for candidate in candidates
            if candidate.id not in state.seen_candidate_ids
            and (self.followup_path is None or candidate.args.path == self.followup_path)
        ]
        return min(followups, key=lambda candidate: candidate.id).id if followups else None


class AdaptiveComparisonTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.repo = self.workspace / "repo"
        self.repo.mkdir()
        self.output = self.workspace / "comparison"
        self.original = {}
        for index in range(2):
            name = f"source{index}.py"
            lines = [f"value_{line} = {index + line}\n" for line in range(1, 46)]
            lines[14] = f"def cancel_callback_{index}(): pass\n"
            text = "".join(lines)
            (self.repo / name).write_text(text, encoding="utf-8")
            self.original[name] = text

    def summary(self, output=None):
        return json.loads(((output or self.output) / "comparison.json").read_text())

    def bundle(self, arm):
        return json.loads((self.output / arm / "evidence.json").read_text())

    def test_default_keeps_the_fixed_frontier_and_offline_behavior(self):
        with patch("jev_scout.jev._post", side_effect=AssertionError("Network was used.")):
            compare(self.repo, "cancel callback", self.output)
        summary = self.summary()
        self.assertEqual(summary["schema_version"], 3)
        self.assertEqual(summary["snapshot"]["limits"]["max_followups"], 0)
        self.assertEqual(summary["snapshot"]["expansion"]["max_followups"], 0)
        self.assertEqual(summary["agreement"]["positional_action_agreement"], 1.0)
        for name in ("rule", "challenger"):
            arm = summary["arms"][name]
            self.assertEqual(arm["initial_candidate_count"], 2)
            self.assertEqual(arm["generated_candidate_count"], 0)
            self.assertEqual(arm["actions"], 2)
            self.assertFalse(arm["expansion"]["enabled"])
            self.assertEqual(arm["policy_accounting"]["provider_attempts"], 0)

    def test_same_local_id_for_different_generated_reads_does_not_match(self):
        with patch("jev_scout.comparison.RulePolicy", SeedFirstPolicy):
            compare(
                self.repo,
                "cancel callback",
                self.output,
                max_steps=3,
                challenger_factory=lambda: SeedFirstPolicy(reverse=True),
                max_followups=4,
            )
        summary = self.summary()
        baseline, challenger = summary["arms"]["rule"], summary["arms"]["challenger"]
        self.assertEqual(baseline["action_candidate_ids"][-1], "c0003")
        self.assertEqual(challenger["action_candidate_ids"][-1], "c0003")
        self.assertNotEqual(baseline["action_identities"][-1], challenger["action_identities"][-1])
        self.assertEqual(summary["agreement"]["matching_action_positions"], 0)
        self.assertEqual(summary["agreement"]["positional_action_agreement"], 0.0)
        self.assertEqual(summary["agreement"]["shared_observed_candidates"], 2)
        self.assertEqual(summary["agreement"]["distinct_observed_candidates"], 4)
        self.assertEqual(summary["agreement"]["observed_candidate_jaccard"], 0.5)

    def test_equivalent_generated_reads_match_despite_different_local_ids(self):
        with patch("jev_scout.comparison.RulePolicy", SeedFirstPolicy):
            compare(
                self.repo,
                "cancel callback",
                self.output,
                max_steps=3,
                challenger_factory=lambda: SeedFirstPolicy(
                    reverse=True, followup_path="source0.py"
                ),
                max_followups=4,
            )
        summary = self.summary()
        baseline, challenger = summary["arms"]["rule"], summary["arms"]["challenger"]
        self.assertEqual(baseline["action_candidate_ids"][-1], "c0003")
        self.assertEqual(challenger["action_candidate_ids"][-1], "c0005")
        self.assertEqual(baseline["action_identities"][-1], challenger["action_identities"][-1])
        self.assertEqual(summary["agreement"]["matching_action_positions"], 1)
        self.assertAlmostEqual(summary["agreement"]["positional_action_agreement"], 1 / 3)
        self.assertEqual(summary["agreement"]["observed_candidate_jaccard"], 1.0)
        self.assertFalse(summary["agreement"]["exact_action_sequence_match"])
        self.assertEqual(
            summary["agreement"]["identity_basis"],
            ["kind", "path", "expected_sha256", "start_line", "end_line", "max_chars"],
        )

    def test_frozen_followups_survive_checkout_changes_and_deletion(self):
        original_read = SafeRepository.read
        live_reads_after_factory = []
        challenger_started = False

        def read(repository, relative, max_bytes=None):
            if challenger_started:
                live_reads_after_factory.append(relative)
            return original_read(repository, relative, max_bytes)

        def factory():
            nonlocal challenger_started
            challenger_started = True
            (self.repo / "source0.py").write_text("def changed(): pass\n")
            (self.repo / "source1.py").unlink()
            return RulePolicy()

        with patch.object(SafeRepository, "read", read):
            compare(
                self.repo,
                "cancel callback",
                self.output,
                max_steps=6,
                challenger_factory=factory,
                max_followups=4,
            )
        first, second = self.bundle("rule"), self.bundle("challenger")
        self.assertEqual(first["candidates"], second["candidates"])
        self.assertEqual(first["observations"], second["observations"])
        self.assertEqual(
            first["generated_candidate_lineage"], second["generated_candidate_lineage"]
        )
        self.assertEqual(live_reads_after_factory, ["source0.py", "source1.py"])
        for observation in second["observations"]:
            lines = self.original[observation["path"]].splitlines(keepends=True)
            expected = "".join(lines[observation["start_line"] - 1 : observation["end_line"]])
            self.assertEqual(observation["text"], expected)
            self.assertEqual(observation["validity"], "matched_frozen_snapshot")
            self.assertIsNone(observation["current_sha256"])
        summary = self.summary()
        self.assertEqual(summary["arms"]["rule"]["generated_candidate_count"], 4)
        self.assertEqual(summary["arms"]["challenger"]["generated_candidate_count"], 4)
        self.assertEqual(
            summary["original_source_revalidation"]["status_counts"],
            {"current_at_final_check": 0, "changed": 1, "unavailable": 1},
        )

    def test_snapshot_identity_includes_generation_configuration(self):
        identities = []
        for maximum in (0, 1, 4):
            output = self.workspace / f"comparison-{maximum}"
            result = compare(self.repo, "cancel callback", output, max_followups=maximum)
            identities.append(result.snapshot_id)
            snapshot = self.summary(output)["snapshot"]
            self.assertEqual(
                snapshot["expansion"],
                {
                    "algorithm": "adjacent-lines-v1",
                    "window_lines": 9,
                    "max_followups": maximum,
                    "max_candidates": 100,
                },
            )
            self.assertEqual(len(snapshot["candidates"]), 2)
            self.assertEqual(len(snapshot["sources"]), 2)
            self.assertTrue(all("text" not in source for source in snapshot["sources"]))
        self.assertEqual(len(set(identities)), 3)

    def test_invalid_followup_budgets_fail_before_setup_or_factory(self):
        factory = Mock(side_effect=AssertionError("Policy was constructed."))
        for value in (-1, True, 1.5, None, 101):
            with self.subTest(value=value), patch.object(SafeRepository, "discover") as discover:
                with self.assertRaises(ValueError):
                    compare(
                        self.repo,
                        "cancel callback",
                        self.output,
                        challenger_factory=factory,
                        max_followups=value,
                    )
                discover.assert_not_called()
                factory.assert_not_called()
                self.assertFalse(self.output.exists())

    def test_generated_evidence_is_compatible_with_bounded_explicit_recovery(self):
        compare(self.repo, "cancel callback", self.output, max_steps=6, max_followups=4)
        bundle = self.bundle("rule")
        generated = {candidate["id"] for candidate in bundle["candidates"][2:]}
        observation = next(
            record for record in bundle["observations"] if record["candidate_id"] in generated
        )
        result = recover(
            self.output / "rule" / "evidence.json",
            self.repo,
            [observation["id"]],
            self.workspace / "recovered",
        )
        recovered = json.loads(result.recovery_path.read_text())
        self.assertEqual(result.recovered, 1)
        self.assertEqual(recovered["observations"][0]["text"], observation["text"])
        self.assertEqual(recovered["context"]["active"][0]["observation_id"], observation["id"])

    def test_total_candidate_cap_is_shared_and_exposed_in_each_arm(self):
        for index in range(2, 99):
            (self.repo / f"source{index:03}.py").write_text(self.original["source0.py"])
        compare(self.repo, "cancel callback", self.output, max_steps=2, max_followups=100)
        summary = self.summary()
        for name in ("rule", "challenger"):
            arm = summary["arms"][name]
            self.assertEqual(arm["initial_candidate_count"], 99)
            self.assertEqual(arm["generated_candidate_count"], 1)
            self.assertTrue(arm["expansion"]["candidate_limit_reached"])
            self.assertEqual(len(self.bundle(name)["candidates"]), 100)
        self.assertEqual(summary["snapshot"]["limits"]["max_candidates"], 100)

    def test_report_explains_dependent_menus_and_source_action_agreement(self):
        compare(self.repo, "cancel callback", self.output, max_followups=2)
        report = (self.output / "report.md").read_text()
        self.assertIn("initial candidate frontier", report)
        self.assertIn("Later candidate menus depend on each arm's preceding selections", report)
        self.assertIn("Candidate IDs are local", report)
        self.assertIn("expected source SHA-256", report)
        self.assertIn("not evidence quality", report)
        self.assertIn("not a full source archive", report)


if __name__ == "__main__":
    unittest.main()
