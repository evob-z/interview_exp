"""detector.py 的单元测试。"""

from pathlib import Path

import pytest


def test_interview_pattern_matches_valid_names():
    from detector import INTERVIEW_PATTERN

    assert INTERVIEW_PATTERN.match("蚂蚁_大厂_260423_一面技术.md")
    assert INTERVIEW_PATTERN.match("abc_小厂_251231_HR.md")


def test_interview_pattern_rejects_invalid_names():
    from detector import INTERVIEW_PATTERN

    assert not INTERVIEW_PATTERN.match("随便.md")
    # 日期段只有 3 位
    assert not INTERVIEW_PATTERN.match("蚂蚁_大厂_123_一面.md")
    # 缺少段
    assert not INTERVIEW_PATTERN.match("蚂蚁_260423.md")
    # 非 md
    assert not INTERVIEW_PATTERN.match("蚂蚁_大厂_260423_一面.txt")


def test_detection_result_has_changes_and_summary():
    from detector import DetectionResult

    empty = DetectionResult()
    assert empty.has_changes is False
    assert empty.summary() == "无变更"

    r = DetectionResult(
        new_raw_inputs=["a.md"],
        new_interviews=["b.md"],
        modified_questions=["q.md"],
    )
    assert r.has_changes is True
    summary = r.summary()
    assert "原始问题新文件: 1" in summary
    assert "新面试记录(根目录): 1" in summary
    assert "问题库变更: 1" in summary


def test_detect_changes_picks_up_new_raw_input(isolated_repo):
    from detector import detect_changes

    # 放一个待处理的原始问题文件
    new_file = isolated_repo / "面试原始问题" / "蚂蚁_大厂_260423_一面技术.md"
    new_file.write_text("一些问题内容", encoding="utf-8")

    result = detect_changes(str(isolated_repo))
    assert any("蚂蚁_大厂_260423_一面技术.md" in p for p in result.new_raw_inputs)


def test_detect_changes_skips_already_reviewed(isolated_repo):
    from detector import detect_changes

    name = "美团_大厂_260331_一面技术.md"
    (isolated_repo / "面试原始问题" / name).write_text("raw", encoding="utf-8")
    (isolated_repo / "面试复盘" / name).write_text("reviewed", encoding="utf-8")

    result = detect_changes(str(isolated_repo))
    assert not any(name in p for p in result.new_raw_inputs)


def test_detect_changes_survives_non_git_path(isolated_repo):
    """isolated_repo 不是 git 仓库，函数应优雅跳过 git 部分。"""
    from detector import detect_changes

    result = detect_changes(str(isolated_repo))
    # 不抛异常，且仅有原始问题相关字段（此处为空）
    assert result.new_interviews == []
    assert result.modified_questions == []


def test_last_sync_time_roundtrip(isolated_repo):
    from detector import get_last_sync_time, update_last_sync_time

    assert get_last_sync_time() is None
    update_last_sync_time()
    value = get_last_sync_time()
    assert value is not None
    # ISO 格式包含 'T'
    assert "T" in value
