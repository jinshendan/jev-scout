"""Bounds and provenance for runtime-generated same-file snippet follow-ups."""

import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jev_scout.expansion import (
    EXPANSION_ALGORITHM,
    FOLLOWUP_LINES,
    FollowupFrontier,
    validate_max_followups,
)
from jev_scout.models import ActionCandidate, ReadSnippetArgs
from jev_scout.repository import MAX_CANDIDATES, SourceFile


class ExpansionTests(unittest.TestCase):
    @staticmethod
    def source(lines=36):
        text = "".join(f"source line {index}\n" for index in range(1, lines + 1))
        raw = text.encode()
        return SourceFile(text, hashlib.sha256(raw).hexdigest(), len(raw))

    @staticmethod
    def candidate(source, start=10, end=18, *, candidate_id="c0001", score=80, max_chars=4000):
        return ActionCandidate(
            candidate_id,
            "read_snippet",
            ReadSnippetArgs("src/source.py", start, end, source.sha256, max_chars),
            score,
            ("Initial lexical match",),
            "initial preview",
        )

    def test_budget_validation_rejects_bool_non_integer_and_out_of_range(self):
        for value in (False, True, None, "1", 1.0, -1, MAX_CANDIDATES + 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_max_followups(value)
        for value in (0, 1, MAX_CANDIDATES):
            validate_max_followups(value)

    def test_default_disabled_expansion_does_not_mutate_state(self):
        source = self.source()
        parent = self.candidate(source)
        frontier = FollowupFrontier([parent])
        before = frontier.describe()
        self.assertEqual(frontier.expand(parent, source, "o0001"), ())
        self.assertEqual(frontier.describe(), before)
        self.assertEqual(frontier.lineage, [])
        self.assertFalse(before["enabled"])
        self.assertFalse(before["followup_limit_reached"])

    def test_neighbors_preserve_source_contract_and_record_lineage(self):
        source = self.source()
        parent = self.candidate(source, max_chars=123)
        frontier = FollowupFrontier([parent], 4)
        derived = frontier.expand(parent, source, "o0001")
        self.assertEqual([item.direction for item in derived], ["before", "after"])
        self.assertEqual([item.candidate.id for item in derived], ["c0002", "c0003"])
        self.assertEqual(
            [(item.candidate.args.start_line, item.candidate.args.end_line) for item in derived],
            [(1, 9), (19, 27)],
        )
        for item in derived:
            self.assertEqual(item.candidate.kind, "read_snippet")
            self.assertEqual(item.candidate.args.path, parent.args.path)
            self.assertEqual(item.candidate.args.expected_sha256, source.sha256)
            self.assertEqual(item.candidate.args.max_chars, 123)
            self.assertEqual(item.candidate.score, 79)
            self.assertIn(item.direction, item.candidate.reasons[0])
            self.assertEqual(item.parent_candidate_id, "c0001")
            self.assertEqual(item.parent_observation_id, "o0001")
            self.assertEqual(
                item.to_dict(),
                {
                    "candidate_id": item.candidate.id,
                    "parent_candidate_id": "c0001",
                    "parent_observation_id": "o0001",
                    "direction": item.direction,
                },
            )
            self.assertEqual(
                item.candidate.preview,
                "".join(
                    source.text.splitlines(keepends=True)[
                        item.candidate.args.start_line - 1 : item.candidate.args.end_line
                    ]
                )[:240],
            )
        self.assertEqual(frontier.lineage, list(derived))
        self.assertEqual(frontier.describe()["algorithm"], EXPANSION_ALGORITHM)
        self.assertEqual(frontier.describe()["window_lines"], FOLLOWUP_LINES)

    def test_short_boundary_windows_never_overlap_or_escape_parent(self):
        source = self.source(15)
        parent = self.candidate(source, 4, 12)
        frontier = FollowupFrontier([parent], 5)
        derived = frontier.expand(parent, source, "o0001")
        self.assertEqual(
            [(item.candidate.args.start_line, item.candidate.args.end_line) for item in derived],
            [(1, 3), (13, 15)],
        )
        for index, item in enumerate(derived, 2):
            self.assertEqual(frontier.expand(item.candidate, source, f"o{index:04}"), ())
        self.assertEqual(frontier.describe()["generated_candidates"], 2)
        self.assertEqual(frontier.describe()["suppressed_proposals"], 0)

    def test_start_and_end_of_file_have_only_one_neighbor(self):
        source = self.source(27)
        for start, end, direction, span in (
            (1, 9, "after", (10, 18)),
            (19, 27, "before", (10, 18)),
        ):
            with self.subTest(start=start):
                parent = self.candidate(source, start, end)
                added = FollowupFrontier([parent], 3).expand(parent, source, "o0001")
                self.assertEqual(len(added), 1)
                self.assertEqual(added[0].direction, direction)
                self.assertEqual(
                    (added[0].candidate.args.start_line, added[0].candidate.args.end_line), span
                )

    def test_seed_and_generated_spans_are_deduplicated(self):
        source = self.source()
        parent = self.candidate(source)
        before = self.candidate(source, 1, 9, candidate_id="c0002")
        after = self.candidate(source, 19, 27, candidate_id="c0003")
        frontier = FollowupFrontier([parent, before, after], 5)
        self.assertEqual(frontier.expand(parent, source, "o0001"), ())
        added = frontier.expand(after, source, "o0002")
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].candidate.args.start_line, 28)
        self.assertEqual(frontier.expand(added[0].candidate, source, "o0003"), ())
        self.assertEqual(frontier.describe()["generated_candidates"], 1)
        self.assertEqual(frontier.describe()["suppressed_proposals"], 0)

    def test_repeated_parent_calls_do_not_duplicate_candidates_or_suppression(self):
        source = self.source()
        parent = self.candidate(source)
        frontier = FollowupFrontier([parent], 1)
        first = frontier.expand(parent, source, "o0001")
        self.assertEqual(len(first), 1)
        before = frontier.describe()
        self.assertEqual(frontier.expand(parent, source, "o0002"), ())
        self.assertEqual(frontier.describe(), before)
        self.assertEqual(before["suppressed_proposals"], 1)
        self.assertEqual(before["followup_limit_suppressed_proposals"], 1)

    def test_hash_mismatch_does_not_consume_parent_or_capacity(self):
        source = self.source()
        parent = self.candidate(source)
        frontier = FollowupFrontier([parent], 2)
        before = frontier.describe()
        changed = SourceFile(source.text, "f" * 64, source.byte_size)
        self.assertEqual(frontier.expand(parent, changed, "o0001"), ())
        self.assertEqual(frontier.describe(), before)
        self.assertEqual(len(frontier.expand(parent, source, "o0002")), 2)

    def test_unregistered_or_modified_parent_cannot_introduce_a_source(self):
        source = self.source()
        parent = self.candidate(source)
        frontier = FollowupFrontier([parent], 2)
        unknown = self.candidate(source, candidate_id="c0999")
        modified = self.candidate(source, 2, 9)
        before = frontier.describe()
        for candidate in (unknown, modified):
            self.assertEqual(frontier.expand(candidate, source, "o0001"), ())
            self.assertEqual(frontier.describe(), before)

    def test_followup_cap_is_separate_from_global_frontier_cap(self):
        source = self.source()
        parent = self.candidate(source)
        frontier = FollowupFrontier([parent], 1)
        self.assertEqual(len(frontier.expand(parent, source, "o0001")), 1)
        summary = frontier.describe()
        self.assertTrue(summary["followup_limit_reached"])
        self.assertFalse(summary["candidate_limit_reached"])
        self.assertEqual(summary["candidate_limit_suppressed_proposals"], 0)
        self.assertEqual(summary["followup_limit_suppressed_proposals"], 1)

    def test_full_initial_frontier_reports_unique_suppressed_proposals(self):
        source = self.source()
        seeds = [
            self.candidate(source, candidate_id=f"c{index:04}")
            for index in range(1, MAX_CANDIDATES + 1)
        ]
        frontier = FollowupFrontier(seeds, 3)
        before = frontier.describe()
        self.assertTrue(before["candidate_limit_reached"])
        self.assertEqual(before["suppressed_proposals"], 0)
        for index, parent in enumerate(seeds, 1):
            self.assertEqual(frontier.expand(parent, source, f"o{index:04}"), ())
        after = frontier.describe()
        self.assertEqual(after["generated_candidates"], 0)
        self.assertEqual(after["suppressed_proposals"], 2)
        self.assertEqual(after["candidate_limit_suppressed_proposals"], 2)
        self.assertFalse(after["followup_limit_reached"])

    def test_last_global_slot_is_used_once_even_when_followup_budget_remains(self):
        source = self.source()
        seeds = [
            self.candidate(source, candidate_id=f"c{index:04}")
            for index in range(1, MAX_CANDIDATES)
        ]
        frontier = FollowupFrontier(seeds, MAX_CANDIDATES)
        added = frontier.expand(seeds[0], source, "o0001")
        self.assertEqual([item.candidate.id for item in added], ["c0100"])
        self.assertEqual(frontier.describe()["suppressed_proposals"], 1)
        self.assertTrue(frontier.describe()["candidate_limit_reached"])
        self.assertFalse(frontier.describe()["followup_limit_reached"])

    def test_long_exploration_cannot_exceed_the_global_candidate_cap(self):
        source = self.source(1800)
        seeds = [self.candidate(source, 900, 908)]
        frontier = FollowupFrontier(seeds, MAX_CANDIDATES)
        queue = seeds.copy()
        index = 0
        while index < len(queue):
            added = frontier.expand(queue[index], source, f"o{index + 1:04}")
            queue.extend(item.candidate for item in added)
            index += 1
        self.assertEqual(len(queue), MAX_CANDIDATES)
        self.assertEqual(len(frontier.lineage), MAX_CANDIDATES - 1)
        self.assertTrue(frontier.describe()["candidate_limit_reached"])
        self.assertGreater(frontier.describe()["suppressed_proposals"], 0)
        self.assertEqual(len({candidate.id for candidate in queue}), MAX_CANDIDATES)

    def test_noncontiguous_existing_ids_do_not_collide_with_followups(self):
        source = self.source()
        first = self.candidate(source)
        second = self.candidate(source, 19, 27, candidate_id="c0003")
        frontier = FollowupFrontier([first, second], 2)
        added = frontier.expand(first, source, "o0001")
        self.assertEqual([item.candidate.id for item in added], ["c0004"])

    def test_score_floor_and_long_line_preview_preserve_character_caps(self):
        text = "first\n" + "x" * 10000 + "\nlast\n"
        raw = text.encode()
        source = SourceFile(text, hashlib.sha256(raw).hexdigest(), len(raw))
        parent = self.candidate(source, 1, 1, score=0, max_chars=37)
        added = FollowupFrontier([parent], 1).expand(parent, source, "o0001")
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].candidate.score, 0)
        self.assertEqual(added[0].candidate.args.max_chars, 37)
        self.assertEqual(added[0].candidate.preview, "x" * 240)

    def test_empty_and_invalid_spans_cannot_create_actions(self):
        empty = self.source(0)
        parent = self.candidate(empty, 1, 1)
        frontier = FollowupFrontier([parent], 3)
        before = frontier.describe()
        self.assertEqual(frontier.expand(parent, empty, "o0001"), ())
        self.assertEqual(frontier.describe(), before)
        source = self.source()
        for start, end in ((0, 2), (10, 9), (35, 40)):
            with self.subTest(start=start, end=end):
                invalid = self.candidate(source, start, end)
                invalid_frontier = FollowupFrontier([invalid], 3)
                before = invalid_frontier.describe()
                self.assertEqual(invalid_frontier.expand(invalid, source, "o0001"), ())
                self.assertEqual(invalid_frontier.describe(), before)

    def test_constructor_rejects_overfull_frontier_and_duplicate_ids(self):
        source = self.source()
        parent = self.candidate(source)
        with self.assertRaises(ValueError):
            FollowupFrontier([parent, parent], 1)
        with self.assertRaises(ValueError):
            FollowupFrontier(
                [
                    self.candidate(source, candidate_id=f"c{index:04}")
                    for index in range(1, MAX_CANDIDATES + 2)
                ],
                1,
            )


if __name__ == "__main__":
    unittest.main()
