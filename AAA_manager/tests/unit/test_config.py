"""config.py 的单元测试。"""

import importlib

import pytest


def test_default_provider_is_deepseek(monkeypatch):
    import config
    monkeypatch.setattr(config, "DEFAULT_PROVIDER", "deepseek")
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "ds_key")
    monkeypatch.setattr(config, "DEEPSEEK_BASE_URL", "https://ds.example/v1")
    monkeypatch.setattr(config, "DEEPSEEK_MODEL", "deepseek-chat")

    key, url, model = config.get_active_provider(None)
    assert key == "ds_key"
    assert url == "https://ds.example/v1"
    assert model == "deepseek-chat"


def test_get_active_provider_qwen_case_insensitive(monkeypatch):
    import config
    monkeypatch.setattr(config, "QWEN_API_KEY", "qw_key")
    monkeypatch.setattr(config, "QWEN_BASE_URL", "https://qw.example/v1")
    monkeypatch.setattr(config, "QWEN_MODEL", "qwen-plus")

    for name in ("qwen", "QWEN", "Qwen"):
        key, url, model = config.get_active_provider(name)
        assert key == "qw_key", f"failed for {name!r}"
        assert url == "https://qw.example/v1"
        assert model == "qwen-plus"


def test_get_active_provider_unknown_falls_back_to_deepseek(monkeypatch):
    import config
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "ds_key")
    monkeypatch.setattr(config, "DEEPSEEK_BASE_URL", "https://ds.example/v1")
    monkeypatch.setattr(config, "DEEPSEEK_MODEL", "deepseek-chat")

    key, _, model = config.get_active_provider("unknown-provider")
    assert key == "ds_key"
    assert model == "deepseek-chat"


def test_interview_repo_path_env_override(tmp_path, monkeypatch):
    """验证环境变量 INTERVIEW_REPO_PATH 在模块 reload 后生效。"""
    monkeypatch.setenv("INTERVIEW_REPO_PATH", str(tmp_path))
    import config
    reloaded = importlib.reload(config)
    try:
        assert str(reloaded.INTERVIEW_REPO_PATH) == str(tmp_path)
        assert str(reloaded.QUESTION_BANK_PATH) == str(tmp_path / "问题库")
    finally:
        # 还原，避免影响后续测试
        monkeypatch.delenv("INTERVIEW_REPO_PATH", raising=False)
        importlib.reload(config)
