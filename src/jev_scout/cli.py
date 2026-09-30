"""Command line entry point for the deterministic M1 investigator."""

import argparse
import sys
from pathlib import Path

from .investigator import investigate


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
    args = parser.parse_args(argv)
    try:
        result = investigate(
            args.repo, args.task, args.output, args.max_steps, args.max_context_chars
        )
    except (ValueError, OSError) as exc:
        print(f"scout: {exc}", file=sys.stderr)
        return 2
    print(f"Collected {result.observations} observations in {result.steps} snippet actions.")
    print(f"Stop reason: {result.stop_reason}")
    print(f"Report: {result.report_path}")
    return 0
