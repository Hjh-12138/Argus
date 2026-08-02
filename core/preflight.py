"""preflight：canonicalize 目标路径、manifest 检测、symlink 越界检测、API scope。

失败语义：不可恢复 → SystemExit(4)（system error，§8.3）。
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

MANIFEST_NAMES = ("package.json", "pyproject.toml", "go.mod", "requirements.txt",
                  "requirements.in", "Cargo.toml", "pom.xml", "build.gradle")


@dataclass
class PreflightResult:
    ok: bool = False
    canonical_root: Path | None = None
    manifest: bool = False
    language: str | None = None
    size_bytes: int = 0
    file_count: int = 0
    unsafe_links: list[str] = field(default_factory=list)
    error: str | None = None


def preflight(target: Path, cfg) -> PreflightResult:
    r = PreflightResult()
    try:
        canonical = target.resolve(strict=True)
    except (FileNotFoundError, OSError):
        print(f"[preflight] ERROR: target does not exist: {target}", file=sys.stderr)
        sys.exit(4)
    if not canonical.is_dir():
        print(f"[preflight] ERROR: target is not a directory: {canonical}", file=sys.stderr)
        sys.exit(4)
    r.canonical_root = canonical

    # symlink 越界检测：指向 canonical_root 之外的真实路径
    for p in canonical.rglob("*"):
        if p.is_symlink():
            try:
                real = p.resolve(strict=False)
            except OSError:
                real = None
            if real is not None and not _is_relative_to(real, canonical):
                r.unsafe_links.append(str(p.relative_to(canonical)))

    r.manifest = any((canonical / n).exists() for n in MANIFEST_NAMES)
    r.language = _detect_language(canonical)
    files = [p for p in canonical.rglob("*") if p.is_file() and not p.is_symlink()]
    r.file_count = len(files)
    r.size_bytes = sum(p.stat().st_size for p in files)
    r.ok = True
    return r


def _detect_language(root: Path) -> str | None:
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
        return "python"
    if (root / "package.json").exists():
        return "javascript"
    if (root / "go.mod").exists():
        return "go"
    if (root / "Cargo.toml").exists():
        return "rust"
    return None


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False
