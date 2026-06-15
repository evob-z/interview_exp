"""reflector.py 的单元测试。

mock PydanticAI Agent，验证覆盖度停止逻辑、降级路径、辅助函数。
"""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 确保 AAA_manager 目录在 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reviewer import _extract_top_concerns
from reflector import (
    CoverageScores,
    Notepad,
    QuestionItem,
    ReflectionTurn,
    ReflectionSummary,
    ReflectionResult,
    ReflectDeps,
    _load_user_profile_brief,
    _parse_interview_meta,
    _parse_questions_from_file,
    _load_prediction_context,
    _init_project_reader,
    _build_initial_context,
    _format_for_reviewer,
    _enhance_mastery_from_summary,
    lookup_project_doc,
)


# ──────────────────────────────────────────────
# 辅助
# ──────────────────────────────────────────────

def _make_turn(coverage_dict=None, should_stop=False, question="测试问题", reasoning=""):
    """快速构造 ReflectionTurn"""
    cov = CoverageScores(**(coverage_dict or {
        "overall_feeling": 30,
        "strengths": 30,
        "weaknesses": 30,
        "interviewer_focus": 30,
        "improvement_areas": 30,
    }))
    return ReflectionTurn(
        next_question=question,
        reasoning=reasoning,
        coverage=cov,
        should_stop=should_stop,
    )


def _make_summary():
    """快速构造 ReflectionSummary"""
    return ReflectionSummary(
        performance_summary="整体表现一般，部分题目回答流畅但有几个关键知识点暴露短板",
        well_answered=["Q1 自我介绍流畅自信", "Q2 项目经历描述清晰"],
        poorly_answered=["Q3 Python 装饰器原理理解不深", "Q5 系统设计题思路混乱"],
        interviewer_focus=["追问了项目并发处理细节", "关注了系统架构设计能力"],
        improvement_suggestions=["加强八股文系统性复习", "多练习系统设计题", "准备项目深挖案例"],
        review_content=(
            "本次面试整体表现中等偏上，自我介绍和项目经历部分回答流畅，展现了较好的沟通能力和项目经验。"
            "但在技术深度方面存在明显短板，Python 装饰器原理回答不够准确，系统设计题缺乏结构化思路。"
            "面试官明显关注候选人的系统架构能力和并发处理经验，对项目细节追问较多。"
            "建议后续重点加强计算机基础知识的系统学习，尤其是 Python 高级特性和分布式系统设计。"
            "同时建议准备 2-3 个项目的深度复盘案例，涵盖技术选型理由、遇到的挑战和解决方案。"
            "这些内容足够超过一百个字符以满足 Pydantic 验证的字段最低长度要求。"
        ),
    )


def _make_summary_with_qids():
    """构造带 qids 的 ReflectionSummary，用于测试 mastery 打标路径。"""
    return ReflectionSummary(
        performance_summary="整体表现中等，八股部分答得不好",
        well_answered=["Q1 自我介绍流畅"],
        poorly_answered=["Q2 Python GIL 理解不深", "Q3 装饰器原理模糊"],
        well_answered_qids=[
            QuestionItem(qid=1, category="八股", reason="自我介绍流畅自信"),
        ],
        poorly_answered_qids=[
            QuestionItem(qid=2, category="八股", reason="GIL 仅知道存在不了解原理"),
            QuestionItem(qid=3, category="八股", reason="装饰器概念模糊"),
        ],
        interviewer_focus=["追问了 Python 并发"],
        improvement_suggestions=["加强 Python 高级特性"],
        review_content="面试整体表现中等偏上，自我介绍流畅自信，八股部分存在明显短板。"
                       "Python GIL 和装饰器原理两道题答得模糊，暴露了基础知识不扎实的问题。"
                       "面试官明显关注 Python 并发能力和系统架构设计经验，对项目细节追问较多。"
                       "建议后续重点加强计算机基础知识的系统学习，尤其是 Python 高级特性和分布式系统设计。"
                       "同时建议准备 2-3 个项目的深度复盘案例，涵盖技术选型理由、遇到的挑战和解决方案。"
                       "这些内容足够超过一百个字符以满足 Pydantic 验证的字段最低长度要求。",
    )


# ──────────────────────────────────────────────
# CoverageScores
# ──────────────────────────────────────────────

def test_coverage_all_covered_below_threshold():
    cov = CoverageScores(
        overall_feeling=80, strengths=80, weaknesses=60,
        interviewer_focus=80, improvement_areas=80,
    )
    assert not cov.all_covered(70)


