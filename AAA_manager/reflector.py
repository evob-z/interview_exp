"""
reflector.py - 面试反思模块 (PydanticAI 重构版)

通过多轮终端对话收集用户对面试的实际回答表现。使用 PydanticAI 双 Agent 架构：
- Conversation Agent: 多轮提问，动态评估 5 维度覆盖度，可查阅项目文档
- Summary Agent: 汇总对话内容，生成结构化反思报告

流水线：extract → reflect(交互) → review(增强) → archive

用法:
    python main.py reflect <面经文件>
    python main.py sync --reflect
"""

from __future__ import annotations

import asyncio
import datetime
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

import config
from logger import get_logger

logger = get_logger("reflector")

# ──────────────────────────────────────────────
# PydanticAI imports
# ──────────────────────────────────────────────
from pydantic_ai import Agent, RunContext, UnexpectedModelBehavior
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits
from pydantic import BaseModel, Field


# ═══════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════

@dataclass
class ReflectionResult:
    """反思结果"""
    company: str = ""
    company_type: str = ""
    date: str = ""
    round: str = ""
    questions: list[dict] = field(default_factory=list)
    transcript: list[dict] = field(default_factory=list)   # QA 对
    summary: dict = field(default_factory=dict)             # ReflectionSummary.model_dump()
    review_content: str = ""                                 # 复盘文本
    enhanced_review_context: str = ""                        # 传给 reviewer 的增强上下文
    profile_updated: bool = False


class CoverageScores(BaseModel):
    """5 维度覆盖度评分 (0-100)"""
    overall_feeling: int = Field(ge=0, le=100, description="整体感受、节奏、时长")
    strengths: int = Field(ge=0, le=100, description="答得好的题目与原因")
    weaknesses: int = Field(ge=0, le=100, description="答不上来的题目与卡壳点")
    interviewer_focus: int = Field(ge=0, le=100, description="面试官追问方向、表情反馈")
    improvement_areas: int = Field(ge=0, le=100, description="下次改进重点")

    def all_covered(self, threshold: int = 70) -> bool:
        return all(
            getattr(self, f) >= threshold
            for f in ["overall_feeling", "strengths", "weaknesses", "interviewer_focus", "improvement_areas"]
        )


class ReflectionTurn(BaseModel):
    """Conversation Agent 单轮输出"""
    next_question: str = Field(default="", description="下一轮提问；should_stop=true 时可为空")
    reasoning: str = Field(default="", description="为什么问这个/为什么停止")
    coverage: CoverageScores
    should_stop: bool = Field(default=False)


class ReflectionSummary(BaseModel):
    """Summary Agent 最终输出"""
    performance_summary: str
    well_answered: list[str] = Field(default_factory=list)
    poorly_answered: list[str] = Field(default_factory=list)
    interviewer_focus: list[str] = Field(default_factory=list)
    improvement_suggestions: list[str] = Field(default_factory=list)
    review_content: str = Field(min_length=100)


@dataclass
class Notepad:
    """Agent 草稿纸 - 跨轮持久的侧边记忆，不进入主线 message_history。

    用途：
    - 工具调用结果存这里，主线只回简短确认 → 防上下文爆炸
    - LLM 主动写笔记（notepad_write/append），跨轮共享思考
    - 每轮通过 dynamic system_prompt 注入到 LLM

    淘汰策略：超过 max_total_chars 时按 LRU 淘汰最旧 section
    """
    sections: dict[str, str] = field(default_factory=dict)
    _access_order: list[str] = field(default_factory=list)
    max_total_chars: int = 16000
    max_section_chars: int = 2400
    dump_path: Path | None = None

    def _normalize_section_content(self, content: str) -> str:
        """单个 section 内容过长时做本地压缩，减少 prompt 注入体积。"""
        normalized = content.strip()
        if len(normalized) <= self.max_section_chars:
            return normalized

        # 头部通常包含定义/结论，尾部包含最新信息，二者都保留。
        head_keep = int(self.max_section_chars * 0.7)
        tail_keep = self.max_section_chars - head_keep
        head = normalized[:head_keep]
        tail = normalized[-tail_keep:] if tail_keep > 0 else ""
        return (
            f"{head}\n\n"
            f"...(中间省略 {len(normalized) - self.max_section_chars} 字，已自动压缩)...\n\n"
            f"{tail}"
        )

    def write(self, section: str, content: str) -> None:
        """覆盖写入"""
        self.sections[section] = self._normalize_section_content(content)
        self._touch(section)
        self._enforce_size()

    def append(self, section: str, content: str) -> None:
        """追加写入"""
        prev = self.sections.get(section, "")
        sep = "\n" if prev else ""
        merged = (prev + sep + content.strip()).strip()
        self.sections[section] = self._normalize_section_content(merged)
        self._touch(section)
        self._enforce_size()

    def _touch(self, section: str) -> None:
        if section in self._access_order:
            self._access_order.remove(section)
        self._access_order.append(section)

    def _enforce_size(self) -> None:
        total = sum(len(v) for v in self.sections.values())
        while total > self.max_total_chars and len(self._access_order) > 1:
            oldest = self._access_order.pop(0)
            old_content = self.sections.pop(oldest, "")
            total -= len(old_content)

    def render(self) -> str:
        if not self.sections:
            return ""
        parts = []
        for section, content in self.sections.items():
            parts.append(f"### {section}")
            parts.append(content)
            parts.append("")
        return "\n".join(parts).strip()

    def snapshot(self, round_idx: int, label: str = "") -> None:
        """将当前草稿纸状态追加写入日志文件（用于 debug）。"""
        if self.dump_path is None:
            return

        ts = datetime.datetime.now().strftime("%H:%M:%S")
        title = f"## Round {round_idx} [{ts}]"
        if label:
            title += f" - {label}"
        body = self.render() or "(空)"
        try:
            with self.dump_path.open("a", encoding="utf-8") as f:
                f.write(f"\n\n{title}\n\n{body}\n")
        except Exception as e:
            logger.warning(f"Notepad 落盘失败: {e}")


