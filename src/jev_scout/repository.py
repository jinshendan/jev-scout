"""Bounded lexical discovery and directory-relative, symlink-safe source reads."""

import hashlib
import os
import re
import stat
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .models import ActionCandidate, ReadSnippetArgs

MAX_FILE_BYTES = 256 * 1024
MAX_SCAN_BYTES = 32 * 1024 * 1024
MAX_SCAN_FILES = 2000
MAX_SCAN_ENTRIES = 10000
MAX_CANDIDATES = 100
CODE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".py",
    ".rs",
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".cs",
    ".m",
    ".mm",
    ".swift",
}
IGNORED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".aws",
    ".codex",
    ".agents",
    ".cache",
    ".venv",
    "venv",
    "node_modules",
    "vendor",
    "third_party",
    "third-party",
    "external",
    "deps",
    "dependencies",
    "__pycache__",
    "build",
    "dist",
    "target",
}
IGNORED_SUFFIXES = {
    ".pyc",
    ".o",
    ".a",
    ".so",
    ".dll",
    ".dylib",
    ".exe",
    ".zip",
    ".gz",
    ".png",
    ".jpg",
    ".jpeg",
    ".pdf",
    ".mp4",
    ".woff",
    ".lock",
    ".pem",
    ".key",
}
STOP_WORDS = set(
    "after and are before bug can code does error file find for from has have how "
    "into issue not occurs please project repo show source test that the their "
    "then this when where which why with would".split()
)


class SkippedFile(ValueError):
    """A source is unsafe, unavailable, too large, or not UTF-8 text."""

    def __init__(self, reason: str, byte_size: int = 0):
        super().__init__(reason)
        self.byte_size = byte_size


@dataclass(frozen=True)
class SourceFile:
    text: str
    sha256: str
    byte_size: int


