"""
preparer.py - 岗位针对性面试预测题生成器

面向「面试前」场景，输入公司+岗位，自动：
1. 联网搜索近期 JD
2. 结合候选人简历与项目
3. 生成针对性预测题库并写入 岗位预测/ 目录
4. 写入的题库自动被 question_bank 纳入检索，供模拟面试功能召回
"""

from __future__ import annotations

import asyncio
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# 确保可以 import 同目录模块
sys.path.insert(0, str(Path(__file__).resolve().parent))

from logger import get_logger
from config import INTERVIEW_REPO_PATH, PREP_OUTPUT_DIR, PREP_QUESTION_COUNT, RESUME_DIR
from llm_client import chat_completion

logger = get_logger("preparer")

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# ──────────────────────────────────────────────
# 数据类
# ──────────────────────────────────────────────

@dataclass
class PrepareResult:
    """岗位预测生成结果"""
    company: str
    position: str
    date: str
    output_file: str = ""
    question_count: int = 0
    jd_source_count: int = 0
    jd_snippet_count: int = 0
    elapsed_sec: float = 0.0


# ──────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────

def _load_prepare_prompt() -> str:
    """加载岗位预测 system prompt"""
    prompt_file = PROMPTS_DIR / "prepare_system.md"
    if prompt_file.exists():
        try:
            return prompt_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"读取 prepare_system.md 失败: {e}")
    # 极简 fallback
    return (
        "你是一位资深面试官。基于公司 JD 与候选人简历项目信息，生成 12-18 道"
        "针对性面试预测题，按 Q1/Q2 格式输出 Markdown，每题包含 来源、考察点、"
        "要点、💬 面试话术（结合候选人项目）。严格按现有问题库格式。"
    )


def _sanitize_filename(s: str) -> str:
    """清理文件名里的非法字符"""
    s = s.strip()
    # Windows 非法字符
    s = re.sub(r'[\\/:*?"<>|]', "_", s)
    # 连续下划线压成一个
    s = re.sub(r"_+", "_", s)
    return s


def _default_date() -> str:
    """默认日期 YYMMDD"""
    return datetime.now().strftime("%y%m%d")


def _build_output_filename(company: str, position: str, date: str) -> str:
    """构造输出文件名：{公司}_{岗位}_{日期}.md"""
    parts = [_sanitize_filename(company), _sanitize_filename(position), _sanitize_filename(date)]
    return "_".join(p for p in parts if p) + ".md"


def _load_resume_summary(max_chars: int = 3000) -> str:
    """从 ResumeReader 获取简历文本摘要"""
    try:
        from knowledge.resume_reader import ResumeReader
        reader = ResumeReader(str(Path(INTERVIEW_REPO_PATH) / RESUME_DIR))
        info = reader.get_resume_info()
        raw = info.get("raw_text", "") or ""
        if len(raw) > max_chars:
            return raw[:max_chars] + "\n... [简历已截断]"
        return raw
    except Exception as e:
        logger.warning(f"读取简历失败，将以空简历继续: {e}")
        return ""


def _load_projects_context(max_chars_per_project: int = 2500) -> str:
    """从 ProjectReader 汇总各项目的启动层上下文（Tier 1-2）"""
    try:
        from config import PROJECT_CONFIGS
        from knowledge.project_reader import ProjectReader
        reader = ProjectReader(PROJECT_CONFIGS)
        reader.load_startup()
        blocks: list[str] = []
        for proj in getattr(reader, "_projects", []):
            name = proj.get("name", "")
            ctx = reader.get_context(name, max_tier=2)
            if ctx:
                if len(ctx) > max_chars_per_project:
                    ctx = ctx[:max_chars_per_project] + "\n... [项目文档已截断]"
                blocks.append(ctx)
        return "\n\n".join(blocks)
    except Exception as e:
        logger.warning(f"读取项目上下文失败，将以空项目继续: {e}")
        return ""


def _load_existing_questions_brief(top_n_per_cat: int = 10) -> str:
    """抓取现有题库中每分类前若干题目题干，用于去重提醒。"""
    try:
        from knowledge.question_bank import QuestionBank
        qb = QuestionBank(str(Path(INTERVIEW_REPO_PATH) / "问题库"))
        qb.load()
        by_cat: dict[str, list[str]] = {}
        for q in qb.questions:
            by_cat.setdefault(q["category"], []).append(f"Q{q['id']}：{q['text']}")
        lines = []
        for cat, items in by_cat.items():
            lines.append(f"[{cat}] 已有题目（前 {top_n_per_cat} 条）:")
            for it in items[:top_n_per_cat]:
                lines.append(f"  - {it}")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"读取现有题库失败: {e}")
        return ""


async def _fetch_jd(company: str, position: str) -> dict:
    """调用 web_searcher.search_jd；失败返回空结构"""
    try:
        # 在 web 环境下优先复用共享单例，避免重复初始化
        from core.web_searcher import WebSearcher
        from config import SEARCH_API_KEY, SEARCH_API_PROVIDER, ENABLE_WEB_SEARCH
        ws = WebSearcher(
            api_key=SEARCH_API_KEY,
            provider=SEARCH_API_PROVIDER,
            enabled=ENABLE_WEB_SEARCH,
        )
        return await ws.search_jd(company, position)
    except Exception as e:
        logger.warning(f"JD 搜索失败: {e}")
        return {
            "company": company, "position": position,
            "jd_snippets": [], "source_urls": [], "raw_results": [],
        }


