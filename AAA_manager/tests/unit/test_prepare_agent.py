"""prepare_agent 单元测试（手写 ReAct Loop 版本）。

不真正调用 LLM，只验证：
1. 模块可正常 import 且关键符号存在
2. PrepareDeps 默认状态正确
3. submit_final 工具回填 final_markdown / final_quality / finalized
4. preparer.prepare_interview 在 agent 失败时正确回退 legacy（PREP_AGENT_FALLBACK=true）
5. preparer.prepare_interview 在 fallback 关闭时直接抛出
6. preparer.prepare_interview 在 agent 成功时透传 meta
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(_BASE_DIR) not in sys.path:
    sys.path.insert(0, str(_BASE_DIR))


def _inject_fake_prepare_agent(monkeypatch, run_fn):
    """通过 sys.modules 注入伪 core.prepare_agent，隔离真实模块副作用。"""
    fake = types.ModuleType("core.prepare_agent")
    fake.run_prepare_agent = run_fn
    monkeypatch.setitem(sys.modules, "core.prepare_agent", fake)


# ──────────────────────────────────────────────
# 1. 模块结构验证
# ──────────────────────────────────────────────

def test_prepare_agent_module_imports():
    """模块应可正常 import 且公开必要符号"""
    import core.prepare_agent as pa
    assert hasattr(pa, "run_prepare_agent")
    assert hasattr(pa, "PrepareDeps")
    assert hasattr(pa, "_TOOL_SCHEMAS")
    # 8 个工具 schema：7 个原生 + submit_final
    assert len(pa._TOOL_SCHEMAS) == 8
    names = {s["function"]["name"] for s in pa._TOOL_SCHEMAS}
    assert "submit_final" in names
    assert "search_jd" in names


def test_prepare_deps_default_state():
    """PrepareDeps 累积/输出字段默认值正确"""
    from core.prepare_agent import PrepareDeps

    deps = PrepareDeps(
        company="X",
        position="Y",
        date="260517",
        question_count=15,
        web_searcher=MagicMock(),
        question_bank=MagicMock(),
        project_reader=MagicMock(),
        profile_manager=MagicMock(),
    )
    assert deps.jd_snippets == []
    assert deps.jd_urls == []
    assert deps.search_rounds == 0
    assert deps.iterations_used == 0
    assert deps.final_markdown == ""
    assert deps.final_quality == 0.0
    assert deps.finalized is False


def test_submit_final_tool_finalizes_deps():
    """submit_final 工具应回填 markdown/quality 并标记 finalized"""
    from core.prepare_agent import PrepareDeps, _tool_submit_final

    deps = PrepareDeps(
        company="X", position="Y", date="260517", question_count=12,
        web_searcher=MagicMock(), question_bank=MagicMock(),
        project_reader=MagicMock(), profile_manager=MagicMock(),
    )

    result = _tool_submit_final(deps, markdown="# 题库\n### Q1：x", quality_score=0.85)
    assert result["accepted"] is True
    assert deps.finalized is True
    assert deps.final_markdown.startswith("# 题库")
    assert abs(deps.final_quality - 0.85) < 1e-6

    # 越界值被夹紧
    _tool_submit_final(deps, markdown="x", quality_score=1.5)
    assert deps.final_quality == 1.0

    # 代码围栏去除
    _tool_submit_final(deps, markdown="```md\n# T\n```", quality_score=0.7)
    assert "```" not in deps.final_markdown


# ──────────────────────────────────────────────
# 2. preparer.prepare_interview 的 fallback 逻辑
# ──────────────────────────────────────────────

def test_prepare_interview_falls_back_when_agent_raises(
    isolated_repo, monkeypatch
):
    """Agent 抛异常 + PREP_AGENT_FALLBACK=true → 走 legacy 路径并写文件"""
    import config
    monkeypatch.setattr(config, "PREP_AGENT_FALLBACK", True)
    monkeypatch.setattr(config, "PREP_QUESTION_COUNT", 12)

    def _raise(*args, **kwargs):
        raise RuntimeError("agent 强制失败用于测试 fallback")

    _inject_fake_prepare_agent(monkeypatch, _raise)

    fake_md = (
        "# 岗位预测-测试公司_测试岗位_260517\n\n"
        "### Q1：测试题目\n- **来源**：[预测] 测试_测试_260517\n"
        "- **考察点**：测试\n- **要点**：\n  - p1\n"
        "- **💬 面试话术**：\n  > 测试话术\n"
    )
    import preparer
    monkeypatch.setattr(preparer, "chat_completion", lambda **kw: fake_md, raising=True)
    monkeypatch.setattr(
        preparer,
        "_fetch_jd",
        lambda *a, **kw: _async_empty_jd(),
        raising=True,
    )

    out_dir = isolated_repo / "岗位预测"
    result = preparer.prepare_interview(
        company="测试公司",
        position="测试岗位",
        date="260517",
        output_dir=str(out_dir),
        question_count=12,
    )

    assert result.used_agent is False
    assert result.question_count >= 1
    assert Path(result.output_file).exists()
    assert result.agent_iterations == 0
    assert result.quality_score == 0.0


def test_prepare_interview_raises_when_fallback_disabled(
    isolated_repo, monkeypatch
):
    """Agent 抛异常 + PREP_AGENT_FALLBACK=false → 直接抛出"""
    import config
    monkeypatch.setattr(config, "PREP_AGENT_FALLBACK", False)

    def _raise(*args, **kwargs):
        raise RuntimeError("agent boom")

    _inject_fake_prepare_agent(monkeypatch, _raise)

    import preparer
    with pytest.raises(RuntimeError, match="agent boom"):
        preparer.prepare_interview(
            company="X",
            position="Y",
            date="260517",
            output_dir=str(isolated_repo / "岗位预测"),
            question_count=10,
        )


def test_prepare_interview_uses_agent_meta_on_success(
    isolated_repo, monkeypatch
):
    """Agent 成功返回 → PrepareResult 反映 agent 元信息"""
    import config
    monkeypatch.setattr(config, "PREP_AGENT_FALLBACK", True)

    fake_md = (
        "# 岗位预测-A_B_260517\n\n"
        "### Q1：题1\n- **来源**：[预测]\n- **考察点**：x\n"
        "- **要点**：\n  - p\n- **💬 面试话术**：\n  > s\n\n"
        "### Q2：题2\n- **来源**：[预测]\n- **考察点**：y\n"
        "- **要点**：\n  - p\n- **💬 面试话术**：\n  > s\n"
    )
    fake_meta = {
        "jd_snippet_count": 5,
        "jd_source_count": 3,
        "iterations_used": 2,
        "quality_score": 0.82,
        "search_rounds": 2,
    }

    _inject_fake_prepare_agent(monkeypatch, lambda *a, **kw: (fake_md, fake_meta))

    import preparer
    out_dir = isolated_repo / "岗位预测"
    result = preparer.prepare_interview(
        company="A",
        position="B",
        date="260517",
        output_dir=str(out_dir),
        question_count=12,
    )

    assert result.used_agent is True
    assert result.agent_iterations == 2
    assert abs(result.quality_score - 0.82) < 1e-6
    assert result.jd_snippet_count == 5
    assert result.jd_source_count == 3
    assert result.question_count == 2
    assert Path(result.output_file).exists()


# ──────────────────────────────────────────────
# helpers
# ──────────────────────────────────────────────

async def _async_empty_jd():
    return {
        "company": "",
        "position": "",
        "jd_snippets": [],
        "source_urls": [],
        "raw_results": [],
    }
