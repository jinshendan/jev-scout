"""Offer bounded, one-shot recall of evicted observations from this investigation."""

from .frontier import CandidateRegistry
from .models import ActionCandidate, ReadSnippetArgs, RestoreObservationArgs
from .repository import MAX_CANDIDATES

RESTORATION_ALGORITHM = "evicted-observations-v1"


def validate_max_restores(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_CANDIDATES:
        raise ValueError(
            f"Restoration candidate budget must be an integer from 0 to {MAX_CANDIDATES}."
        )


class RestorationFrontier:
    def __init__(self, registry: CandidateRegistry, max_restores: int = 0):
        validate_max_restores(max_restores)
        self.registry = registry
        self.max_restores = max_restores
        self.generated: list[ActionCandidate] = []
        self._considered: set[str] = set()
        self._suppressed = self._candidate_suppressed = self._restore_suppressed = 0

    def offer(self, observation: dict, original: ActionCandidate) -> ActionCandidate | None:
        identifier = observation["id"]
        if (
            self.max_restores == 0
            or identifier in self._considered
            or self.registry.by_id.get(original.id) != original
            or original.kind != "read_snippet"
            or not isinstance(original.args, ReadSnippetArgs)
            or observation["candidate_id"] != original.id
        ):
            return None
        self._considered.add(identifier)
        candidate_limit = self.registry.full
        restore_limit = len(self.generated) >= self.max_restores
        if candidate_limit or restore_limit:
            self._suppressed += 1
            self._candidate_suppressed += int(candidate_limit)
            self._restore_suppressed += int(restore_limit)
            return None
        candidate = self.registry.add(
            "restore_observation",
            RestoreObservationArgs(
                identifier,
                observation["path"],
                observation["start_line"],
                observation["end_line"],
                observation["source_sha256"],
                original.args.max_chars,
            ),
            -1,
            (
                f"Restore evicted observation {identifier} after source and excerpt revalidation",
                "One offer per observation; consumes the shared action budget",
            ),
            observation["text"][:240],
        )
        assert candidate is not None
        self.generated.append(candidate)
        return candidate

    def describe(self) -> dict:
        return {
            "enabled": self.max_restores > 0,
            "algorithm": RESTORATION_ALGORITHM,
            "max_restores": self.max_restores,
            "generated_candidates": len(self.generated),
            "suppressed_proposals": self._suppressed,
            "candidate_limit_suppressed_proposals": self._candidate_suppressed,
            "restore_limit_suppressed_proposals": self._restore_suppressed,
        }
