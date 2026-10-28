"""pytest 共享 fixture：内存库 + 可注入的固定时钟。"""

from __future__ import annotations

import pytest

from memomind.extract import RuleExtractor
from memomind.ops import RuleOpsDecider
from memomind.retrieve import Retriever
from memomind.store import MemoryStore

T0 = 1782864000.0  # 2026-07-01 00:00:00 UTC，固定起点保证测试确定性


class FakeClock:
    """手动拨动的时钟（秒）。"""

    def __init__(self, t: float = T0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, days: float = 0.0, seconds: float = 0.0) -> None:
        self.t += days * 86400.0 + seconds


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
def store(clock: FakeClock) -> MemoryStore:
    s = MemoryStore(":memory:", clock=clock)
    yield s
    s.close()


@pytest.fixture()
def extractor() -> RuleExtractor:
    return RuleExtractor()


@pytest.fixture()
def decider() -> RuleOpsDecider:
    return RuleOpsDecider()


@pytest.fixture()
def retriever(store: MemoryStore, clock: FakeClock) -> Retriever:
    return Retriever(store, clock=clock)
