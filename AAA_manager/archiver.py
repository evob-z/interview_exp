"""
archiver.py - 归档分类模块
负责验证/规范化面试记录文件名，将结构化问题分类追加到问题库，并执行去重检测。
"""

import json
import os
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from config import INTERVIEW_REPO_PATH, QUESTION_BANK_PATH
from logger import get_logger

logger = get_logger("archiver")

# ──────────────────────────────────────────────
# 分类规则映射
# ──────────────────────────────────────────────

CATEGORY_FILE_MAP = {
    "项目-law_sea": "项目-law_sea.md",
    "项目-compliance_checker": "项目-compliance_checker.md",
    "项目-Agent_SFT_SHENWEI": "项目-Agent_SFT_SHENWEI.md",
    "AI_Coding": "AI_Coding.md",
    "八股": "八股.md",
}

# 文件名规范: {公司}_{类型}_{YYMMDD}_{场次}.md
FILENAME_PATTERN = re.compile(
    r"^(.+?)_(.+?)_(\d{6})_(.+?)\.md$"
)


# ──────────────────────────────────────────────
# 数据类
# ──────────────────────────────────────────────

@dataclass
class ArchiveResult:
    """归档结果"""
    source_file: str                          # 源面经文件
    renamed_to: str | None = None             # 重命名后的文件名（None 表示没有重命名）
    archived_questions: list[dict] = field(default_factory=list)   # [{"question": "...", "target_file": "...", "question_id": "Q5"}]
    skipped_duplicates: list[str] = field(default_factory=list)    # 跳过的重复题目


# ──────────────────────────────────────────────
# 文件名验证与规范化
# ──────────────────────────────────────────────

def validate_filename(filename: str) -> tuple[bool, str | None]:
    """
    验证文件名是否符合规范: {公司}_{类型}_{YYMMDD}_{场次}.md

    Returns:
        (is_valid, suggested_name)
        如果合规返回 (True, None)
        如果不合规返回 (False, suggested_name_or_None)
    """
    match = FILENAME_PATTERN.match(filename)
    if match:
        return (True, None)
    # 不合规，尝试提供建议名称（返回 None 表示无法自动推断）
    logger.warning(f"文件名不符合规范: {filename}")
    return (False, None)


def get_interview_date(company: str) -> str | None:
    """
    从 INTERVIEW_REPO_PATH/.interview_dates.json 查找公司对应日期。
    返回 YYMMDD 格式字符串，找不到返回 None。
    """
    dates_file = Path(INTERVIEW_REPO_PATH) / ".interview_dates.json"
    if not dates_file.exists():
        logger.debug(f".interview_dates.json 不存在: {dates_file}")
        return None

    try:
        with open(dates_file, "r", encoding="utf-8") as f:
            records = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"读取 .interview_dates.json 失败: {e}")
        return None

    # 模糊匹配公司名：支持部分匹配（如 "蚂蚁" 匹配 "蚂蚁集团"）
    for record in records:
        record_company = record.get("company", "")
        if company in record_company or record_company in company:
            date = record.get("date", "")
            if date:
                logger.debug(f"找到公司 '{company}' 对应日期: {date}")
                return date

    logger.debug(f"未找到公司 '{company}' 的面试日期")
    return None


def normalize_filename(file_path: str) -> str:
    """
    尝试规范化文件名。
    - 从 .interview_dates.json 查日期
    - 如果找不到日期，返回原文件路径（不强制重命名）
    - 如果可以规范化，执行重命名并返回新路径
    """
    path = Path(file_path)
    filename = path.name

    is_valid, _ = validate_filename(filename)
    if is_valid:
        logger.info(f"文件名已符合规范: {filename}")
        return file_path

    # 尝试从文件名中解析公司名（假设下划线分隔，第一段为公司名）
    stem = path.stem
    parts = stem.split("_")

    if len(parts) >= 1:
        company = parts[0]
        date = get_interview_date(company)

        if date and len(parts) >= 2:
            # 尝试构建规范文件名
            category = parts[1] if len(parts) >= 2 else "技术"
            round_info = parts[2] if len(parts) >= 3 else "技术"

            # 检查是否只是缺少日期
            new_name = f"{company}_{category}_{date}_{round_info}.md"
            new_path = path.parent / new_name

            # 避免覆盖已有文件
            if new_path.exists() and new_path != path:
                logger.warning(f"目标文件已存在，无法重命名: {new_path}")
                return file_path

            try:
                path.rename(new_path)
                logger.info(f"文件重命名: {filename} → {new_name}")
                return str(new_path)
            except OSError as e:
                logger.error(f"重命名失败: {e}")
                return file_path

    logger.info(f"无法规范化文件名，保持原样: {filename}")
    return file_path


# ──────────────────────────────────────────────
# 问题库操作
# ──────────────────────────────────────────────

