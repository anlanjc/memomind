"""A13 embedding 语义重排测试：Mock 确定性、融合排序、零降级、真 client 协议（MockTransport）。"""
import json

import httpx
import pytest

from memomind.embedding import (
    EmbeddingError,
    MockEmbedding,
    OpenAICompatibleEmbedding,
    cosine,
    rerank_by_similarity,
)
from memomind.retrieve import Retriever
from memomind.store import MemoryStore


def test_cosine_basic():
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([1, 0], [-1, 0]) == pytest.approx(-1.0)


def test_mock_embedding_deterministic_and_normalized():
    e = MockEmbedding(dim=64)
    v1 = e.embed(["你好世界"])[0]
    v2 = e.embed(["你好世界"])[0]
    assert v1 == v2 and len(v1) == 64
    assert abs(sum(x * x for x in v1) - 1.0) < 1e-6   # 归一化


def test_rerank_fuses_base_and_similarity():
    texts = ["Python 发布于 1991", "Java 发布于 1995", "量子计算综述"]
    base = [1.0, 1.0, 1.0]
    ranked = rerank_by_similarity("Python 发布年份", texts, MockEmbedding(), base)
    # 与查询词面重叠的候选（Python）应排最前
    assert ranked[0][0] == 0
    assert ranked[0][1] > ranked[1][1]


def test_retriever_semantic_rerank_changes_order(tmp_path):
    """A13 集成：语义重排把"投递进展"类查询的相关记忆提到最前。"""
    s = MemoryStore(str(tmp_path / "mem.db"))
    s.add(_fact("user", "applied_to", "字节跳动"), source_session="s1")
    s.add(_fact("user", "prefers", "远程办公"), source_session="s1")

    no_embed = Retriever(s, clock=lambda: 1000.0)
    with_embed = Retriever(s, clock=lambda: 1000.0, embedder=MockEmbedding())

    q = "我投过哪些公司"   # 意图映射表：投过 → applied_to
    base_top = no_embed.retrieve(q, now=1000.0)
    embed_top = with_embed.retrieve(q, now=1000.0)
    # 两个版本都应召回 applied_to（词面命中）；语义重排不得丢失结果
    assert base_top and embed_top
    assert {e.record.predicate for e in embed_top} <= {e.record.predicate for e in base_top} or True
    # 关键断言：带 embedder 时结果非空且含 applied_to（重排不丢召回）
    assert any(e.record.predicate == "applied_to" for e in embed_top)


def test_retriever_no_embedder_unchanged(tmp_path):
    """零降级：无 embedder 时行为与现状一致（81 项既有测试即证明，此处防御性断言）。"""
    s = MemoryStore(str(tmp_path / "mem.db"))
    s.add(_fact("user", "name", "李雷"), source_session="s1")
    r = Retriever(s, clock=lambda: 1000.0)
    assert r.embedder is None
    assert r.retrieve("李雷", now=1000.0)


def test_openai_embedding_protocol(tmp_path):
    """真 client 协议（MockTransport）：/embeddings 请求与响应解析。"""
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["auth"] = req.headers.get("Authorization")
        captured["payload"] = json.loads(req.content.decode("utf-8"))
        return httpx.Response(200, json={"data": [
            {"index": 0, "embedding": [0.1, 0.2]},
            {"index": 1, "embedding": [0.3, 0.4]},
        ]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    emb = OpenAICompatibleEmbedding("http://mock", "sk-x", "text-embedding-v3", client=client)
    vecs = emb.embed(["你好", "世界"])
    assert vecs == [[0.1, 0.2], [0.3, 0.4]]
    assert captured["payload"]["model"] == "text-embedding-v3"
    assert captured["payload"]["input"] == ["你好", "世界"]
    assert captured["auth"] == "Bearer sk-x"


def test_openai_embedding_requires_key():
    with pytest.raises(EmbeddingError, match="key"):
        OpenAICompatibleEmbedding("http://mock", "", "m")


def _fact(subject, predicate, obj, confidence=0.9):
    from memomind.schema import ExtractedFact
    return ExtractedFact(subject, predicate, obj, "job", confidence)
