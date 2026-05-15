"""会话问题导出模块 - 从模拟面试会话中提取原始问题，支持 LLM 改写"""
import json
import re
from pathlib import Path
from datetime import datetime
from logger import get_logger
from config import INTERVIEW_REPO_PATH, PROJECT_ALIASES
from llm_client import chat_completion

logger = get_logger("exporter")

SESSIONS_DIR = Path(__file__).resolve().parent / "data" / "sessions"
RAW_QUESTIONS_DIR = INTERVIEW_REPO_PATH / "面试原始问题"


def export_session_questions(session_id: str, filename: str = None, rewrite: bool = False) -> tuple[Path, int]:
    """
    从会话中提取 interview 模式的用户问题，生成标准问题列表文件。
    
    Args:
        session_id: 会话ID (8位hex)
        filename: 输出文件名(不含.md)，默认用 模拟面试_{YYMMDD}
        rewrite: 是否调用 LLM 对问题进行改写（使其自包含、归属项目）
    
    Returns:
        (output_path, question_count) 元组
    
    Raises:
        FileNotFoundError: 会话不存在
        ValueError: 没有找到面试问题
    """
    # 1. 读取会话
    session_path = SESSIONS_DIR / f"{session_id}.json"
    if not session_path.exists():
        raise FileNotFoundError(f"会话不存在: {session_id}")
    
    with open(session_path, "r", encoding="utf-8") as f:
        session = json.load(f)
    
    # 2. 过滤 interview 模式的用户消息（这些就是面试问题）
    questions = []
    for msg in session.get("messages", []):
        if msg.get("role") == "user" and msg.get("mode") == "interview":
            questions.append(msg["content"].strip())
    
    if not questions:
        raise ValueError(f"会话 {session_id} 中没有找到面试问题（interview模式的用户消息）")
    
    # 2.5 如果启用 rewrite，调用 LLM 改写问题
    if rewrite:
        messages = session.get("messages", [])
        questions = _rewrite_questions(messages, questions)
        logger.info(f"LLM 改写完成，共 {len(questions)} 个问题")
    
    # 3. 确定输出文件名
    if not filename:
        created = session.get("created_at", "")
        try:
            dt = datetime.fromisoformat(created)
            date_str = dt.strftime("%y%m%d")
        except (ValueError, TypeError):
            date_str = datetime.now().strftime("%y%m%d")
        filename = f"模拟面试_{date_str}"
    
    # 3.5 检查文件名是否符合规范格式
    STANDARD_PATTERN = re.compile(r"^.+_.+_\d{6}_.+$")
    if not STANDARD_PATTERN.match(filename):
        logger.warning(f"文件名未遵循规范格式(公司_规模_日期_面试类型): '{filename}'，可能影响后续复盘和入库的来源追溯")

    # 4. 生成编号列表格式
    lines = []
    for i, q in enumerate(questions, 1):
        lines.append(f"{i}. {q}")
    content = "\n".join(lines) + "\n"
    
    # 5. 写入文件
    RAW_QUESTIONS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RAW_QUESTIONS_DIR / f"{filename}.md"
    output_path.write_text(content, encoding="utf-8")
    
    logger.info(f"导出成功: {len(questions)} 个问题 → {output_path.name}")
    return output_path, len(questions)


def _rewrite_questions(messages: list[dict], questions: list[str]) -> list[str]:
    """
    调用 LLM 对原始面试问题进行批量改写，使其自包含、归属项目、便于复习。
    
    Args:
        messages: 会话完整消息列表（用于提取上下文）
        questions: 原始问题列表
    
    Returns:
        改写后的问题列表（与原列表等长）
    """
    # 构建每个问题的上下文概要（前一个 assistant 回答的前50字）
    question_contexts = []
    user_question_idx = 0
    for i, msg in enumerate(messages):
        if msg.get("role") == "user" and msg.get("mode") == "interview":
            # 找前一个 assistant 消息作为上下文
            prev_context = ""
            for j in range(i - 1, -1, -1):
                if messages[j].get("role") == "assistant":
                    prev_context = messages[j]["content"][:50].replace("\n", " ")
                    break
            question_contexts.append({
                "index": user_question_idx + 1,
                "question": questions[user_question_idx] if user_question_idx < len(questions) else "",
                "prev_assistant_context": prev_context,
            })
            user_question_idx += 1

    # 构建 system prompt
    system_prompt = """你是一个面试问题改写助手。你的任务是将面试中的口语化问题改写为清晰、自包含的问题标题。

用户有三个项目：
- law_sea：海商法RAG问答系统（晓海智法），包含向量+BM25+知识图谱三路混合检索
- Agent_SFT_SHENWEI：旅行顾问Agent+微调项目，包含多轮对话、Skill渐进式披露
- compliance_checker：中能建合规审查项目，包含合同审查、Skill设计

改写规则：
1. 如果问题明确涉及某个项目，在问题前标注 [项目名]，如 [law_sea]、[Agent_SFT_SHENWEI]、[compliance_checker]
2. 改写要求：简洁、自包含（不依赖上下文就能理解）、便于后续复习检索
3. 保持原问题的核心意图不变
4. 结合上下文（前一个回答涉及的主题）让问题含义完整
5. 不要添加原问题没有的信息或要求

输出格式：每行一个改写后的问题，编号对应原始编号，格式如：
1. 改写后的问题
2. 改写后的问题
...

只输出编号列表，不要其他解释。"""

    # 构建 user prompt
    user_lines = ["以下是面试中的原始问题列表，请逐一改写：\n"]
    for ctx in question_contexts:
        line = f"{ctx['index']}. {ctx['question']}"
        if ctx["prev_assistant_context"]:
            line += f"\n   [上文语境] 面试官之前的回答涉及: {ctx['prev_assistant_context']}..."
        user_lines.append(line)
    user_prompt = "\n".join(user_lines)

    # 调用 LLM
    try:
        result = chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=2048,
        )
    except Exception as e:
        logger.error(f"LLM 改写调用失败: {e}，回退为原始问题")
        return questions

    # 解析 LLM 返回结果
    rewritten = _parse_rewrite_result(result, len(questions))
    if len(rewritten) == len(questions):
        return rewritten
    else:
        logger.warning(f"LLM 改写结果数量不匹配（期望 {len(questions)}，得到 {len(rewritten)}），回退为原始问题")
        return questions


def _parse_rewrite_result(result: str, expected_count: int) -> list[str]:
    """
    解析 LLM 返回的编号列表格式文本。
    
    Args:
        result: LLM 返回的文本
        expected_count: 期望的问题数量
    
    Returns:
        解析后的问题列表
    """
    import re
    lines = result.strip().split("\n")
    parsed = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 匹配 "数字. 内容" 或 "数字、内容" 格式
        match = re.match(r"^\d+[\.\.、\)\]]\.?\s*(.+)", line)
        if match:
            parsed.append(match.group(1).strip())
    return parsed
