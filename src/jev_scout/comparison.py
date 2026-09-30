"""Paired policy runs over one bounded, immutable source capture."""

import hashlib
import json
import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from .artifacts import prepare_output
from .investigator import _run_investigation
from .models import Policy, RulePolicy
from .repository import (
    MAX_CANDIDATES,
    MAX_FILE_BYTES,
    MAX_SCAN_BYTES,
    MAX_SCAN_ENTRIES,
    MAX_SCAN_FILES,
    SafeRepository,
    SkippedFile,
    SourceFile,
)
from .version import __version__


@dataclass(frozen=True)
class ComparisonResult:
    output_dir: Path
    snapshot_id: str

    @property
    def comparison_path(self) -> Path:
        return self.output_dir / "comparison.json"

    @property
    def report_path(self) -> Path:
        return self.output_dir / "report.md"


class _FrozenRepository:
    """Serve captured text without reopening or writing the original checkout."""

    def __init__(self, root: Path, stats: dict, sources: dict[str, SourceFile]):
        self.root = root
        self.stats = deepcopy(stats)
        self._sources = sources.copy()

    def read(self, relative: str) -> SourceFile:
        try:
            return self._sources[relative]
        except KeyError:
            raise SkippedFile("not_in_frozen_snapshot") from None


def _elapsed_ms(started: float) -> float:
    return round(max(0.0, time.monotonic() - started) * 1000, 3)


def _limits(max_steps: int, max_context_chars: int) -> dict:
    return {
        "max_steps": max_steps,
        "max_context_chars": max_context_chars,
        "max_excerpt_chars": 4000,
        "max_file_bytes": MAX_FILE_BYTES,
        "max_scan_bytes": MAX_SCAN_BYTES,
        "max_scan_files": MAX_SCAN_FILES,
        "max_scan_entries": MAX_SCAN_ENTRIES,
        "max_candidates": MAX_CANDIDATES,
        "max_capture_bytes": MAX_SCAN_BYTES,
    }


def _transport_mode(policy: Policy, config: dict) -> str:
    if isinstance(policy, RulePolicy):
        return "none"
    transport = config.get("transport")
    return transport if transport in ("http", "injected") else "custom"


def _summarize_arm(result, policy: Policy, elapsed_ms: float) -> dict:
    bundle = json.loads(result.evidence_path.read_text(encoding="utf-8"))
    events = [
        json.loads(line) for line in result.events_path.read_text(encoding="utf-8").splitlines()
    ]
    actions = [event["candidate"]["id"] for event in events if event["type"] == "action_selected"]
    config = bundle["policy_config"]
    models = sorted(
        {
            attempt["response_model"]
            for decision in bundle["decisions"]
            for attempt in decision["attempts"]
            if attempt["response_model"] is not None
        }
    )
    return {
        "configured_policy": bundle["policy"],
        "policy_config": config,
        "transport": _transport_mode(policy, config),
        "elapsed_ms": elapsed_ms,
        "stop_reason": result.stop_reason,
        "actions": result.steps,
        "observations": result.observations,
        "action_candidate_ids": actions,
        "observed_candidate_ids": [
            observation["candidate_id"] for observation in bundle["observations"]
        ],
        "observed_paths": [observation["path"] for observation in bundle["observations"]],
        "active_context_chars": bundle["context"]["characters"],
        "reported_response_models": models,
        "policy_accounting": bundle["policy_accounting"],
    }


def _agreement(baseline: dict, challenger: dict) -> dict:
    first = baseline["action_candidate_ids"]
    second = challenger["action_candidate_ids"]
    positions = max(len(first), len(second))
    matching = sum(left == right for left, right in zip(first, second, strict=False))
    first_observed = set(baseline["observed_candidate_ids"])
    second_observed = set(challenger["observed_candidate_ids"])
    shared = first_observed & second_observed
    union = first_observed | second_observed
    return {
        "interpretation": "Behavioral agreement is not evidence quality or task success.",
        "action_positions": positions,
        "matching_action_positions": matching,
        "positional_action_agreement": matching / positions if positions else None,
        "exact_action_sequence_match": first == second,
        "shared_observed_candidates": len(shared),
        "distinct_observed_candidates": len(union),
        "observed_candidate_jaccard": len(shared) / len(union) if union else None,
    }


