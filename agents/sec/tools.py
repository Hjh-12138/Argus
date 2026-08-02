"""Security Auditor 工具边界。

只读快照和规则；禁止主动攻击、源码外发、原始 secret 输出。
"""
from __future__ import annotations


def assert_safe_finding_payload(payload: dict) -> None:
    serialized = str(payload).lower()
    forbidden = ("private_reasoning", "raw_prompt", "raw_response", "api_key_raw")
    hit = [name for name in forbidden if name in serialized]
    if hit:
        raise ValueError(f"unsafe finding payload keys: {hit}")