@dataclass
class ReflectDeps:
    """反思 Agent 依赖（共享单例）"""
    project_reader: Any = None  # ProjectReader 实例
    notepad: Notepad | None = None  # 草稿纸（跨轮持久）


# ═══════════════════════════════════════════════
# 工具函数（保留）
# ═══════════════════════════════════════════════

def _load_prompt(filename: str) -> str:
    """加载 prompts 目录下的模板文件"""
    prompts_dir = Path(__file__).parent / "prompts"
    filepath = prompts_dir / filename
    if not filepath.exists():
        raise FileNotFoundError(f"提示词模板不存在: {filepath}")
    return filepath.read_text(encoding="utf-8")


def _parse_interview_meta(file_path: str) -> dict:
    """从文件名解析面试元信息（保留原有逻辑）"""
    stem = Path(file_path).stem
    parts = stem.split("_")
    meta = {
        "company": parts[0] if len(parts) > 0 else "",
        "company_type": parts[1] if len(parts) > 1 else "",
        "date": "",
        "round": "",
    }
    date_match = re.search(r"(\d{6})", stem)
    if date_match:
        meta["date"] = date_match.group(1)
    if date_match and len(parts) > 3:
        meta["round"] = parts[-1] if not parts[-1].isdigit() else ""
    elif len(parts) > 2:
        for p in parts[2:]:
            if not p.isdigit() and len(p) < 8:
                meta["round"] = p
                break
    return meta


def _parse_questions_from_file(file_path: str) -> list[dict]:
    """从面经文件解析问题列表，提取 [项目名] 标签作为 category_suggestion"""
    content = Path(file_path).read_text(encoding="utf-8")
    questions = []
    tag_pattern = re.compile(r"^\[([^\]]+)\]\s*")

    def _extract_tag(text: str) -> tuple[str | None, str]:
        """从问题文本提取 [标签] → category_suggestion，去除标签后的纯净文本"""
        m = tag_pattern.match(text)
        if m:
            tag = m.group(1)
            clean = text[m.end():].strip()
            # 多项目标签取第一个
            pn = tag.split("/")[0].strip()
            return f"项目-{pn}", clean
        return None, text

    q_pattern = re.compile(r"^#{2,4}\s*Q(\d+)[：:]\s*(.+)", re.MULTILINE)
    matches = q_pattern.findall(content)
    if matches:
        for q_id, q_text in matches:
            cat, clean_text = _extract_tag(q_text.strip())
            entry = {"id": int(q_id), "text": clean_text}
            if cat:
                entry["category_suggestion"] = cat
            questions.append(entry)
        return questions

    num_pattern = re.compile(r"^\s*(\d+)[\.\、\)]\s*(.+)", re.MULTILINE)
    matches = num_pattern.findall(content)
    if matches:
        for q_id, q_text in matches:
            text = q_text.strip()
            if len(text) > 5:
                cat, clean_text = _extract_tag(text)
                entry = {"id": int(q_id), "text": clean_text}
                if cat:
                    entry["category_suggestion"] = cat
                questions.append(entry)

    return questions


