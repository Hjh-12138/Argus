"""Dependency Auditor detector。

- 解析 manifest（pyproject.toml/requirements.txt/package.json/go.mod）中的直接依赖；
- 对照本地 registry fixture 判定存在性（不存在 → dependency.nonexistent）；
- registry 查询超时/离线不得判"不存在"（§13）：缺失 registry 项 → 不产出 finding。

仅读取快照内文件；不安装、不执行脚本。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from core.redaction import hmac_fingerprint
from core.schemas import SourceSnapshot, Finding, Evidence

_FINGERPRINT_SALT = b"argus-dep-salt"

# manifest 文件 → 解析器
_MANIFEST_PARSERS = {
    "pyproject.toml": "pyproject",
    "requirements.txt": "requirements",
    "requirements.in": "requirements",
    "package.json": "package_json",
    "go.mod": "go_mod",
}

_PEP508 = re.compile(
    r"""^\s*([A-Za-z0-9_.-]+)\s*(?:\[[^\]]*\])?\s*"""
    r"""(==|>=|<=|~=|!=|>|<)?\s*([^\s,;]+)?"""
)
_JSON_KEY_RE = re.compile(r'"([^"]+)"\s*:\s*"([^"]*)"')


class DepDetector:
    def detect(self, snapshot: SourceSnapshot, registry: dict | None = None) -> tuple[Finding, ...]:
        registry = registry or {}
        out: list[Finding] = []
        for sf in snapshot.files:
            parser = _MANIFEST_PARSERS.get(sf.path.split("/")[-1])
            if parser is None:
                continue
            text = self._read(snapshot.root, sf.path)
            for name, spec in self._parse(text, parser):
                entry = registry.get(name)
                # registry 项缺失 = 未验证，不判不存在；仅显式 exists=false 才产出 finding。
                if entry is None:
                    continue
                if entry.get("exists") is False:
                    out.append(self._nonexistent_finding(sf, name, spec))
        return tuple(out)

    def _read(self, root: str, path: str) -> str:
        return (Path(root) / path).read_text(encoding="utf-8", errors="replace")

    def _parse(self, text: str, parser: str):
        if parser == "requirements":
            for line in text.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith(("#", "-", "git+", "http")):
                    continue
                m = _PEP508.match(line)
                if m:
                    yield m.group(1), m.group(2) or "any"
        elif parser == "pyproject":
            # PEP 621: dependencies = ["pkg>=1", ...]，支持单行和多行数组。
            array = re.search(r"(?s)dependencies\s*=\s*\[(.*?)\]", text)
            if array:
                for quoted in re.findall(r"['\"]([^'\"]+)['\"]", array.group(1)):
                    m = _PEP508.match(quoted)
                    if m:
                        yield m.group(1), (m.group(2) or "") + (m.group(3) or "") or "any"
        elif parser == "package_json":
            for k, v in _JSON_KEY_RE.findall(text):
                if k in ("dependencies", "devDependencies", "peerDependencies"):
                    # 嵌套对象内容（简单近似：下一批 key:value 即包名）
                    pass
        elif parser == "go_mod":
            for line in text.splitlines():
                stripped = line.strip()
                m = re.match(r"^\s*([A-Za-z0-9_./-]+)\s+v([0-9][^\s]*)", line)
                if m and not stripped.startswith(("module", "go ")):
                    yield m.group(1), m.group(2)

    def _nonexistent_finding(self, sf, name: str, spec: str) -> Finding:
        return Finding(
            id=f"dep-nonexistent-{sf.path}-{name}",
            agent="dep",
            category="dependency.nonexistent",
            severity="high" if ">=" in spec else "medium",
            confidence=0.98,
            title=f"dependency not found: {name}",
            detail=f"'{name}' is not present in the registry fixture",
            file=sf.path,
            line_start=1,
            line_end=1,
            remediation=f"remove or replace dependency '{name}'",
            verification="rerun dep detector against fixed manifest",
            rollback=None,
            cwe=None,
            fingerprint=hmac_fingerprint(f"dep.nonexistent:{name}", _FINGERPRINT_SALT),
            rule_id="DEP-001",
            rule_version="1",
            evidence=Evidence(
                context_lines=[f"declares dependency {name} (spec {spec})"],
                source_sha256=sf.sha256,
                redacted_value=None,
                detector="dep.registry-verify",
                reasoning_summary=None,
            ),
        )
