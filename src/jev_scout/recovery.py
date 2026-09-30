"""Restore retained observations into a fresh, version-checked working context."""

import hashlib
import json
import os
import re
import stat
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from .artifacts import prepare_output
from .investigator import EventLog, _add_context
from .repository import IGNORED_DIRS, MAX_CANDIDATES, MAX_FILE_BYTES, SafeRepository, SkippedFile

MAX_IMPORT_BYTES = 16 * 1024 * 1024
MAX_EXCERPT_CHARS = 4000
OUTPUT_NAMES = ("recovery.json", "events.jsonl", "report.md")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_OBSERVATION_ID = re.compile(r"o[0-9]{4}\Z")
_CANDIDATE_ID = re.compile(r"c[0-9]{4}\Z")
_ORIGINAL_VALIDITIES = {
    "matched_at_read",
    "current_at_final_check",
    "matched_frozen_snapshot",
    "changed",
    "unavailable",
}


@dataclass(frozen=True)
class RecoveryResult:
    """Counts cover requested records and fresh records, including later evictions."""

    output_dir: Path
    requested: int
    recovered: int

    @property
    def recovery_path(self) -> Path:
        return self.output_dir / "recovery.json"

    @property
    def events_path(self) -> Path:
        return self.output_dir / "events.jsonl"

    @property
    def report_path(self) -> Path:
        return self.output_dir / "report.md"


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Evidence JSON contains a duplicate object key.")
        result[key] = value
    return result


def _reject_constant(_value: str):
    raise ValueError("Evidence JSON contains a non-finite number.")


def _load_evidence(path: Path) -> tuple[dict, str]:
    """Bound reads independently of stat size and never open a final symlink or FIFO."""
    if not hasattr(os, "O_NOFOLLOW"):
        raise ValueError("Safe evidence imports require POSIX no-follow open.")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Evidence input must be a regular, non-symlink file.")
        if before.st_size > MAX_IMPORT_BYTES:
            raise ValueError("Evidence input exceeds the import byte limit.")
        chunks, remaining = [], MAX_IMPORT_BYTES + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        if len(raw) > MAX_IMPORT_BYTES:
            raise ValueError("Evidence input exceeds the import byte limit.")
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("Evidence input changed during import.")
    finally:
        os.close(descriptor)
    try:
        bundle = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("Evidence input must contain bounded, valid UTF-8 JSON.") from exc
    if not isinstance(bundle, dict):
        raise ValueError("Evidence input must be a JSON object.")
    return bundle, hashlib.sha256(raw).hexdigest()


def _valid_string(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _safe_path(value: object) -> bool:
    if not _valid_string(value) or not value or len(value) > 4096:
        return False
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and bool(path.parts)
        and str(path) == value
        and ".." not in path.parts
        and "\\" not in value
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
        and not any(
            component in IGNORED_DIRS or SafeRepository._excluded_name(component)
            for component in path.parts
        )
    )


