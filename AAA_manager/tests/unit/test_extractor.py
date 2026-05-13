"""extractor.py 的单元测试。"""

import json

import pytest


# ────────── needs_extraction ──────────

def test_needs_extraction_empty_returns_false():
    from extractor import needs_extraction
    assert needs_extraction("") is False
    assert needs_extraction("   \n  ") is False


def test_needs_extraction_skips_q_numbered_markdown():
    from extractor import needs_extraction
    content = "# 面试\n\n## Q1 自我介绍\n要点 1\n\n## Q2 项目经历\n要点 2\n"
    assert needs_extraction(content) is False


def test_needs_extraction_skips_numbered_list_with_questions():
    from extractor import needs_extraction
    content = (
        "1. 介绍一下你自己吗？\n"
        "2. 你是怎么实现这个模块的？\n"
        "3. 为什么选择这个方案？\n"
    )
    assert needs_extraction(content) is False


def test_needs_extraction_detects_transcript_format():
    from extractor import needs_extraction
    content = "说话人1 00:03\n嗯你先自我介绍一下。\n说话人2 00:08\n好。"
    assert needs_extraction(content) is True


def test_needs_extraction_detects_oral_markers():
    from extractor import needs_extraction
    # 6 个口语词
    content = "嗯 啊 嗯 对吧 就是说 那个 然后呢"
    assert needs_extraction(content) is True


# ────────── _parse_extraction_result ──────────

def test_parse_valid_json():
    from extractor import _parse_extraction_result

    payload = json.dumps({
        "company": "蚂蚁",
        "company_type": "大厂",
        "round": "一面技术",
        "questions": [
            {"id": 1, "text": "自我介绍", "category_suggestion": "八股", "is_followup": False},
            {"id": 2, "text": "ReAct 原理", "category_suggestion": "AI_Coding", "is_followup": True},
        ],
    }, ensure_ascii=False)

    result = _parse_extraction_result(payload, raw_file="/tmp/x.md")
    assert result is not None
    assert result.company == "蚂蚁"
    assert result.round == "一面技术"
    assert len(result.questions) == 2
    assert result.questions[1].is_followup is True


def test_parse_strips_markdown_code_fence():
    from extractor import _parse_extraction_result

    payload = (
        "```json\n"
        + json.dumps({
            "company": "美团",
            "company_type": "大厂",
            "round": "一面",
            "questions": [{"id": 1, "text": "hi", "category_suggestion": "八股"}],
        }, ensure_ascii=False)
        + "\n```"
    )
    result = _parse_extraction_result(payload, raw_file="x.md")
    assert result is not None
    assert result.company == "美团"


def test_parse_empty_questions_returns_none():
    from extractor import _parse_extraction_result
    payload = json.dumps({"company": "X", "company_type": "", "round": "", "questions": []})
    assert _parse_extraction_result(payload, raw_file="x.md") is None


def test_parse_invalid_json_returns_none():
    from extractor import _parse_extraction_result
    assert _parse_extraction_result("not-a-json", raw_file="x.md") is None


# ────────── extract_questions ──────────

def test_extract_questions_missing_file(tmp_path):
    from extractor import extract_questions
    assert extract_questions(str(tmp_path / "nope.md")) is None


def test_extract_questions_skips_structured_file(tmp_path, mock_llm, fixtures_dir):
    from extractor import extract_questions
    target = tmp_path / "s.md"
    target.write_text(
        (fixtures_dir / "structured_interview.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    assert extract_questions(str(target)) is None
    # 不应触发 LLM
    assert mock_llm.call_count == 0


def test_extract_questions_end_to_end(tmp_path, mock_llm, fixtures_dir):
    from extractor import extract_questions

    target = tmp_path / "raw.md"
    target.write_text(
        (fixtures_dir / "sample_interview.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    mock_llm.set_response(json.dumps({
        "company": "蚂蚁",
        "company_type": "大厂",
        "round": "一面技术",
        "questions": [
            {"id": 1, "text": "自我介绍", "category_suggestion": "八股"},
            {"id": 2, "text": "ReAct 原理", "category_suggestion": "AI_Coding"},
        ],
    }, ensure_ascii=False))

    result = extract_questions(str(target))
    assert result is not None
    assert result.company == "蚂蚁"
    assert len(result.questions) == 2
    assert mock_llm.call_count == 1


def test_extract_questions_llm_exception_returns_none(tmp_path, mocker, fixtures_dir):
    from extractor import extract_questions
    target = tmp_path / "raw.md"
    target.write_text(
        (fixtures_dir / "sample_interview.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    mocker.patch("extractor.chat_completion", side_effect=RuntimeError("boom"))

    assert extract_questions(str(target)) is None
