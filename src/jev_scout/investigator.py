"""Investigation loop, recoverable context projections, and auditable artifacts."""

import json
import re
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .artifacts import prepare_output as _prepare_output
from .models import (
    ActionCandidate,
    ContextEntry,
    DecisionState,
    InvestigationResult,
    Policy,
    PolicyDecision,
    RulePolicy,
)
from .repository import (
    MAX_CANDIDATES,
    MAX_FILE_BYTES,
    MAX_SCAN_BYTES,
    MAX_SCAN_ENTRIES,
    MAX_SCAN_FILES,
    SafeRepository,
    SkippedFile,
)


class EventLog:
    def __init__(self, path: Path):
        self.stream = path.open("x", encoding="utf-8")
        self.sequence = 0

    def emit(self, kind: str, **payload):
        self.sequence += 1
        event = {
            "sequence": self.sequence,
            "type": kind,
            "timestamp": datetime.now(UTC).isoformat(),
            **payload,
        }
        self.stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        self.stream.flush()

    def close(self):
        self.stream.close()


def _add_context(active, observation, max_chars, events, evicted):
    text = observation["text"][:max_chars]
    while active and sum(len(entry.text) for entry in active) + len(text) > max_chars:
        old = active.pop(0)
        evicted.append(old.observation_id)
        events.emit(
            "context_evicted",
            observation_id=old.observation_id,
            reason="context_char_budget",
            raw_evidence_preserved=True,
        )
    truncated = len(text) < len(observation["text"])
    active.append(ContextEntry(observation["id"], text, truncated))
    if truncated:
        events.emit(
            "context_truncated",
            observation_id=observation["id"],
            active_chars=len(text),
            raw_chars=len(observation["text"]),
            raw_evidence_preserved=True,
        )


def _policy_accounting(decisions: list[dict]) -> dict:
    attempts = [attempt for decision in decisions for attempt in decision["attempts"]]
    return {
        "decisions": len(decisions),
        "backend_decisions": dict(sorted(Counter(d["backend"] for d in decisions).items())),
        "fallback_decisions": sum(d["fallback_reason"] is not None for d in decisions),
        "provider_attempts": len(attempts),
        "provider_latency_ms": round(sum(a["elapsed_ms"] for a in attempts), 3),
        "reported_input_tokens": sum(a["input_tokens"] or 0 for a in attempts),
        "reported_output_tokens": sum(a["output_tokens"] or 0 for a in attempts),
        "unknown_input_usage_attempts": sum(a["input_tokens"] is None for a in attempts),
        "unknown_output_usage_attempts": sum(a["output_tokens"] is None for a in attempts),
    }