def _render_report(summary: dict) -> str:
    timing = summary["timing"]
    agreement = summary["agreement"]
    lines = [
        "# Frozen policy comparison",
        "",
        f"Task: {summary['snapshot']['task']}",
        "",
        f"Snapshot identity: `{summary['snapshot_id']}`.",
        "",
        "Both arms use the same captured source text, initial candidate frontier, task, and "
        "investigation budgets. Each arm has independent policy state and retained evidence.",
        "The capture is a bounded, sequential collection of retained candidate files; it is "
        "not an atomic snapshot of the whole repository. Truncated discovery remains partial.",
        "The manifest records identities and candidate metadata, not a full source archive. "
        "A later rerun requires the original source content separately.",
        "",
        f"Discovery truncated: `{summary['snapshot']['scan']['truncated']}`; "
        f"candidate frontier truncated: `{summary['snapshot']['scan']['candidate_truncated']}`.",
        f"Captured files: {len(summary['snapshot']['sources'])}; "
        f"captured bytes: {summary['captured_bytes']}.",
        f"Shared discovery/capture elapsed: {timing['capture_elapsed_ms']} ms; "
        f"whole comparison elapsed through summary construction: {timing['whole_elapsed_ms']} ms.",
        "Arms run sequentially in the fixed order: rule, challenger. Timing excludes final "
        "comparison-summary publication and is not a controlled benchmark of cold-start latency.",
        "",
        "| Arm | Configured policy | Transport | Actions | Observations | Elapsed ms |",
        "| --- | --- | --- | ---: | ---: | ---: |",
    ]
    for name in ("rule", "challenger"):
        arm = summary["arms"][name]
        lines.append(
            f"| [{name}]({name}/report.md) | `{arm['configured_policy']}` | "
            f"`{arm['transport']}` | {arm['actions']} | {arm['observations']} | "
            f"{arm['elapsed_ms']} |"
        )
    lines.extend(["", "## Provider accounting", ""])
    for name in ("rule", "challenger"):
        arm = summary["arms"][name]
        usage = arm["policy_accounting"]
        lines.extend(
            [
                f"- {name}: actual decision backends `{usage['backend_decisions']}`; "
                f"{usage['provider_attempts']} provider attempts; "
                f"{usage['fallback_decisions']} fallbacks; "
                f"reported input/output tokens {usage['reported_input_tokens']} / "
                f"{usage['reported_output_tokens']}; unknown input/output usage in "
                f"{usage['unknown_input_usage_attempts']} / "
                f"{usage['unknown_output_usage_attempts']} attempts; "
                f"returned models `{arm['reported_response_models']}`."
            ]
        )
    lines.extend(
        [
            "",
            "Reported token sums exclude unknown usage. They are not a price or success estimate. "
            "An injected transport represents a controlled fixture, "
            "not a live-provider validation.",
            "",
            "## Behavioral diagnostics",
            "",
            f"Matching action positions: {agreement['matching_action_positions']} / "
            f"{agreement['action_positions']}; "
            f"positional agreement: `{agreement['positional_action_agreement']}`.",
            f"Observed-candidate overlap (Jaccard): `{agreement['observed_candidate_jaccard']}`.",
            "Empty denominators produce null. Agreement measures behavior, not evidence quality, "
            "root-cause accuracy, or repair success. "
            "No investigated source was executed or edited.",
            "",
            "## Original checkout after both arms",
            "",
            "The following check is separate from the frozen inputs used by both arms. "
            "A source changing in the original checkout does not alter the captured evidence.",
            "",
        ]
    )
    counts = summary["original_source_revalidation"]["status_counts"]
    lines.extend([f"Source status counts: `{counts}`.", ""])
    return "\n".join(lines)


