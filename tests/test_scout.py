"""Meaningful source-boundary, provenance, policy, and budget checks."""

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

from jev_scout import investigate
from jev_scout.cli import main
from jev_scout.repository import MAX_FILE_BYTES, SafeRepository, SkippedFile


class ScoutTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.repo = self.workspace / "repo"
        self.repo.mkdir()
        self.output = self.workspace / "results"

    def source(self, path, text):
        destination = self.repo / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
        return destination

    def bundle(self, output=None):
        return json.loads(((output or self.output) / "evidence.json").read_text())

    def events(self):
        return [
            json.loads(line) for line in (self.output / "events.jsonl").read_text().splitlines()
        ]

    def test_localizes_demo_and_records_source_hash(self):
        text = "void Request::cancel() {\n    cancelled_ = true;\n}\n"
        self.source("src/request.cc", text)
        self.source("src/unrelated.cc", "int calculate_tax() { return 1; }\n")
        result = investigate(self.repo, "Request cancel callback lifetime", self.output)
        bundle = self.bundle()
        observation = bundle["observations"][0]
        self.assertEqual(observation["path"], "src/request.cc")
        self.assertEqual(observation["source_sha256"], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(observation["validity"], "current_at_final_check")
        self.assertEqual(observation["kind"], "observation")
        self.assertEqual(result.stop_reason, "candidates_exhausted")
        args = bundle["candidates"][0]["args"]
        self.assertEqual(args["expected_sha256"], observation["source_sha256"])
        self.assertGreaterEqual(args["start_line"], 1)
        self.assertIn("not a root-cause diagnosis", result.report_path.read_text())
        self.assertEqual(self.events()[-1]["type"], "investigation_finished")

    def test_step_budget_preserves_deferred_candidates(self):
        for name in ("alpha.cc", "beta.cc", "gamma.cc"):
            self.source(name, "void cancel_request() {}\n")
        result = investigate(self.repo, "cancel request", self.output, max_steps=1)
        bundle = self.bundle()
        self.assertEqual(result.steps, 1)
        self.assertEqual(result.stop_reason, "step_budget_exhausted")
        self.assertEqual(len(bundle["observations"]), 1)
        self.assertEqual(len(bundle["deferred_candidate_ids"]), 2)

    def test_context_eviction_preserves_raw_evidence(self):
        self.source("alpha.cc", "void cancel_alpha() { cleanup(); }\n")
        self.source("beta.cc", "void cancel_beta() { cleanup(); }\n")
        investigate(self.repo, "cancel", self.output, max_context_chars=38)
        bundle = self.bundle()
        self.assertEqual(len(bundle["observations"]), 2)
        self.assertLessEqual(bundle["context"]["characters"], 38)
        self.assertEqual(len(bundle["context"]["active"]), 1)
        self.assertEqual(bundle["context"]["evicted_ids"], ["o0001"])
        raw = [
            event["observation"]
            for event in self.events()
            if event["type"] == "observation_recorded"
        ]
        self.assertEqual([o["text"] for o in raw], [o["text"] for o in bundle["observations"]])
        self.assertTrue(any(event["type"] == "context_evicted" for event in self.events()))

    def test_context_truncation_does_not_truncate_raw_observation(self):
        self.source("cancel.cc", "void cancel() { release_pending_callback(); }\n")
        investigate(self.repo, "cancel", self.output, max_context_chars=8)
        bundle = self.bundle()
        self.assertEqual(bundle["context"]["characters"], 8)
        self.assertTrue(bundle["context"]["active"][0]["truncated"])
        self.assertGreater(len(bundle["observations"][0]["text"]), 8)
        self.assertTrue(any(event["type"] == "context_truncated" for event in self.events()))

    def test_excludes_secrets_dependencies_binary_large_files_and_symlinks(self):
        self.source("safe.cc", "void cancel_safe() {}\n")
        for name in (
            ".env",
            ".env.production",
            ".git/config",
            "node_modules/dep.js",
            "third_party/dep.cc",
            "vendor/dep.cc",
        ):
            self.source(name, "cancel PRIVATE_EXCLUDED_CONTENT\n")
        (self.repo / "binary.cc").write_bytes(b"cancel\x00PRIVATE_EXCLUDED_CONTENT")
        (self.repo / "non_utf8.cc").write_bytes(b"cancel\xffPRIVATE_EXCLUDED_CONTENT")
        (self.repo / "large.cc").write_bytes(b"cancel " + b"x" * MAX_FILE_BYTES)
        outside = self.workspace / "outside.cc"
        outside.write_text("cancel PRIVATE_EXCLUDED_CONTENT\n")
        (self.repo / "linked.cc").symlink_to(outside)
        outside_dir = self.workspace / "external_sources"
        outside_dir.mkdir()
        (outside_dir / "secret.cc").write_text("cancel PRIVATE_EXCLUDED_CONTENT\n")
        (self.repo / "linked_dir").symlink_to(outside_dir, target_is_directory=True)
        investigate(self.repo, "cancel", self.output)
        self.assertEqual([o["path"] for o in self.bundle()["observations"]], ["safe.cc"])
        self.assertNotIn("PRIVATE_EXCLUDED_CONTENT", (self.output / "events.jsonl").read_text())

    def test_direct_reads_reject_traversal_and_symlink_components(self):
        outside = self.workspace / "private.cc"
        outside.write_text("private")
        (self.repo / "linked").symlink_to(self.workspace, target_is_directory=True)
        with SafeRepository(self.repo) as repository:
            for path in ("../private.cc", str(outside), "linked/private.cc", "..\\private.cc"):
                with self.subTest(path=path), self.assertRaises(SkippedFile):
                    repository.read(path)

    def test_directory_only_scan_stops_at_entry_cap(self):
        for i in range(10):
            (self.repo / f"dir{i:02}").mkdir()
        with patch("jev_scout.repository.MAX_SCAN_ENTRIES", 3):
            with SafeRepository(self.repo) as repository:
                candidates, _ = repository.discover("cancel")
                self.assertFalse(candidates)
                self.assertTrue(repository.stats["truncated"])
                self.assertEqual(repository.stats["visited_entries"], 3)

    def test_entry_cap_bounds_actual_scandir_consumption(self):
        for i in range(100):
            self.source(f"source{i:03}.cc", "void cancel() {}\n")
        original_scandir = os.scandir
        consumed = 0

        class CountingScan:
            def __init__(self, directory):
                self.iterator = original_scandir(directory)

            def __enter__(self):
                self.iterator.__enter__()
                return self

            def __next__(self):
                nonlocal consumed
                entry = next(self.iterator)
                consumed += 1
                return entry

            def __exit__(self, *args):
                return self.iterator.__exit__(*args)

        with patch("jev_scout.repository.MAX_SCAN_ENTRIES", 3):
            with patch("jev_scout.repository.os.scandir", CountingScan):
                with SafeRepository(self.repo) as repository:
                    repository.discover("cancel")
                    self.assertTrue(repository.stats["truncated"])
        self.assertEqual(consumed, 3)

    def test_scan_byte_cap_includes_rejected_binary_reads(self):
        (self.repo / "a.cc").write_bytes(b"abcdef\x00\x00")
        self.source("b.cc", "cancel()")
        with patch("jev_scout.repository.MAX_SCAN_BYTES", 10):
            with SafeRepository(self.repo) as repository:
                candidates, _ = repository.discover("cancel")
                self.assertFalse(candidates)
                self.assertTrue(repository.stats["truncated"])
                self.assertEqual(repository.stats["scanned_bytes"], 8)
                self.assertLessEqual(repository.stats["scanned_bytes"], 10)

    def test_repository_root_symlink_is_rejected(self):
        linked = self.workspace / "linked_repo"
        linked.symlink_to(self.repo, target_is_directory=True)
        with self.assertRaises(ValueError):
            investigate(linked, "cancel", self.output)

    def test_qualified_symbol_selects_definition_not_longer_prefix(self):
        self.source(
            "request.cpp",
            "bool Request::cancelled() { return true; }\n" * 20
            + "void Request::cancel() {\n    cancelled_ = true;\n}\n",
        )
        self.source("README.md", "Request::cancel " * 20)
        investigate(self.repo, "Investigate Request::cancel", self.output, max_steps=1)
        observation = self.bundle()["observations"][0]
        self.assertEqual(observation["path"], "request.cpp")
        self.assertIn("void Request::cancel()", observation["text"])
        self.assertIn("cancelled_ = true;", observation["text"])

    def test_default_demo_task_includes_cancel_definition(self):
        demo = Path(__file__).resolve().parents[1] / "examples" / "cancellation"
        investigate(
            demo,
            "Investigate whether Request::cancel removes queued callbacks.",
            self.output,
            max_steps=6,
        )
        observations = self.bundle()["observations"]
        self.assertEqual(observations[0]["path"], "request.cpp")
        self.assertTrue(
            any(
                o["path"] == "request.cpp"
                and "void Request::cancel()" in o["text"]
                and "cancelled_ = true;" in o["text"]
                for o in observations
            )
        )

    def test_candidate_cap_is_disclosed_in_bundle_and_report(self):
        for name in ("alpha.cc", "beta.cc", "gamma.cc"):
            self.source(name, "void cancel() {}\n")
        with patch("jev_scout.repository.MAX_CANDIDATES", 2):
            investigate(self.repo, "cancel", self.output)
        bundle = self.bundle()
        self.assertEqual(bundle["scan"]["candidate_total"], 3)
        self.assertTrue(bundle["scan"]["candidate_truncated"])
        self.assertEqual(len(bundle["candidates"]), 2)
        self.assertIn(
            "Retained candidates: 2 / 3 discovered", (self.output / "report.md").read_text()
        )

    def test_invalid_policy_cannot_introduce_arbitrary_action(self):
        self.source("cancel.cc", "void cancel() {}\n")

        class InvalidPolicy:
            def choose(self, state, candidates):
                return "../../private.cc"

        result = investigate(self.repo, "cancel", self.output, policy=InvalidPolicy())
        self.assertEqual(result.stop_reason, "invalid_policy_choice")
        self.assertEqual(result.observations, 0)
        self.assertEqual(result.steps, 0)

    def test_changed_source_invalidates_discovered_action(self):
        source = self.source("cancel.cc", "void cancel() {}\n")

        class ChangingPolicy:
            def choose(self, state, candidates):
                source.write_text("void replacement() {}\n")
                return candidates[0].id

        result = investigate(self.repo, "cancel", self.output, policy=ChangingPolicy())
        self.assertEqual(result.observations, 0)
        self.assertTrue(any(e.get("reason") == "source_changed" for e in self.events()))

    def test_final_revalidation_detects_changed_observation(self):
        first = self.source("alpha.cc", "void cancel_alpha() {}\n")
        self.source("beta.cc", "void cancel_beta() {}\n")

        class LaterChangePolicy:
            def choose(self, state, candidates):
                if state.step:
                    first.write_text("void changed() {}\n")
                return next(c.id for c in candidates if c.id not in state.seen_candidate_ids)

        investigate(self.repo, "cancel", self.output, policy=LaterChangePolicy())
        observation = self.bundle()["observations"][0]
        self.assertEqual(observation["validity"], "changed")
        self.assertIn("cancel_alpha", observation["text"])
        self.assertNotEqual(observation["source_sha256"], observation["current_sha256"])

    def test_output_cannot_modify_repository_or_overwrite_artifacts(self):
        self.source("cancel.cc", "void cancel() {}\n")
        with self.assertRaises(ValueError):
            investigate(self.repo, "cancel", self.repo / "results")
        self.assertFalse((self.repo / "results").exists())
        investigate(self.repo, "cancel", self.output)
        original = (self.output / "evidence.json").read_bytes()
        with self.assertRaises(ValueError):
            investigate(self.repo, "cancel", self.output)
        self.assertEqual((self.output / "evidence.json").read_bytes(), original)

    def test_case_alias_output_is_rejected_on_case_insensitive_filesystems(self):
        alias = self.workspace / "REPO"
        if not alias.exists() or not alias.samefile(self.repo):
            self.skipTest("Filesystem is case sensitive.")
        with self.assertRaises(ValueError):
            investigate(self.repo, "cancel", alias / "results")
        self.assertFalse((self.repo / "results").exists())

    def test_cli_handles_ancestor_symlink_loops(self):
        loop = self.workspace / "loop"
        loop.symlink_to(loop, target_is_directory=True)
        for repo, output in ((loop / "child", self.output), (self.repo, loop / "child")):
            with self.subTest(repo=repo, output=output):
                with contextlib.redirect_stderr(io.StringIO()) as error:
                    code = main(
                        [
                            "investigate",
                            "--repo",
                            str(repo),
                            "--task",
                            "cancel",
                            "--output",
                            str(output),
                        ]
                    )
                self.assertEqual(code, 2)
                self.assertNotIn("Traceback", error.getvalue())

    def test_no_candidates_and_cli_validation(self):
        self.source("other.cc", "int compute_value() { return 0; }\n")
        result = investigate(self.repo, "zebra_callback", self.output)
        self.assertEqual(result.stop_reason, "no_candidates")
        self.assertEqual(result.observations, 0)
        with contextlib.redirect_stderr(io.StringIO()) as error:
            code = main(
                [
                    "investigate",
                    "--repo",
                    str(self.repo),
                    "--task",
                    "zebra",
                    "--output",
                    str(self.workspace / "bad"),
                    "--max-steps",
                    "0",
                ]
            )
        self.assertEqual(code, 2)
        self.assertIn("budgets must be positive", error.getvalue())

    def test_cli_runs_investigation(self):
        self.source("request.cc", "void cancel_request() {}\n")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(
                [
                    "investigate",
                    "--repo",
                    str(self.repo),
                    "--task",
                    "cancel",
                    "--output",
                    str(self.output),
                    "--max-steps",
                    "1",
                ]
            )
        self.assertEqual(code, 0)
        self.assertIn("Collected 1 observations", output.getvalue())
        self.assertTrue((self.output / "report.md").is_file())


if __name__ == "__main__":
    unittest.main()