# ═══════════════════════════════════════════════
# 上下文构建
# ═══════════════════════════════════════════════

def _load_user_profile_brief() -> str:
    """加载用户画像摘要（截断 ~500 字）"""
    profile_path = Path(__file__).parent / "data" / "user_profile.json"
    if not profile_path.exists():
        logger.info("用户画像文件不存在，跳过")
        return ""

    try:
        import json
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        parts = []

        basic = data.get("basic_info", {})
        if basic:
            name = basic.get("name", "")
            edu = basic.get("education", "")
            role = basic.get("target_role", "")
            skills = basic.get("skills", [])
            if name:
                parts.append(f"姓名: {name}")
            if edu:
                parts.append(f"学历: {edu}")
            if role:
                parts.append(f"目标岗位: {role}")
            if skills:
                parts.append(f"技能栈: {', '.join(skills[:10])}")

        strengths = data.get("strengths", [])
        if strengths:
            parts.append(f"优势: {'; '.join(strengths[:5])}")

        weaknesses = data.get("weaknesses", [])
        if weaknesses:
            parts.append(f"短板: {'; '.join(weaknesses[:5])}")

        skill_map = data.get("skill_map", [])
        if skill_map:
            top_skills = [f"{s.get('name','')}({s.get('level','')})" for s in skill_map[:5]]
            parts.append(f"技能等级: {', '.join(top_skills)}")

        result = " | ".join(parts)
        if len(result) > 500:
            result = result[:497] + "..."
        return result
    except Exception as e:
        logger.warning(f"加载用户画像失败: {e}")
        return ""


def _load_prediction_context(company: str) -> str | None:
    """加载岗位预测对比（若有）"""
    prediction_dir = config.INTERVIEW_REPO_PATH / config.PREP_OUTPUT_DIR
    if not prediction_dir.exists():
        return None

    company_clean = company.replace(" ", "").replace("（", "(").replace("）", ")")
    for f in prediction_dir.iterdir():
        if f.is_file() and f.suffix == ".md" and company_clean in f.stem:
            try:
                content = f.read_text(encoding="utf-8")
                # 截取前 1000 字 + 预测题目部分
                if len(content) > 2000:
                    content = content[:2000] + "\n...(已截断)..."
                return content
            except Exception as e:
                logger.warning(f"加载岗位预测失败 {f}: {e}")
                return None
    return None


def _get_project_name_from_category(category: str) -> str | None:
    """从 category 字符串提取项目名，如 '项目-Agent_SFT_SHENWEI' → 'Agent_SFT_SHENWEI'"""
    if not category:
        return None
    if category.startswith("项目-"):
        return category[3:]
    return None


def _init_project_reader(
    questions: list[dict],
) -> tuple[Any, dict[str, dict]]:
    """初始化 ProjectReader，扫描涉及的项目并建立索引

    仅 discover + load_startup (Tier1/2 索引)，不预加载文档内容。
    返回 (reader, {project_name: tier_summary})。
    """
    from knowledge.project_reader import ProjectReader

    # 收集所有涉及的项目名
    project_names: set[str] = set()
    for q in questions:
        cat = q.get("category_suggestion", "")
        pn = _get_project_name_from_category(cat)
        if pn:
            project_names.add(pn)

    if not project_names:
        logger.info("未发现涉及项目的题目，跳过项目文档初始化")
        return None, {}

    logger.info(f"涉及项目: {project_names}")

    # 构造 ProjectReader
    projects_for_reader = []
    for pn in project_names:
        # 从 projects.yaml 查找路径
        found = False
        for p in config.PROJECTS_META.get("projects", []):
            if p.get("name") == pn:
                path = p.get("path", "")
                if not path or not Path(path).exists():
                    logger.warning(f"项目 {pn} 路径未配置或不存在，跳过: {path!r}")
                else:
                    projects_for_reader.append({"name": pn, "path": path})
                found = True
                break
        if not found:
            logger.warning(f"项目 {pn} 未在 projects.yaml 中配置，跳过")

    if not projects_for_reader:
        return None, {}

    try:
        reader = ProjectReader(projects=projects_for_reader)
        for proj in projects_for_reader:
            reader.discover(proj["name"])
            reader.load_startup()
        logger.info("ProjectReader 初始化完成")

        summaries = {}
        for proj in projects_for_reader:
            name = proj["name"]
            try:
                summaries[name] = reader.get_tier_summary(name)
            except Exception as e:
                logger.warning(f"获取项目 {name} 摘要失败: {e}")
                summaries[name] = {"error": str(e)}

        return reader, summaries
    except Exception as e:
        logger.warning(f"初始化 ProjectReader 失败: {e}")
        return None, {}