def compare(
    repo: Path,
    task: str,
    output: Path,
    max_steps: int = 8,
    max_context_chars: int = 12000,
    challenger_factory: Callable[[], Policy] = RulePolicy,
) -> ComparisonResult:
    """Run fresh rule and challenger policies over one bounded frozen source input.

    The default rule-versus-rule pair is an offline reproducibility check. A caller
    can supply a fresh Jev policy factory for a live or explicitly injected arm.
    Discovery and capture finish successfully before the challenger factory is invoked.
    """
    if not task.strip():
        raise ValueError("Task must not be empty.")
    if (
        isinstance(max_steps, bool)
        or not isinstance(max_steps, int)
        or max_steps < 1
        or isinstance(max_context_chars, bool)
        or not isinstance(max_context_chars, int)
        or max_context_chars < 1
    ):
        raise ValueError("Step and context budgets must be positive integers.")
    if not callable(challenger_factory):
        raise ValueError("Challenger factory must construct a fresh policy.")
    started = time.monotonic()
    with SafeRepository(Path(repo)) as repository:
        destination = prepare_output(
            Path(output),
            repository.root,
            names=("comparison.json", "report.md", "rule", "challenger"),
        )
        destinations = {
            name: prepare_output(destination / name, repository.root)
            for name in ("rule", "challenger")
        }
        capture_started = time.monotonic()
        candidates, terms = repository.discover(task)
        sources: dict[str, SourceFile] = {}
        captured_bytes = 0
        for candidate in candidates:
            path = candidate.args.path
            if path not in sources:
                try:
                    source = repository.read(path)
                except SkippedFile as exc:
                    raise ValueError(
                        f"Comparison source unavailable during capture: {path}."
                    ) from exc
                captured_bytes += source.byte_size
                if captured_bytes > MAX_SCAN_BYTES:
                    raise ValueError("Comparison capture byte budget exceeded.")
                sources[path] = source
            if sources[path].sha256 != candidate.args.expected_sha256:
                raise ValueError(f"Comparison source changed during capture: {path}.")
        snapshot = {
            "schema_version": 1,
            "implementation_version": __version__,
            "task": task,
            "terms": terms,
            "candidates": [candidate.to_dict() for candidate in candidates],
            "sources": [
                {"path": path, "sha256": source.sha256, "byte_size": source.byte_size}
                for path, source in sorted(sources.items())
            ],
            "limits": _limits(max_steps, max_context_chars),
            "scan": deepcopy(repository.stats),
        }
        encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        snapshot_id = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        capture_elapsed = _elapsed_ms(capture_started)
        arms = {}
        for name, factory in (("rule", RulePolicy), ("challenger", challenger_factory)):
            arm_started = time.monotonic()
            policy = factory()
            if not callable(getattr(policy, "choose", None)):
                raise ValueError("Challenger factory must construct a decision policy.")
            frozen = _FrozenRepository(repository.root, snapshot["scan"], sources)
            result = _run_investigation(
                frozen,
                task,
                destinations[name],
                max_steps,
                max_context_chars,
                policy,
                frontier=(candidates.copy(), terms.copy()),
                source_mode="frozen",
                snapshot_id=snapshot_id,
            )
            arms[name] = _summarize_arm(result, policy, _elapsed_ms(arm_started))
        revalidated = []
        status_counts = {"current_at_final_check": 0, "changed": 0, "unavailable": 0}
        for path, captured in sorted(sources.items()):
            try:
                current = repository.read(path)
                current_sha256 = current.sha256
                status = (
                    "current_at_final_check" if current.sha256 == captured.sha256 else "changed"
                )
            except SkippedFile:
                current_sha256, status = None, "unavailable"
            status_counts[status] += 1
            revalidated.append({"path": path, "status": status, "current_sha256": current_sha256})
        summary = {
            "schema_version": 1,
            "snapshot_id": snapshot_id,
            "snapshot": snapshot,
            "captured_bytes": captured_bytes,
            "source_repo": str(repository.root),
            "source_mode": "frozen",
            "arm_order": ["rule", "challenger"],
            "arms": arms,
            "agreement": _agreement(arms["rule"], arms["challenger"]),
            "original_source_revalidation": {
                "performed_after_both_arms": True,
                "files": revalidated,
                "status_counts": status_counts,
            },
            "timing": {
                "capture_elapsed_ms": capture_elapsed,
                "whole_elapsed_ms": _elapsed_ms(started),
                "measurement_boundary": (
                    "Includes output preparation, capture, complete sequential arm runs, and "
                    "original-source revalidation; excludes final comparison-summary publication."
                ),
            },
        }
        report = _render_report(summary)
        summary["timing"]["whole_elapsed_ms"] = _elapsed_ms(started)
        report = _render_report(summary)
        with (destination / "comparison.json").open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
        with (destination / "report.md").open("x", encoding="utf-8") as stream:
            stream.write(report)
        return ComparisonResult(destination, snapshot_id)
