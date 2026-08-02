"""secret/PII 脱敏与 HMAC fingerprint。

- redact(): 从文本中掩码常见 secret 形态，输出不包含原始值。
- hmac_fingerprint(): 带项目级 salt 的 HMAC-SHA256，用于稳定跨运行指纹，
  避免直接截断 secret 裸 SHA-256（降低离线猜测风险，设计文档 §9.3.5）。
"""
from __future__ import annotations

import hashlib
import hmac
import re

_SECRET_PATTERNS = [
    re.compile(r"""(?i)(api[_-]?key|secret|token|password|passwd)\s*[=:]\s*['"]?([^'"\s,]{6,})"""),
    re.compile(r"(?i)\b(sk-[A-Za-z0-9_-]{8,})\b"),
    re.compile(r"(?i)\b(AKIA[0-9A-Z]{16})\b"),
    re.compile(r"(?i)\b(ghp_[A-Za-z0-9]{20,})\b"),
]


def redact(text: str) -> str:
    """掩码常见 secret。返回文本不含原始 secret 值。"""
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub(_mask, out)
    return out


def _mask(m: re.Match) -> str:
    if m.lastindex == 2:
        # key=value 形式：只掩码 value
        return m.group(1) + "=" * (m.group(0).count("=")) + "'***'" if "=" in m.group(0) \
            else f"{m.group(1)}: ***"
    return "***"


def hmac_fingerprint(raw: str, salt: bytes) -> str:
    """带 salt 的 HMAC-SHA256 指纹（hex）。"""
    return hmac.new(salt, raw.encode("utf-8"), hashlib.sha256).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
