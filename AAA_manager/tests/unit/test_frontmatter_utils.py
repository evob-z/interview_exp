"""frontmatter_utils.py 的单元测试。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from frontmatter_utils import (
    read_frontmatter,
    write_frontmatter,
    parse_wikilinks,
    upsert_inline_metadata,
    INLINE_KEY_WHITELIST,
)


# ──────────────────────────────────────────────
# read_frontmatter
# ──────────────────────────────────────────────

def test_read_frontmatter_no_frontmatter(tmp_path):
    """无 frontmatter 的文件 → 返回 ({}, 全文)。"""
    f = tmp_path / "test.md"
    f.write_text("# Hello\n\nWorld", encoding="utf-8")
    meta, body = read_frontmatter(f)
    assert meta == {}
    assert body == "# Hello\n\nWorld"


def test_read_frontmatter_with_yaml(tmp_path):
    """有 frontmatter 的文件 → 正确解析 YAML。"""
    f = tmp_path / "test.md"
    f.write_text("---\ncompany: 字节跳动\ndate: \"260513\"\n---\n\n# 正文\n", encoding="utf-8")
    meta, body = read_frontmatter(f)
    assert meta == {"company": "字节跳动", "date": "260513"}
    assert body == "# 正文\n"


def test_read_frontmatter_unclosed(tmp_path):
    """只有开头 --- 没有闭合 --- → 返回 ({}, 全文)。"""
    f = tmp_path / "test.md"
    f.write_text("---\ncompany: 字节跳动\n\n# 正文", encoding="utf-8")
    meta, body = read_frontmatter(f)
    assert meta == {}
    assert body.startswith("---\n")


def test_read_frontmatter_invalid_yaml(tmp_path):
    """YAML 解析失败 → 返回 ({}, 全文)。"""
    f = tmp_path / "test.md"
    f.write_text("---\n*invalid: yaml: [\n---\n\n# 正文\n", encoding="utf-8")
    meta, body = read_frontmatter(f)
    assert meta == {}
    # YAML 解析失败时返回原始全文
    assert body.startswith("---\n")


# ──────────────────────────────────────────────
# write_frontmatter
# ──────────────────────────────────────────────

def test_write_frontmatter_creates_new(tmp_path):
    """无 frontmatter 文件 → 创建新的 frontmatter 块。"""
    f = tmp_path / "test.md"
    f.write_text("# Hello\n\nWorld", encoding="utf-8")
    write_frontmatter(f, {"company": "字节跳动"})
    content = f.read_text(encoding="utf-8")
    assert content.startswith("---\ncompany: 字节跳动\n---\n")
    assert "World" in content


def test_write_frontmatter_merges_existing(tmp_path):
    """已有 frontmatter → 合并保留旧字段。"""
    f = tmp_path / "test.md"
    f.write_text("---\ncompany: 字节跳动\n---\n\n# 正文\n", encoding="utf-8")
    write_frontmatter(f, {"date": "260513"})
    meta, _ = read_frontmatter(f)
    assert meta == {"company": "字节跳动", "date": "260513"}


def test_write_frontmatter_overwrites_existing_key(tmp_path):
    """已有 frontmatter → 更新同名字段。"""
    f = tmp_path / "test.md"
    f.write_text("---\ncompany: 字节跳动\n---\n\n# 正文\n", encoding="utf-8")
    write_frontmatter(f, {"company": "蚂蚁集团"})
    meta, _ = read_frontmatter(f)
    assert meta == {"company": "蚂蚁集团"}


def test_read_write_roundtrip(tmp_path):
    """写入后读取 → 数据一致。"""
    f = tmp_path / "test.md"
    f.write_text("---\ncompany: 字节跳动\n---\n\nBody text", encoding="utf-8")
    write_frontmatter(f, {"date": "260513", "round": "一面技术"})
    meta, body = read_frontmatter(f)
    assert meta["company"] == "字节跳动"
    assert meta["date"] == "260513"
    assert meta["round"] == "一面技术"
    assert body == "Body text"


# ──────────────────────────────────────────────
# parse_wikilinks
# ──────────────────────────────────────────────

def test_parse_wikilinks_simple():
    """简单 wikilink 解析。"""
    result = parse_wikilinks("参见 [[八股]] 和 [[AI_Coding]]")
    assert result == ["八股", "AI_Coding"]


def test_parse_wikilinks_with_alias():
    """带别名的 wikilink。"""
    result = parse_wikilinks("参见 [[八股|八股文题库]]")
    assert result == ["八股|八股文题库"]


def test_parse_wikilinks_dedup():
    """重复 wikilink 去重。"""
    result = parse_wikilinks("[[Q1]] [[Q1]] [[Q2]]")
    assert result == ["Q1", "Q2"]


def test_parse_wikilinks_empty():
    """无 wikilink 时返回空列表。"""
    assert parse_wikilinks("普通文本") == []


# ──────────────────────────────────────────────
# upsert_inline_metadata
# ──────────────────────────────────────────────

def _make_q_file(path: Path, qid: int, text: str, existing_inline: dict = None):
    """构造一个包含 Q 块和可选 inline 字段的 Markdown 文件。"""
    inlines = ""
    if existing_inline:
        inlines = "\n".join(f"{k}:: {v}" for k, v in existing_inline.items())
    content = (
        f"## Q{qid}：测试问题\n"
        f"{text}\n\n"
    )
    if inlines:
        content += f"\n{inlines}\n"
    content += f"## Q{qid+1}：下一题\n一些内容\n"
    path.write_text(content, encoding="utf-8")


def test_upsert_writes_inline_to_existing_q(tmp_path):
    """Q 块存在 → 正确写入 inline 字段。"""
    f = tmp_path / "questions.md"
    _make_q_file(f, 1, "回答内容")
    upsert_inline_metadata(f, 1, {"mastery": "weak", "last_reviewed": "2026-05-25"})
    content = f.read_text(encoding="utf-8")
    assert "mastery:: weak" in content
    assert "last_reviewed:: 2026-05-25" in content


def test_upsert_merges_existing_inline(tmp_path):
    """已有 review_count: 1 → 更新后保留。"""
    f = tmp_path / "questions.md"
    _make_q_file(f, 1, "回答内容", existing_inline={"review_count": "1"})
    upsert_inline_metadata(f, 1, {"mastery": "weak"})
    content = f.read_text(encoding="utf-8")
    assert "mastery:: weak" in content
    assert "review_count:: 1" in content


def test_upsert_q_not_found(tmp_path):
    """Q 编号不存在 → 不抛异常，不改文件。"""
    f = tmp_path / "questions.md"
    f.write_text("## Q1：唯一的问题\n内容\n", encoding="utf-8")
    original = f.read_text(encoding="utf-8")
    upsert_inline_metadata(f, 99, {"mastery": "weak"})
    assert f.read_text(encoding="utf-8") == original


def test_upsert_empty_file(tmp_path):
    """空文件 → 不抛异常。"""
    f = tmp_path / "empty.md"
    f.write_text("", encoding="utf-8")
    upsert_inline_metadata(f, 1, {"mastery": "weak"})
    # 不抛异常即为通过


def test_upsert_last_q_in_file(tmp_path):
    """Q 块是文件最后一个块（无下一个 Q 标题）→ 正确写入到文件尾部。"""
    f = tmp_path / "questions.md"
    f.write_text("## Q1：最后一个问题\n回答内容\n", encoding="utf-8")
    upsert_inline_metadata(f, 1, {"mastery": "mastered"})
    content = f.read_text(encoding="utf-8")
    assert "mastery:: mastered" in content


def test_upsert_skips_non_whitelist_inline(tmp_path):
    """非白名单 :: 字段不被识别为 inline。"""
    f = tmp_path / "questions.md"
    _make_q_file(f, 1, "用 std::vector 实现", existing_inline={"custom_field": "value"})
    upsert_inline_metadata(f, 1, {"mastery": "weak"})
    content = f.read_text(encoding="utf-8")
    # custom_field 不应出现在新 inline 中
    assert "mastery:: weak" in content
    after_q1 = content.split("## Q2")[0]
    assert "custom_field::" not in after_q1


def test_upsert_double_colon_in_body_not_confused(tmp_path):
    """正文中的 ::  不被识别为 inline 字段。"""
    f = tmp_path / "questions.md"
    f.write_text(
        "## Q1：C++ 中的 std::vector\n"
        "std::vector 是标准库中的容器\n"
        "主要用法： push_back\n"
        "\n"
        "## Q2：下一个问题\n"
        "内容\n",
        encoding="utf-8",
    )
    upsert_inline_metadata(f, 1, {"mastery": "weak"})
    content = f.read_text(encoding="utf-8")
    assert "mastery:: weak" in content
    assert "std::vector" in content  # 正文未损坏


# ──────────────────────────────────────────────
# INLINE_KEY_WHITELIST
# ──────────────────────────────────────────────

def test_whitelist_contains_expected_keys():
    """白名单包含预期 key。"""
    assert "mastery" in INLINE_KEY_WHITELIST
    assert "last_reviewed" in INLINE_KEY_WHITELIST
    assert "review_count" in INLINE_KEY_WHITELIST
