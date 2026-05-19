"""
reviewer.py - 面试复盘分析模块
对面经文件生成完整复盘分析报告。

主流程：用户指定 面试原始问题/ 中的文件 → 校验结构化 → 生成复盘 → 写入 面试复盘/
"""

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from config import INTERVIEW_REPO_PATH, RAW_INPUT_DIR, REVIEW_OUTPUT_DIR
from llm_client import chat_completion
from logger import get_logger

logger = get_logger("reviewer")

# 本文件所在目录
_MODULE_DIR = Path(__file__).resolve().parent

# Fallback prompt（当模板文件不存在时使用）
_FALLBACK_PROMPT = """你是一个资深面试教练。请对以下面试问题记录进行复盘分析，输出包含三段：
1. 问题分类与占比（Markdown 表格：类别|题号|数量|占比|面试官意图）
2. 面试官最在意的 3 件事（金句+题号+潜台词）
3. 面试官画像（5条要点）+ 复盘建议（4条可执行项）
报告以 `### 一、问题分类与占比` 开头，直接输出 Markdown 格式。"""

# 独立复盘文件使用的完整 prompt
_FULL_REVIEW_PROMPT = """你是一个资深面试教练。请对以下面试问题记录进行深度复盘分析，生成一份**完整的独立复盘文件**。

## 输出格式要求（严格遵守）

请按以下结构输出完整的 Markdown 报告：

```
## 一、面试题原始记录（{N} 题）

### A. {分类1}
1. 问题1
2. 问题2
...

### B. {分类2}
...

---

## 二、面试官关注点总结与画像分析

### 1. 问题分类与占比
| 类别 | 题号 | 数量 | 占比 | 面试官意图 |
| --- | --- | --- | --- | --- |
...

### 2. 面试官最在意的 3 件事
**① ...**
（对应题号 + 潜台词分析 + 考察目的）

**② ...**
...

**③ ...**
...

### 3. 面试官想要什么样的人
- 要点1
- 要点2
...

### 4. 给自己的复盘建议
- 建议1
- 建议2
...
```

## 具体要求
1. **面试题原始记录**：将原始问题按面试官考察意图分类（如项目深挖、技术选型、AI工具使用、Agent核心概念、综合背景等），每类用 ### A/B/C... 标题，问题用数字编号
2. **问题分类与占比**：Markdown 表格，占比用 ~XX%
3. **面试官最在意的 3 件事**：每件事用金句点题，指出对应题号，分析潜台词
4. **面试官想要的人**：5 条要点
5. **复盘建议**：4 条可执行改进项

## 风格要求
- 避免空泛，每条观点用题号回溯支撑
- 建议要可执行，不要鸡汤
- 直接输出 Markdown，不要用 JSON
- 报告以 `## 一、面试题原始记录` 开头"""


@dataclass
class ReviewResult:
    """复盘结果"""
    source_file: str          # 被复盘的面经文件
    report_text: str          # 生成的复盘报告（Markdown 格式）
    question_count: int       # 分析的问题数量
    top_concerns: list[str] = field(default_factory=list)  # 面试官最关注的 TOP3
    output_file: str = ""     # 输出的独立复盘文件路径（新模式下有值）


def validate_review_input(file_path: str) -> tuple[bool, str]:
    """
    校验 review 的输入文件是否合法。

    规则：
    1. 文件必须位于 面试原始问题/ 目录
    2. 文件内容必须已结构化（包含编号问题列表）

    Returns:
        (通过/不通过, 错误信息)
    """
    path = Path(file_path).resolve()
    raw_dir = (Path(INTERVIEW_REPO_PATH) / RAW_INPUT_DIR).resolve()

    # 1. 校验文件是否在 面试原始问题/ 目录
    try:
        path.relative_to(raw_dir)
    except ValueError:
        return False, "错误：review 只接受 面试原始问题/ 目录中的文件"

    # 2. 校验文件是否存在
    if not path.exists():
        return False, f"错误：文件不存在: {file_path}"

    # 3. 校验文件内容是否已结构化
    content = path.read_text(encoding="utf-8")
    if not _is_structured(content):
        return False, "错误：文件尚未结构化，请先执行 extract"

    return True, ""


