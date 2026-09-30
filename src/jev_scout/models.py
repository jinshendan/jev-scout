"""Typed action contracts shared by deterministic and future provider policies."""

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ReadSnippetArgs:
    path: str
    start_line: int
    end_line: int
    expected_sha256: str
    max_chars: int = 4000


@dataclass(frozen=True)
class ActionCandidate:
    id: str
    kind: str
    args: ReadSnippetArgs
    score: int
    reasons: tuple[str, ...]
    preview: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ContextEntry:
    observation_id: str
    text: str
    truncated: bool


@dataclass(frozen=True)
class DecisionState:
    task: str
    step: int
    max_steps: int
    seen_candidate_ids: frozenset[str]
    active_context: tuple[ContextEntry, ...]
    max_context_chars: int


class Policy(Protocol):
    """Select an existing complete action; None ends investigation."""

    def choose(self, state: DecisionState, candidates: Sequence[ActionCandidate]) -> str | None: ...


class RulePolicy:
    """Prefer lexical relevance, with stable candidate IDs as a tie breaker."""

    def choose(self, state: DecisionState, candidates: Sequence[ActionCandidate]) -> str | None:
        remaining = [c for c in candidates if c.id not in state.seen_candidate_ids]
        if not remaining:
            return None
        return min(remaining, key=lambda c: (-c.score, c.id)).id


@dataclass(frozen=True)
class InvestigationResult:
    output_dir: Path
    stop_reason: str
    steps: int
    observations: int

    @property
    def events_path(self) -> Path:
        return self.output_dir / "events.jsonl"

    @property
    def evidence_path(self) -> Path:
        return self.output_dir / "evidence.json"

    @property
    def report_path(self) -> Path:
        return self.output_dir / "report.md"