def _validated_observations(bundle: dict) -> dict[str, dict]:
    if type(bundle.get("schema_version")) is not int or bundle["schema_version"] not in (1, 2):
        raise ValueError("Recovery supports investigation evidence schemas 1 and 2.")
    observations = bundle.get("observations")
    if not isinstance(observations, list) or len(observations) > MAX_CANDIDATES:
        raise ValueError("Evidence observations must be a bounded list.")
    result = {}
    for observation in observations:
        if not isinstance(observation, dict):
            raise ValueError("Each evidence observation must be an object.")
        identifier = observation.get("id")
        if (
            not isinstance(identifier, str)
            or not _OBSERVATION_ID.fullmatch(identifier)
            or identifier == "o0000"
            or identifier in result
        ):
            raise ValueError("Evidence observation IDs must be canonical and unique.")
        if observation.get("kind") != "observation" or not _safe_path(observation.get("path")):
            raise ValueError("Evidence contains an unsupported observation or unsafe source path.")
        start, end = observation.get("start_line"), observation.get("end_line")
        if not (
            type(start) is int and type(end) is int and 1 <= start <= end <= MAX_FILE_BYTES + 1
        ):
            raise ValueError("Evidence source line spans must contain bounded positive integers.")
        source_hash, text = observation.get("source_sha256"), observation.get("text")
        if not isinstance(source_hash, str) or not _HASH.fullmatch(source_hash):
            raise ValueError("Evidence source hashes must be lowercase SHA-256 values.")
        if not _valid_string(text) or len(text) > MAX_EXCERPT_CHARS or "\0" in text:
            raise ValueError("Evidence excerpts must be bounded UTF-8 strings without NUL bytes.")
        if type(observation.get("excerpt_truncated")) is not bool:
            raise ValueError("Evidence excerpt truncation must be a boolean.")
        record = {
            field: observation[field]
            for field in (
                "id",
                "kind",
                "path",
                "start_line",
                "end_line",
                "source_sha256",
                "text",
                "excerpt_truncated",
            )
        }
        if "candidate_id" in observation:
            candidate = observation["candidate_id"]
            if not isinstance(candidate, str) or not _CANDIDATE_ID.fullmatch(candidate):
                raise ValueError("Evidence candidate IDs must be canonical.")
            record["candidate_id"] = candidate
        if "validity" in observation:
            validity = observation["validity"]
            if not isinstance(validity, str) or validity not in _ORIGINAL_VALIDITIES:
                raise ValueError("Evidence historical validity is unsupported.")
            record["original_validity"] = validity
        if "current_sha256" in observation:
            current_hash = observation["current_sha256"]
            if current_hash is not None and (
                not isinstance(current_hash, str) or not _HASH.fullmatch(current_hash)
            ):
                raise ValueError("Evidence historical source hashes must be SHA-256 or null.")
            record["original_current_sha256"] = current_hash
        result[identifier] = record
    return result


def _revalidate(observation: dict, repository: SafeRepository) -> dict:
    record = dict(observation)
    try:
        source = repository.read(record["path"])
    except SkippedFile as exc:
        record.update(validity="unavailable", current_sha256=None, source_check_reason=str(exc))
        return record
    record["current_sha256"] = source.sha256
    if source.sha256 != record["source_sha256"]:
        record.update(validity="changed", source_check_reason="source_hash_changed")
        return record
    lines = source.text.splitlines(keepends=True)
    raw = "".join(lines[record["start_line"] - 1 : record["end_line"]])
    if (
        record["end_line"] > max(1, len(lines))
        or raw[:MAX_EXCERPT_CHARS] != record["text"]
        or (len(raw) > MAX_EXCERPT_CHARS) != record["excerpt_truncated"]
    ):
        record.update(validity="excerpt_mismatch", source_check_reason="recorded_excerpt_mismatch")
    else:
        record.update(validity="current_at_recovery_check", source_check_reason=None)
    return record


def _render_report(bundle: dict) -> str:
    context = bundle["context"]
    lines = [
        "# Evidence recovery report",
        "",
        "This is a fresh context handoff of retained observations, not an investigation resume.",
        "Historical artifact content is not authenticated. Current records were checked "
        "against the explicitly supplied repository at recovery time.",
        "",
        f"Input artifact SHA-256: `{bundle['origin']['sha256']}`.",
        f"Requested records: {len(bundle['requested_observation_ids'])}; "
        f"fresh records: {bundle['recovered']}; active records: {len(context['active'])}.",
        f"Active excerpt characters: {context['characters']} / {context['max_chars']}.",
        f"Context-evicted records: {', '.join(context['evicted_ids']) or 'none'}.",
        "Changed, unavailable, and mismatching records remain below but are omitted "
        "from the active context.",
        "",
        "## Historical observations and fresh checks",
        "",
    ]
    for observation in bundle["observations"]:
        label = observation["path"].replace("[", "\\[").replace("]", "\\]")
        target = (
            str(Path(bundle["repo"]) / observation["path"]).replace("<", "%3C").replace(">", "%3E")
        )
        longest = max((len(match) for match in re.findall(r"`+", observation["text"])), default=0)
        fence = "`" * max(3, longest + 1)
        lines.extend(
            [
                f"### {observation['id']}",
                "",
                f"Source: [{label}:{observation['start_line']}]"
                f"(<{target}:{observation['start_line']}>)",
                f"Historical source SHA-256: `{observation['source_sha256']}`.",
                f"Validity at recovery check: `{observation['validity']}`.",
                f"Excerpt truncated when collected: `{observation['excerpt_truncated']}`.",
                "",
                fence + "text",
                observation["text"].rstrip("\n"),
                fence,
                "",
            ]
        )
    lines.extend(
        [
            "## Active context",
            "",
            "Active entries follow the caller's requested order with FIFO eviction. "
            "Truncation and eviction affect the active projection only; historical excerpts "
            "remain in recovery.json and events.jsonl.",
            "",
        ]
    )
    for entry in context["active"]:
        lines.append(
            f"- `{entry['observation_id']}`: {len(entry['text'])} characters; "
            f"context truncated: `{entry['truncated']}`."
        )
    lines.extend(
        [
            "",
            "No source edits, code execution, or provider calls were performed. "
            "Freshness checks are point-in-time checks, not root-cause verification.",
            "",
        ]
    )
    return "\n".join(lines)


