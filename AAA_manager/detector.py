"""
detector.py - Git 变更检测模块
检测面经仓库中的 Git 变更，分类返回需要处理的文件列表。

NOTE: 本模块仅由 Web API 使用（api/routes/sync.py、api/routes/stats.py），
      CLI 工作流已不再依赖此模块（见 main.py 的 extract/review/archive/sync 命令）。
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import git

from config import (
    INTERVIEW_REPO_PATH,
    LAST_SYNC_FILE,
    QUESTION_BANK_PATH,
    RAW_INPUT_DIR,
    REVIEW_OUTPUT_DIR,
    GIT_ENABLED,
)
from logger import get_logger

logger = get_logger("detector")

# 面试记录文件名模式：{任意}_{任意}_{6位数字}_{任意}.md
INTERVIEW_PATTERN = re.compile(r'^[^_]+_[^_]+_\d{6}_[^_]+\.md$')


@dataclass
class DetectionResult:
    """变更检测结果"""
    new_interviews: list[str] = field(default_factory=list)
    modified_docs: list[str] = field(default_factory=list)
    modified_questions: list[str] = field(default_factory=list)
    untracked_files: list[str] = field(default_factory=list)

    new_raw_inputs: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        """是否有任何变更"""
        return bool(
            self.new_interviews
            or self.new_raw_inputs
            or self.modified_docs
            or self.modified_questions
            or self.untracked_files
        )

    def summary(self) -> str:
        """返回变更摘要字符串"""
        parts = []
        if self.new_raw_inputs:
            parts.append(f"原始问题新文件: {len(self.new_raw_inputs)} 个")
        if self.new_interviews:
            parts.append(f"新面试记录(根目录): {len(self.new_interviews)} 个")
        if self.modified_questions:
            parts.append(f"问题库变更: {len(self.modified_questions)} 个")
        if self.modified_docs:
            parts.append(f"文档变更: {len(self.modified_docs)} 个")
        if self.untracked_files:
            parts.append(f"未追踪文件: {len(self.untracked_files)} 个")
        return "，".join(parts) if parts else "无变更"


def detect_changes(repo_path: str = None) -> DetectionResult:
    """
    检测面经仓库中的变更。

    检测规则：
    1. 根目录新增匹配 {X}_{X}_{6位数字}_{X}.md 格式的 → new_interviews
    2. 根目录新增其他 .md → untracked_files（可能是面试记录待确认）
    3. 问题库/*.md 有修改 → modified_questions
    4. .qoder/repowiki/** 有修改 → modified_docs
    5. 其他修改/新增 → 忽略

    Args:
        repo_path: 仓库路径，默认使用 config.INTERVIEW_REPO_PATH

    Returns:
        DetectionResult 实例
    """
    path = repo_path or str(INTERVIEW_REPO_PATH)
    result = DetectionResult()

    logger.info(f"开始检测变更: {path}")

    # ── 优先检测 面试原始问题/ 目录下的新 .md 文件（不依赖 Git）──
    raw_input_path = Path(path) / RAW_INPUT_DIR
    review_output_path = Path(path) / REVIEW_OUTPUT_DIR

    if raw_input_path.is_dir():
        for md_file in raw_input_path.glob("*.md"):
            if not md_file.is_file():
                continue
            # 判断是否已处理：检查 面试复盘/ 目录下是否存在同名文件
            review_counterpart = review_output_path / md_file.name
            if review_counterpart.exists():
                logger.debug(f"已处理过，跳过: {md_file.name}")
                continue
            full_path = str(md_file.resolve())
            result.new_raw_inputs.append(full_path)
            logger.info(f"发现原始问题新文件: {md_file.name}")
    else:
        logger.debug(f"原始问题目录不存在: {raw_input_path}")

    # ── Git 相关检测（由 GIT_ENABLED 控制，关闭时静默跳过）──
    if not GIT_ENABLED:
        logger.debug("Git 集成已关闭 (GIT_ENABLED=false)，跳过 Git 检测")
        return result

    try:
        repo = git.Repo(path)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError) as e:
        logger.warning(f"路径 '{path}' 不是有效的 Git 仓库: {e}，跳过 Git 检测")
        return result

    # 检测未追踪文件（新增文件）— 根目录兼容历史
    for filepath in repo.untracked_files:
        # filepath 是相对于仓库根目录的路径，使用 / 分隔
        # 只关注根目录下的文件（不含路径分隔符表示在根目录）
        if '/' in filepath or '\\' in filepath:
            # 非根目录文件，忽略
            continue

        if not filepath.endswith('.md'):
            continue

        full_path = str(Path(path) / filepath)

        if INTERVIEW_PATTERN.match(filepath):
            result.new_interviews.append(full_path)
            logger.info(f"发现新面试记录: {filepath}")
        else:
            result.untracked_files.append(full_path)
            logger.debug(f"发现未追踪 md 文件: {filepath}")

    # 检测已修改文件（工作区相对于暂存区的变更）
    try:
        diffs = repo.index.diff(None)  # 工作区 vs 暂存区
    except Exception as e:
        logger.warning(f"获取 diff 失败: {e}")
        diffs = []

    for diff in diffs:
        filepath = diff.a_path or diff.b_path
        if not filepath:
            continue

        # 问题库文件
        if filepath.startswith("问题库/") and filepath.endswith(".md"):
            full_path = str(Path(path) / filepath)
            result.modified_questions.append(full_path)
            logger.info(f"问题库文件变更: {filepath}")
        # repowiki 文档
        elif filepath.startswith(".qoder/repowiki/"):
            full_path = str(Path(path) / filepath)
            result.modified_docs.append(full_path)
            logger.debug(f"文档变更: {filepath}")

    # 同时检测暂存区相对于 HEAD 的变更
    try:
        staged_diffs = repo.index.diff("HEAD")
    except Exception as e:
        logger.debug(f"获取暂存区 diff 失败（可能是空仓库）: {e}")
        staged_diffs = []

    for diff in staged_diffs:
        filepath = diff.a_path or diff.b_path
        if not filepath:
            continue

        if filepath.startswith("问题库/") and filepath.endswith(".md"):
            full_path = str(Path(path) / filepath)
            if full_path not in result.modified_questions:
                result.modified_questions.append(full_path)
                logger.info(f"问题库文件变更（暂存）: {filepath}")
        elif filepath.startswith(".qoder/repowiki/"):
            full_path = str(Path(path) / filepath)
            if full_path not in result.modified_docs:
                result.modified_docs.append(full_path)
                logger.debug(f"文档变更（暂存）: {filepath}")

    logger.info(f"检测完成: {result.summary()}")
    return result


def get_last_sync_time() -> str | None:
    """
    读取 .last_sync_time 文件，返回 ISO 时间戳字符串。

    Returns:
        ISO 格式时间戳字符串，文件不存在则返回 None
    """
    if not LAST_SYNC_FILE.exists():
        logger.debug("上次同步时间文件不存在")
        return None

    try:
        content = LAST_SYNC_FILE.read_text(encoding="utf-8").strip()
        logger.debug(f"上次同步时间: {content}")
        return content
    except Exception as e:
        logger.warning(f"读取同步时间文件失败: {e}")
        return None


def update_last_sync_time():
    """更新 .last_sync_time 为当前时间（ISO 格式）"""
    now = datetime.now(timezone.utc).isoformat()
    try:
        LAST_SYNC_FILE.write_text(now, encoding="utf-8")
        logger.info(f"同步时间已更新: {now}")
    except Exception as e:
        logger.error(f"更新同步时间文件失败: {e}")