def _build_initial_context(
    questions: list[dict],
    meta: dict,
    profile_brief: str,
    prediction: str | None,
    project_summaries: dict[str, dict],
) -> str:
    """构建首轮 user message（仅保留核心信息，长上下文交给 notepad）。"""
    parts = []

    # 1. 面试基本信息 + 问题列表
    parts.append(f"## 面试基本信息")
    parts.append(f"- 公司: {meta.get('company', '未知')}")
    parts.append(f"- 类型: {meta.get('company_type', '')}")
    parts.append(f"- 轮次: {meta.get('round', '')}")
    parts.append(f"- 日期: {meta.get('date', '')}")
    parts.append("")

    parts.append(f"## 面试问题列表（共 {len(questions)} 题）")
    parts.append("")
    for q in questions:
        parts.append(f"Q{q.get('id', '?')}: {q.get('text', '')}")
    parts.append("")

    # 长文本（画像/岗位预测/项目索引）已转入 notepad，避免主线上下文膨胀。

    # 2. 首轮指引
    parts.append("---")
    parts.append("## 提问指引")
    parts.append("1. 你可以结合题目清单、notepad、候选人回答，做混合提问（开放感受 + 具体题目）。")
    parts.append("2. 每次只问一个问题。")
    parts.append("3. 工具可在任意轮按需调用，但每轮建议 <= 3 次，避免过度调研。")
    parts.append("4. 调完工具后，优先写入 notepad，再继续提问。")
    parts.append("5. 首轮还没有候选人回答时，coverage 应保持低值，`should_stop` 设为 false。")

    return "\n".join(parts)


def _format_project_summary_for_notepad(summary: dict) -> str:
    """把项目摘要格式化为 notepad 文本。"""
    if "error" in summary:
        return f"(不可用: {summary['error']})"

    lines: list[str] = []
    for tier_key in sorted(summary.keys()):
        tier_info = summary[tier_key]
        locked = "🔒" if tier_info.get("locked") else ""
        status = "已加载" if tier_info.get("loaded") else "未加载"
        files = tier_info.get("files", [])
        file_count = tier_info.get("file_count", len(files))
        lines.append(f"- {tier_info['name']}: {file_count} 个文件 [{status}] {locked}")
        if files and not tier_info.get("locked"):
            for f in files[:8]:
                lines.append(f"  - {f}")
    return "\n".join(lines)


def _seed_notepad(
    notepad: Notepad,
    profile_brief: str,
    prediction: str | None,
    project_summaries: dict[str, dict],
) -> None:
    """预置长上下文到 notepad，减少主线 prompt 压力。"""
    if profile_brief:
        notepad.write("候选人画像", profile_brief)
    if prediction:
        notepad.write("岗位预测对比", prediction)
    for proj_name, summary in project_summaries.items():
        notepad.write(f"项目索引-{proj_name}", _format_project_summary_for_notepad(summary))


def _build_notepad_log_path(meta: dict) -> Path:
    """构建 notepad 演变日志路径。"""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    company = meta.get("company", "unknown").replace("/", "-")
    date_str = meta.get("date", "")
    stem = f"notepad_{ts}_{company}_{date_str}" if date_str else f"notepad_{ts}_{company}"
    log_path = config.LOG_DIR / f"{stem}.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    header = f"# Notepad 演变日志（{company} {date_str}）\n"
    log_path.write_text(header, encoding="utf-8")
    return log_path


# ═══════════════════════════════════════════════
# PydanticAI Tools（渐进式披露）
# ═══════════════════════════════════════════════

MAX_TOOL_OUTPUT_CHARS = 1500


