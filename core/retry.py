"""执行重试 + 节点级熔断（R3.1）。

超时 / 工具失败 / 输出格式不对：重试 N 次止损，仍失败则标熔断（CIRCUIT_OPEN），
绝不无限重试拖死链路（绝不允许一个 agent 卡住整个链路）。
熔断粒度 = 节点级（本次 run 的单个 agent），非类型级——不「sec 以后都熔断」。
"""
from __future__ import annotations

import time
from dataclasses import dataclass

DEFAULT_ATTEMPTS = 3   # 初始 1 次 + 重试 2 次
DEFAULT_DELAY_S = 1.0


@dataclass(frozen=True)
class RetryOutcome:
    ok: bool
    value: object
    attempts_used: int
    error: Exception | None


def run_with_retry(fn, *, attempts: int = DEFAULT_ATTEMPTS,
                   delay_s: float = DEFAULT_DELAY_S) -> RetryOutcome:
    """调用 fn，异常时重试至 attempts 次；重试耗尽返回失败结果。"""
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return RetryOutcome(ok=True, value=fn(), attempts_used=attempt,
                                error=None)
        except Exception as exc:  # noqa: BLE001 — 节点级隔离，吞掉单节点异常
            last = exc
            if attempt < attempts:
                time.sleep(delay_s)
    return RetryOutcome(ok=False, value=None, attempts_used=attempts, error=last)