def _render_report(bundle: dict) -> str:
    context = bundle["context"]
    scan = bundle["scan"]
    accounting = bundle["policy_accounting"]
    lines = [
        "# Code investigation report",
        "",
        f"Task: {bundle['task']}",
        "",
        "This report contains lexical observations, not a root-cause diagnosis.",
        "",
        f"Source mode: `{bundle.get('source_mode', 'live')}`; "
        f"snapshot: `{bundle.get('snapshot_id')}`.",
        (
            "These excerpts match a captured candidate-source snapshot. "
            "Snapshot matches do not imply that the current checkout is unchanged."
            if bundle.get("source_mode") == "frozen"
            else "Source validity describes a point-in-time check of the investigated checkout."
        ),
        "",
        f"Configured policy: `{bundle['policy']}`.",
        f"Provider attempts: {accounting['provider_attempts']}; "
        f"rule fallbacks: {accounting['fallback_decisions']}; "
        f"provider attempt latency: {accounting['provider_latency_ms']} ms.",
        f"Reported input/output tokens: {accounting['reported_input_tokens']} / "
        f"{accounting['reported_output_tokens']}; counts unavailable for "
        f"{accounting['unknown_input_usage_attempts']} / "
        f"{accounting['unknown_output_usage_attempts']} attempts respectively. "
        "Reported sums exclude unknown usage and are not whole-run cost estimates.",
        "",
        f"Stop reason: `{bundle['stop_reason']}`.",
        f"Snippet actions: {bundle['steps']} / {bundle['limits']['max_steps']}.",
        f"Active excerpt characters: {context['characters']} / {context['max_chars']}.",
        f"Discovery truncated: `{scan['truncated']}`. "
        f"Retained candidates: {len(bundle['candidates'])} / {scan['candidate_total']} discovered; "
        f"candidate truncation: `{scan['candidate_truncated']}`.",
        f"Discovery attempted {scan['scanned_files']} file reads and read "
        f"{scan['scanned_bytes']} bytes. Skipped entries: `{dict(scan['skipped'])}`.",
        f"Deferred retained candidates: {len(bundle['deferred_candidate_ids'])}. "
        f"Each source excerpt is capped at {bundle['limits']['max_excerpt_chars']} characters.",
        "",
        "## Observations",
        "",
    ]
    if not bundle["observations"]:
        lines.extend(["No source observations were collected.", ""])
    for observation in bundle["observations"]:
        path = observation["path"]
        label = path.replace("[", "\\[").replace("]", "\\]")
        target = str(Path(bundle["repo"]) / path).replace("<", "%3C").replace(">", "%3E")
        lines.extend(
            [
                f"### {observation['id']}",
                "",
                f"Source: [{label}:{observation['start_line']}]"
                f"(<{target}:{observation['start_line']}>)",
                f"Source SHA-256: `{observation['source_sha256']}`.",
                f"Validity at final check: `{observation['validity']}`.",
                "",
            ]
        )
        longest = max((len(match) for match in re.findall(r"`+", observation["text"])), default=0)
        fence = "`" * max(3, longest + 1)
        lines.extend([fence + "text", observation["text"].rstrip("\n"), fence, ""])
    lines.extend(
        [
            "## Policy decisions",
            "",
            "Confidence describes the provider's choice distribution; "
            "it is not the probability of solving the task.",
            "",
        ]
    )
    for decision in bundle["decisions"]:
        lines.append(
            f"- Step {decision['step']}: `{decision['backend']}` selected "
            f"`{decision['candidate_id']}`; "
            f"fallback: `{decision['fallback_reason']}`; "
            f"provider attempts: {len(decision['attempts'])}."
        )
    lines.extend(
        [
            "",
            "## Limits and follow-up",
            "",
            "Candidates come from filename and keyword matching. Missing candidates, "
            "skipped files, and the action budget can prevent relevant evidence from being found.",
            "Context eviction and truncation affect only the active projection. "
            "Raw observations remain in events.jsonl and evidence.json.",
            "Source hashes describe snapshots; re-check sources before using these observations "
            "to make changes. No compilation, tests, or patches were performed. "
            "Remote policy calls, when enabled, select existing candidates and do not verify code.",
            "Provider request bodies are recorded in evidence.json and events.jsonl; "
            "authentication headers and raw error bodies are not recorded.",
            "",
        ]
    )
    return "\n".join(lines)


def investigate(
    repo: Path,
    task: str,
    output: Path,
    max_steps: int = 8,
    max_context_chars: int = 12000,
    policy: Policy | None = None,
) -> InvestigationResult:
    """Inspect bounded snippets, with complete raw evidence and no repository writes."""
    if not task.strip():
        raise ValueError("Task must not be empty.")
    if any(
        isinstance(budget, bool) or not isinstance(budget, int) or budget < 1
        for budget in (max_steps, max_context_chars)
    ):
        raise ValueError("Step and context budgets must be positive integers.")
    policy = RulePolicy() if policy is None else policy
    with SafeRepository(Path(repo)) as repository:
        destination = _prepare_output(Path(output), repository.root)
        return _run_investigation(
            repository, task, destination, max_steps, max_context_chars, policy
        )