def _is_structured(content: str) -> bool:
    """
    判断文件内容是否已结构化。

    规则：
    - 包含 3 个以上编号列表项（^\d+[.、]\s+.+） → 已结构化
    - 或包含 ## Q{N} / ### Q{N} 格式 → 已结构化
    - 否则 → 未结构化
    """
    lines = content.split("\n")

    # 检查 Q{N} 格式
    q_pattern = re.compile(r"^#{2,4}\s*Q\d+")
    q_count = sum(1 for line in lines if q_pattern.match(line))
    if q_count >= 3:
        return True

    # 检查编号列表项
    num_pattern = re.compile(r"^\d+[\.\.\、]\s+.+")
    num_count = sum(1 for line in lines if num_pattern.match(line))
    if num_count >= 3:
        return True

    return False


def _load_review_prompt() -> str:
    """加载复盘 prompt 模板，不存在则使用 fallback。"""
    template_path = _MODULE_DIR / "prompts" / "review_template.md"
    if template_path.exists():
        logger.debug(f"加载 prompt 模板: {template_path}")
        return template_path.read_text(encoding="utf-8")
    else:
        logger.warning(f"模板文件不存在: {template_path}，使用内置 fallback prompt")
        return _FALLBACK_PROMPT


def _count_questions(content: str) -> int:
    """统计面经文件中的问题数量。"""
    # 匹配常见问题格式：数字编号、- 列表项中的问号、## 标题中的问题等
    patterns = [
        r"^\s*\d+[\.\、\)]\s*.+",      # 1. xxx / 1、xxx / 1) xxx
        r"^\s*[-*]\s*.+[？?]",          # - xxx？
        r"^#{1,4}\s*\d+[\.\、]",        # ## 1. xxx
    ]
    lines = content.split("\n")
    count = 0
    for line in lines:
        for pattern in patterns:
            if re.match(pattern, line):
                count += 1
                break
    # 至少返回 1（如果文件有内容的话）
    return max(count, 1) if content.strip() else 0


def _extract_top_concerns(report: str) -> list[str]:
    """从复盘报告中提取面试官最关注的 TOP3 主题。"""
    concerns = []
    # 匹配 **1. xxx** 或 **数字. xxx** 格式
    pattern = r"\*\*\d+\.\s*(.+?)\*\*"
    matches = re.findall(pattern, report)
    # 取第二段（面试官最在意的 3 件事）中的匹配
    # 通常在 "### 二、" 之后
    section_start = report.find("### 二、")
    section_end = report.find("### 三、")
    if section_start != -1:
        section = report[section_start:section_end] if section_end != -1 else report[section_start:]
        section_matches = re.findall(pattern, section)
        if section_matches:
            concerns = section_matches[:3]
    # 如果上面没提取到，用全文匹配的前 3 个
    if not concerns and matches:
        concerns = matches[:3]
    return concerns


