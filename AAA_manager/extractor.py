"""
extractor.py - 面试问题抽取模块
从非结构化面试记录中抽取结构化问题清单。
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from config import INTERVIEW_REPO_PATH
from llm_client import chat_completion
from logger import get_logger

logger = get_logger("extractor")

# prompts 目录定位
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# 精简版 fallback prompt（当文件不存在时使用）
FALLBACK_SYSTEM_PROMPT = """你是一个面试问题抽取助手。从面试原始文本中抽取结构化问题清单。
规则：
1. 识别显式问句和隐式追问
2. 去口语化（去掉嗯、啊、对吧、就是等填充词）
3. 同一主题连续追问标记 is_followup=true
4. 根据内容给出分类建议：项目-law_sea / 项目-compliance_checker / 项目-Agent_SFT_SHENWEI / AI_Coding / 八股

输出合法 JSON：
{
  "company": "公司名",
  "company_type": "大厂|中厂|小厂|国企|外企",
  "round": "一面技术|二面技术|HR面|交叉面|主管面",
  "questions": [{"id": 1, "text": "问题文本", "category_suggestion": "分类", "is_followup": false}],
  "metadata": {"interviewer_intro": "", "notes": ""}
}
约束：不编造问题，不脑补答案，保持原始顺序。"""


@dataclass
class ExtractedQuestion:
    """抽取出的单个问题"""
    id: int
    text: str                    # 去口语化的问题文本
    category_suggestion: str     # 建议归属文件（如 "项目-law_sea"、"八股"、"AI_Coding"）
    is_followup: bool = False    # 是否是追问


@dataclass
class ExtractionResult:
    """抽取结果"""
    company: str            # 公司名
    company_type: str       # 类型（大厂/中厂/小厂/国企/外企）
    round: str              # 场次（一面技术/二面技术等）
    questions: list[ExtractedQuestion] = field(default_factory=list)
    raw_file: str = ""      # 源文件路径


def _load_system_prompt() -> str:
    """加载 system prompt，优先从文件读取，不存在则用 fallback。"""
    prompt_file = PROMPTS_DIR / "extract_system.md"
    try:
        if prompt_file.exists():
            content = prompt_file.read_text(encoding="utf-8")
            logger.debug(f"已加载 system prompt: {prompt_file}")
            return content
    except Exception as e:
        logger.warning(f"读取 system prompt 失败: {e}")

    logger.info("使用 fallback system prompt")
    return FALLBACK_SYSTEM_PROMPT


def needs_extraction(file_content: str) -> bool:
    """
    判断文件内容是否需要抽取。

    需要抽取（返回 True）:
    - 含 "说话人" + 时间戳格式（录音转写）
    - 纯文本连续段落，无 ## 标题、无编号
    - 有明显口语化特征（嗯、啊、对吧、就是）

    不需要抽取（返回 False）:
    - 已有 ## Q{N} 或 ### Q{N} 编号格式
    - 已有编号列表（1. 2. 3.）+ 问题格式
    - 文件已经是结构化面经
    """
    if not file_content or not file_content.strip():
        return False

    # ---------- 不需要抽取的特征 ----------

    # 已有 Q{N} 编号格式（## Q1 / ### Q1）
    if re.search(r"^#{2,3}\s*Q\d+", file_content, re.MULTILINE):
        logger.debug("检测到 Q{N} 编号格式，无需抽取")
        return False

    # 已有编号列表（至少 3 个连续编号项）
    numbered_items = re.findall(r"^\d+\.\s+.+", file_content, re.MULTILINE)
    if len(numbered_items) >= 3:
        # 进一步检查：如果编号项看起来像问题列表
        question_like = sum(
            1 for item in numbered_items
            if re.search(r"[?？吗呢怎么为什么如何介绍]", item)
        )
        if question_like >= 2:
            logger.debug("检测到结构化编号问题列表，无需抽取")
            return False

    # 已有多个 ## 标题（结构化文档）
    headings = re.findall(r"^##\s+.+", file_content, re.MULTILINE)
    if len(headings) >= 3:
        logger.debug("检测到多个二级标题，文件已结构化，无需抽取")
        return False

    # ---------- 需要抽取的特征 ----------

    # 录音转写特征：含 "说话人" + 时间戳
    has_speaker = bool(re.search(r"说话人\s*[12]", file_content))
    has_timestamp = bool(re.search(r"\d{1,2}:\d{2}(:\d{2})?", file_content))
    if has_speaker and has_timestamp:
        logger.debug("检测到录音转写格式，需要抽取")
        return True

    # 口语化特征
    oral_markers = ["嗯", "啊", "对吧", "就是说", "那个", "然后呢", "这个嘛"]
    oral_count = sum(file_content.count(marker) for marker in oral_markers)
    if oral_count >= 5:
        logger.debug(f"检测到口语化特征 ({oral_count} 处)，需要抽取")
        return True

    # 纯文本连续段落（无标题、无列表，但有足够长度）
    lines = file_content.strip().split("\n")
    non_empty_lines = [l for l in lines if l.strip()]
    if len(non_empty_lines) >= 10:
        # 检查是否缺少结构化标记
        has_any_structure = bool(
            re.search(r"^(#+\s|[-*]\s|\d+\.\s)", file_content, re.MULTILINE)
        )
        if not has_any_structure:
            logger.debug("检测到纯文本连续段落，需要抽取")
            return True

    return False


def _parse_extraction_result(json_str: str, raw_file: str) -> ExtractionResult | None:
    """解析 LLM 返回的 JSON 为 ExtractionResult。"""
    try:
        # 尝试清理可能的 markdown 代码块包裹
        cleaned = json_str.strip()
        if cleaned.startswith("```"):
            # 去掉 ```json 和 ```
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"JSON 解析失败: {e}")
        logger.debug(f"原始返回内容: {json_str[:500]}")
        return None

    # 解析 questions
    questions = []
    for q in data.get("questions", []):
        try:
            questions.append(ExtractedQuestion(
                id=int(q.get("id", 0)),
                text=str(q.get("text", "")),
                category_suggestion=str(q.get("category_suggestion", "")),
                is_followup=bool(q.get("is_followup", False)),
            ))
        except (TypeError, ValueError) as e:
            logger.warning(f"跳过无法解析的问题项: {e}")
            continue

    if not questions:
        logger.warning("未解析出任何问题")
        return None

    return ExtractionResult(
        company=str(data.get("company", "")),
        company_type=str(data.get("company_type", "")),
        round=str(data.get("round", "")),
        questions=questions,
        raw_file=raw_file,
    )


def extract_questions(file_path: str) -> ExtractionResult | None:
    """
    从文件中抽取问题。

    流程:
    1. 读取文件内容
    2. 判断是否需要抽取（不需要则返回 None）
    3. 加载 prompts/extract_system.md 作为 system prompt
    4. 调用 LLM，要求以 JSON 格式返回
    5. 解析 JSON 为 ExtractionResult

    Returns:
        ExtractionResult 或 None（如果文件已经是结构化的）
    """
    file_path_obj = Path(file_path)

    # 1. 读取文件内容
    if not file_path_obj.exists():
        logger.error(f"文件不存在: {file_path}")
        return None

    try:
        content = file_path_obj.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"读取文件失败: {file_path}, 错误: {e}")
        return None

    # 2. 判断是否需要抽取
    if not needs_extraction(content):
        logger.info(f"文件已结构化，无需抽取: {file_path_obj.name}")
        return None

    logger.info(f"开始抽取问题: {file_path_obj.name}")

    # 3. 加载 system prompt
    system_prompt = _load_system_prompt()

    # 4. 调用 LLM
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ]

    try:
        response = chat_completion(
            messages=messages,
            temperature=0.3,
            response_format={"type": "json_object"},
        )
    except Exception as e:
        logger.error(f"LLM 调用失败: {e}")
        return None

    # 5. 解析结果
    result = _parse_extraction_result(response, raw_file=str(file_path))

    if result:
        logger.info(
            f"抽取完成: {result.company} {result.round}, "
            f"共 {len(result.questions)} 个问题"
        )
    else:
        logger.warning(f"抽取结果解析失败: {file_path_obj.name}")

    return result
