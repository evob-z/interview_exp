"""API 路由冒烟测试。

原则：仅验证可达性与基本响应结构，不校验业务正确性；
所有外部依赖（LLM、网络、ASR）由 fixture 层面 mock。
"""

import pytest


def test_get_profile(api_client):
    r = api_client.get("/api/profile")
    assert r.status_code == 200
    body = r.json()
    assert "status" in body
    assert body["status"] in ("ok", "empty")


def test_get_stats(api_client):
    r = api_client.get("/api/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "question_bank" in body
    assert "interviews" in body


def test_list_sessions(api_client):
    r = api_client.get("/api/history/sessions")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert isinstance(body["sessions"], list)


def test_create_session(api_client):
    r = api_client.post("/api/history/sessions")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "id" in body["session"]


def test_qa_with_mocked_llm(api_client, mock_llm):
    mock_llm.set_response("这是 mocked 回答")
    r = api_client.post("/api/qa", json={"question": "什么是 ReAct？", "mode": "quick"})
    assert r.status_code == 200
    body = r.json()
    assert "answer" in body
    assert "sources" in body


def test_qa_empty_question_rejected(api_client):
    r = api_client.post("/api/qa", json={"question": "  "})
    assert r.status_code == 400


def test_followup_unknown_session(api_client):
    r = api_client.get("/api/followup/no-such-session")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is False
    assert body["followups"] == []


def test_prepare_list_empty(api_client):
    r = api_client.get("/api/prepare/list")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert isinstance(body["items"], list)


def test_prepare_missing_fields(api_client):
    # 缺失 company/position 应返回 400
    r = api_client.post("/api/prepare/run", json={"company": "", "position": ""})
    assert r.status_code == 400


def test_asr_route_registered(api_client):
    """ASR 是 WebSocket 端点，这里只验证 app 成功加载了该路由。"""
    from app import app
    paths = [getattr(r, "path", None) for r in app.router.routes]
    assert "/api/asr/ws" in paths