def _format_jd_context(jd: dict, max_snippets: int = 8, max_chars: int = 4000) -> str:
    """将 JD 搜索结果组装成注入 prompt 的文本块"""
    snippets = jd.get("jd_snippets", [])[:max_snippets]
    urls = jd.get("source_urls", [])[:max_snippets]
    if not snippets and not urls:
        return "（未能检索到有效 JD 信息，请依据岗位名称和常识进行合理推断）"

    parts: list[str] = []
    for i, s in enumerate(snippets, 1):
        parts.append(f"[片段 {i}] {s}")
    text = "\n\n".join(parts)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... [JD 片段已截断]"

    if urls:
        text += "\n\n参考 URL：\n" + "\n".join(f"- {u}" for u in urls)
    return text


# ──────────────────────────────────────────────
# 核心入口
# ──────────────────────────────────────────────

def prepare_interview(
    company: str,
    position: str,
    date: str | None = None,
    output_dir: str | None = None,
    question_count: int | None = None,
) -> PrepareResult:
    """
    生成岗位预测题库文件。

    Args:
        company: 公司名（如 "字节跳动"）
        position: 岗位名（如 "AI应用开发实习生-AI数据与安全"）
        date: YYMMDD，默认为今天
        output_dir: 输出目录，默认 INTERVIEW_REPO_PATH / PREP_OUTPUT_DIR
        question_count: 题目数量建议值（LLM 最终题数以其判断为准）

    Returns:
        PrepareResult
    """
    start_ts = datetime.now()

    if not company or not position:
        raise ValueError("company 和 position 都不能为空")

    date = date or _default_date()
    qc = question_count or PREP_QUESTION_COUNT

    logger.info(f"岗位预测启动: company={company}, position={position}, date={date}, count={qc}")

    # 1. 搜索 JD（异步 → 同步包装）
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        jd = loop.run_until_complete(_fetch_jd(company, position))
        loop.close()
    except Exception as e:
        logger.warning(f"JD 搜索包装失败: {e}")
        jd = {"jd_snippets": [], "source_urls": [], "raw_results": []}

    jd_context = _format_jd_context(jd)

    # 2. 读取简历与项目上下文
    resume_text = _load_resume_summary()
    projects_text = _load_projects_context()

    # 3. 拉取现有题库摘要（用于去重提醒）
    existing_brief = _load_existing_questions_brief()

    # 4. 组装 messages
    system_prompt = _load_prepare_prompt()
    user_parts = [
        f"## 公司与岗位\n- 公司：{company}\n- 岗位：{position}\n- 面试日期：{date}\n- 期望题数：约 {qc} 题（允许 ±3）",
        f"## JD 片段（来自网络搜索）\n\n{jd_context}",
        f"## 候选人简历摘要\n\n{resume_text or '（简历未能读取，请基于岗位要求合理出题）'}",
        f"## 候选人项目上下文\n\n{projects_text or '（暂无项目文档）'}",
        f"## 已有题库题目（请避免重复出题）\n\n{existing_brief or '（题库为空或读取失败）'}",
        "请按系统提示中的 Markdown 模板输出完整题库文件内容，**不要包含任何多余说明或代码围栏**。",
    ]
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]

    logger.info("调用 LLM 生成岗位预测题...")
    report_text = chat_completion(
        messages=messages,
        temperature=0.6,
        max_tokens=4096,
    )
    logger.info(f"LLM 生成成功，长度 {len(report_text)} 字符")

    # 5. 写文件
    if output_dir:
        out_dir = Path(output_dir)
    else:
        out_dir = Path(INTERVIEW_REPO_PATH) / PREP_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = _build_output_filename(company, position, date)
    out_path = out_dir / filename

    # 清理 LLM 可能添加的代码围栏
    body = report_text.strip()
    if body.startswith("```"):
        body = re.sub(r"^```[a-zA-Z]*\n", "", body, count=1)
        body = re.sub(r"\n```\s*$", "", body, count=1)
    out_path.write_text(body + "\n", encoding="utf-8")

    # 6. 统计题数（通过 Q{N} 正则）
    q_count = len(re.findall(r"^#{2,4}\s*Q\d+[：:]", body, re.MULTILINE))

    elapsed = (datetime.now() - start_ts).total_seconds()
    logger.info(
        f"岗位预测完成: 文件={out_path}, 题数={q_count}, "
        f"JD 片段={len(jd.get('jd_snippets', []))}, 耗时={elapsed:.1f}s"
    )

    return PrepareResult(
        company=company,
        position=position,
        date=date,
        output_file=str(out_path),
        question_count=q_count,
        jd_source_count=len(jd.get("source_urls", [])),
        jd_snippet_count=len(jd.get("jd_snippets", [])),
        elapsed_sec=elapsed,
    )


def parse_spec(spec: str) -> tuple[str, str, str]:
    """
    解析 CLI 位置参数 spec，格式：'公司_岗位_YYMMDD'
    最后一段若是 6 位数字视为日期，否则使用今天。
    """
    parts = spec.split("_")
    if len(parts) >= 3 and re.fullmatch(r"\d{6}", parts[-1]):
        date = parts[-1]
        company = parts[0]
        position = "_".join(parts[1:-1])
    elif len(parts) == 2:
        company, position = parts[0], parts[1]
        date = _default_date()
    elif len(parts) == 1:
        # 只给了公司名也允许（岗位留空兜底）
        company, position = parts[0], ""
        date = _default_date()
    else:
        date = _default_date()
        company = parts[0]
        position = "_".join(parts[1:])
    return company, position, date