async def lookup_project_doc(
    ctx: RunContext[ReflectDeps],
    project_name: str,
    file_path: str,
) -> str:
    """按文件路径读取项目文档内容。

    Args:
        project_name: 项目名（如 Agent_SFT_SHENWEI）
        file_path: 文档路径（从 list_project_tier 获取，如 README.md 或 docs/design.md）

    Returns:
        简要确认信息（正文写入 notepad，防主线上下文膨胀）
    """
    reader = ctx.deps.project_reader
    if reader is None:
        return "[文档不可用: ProjectReader 未初始化]"

    logger.debug(f"[tool] lookup_project_doc: {project_name} / {file_path}")
    try:
        # 确保项目已加载
        if project_name not in reader._tiers:
            return f"[项目未发现: {project_name}]"

        # 在所有已加载 tier 中查找文件
        for tier_num in [1, 2, 3]:
            doc_tier = reader._tiers[project_name].get(tier_num)
            if doc_tier is None:
                continue
            # 确保 tier 已加载
            if not doc_tier.loaded:
                reader.load_tier(project_name, tier_num)

            for file_info in doc_tier.files:
                if file_info.get("path", "") == file_path:
                    content = file_info.get("content", "")
                    if content:
                        snippet = (
                            content[:MAX_TOOL_OUTPUT_CHARS] + "\n...(已截断)..."
                            if len(content) > MAX_TOOL_OUTPUT_CHARS
                            else content
                        )
                        if ctx.deps.notepad is not None:
                            section = f"项目文档:{project_name}/{file_path}"
                            ctx.deps.notepad.write(section, snippet)
                            return (
                                f"[已读取 {project_name}/{file_path}（{len(content)} 字），"
                                f"内容已写入 notepad: {section}]"
                            )
                        return snippet
                    return f"[文件 {file_path} 内容为空]"

        return f"[未找到文件 {file_path}，请先用 list_project_tier 查看可用文件]"
    except Exception as e:
        return f"[文档不可用: {e}]"


async def search_project_doc(
    ctx: RunContext[ReflectDeps],
    project_name: str,
    query: str,
) -> str:
    """在项目文档中搜索关键词。

    Args:
        project_name: 项目名
        query: 搜索关键词

    Returns:
        简要确认信息（搜索摘要写入 notepad）
    """
    reader = ctx.deps.project_reader
    if reader is None:
        return "[搜索不可用: ProjectReader 未初始化]"

    logger.debug(f"[tool] search_project_doc: {project_name} / '{query}'")
    try:
        results = reader.search_in_projects(query, max_tier=3)
        # 过滤出目标项目
        filtered = [r for r in results if r.get("project_name") == project_name]

        if not filtered:
            return f"[在 {project_name} 中未找到与 '{query}' 相关的内容]"

        lines = [f"搜索 '{query}' 在 {project_name} 中的结果:"]
        for r in filtered[:5]:
            lines.append(
                f"  [{r.get('tier')}层] {r.get('file', '?')}: "
                f"{r.get('context', '')[:200]}"
            )

        result = "\n".join(lines)
        if len(result) > MAX_TOOL_OUTPUT_CHARS:
            result = result[:MAX_TOOL_OUTPUT_CHARS] + "\n...(已截断)..."

        if ctx.deps.notepad is not None:
            section = f"项目搜索:{project_name}/{query}"
            ctx.deps.notepad.write(section, result)
            return f"[已完成搜索 '{query}'，摘要已写入 notepad: {section}]"
        return result
    except Exception as e:
        return f"[搜索失败: {e}]"


async def list_project_tier(
    ctx: RunContext[ReflectDeps],
    project_name: str,
    tier: int,
) -> str:
    """列出项目某层级的所有文档文件（不含内容）。

    Args:
        project_name: 项目名
        tier: 层级号 (1=AI工具总结, 2=设计文档, 3=零散文档)

    Returns:
        文件路径清单
    """
    reader = ctx.deps.project_reader
    if reader is None:
        return "[列举不可用: ProjectReader 未初始化]"
    
    logger.debug(f"[tool] list_project_tier: {project_name} tier={tier}")
    try:
        if project_name not in reader._tiers:
            return f"[项目未发现: {project_name}]"

        doc_tier = reader._tiers[project_name].get(tier)
        if doc_tier is None:
            return f"[Tier {tier} 不可用]"

        if not doc_tier.files:
            return f"[Tier {tier}（{doc_tier.name}）: 无文件]"

        lines = [f"Tier {tier}（{doc_tier.name}）文件清单:"]
        for i, file_info in enumerate(doc_tier.files, 1):
            lines.append(f"  {i}. {file_info.get('path', '?')}")

        return "\n".join(lines)
    except Exception as e:
        return f"[列举失败: {e}]"


async def notepad_write(
    ctx: RunContext[ReflectDeps],
    section: str,
    content: str,
) -> str:
    """覆盖写入 notepad 的某个 section。"""
    if ctx.deps.notepad is None:
        return "[notepad 不可用]"
    ctx.deps.notepad.write(section, content)
    return f"[已写入 notepad: {section}]"


async def notepad_append(
    ctx: RunContext[ReflectDeps],
    section: str,
    content: str,
) -> str:
    """追加写入 notepad 的某个 section。"""
    if ctx.deps.notepad is None:
        return "[notepad 不可用]"
    ctx.deps.notepad.append(section, content)
    return f"[已追加 notepad: {section}]"


# ═══════════════════════════════════════════════
# Agent 构建
# ═══════════════════════════════════════════════

