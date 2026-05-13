"""archiver.py 的单元测试。"""

import json

import pytest


# ────────── validate_filename ──────────

def test_validate_filename_valid():
    from archiver import validate_filename
    ok, suggested = validate_filename("蚂蚁_大厂_260423_一面技术.md")
    assert ok is True
    assert suggested is None


def test_validate_filename_invalid():
    from archiver import validate_filename
    ok, _ = validate_filename("foo.md")
    assert ok is False


# ────────── get_interview_date ──────────

def test_get_interview_date_file_missing(isolated_repo):
    from archiver import get_interview_date
    assert get_interview_date("蚂蚁") is None


def test_get_interview_date_broken_json(isolated_repo):
    from archiver import get_interview_date
    (isolated_repo / ".interview_dates.json").write_text("{not json", encoding="utf-8")
    assert get_interview_date("蚂蚁") is None


def test_get_interview_date_fuzzy_match(isolated_repo):
    from archiver import get_interview_date
    (isolated_repo / ".interview_dates.json").write_text(
        json.dumps(
            [{"company": "蚂蚁集团", "date": "260423"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert get_interview_date("蚂蚁") == "260423"
    assert get_interview_date("某司") is None


# ────────── normalize_filename ──────────

def test_normalize_filename_already_valid(isolated_repo):
    from archiver import normalize_filename
    src = isolated_repo / "蚂蚁_大厂_260423_一面技术.md"
    src.write_text("x", encoding="utf-8")
    assert normalize_filename(str(src)) == str(src)


def test_normalize_filename_fills_date(isolated_repo):
    from archiver import normalize_filename
    (isolated_repo / ".interview_dates.json").write_text(
        json.dumps([{"company": "美团", "date": "260331"}], ensure_ascii=False),
        encoding="utf-8",
    )
    src = isolated_repo / "美团_大厂_一面技术.md"
    src.write_text("x", encoding="utf-8")

    new_path = normalize_filename(str(src))
    assert new_path.endswith("美团_大厂_260331_一面技术.md")
    from pathlib import Path
    assert Path(new_path).exists()


def test_normalize_filename_does_not_overwrite(isolated_repo):
    from archiver import normalize_filename
    (isolated_repo / ".interview_dates.json").write_text(
        json.dumps([{"company": "美团", "date": "260331"}], ensure_ascii=False),
        encoding="utf-8",
    )
    target = isolated_repo / "美团_大厂_260331_一面技术.md"
    target.write_text("already here", encoding="utf-8")

    src = isolated_repo / "美团_大厂_一面技术.md"
    src.write_text("new", encoding="utf-8")

    # 目标已存在时不应覆盖，保持原路径返回
    assert normalize_filename(str(src)) == str(src)
    assert target.read_text(encoding="utf-8") == "already here"


# ────────── get_next_question_id ──────────

def test_get_next_question_id_empty(tmp_path):
    from archiver import get_next_question_id
    assert get_next_question_id(str(tmp_path / "notexist.md")) == 1


def test_get_next_question_id_no_q(tmp_path):
    from archiver import get_next_question_id
    p = tmp_path / "x.md"
    p.write_text("# 标题\n随便内容", encoding="utf-8")
    assert get_next_question_id(str(p)) == 1


def test_get_next_question_id_mixed_levels(tmp_path):
    from archiver import get_next_question_id
    p = tmp_path / "x.md"
    p.write_text("## Q3 a\n内容\n\n### Q7 b\n内容\n", encoding="utf-8")
    assert get_next_question_id(str(p)) == 8


# ────────── check_duplicate ──────────

def test_check_duplicate_similar_same_source(tmp_path):
    from archiver import check_duplicate
    p = tmp_path / "b.md"
    p.write_text(
        "## Q1：Transformer 和 RNN 有什么区别？\n"
        "- **来源**：蚂蚁_大厂_260423_一面技术 #1\n",
        encoding="utf-8",
    )
    assert check_duplicate(str(p), "蚂蚁_大厂_260423_一面技术", "Transformer 和 RNN 有什么区别？") is True


def test_check_duplicate_similar_different_source(tmp_path):
    from archiver import check_duplicate
    p = tmp_path / "b.md"
    p.write_text(
        "## Q1：Transformer 和 RNN 有什么区别？\n"
        "- **来源**：美团_大厂_260331_一面技术 #1\n",
        encoding="utf-8",
    )
    # 高相似度即使来源不同也判重
    assert check_duplicate(str(p), "其他来源", "Transformer 和 RNN 有什么区别") is True


def test_check_duplicate_low_similarity(tmp_path):
    from archiver import check_duplicate
    p = tmp_path / "b.md"
    p.write_text(
        "## Q1：Python 的 GIL 是什么？\n"
        "- **来源**：美团_大厂_260331 #1\n",
        encoding="utf-8",
    )
    assert check_duplicate(str(p), "美团_大厂_260331", "完全不相关的另一个问题是关于 K8s 网络的") is False


# ────────── archive_questions ──────────

def test_archive_questions_known_category(isolated_repo):
    from archiver import archive_questions

    result = archive_questions(
        [{"id": 1, "text": "介绍 Transformer", "category_suggestion": "八股"}],
        source_label="蚂蚁_大厂_260423_一面技术",
    )
    assert len(result.archived_questions) == 1
    bg = isolated_repo / "问题库" / "八股.md"
    assert bg.exists()
    content = bg.read_text(encoding="utf-8")
    assert "介绍 Transformer" in content
    assert "蚂蚁_大厂_260423_一面技术" in content


def test_archive_questions_unknown_category_falls_back(isolated_repo):
    from archiver import archive_questions

    result = archive_questions(
        [{"id": 1, "text": "奇怪的问题", "category_suggestion": "不存在的分类"}],
        source_label="美团_大厂_260331_一面技术",
    )
    assert len(result.archived_questions) == 1
    # 落到八股
    assert (isolated_repo / "问题库" / "八股.md").exists()


def test_archive_questions_skips_duplicates(isolated_repo):
    from archiver import archive_questions

    source = "蚂蚁_大厂_260423_一面技术"
    archive_questions(
        [{"id": 1, "text": "介绍 Transformer", "category_suggestion": "八股"}],
        source_label=source,
    )
    # 再来一次应被去重
    result = archive_questions(
        [{"id": 1, "text": "介绍 Transformer", "category_suggestion": "八股"}],
        source_label=source,
    )
    assert result.skipped_duplicates
    assert not result.archived_questions


def test_archive_questions_creates_missing_file(isolated_repo):
    from archiver import archive_questions

    result = archive_questions(
        [{"id": 1, "text": "law_sea 项目介绍", "category_suggestion": "项目-law_sea"}],
        source_label="美团_大厂_260331_一面技术",
    )
    target = isolated_repo / "问题库" / "项目-law_sea.md"
    assert target.exists()
    assert "law_sea 项目介绍" in target.read_text(encoding="utf-8")
    assert result.archived_questions[0]["target_file"] == "项目-law_sea.md"