def recover(
    evidence: Path,
    repo: Path,
    observation_ids: Sequence[str],
    output: Path,
    max_context_chars: int = 12000,
) -> RecoveryResult:
    """Recover explicit records without following paths or instructions from the artifact."""
    if type(max_context_chars) is not int or max_context_chars < 1:
        raise ValueError("Recovery context budget must be a positive integer.")
    if isinstance(observation_ids, (str, bytes)) or not isinstance(observation_ids, Sequence):
        raise ValueError("Recovery requires an ordered sequence of observation IDs.")
    requested = list(observation_ids)
    if not requested or len(requested) > MAX_CANDIDATES:
        raise ValueError("Recovery requires between 1 and 100 observation IDs.")
    if any(not isinstance(identifier, str) for identifier in requested):
        raise ValueError("Requested observation IDs must be strings.")
    if len(set(requested)) != len(requested):
        raise ValueError("Requested observation IDs must be unique.")
    artifact_path = Path(evidence).expanduser().absolute()
    imported, digest = _load_evidence(artifact_path)
    by_id = _validated_observations(imported)
    if any(identifier not in by_id for identifier in requested):
        raise ValueError("A requested observation ID is absent from the evidence artifact.")
    with SafeRepository(Path(repo)) as repository:
        destination = prepare_output(Path(output), repository.root, OUTPUT_NAMES)
        events = EventLog(destination / "events.jsonl")
        try:
            origin = {
                "path": str(artifact_path),
                "sha256": digest,
                "schema_version": imported["schema_version"],
            }
            events.emit(
                "recovery_started",
                origin=origin,
                repo=str(repository.root),
                requested_observation_ids=requested,
                max_context_chars=max_context_chars,
                max_import_bytes=MAX_IMPORT_BYTES,
            )
            active, evicted, omitted, observations = [], [], [], []
            recovered = 0
            for identifier in requested:
                observation = _revalidate(by_id[identifier], repository)
                observations.append(observation)
                events.emit("historical_observation_recovered", observation=observation)
                if observation["validity"] == "current_at_recovery_check":
                    recovered += 1
                    _add_context(active, observation, max_context_chars, events, evicted)
                else:
                    omission = {"observation_id": identifier, "reason": observation["validity"]}
                    omitted.append(omission)
                    events.emit("context_omitted", **omission, raw_evidence_preserved=True)
            bundle = {
                "schema_version": 1,
                "artifact_type": "context_recovery",
                "origin": origin,
                "repo": str(repository.root),
                "requested_observation_ids": requested,
                "recovered": recovered,
                "observations": observations,
                "limits": {
                    "max_import_bytes": MAX_IMPORT_BYTES,
                    "max_observations": MAX_CANDIDATES,
                    "max_excerpt_chars": MAX_EXCERPT_CHARS,
                },
                "context": {
                    "max_chars": max_context_chars,
                    "characters": sum(len(entry.text) for entry in active),
                    "active": [asdict(entry) for entry in active],
                    "evicted_ids": evicted,
                    "omitted": omitted,
                },
            }
            with (destination / "recovery.json").open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n")
            with (destination / "report.md").open("x", encoding="utf-8") as stream:
                stream.write(_render_report(bundle))
            events.emit(
                "recovery_finished",
                requested=len(requested),
                recovered=recovered,
                active_chars=bundle["context"]["characters"],
                evicted_ids=evicted,
                omitted=omitted,
            )
            return RecoveryResult(destination, len(requested), recovered)
        finally:
            events.close()
