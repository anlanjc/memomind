"""Embedding 适配层（A13）：语义召回的迁移路径第一步——接口就位、mock 可测。

设计（对齐 transfer/retrieve 的取舍记录）：
1. provider 抽象：MockEmbedding（确定性词袋向量，测试/演示）+
   OpenAICompatibleEmbedding（DashScope/OpenAI 兼容 /embeddings，真额度开通即用）；
2. 接入点是 **Retriever 的语义重排**：FTS/意图/图三路召回的候选，用查询与记忆
   文本的余弦相似度重排——不改动存储 schema（生产应预计算向量表，v1 惰性计算
   并在 ADR 声明边界）；
3. 无 embedding 时行为与现状逐字一致（可空依赖，零成本降级）。
"""
from __future__ import annotations

import math
import re
from typing import Optional

import httpx


class EmbeddingError(RuntimeError):
    pass


class BaseEmbedding:
    """embed(texts) -> list[list[float]]，维度由实现自定（同实例内一致）。"""

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class MockEmbedding(BaseEmbedding):
    """确定性词袋向量：按字符 4-gram 哈希到固定维度，测试/演示零网络。"""

    def __init__(self, dim: int = 64):
        self.dim = dim

    def _text_to_vec(self, text: str) -> list[float]:
        import hashlib

        vec = [0.0] * self.dim
        for i in range(len(text) - 3):
            gram = text[i:i + 4]
            h = int(hashlib.md5(gram.encode("utf-8")).hexdigest(), 16)
            vec[h % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._text_to_vec(t) for t in texts]


class OpenAICompatibleEmbedding(BaseEmbedding):
    """OpenAI 兼容 /embeddings 端点（DashScope text-embedding-v3 等）。"""

    def __init__(self, base_url: str, api_key: str, model: str,
                 client: Optional[httpx.Client] = None):
        if not api_key:
            raise EmbeddingError("缺少 embedding API key（MEMOMIND_EMBED_API_KEY）")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client = client or httpx.Client(timeout=60)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            resp = self._client.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": texts},
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as e:
            raise EmbeddingError(f"embedding 接口错误: {e}") from e
        items = sorted(data["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in items]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def rerank_by_similarity(query: str, texts: list[str], embedder: BaseEmbedding,
                         base_scores: list[float], weight: float = 2.0) -> list[tuple[int, float]]:
    """查询与各候选文本的余弦相似度 → 与原分数加权融合，返回 (原索引, 新分) 降序。"""
    if not texts:
        return []
    vecs = embedder.embed([query] + list(texts))
    qv = vecs[0]
    out = []
    for i, tv in enumerate(vecs[1:]):
        out.append((i, base_scores[i] + weight * cosine(qv, tv)))
    out.sort(key=lambda kv: -kv[1])
    return out


_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+")
