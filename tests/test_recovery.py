"""Recovery preserves historical evidence while checking imported source boundaries."""

import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jev_scout import investigate
from jev_scout.recovery import recover
from jev_scout.repository import SafeRepository


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.repo = self.workspace / "repo"
        self.repo.mkdir()
        self.alpha = self.repo / "alpha.cc"
        self.beta = self.repo / "beta.cc"
        self.alpha.write_text("void cancel_alpha() { cleanup(); }\n", encoding="utf-8")
        self.beta.write_text("void cancel_beta() { cleanup(); }\n", encoding="utf-8")
        self.run = self.workspace / "run"
        investigate(self.repo, "cancel", self.run, max_context_chars=20)
        self.evidence = self.run / "evidence.json"
        self.original = self.evidence.read_bytes()
        self.bundle = json.loads(self.original)
        self.output = self.workspace / "recovery"

    def write_bundle(self, bundle=None):
        self.evidence.write_text(json.dumps(bundle or self.bundle), encoding="utf-8")

    def read_recovery(self):
        return json.loads((self.output / "recovery.json").read_text(encoding="utf-8"))

    def events(self):
        return [
            json.loads(line) for line in (self.output / "events.jsonl").read_text().splitlines()
        ]

    def test_recovers_evicted_record_without_changing_inputs(self):
        before_source = self.alpha.read_bytes()
        self.assertIn("o0001", self.bundle["context"]["evicted_ids"])
        result = recover(self.evidence, self.repo, ["o0001"], self.output)
        recovered = self.read_recovery()
        self.assertEqual((result.requested, result.recovered), (1, 1))
        self.assertEqual(recovered["origin"]["sha256"], hashlib.sha256(self.original).hexdigest())
        self.assertEqual(
            recovered["observations"][0]["text"], self.bundle["observations"][0]["text"]
        )
        self.assertEqual(recovered["observations"][0]["validity"], "current_at_recovery_check")
        self.assertEqual(
            recovered["context"]["active"][0]["text"], self.bundle["observations"][0]["text"]
        )
        self.assertEqual(self.evidence.read_bytes(), self.original)
        self.assertEqual(self.alpha.read_bytes(), before_source)
        self.assertEqual(result.recovery_path, self.output.resolve() / "recovery.json")
        self.assertIn("not an investigation resume", result.report_path.read_text())
        self.assertEqual(self.events()[-1]["type"], "recovery_finished")

    def test_requested_order_fifo_budget_and_event_evidence_consistency(self):
        result = recover(self.evidence, self.repo, ["o0002", "o0001"], self.output, 8)
        recovered = self.read_recovery()
        self.assertEqual(result.recovered, 2)
        self.assertEqual([o["id"] for o in recovered["observations"]], ["o0002", "o0001"])
        self.assertEqual(recovered["context"]["evicted_ids"], ["o0002"])
        self.assertEqual(recovered["context"]["characters"], 8)
        self.assertEqual(
            recovered["context"]["active"],
            [{"observation_id": "o0001", "text": "void can", "truncated": True}],
        )
        recorded = [
            event["observation"]
            for event in self.events()
            if event["type"] == "historical_observation_recovered"
        ]
        self.assertEqual(recorded, recovered["observations"])
        self.assertTrue(any(event["type"] == "context_truncated" for event in self.events()))
        self.assertTrue(any(event["type"] == "context_evicted" for event in self.events()))

    def test_changed_and_deleted_sources_preserve_history_without_active_context(self):
        self.alpha.write_text("void changed_alpha() {}\n", encoding="utf-8")
        self.beta.unlink()
        current = self.alpha.read_bytes()
        result = recover(self.evidence, self.repo, ["o0001", "o0002"], self.output)
        recovered = self.read_recovery()
        self.assertEqual(result.recovered, 0)
        self.assertEqual(
            [o["validity"] for o in recovered["observations"]], ["changed", "unavailable"]
        )
        self.assertEqual(
            [o["text"] for o in recovered["observations"]],
            [o["text"] for o in self.bundle["observations"]],
        )
        self.assertEqual(recovered["context"]["active"], [])
        self.assertEqual(
            recovered["context"]["omitted"],
            [
                {"observation_id": "o0001", "reason": "changed"},
                {"observation_id": "o0002", "reason": "unavailable"},
            ],
        )
        self.assertEqual(self.alpha.read_bytes(), current)
        self.assertEqual(self.evidence.read_bytes(), self.original)

    def test_symlinked_source_does_not_read_external_content(self):
        outside = self.workspace / "outside.cc"
        outside.write_text("PRIVATE_REPLACEMENT", encoding="utf-8")
        self.alpha.unlink()
        self.alpha.symlink_to(outside)
        recover(self.evidence, self.repo, ["o0001"], self.output)
        self.assertEqual(self.read_recovery()["observations"][0]["validity"], "unavailable")
        self.assertNotIn("PRIVATE_REPLACEMENT", (self.output / "recovery.json").read_text())

    def test_artifact_repository_and_unknown_fields_are_inert(self):
        self.bundle["repo"] = str(self.workspace / "private_repository")
        self.bundle["observations"][0]["instructions"] = "DO_NOT_COPY_PRIVATE_FIELD"
        self.bundle["decisions"] = [{"command": "DO_NOT_COPY_PRIVATE_FIELD"}]
        self.write_bundle()
        recover(self.evidence, self.repo, ["o0001"], self.output)
        recovered = self.read_recovery()
        self.assertEqual(recovered["repo"], str(self.repo.resolve()))
        self.assertEqual(recovered["observations"][0]["validity"], "current_at_recovery_check")
        self.assertNotIn("DO_NOT_COPY_PRIVATE_FIELD", (self.output / "recovery.json").read_text())

    def test_all_delivered_investigation_schemas_are_supported(self):
        for version in (1, 2, 3):
            with self.subTest(version=version):
                self.bundle["schema_version"] = version
                self.write_bundle()
                output = self.workspace / f"schema{version}"
                result = recover(self.evidence, self.repo, ["o0001"], output)
                self.assertEqual(result.recovered, 1)

    def test_frozen_comparison_record_is_checked_against_explicit_live_source(self):
        self.bundle["source_mode"] = "frozen"
        self.bundle["snapshot_id"] = "a" * 64
        observation = self.bundle["observations"][0]
        observation["validity"] = "matched_frozen_snapshot"
        observation["current_sha256"] = None
        observation["checked_snapshot_sha256"] = observation["source_sha256"]
        self.write_bundle()
        result = recover(self.evidence, self.repo, ["o0001"], self.output)
        recovered = self.read_recovery()["observations"][0]
        self.assertEqual(result.recovered, 1)
        self.assertEqual(recovered["original_validity"], "matched_frozen_snapshot")
        self.assertIsNone(recovered["original_current_sha256"])
        self.assertEqual(recovered["validity"], "current_at_recovery_check")
        self.assertEqual(recovered["current_sha256"], observation["source_sha256"])
        self.alpha.write_text("void changed_since_snapshot() {}\n", encoding="utf-8")
        changed = recover(self.evidence, self.repo, ["o0001"], self.workspace / "changed")
        changed_bundle = json.loads(changed.recovery_path.read_text())
        self.assertEqual(changed.recovered, 0)
        self.assertEqual(changed_bundle["observations"][0]["validity"], "changed")
        self.assertEqual(changed_bundle["observations"][0]["text"], observation["text"])
        self.assertEqual(changed_bundle["context"]["active"], [])

    def test_forged_text_span_or_truncation_cannot_claim_freshness(self):
        cases = (
            {"text": "INJECTED_OBSERVATION"},
            {"start_line": 2, "end_line": 2},
            {"excerpt_truncated": True},
        )
        for index, changes in enumerate(cases):
            with self.subTest(changes=changes):
                bundle = json.loads(self.original)
                bundle["observations"][0].update(changes)
                self.write_bundle(bundle)
                output = self.workspace / f"mismatch{index}"
                result = recover(self.evidence, self.repo, ["o0001"], output)
                recovery = json.loads(result.recovery_path.read_text())
                self.assertEqual(result.recovered, 0)
                self.assertEqual(recovery["observations"][0]["validity"], "excerpt_mismatch")
                self.assertEqual(recovery["context"]["active"], [])

    def test_markdown_excerpt_uses_fence_longer_than_source_backticks(self):
        self.alpha.write_text("void cancel_alpha() { /* ````` */ }\n", encoding="utf-8")
        run = self.workspace / "backtick_run"
        investigate(self.repo, "cancel_alpha", run, max_steps=1)
        result = recover(run / "evidence.json", self.repo, ["o0001"], self.output)
        self.assertIn("``````text", result.report_path.read_text())

    def test_unsafe_paths_are_rejected_before_any_source_read_or_output(self):
        paths = (
            "../private.cc",
            "/tmp/private.cc",
            "..\\private.cc",
            "./alpha.cc",
            "a//b.cc",
            "alpha.cc\n",
            ".env",
            ".aws/credentials",
            "vendor/source.cc",
            "node_modules/source.js",
            ".git/config",
        )
        for source_path in paths:
            with self.subTest(path=source_path):
                bundle = json.loads(self.original)
                bundle["observations"][0]["path"] = source_path
                self.write_bundle(bundle)
                with patch.object(
                    SafeRepository, "read", side_effect=AssertionError("Unexpected source read")
                ):
                    with self.assertRaises(ValueError):
                        recover(self.evidence, self.repo, ["o0001"], self.output)
                self.assertFalse(self.output.exists())

    def test_duplicate_or_unknown_requested_ids_fail_before_source_reads(self):
        for identifiers in ([], ["o0001", "o0001"], ["o9999"], "o0001", [True]):
            with self.subTest(identifiers=identifiers):
                with patch.object(
                    SafeRepository, "read", side_effect=AssertionError("Unexpected source read")
                ):
                    with self.assertRaises(ValueError):
                        recover(self.evidence, self.repo, identifiers, self.output)
                self.assertFalse(self.output.exists())

    def test_invalid_observation_fields_are_rejected_before_output(self):
        cases = (
            {"id": "o0000"},
            {"kind": "command"},
            {"start_line": True},
            {"end_line": 0},
            {"end_line": 10**20},
            {"source_sha256": "not-a-hash"},
            {"text": "x" * 4001},
            {"text": "\ud800"},
            {"excerpt_truncated": 0},
            {"candidate_id": "../../bad"},
            {"current_sha256": 1},
            {"validity": []},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                bundle = json.loads(self.original)
                bundle["observations"][0].update(changes)
                self.write_bundle(bundle)
                with self.assertRaises(ValueError):
                    recover(self.evidence, self.repo, ["o0001"], self.output)
                self.assertFalse(self.output.exists())

    def test_schema_and_duplicate_observation_ids_are_rejected(self):
        for version in (True, 0, 4, "2"):
            with self.subTest(version=version):
                bundle = json.loads(self.original)
                bundle["schema_version"] = version
                self.write_bundle(bundle)
                with self.assertRaises(ValueError):
                    recover(self.evidence, self.repo, ["o0001"], self.output)
        bundle = json.loads(self.original)
        bundle["observations"][1]["id"] = "o0001"
        self.write_bundle(bundle)
        with self.assertRaises(ValueError):
            recover(self.evidence, self.repo, ["o0001"], self.output)
        self.assertFalse(self.output.exists())

    def test_json_import_rejects_malformed_duplicate_nonfinite_and_deep_inputs(self):
        payloads = (
            b"\xff",
            b"{",
            b"[]",
            b'{"schema_version":2,"schema_version":1}',
            b'{"x":NaN}',
            b'{"x":Infinity}',
            b"[" * 2000 + b"0" + b"]" * 2000,
        )
        for payload in payloads:
            with self.subTest(payload=payload[:60]):
                self.evidence.write_bytes(payload)
                with self.assertRaises(ValueError):
                    recover(self.evidence, self.repo, ["o0001"], self.output)
                self.assertFalse(self.output.exists())

    def test_import_byte_limit_bounds_reads_even_if_stat_underreports_size(self):
        fake_stat = SimpleNamespace(st_mode=stat.S_IFREG, st_size=1, st_mtime_ns=0)
        with patch("jev_scout.recovery.MAX_IMPORT_BYTES", 128):
            with patch("jev_scout.recovery.os.fstat", return_value=fake_stat):
                with self.assertRaisesRegex(ValueError, "byte limit"):
                    recover(self.evidence, self.repo, ["o0001"], self.output)
        self.assertFalse(self.output.exists())

    def test_nonregular_and_symlink_input_fail_without_blocking(self):
        link = self.workspace / "linked.json"
        link.symlink_to(self.evidence)
        fifo = self.workspace / "fifo.json"
        os.mkfifo(fifo)
        for evidence in (link, fifo, self.run):
            with self.subTest(evidence=evidence), self.assertRaises((ValueError, OSError)):
                recover(evidence, self.repo, ["o0001"], self.output)
        self.assertFalse(self.output.exists())

    def test_output_conflicts_and_repository_paths_do_not_overwrite_inputs(self):
        with self.assertRaises(ValueError):
            recover(self.evidence, self.repo, ["o0001"], self.repo / "recovery")
        self.assertFalse((self.repo / "recovery").exists())
        result = recover(self.evidence, self.repo, ["o0001"], self.output)
        initial = result.recovery_path.read_bytes()
        with self.assertRaises(ValueError):
            recover(self.evidence, self.repo, ["o0001"], self.output)
        self.assertEqual(result.recovery_path.read_bytes(), initial)
        self.assertEqual(self.evidence.read_bytes(), self.original)

    def test_context_budget_and_observation_count_are_bounded(self):
        for budget in (0, -1, True, 1.5):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                recover(self.evidence, self.repo, ["o0001"], self.output, budget)
        self.bundle["observations"] *= 51
        self.write_bundle()
        with self.assertRaisesRegex(ValueError, "bounded list"):
            recover(self.evidence, self.repo, ["o0001"], self.output)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
