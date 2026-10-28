"""memomind —— 自研 Agent 长期记忆系统（求职记忆助理场景）。

五层闭环：extract（抽取） -> ops（操作决策） -> store（存储）
          -> retrieve（检索） -> decay（遗忘），chat 把它们串成主循环。
"""

from .decay import DecayConfig, DecayReport, compact, run_decay
from .extract import BaseExtractor, OpenAICompatibleExtractor, RuleExtractor
from .llm import LLMConfig, MissingLLMConfigError, MockResponder, OpenAICompatibleClient
from .ops import LLMOpsDecider, PredicatePolicy, RuleOpsDecider, conflict_key
from .retrieve import RetrievalConfig, Retriever, ScoredMemory
from .schema import (
    ExtractedFact,
    MemoryOp,
    MemoryRecord,
    MemoryStatus,
    OP_ADD,
    OP_DELETE,
    OP_NOOP,
    OP_UPDATE,
)
from .store import MemoryStore

__version__ = "0.1.0"

__all__ = [
    "MemoryStore",
    "MemoryRecord",
    "MemoryStatus",
    "ExtractedFact",
    "MemoryOp",
    "OP_ADD",
    "OP_UPDATE",
    "OP_DELETE",
    "OP_NOOP",
    "RuleExtractor",
    "OpenAICompatibleExtractor",
    "BaseExtractor",
    "RuleOpsDecider",
    "LLMOpsDecider",
    "PredicatePolicy",
    "conflict_key",
    "Retriever",
    "RetrievalConfig",
    "ScoredMemory",
    "run_decay",
    "compact",
    "DecayConfig",
    "DecayReport",
    "MockResponder",
    "OpenAICompatibleClient",
    "LLMConfig",
    "MissingLLMConfigError",
    "__version__",
]
