"""Offline provider-contract, request-boundary, and recovery checks."""

import copy
import json
import math
import sys
import threading
import unittest
from dataclasses import asdict
from http.client import BadStatusLine, IncompleteRead, LineTooLong
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import ProxyHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jev_scout.jev import JevPolicy, TransportFailure, TransportResponse
from jev_scout.models import ActionCandidate, ContextEntry, DecisionState, ReadSnippetArgs

KEY_SENTINEL = "test-credential-must-not-appear-in-artifacts"


class JevTests(unittest.TestCase):
    def setUp(self):
        self.candidates = (
            ActionCandidate(
                "c0001",
                "read_snippet",
                ReadSnippetArgs("alpha.cc", 2, 6, "a" * 64),
                100,
                ("Lexical match",),
                "void cancel_alpha() {}",
            ),
            ActionCandidate(
                "c0002",
                "read_snippet",
                ReadSnippetArgs("beta.cc", 7, 10, "b" * 64),
                90,
                ("Lexical match",),
                "void cancel_beta() {}",
            ),
        )
        self.state = DecisionState(
            "Investigate cancellation",
            1,
            8,
            frozenset(),
            (ContextEntry("o0001", "cancelled_ = true;", False),),
            1200,
        )
        self.response = {
            "model": "jev-1.13.0",
            "answers": {
                "next_action": {
                    "type": "choice",
                    "choice": "c0002",
                    "confidence": 0.81,
                    "probabilities": {"c0001": 0.12, "c0002": 0.88},
                }
            },
            "usage": {"input_tokens": 318, "output_tokens": 34},
        }
        self.requests = []

    def transport(self, payload, key, timeout, max_response_bytes):
        self.requests.append((payload, key, timeout, max_response_bytes))
        return TransportResponse(200, json.dumps(self.response).encode())

    def policy(self, **kwargs):
        return JevPolicy(KEY_SENTINEL, transport=self.transport, **kwargs)

    def assert_fallback(self, decision, reason):
        self.assertEqual(decision.backend, "rule")
        self.assertEqual(decision.candidate_id, "c0001")
        self.assertEqual(decision.fallback_reason, reason)

    def test_typed_choice_sends_all_unseen_criteria_and_bounded_state(self):
        policy = self.policy()
        result = policy.choose(self.state, self.candidates)
        self.assertEqual(result.backend, "jev")
        self.assertEqual(result.candidate_id, "c0002")
        self.assertIsNone(result.fallback_reason)
        self.assertEqual(policy.calls, 1)
        request = json.loads(self.requests[0][0])
        self.assertEqual(request["model"], "jev-1.13.0")
        self.assertEqual(request["state"]["remaining_steps"], 7)
        self.assertEqual(request["state"]["active_context"][0]["observation_id"], "o0001")
        question = request["questions"]["next_action"]
        self.assertEqual(question["type"], "choice")
        self.assertEqual(set(question["criteria"]), {"c0001", "c0002"})
        self.assertEqual(question["criteria"]["c0002"]["path"], "beta.cc")
        self.assertNotIn("expected_sha256", question["criteria"]["c0002"])
        attempt = result.attempts[0]
        self.assertEqual(attempt.outcome, "accepted")
        self.assertEqual(attempt.http_status, 200)
        self.assertEqual(attempt.response_model, "jev-1.13.0")
        self.assertEqual(attempt.input_tokens, 318)
        self.assertEqual(attempt.output_tokens, 34)
        self.assertGreaterEqual(attempt.elapsed_ms, 0)
        self.assertEqual(attempt.confidence, 0.81)
        self.assertEqual(attempt.probabilities["c0002"], 0.88)
        self.assertNotIn(KEY_SENTINEL, repr(policy))
        self.assertNotIn(KEY_SENTINEL, json.dumps(policy.describe()))
        self.assertNotIn(KEY_SENTINEL, json.dumps(asdict(result)))
        self.assertNotIn(KEY_SENTINEL, repr(TransportResponse(200, KEY_SENTINEL.encode())))

    def test_seen_candidates_are_not_transmitted_or_selected(self):
        state = DecisionState("cancel", 2, 8, frozenset({"c0001"}), (), 1200)
        self.response["answers"]["next_action"]["probabilities"] = {"c0002": 1.0}
        result = self.policy().choose(state, self.candidates)
        self.assertEqual(result.candidate_id, "c0002")
        self.assertEqual(
            set(json.loads(self.requests[0][0])["questions"]["next_action"]["criteria"]), {"c0002"}
        )

    def test_empty_frontier_does_not_request(self):
        result = self.policy().choose(self.state, ())
        self.assertIsNone(result.candidate_id)
        self.assertIsNone(result.fallback_reason)
        self.assertEqual(result.attempts, ())
        self.assertEqual(self.requests, [])

    def test_provider_candidate_limit_falls_back_without_truncating_frontier(self):
        candidates = tuple(
            ActionCandidate(
                f"c{i:04}",
                "read_snippet",
                ReadSnippetArgs(f"source{i}.cc", 1, 2, "a" * 64),
                100 - i,
                (),
                "cancel",
            )
            for i in range(256)
        )
        result = self.policy().choose(self.state, candidates)
        self.assertEqual(result.backend, "rule")
        self.assertEqual(result.candidate_id, "c0000")
        self.assertEqual(result.fallback_reason, "candidate_limit_exceeded")
        self.assertEqual(result.attempts, ())
        self.assertEqual(self.requests, [])

    def test_request_budget_counts_utf8_and_keeps_no_partial_request(self):
        state = DecisionState("界" * 500, 0, 8, frozenset(), (), 1200)
        result = self.policy(max_request_bytes=1000).choose(state, self.candidates)
        self.assert_fallback(result, "request_budget_exceeded")
        self.assertEqual(result.attempts, ())
        self.assertEqual(self.requests, [])
        self.assertNotIn("界", json.dumps(asdict(result)))

    def test_complete_payload_budget_includes_context_paths_and_previews(self):
        for source in ("task", "context", "path", "preview"):
            with self.subTest(source=source):
                state, candidates = self.state, self.candidates
                if source == "task":
                    state = DecisionState("x" * 10000, 0, 8, frozenset(), (), 1200)
                elif source == "context":
                    state = DecisionState(
                        "cancel",
                        0,
                        8,
                        frozenset(),
                        (ContextEntry("o1", "x" * 10000, False),),
                        12000,
                    )
                else:
                    candidate = ActionCandidate(
                        "c0001",
                        "read_snippet",
                        ReadSnippetArgs(
                            "x" * 10000 if source == "path" else "alpha.cc", 1, 2, "a" * 64
                        ),
                        100,
                        (),
                        "x" * 10000 if source == "preview" else "cancel",
                    )
                    candidates = (candidate,)
                result = self.policy(max_request_bytes=2000).choose(state, candidates)
                self.assert_fallback(result, "request_budget_exceeded")
        self.assertEqual(self.requests, [])

    def test_request_byte_limit_is_inclusive(self):
        self.policy().choose(self.state, self.candidates)
        payload_size = len(self.requests[0][0])
        self.requests.clear()
        result = self.policy(max_request_bytes=payload_size).choose(self.state, self.candidates)
        self.assertEqual(result.backend, "jev")
        self.requests.clear()
        result = self.policy(max_request_bytes=payload_size - 1).choose(self.state, self.candidates)
        self.assert_fallback(result, "request_budget_exceeded")
        self.assertEqual(self.requests, [])

    def test_call_budget_counts_failed_attempts_without_retry(self):
        calls = []

        def failed(*args):
            calls.append(args)
            raise TransportFailure("rate_limited", 429)

        policy = JevPolicy(KEY_SENTINEL, max_calls=1, transport=failed)
        result = policy.choose(self.state, self.candidates)
        self.assert_fallback(result, "rate_limited")
        self.assertEqual(result.attempts[0].http_status, 429)
        self.assertGreaterEqual(result.attempts[0].elapsed_ms, 0)
        self.assertIsNone(result.attempts[0].input_tokens)
        self.assert_fallback(policy.choose(self.state, self.candidates), "call_budget_exhausted")
        self.assertEqual(len(calls), 1)

    def test_low_confidence_retains_valid_distribution_model_and_usage(self):
        self.response["answers"]["next_action"]["confidence"] = 0.4
        result = self.policy(min_confidence=0.5).choose(self.state, self.candidates)
        self.assert_fallback(result, "low_confidence")
        attempt = result.attempts[0]
        self.assertEqual(attempt.choice, "c0002")
        self.assertEqual(attempt.confidence, 0.4)
        self.assertEqual(attempt.response_model, "jev-1.13.0")
        self.assertEqual(attempt.input_tokens, 318)
        self.assertEqual(attempt.probabilities, {"c0001": 0.12, "c0002": 0.88})

    def test_confidence_threshold_is_inclusive_and_distinct_from_winner_probability(self):
        result = self.policy(min_confidence=0.81).choose(self.state, self.candidates)
        self.assertEqual(result.backend, "jev")
        self.assertNotEqual(
            result.attempts[0].confidence, result.attempts[0].probabilities["c0002"]
        )

    def test_missing_or_null_usage_remains_unknown(self):
        for usage in (None, {}, {"input_tokens": None, "output_tokens": None}):
            with self.subTest(usage=usage):
                self.response["usage"] = usage
                result = self.policy().choose(self.state, self.candidates)
                self.assertEqual(result.backend, "jev")
                self.assertIsNone(result.attempts[0].input_tokens)
                self.assertIsNone(result.attempts[0].output_tokens)
        self.response.pop("usage")
        self.assertEqual(self.policy().choose(self.state, self.candidates).backend, "jev")

    def test_invalid_answers_fallback_and_preserve_safe_usage(self):
        good = copy.deepcopy(self.response)
        variants = [
            ("type", "noul"),
            ("choice", True),
            ("choice", "unknown"),
            ("confidence", True),
            ("confidence", -0.1),
            ("confidence", 1.1),
            ("confidence", float("nan")),
            ("confidence", float("inf")),
            ("probabilities", {"c0001": 0.12}),
            ("probabilities", {"c0001": 0.12, "c0002": 0.88, "unknown": 0}),
            ("probabilities", {"c0001": True, "c0002": 0}),
            ("probabilities", {"c0001": -0.1, "c0002": 1.1}),
            ("probabilities", {"c0001": 0.1, "c0002": 0.8}),
            ("probabilities", {"c0001": 0.9, "c0002": 0.1}),
        ]
        for field_name, value in variants:
            with self.subTest(field=field_name, value=value):
                self.response = copy.deepcopy(good)
                self.response["answers"]["next_action"][field_name] = value
                result = self.policy().choose(self.state, self.candidates)
                self.assert_fallback(result, "invalid_response")
                # Non-finite JSON constants reject the body before any metadata is trusted.
                if not isinstance(value, float) or math.isfinite(value):
                    self.assertEqual(result.attempts[0].input_tokens, 318)
                    self.assertEqual(result.attempts[0].response_model, "jev-1.13.0")

    def test_normalization_tolerance_and_equal_probability_ties(self):
        self.response["answers"]["next_action"]["probabilities"] = {
            "c0001": 0.5,
            "c0002": 0.5000005,
        }
        self.assertEqual(self.policy().choose(self.state, self.candidates).backend, "jev")
        self.response["answers"]["next_action"]["probabilities"] = {"c0001": 0.5, "c0002": 0.5}
        self.assertEqual(self.policy().choose(self.state, self.candidates).backend, "jev")

    def test_unknown_response_content_and_secret_echoes_never_become_metadata(self):
        self.response["debug"] = KEY_SENTINEL
        self.response["answers"]["next_action"]["choice"] = KEY_SENTINEL
        self.response["answers"]["next_action"]["probabilities"] = {KEY_SENTINEL: 1.0}
        result = self.policy().choose(self.state, self.candidates)
        self.assert_fallback(result, "invalid_response")
        self.assertNotIn(KEY_SENTINEL, json.dumps(asdict(result)))
        self.assertIsNone(result.attempts[0].choice)

    def test_model_alias_resolves_to_recorded_version_and_pin_mismatch_falls_back(self):
        self.response["model"] = "jev-1.14.0"
        alias = self.policy(model="jev-latest").choose(self.state, self.candidates)
        self.assertEqual(alias.backend, "jev")
        self.assertEqual(alias.attempts[0].response_model, "jev-1.14.0")
        pin = self.policy().choose(self.state, self.candidates)
        self.assert_fallback(pin, "invalid_response")
        self.assertEqual(pin.attempts[0].response_model, "jev-1.14.0")
        self.assertEqual(pin.attempts[0].input_tokens, 318)

    def test_model_or_usage_invalidity_cannot_smuggle_arbitrary_text(self):
        good = copy.deepcopy(self.response)
        for field_name, value in (
            ("model", KEY_SENTINEL),
            ("model", "jev-latest"),
            ("usage", KEY_SENTINEL),
            ("usage", {"input_tokens": True}),
            ("usage", {"output_tokens": -1}),
            ("usage", {"input_tokens": KEY_SENTINEL}),
        ):
            with self.subTest(field=field_name, value=value):
                self.response = copy.deepcopy(good)
                self.response[field_name] = value
                result = self.policy().choose(self.state, self.candidates)
                self.assert_fallback(result, "invalid_response")
                self.assertNotIn(KEY_SENTINEL, json.dumps(asdict(result)))

    def test_response_byte_limit_and_invalid_json_are_fixed_failures(self):
        for body, limit, reason in (
            (b"x" * 101, 100, "response_budget_exceeded"),
            (KEY_SENTINEL.encode(), 1000, "invalid_response"),
            (b"\xff", 1000, "invalid_response"),
            (b'{"model":"jev-1.13.0","model":"jev-1.14.0"}', 1000, "invalid_response"),
            (b"[]", 1000, "invalid_response"),
        ):
            with self.subTest(body=body):
                result = JevPolicy(
                    KEY_SENTINEL,
                    max_response_bytes=limit,
                    transport=lambda *args, body=body: TransportResponse(200, body),
                ).choose(self.state, self.candidates)
                self.assert_fallback(result, reason)
                self.assertEqual(len(result.attempts), 1)
                self.assertNotIn(KEY_SENTINEL, json.dumps(asdict(result)))

    def test_transport_failures_use_fixed_codes_and_unknown_usage(self):
        for failure, expected in (
            (TimeoutError(KEY_SENTINEL), "timeout"),
            (URLError(TimeoutError(KEY_SENTINEL)), "timeout"),
            (URLError(KEY_SENTINEL), "network_error"),
            (OSError(KEY_SENTINEL), "network_error"),
            (TransportFailure("overloaded", 529), "overloaded"),
        ):
            with self.subTest(expected=expected):

                def failed(*args, failure=failure):
                    raise failure

                policy = JevPolicy(KEY_SENTINEL, transport=failed)
                result = policy.choose(self.state, self.candidates)
                self.assert_fallback(result, expected)
                self.assertEqual(policy.calls, 1)
                self.assertIsNone(result.attempts[0].input_tokens)
                self.assertNotIn(KEY_SENTINEL, json.dumps(asdict(result)))

    def test_http_protocol_exceptions_in_injected_transport_use_fixed_fallback(self):
        for failure in (
            BadStatusLine(KEY_SENTINEL),
            IncompleteRead(KEY_SENTINEL.encode(), 200),
            LineTooLong(KEY_SENTINEL),
        ):
            with self.subTest(kind=type(failure).__name__):

                def failed(*args, failure=failure):
                    raise failure

                policy = JevPolicy(KEY_SENTINEL, transport=failed)
                result = policy.choose(self.state, self.candidates)
                self.assert_fallback(result, "network_error")
                self.assertEqual(policy.calls, 1)
                self.assertNotIn(KEY_SENTINEL, json.dumps(asdict(result)))

    def test_http_protocol_exceptions_in_opener_never_escape_or_leak_partial_data(self):
        for failure in (
            BadStatusLine(KEY_SENTINEL),
            IncompleteRead(KEY_SENTINEL.encode(), 200),
            LineTooLong(KEY_SENTINEL),
        ):
            with self.subTest(kind=type(failure).__name__):
                with patch("jev_scout.jev.build_opener") as make_opener:
                    if isinstance(failure, IncompleteRead):
                        response = make_opener.return_value.open.return_value.__enter__.return_value
                        response.status = 200
                        response.read.side_effect = failure
                    else:
                        make_opener.return_value.open.side_effect = failure
                    result = JevPolicy(KEY_SENTINEL).choose(self.state, self.candidates)
                self.assert_fallback(result, "network_error")
                self.assertIsNone(result.attempts[0].input_tokens)
                self.assertNotIn(KEY_SENTINEL, json.dumps(asdict(result)))

    def test_http_statuses_are_mapped_without_persisting_error_bodies(self):
        for status, expected in (
            (401, "authentication_error"),
            (403, "authentication_error"),
            (429, "rate_limited"),
            (529, "overloaded"),
            (422, "http_error"),
            (302, "http_error"),
        ):
            with self.subTest(status=status):
                policy = JevPolicy(
                    KEY_SENTINEL,
                    transport=lambda *args, status=status: TransportResponse(
                        status, KEY_SENTINEL.encode()
                    ),
                )
                result = policy.choose(self.state, self.candidates)
                self.assert_fallback(result, expected)
                self.assertEqual(result.attempts[0].http_status, status)
                self.assertNotIn(KEY_SENTINEL, json.dumps(asdict(result)))

    def test_invalid_configuration_raises_value_error_without_echoing_credentials(self):
        variants = [
            {"api_key": ""},
            {"api_key": "bad\nkey"},
            {"api_key": "bad key"},
            {"api_key": None},
            {"model": ""},
            {"model": KEY_SENTINEL},
            {"min_confidence": True},
            {"min_confidence": float("nan")},
            {"min_confidence": 1.1},
            {"min_confidence": 10**1000},
            {"max_calls": 0},
            {"max_calls": True},
            {"max_request_bytes": -1},
            {"max_response_bytes": 0},
            {"timeout": 0},
            {"timeout": True},
            {"timeout": float("inf")},
            {"timeout": 10**1000},
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                configuration = {"api_key": KEY_SENTINEL, **variant}
                with self.assertRaises(ValueError) as caught:
                    JevPolicy(**configuration)
                self.assertNotIn(KEY_SENTINEL, str(caught.exception))

    def test_real_http_transport_is_single_attempt_and_refuses_redirects(self):
        received = []
        body = json.dumps(self.response).encode()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def do_POST(self):
                payload = self.rfile.read(int(self.headers["Content-Length"]))
                received.append((self.path, self.headers["Authorization"], payload))
                if self.path == "/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/must-not-receive-credentials")
                    self.end_headers()
                elif self.path == "/oversized":
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"x" * 300)
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            with patch("jev_scout.jev.ENDPOINT", base + "/accepted"):
                with patch("jev_scout.jev.ProxyHandler", wraps=ProxyHandler) as proxy:
                    result = JevPolicy(KEY_SENTINEL).choose(self.state, self.candidates)
                    self.assertEqual(result.backend, "jev")
                    proxy.assert_called_once_with({})
            with patch("jev_scout.jev.ENDPOINT", base + "/redirect"):
                result = JevPolicy(KEY_SENTINEL).choose(self.state, self.candidates)
                self.assert_fallback(result, "http_error")
                self.assertEqual(result.attempts[0].http_status, 302)
            with patch("jev_scout.jev.ENDPOINT", base + "/oversized"):
                result = JevPolicy(KEY_SENTINEL, max_response_bytes=100).choose(
                    self.state, self.candidates
                )
                self.assert_fallback(result, "response_budget_exceeded")
            self.assertEqual(
                [request[0] for request in received], ["/accepted", "/redirect", "/oversized"]
            )
            self.assertTrue(all(request[1] == f"Bearer {KEY_SENTINEL}" for request in received))
            self.assertTrue(all(KEY_SENTINEL.encode() not in request[2] for request in received))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