class SafeRepository:
    def __init__(self, root: Path):
        requested = Path(root).expanduser()
        if requested.is_symlink():
            raise ValueError("Repository root must not be a symlink.")
        try:
            self.root = requested.resolve(strict=True)
        except RuntimeError as exc:
            raise ValueError("Repository path contains a symlink loop.") from exc
        if not self.root.is_dir():
            raise ValueError("Repository must be a directory.")
        if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
            raise ValueError("Safe repository reads require POSIX directory-relative open.")
        self._root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.stats = {
            "scanned_files": 0,
            "scanned_bytes": 0,
            "visited_entries": 0,
            "truncated": False,
            "candidate_total": 0,
            "candidate_truncated": False,
            "skipped": Counter(),
        }

    def __enter__(self):
        return self

    def __exit__(self, *_):
        os.close(self._root_fd)

    def _open_directory(self, relative: str) -> int:
        directory_fd = os.dup(self._root_fd)
        try:
            for component in PurePosixPath(relative).parts:
                next_fd = os.open(
                    component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd
                )
                os.close(directory_fd)
                directory_fd = next_fd
            return directory_fd
        except OSError:
            os.close(directory_fd)
            raise

    @staticmethod
    def _excluded_name(name: str) -> bool:
        return (
            name == ".env"
            or name.startswith(".env.")
            or Path(name).suffix.lower() in IGNORED_SUFFIXES
        )

    def _iter_files(self):
        """Never consume more directory entries than the global entry budget."""
        stack = [""]
        while stack:
            if self.stats["visited_entries"] >= MAX_SCAN_ENTRIES:
                self.stats["truncated"] = True
                return
            relative_dir = stack.pop()
            try:
                directory_fd = self._open_directory(relative_dir)
            except OSError:
                self.stats["skipped"]["unavailable_directory"] += 1
                continue
            dirs, files = [], []
            try:
                with os.scandir(directory_fd) as entries:
                    while self.stats["visited_entries"] < MAX_SCAN_ENTRIES:
                        try:
                            entry = next(entries)
                        except StopIteration:
                            break
                        self.stats["visited_entries"] += 1
                        try:
                            entry.name.encode("utf-8")
                            relative = str(PurePosixPath(relative_dir) / entry.name)
                            if entry.is_symlink():
                                self.stats["skipped"]["directory_or_symlink"] += 1
                            elif entry.is_dir(follow_symlinks=False):
                                if entry.name in IGNORED_DIRS or self._excluded_name(entry.name):
                                    self.stats["skipped"]["excluded_directory"] += 1
                                else:
                                    dirs.append(relative)
                            elif entry.is_file(follow_symlinks=False):
                                if self._excluded_name(entry.name):
                                    self.stats["skipped"]["excluded_name"] += 1
                                else:
                                    files.append(relative)
                            else:
                                self.stats["skipped"]["not_regular_file"] += 1
                        except UnicodeEncodeError:
                            self.stats["skipped"]["non_utf8_name"] += 1
                        except OSError:
                            self.stats["skipped"]["unavailable_entry"] += 1
            except OSError:
                self.stats["skipped"]["unavailable_directory"] += 1
            finally:
                os.close(directory_fd)
            if self.stats["visited_entries"] >= MAX_SCAN_ENTRIES:
                self.stats["truncated"] = True
            yield from sorted(files)
            if self.stats["truncated"]:
                return
            stack.extend(reversed(sorted(dirs)))

    def read(self, relative_path: str, max_bytes: int | None = None) -> SourceFile:
        path = PurePosixPath(relative_path)
        if (
            not relative_path
            or path.is_absolute()
            or ".." in path.parts
            or "\\" in relative_path
            or not path.parts
        ):
            raise SkippedFile("unsafe_path")
        directory_fd = os.dup(self._root_fd)
        file_fd = None
        try:
            for component in path.parts[:-1]:
                next_fd = os.open(
                    component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd
                )
                os.close(directory_fd)
                directory_fd = next_fd
            file_fd = os.open(
                path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd
            )
            info = os.fstat(file_fd)
            if not stat.S_ISREG(info.st_mode):
                raise SkippedFile("not_regular_file")
            if info.st_size > MAX_FILE_BYTES:
                raise SkippedFile("large_file")
            read_limit = min(MAX_FILE_BYTES, max_bytes) if max_bytes is not None else MAX_FILE_BYTES
            if info.st_size > read_limit:
                raise SkippedFile("scan_byte_budget")
            chunks = []
            remaining = read_limit
            while remaining:
                chunk = os.read(file_fd, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            final_info = os.fstat(file_fd)
            if (info.st_size, info.st_mtime_ns) != (final_info.st_size, final_info.st_mtime_ns):
                raise SkippedFile("changed_during_read", len(raw))
            if b"\0" in raw:
                raise SkippedFile("binary_file", len(raw))
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise SkippedFile("non_utf8_file", len(raw)) from exc
            return SourceFile(text, hashlib.sha256(raw).hexdigest(), len(raw))
        except OSError as exc:
            raise SkippedFile("symlink_or_unavailable") from exc
        finally:
            if file_fd is not None:
                os.close(file_fd)
            os.close(directory_fd)

    def discover(self, task: str) -> tuple[list[ActionCandidate], list[str]]:
        terms = list(
            dict.fromkeys(
                term.lower()
                for term in re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", task)
                if term.lower() not in STOP_WORDS
            )
        )[:32]
        symbols = list(dict.fromkeys(re.findall(r"\b[A-Za-z_]\w*(?:::[A-Za-z_]\w*)+\b", task)))[:16]
        literal_patterns = [
            re.compile(r"(?<!\w)" + re.escape(symbol) + r"(?!\w)", re.I) for symbol in symbols
        ]
        ranked = []
        for relative in self._iter_files():
            if (
                self.stats["scanned_files"] >= MAX_SCAN_FILES
                or self.stats["scanned_bytes"] >= MAX_SCAN_BYTES
            ):
                self.stats["truncated"] = True
                break
            self.stats["scanned_files"] += 1
            try:
                source = self.read(relative, MAX_SCAN_BYTES - self.stats["scanned_bytes"])
            except SkippedFile as exc:
                self.stats["scanned_bytes"] += exc.byte_size
                self.stats["skipped"][str(exc)] += 1
                if str(exc) == "scan_byte_budget":
                    self.stats["truncated"] = True
                    break
                continue
            self.stats["scanned_bytes"] += source.byte_size
            lines = source.text.splitlines(keepends=True)
            path_hits = sum(term in relative.lower() for term in terms)
            hits = [
                (
                    i,
                    sum(term in line.lower() for term in terms),
                    sum(
                        bool(pattern.search(line)) * (len(symbols) - index)
                        for index, pattern in enumerate(literal_patterns)
                    ),
                )
                for i, line in enumerate(lines)
            ]
            content_hits = sum(count for _, count, _ in hits)
            literal_hits = sum(count for _, _, count in hits)
            if not path_hits and not content_hits and not literal_hits:
                continue
            best_line = min(hits, key=lambda item: (-item[2], -item[1], item[0]))[0] if hits else 0
            start = max(0, best_line - 4)
            end = min(len(lines), best_line + 5)
            args = ReadSnippetArgs(relative, start + 1, max(start + 1, end), source.sha256)
            code_bonus = 50 if Path(relative).suffix.lower() in CODE_SUFFIXES else 0
            ranked.append(
                (
                    100 * bool(literal_hits) + code_bonus + path_hits * 5 + min(content_hits, 20),
                    relative,
                    args,
                    (
                        f"Path keyword matches: {path_hits}",
                        f"Content keyword matches: {content_hits}",
                        f"Qualified symbol matches: {literal_hits}",
                        f"Source code preference: {code_bonus}",
                    ),
                    "".join(lines[start:end])[:240],
                )
            )
        return self._finalize(ranked), terms

    def _finalize(self, ranked) -> list[ActionCandidate]:
        self.stats["candidate_total"] = len(ranked)
        self.stats["candidate_truncated"] = len(ranked) > MAX_CANDIDATES
        ordered = sorted(ranked, key=lambda item: (-item[0], item[1]))[:MAX_CANDIDATES]
        return [
            ActionCandidate(f"c{i:04}", "read_snippet", args, score, reasons, preview)
            for i, (score, _, args, reasons, preview) in enumerate(ordered, 1)
        ]