def _format_append_report(report_text: str) -> str:
    """格式化要追加到文件末尾的报告内容。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    header = f"\n---\n\n## 面试复盘分析\n\n> 自动生成于 {now}\n\n"
    return header + report_text + "\n"


def review_interview(
    file_path: str,
    append_to_file: bool = True,
    output_mode: str = "append",
    output_dir: str | None = None,
    extracted_data: dict | None = None,
) -> ReviewResult:
    """
    对面经文件进行复盘分析。

    Args:
        file_path: 面经文件路径
        append_to_file: 是否将报告追加到原文件末尾（旧参数，向后兼容）
        output_mode: 输出模式，"append"=追加到原文件，"standalone"=生成独立文件
        output_dir: 独立文件输出目录（仅 output_mode="standalone" 时有效）
        extracted_data: extractor 的输出数据（仅 output_mode="standalone" 时有效）

    Returns:
        ReviewResult 复盘结果
    """
    # 如果是独立文件模式，委托给 generate_review_file
    if output_mode == "standalone":
        return generate_review_file(
            source_file=file_path,
            extracted_data=extracted_data,
            output_dir=output_dir,
        )
    file_path = str(Path(file_path).resolve())
    logger.info(f"开始复盘分析: {file_path}")

    # 1. 读取面经文件内容
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"面经文件不存在: {file_path}")

    content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError(f"面经文件为空: {file_path}")

    logger.info(f"文件读取成功，长度: {len(content)} 字符")

    # 2. 加载 prompt 模板
    system_prompt = _load_review_prompt()

    # 3. 调用 LLM 生成复盘报告
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ]

    logger.info("调用 LLM 生成复盘报告...")
    report_text = chat_completion(
        messages=messages,
        temperature=0.5,
        max_tokens=2048,
    )
    logger.info(f"复盘报告生成成功，长度: {len(report_text)} 字符")

    # 4. 统计问题数量和提取关注点
    question_count = _count_questions(content)
    top_concerns = _extract_top_concerns(report_text)
    logger.info(f"统计问题数: {question_count}, TOP3 关注点: {top_concerns}")

    # 5. 如果 append_to_file=True，追加到原文件末尾
    if append_to_file:
        append_content = _format_append_report(report_text)
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(append_content)
        logger.info(f"复盘报告已追加到文件: {file_path}")

    return ReviewResult(
        source_file=file_path,
        report_text=report_text,
        question_count=question_count,
        top_concerns=top_concerns,
    )


def _infer_review_filename(source_file: str, extracted_data: dict | None = None) -> str:
    """
    从源文件名或 extractor 的输出推断复盘文件名。
    目标格式：{公司}_{类型}_{YYMMDD}_{场次}.md

    优先使用 extracted_data 中的信息，其次从文件名解析。
    """
    stem = Path(source_file).stem

    # 尝试从 extracted_data 推断
    if extracted_data:
        company = extracted_data.get("company", "")
        company_type = extracted_data.get("company_type", "")
        round_info = extracted_data.get("round", "")
        date_str = extracted_data.get("date", "")

        # 如果 extracted_data 缺少日期，尝试从文件名解析
        if not date_str:
            date_match = re.search(r"(\d{6})", stem)
            if date_match:
                date_str = date_match.group(1)

        if company and company_type and date_str and round_info:
            return f"{company}_{company_type}_{date_str}_{round_info}.md"

    # 尝试从文件名解析（已符合规范的文件名）
    filename_match = re.match(r"^(.+?)_(.+?)_(\d{6})_(.+?)$", stem)
    if filename_match:
        return Path(source_file).name  # 已是规范格式，直接用

    # 无法推断，使用原文件名
    logger.warning(f"无法推断复盘文件名，使用原文件名: {stem}")
    return Path(source_file).name


def generate_review_file(
    source_file: str,
    extracted_data: dict | None = None,
    output_dir: str | None = None,
    reflection_context: str | None = None,
) -> ReviewResult:
    """
    生成独立的完整复盘文件到指定目录。

    Args:
        source_file: 原始面经文件路径
        extracted_data: extractor 的输出数据（用于推断文件名和提供上下文）
            格式: {"company": "...", "company_type": "...", "round": "...", "date": "..."}
        output_dir: 输出目录路径，默认使用 config.REVIEW_OUTPUT_DIR
        reflection_context: 反思 Agent 输出的实际回答表现摘要（可选）

    Returns:
        ReviewResult 复盘结果（含 output_file 路径）
    """
    source_file = str(Path(source_file).resolve())
    logger.info(f"开始生成独立复盘文件: {source_file}")

    # 1. 读取面经文件内容
    path = Path(source_file)
    if not path.exists():
        logger.error(f"面经文件不存在: {source_file}")
        raise FileNotFoundError(f"面经文件不存在: {source_file}")

    content = path.read_text(encoding="utf-8")
    if not content.strip():
        logger.error(f"面经文件为空: {source_file}")
        raise ValueError(f"面经文件为空: {source_file}")

    logger.info(f"文件读取成功，长度: {len(content)} 字符")

    # 2. 推断输出文件名和路径
    review_filename = _infer_review_filename(source_file, extracted_data)

    if output_dir:
        out_dir = Path(output_dir)
    else:
        out_dir = Path(INTERVIEW_REPO_PATH) / REVIEW_OUTPUT_DIR

    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / review_filename

    # 3. 构建完整 prompt —— 使用独立复盘文件的 prompt
    system_prompt = _FULL_REVIEW_PROMPT

    # 推断标题信息
    title_info = ""
    if extracted_data:
        company = extracted_data.get("company", "")
        round_info = extracted_data.get("round", "")
        if company and round_info:
            title_info = f"{company}{round_info}"
    if not title_info:
        title_info = Path(source_file).stem

    # 4. 调用 LLM 生成复盘报告
    user_content = f"以下是 **{title_info}** 的面试问题记录，请生成完整复盘报告：\n\n{content}"

    # 追加反思上下文（若有）
    if reflection_context:
        user_content += f"\n\n{reflection_context}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    logger.info("调用 LLM 生成完整复盘报告...")
    report_text = chat_completion(
        messages=messages,
        temperature=0.5,
        max_tokens=4096,
    )
    logger.info(f"复盘报告生成成功，长度: {len(report_text)} 字符")

    # 5. 统计和提取
    question_count = _count_questions(content)
    top_concerns = _extract_top_concerns(report_text)
    logger.info(f"统计问题数: {question_count}, TOP3 关注点: {top_concerns}")

    # 6. 组装完整文件内容并写入
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    file_content = f"# {title_info} · 问题清单与复盘\n\n> 自动生成于 {now}\n\n{report_text}\n"

    output_path.write_text(file_content, encoding="utf-8")
    logger.info(f"独立复盘文件已生成: {output_path}")

    return ReviewResult(
        source_file=source_file,
        report_text=report_text,
        question_count=question_count,
        top_concerns=top_concerns,
        output_file=str(output_path),
    )


# [DEPRECATED] find_latest_interview 已废弃，不再被 CLI 调用
# Web API 如有需要可保留，但建议迁移到新流程
def find_latest_interview(repo_path: str = None) -> str | None:
    """
    [DEPRECATED] 找到最新的面经文件（按文件名中的 YYMMDD 排序）。
    此函数已废弃，新 CLI 流程要求用户显式指定文件。
    """
    import warnings
    warnings.warn("find_latest_interview() 已废弃，请使用显式文件路径", DeprecationWarning, stacklevel=2)

    search_path = Path(repo_path) if repo_path else INTERVIEW_REPO_PATH
    logger.info(f"搜索最新面经文件，路径: {search_path}")

    date_pattern = re.compile(r"(\d{6})")
    candidates: list[tuple[str, str]] = []

    for md_file in search_path.rglob("*.md"):
        rel_path = md_file.relative_to(search_path)
        skip_dirs = {"问题库", "AAA_manager", ".qoder", "面试"}
        if any(part in skip_dirs for part in rel_path.parts[:-1]):
            continue
        match = date_pattern.search(md_file.stem)
        if match:
            candidates.append((match.group(1), str(md_file)))

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


if __name__ == "__main__":
    # 快速测试
    import sys
    if len(sys.argv) > 1:
        test_file = sys.argv[1]
        valid, err = validate_review_input(test_file)
        if not valid:
            print(f"[校验失败] {err}")
        else:
            print(f"[校验通过] 开始生成复盘...")
            result = generate_review_file(source_file=test_file)
            print(f"输出文件: {result.output_file}")
    else:
        print("用法: python reviewer.py <面试原始问题/中的文件>")
