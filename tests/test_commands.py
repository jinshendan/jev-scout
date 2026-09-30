"""Complete CLI handoffs and shared source boundaries for recovery and comparison."""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jev_scout import JevPolicy, investigate
from jev_scout.cli import main
from jev_scout.jev import TransportResponse
from jev_scout.repository import SafeRepository, SkippedFile


class CommandTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.repo = self.workspace / "repo"
        self.repo.mkdir()
        for index in range(3):
            (self.repo / f"source{index}.py").write_text(
                f"def cancel_callback_{index}():\n    return {index}\n"
            )
        self.output = self.workspace / "output"

    def compare_args(self, *extra):
        return [
            "compare",
            "--repo",
            str(self.repo),
            "--task",
            "cancel callback",
            "--output",
            str(self.output),
            "--max-steps",
            "2",
            *extra,
        ]

    def test_default_compare_remains_offline_even_with_credentials(self):
        with (
            patch.dict(os.environ, {"TYPESAFE_API_KEY": "cli-key-sentinel"}),
            patch("jev_scout.cli.JevPolicy", side_effect=AssertionError("Remote opt-in required.")),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(main(self.compare_args()), 0)
        comparison = json.loads((self.output / "comparison.json").read_text())
        self.assertEqual(comparison["agreement"]["positional_action_agreement"], 1.0)
        for name in ("rule", "challenger"):
            bundle = json.loads((self.output / name / "evidence.json").read_text())
            self.assertEqual(bundle["source_mode"], "frozen")
            self.assertEqual(bundle["snapshot_id"], comparison["snapshot_id"])
            self.assertEqual(bundle["policy_accounting"]["provider_attempts"], 0)
            self.assertTrue(all(o["current_sha256"] is None for o in bundle["observations"]))
            self.assertTrue(
                all(o["validity"] == "matched_frozen_snapshot" for o in bundle["observations"])
            )

    def test_compare_missing_key_is_setup_error_before_output(self):
        stderr = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(stderr):
            self.assertEqual(main(self.compare_args("--challenger", "jev")), 2)
        self.assertIn("TYPESAFE_API_KEY", stderr.getvalue())
        self.assertFalse(self.output.exists())

    def test_compare_provider_options_require_challenger_opt_in(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(main(self.compare_args("--jev-timeout", "1")), 2)
        self.assertIn("--challenger jev", stderr.getvalue())
        self.assertFalse(self.output.exists())

    def test_compare_cli_records_injected_selection_and_rule_fallback(self):
        secret = "cli-key-sentinel"

        def fixture(payload, key, timeout, max_response_bytes):
            request = json.loads(payload)
            ids = list(request["questions"]["next_action"]["criteria"])
            chosen = ids[-1]
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
                                    candidate: float(candidate == chosen) for candidate in ids
                                },
                            }
                        },
                        "usage": {"input_tokens": 25, "output_tokens": 2},
                    }
                ).encode(),
            )

        policy = JevPolicy(secret, max_calls=1, transport=fixture)
        with (
            patch.dict(os.environ, {"TYPESAFE_API_KEY": secret}),
            patch("jev_scout.cli.JevPolicy", return_value=policy) as constructor,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(
                main(self.compare_args("--challenger", "jev", "--jev-max-calls", "1")), 0
            )
        self.assertEqual(constructor.call_args.kwargs["max_calls"], 1)
        comparison = json.loads((self.output / "comparison.json").read_text())
        challenger = comparison["arms"]["challenger"]
        self.assertEqual(challenger["transport"], "injected")
        self.assertEqual(
            challenger["policy_accounting"]["backend_decisions"], {"jev": 1, "rule": 1}
        )
        self.assertEqual(challenger["policy_accounting"]["provider_attempts"], 1)
        for path in self.output.rglob("*"):
            if path.is_file():
                self.assertNotIn(secret, path.read_text())

    def test_recover_cli_restores_an_evicted_record_without_network(self):
        initial = self.workspace / "initial"
        investigate(self.repo, "cancel callback", initial, max_context_chars=1)
        original = (initial / "evidence.json").read_bytes()
        self.assertIn("o0001", json.loads(original)["context"]["evicted_ids"])
        with (
            patch("jev_scout.cli.JevPolicy", side_effect=AssertionError("Recovery is offline.")),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            status = main(
                [
                    "recover",
                    "--evidence",
                    str(initial / "evidence.json"),
                    "--repo",
                    str(self.repo),
                    "--observation",
                    "o0001",
                    "--output",
                    str(self.output),
                    "--max-context-chars",
                    "20",
                ]
            )
        self.assertEqual(status, 0)
        recovery = json.loads((self.output / "recovery.json").read_text())
        self.assertEqual(recovery["context"]["active"][0]["observation_id"], "o0001")
        self.assertEqual(recovery["observations"][0]["validity"], "current_at_recovery_check")
        self.assertEqual((initial / "evidence.json").read_bytes(), original)

    def test_recover_cli_rejects_unknown_id_before_output(self):
        initial = self.workspace / "initial"
        investigate(self.repo, "cancel callback", initial)
        with contextlib.redirect_stderr(io.StringIO()):
            status = main(
                [
                    "recover",
                    "--evidence",
                    str(initial / "evidence.json"),
                    "--repo",
                    str(self.repo),
                    "--observation",
                    "o9999",
                    "--output",
                    str(self.output),
                ]
            )
        self.assertEqual(status, 2)
        self.assertFalse(self.output.exists())

    def test_direct_reads_enforce_excluded_and_canonical_paths(self):
        with SafeRepository(self.repo) as repository:
            for path in (".env", ".aws/credentials", "node_modules/code.py", ".scout/code.py"):
                with self.subTest(path=path), self.assertRaises(SkippedFile) as caught:
                    repository.read(path)
                self.assertEqual(str(caught.exception), "excluded_path")
            for path in ("./source0.py", "x//code.py", "source0.py/", "bad\x00path", "bad\npath"):
                with self.subTest(path=path), self.assertRaises(SkippedFile) as caught:
                    repository.read(path)
                self.assertEqual(str(caught.exception), "unsafe_path")

    def test_generated_scout_directory_is_excluded_from_discovery(self):
        (self.repo / ".scout").mkdir()
        (self.repo / ".scout" / "generated.py").write_text("def cancel_callback(): pass\n")
        with SafeRepository(self.repo) as repository:
            candidates, _ = repository.discover("cancel callback")
        self.assertEqual(len(candidates), 3)
        self.assertFalse(any(c.args.path.startswith(".scout/") for c in candidates))


if __name__ == "__main__":
    unittest.main()