def _build_agent_model():
    """构建 PydanticAI 模型（复用 DeepSeek/Qwen 配置）"""
    api_key, base_url, model_name = config.get_active_provider()
    return OpenAIChatModel(
        model_name,
        provider=OpenAIProvider(
            base_url=base_url,
            api_key=api_key,
        ),
    )


def _build_conv_agent() -> Agent[ReflectDeps, ReflectionTurn]:
    """构建 Conversation Agent"""
    system_prompt = _load_prompt("reflect_agent_system.md")
    model = _build_agent_model()
    agent = Agent(
        model,
        output_type=ReflectionTurn,
        deps_type=ReflectDeps,
        system_prompt=system_prompt,
        tools=[
            lookup_project_doc,
            search_project_doc,
            list_project_tier,
            notepad_write,
            notepad_append,
        ],
        retries=2,
    )

    @agent.system_prompt(dynamic=True)
    async def _inject_notepad(ctx: RunContext[ReflectDeps]) -> str:
        if ctx.deps is None or ctx.deps.notepad is None:
            return ""
        rendered = ctx.deps.notepad.render()
        if not rendered:
            return (
                "## 你的草稿纸（自动注入）\n"
                "当前为空。需要时请使用 notepad_write / notepad_append 记录关键事实。"
            )
        return f"## 你的草稿纸（自动注入）\n\n{rendered}"

    return agent


def _build_summary_agent() -> Agent[None, ReflectionSummary]:
    """构建 Summary Agent"""
    system_prompt = _load_prompt("reflect_summary_system.md")
    model = _build_agent_model()
    return Agent(
        model,
        output_type=ReflectionSummary,
        system_prompt=system_prompt,
        retries=2,
    )


# ═══════════════════════════════════════════════
# 格式化
# ═══════════════════════════════════════════════

def _format_transcript(
    transcript: list[dict],
    meta: dict,
    questions: list[dict],
) -> str:
    """格式化对话记录为 Summary Agent 输入"""
    parts = []
    parts.append(f"## 面试信息")
    parts.append(f"- 公司: {meta.get('company', '未知')}")
    parts.append(f"- 轮次: {meta.get('round', '')}")
    parts.append(f"- 日期: {meta.get('date', '')}")
    parts.append("")

    parts.append(f"## 面试问题（共 {len(questions)} 题）")
    for q in questions:
        parts.append(f"Q{q.get('id', '?')}: {q.get('text', '')}")
    parts.append("")

    parts.append("## 反思对话记录")
    for i, pair in enumerate(transcript, 1):
        parts.append(f"### 第{i}轮")
        parts.append(f"AI 提问: {pair.get('q', '')}")
        parts.append(f"候选人回答: {pair.get('a', '')}")
        parts.append("")

    return "\n".join(parts)


def _format_for_reviewer(summary: ReflectionSummary) -> str:
    """将 ReflectionSummary 格式化为 reviewer 可用的上下文"""
    parts = ["## 求职者实际回答表现（来自反思）", ""]
    parts.append(f"**整体表现**: {summary.performance_summary}")
    parts.append("")

    if summary.well_answered:
        parts.append("**答得好的题/话题**:")
        for item in summary.well_answered:
            parts.append(f"  - {item}")
        parts.append("")

    if summary.poorly_answered:
        parts.append("**答得不好的题/话题**:")
        for item in summary.poorly_answered:
            parts.append(f"  - {item}")
        parts.append("")

    if summary.interviewer_focus:
        parts.append("**面试官关注方向**:")
        for item in summary.interviewer_focus:
            parts.append(f"  - {item}")
        parts.append("")

    if summary.improvement_suggestions:
        parts.append("**改进建议**:")
        for item in summary.improvement_suggestions:
            parts.append(f"  - {item}")
        parts.append("")

    return "\n".join(parts)


# ═══════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════

