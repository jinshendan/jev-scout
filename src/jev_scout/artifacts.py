"""Shared output boundaries for investigation, recovery, and comparison artifacts."""

from collections.abc import Sequence
from pathlib import Path


def prepare_output(
    output: Path,
    repo: Path,
    names: Sequence[str] = ("events.jsonl", "evidence.json", "report.md"),
) -> Path:
    """Resolve output outside the source scope and refuse existing named artifacts."""
    requested = Path(output).expanduser()
    if requested.is_symlink():
        raise ValueError("Output directory must not be a symlink.")
    try:
        resolved = requested.resolve()
    except RuntimeError as exc:
        raise ValueError("Output path contains a symlink loop.") from exc
    if resolved == repo or resolved.is_relative_to(repo):
        raise ValueError("Output must be outside the investigated repository.")
    for ancestor in (resolved, *resolved.parents):
        if ancestor.exists() and ancestor.samefile(repo):
            raise ValueError("Output must be outside the investigated repository.")
    for name in names:
        if not name or Path(name).name != name or name in {".", ".."}:
            raise ValueError("Artifact names must be single path components.")
    resolved.mkdir(parents=True, exist_ok=True)
    for name in names:
        if (resolved / name).exists() or (resolved / name).is_symlink():
            raise ValueError(f"Output already contains {name}; choose a fresh directory.")
    return resolved
