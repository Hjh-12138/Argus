"""Read-only current-source snapshot bundle for AgentTeams real Worker audits.

Uses only read-only Git commands to inventory tracked, modified, untracked and
deleted paths, applies a deterministic exclusion policy, and streams the
included files into an immutable ZIP with stable ordering and timestamps. The
target workspace is never mutated: no checkout/clean/add/reset, no dependency
install, no build, and no execution of target code.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from core.snapshot import _language_of, _sha256

DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".git/**",
    "node_modules/**",
    "**/__pycache__/**",
    "**/.pytest_cache/**",
    "**/*.pyc",
    ".pytest-tmp-*/**",
    "**/.pytest-tmp-*/**",
    ".edge-diagnostic-profile*/**",
    "**/.edge-diagnostic-profile*/**",
    ".web-test-data/**",
    "tmp-*/**",
    "**/tmp-*/**",
    "tmp-video-*/**",
    "**/tmp-video-*/**",
    "dist/**",
    "**/dist/**",
    "build/**",
    "**/build/**",
    "coverage/**",
    "**/coverage/**",
    "**/*.png",
    "**/*.mp4",
)

# Fixed ZIP timestamp (1980-02-01 00:00:00) for deterministic archives.
_ZIP_DATE_TIME = (1980, 2, 1, 0, 0, 0)


@dataclass(frozen=True)
class WorkspaceSnapshotFile:
    path: str
    sha256: str
    size: int
    language: str | None = None


@dataclass
class WorkspaceSnapshot:
    root: str
    snapshot_id: str
    files: tuple[WorkspaceSnapshotFile, ...] = ()
    deleted: tuple[str, ...] = ()
    created_at: str | None = None


@dataclass
class WorkspaceBundle:
    snapshot: WorkspaceSnapshot
    coverage: dict
    included: list[str] = field(default_factory=list)
    excluded: dict[str, str] = field(default_factory=dict)
    deleted: list[str] = field(default_factory=list)
    archive_path: str = ""
    archive_sha256: str = ""


class WorkspaceSnapshotBuilder:
    def __init__(self, excludes: tuple[str, ...] = DEFAULT_EXCLUDES):
        self._exclude_patterns = [
            (re.compile(_glob_to_regex(p)), p) for p in excludes
        ]

    def build(self, target: Path, output_zip: Path) -> WorkspaceBundle:
        root = target.resolve()
        tracked, modified, untracked, deleted = self._git_inventory(root)
        include_paths = self._resolve_included(root, tracked, modified, untracked)
        excluded: dict[str, str] = {}
        included: list[WorkspaceSnapshotFile] = []
        files_in_zip: list[str] = []
        for posix in sorted(include_paths):
            reason = self._excluded_reason(posix)
            if reason:
                excluded[posix] = reason
                continue
            full = root / PurePosixPath(posix)
            if not full.is_file() or full.is_symlink():
                excluded[posix] = "not-regular-file"
                continue
            try:
                data = full.read_bytes()
            except OSError:
                excluded[posix] = "unreadable"
                continue
            sha = hashlib.sha256(data).hexdigest()
            included.append(WorkspaceSnapshotFile(
                path=posix, sha256=sha, size=len(data),
                language=_language_of(full)))
            files_in_zip.append((posix, data))

        self._write_archive(output_zip, files_in_zip)
        archive_sha = hashlib.sha256(output_zip.read_bytes()).hexdigest()

        snapshot_id = hashlib.sha256(
            ("\n".join(f.path for f in included)).encode("utf-8")).hexdigest()[:16]
        snapshot = WorkspaceSnapshot(
            root=str(root), snapshot_id=snapshot_id,
            files=tuple(included), deleted=tuple(deleted),
            created_at=datetime.now(timezone.utc).isoformat() + "Z")
        coverage = {
            "files_included": len(included),
            "files_excluded": len(excluded),
            "paths_deleted": len(deleted),
            "exclusion_reasons": _count(excluded),
        }
        return WorkspaceBundle(
            snapshot=snapshot, coverage=coverage,
            included=[f.path for f in included],
            excluded=excluded, deleted=list(deleted),
            archive_path=str(output_zip), archive_sha256=archive_sha)

    def _git_inventory(self, root: Path) -> tuple[list[str], list[str], list[str], list[str]]:
        tracked = [t for t in self._git(root, ["ls-files", "-z"]).split("\0") if t]
        status = self._git(root, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
        modified: list[str] = []
        untracked: list[str] = []
        deleted: list[str] = []
        tokens = [t for t in status.split("\0") if t]
        index = 0
        while index < len(tokens):
            tok = tokens[index]
            if len(tok) < 3 or tok[2] != " ":
                index += 1
                continue
            status_code = tok[:2]
            path = tok[3:]
            if status_code[0] in "RC":
                index += 2
            else:
                index += 1
            if not path:
                continue
            if status_code == "??":
                untracked.append(path)
            elif status_code[0] == "D" or status_code[1] == "D":
                deleted.append(path)
            else:
                modified.append(path)
        return tracked, modified, untracked, deleted

    def _resolve_included(self, root: Path, tracked: list[str],
                          modified: list[str], untracked: list[str]) -> set[str]:
        tracked_set = set(tracked)
        include = set()
        for posix in tracked_set:
            if (root / PurePosixPath(posix)).is_file():
                include.add(posix)
        include.update(modified)
        include.update(untracked)
        return include

    def _excluded_reason(self, posix: str) -> str | None:
        for pattern, source in self._exclude_patterns:
            if pattern.match(posix):
                return source
        return None

    def _write_archive(self, output_zip: Path, files: list[tuple[str, bytes]]) -> None:
        output_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            for posix, data in sorted(files, key=lambda item: item[0]):
                info = zipfile.ZipInfo(posix, date_time=_ZIP_DATE_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, data)

    def _git(self, root: Path, args: list[str]) -> str:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
        return proc.stdout


def _glob_to_regex(pattern: str) -> str:
    """Convert an exclusion glob to an anchored regex over POSIX paths.

    `**/` matches zero or more leading directories so root-level files are
    also matched, and `**` matches across separators.
    """
    out = []
    index = 0
    length = len(pattern)
    while index < length:
        char = pattern[index]
        if char == "*":
            if pattern[index:index + 3] == "**/":
                out.append(r"(?:[^/]*/)*")
                index += 3
            elif pattern[index:index + 2] == "**":
                out.append(r".*")
                index += 2
            else:
                out.append(r"[^/]*")
                index += 1
        elif char == "?":
            out.append(r"[^/]")
            index += 1
        elif char == "[":
            end = pattern.find("]", index)
            if end == -1:
                out.append(re.escape(char))
                index += 1
            else:
                out.append(pattern[index:end + 1])
                index = end + 1
        else:
            out.append(re.escape(char))
            index += 1
    return "^" + "".join(out) + "$"


def _count(excluded: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for reason in excluded.values():
        counts[reason] = counts.get(reason, 0) + 1
    return counts
