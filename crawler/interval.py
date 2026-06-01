"""限速 + 429 退避。

移植自 src/ts/CrawlInterval.ts。
- short: 用户设定的 interval × uniform(0.8, 1.2)
- long:  uniform(300, 360) 秒，用于触发 429 时的冷却
"""
from __future__ import annotations

import logging
import random
import time
from typing import Literal

from i18n import t

logger = logging.getLogger(__name__)


class CrawlInterval:
    def __init__(self, interval_sec: float, lang: str = "zh-CN") -> None:
        self.interval_sec = max(0.0, interval_sec)
        self._next_allowed_ts: float = 0.0
        self.lang = lang

    def wait(self) -> None:
        now = time.monotonic()
        if now < self._next_allowed_ts:
            sleep_for = self._next_allowed_ts - now
            time.sleep(sleep_for)

    def bump(self, kind: Literal["short", "long"] = "short") -> None:
        now = time.monotonic()
        if kind == "short":
            factor = 0.8 + random.random() * 0.4
            delta = self.interval_sec * factor
        else:
            delta = random.uniform(300.0, 360.0)
            logger.warning(
                t(self.lang, "interval.rate_limited_wait", seconds=delta)
            )
        self._next_allowed_ts = now + delta

    def reset(self) -> None:
        self._next_allowed_ts = 0.0