def _save_reflect_log(
    meta: dict,
    questions: list[dict],
    transcript: list[dict],
    summary: ReflectionSummary | None = None,
) -> Path | None:
    """将反思对话内容持久化到 logs/reflect_YYYYMMDD_HHMMSS_{company}.md"""
    try:
        log_dir = config.LOG_DIR
        log_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        company = meta.get("company", "unknown").replace("/", "-")
        date_str = meta.get("date", "")
        stem = f"reflect_{ts}_{company}_{date_str}" if date_str else f"reflect_{ts}_{company}"
        log_path = log_dir / f"{stem}.md"

        lines: list[str] = []
        lines.append("# 面试反思记录")
        lines.append("")
        lines.append(f"- **公司**: {meta.get('company', '')} ({meta.get('company_type', '')}")
        lines.append(f"- **日期**: {meta.get('date', '')} {meta.get('round', '')}")
        lines.append(f"- **生成时间**: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"- **题目数**: {len(questions)} 题")
        lines.append("")

        lines.append("## 反思对话")
        lines.append("")
        if transcript:
            for i, pair in enumerate(transcript, 1):
                lines.append(f"### 第 {i} 轮")
                lines.append("")
                lines.append(f"**AI**: {pair['q']}")
                lines.append("")
                lines.append(f"**我**: {pair['a']}")
                lines.append("")
        else:
            lines.append("_无对话记录_")
            lines.append("")

        if summary:
            lines.append("## AI 汇总分析")
            lines.append("")
            lines.append(f"**整体评价**: {summary.performance_summary}")
            lines.append("")
            if summary.well_answered:
                lines.append("**表现亮点**:")
                for item in summary.well_answered:
                    lines.append(f"- {item}")
                lines.append("")
            if summary.poorly_answered:
                lines.append("**暴露短板**:")
                for item in summary.poorly_answered:
                    lines.append(f"- {item}")
                lines.append("")
            if summary.interviewer_focus:
                lines.append("**面试官关注**:")
                for item in summary.interviewer_focus:
                    lines.append(f"- {item}")
                lines.append("")
            if summary.improvement_suggestions:
                lines.append("**改进建议**:")
                for item in summary.improvement_suggestions:
                    lines.append(f"- {item}")
                lines.append("")

        log_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"反思日志已保存: {log_path.name}")
        return log_path
    except Exception as e:
        logger.warning(f"反思日志写入失败: {e}")
        return None


async def reflect_interview_async(
    file_path: str,
    *,
    max_rounds: int | None = None,
    threshold: int | None = None,
) -> ReflectionResult:
    """异步反思主流程"""
    _max_rounds = max_rounds if max_rounds is not None else config.REFLECT_MAX_ROUNDS
    _threshold = threshold if threshold is not None else config.REFLECT_COVERAGE_THRESHOLD

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    result = ReflectionResult()

    # 1. 解析元信息
    meta = _parse_interview_meta(file_path)
    result.company = meta["company"]
    result.company_type = meta["company_type"]
    result.date = meta["date"]
    result.round = meta["round"]

    # 2. 解析问题列表
    questions = _parse_questions_from_file(file_path)
    if not questions:
        raise ValueError(f"未能从文件中解析出问题: {path.name}")
    result.questions = questions

    print(f"\n  已加载 {len(questions)} 个面试问题")

    # 3. 构建上下文
    print("  正在准备反思上下文...")
    profile_brief = _load_user_profile_brief()
    prediction = _load_prediction_context(meta["company"])
    reader, project_summaries = _init_project_reader(questions)
    notepad = Notepad(
        max_total_chars=config.NOTEPAD_MAX_CHARS,
        max_section_chars=config.NOTEPAD_MAX_SECTION_CHARS,
        dump_path=_build_notepad_log_path(meta),
    )
    _seed_notepad(notepad, profile_brief, prediction, project_summaries)
    notepad.snapshot(0, label="初始种子")
    deps = ReflectDeps(project_reader=reader, notepad=notepad)

    initial_ctx = _build_initial_context(
        questions, meta, profile_brief, prediction, project_summaries
    )

    # 4. 多轮对话
    conv_agent = _build_conv_agent()
    transcript: list[dict] = []

    print("\n" + "─" * 50)
    print("  AI 面试教练想了解你的实际表现")
    print("  （直接输入回答，/stop 可随时停止）")
    print("─" * 50 + "\n")

    try:
        agent_result = await conv_agent.run(
            initial_ctx,
            deps=deps,
            usage_limits=UsageLimits(request_limit=50),
        )
        notepad.snapshot(1, label="首轮提问生成后")
    except UnexpectedModelBehavior as e:
        logger.error(f"Conversation Agent 启动失败: {e}")
        return result
    except Exception as e:
        logger.error(f"Conversation Agent 启动失败: {e}")
        return result

    rounds = 0

    while True:
        turn = agent_result.output

        rounds += 1

        # 检查停止条件
        if turn.should_stop or turn.coverage.all_covered(_threshold) or rounds > _max_rounds:
            if turn.should_stop:
                print(f"\n  [AI 认为信息已足够: {turn.reasoning}]")
            elif turn.coverage.all_covered(_threshold):
                print(f"\n  [覆盖度达标，停止提问]")
            else:
                print(f"\n  [已达最大轮数 {_max_rounds}]")
            break

        # 显示覆盖度进度
        cov = turn.coverage
        print(
            f"\n  [第{rounds}轮 | "
            f"整体{cov.overall_feeling} 优势{cov.strengths} "
            f"短板{cov.weaknesses} 关注{cov.interviewer_focus} "
            f"改进{cov.improvement_areas}]"
        )
        print(f"  AI: {turn.next_question}")

        # 收集用户输入
        try:
            user_input = input("\n  你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  [中断]")
            break

        if user_input.lower() == "/stop":
            print("  [手动停止]")
            break

        if not user_input:
            continue

        transcript.append({"q": turn.next_question, "a": user_input})

        try:
            agent_result = await conv_agent.run(
                user_input,
                message_history=agent_result.all_messages(),
                deps=deps,
                usage_limits=UsageLimits(request_limit=50),
            )
            notepad.snapshot(rounds + 1, label=f"第{rounds}轮用户回答后")
        except UnexpectedModelBehavior as e:
            logger.warning(f"Conversation Agent 中途失败: {e}")
            break
        except Exception as e:
            logger.error(f"Conversation Agent 意外错误: {e}")
            break

    result.transcript = transcript

    # 对话持久化（无汇总版）
    _save_reflect_log(meta, questions, transcript)

    if not transcript:
        print("\n  [未收集到任何回答，跳过汇总]")
        return result

    # 5. Summary Agent 汇总
    print("\n  正在生成反思汇总...")
    summary_agent = _build_summary_agent()
    transcript_text = _format_transcript(transcript, meta, questions)

    try:
        summary_result = await summary_agent.run(transcript_text)
        summary_output = summary_result.output
    except UnexpectedModelBehavior as e:
        logger.error(f"Summary Agent 失败: {e}")
        # 降级：拼接纯文本
        fallback_content = "\n".join(
            [f"Q: {p['q']}\nA: {p['a']}" for p in transcript]
        )
        result.review_content = fallback_content
        result.enhanced_review_context = f"## 反思记录（汇总失败）\n\n{fallback_content}"
        return result
    except Exception as e:
        logger.error(f"Summary Agent 意外错误: {e}")
        fallback_content = "\n".join(
            [f"Q: {p['q']}\nA: {p['a']}" for p in transcript]
        )
        result.review_content = fallback_content
        result.enhanced_review_context = f"## 反思记录（汇总失败）\n\n{fallback_content}"
        return result

    result.summary = summary_output.model_dump()
    result.review_content = summary_output.review_content
    result.enhanced_review_context = _format_for_reviewer(summary_output)

    # 持久化（含汇总分析）
    _save_reflect_log(meta, questions, transcript, summary_output)

    logger.info("反思汇总完成")
    return result