def test_coverage_all_covered_above_threshold():
    cov = CoverageScores(
        overall_feeling=75, strengths=72, weaknesses=70,
        interviewer_focus=80, improvement_areas=71,
    )
    assert cov.all_covered(70)


def test_coverage_all_covered_exact_threshold():
    cov = CoverageScores(
        overall_feeling=70, strengths=70, weaknesses=70,
        interviewer_focus=70, improvement_areas=70,
    )
    assert cov.all_covered(70)


# ──────────────────────────────────────────────
# _parse_interview_meta
# ──────────────────────────────────────────────

def test_parse_meta_standard():
    meta = _parse_interview_meta("字节跳动_大厂_260513_技术一面.md")
    assert meta["company"] == "字节跳动"
    assert meta["company_type"] == "大厂"
    assert meta["date"] == "260513"
    assert meta["round"] == "技术一面"


def test_parse_meta_no_date():
    meta = _parse_interview_meta("信通院_国企_技术.md")
    assert meta["company"] == "信通院"
    assert meta["company_type"] == "国企"
    assert meta["round"] == "技术"


# ──────────────────────────────────────────────
# _parse_questions_from_file
# ──────────────────────────────────────────────

def test_parse_questions_q_format(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("""## Q1: 自我介绍
### Q2：项目介绍
#### Q3: 八股文问题
""", encoding="utf-8")
    qs = _parse_questions_from_file(str(f))
    assert len(qs) == 3
    assert qs[0]["text"] == "自我介绍"


def test_parse_questions_numbered(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("""1. 第一个面试问题内容
2、第二个面试问题内容
3) 第三个面试问题内容
""", encoding="utf-8")
    qs = _parse_questions_from_file(str(f))
    assert len(qs) == 3


def test_parse_questions_empty_file(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("没有问题的文件", encoding="utf-8")
    qs = _parse_questions_from_file(str(f))
    assert qs == []


# ──────────────────────────────────────────────
# _load_user_profile_brief
# ──────────────────────────────────────────────

def test_load_profile_missing_file(monkeypatch, tmp_path):
    """缺文件时返回空字符串"""
    import reflector
    monkeypatch.setattr(reflector.Path, "__init__", lambda self, *a: None)
    monkeypatch.setattr(reflector.Path, "exists", lambda self: False)
    # 直接测内部逻辑：用不存在路径
    result = _load_user_profile_brief()
    assert result == ""


# ──────────────────────────────────────────────
# _load_prediction_context
# ──────────────────────────────────────────────

def test_load_prediction_not_found(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "INTERVIEW_REPO_PATH", tmp_path)
    monkeypatch.setattr(config, "PREP_OUTPUT_DIR", "岗位预测")
    (tmp_path / "岗位预测").mkdir(exist_ok=True)
    result = _load_prediction_context("不存在的公司")
    assert result is None


# ──────────────────────────────────────────────
# _init_project_reader
# ──────────────────────────────────────────────

def test_init_project_reader_no_projects():
    questions = [
        {"id": 1, "text": "八股题", "category_suggestion": "八股"},
        {"id": 2, "text": "AI题", "category_suggestion": "AI_Coding"},
    ]
    reader, summaries = _init_project_reader(questions)
    assert reader is None
    assert summaries == {}


# ──────────────────────────────────────────────
# _build_initial_context
# ──────────────────────────────────────────────

def test_build_initial_context_minimal():
    questions = [{"id": 1, "text": "自我介绍"}]
    meta = {"company": "字节", "company_type": "大厂", "round": "一面", "date": "260513"}
    ctx = _build_initial_context(questions, meta, "", None, {})
    assert "字节" in ctx
    assert "自我介绍" in ctx


def test_build_initial_context_with_profile():
    questions = [{"id": 1, "text": "自我介绍"}]
    meta = {"company": "字节", "company_type": "大厂", "round": "一面", "date": "260513"}
    ctx = _build_initial_context(questions, meta, "技能: Python", None, {})
    assert "Python" not in ctx


def test_build_initial_context_with_prediction():
    questions = [{"id": 1, "text": "自我介绍"}]
    meta = {"company": "字节", "company_type": "大厂", "round": "一面", "date": "260513"}
    ctx = _build_initial_context(questions, meta, "", "预测题目内容", {})
    assert "预测题目内容" not in ctx


def test_build_initial_context_with_projects():
    questions = [{"id": 1, "text": "自我介绍"}]
    meta = {"company": "字节", "company_type": "大厂", "round": "一面", "date": "260513"}
    summaries = {
        "TestProject": {
            "tier_1": {"name": "AI工具总结", "file_count": 1, "loaded": True, "files": ["readme.md"]},
            "tier_2": {"name": "设计文档", "file_count": 0, "loaded": False, "files": []},
        }
    }
    ctx = _build_initial_context(questions, meta, "", None, summaries)
    assert "TestProject" not in ctx
    assert "notepad" in ctx


# ──────────────────────────────────────────────
# _format_for_reviewer
# ──────────────────────────────────────────────

def test_extract_top_concerns_circled_numbers():
    report = """
### 二、面试官关注点总结与画像分析

**① "你的项目到底是你做的，还是你只是用过？"**
**② "你懂分布式系统的核心组件吗？"**
**③ "你的Agent设计是花架子还是有工程价值？"**

### 三、给自己的复盘建议
"""
    concerns = _extract_top_concerns(report)
    assert len(concerns) == 3
    assert "项目" in concerns[0]
    assert "分布式" in concerns[1]


def test_format_for_reviewer():
    summary = _make_summary()
    result = _format_for_reviewer(summary)
    assert "整体表现一般" in result
    assert "自我介绍流畅自信" in result
    assert "Python 装饰器原理理解不深" in result
    assert "追问了项目并发处理细节" in result
    assert "加强八股文系统性复习" in result


# ──────────────────────────────────────────────
# Notepad
# ──────────────────────────────────────────────

def test_notepad_write_append():
    n = Notepad(max_total_chars=200)
    n.write("A", "foo")
    n.append("A", "bar")
    assert "foo" in n.sections["A"]
    assert "bar" in n.sections["A"]


def test_notepad_lru_eviction():
    n = Notepad(max_total_chars=40)
    n.write("A", "12345678901234567890")
    n.write("B", "12345678901234567890")
    n.write("C", "12345678901234567890")
    # 容量超限时应淘汰最旧 section（至少保留一个）
    assert "A" not in n.sections
    assert len(n.sections) >= 1


def test_notepad_snapshot_to_file(tmp_path):
    p = tmp_path / "notepad.md"
    n = Notepad(max_total_chars=200, dump_path=p)
    n.write("seed", "hello")
    n.snapshot(0, "init")
    content = p.read_text(encoding="utf-8")
    assert "Round 0" in content
    assert "hello" in content


def test_notepad_section_auto_compress():
    n = Notepad(max_total_chars=10000, max_section_chars=20)
    raw = "abcdefghijklmnopqrstuvwxyz"
    n.write("long", raw)
    content = n.sections["long"]
    assert "中间省略" in content
    assert len(content) > 20  # 包含压缩提示文本
    assert "abc" in content
    assert "xyz" in content


@pytest.mark.asyncio
async def test_lookup_project_doc_writes_notepad():
    class DocTier:
        def __init__(self):
            self.loaded = True
            self.files = [{"path": "README.md", "content": "abc"}]

    class Reader:
        def __init__(self):
            self._tiers = {"P": {1: DocTier(), 2: None, 3: None}}

    deps = ReflectDeps(project_reader=Reader(), notepad=Notepad(max_total_chars=200))
    ctx = MagicMock()
    ctx.deps = deps

    msg = await lookup_project_doc(ctx, "P", "README.md")
    assert "已读取 P/README.md" in msg
    assert "项目文档:P/README.md" in deps.notepad.sections


# ──────────────────────────────────────────────
# reflect_interview_async 完整流程 mock
# ──────────────────────────────────────────────

@pytest.fixture
def sample_interview_file(tmp_path):
    """创建一个示例面经文件"""
    f = tmp_path / "字节跳动_大厂_260513_技术一面.md"
    f.write_text("""## Q1: 自我介绍
### Q2: 项目介绍
#### Q3: Python 装饰器原理
""", encoding="utf-8")
    return str(f)


@pytest.mark.asyncio
async def test_reflect_stops_on_full_coverage(sample_interview_file, mocker):
    """全维度 ≥70 时正确停止"""
    # mock Agent 返回一次性全覆盖
    mock_agent = MagicMock()
    mock_result = MagicMock()
    mock_result.output = _make_turn(
        coverage_dict={
            "overall_feeling": 80, "strengths": 80, "weaknesses": 75,
            "interviewer_focus": 78, "improvement_areas": 72,
        },
        should_stop=False,
        reasoning="信息已足够",
    )
    mock_agent.run = AsyncMock(return_value=mock_result)

    mocker.patch("reflector._build_conv_agent", return_value=mock_agent)
    # mock input 不会被调用（第一轮就停了），但仍需 patch 以防万一
    mocker.patch("builtins.input", return_value="")

    from reflector import reflect_interview_async
    result = await reflect_interview_async(sample_interview_file, max_rounds=2, threshold=70)

    assert result.company == "字节跳动"
    assert len(result.questions) == 3
    # 应该在第一轮直接停止，transcript 为空
    assert len(result.transcript) == 0


@pytest.mark.asyncio
async def test_reflect_stops_on_max_rounds(sample_interview_file, mocker):
    """达到 max_rounds 时强制停止"""
    # 每轮都返回低覆盖度
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=MagicMock(output=_make_turn(
        coverage_dict={
            "overall_feeling": 10, "strengths": 10, "weaknesses": 10,
            "interviewer_focus": 10, "improvement_areas": 10,
        },
        should_stop=False,
    )))
    mock_agent.run.return_value.all_messages = MagicMock(return_value=[])

    mocker.patch("reflector._build_conv_agent", return_value=mock_agent)

    # 模拟用户输入
    inputs = ["答得一般", "Q1还行", "Q3不行"]
    mocker.patch("builtins.input", side_effect=inputs)

    from reflector import reflect_interview_async
    result = await reflect_interview_async(sample_interview_file, max_rounds=3, threshold=70)

    assert len(result.transcript) == 3
    assert result.transcript[0]["a"] == "答得一般"
    assert result.transcript[2]["a"] == "Q3不行"


@pytest.mark.asyncio
async def test_reflect_stops_on_stop_command(sample_interview_file, mocker):
    """/stop 输入跳出循环"""
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=MagicMock(output=_make_turn(
        coverage_dict={
            "overall_feeling": 30, "strengths": 30, "weaknesses": 30,
            "interviewer_focus": 30, "improvement_areas": 30,
        },
        should_stop=False,
    )))
    mock_agent.run.return_value.all_messages = MagicMock(return_value=[])

    mocker.patch("reflector._build_conv_agent", return_value=mock_agent)
    # 第一轮输入 /stop
    mocker.patch("builtins.input", return_value="/stop")

    from reflector import reflect_interview_async
    result = await reflect_interview_async(sample_interview_file, max_rounds=5, threshold=70)

    # 手动停止后 transcript 应为空
    assert len(result.transcript) == 0


@pytest.mark.asyncio
async def test_reflect_full_flow_with_summary(sample_interview_file, mocker):
    """完整流程：多轮对话 + Summary Agent 汇总"""
    from pydantic_ai import UnexpectedModelBehavior

    # Conversation Agent：第一轮低覆盖 → 第二轮满分停止
    conv_agent = MagicMock()
    call_count = [0]

    async def conv_run(user_input=None, **kwargs):
        call_count[0] += 1
        result = MagicMock()
        if call_count[0] == 1:
            result.output = _make_turn(
                coverage_dict={
                    "overall_feeling": 40, "strengths": 30, "weaknesses": 30,
                    "interviewer_focus": 30, "improvement_areas": 30,
                },
                should_stop=False,
                question="第一题答得怎么样？",
            )
        else:
            result.output = _make_turn(
                coverage_dict={
                    "overall_feeling": 80, "strengths": 80, "weaknesses": 75,
                    "interviewer_focus": 78, "improvement_areas": 72,
                },
                should_stop=False,
                reasoning="全覆盖",
            )
        result.all_messages = MagicMock(return_value=[])
        return result

    conv_agent.run = conv_run
    mocker.patch("reflector._build_conv_agent", return_value=conv_agent)

    # Summary Agent
    summary_agent = MagicMock()
    summary_result = MagicMock()
    summary_result.output = _make_summary()
    summary_agent.run = AsyncMock(return_value=summary_result)
    mocker.patch("reflector._build_summary_agent", return_value=summary_agent)

    mocker.patch("builtins.input", return_value="答得不错")

    from reflector import reflect_interview_async
    result = await reflect_interview_async(sample_interview_file, max_rounds=5, threshold=70)

    # 验证 transcript
    assert len(result.transcript) == 1
    assert result.transcript[0]["a"] == "答得不错"

    # 验证 summary
    assert result.summary["performance_summary"] == "整体表现一般，部分题目回答流畅但有几个关键知识点暴露短板"
    assert "review_content" in result.summary
    assert result.review_content.startswith("本次面试整体表现中等偏上")


@pytest.mark.asyncio
async def test_reflect_agent_startup_failure(sample_interview_file, mocker):
    """Conversation Agent 启动失败时直接返回空 ReflectionResult"""
    from pydantic_ai import UnexpectedModelBehavior

    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(side_effect=UnexpectedModelBehavior("模型异常"))
    mocker.patch("reflector._build_conv_agent", return_value=mock_agent)

    from reflector import reflect_interview_async
    result = await reflect_interview_async(sample_interview_file, max_rounds=2, threshold=70)

    # 启动即失败，不进入交互
    assert result.transcript == []
    assert result.review_content == ""


@pytest.mark.asyncio
async def test_reflect_summary_failure_fallback(sample_interview_file, mocker):
    """Summary Agent 失败时走降级路径"""
    from pydantic_ai import UnexpectedModelBehavior

    # Conv Agent: 第一轮低覆盖 → 第二轮满分停止
    call_count = [0]

    async def conv_run(user_input=None, **kwargs):
        call_count[0] += 1
        result = MagicMock()
        if call_count[0] == 1:
            result.output = _make_turn(
                coverage_dict={
                    "overall_feeling": 40, "strengths": 40, "weaknesses": 40,
                    "interviewer_focus": 40, "improvement_areas": 40,
                },
                should_stop=False,
                question="答得怎么样？",
            )
        else:
            result.output = _make_turn(
                coverage_dict={
                    "overall_feeling": 80, "strengths": 80, "weaknesses": 75,
                    "interviewer_focus": 78, "improvement_areas": 72,
                },
                should_stop=False,
            )
        result.all_messages = MagicMock(return_value=[])
        return result

    conv_agent = MagicMock()
    conv_agent.run = conv_run
    mocker.patch("reflector._build_conv_agent", return_value=conv_agent)

    # Summary Agent 失败
    summary_agent = MagicMock()
    summary_agent.run = AsyncMock(side_effect=UnexpectedModelBehavior("汇总失败"))
    mocker.patch("reflector._build_summary_agent", return_value=summary_agent)

    mocker.patch("builtins.input", return_value="答得还行吧")

    from reflector import reflect_interview_async
    result = await reflect_interview_async(sample_interview_file, max_rounds=3, threshold=70)

    # 应走降级：review_content 包含原始对话
    assert result.review_content != ""
    assert "答得还行吧" in result.review_content
    assert result.enhanced_review_context != ""
    # summary 应为空 dict
    assert result.summary == {}


# ──────────────────────────────────────────────
# _enhance_mastery_from_summary（语义匹配版）
# ──────────────────────────────────────────────

_MOCK_QUESTIONS = [
    {"id": 1, "text": "自我介绍如何准备", "category_suggestion": "八股"},
    {"id": 2, "text": "Python GIL 是什么", "category_suggestion": "八股"},
    {"id": 3, "text": "装饰器原理", "category_suggestion": "八股"},
]


def test_enhance_mastery_writes_inline(tmp_path, monkeypatch, mocker):
    """语义匹配成功 → 写入 mastery 到问题库文件。"""
    import config

    qb_dir = tmp_path / "问题库"
    qb_dir.mkdir()
    monkeypatch.setattr(config, "QUESTION_BANK_PATH", qb_dir)
    monkeypatch.setattr(config, "CATEGORY_FILE_MAP", {"八股": "八股.md"})

    # 问题库文件（包含不同 qid 的题目，验证跨编号匹配）
    qb_file = qb_dir / "八股.md"
    qb_file.write_text(
        "## Q10：自我介绍如何准备\n"
        "内容略\n\n"
        "## Q20：Python GIL 是什么\n"
        "GIL 是全局解释器锁\n\n"
        "## Q30：装饰器原理\n"
        "装饰器本质是闭包\n",
        encoding="utf-8",
    )

    # Mock QuestionBank.search 返回匹配结果
    def mock_search(query, top_k=5, boost_categories=None):
        mapping = {
            "自我介绍如何准备": [{"id": 10, "text": "自我介绍如何准备", "category": "八股", "score": 15.0}],
            "Python GIL 是什么": [{"id": 20, "text": "Python GIL 是什么", "category": "八股", "score": 14.0}],
            "装饰器原理": [{"id": 30, "text": "装饰器原理", "category": "八股", "score": 12.0}],
        }
        return mapping.get(query, [])

    mocker.patch(
        "AAA_manager.knowledge.question_bank.QuestionBank.search",
        mock_search,
    )

    summary = _make_summary_with_qids()
    _enhance_mastery_from_summary(summary, _MOCK_QUESTIONS)

    content = qb_file.read_text(encoding="utf-8")
    # Q10 应该是 mastered（来自 well_answered Q1）
    assert "mastery:: mastered" in content
    # Q20 应该是 weak（来自 poorly_answered Q2）
    parts = content.split("## Q")
    q20_block = [p for p in parts if p.startswith("20")][0]
    assert "mastery:: weak" in q20_block
    # Q30 应该是 weak（来自 poorly_answered Q3）
    q30_block = [p for p in parts if p.startswith("30")][0]
    assert "mastery:: weak" in q30_block


def test_enhance_mastery_low_score_skip(tmp_path, monkeypatch, mocker):
    """语义匹配分数低于阈值 → 不写入。"""
    import config

    qb_dir = tmp_path / "问题库"
    qb_dir.mkdir()
    monkeypatch.setattr(config, "QUESTION_BANK_PATH", qb_dir)
    monkeypatch.setattr(config, "CATEGORY_FILE_MAP", {"八股": "八股.md"})

    qb_file = qb_dir / "八股.md"
    qb_file.write_text("## Q1：完全不相关的问题\n内容\n", encoding="utf-8")

    # 搜索返回低分结果
    mocker.patch(
        "AAA_manager.knowledge.question_bank.QuestionBank.search",
        return_value=[{"id": 1, "text": "完全不相关", "category": "八股", "score": 3.0}],
    )

    summary = _make_summary_with_qids()
    _enhance_mastery_from_summary(summary, _MOCK_QUESTIONS)

    # 不应有任何 mastery 写入
    content = qb_file.read_text(encoding="utf-8")
    assert "mastery::" not in content


def test_enhance_mastery_empty_qids(tmp_path, monkeypatch):
    """qids 为空 → 不写任何内容，不抛异常。"""
    import config

    qb_dir = tmp_path / "问题库"
    qb_dir.mkdir()
    monkeypatch.setattr(config, "QUESTION_BANK_PATH", qb_dir)
    monkeypatch.setattr(config, "CATEGORY_FILE_MAP", {"八股": "八股.md"})

    qb_file = qb_dir / "八股.md"
    original = "## Q1：测试\n内容\n"
    qb_file.write_text(original, encoding="utf-8")

    summary = _make_summary()  # qids 为空
    _enhance_mastery_from_summary(summary, _MOCK_QUESTIONS)

    assert qb_file.read_text(encoding="utf-8") == original


def test_enhance_mastery_unknown_category(tmp_path, monkeypatch, mocker):
    """category 不在 CATEGORY_FILE_MAP → 静默跳过。"""
    import config

    qb_dir = tmp_path / "问题库"
    qb_dir.mkdir()
    monkeypatch.setattr(config, "QUESTION_BANK_PATH", qb_dir)
    monkeypatch.setattr(config, "CATEGORY_FILE_MAP", {"八股": "八股.md"})

    qb_file = qb_dir / "八股.md"
    original = "## Q1：测试问题\n内容\n"
    qb_file.write_text(original, encoding="utf-8")

    summary = ReflectionSummary(
        performance_summary="测试",
        poorly_answered_qids=[
            QuestionItem(qid=1, category="不存在的分类", reason="测试"),
        ],
        review_content=(
            "这是测试内容用来满足 Pydantic 验证的最低一百个字符限制要求。"
            "面试整体表现中等偏上，自我介绍流畅自信，技术部分存在明显短板。"
            "Python GIL 和装饰器原理两道题答得模糊，暴露了基础知识不扎实的问题。"
            "面试官明显关注 Python 并发能力和系统架构设计经验，对项目细节追问较多。"
            "建议后续重点加强计算机基础知识的系统学习，尤其是 Python 高级特性。"
        ),
    )

    _enhance_mastery_from_summary(summary, _MOCK_QUESTIONS)
    assert qb_file.read_text(encoding="utf-8") == original


def test_enhance_mastery_import_error(monkeypatch):
    """frontmatter_utils 不可用 → 静默返回。"""
    import sys
    from pathlib import Path

    monkeypatch.delitem(sys.modules, "frontmatter_utils", raising=False)

    import config
    monkeypatch.setattr(config, "QUESTION_BANK_PATH", Path("/nonexistent"))

    import builtins
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "frontmatter_utils":
            raise ImportError("mock import error")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    summary = _make_summary_with_qids()
    _enhance_mastery_from_summary(summary, _MOCK_QUESTIONS)
