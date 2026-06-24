"""共享测试 fixture。

关键点：config.py 在 import 时就把路径固化到模块级常量；
detector / archiver / extractor 在 import 时 `from config import INTERVIEW_REPO_PATH`
拷贝了这些值。因此 isolated_repo 必须把每个目标模块自己的引用都 patch 掉，
只改 config 不生效。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# 确保 AAA_manager 目录在 sys.path 最前
_BASE_DIR = Path(__file__).resolve().parent.parent
if str(_BASE_DIR) not in sys.path:
    sys.path.insert(0, str(_BASE_DIR))


@pytest.fixture
def isolated_repo(tmp_path, monkeypatch):
    """在 tmp_path 下搭一个隔离的仓库结构，并重定向所有路径常量。"""
    (tmp_path / "面试原始问题").mkdir()
    (tmp_path / "面试复盘").mkdir()
    (tmp_path / "问题库").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "岗位预测").mkdir()

    last_sync = tmp_path / ".last_sync_time"
    question_bank = tmp_path / "问题库"

    import config
    monkeypatch.setattr(config, "INTERVIEW_REPO_PATH", tmp_path)
    monkeypatch.setattr(config, "QUESTION_BANK_PATH", question_bank)
    monkeypatch.setattr(config, "LAST_SYNC_FILE", last_sync)
    monkeypatch.setattr(config, "PREP_OUTPUT_PATH", tmp_path / "岗位预测")

    import detector
    monkeypatch.setattr(detector, "INTERVIEW_REPO_PATH", tmp_path)
    monkeypatch.setattr(detector, "QUESTION_BANK_PATH", question_bank)
    monkeypatch.setattr(detector, "LAST_SYNC_FILE", last_sync)

    import archiver
    monkeypatch.setattr(archiver, "INTERVIEW_REPO_PATH", tmp_path)
    monkeypatch.setattr(archiver, "QUESTION_BANK_PATH", question_bank)
    monkeypatch.setattr(
        archiver,
        "CATEGORY_FILE_MAP",
        {
            "AI_Coding": "AI_Coding.md",
            "八股": "八股.md",
            "工程基础": "八股.md",
        },
    )
    monkeypatch.setattr(
        archiver,
        "generate_answer",
        lambda question_text, category, source_label: {
            "points": ["测试要点"],
            "speech": "测试话术",
        },
    )

    import extractor
    monkeypatch.setattr(extractor, "INTERVIEW_REPO_PATH", tmp_path)

    return tmp_path


class _MockLLM:
    """可配置的 LLM stub，记录调用次数与最后一次 messages。"""

    def __init__(self, default: str = '{"questions": []}'):
        self._response = default
        self.call_count = 0
        self.last_messages: list[dict] | None = None
        self.last_kwargs: dict | None = None

    def set_response(self, text: str) -> None:
        self._response = text

    def __call__(self, messages=None, **kwargs):
        self.call_count += 1
        self.last_messages = messages
        self.last_kwargs = kwargs
        return self._response


@pytest.fixture
def mock_llm(mocker):
    """patch llm_client.chat_completion，返回一个可配置响应的 stub。"""
    stub = _MockLLM()
    # 同时打两处：直接 import 的，和通过模块属性访问的
    mocker.patch("llm_client.chat_completion", side_effect=stub)
    mocker.patch("extractor.chat_completion", side_effect=stub)
    return stub


@pytest.fixture
def api_client(isolated_repo, mock_llm, monkeypatch, tmp_path):
    """FastAPI TestClient，所有路径都指向 tmp_path，LLM 已 mock。

    不 reload api.deps（会触发二次 load 与重复 WebSearcher 初始化），
    而是对已加载实例的路径属性做原位替换。
    """
    # 让 history 的 sessions 目录指向 tmp
    sessions_dir = tmp_path / "data" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    import api.routes.history as hist
    monkeypatch.setattr(hist, "SESSIONS_DIR", sessions_dir)

    # 重定向 profile_manager 的读写路径，避免污染真实 data/user_profile.json
    import api.deps as deps
    profile_file = tmp_path / "data" / "user_profile.json"
    monkeypatch.setattr(deps.profile_manager, "profile_path", str(profile_file))
    deps.profile_manager.profile = {}
    deps.profile_manager.load()

    # 让 question_bank 指向 tmp 的空问题库
    qb_path = str(isolated_repo / "问题库")
    try:
        deps.question_bank.qa_dir = qb_path
    except Exception:
        pass
    try:
        deps.question_bank.extra_dirs = [str(isolated_repo / "岗位预测")]
    except Exception:
        pass
    try:
        deps.question_bank.load()
    except Exception:
        pass

    from app import app
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"
