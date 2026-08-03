"""不可变源码快照：固定本次审计读取的文件集合与 SHA-256。

所有 Agent 读取同一快照；报告 path/line 指向快照而非工作区（§5.1）。
跳过 binary/vendor/generated/超大文件，并在 coverage 中体现。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from core.schemas import SourceSnapshot, SnapshotFile

_SKIP_EXTS = {
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".dylib", ".png", ".jpg", ".jpeg",
    ".gif", ".ico", ".bmp", ".webp", ".zip", ".gz", ".tar", ".7z", ".woff",
    ".woff2", ".ttf", ".eot", ".pdf", ".class", ".o", ".a",
}
_MAX_BYTES = 5 * 1024 * 1024
_SKIP_DIR_PARTS = {"node_modules", "vendor", ".git", ".venv", "venv", "__pycache__",
                   ".idea", ".vscode", "dist", "build", "target", ".pytest_cache"}
_CODE_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java",
              ".sql", ".yml", ".yaml", ".toml", ".json", ".md", ".sh", ".ps1"}


@dataclass
class Coverage:
    files_total: int
    files_scanned: int
    skip_reasons: dict[str, int]


class SnapshotBuilder:
    def build(self, target: Path) -> tuple[SourceSnapshot, Coverage]:
        root = target.resolve()
        files: list[SnapshotFile] = []
        skip: dict[str, int] = {}
        total = 0
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.is_symlink():
                continue
            rel = p.relative_to(root).as_posix()
            if any(part in _SKIP_DIR_PARTS for part in p.parts):
                continue
            total += 1
            size = p.stat().st_size
            if p.suffix.lower() in _SKIP_EXTS:
                skip["binary"] = skip.get("binary", 0) + 1
                continue
            if size > _MAX_BYTES:
                skip["oversize"] = skip.get("oversize", 0) + 1
                continue
            sha = _sha256(p)
            files.append(SnapshotFile(path=rel, sha256=sha, size=size,
                                      language=_language_of(p)))
        snapshot = SourceSnapshot(root=str(root), files=tuple(files), created_at=None)
        return snapshot, Coverage(files_total=total, files_scanned=len(files),
                                  skip_reasons=skip)


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _language_of(p: Path) -> str | None:
    return p.suffix.lstrip(".") if p.suffix in _CODE_EXTS else None


def build_snapshot(target: Path, cfg) -> SourceSnapshot:
    """便捷函数：丢弃 coverage，只返回快照（测试/工具使用）。"""
    snap, _ = SnapshotBuilder().build(target)
    return snap