def _run_investigation(
    repository,
    task: str,
    destination: Path,
    max_steps: int,
    max_context_chars: int,
    policy: Policy,
    *,
    frontier: tuple[list[ActionCandidate], list[str]] | None = None,
    source_mode: str = "live",
    snapshot_id: str | None = None,
) -> InvestigationResult:
    """Execute a live or prepared frontier in an already validated output directory."""
    if source_mode not in {"live", "frozen"}:
        raise ValueError("Unsupported investigation source mode.")
    if source_mode == "frozen" and snapshot_id is None:
        raise ValueError("Frozen investigation requires a snapshot identity.")
    describe = getattr(policy, "describe", None)
    policy_config = describe() if callable(describe) else {"name": type(policy).__name__}
    events = EventLog(destination / "events.jsonl")
    try:
        events.emit(
            "investigation_started",
            repo=str(repository.root),
            task=task,
            max_steps=max_steps,
            max_context_chars=max_context_chars,
            policy=type(policy).__name__,
            policy_config=policy_config,
            source_mode=source_mode,
            snapshot_id=snapshot_id,
        )
        candidates, terms = repository.discover(task) if frontier is None else frontier
        events.emit(
            "candidates_discovered",
            terms=terms,
            scan=repository.stats,
            candidates=[candidate.to_dict() for candidate in candidates],
        )
        by_id = {candidate.id: candidate for candidate in candidates}
        seen, observations, active, evicted, decisions = set(), [], [], [], []
        steps, stop_reason = 0, "no_candidates"
        while candidates and steps < max_steps:
            if len(seen) == len(candidates):
                stop_reason = "candidates_exhausted"
                break
            state = DecisionState(
                task, steps, max_steps, frozenset(seen), tuple(active), max_context_chars
            )
            selection = policy.choose(state, tuple(candidates))
            decision = (
                selection
                if isinstance(selection, PolicyDecision)
                else PolicyDecision(
                    selection,
                    "rule" if isinstance(policy, RulePolicy) else type(policy).__name__,
                )
            )
            decision_record = {"step": steps + 1, **asdict(decision)}
            decisions.append(decision_record)
            events.emit("policy_decision", **decision_record)
            chosen = decision.candidate_id
            if chosen is None:
                stop_reason = "policy_stopped"
                break
            if chosen not in by_id or chosen in seen:
                events.emit(
                    "decision_rejected",
                    candidate_id=chosen,
                    reason="unknown_or_repeated_candidate",
                )
                stop_reason = "invalid_policy_choice"
                break
            candidate = by_id[chosen]
            seen.add(chosen)
            steps += 1
            events.emit("action_selected", step=steps, candidate=candidate.to_dict())
            try:
                source = repository.read(candidate.args.path)
            except SkippedFile as exc:
                events.emit("action_skipped", candidate_id=chosen, reason=str(exc))
                continue
            if source.sha256 != candidate.args.expected_sha256:
                events.emit(
                    "action_skipped",
                    candidate_id=chosen,
                    reason="source_changed",
                    current_sha256=source.sha256,
                )
                continue
            args = candidate.args
            raw = "".join(
                source.text.splitlines(keepends=True)[args.start_line - 1 : args.end_line]
            )
            observation = {
                "id": f"o{len(observations) + 1:04}",
                "kind": "observation",
                "candidate_id": chosen,
                "path": args.path,
                "start_line": args.start_line,
                "end_line": args.end_line,
                "source_sha256": source.sha256,
                "text": raw[: args.max_chars],
                "excerpt_truncated": len(raw) > args.max_chars,
                "validity": "matched_at_read",
            }
            observations.append(observation)
            events.emit("observation_recorded", observation=observation)
            _add_context(active, observation, max_context_chars, events, evicted)
        else:
            if candidates:
                stop_reason = (
                    "candidates_exhausted"
                    if len(seen) == len(candidates)
                    else "step_budget_exhausted"
                )
        for observation in observations:
            try:
                current = repository.read(observation["path"])
                observation["current_sha256"] = current.sha256 if source_mode == "live" else None
                if source_mode == "frozen":
                    observation["checked_snapshot_sha256"] = current.sha256
                observation["validity"] = (
                    (
                        "matched_frozen_snapshot"
                        if source_mode == "frozen"
                        else "current_at_final_check"
                    )
                    if current.sha256 == observation["source_sha256"]
                    else "changed"
                )
            except SkippedFile:
                observation["current_sha256"] = None
                observation["validity"] = "unavailable"
            events.emit(
                "source_revalidated",
                observation_id=observation["id"],
                validity=observation["validity"],
                current_sha256=observation["current_sha256"],
                source_mode=source_mode,
            )
        bundle = {
            "schema_version": 2,
            "source_mode": source_mode,
            "snapshot_id": snapshot_id,
            "repo": str(repository.root),
            "task": task,
            "policy": type(policy).__name__,
            "policy_config": policy_config,
            "decisions": decisions,
            "policy_accounting": _policy_accounting(decisions),
            "stop_reason": stop_reason,
            "steps": steps,
            "limits": {
                "max_steps": max_steps,
                "max_context_chars": max_context_chars,
                "max_excerpt_chars": 4000,
                "max_file_bytes": MAX_FILE_BYTES,
                "max_scan_bytes": MAX_SCAN_BYTES,
                "max_scan_files": MAX_SCAN_FILES,
                "max_scan_entries": MAX_SCAN_ENTRIES,
                "max_candidates": MAX_CANDIDATES,
            },
            "scan": repository.stats,
            "terms": terms,
            "candidates": [c.to_dict() for c in candidates],
            "deferred_candidate_ids": [c.id for c in candidates if c.id not in seen],
            "observations": observations,
            "context": {
                "max_chars": max_context_chars,
                "characters": sum(len(entry.text) for entry in active),
                "active": [asdict(entry) for entry in active],
                "evicted_ids": evicted,
            },
        }
        with (destination / "evidence.json").open("x", encoding="utf-8") as evidence_file:
            evidence_file.write(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n")
        with (destination / "report.md").open("x", encoding="utf-8") as report_file:
            report_file.write(_render_report(bundle))
        events.emit(
            "investigation_finished",
            stop_reason=stop_reason,
            steps=steps,
            observations=len(observations),
            active_chars=bundle["context"]["characters"],
        )
        return InvestigationResult(destination, stop_reason, steps, len(observations))
    finally:
        events.close()
