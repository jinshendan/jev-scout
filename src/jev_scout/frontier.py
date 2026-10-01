"""One admission limit and candidate-ID allocator for every runtime action kind."""

from collections.abc import Sequence

from .models import ActionCandidate, ReadSnippetArgs, RestoreObservationArgs
from .repository import MAX_CANDIDATES


class CandidateRegistry:
    def __init__(self, initial: Sequence[ActionCandidate]):
        if len(initial) > MAX_CANDIDATES:
            raise ValueError("Initial candidate frontier exceeds the candidate limit.")
        self.by_id = {candidate.id: candidate for candidate in initial}
        if len(self.by_id) != len(initial):
            raise ValueError("Initial candidate IDs must be unique.")
        self._next_id = len(initial) + 1

    @property
    def full(self) -> bool:
        return len(self.by_id) >= MAX_CANDIDATES

    def add(
        self,
        kind: str,
        args: ReadSnippetArgs | RestoreObservationArgs,
        score: int,
        reasons: tuple[str, ...],
        preview: str,
    ) -> ActionCandidate | None:
        if self.full:
            return None
        candidate_id = f"c{self._next_id:04}"
        while candidate_id in self.by_id:
            self._next_id += 1
            candidate_id = f"c{self._next_id:04}"
        self._next_id += 1
        candidate = ActionCandidate(candidate_id, kind, args, score, reasons, preview)
        self.by_id[candidate_id] = candidate
        return candidate
