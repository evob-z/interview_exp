"""
git_ops.py - Git 操作模块
封装 Git 操作（add, commit），支持 dry-run 模式。
"""

from datetime import datetime
from pathlib import Path

import git

from config import INTERVIEW_REPO_PATH
from logger import get_logger

logger = get_logger("git_ops")


def stage_files(repo_path: str, file_paths: list[str]):
    """
    将指定文件添加到 git 暂存区。

    Args:
        repo_path: 仓库路径
        file_paths: 要暂存的文件完整路径列表
    """
    if not file_paths:
        logger.debug("没有文件需要暂存")
        return

    try:
        repo = git.Repo(repo_path)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError) as e:
        logger.error(f"无法打开 Git 仓库 '{repo_path}': {e}")
        return

    # 转换为相对路径（相对于仓库根目录）
    repo_root = Path(repo.working_dir)
    relative_paths = []
    for fp in file_paths:
        try:
            rel = str(Path(fp).relative_to(repo_root))
            relative_paths.append(rel)
        except ValueError:
            # 如果已经是相对路径，直接使用
            relative_paths.append(fp)

    try:
        repo.index.add(relative_paths)
        logger.info(f"已暂存 {len(relative_paths)} 个文件: {relative_paths}")
    except Exception as e:
        logger.error(f"暂存文件失败: {e}")


def commit_changes(repo_path: str, message: str, dry_run: bool = False) -> bool:
    """
    提交暂存区的更改。

    Args:
        repo_path: 仓库路径
        message: commit message
        dry_run: 如果 True，只打印会做什么，不实际提交

    Returns:
        是否成功提交（dry_run 模式下返回 True 表示有内容可提交）
    """
    try:
        repo = git.Repo(repo_path)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError) as e:
        logger.error(f"无法打开 Git 仓库 '{repo_path}': {e}")
        return False

    # 检查是否有暂存的更改
    staged = repo.index.diff("HEAD")
    if not staged and not repo.untracked_files:
        # 再检查一下是否有新文件已 add
        try:
            staged = repo.index.diff("HEAD")
        except Exception:
            pass
        if not staged:
            logger.info("暂存区没有更改，跳过提交")
            return False

    if dry_run:
        logger.info("[DRY-RUN] 将执行以下提交:")
        logger.info(f"[DRY-RUN] commit message: {message}")
        diff_summary = get_staged_diff(repo_path)
        logger.info(f"[DRY-RUN] 变更摘要:\n{diff_summary}")
        return True

    try:
        repo.index.commit(message)
        logger.info(f"提交成功: {message}")
        return True
    except Exception as e:
        logger.error(f"提交失败: {e}")
        return False


def generate_commit_message(summary: dict) -> str:
    """
    根据处理摘要生成 commit message。

    格式: "面经同步：{date} - {摘要}"
    示例: "面经同步：2026-05-11 - 归档蚂蚁一面(28题)，更新问题库3个文件"

    Args:
        summary: 处理摘要字典，结构如下:
            {
                "archived_files": ["蚂蚁_大厂_260423_一面技术.md"],
                "question_count": 28,
                "updated_banks": ["项目-law_sea.md", "八股.md", "AI_Coding.md"],
                "reviewed": True
            }

    Returns:
        格式化的 commit message
    """
    date_str = datetime.now().strftime("%Y-%m-%d")
    parts = []

    # 归档信息
    archived = summary.get("archived_files", [])
    question_count = summary.get("question_count", 0)
    if archived:
        # 从文件名提取简短描述
        for f in archived:
            name = Path(f).stem  # 去掉 .md 后缀
            # 尝试提取公司和面试轮次: {公司}_{规模}_{日期}_{轮次}
            segments = name.split("_")
            if len(segments) >= 4:
                company = segments[0]
                round_info = segments[3]
                desc = f"归档{company}{round_info}"
            else:
                desc = f"归档{name}"
            if question_count:
                desc += f"({question_count}题)"
            parts.append(desc)

    # 问题库更新
    updated_banks = summary.get("updated_banks", [])
    if updated_banks:
        parts.append(f"更新问题库{len(updated_banks)}个文件")

    # 审核标记
    if summary.get("reviewed"):
        pass  # 不额外添加，已在流程中

    detail = "，".join(parts) if parts else "常规同步"
    message = f"面经同步：{date_str} - {detail}"

    logger.debug(f"生成 commit message: {message}")
    return message


def get_staged_diff(repo_path: str) -> str:
    """
    获取暂存区的 diff 摘要，用于 dry-run 显示。

    Args:
        repo_path: 仓库路径

    Returns:
        暂存区 diff 的可读摘要字符串
    """
    try:
        repo = git.Repo(repo_path)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError) as e:
        return f"无法打开仓库: {e}"

    lines = []

    try:
        staged_diffs = repo.index.diff("HEAD")
    except Exception:
        staged_diffs = []

    if not staged_diffs:
        lines.append("暂存区无变更")
        return "\n".join(lines)

    for diff in staged_diffs:
        change_type = diff.change_type  # A=added, M=modified, D=deleted, R=renamed
        filepath = diff.a_path or diff.b_path
        type_map = {
            'A': '新增',
            'M': '修改',
            'D': '删除',
            'R': '重命名',
        }
        type_label = type_map.get(change_type, change_type)
        lines.append(f"  [{type_label}] {filepath}")

    return "\n".join(lines)
