"""api.py：FastAPI 端点（TestClient 全 mock，无网络）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from memomind.api import create_app


@pytest.fixture()
def client():
    app = create_app(":memory:")
    with TestClient(app) as c:
        yield c


def test_health(client: TestClient):
    data = client.get("/health").json()
    assert data["status"] == "ok" and data["memories"] == 0


def test_chat_endpoint_full_payload(client: TestClient):
    resp = client.post("/chat", json={"session_id": "s1", "message": "我投了字节跳动"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"]
    assert {op["op"] for op in data["ops"]} == {"ADD"}
    assert len(data["memories_used"]) == 0  # 冷启动无记忆命中
    assert any(f["predicate"] == "applied_to" for f in data["facts_extracted"])


def test_memories_status_filter(client: TestClient):
    client.post("/chat", json={"session_id": "s1", "message": "我想投后端岗"})
    client.post("/chat", json={"session_id": "s2", "message": "改投 Agent 岗了"})
    active = client.get("/memories", params={"status": "active"}).json()
    sup = client.get("/memories", params={"status": "superseded"}).json()
    assert any(m["object"] == "Agent岗" for m in active["memories"])
    assert any(m["object"] == "后端岗" and m["status"] == "superseded"
               for m in sup["memories"])
    # 关键词过滤
    q = client.get("/memories", params={"q": "Agent"}).json()
    assert all("Agent" in (m["object"] + m["predicate"]) for m in q["memories"])
    # 非法 status -> 400
    assert client.get("/memories", params={"status": "bogus"}).status_code == 400


def test_forget_endpoint(client: TestClient):
    client.post("/chat", json={"session_id": "s1", "message": "我投了字节跳动"})
    mem = client.get("/memories", params={"status": "active"}).json()["memories"][0]
    resp = client.post("/forget", json={"memory_id": mem["id"]})
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"
    after = client.get("/memories", params={"status": "archived"}).json()
    assert any(m["id"] == mem["id"] for m in after["memories"])
    # 重复遗忘 -> 409；不存在 -> 404
    assert client.post("/forget", json={"memory_id": mem["id"]}).status_code == 409
    assert client.post("/forget", json={"memory_id": "nope"}).status_code == 404


def test_graph_endpoint(client: TestClient):
    client.post("/chat", json={"session_id": "s1", "message": "我投了字节跳动"})
    data = client.get("/graph/字节跳动").json()
    assert data["entity"] == "字节跳动"
    assert {n["id"] for n in data["nodes"]} == {"user", "字节跳动"}
    predicates = {e["predicate"] for e in data["edges"]}
    assert "applied_to" in predicates
    assert any(p.startswith("application_status") for p in predicates)
    assert client.get("/graph/不存在").json()["nodes"] == []


def test_maintenance_and_static_page(client: TestClient):
    client.post("/chat", json={"session_id": "s1", "message": "我投了字节跳动"})
    m = client.post("/maintenance", json={"run_decay": True, "run_compact": True,
                                          "half_life_days": 30})
    assert m.status_code == 200
    body = m.json()
    assert body["decay"] is not None and "compacted" in body
    page = client.get("/")
    assert page.status_code == 200
    assert "memomind 记忆浏览器" in page.text


# ---- MM-3 回归（评审 2.0 high）：half_life_days 无下界曾一次请求静默归档全库 ----

def test_chat_session_id_charset_rejected(client: TestClient):
    """MM-4 纵深：session_id 字符集白名单（曾仅限长度，<img onerror> 经 source_session 透出）。"""
    r = client.post("/chat", json={"session_id": "<img src=x onerror=alert(1)>",
                                   "message": "我投了字节跳动"})
    assert r.status_code == 422


def test_maintenance_half_life_days_rejects_non_positive(client: TestClient):
    """0 / 负数 / NaN 必须 422（此前 0 会把除刚 touch 外的全部记忆静默归档）。"""
    client.post("/chat", json={"session_id": "s1", "message": "我投了字节跳动"})
    for bad in (0, -1, "NaN"):
        r = client.post("/maintenance", json={"run_decay": True, "run_compact": False,
                                              "half_life_days": bad})
        assert r.status_code == 422, f"half_life_days={bad!r} 应 422"


def test_maintenance_zero_half_life_leaves_memories_active(client: TestClient):
    """语义回归锁：非法半衰期被拒后，任何记忆不得被归档。"""
    client.post("/chat", json={"session_id": "s1", "message": "我投了字节跳动"})
    client.post("/maintenance", json={"run_decay": True, "run_compact": False,
                                      "half_life_days": 0})
    data = client.get("/memories").json()
    assert data["count"] > 0
    for m in data["memories"]:
        assert m["status"] == "active"