def reflect_interview(file_path: str, llm_client=None) -> ReflectionResult:
    """同步反思主入口（保持原有签名兼容）

    Args:
        file_path: 面经文件路径
        llm_client: 保留参数（不再使用，PydanticAI 内部管理 LLM 调用）

    Returns:
        ReflectionResult 反思结果
    """
    # llm_client 参数保留但不使用（向后兼容）
    return asyncio.run(reflect_interview_async(file_path))


def print_reflection_report(result: ReflectionResult):
    """在终端打印反思分析报告"""
    print("\n" + "═" * 50)
    print("  面试反思分析报告")
    print("═" * 50)

    summary = result.summary
    if not summary:
        # 降级：打印 transcript
        if result.transcript:
            print("\n  反思对话记录:")
            for pair in result.transcript:
                print(f"\n  Q: {pair['q']}")
                print(f"  A: {pair['a']}")
        else:
            print("\n  （无分析结果）")
        return

    perf = summary.get("performance_summary", "")
    if perf:
        print(f"\n  📋 整体评价: {perf}")

    well = summary.get("well_answered", [])
    if well:
        print("\n  ✅ 表现亮点:")
        for item in well:
            print(f"     • {item}")

    poor = summary.get("poorly_answered", [])
    if poor:
        print("\n  ❌ 暴露短板:")
        for item in poor:
            print(f"     • {item}")

    focus = summary.get("interviewer_focus", [])
    if focus:
        print("\n  🎯 面试官关注:")
        for item in focus:
            print(f"     • {item}")

    suggestions = summary.get("improvement_suggestions", [])
    if suggestions:
        print("\n  💡 改进建议:")
        for item in suggestions:
            print(f"     • {item}")

    if result.profile_updated:
        print("\n  ✓ 用户画像已更新")
    else:
        print("\n  ⚠ 用户画像未更新")

    print("\n" + "═" * 50)
