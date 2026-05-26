"""
obsidian_reader.py - Obsidian CLI 可选增强读取层

提供：
- 启动时健康检查（惰性求值，_is_cli_available()）
- CLI 加速查询（backlinks、search、tags）
- 无 Obsidian 时自动降级到 Python 纯文本解析

所有函数均可选，调用方负责 try/except 包裹。
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger("obsidian_reader")

# ── 启动时健康检查（惰性求值，仅在首次访问时执行 subprocess） ──

_obsidian_available: bool | None = None


def _is_cli_available() -> bool:
    """惰性检查 Obsidian CLI 是否可用。首次调用执行 subprocess，后续缓存。"""
    global _obsidian_available
    if _obsidian_available is not None:
        return _obsidian_available
    try:
        result = subprocess.run(
            ["obsidian", "version"],
            capture_output=True,
            timeout=5,
        )
        _obsidian_available = result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        _obsidian_available = False
    if _obsidian_available:
        logger.info("Obsidian CLI 可用，增强读取层已激活")
    else:
        logger.info("Obsidian CLI 不可用，增强读取层已禁用（降级到 Python 解析）")
    return _obsidian_available


# ── 降级路径 ──

_QUESTION_BANK_PATHS: list[Path] | None = None


def _get_question_bank_paths() -> list[Path]:
    """获取问题库所有 .md 文件路径（缓存）"""
    global _QUESTION_BANK_PATHS
    if _QUESTION_BANK_PATHS is not None:
        return _QUESTION_BANK_PATHS

    from config import QUESTION_BANK_PATH

    _QUESTION_BANK_PATHS = list(QUESTION_BANK_PATH.rglob("*.md"))
    return _QUESTION_BANK_PATHS


def _fallback_backlinks(target_path: str) -> list[str]:
    """降级：遍历问题库文件，精确解析 [[wikilink]] 引用"""
    file_name = Path(target_path).name
    file_stem = Path(target_path).stem
    results: list[str] = []
    for md_path in _get_question_bank_paths():
        content = md_path.read_text(encoding="utf-8")
        links = re.findall(r"\[\[(.+?)\]\]", content)
        # 精确比对：wikilink 目标需包含文件名或文件名不含扩展名的部分
        for link in links:
            target = link.split("|")[0].split("#")[0].strip()
            if target == file_name or target == file_stem:
                results.append(str(md_path))
                break
    return results


def _fallback_search(query: str) -> list[dict]:
    """降级：pathlib + grep 全文搜索"""
    results: list[dict] = []
    for md_path in _get_question_bank_paths():
        try:
            content = md_path.read_text(encoding="utf-8")
        except Exception:
            continue
        lines = content.split("\n")
        for lineno, line in enumerate(lines, 1):
            if query.lower() in line.lower():
                results.append({"file": str(md_path), "line": lineno, "text": line.strip()})
    return results


# ── 公开 API ──


def get_backlinks(file_path: str, *, fallback: bool = True) -> list[str]:
    """获取引用指定文件的所有其他文件。

    Args:
        file_path: 目标文件路径（相对 vault 的路径）
        fallback: CLI 不可用时是否降级到 Python 正则扫描

    Returns:
        文件路径列表
    """
    if _is_cli_available():
        try:
            result = subprocess.run(
                ["obsidian", "backlinks", f"path={file_path}", "format=json"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return [item.get("file", "") for item in data if isinstance(item, dict)]
        except Exception:
            logger.debug("Obsidian CLI backlinks 查询失败，降级到 Python 解析", exc_info=True)

    if fallback:
        return _fallback_backlinks(file_path)
    return []


def search_vault(query: str, *, limit: int = 50, fallback: bool = True) -> list[dict]:
    """全文搜索 vault。

    Args:
        query: 搜索关键词
        limit: 最大结果数
        fallback: CLI 不可用时是否降级到 Python 扫描

    Returns:
        [{"file": str, "line": int, "text": str}, ...]
    """
    if _is_cli_available():
        try:
            result = subprocess.run(
                ["obsidian", "search", f"query={query}", f"limit={limit}", "format=json"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return data if isinstance(data, list) else []
        except Exception:
            logger.debug("Obsidian CLI search 查询失败，降级到 Python 扫描", exc_info=True)

    if fallback:
        results = _fallback_search(query)
        return results[:limit]
    return []


def get_files_by_property(key: str, value: str) -> list[str]:
    """搜索 vault 中 frontmatter 包含 key=value 的文件。

    Args:
        key: frontmatter 字段名（如 mastery）
        value: 期望值（如 weak）

    Returns:
        文件路径列表
    """
    if _is_cli_available():
        try:
            result = subprocess.run(
                ["obsidian", "search", f"query={key}: {value}", "format=json"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if isinstance(data, list):
                    # 去重文件路径
                    files = list(dict.fromkeys(item.get("file", "") for item in data if isinstance(item, dict)))
                    return [f for f in files if f]
        except Exception:
            logger.debug("Obsidian CLI properties 查询失败", exc_info=True)

    # 降级：遍历文件，用 frontmatter_utils 检查
    try:
        from frontmatter_utils import read_frontmatter

        results: list[str] = []
        for md_path in _get_question_bank_paths():
            meta, _ = read_frontmatter(md_path)
            if meta.get(key) == value:
                results.append(str(md_path))
        return results
    except Exception:
        return []
