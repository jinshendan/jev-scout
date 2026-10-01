"""Shared point-in-time hash and exact-excerpt checks for retained evidence."""

from .repository import SkippedFile

MAX_EXCERPT_CHARS = 4000


def revalidate_excerpt(
    observation: dict,
    repository,
    *,
    max_excerpt_chars: int = MAX_EXCERPT_CHARS,
    source_mode: str = "live",
    current_label: str = "current_at_recovery_check",
) -> dict:
    record = dict(observation)
    try:
        source = repository.read(record["path"])
    except SkippedFile as exc:
        record.update(validity="unavailable", current_sha256=None, source_check_reason=str(exc))
        return record
    record["current_sha256"] = source.sha256 if source_mode == "live" else None
    if source_mode == "frozen":
        record["checked_snapshot_sha256"] = source.sha256
    if source.sha256 != record["source_sha256"]:
        record.update(validity="changed", source_check_reason="source_hash_changed")
        return record
    lines = source.text.splitlines(keepends=True)
    raw = "".join(lines[record["start_line"] - 1 : record["end_line"]])
    if (
        record["end_line"] > max(1, len(lines))
        or raw[:max_excerpt_chars] != record["text"]
        or (len(raw) > max_excerpt_chars) != record["excerpt_truncated"]
    ):
        record.update(validity="excerpt_mismatch", source_check_reason="recorded_excerpt_mismatch")
    else:
        record.update(
            validity="matched_frozen_snapshot" if source_mode == "frozen" else current_label,
            source_check_reason=None,
        )
    return record