def get_next_question_id(file_path: str) -> int:
    """读取问题库 md 文件，返回下一个可用的 Q 编号"""
    path = Path(file_path)
    if not path.exists():
        return 1

    try:
        content = path.read_text(encoding="utf-8")
    except IOError as e:
        logger.error(f"读取文件失败 {file_path}: {e}")
        return 1

    # 匹配所有 Q{N} 格式的编号（支持 ## Q1、### Q1 等各级标题）
    pattern = re.compile(r"^#{2,4}\s+Q(\d+)", re.MULTILINE)
    matches = pattern.findall(content)

    if not matches:
        return 1

    max_id = max(int(m) for m in matches)
    return max_id + 1


def check_duplicate(file_path: str, source_label: str, question_text: str) -> bool:
    """
    检查是否重复：
    - 同来源标签出现在文件中 → 进一步检查文本相似度
    - 文本相似度 >80%（SequenceMatcher） → 重复
    """
    path = Path(file_path)
    if not path.exists():
        return False

    try:
        content = path.read_text(encoding="utf-8")
    except IOError:
        return False

    # 按 Q 条目分块
    blocks = re.split(r"(?=^#{2,4}\s+Q\d+)", content, flags=re.MULTILINE)

    for block in blocks:
        if not block.strip():
            continue

        # 检查同来源
        if source_label in block:
            # 提取该块中的问题文本（标题部分）
            title_match = re.search(r"Q\d+[：:]\s*(.+)", block)
            if title_match:
                existing_text = title_match.group(1).strip()
                similarity = SequenceMatcher(
                    None, question_text, existing_text
                ).ratio()
                if similarity > 0.8:
                    return True

        # 即使不同来源，也检查文本高相似度
        title_match = re.search(r"Q\d+[：:]\s*(.+)", block)
        if title_match:
            existing_text = title_match.group(1).strip()
            similarity = SequenceMatcher(
                None, question_text, existing_text
            ).ratio()
            if similarity > 0.8:
                return True

    return False


def _append_question_to_file(
    file_path: str,
    question_id: int,
    question_text: str,
    source_label: str,
    original_id: int,
) -> None:
    """将单个问题追加到问题库 md 文件末尾"""
    entry = (
        f"\n\n## Q{question_id}：{question_text}\n"
        f"- **来源**：{source_label} #{original_id}\n"
        f"- **要点**：待补充\n"
    )

    path = Path(file_path)

    # 确保文件存在
    if not path.exists():
        logger.warning(f"目标文件不存在，将创建: {file_path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.stem}\n", encoding="utf-8")

    with open(file_path, "a", encoding="utf-8") as f:
        f.write(entry)

    logger.debug(f"追加 Q{question_id} 到 {path.name}")


# ──────────────────────────────────────────────
# 核心归档函数
# ──────────────────────────────────────────────

def archive_questions(
    questions: list[dict],
    source_label: str,
) -> ArchiveResult:
    """
    将问题列表归档到问题库。

    Args:
        questions: 问题列表，每项格式：
            {"id": 1, "text": "问题文本", "category_suggestion": "项目-law_sea"}
        source_label: 来源标签，如 "蚂蚁_大厂_260423_一面技术"

    流程:
    1. 对每个问题，根据 category_suggestion 确定目标文件
    2. 读取目标文件，获取当前最大 Q 编号
    3. 检查是否已存在相同来源+相似内容的条目（去重）
    4. 追加新条目到文件末尾
    5. 返回归档结果
    """
    result = ArchiveResult(source_file=source_label)

    for q in questions:
        q_id = q.get("id", 0)
        q_text = q.get("text", "").strip()
        category = q.get("category_suggestion", "八股")

        if not q_text:
            logger.warning(f"跳过空问题 (id={q_id})")
            continue

        # 确定目标文件
        target_filename = CATEGORY_FILE_MAP.get(category)
        if not target_filename:
            logger.warning(
                f"未知分类 '{category}'，归入八股。问题: {q_text[:30]}..."
            )
            target_filename = CATEGORY_FILE_MAP["八股"]

        target_path = str(Path(QUESTION_BANK_PATH) / target_filename)

        # 去重检测
        if check_duplicate(target_path, source_label, q_text):
            logger.info(f"跳过重复问题: {q_text[:40]}...")
            result.skipped_duplicates.append(q_text)
            continue

        # 获取下一个 Q 编号
        next_id = get_next_question_id(target_path)

        # 追加到文件
        _append_question_to_file(
            file_path=target_path,
            question_id=next_id,
            question_text=q_text,
            source_label=source_label,
            original_id=q_id,
        )

        result.archived_questions.append({
            "question": q_text,
            "target_file": target_filename,
            "question_id": f"Q{next_id}",
        })

        logger.info(
            f"归档成功: Q{next_id} → {target_filename} "
            f"(来源: {source_label} #{q_id})"
        )

    logger.info(
        f"归档完成: 共 {len(result.archived_questions)} 条新增, "
        f"{len(result.skipped_duplicates)} 条跳过(重复)"
    )
    return result
