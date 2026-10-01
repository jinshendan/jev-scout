"""Command line entry point with offline defaults and explicit remote policy opt-in."""

import argparse
import os
import sys
from pathlib import Path

from .comparison import compare
from .investigator import investigate
from .jev import JevPolicy
from .models import Policy, RulePolicy
from .recovery import recover


def _add_jev_arguments(command: argparse.ArgumentParser):
    command.add_argument("--jev-model", help="Jev model or alias (default: jev-1.13.0).")
    command.add_argument(
        "--jev-min-confidence", type=float, help="Choice concentration threshold (default: 0)."
    )
    command.add_argument("--jev-max-calls", type=int, help="Provider attempt budget (default: 8).")
    command.add_argument(
        "--jev-timeout", type=float, help="Socket operation timeout in seconds (default: 10)."
    )
    command.add_argument(
        "--jev-max-request-bytes", type=int, help="UTF-8 request body cap (default: 65536)."
    )


def _make_policy(args: argparse.Namespace, selection: str) -> Policy:
    option = "--challenger" if args.command == "compare" else "--policy"
    if selection == "jev":
        key = os.environ.get("TYPESAFE_API_KEY", "")
        if not key.strip():
            raise ValueError(f"{option} jev requires TYPESAFE_API_KEY in the environment.")
        return JevPolicy(
            api_key=key,
            model=args.jev_model if args.jev_model is not None else "jev-1.13.0",
            min_confidence=args.jev_min_confidence if args.jev_min_confidence is not None else 0.0,
            max_calls=args.jev_max_calls if args.jev_max_calls is not None else 8,
            timeout=args.jev_timeout if args.jev_timeout is not None else 10.0,
            max_request_bytes=(
                args.jev_max_request_bytes if args.jev_max_request_bytes is not None else 65536
            ),
        )
    if any(
        value is not None
        for value in (
            args.jev_model,
            args.jev_min_confidence,
            args.jev_max_calls,
            args.jev_timeout,
            args.jev_max_request_bytes,
        )
    ):
        raise ValueError(f"--jev-* options require {option} jev.")
    return RulePolicy()


def _add_investigation_arguments(command: argparse.ArgumentParser):
    command.add_argument("--repo", required=True, type=Path)
    command.add_argument("--task", required=True)
    command.add_argument("--output", required=True, type=Path)
    command.add_argument("--max-steps", type=int, default=8)
    command.add_argument("--max-context-chars", type=int, default=12000)
    command.add_argument(
        "--max-followups",
        type=int,
        default=0,
        help="Maximum generated same-file neighbor candidates, 0-100 (default: disabled).",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scout",
        description="Read-only investigation, evidence recovery, and policy comparison.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("investigate", help="Collect source observations for a task.")
    _add_investigation_arguments(command)
    command.add_argument("--policy", choices=("rule", "jev"), default="rule")
    _add_jev_arguments(command)

    command = commands.add_parser("recover", help="Restore retained evidence into fresh context.")
    command.add_argument("--evidence", required=True, type=Path)
    command.add_argument("--repo", required=True, type=Path)
    command.add_argument("--observation", dest="observation_ids", action="append", required=True)
    command.add_argument("--output", required=True, type=Path)
    command.add_argument("--max-context-chars", type=int, default=12000)

    command = commands.add_parser("compare", help="Compare policies on one captured frontier.")
    _add_investigation_arguments(command)
    command.add_argument("--challenger", choices=("rule", "jev"), default="rule")
    _add_jev_arguments(command)
    args = parser.parse_args(argv)
    try:
        if args.command == "recover":
            result = recover(
                args.evidence, args.repo, args.observation_ids, args.output, args.max_context_chars
            )
            print(
                f"Validated {result.recovered} current observations "
                f"out of {result.requested} requested."
            )
        elif args.command == "compare":
            challenger = _make_policy(args, args.challenger)
            result = compare(
                args.repo,
                args.task,
                args.output,
                args.max_steps,
                args.max_context_chars,
                challenger_factory=lambda: challenger,
                max_followups=args.max_followups,
            )
            print(f"Compared two fresh policy runs on snapshot {result.snapshot_id}.")
            print("Action agreement describes behavior, not task quality or repair success.")
        else:
            policy = _make_policy(args, args.policy)
            result = investigate(
                args.repo,
                args.task,
                args.output,
                args.max_steps,
                args.max_context_chars,
                policy,
                max_followups=args.max_followups,
            )
            print(
                f"Collected {result.observations} observations in {result.steps} snippet actions."
            )
            print(f"Stop reason: {result.stop_reason}")
    except (ValueError, OSError) as exc:
        print(f"scout: {exc}", file=sys.stderr)
        return 2
    print(f"Report: {result.report_path}")
    return 0
