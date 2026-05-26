"""
frontmatter_utils.py - YAML frontmatter 与 inline 元数据读写工具

纯 Python 实现，零外部服务依赖。提供：
- 文件级 YAML frontmatter 的读写（用于岗位预测/复盘文件）
- 每题级 Dataview inline 字段的写入（用于问题库 mastery 打标）
- wikilink 解析

所有函数均为同步 IO，调用方负责 try/except 包裹。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

logger = logging.getLogger("frontmatter_utils")

# ── inline 字段 key 白名单，防止正文中 ::  模式被误识别 ──
INLINE_KEY_WHITELIST = frozenset({"mastery", "last_reviewed", "review_count"})


def read_frontmatter(file_path: Path) -> tuple[dict, str]:
    """读取文件的 YAML frontmatter 和正文。

    Returns:
        (metadata_dict, body_text)。无 frontmatter 时返回 ({}, 全文)。
    """
    text = file_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text

    try:
        end = text.index("\n---\n", 4)
    except ValueError:
        return {}, text

    try:
        metadata = yaml.safe_load(text[4:end]) or {}
    except yaml.YAMLError:
        logger.warning(f"YAML 解析失败: {file_path}")
        return {}, text

    body = text[end + 5:].lstrip("\n")
    return metadata, body


def write_frontmatter(file_path: Path, updates: dict) -> None:
    """合并更新文件的 YAML frontmatter。

    保留已有字段，仅更新 updates 中指定的 key。
    文件无 frontmatter 时自动创建。
    """
    existing, body = read_frontmatter(file_path)
    existing.update(updates)

    frontmatter_block = yaml.dump(existing, allow_unicode=True, default_flow_style=False).strip()
    new_text = f"---\n{frontmatter_block}\n---\n{body}"
    file_path.write_text(new_text, encoding="utf-8")


def parse_wikilinks(content: str) -> list[str]:
    """从 Markdown 正文中提取所有 [[wikilink]] 引用。

    Returns:
        去掉方括号的链接目标列表（去重）。
    """
    matches = re.findall(r"\[\[(.+?)\]\]", content)
    return list(dict.fromkeys(matches))  # 保序去重


def upsert_inline_metadata(file_path: Path, qid: int, updates: dict[str, str]) -> None:
    """在问题库文件指定 Q 编号的题块末尾，写入/更新 Dataview inline 字段。

    格式: key:: value（每行一个，位于 Q 块末尾，下一个 ### Q 标题之前）

    算法：
    1. 定位 `### Q{qid}[：:]` 行（行号 q_start）
    2. 定位下一个 `### Q\\d+[：:]` 行（行号 q_end），无则用文件尾
    3. 从 q_end 向上扫描，收集已有 inline 字段（仅白名单 key）
    4. existing.update(updates)
    5. 用 [行:strip_start] + new_inlines + [行:q_end] 重建文件

    边缘情况：
    - Q 编号不存在 → warning 日志 + return
    - 无匹配 Q 块 → 同上
    """
    content = file_path.read_text(encoding="utf-8")
    lines = content.split("\n")

    # 1. 定位 Q{n} 起始行（兼容 ## / ### / #### 标题级别）
    q_pattern = re.compile(rf"^#{{2,4}}\s+Q{qid}[：:]")
    q_start = None
    for i, line in enumerate(lines):
        if q_pattern.match(line):
            q_start = i
            break

    if q_start is None:
        logger.warning(f"Q{qid} 未在文件 {file_path.name} 中找到，跳过 inline 元数据写入")
        return

    # 2. 定位下一个 Q 块起始（作为当前块结束边界）
    next_q_pattern = re.compile(r"^#{2,4}\s+Q\d+[：:]")
    q_end = None
    for i in range(q_start + 1, len(lines)):
        if next_q_pattern.match(lines[i]):
            q_end = i
            break

    if q_end is None:
        q_end = len(lines)

    # 3. 从块末尾向上扫描，收集已有 inline 字段（仅白名单 key）
    inline_re = re.compile(r"^(\w+)::\s*(.*)")
    existing: dict[str, str] = {}
    strip_start = q_end
    skipped: list[str] = []

    for i in range(q_end - 1, q_start, -1):
        m = inline_re.match(lines[i])
        if m:
            key = m.group(1)
            if key in INLINE_KEY_WHITELIST:
                existing[key] = m.group(2)
            else:
                skipped.append(key)
            strip_start = i
        elif lines[i].strip() == "":
            strip_start = i
        else:
            break

    if skipped:
        logger.debug(
            f"Q{qid} 中非白名单 inline 字段被跳过：{skipped} "
            f"（白名单={sorted(INLINE_KEY_WHITELIST)}）"
        )

    # 4. 合并更新
    existing.update(updates)

    # 5. 重建
    new_inlines = [f"{k}:: {v}" for k, v in existing.items()]
    result_lines = lines[:strip_start] + new_inlines + [""] + lines[q_end:]
    file_path.write_text("\n".join(result_lines), encoding="utf-8")
    logger.debug(f"Q{qid} inline 元数据已更新: {updates}")
