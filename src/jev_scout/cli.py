"""Command line entry point with offline defaults and explicit remote policy opt-in."""

import argparse
import os
import sys
from pathlib import Path

from .investigator import investigate
from .jev import JevPolicy
from .models import RulePolicy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scout", description="Read-only lexical code investigation."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("investigate", help="Collect source observations for a task.")
    command.add_argument("--repo", required=True, type=Path)
    command.add_argument("--task", required=True)
    command.add_argument("--output", required=True, type=Path)
    command.add_argument("--max-steps", type=int, default=8)
    command.add_argument("--max-context-chars", type=int, default=12000)
    command.add_argument("--policy", choices=("rule", "jev"), default="rule")
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
    args = parser.parse_args(argv)
    try:
        if args.policy == "jev":
            key = os.environ.get("TYPESAFE_API_KEY", "")
            if not key.strip():
                raise ValueError("--policy jev requires TYPESAFE_API_KEY in the environment.")
            policy = JevPolicy(
                api_key=key,
                model=args.jev_model if args.jev_model is not None else "jev-1.13.0",
                min_confidence=(
                    args.jev_min_confidence if args.jev_min_confidence is not None else 0.0
                ),
                max_calls=args.jev_max_calls if args.jev_max_calls is not None else 8,
                timeout=args.jev_timeout if args.jev_timeout is not None else 10.0,
                max_request_bytes=(
                    args.jev_max_request_bytes if args.jev_max_request_bytes is not None else 65536
                ),
            )
        else:
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
                raise ValueError("--jev-* options require --policy jev.")
            policy = RulePolicy()
        result = investigate(
            args.repo, args.task, args.output, args.max_steps, args.max_context_chars, policy
        )
    except (ValueError, OSError) as exc:
        print(f"scout: {exc}", file=sys.stderr)
        return 2
    print(f"Collected {result.observations} observations in {result.steps} snippet actions.")
    print(f"Stop reason: {result.stop_reason}")
    print(f"Report: {result.report_path}")
    return 0
