"""Policy opt-in, fallback, accounting, and evidence integrity across complete runs."""

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

from jev_scout import JevPolicy, PolicyDecision, investigate
from jev_scout.cli import main
from jev_scout.jev import TransportResponse


class PolicyIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.repo = self.workspace / "repo"
        self.repo.mkdir()
        self.output = self.workspace / "output"
        for index in range(3):
            (self.repo / f"source{index}.py").write_text(
                f"def cancel_callback_{index}():\n    return {index}\n"
            )
        self.secret = "credential-sentinel-never-persist"

    def bundle(self):
        return json.loads((self.output / "evidence.json").read_text())

    def events(self):
        return [
            json.loads(line) for line in (self.output / "events.jsonl").read_text().splitlines()
        ]

    def response(self, payload, usage=True):
        request = json.loads(payload)
        ids = list(request["questions"]["next_action"]["criteria"])
        response = {
            "model": "jev-1.13.0",
            "answers": {
                "next_action": {
                    "type": "choice",
                    "choice": ids[-1],
                    "confidence": 1.0,
                    "probabilities": {
                        candidate_id: float(candidate_id == ids[-1]) for candidate_id in ids
                    },
                }
            },
        }
        if usage:
            response["usage"] = {"input_tokens": 5, "output_tokens": 2}
        return TransportResponse(200, json.dumps(response).encode())

    def cli_args(self, *extra):
        return [
            "investigate",
            "--repo",
            str(self.repo),
            "--task",
            "cancel callback",
            "--output",
            str(self.output),
            *extra,
        ]

    def test_offline_cli_does_not_construct_provider_even_with_key(self):
        with (
            patch.dict(os.environ, {"TYPESAFE_API_KEY": self.secret}),
            patch("jev_scout.cli.JevPolicy", side_effect=AssertionError("Provider was used.")),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(main(self.cli_args()), 0)
        bundle = self.bundle()
        self.assertEqual(bundle["schema_version"], 2)
        self.assertEqual(bundle["policy_config"]["backend"], "rule")
        self.assertEqual(bundle["policy_accounting"]["provider_attempts"], 0)
        self.assertEqual(bundle["policy_accounting"]["backend_decisions"], {"rule": 3})

    def test_missing_key_is_setup_error_before_artifacts(self):
        stderr = io.StringIO()
        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(stderr):
            self.assertEqual(main(self.cli_args("--policy", "jev")), 2)
        self.assertIn("TYPESAFE_API_KEY", stderr.getvalue())
        self.assertFalse(self.output.exists())

    def test_provider_options_require_explicit_opt_in(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(self.cli_args("--jev-max-calls", "1")), 2)
        self.assertFalse(self.output.exists())

    def test_call_budget_fallback_is_recorded_without_losing_evidence(self):
        calls = []

        def transport(payload, key, timeout, max_response_bytes):
            calls.append(payload)
            self.assertEqual(key, self.secret)
            return self.response(payload)

        policy = JevPolicy(self.secret, max_calls=1, transport=transport)
        result = investigate(self.repo, "cancel callback", self.output, max_steps=3, policy=policy)
        self.assertEqual(result.observations, 3)
        bundle = self.bundle()
        accounting = bundle["policy_accounting"]
        self.assertEqual(len(calls), 1)
        self.assertEqual(accounting["provider_attempts"], 1)
        self.assertEqual(accounting["fallback_decisions"], 2)
        self.assertEqual(accounting["reported_input_tokens"], 5)
        self.assertEqual(accounting["reported_output_tokens"], 2)
        self.assertEqual(accounting["unknown_input_usage_attempts"], 0)
        self.assertEqual(accounting["backend_decisions"], {"jev": 1, "rule": 2})
        self.assertTrue(
            all(o["validity"] == "current_at_final_check" for o in bundle["observations"])
        )
        recorded = [e for e in self.events() if e["type"] == "policy_decision"]
        self.assertEqual(
            [e["candidate_id"] for e in recorded], [d["candidate_id"] for d in bundle["decisions"]]
        )
        self.assertEqual(recorded[1]["fallback_reason"], "call_budget_exhausted")

    def test_error_bodies_and_credentials_do_not_enter_any_artifact(self):
        def transport(payload, key, timeout, max_response_bytes):
            return TransportResponse(429, json.dumps({"error": key}).encode())

        policy = JevPolicy(self.secret, max_calls=1, transport=transport)
        result = investigate(self.repo, "cancel callback", self.output, policy=policy)
        self.assertEqual(result.observations, 3)
        bundle = self.bundle()
        first = bundle["decisions"][0]
        self.assertEqual(first["backend"], "rule")
        self.assertEqual(first["fallback_reason"], "rate_limited")
        self.assertEqual(first["attempts"][0]["http_status"], 429)
        self.assertIsNone(first["attempts"][0]["input_tokens"])
        self.assertEqual(bundle["policy_accounting"]["unknown_input_usage_attempts"], 1)
        for path in self.output.iterdir():
            self.assertNotIn(self.secret, path.read_text())
            self.assertNotIn("Authorization", path.read_text())
        report = result.report_path.read_text()
        self.assertIn("rule fallbacks: 3", report)
        self.assertIn("exclude unknown usage", report)
        self.assertNotIn("No compilation, tests, patches, Jev", report)

    def test_missing_usage_is_unknown_even_for_successful_decision(self):
        def transport(payload, key, timeout, max_response_bytes):
            return self.response(payload, usage=False)

        investigate(
            self.repo,
            "cancel callback",
            self.output,
            max_steps=1,
            policy=JevPolicy(self.secret, transport=transport),
        )
        bundle = self.bundle()
        attempt = bundle["decisions"][0]["attempts"][0]
        self.assertIsNone(attempt["input_tokens"])
        self.assertIsNone(attempt["output_tokens"])
        self.assertEqual(bundle["policy_accounting"]["unknown_output_usage_attempts"], 1)

    def test_source_change_after_provider_choice_remains_untrusted(self):
        changed = []

        def transport(payload, key, timeout, max_response_bytes):
            response = self.response(payload)
            request = json.loads(payload)
            chosen = json.loads(response.body)["answers"]["next_action"]["choice"]
            path = request["questions"]["next_action"]["criteria"][chosen]["path"]
            (self.repo / path).write_text("def completely_changed():\n    return 99\n")
            changed.append(chosen)
            return response

        result = investigate(
            self.repo,
            "cancel callback",
            self.output,
            max_steps=3,
            policy=JevPolicy(self.secret, max_calls=1, transport=transport),
        )
        self.assertEqual(result.observations, 2)
        self.assertNotIn(changed[0], [o["candidate_id"] for o in self.bundle()["observations"]])
        self.assertTrue(
            any(
                e["type"] == "action_skipped" and e["reason"] == "source_changed"
                for e in self.events()
            )
        )

    def test_typed_decision_still_cannot_introduce_arbitrary_action(self):
        class InvalidPolicy:
            def choose(self, state, candidates):
                return PolicyDecision("execute-shell-command", "fixture")

        result = investigate(self.repo, "cancel callback", self.output, policy=InvalidPolicy())
        self.assertEqual(result.stop_reason, "invalid_policy_choice")
        self.assertEqual(result.steps, 0)
        self.assertEqual(result.observations, 0)
        self.assertEqual(self.bundle()["policy_accounting"]["provider_attempts"], 0)


if __name__ == "__main__":
    unittest.main()
