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
    department: str = ""
    output_file: str = ""
    question_count: int = 0
    jd_source_count: int = 0
    jd_snippet_count: int = 0
    elapsed_sec: float = 0.0
    # Agent 路径附加字段（fallback 走线性流程时为默认值）
    agent_iterations: int = 0
    quality_score: float = 0.0
    used_agent: bool = False


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


def _build_output_filename(company: str, position: str, date: str, department: str = "") -> str:
    """构造输出文件名：{公司}_{部门_}_{岗位}_{日期}.md（无部门时省略）"""
    if department:
        parts = [_sanitize_filename(company), _sanitize_filename(department), _sanitize_filename(position), _sanitize_filename(date)]
    else:
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
    department: str = "",
    output_dir: str | None = None,
    question_count: int | None = None,
) -> PrepareResult:
    """
    生成岗位预测题库文件。

    默认走 ReAct Agent 路径（自主决策搜索/出题/迭代）；
    Agent 异常时若 PREP_AGENT_FALLBACK=true 则回退到线性流程。

    Args:
        company: 公司名（如 "字节跳动"）
        position: 岗位名（如 "AI应用开发实习生-AI数据与安全"）
        department: 部门名（如 "CHO体系-企业信息化部"，可选）
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

    logger.info(
        f"岗位预测启动: company={company}, position={position}, department={department or '无'}, date={date}, count={qc}"
    )

    # 解析输出路径（agent 与 legacy 共用）
    if output_dir:
        out_dir = Path(output_dir)
    else:
        out_dir = Path(INTERVIEW_REPO_PATH) / PREP_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = _build_output_filename(company, position, date, department)
    out_path = out_dir / filename

    # ── Agent 路径 ──
    try:
        from core.prepare_agent import run_prepare_agent
        body, meta = run_prepare_agent(company, position, date, qc, department=department)
        if not body or not body.strip():
            raise RuntimeError("Agent 返回空内容")
    except Exception as e:
        # 容错：根据配置决定是否回退线性流程
        try:
            import config as _cfg
            fallback_enabled = bool(getattr(_cfg, "PREP_AGENT_FALLBACK", True))
        except Exception:
            fallback_enabled = True

        logger.warning(
            f"Agent 路径失败: {e}; fallback={fallback_enabled}"
        )
        if not fallback_enabled:
            raise
        return _legacy_prepare(company, position, date, qc, out_path, start_ts, department=department)

    # ── 写文件 ──
    body = body.strip()
    if body.startswith("```"):
        body = re.sub(r"^```[a-zA-Z]*\n", "", body, count=1)
        body = re.sub(r"\n```\s*$", "", body, count=1)
    out_path.write_text(body + "\n", encoding="utf-8")

    q_count = len(re.findall(r"^#{2,4}\s*Q\d+[：:]", body, re.MULTILINE))
    elapsed = (datetime.now() - start_ts).total_seconds()
    logger.info(
        f"岗位预测完成（agent）: 文件={out_path}, 题数={q_count}, "
        f"迭代={meta.get('iterations_used', 0)}, 自评={meta.get('quality_score', 0):.2f}, "
        f"JD 片段={meta.get('jd_snippet_count', 0)}, 耗时={elapsed:.1f}s"
    )

    return PrepareResult(
        company=company,
        position=position,
        date=date,
        department=department,
        output_file=str(out_path),
        question_count=q_count,
        jd_source_count=int(meta.get("jd_source_count", 0)),
        jd_snippet_count=int(meta.get("jd_snippet_count", 0)),
        elapsed_sec=elapsed,
        agent_iterations=int(meta.get("iterations_used", 0)),
        quality_score=float(meta.get("quality_score", 0.0)),
        used_agent=True,
    )


def _legacy_prepare(
    company: str,
    position: str,
    date: str,
    qc: int,
    out_path: Path,
    start_ts: datetime,
    department: str = "",
) -> PrepareResult:
    """旧版线性流水线：搜JD → 读简历项目 → LLM 一次出题 → 写文件。

    作为 Agent 路径的 fallback；输入参数已由 prepare_interview 预处理。
    """
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
    dept_line = f"\n- 部门：{department}" if department else ""
    user_parts = [
        f"## 公司与岗位\n- 公司：{company}{dept_line}\n- 岗位：{position}\n- 面试日期：{date}\n- 期望题数：约 {qc} 题（允许 ±3）",
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

    logger.info("调用 LLM 生成岗位预测题（legacy 线性路径）...")
    report_text = chat_completion(
        messages=messages,
        temperature=0.6,
        max_tokens=4096,
    )
    logger.info(f"LLM 生成成功，长度 {len(report_text)} 字符")

    # 5. 写文件
    body = report_text.strip()
    if body.startswith("```"):
        body = re.sub(r"^```[a-zA-Z]*\n", "", body, count=1)
        body = re.sub(r"\n```\s*$", "", body, count=1)
    out_path.write_text(body + "\n", encoding="utf-8")

    # 6. 统计题数
    q_count = len(re.findall(r"^#{2,4}\s*Q\d+[：:]", body, re.MULTILINE))

    elapsed = (datetime.now() - start_ts).total_seconds()
    logger.info(
        f"岗位预测完成（legacy）: 文件={out_path}, 题数={q_count}, "
        f"JD 片段={len(jd.get('jd_snippets', []))}, 耗时={elapsed:.1f}s"
    )

    return PrepareResult(
        company=company,
        position=position,
        date=date,
        department=department,
        output_file=str(out_path),
        question_count=q_count,
        jd_source_count=len(jd.get("source_urls", [])),
        jd_snippet_count=len(jd.get("jd_snippets", [])),
        elapsed_sec=elapsed,
        agent_iterations=0,
        quality_score=0.0,
        used_agent=False,
    )


def parse_spec(spec: str) -> tuple[str, str, str, str]:
    """
    解析 CLI 位置参数 spec。

    格式：'公司_[部门_...]岗位_[YYMMDD]'
    - 最后一段若是 6 位纯数字 → 日期，否则日期用今天
    - 倒数第二段（或 core 最后一段）→ 岗位
    - 公司与岗位之间的所有段 → 部门（可为空）
    - 如果只有公司名，岗位和部门均留空

    返回 (company, position, date, department)

    示例:
        '京东_后端开发工程师' → ('京东', '后端开发工程师', '260517', '')
        '京东_后端开发工程师_260512' → ('京东', '后端开发工程师', '260512', '')
        '京东_CHO体系-企业信息化部_后端开发工程师' → ('京东', '后端开发工程师', '260517', 'CHO体系-企业信息化部')
        '京东_CHO体系-企业信息化部_后端开发工程师_260512' → ('京东', '后端开发工程师', '260512', 'CHO体系-企业信息化部')
    """
    parts = spec.split("_")
    if not parts or all(p == "" for p in parts):
        return "", "", _default_date(), ""

    # 最后一段若是 6 位数字 → 日期
    if re.fullmatch(r"\d{6}", parts[-1]):
        date = parts[-1]
        core_parts = parts[:-1]
    else:
        date = _default_date()
        core_parts = parts

    if not core_parts:
        return "", "", date, ""

    company = core_parts[0]

    if len(core_parts) == 1:
        # 只有公司名
        return company, "", date, ""

    # position = 最后一段; department = 公司与岗位之间的所有段
    position = core_parts[-1]
    department = "_".join(core_parts[1:-1]) if len(core_parts) > 2 else ""

    return company, position, date, department
