"""
core/prepare_agent.py - 岗位预测手写 ReAct Agent

将原 preparer.py 的线性流水线（搜JD → 读简历项目 → 出题 → 写文件）
升级为可自主决策的 Agent：
- 根据 JD 搜索结果数量决定是否换关键词补充搜索
- 根据用户画像调整出题方向（短板/高频考点重点考察）
- 生成后自评质量并按需迭代优化

基于 OpenAI 原生 function calling（DeepSeek / Qwen 均兼容），零额外框架依赖。
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# 确保可以 import 上层模块（CLI / API 两种入口都安全）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI

import config
from logger import get_logger
from llm_client import chat_completion

logger = get_logger("prepare_agent")

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


# ──────────────────────────────────────────────
# Deps
# ──────────────────────────────────────────────

@dataclass
class PrepareDeps:
    """Agent 运行期依赖（含可变累积状态，不持久化）"""
    company: str
    position: str
    date: str
    question_count: int

    # 共享单例（由 api/deps.py 提供）
    web_searcher: Any
    question_bank: Any
    project_reader: Any
    profile_manager: Any

    department: str = ""

    # 累积状态：tool 之间通过 deps 传递
    jd_snippets: list[str] = field(default_factory=list)
    jd_urls: list[str] = field(default_factory=list)
    search_rounds: int = 0
    iterations_used: int = 0

    # 最终输出（submit_final 工具回填）
    final_markdown: str = ""
    final_quality: float = 0.0
    finalized: bool = False

    # 版本管理：防止反思后质量下降（保留最佳版本 + 最近版本对比）
    best_markdown: str = ""
    best_score: float = 0.0
    last_markdown: str = ""
    last_score: float = 0.0
    version: int = 0


# ──────────────────────────────────────────────
# 系统提示
# ──────────────────────────────────────────────

_SYSTEM_PROMPT = """\
你是面试预测题生成 Agent。目标：为指定公司+岗位生成 12-18 道针对性预测题。

可用工具：
- search_jd(query, max_results) - 搜索 JD；可多轮，每轮换关键词
- read_resume() - 读取候选人简历摘要
- read_projects(max_tier) - 读取项目文档（tier 1=README, 2=启动层, 3=深挖）
- get_user_profile() - 获取候选人优势/短板/高频考点画像
- check_duplicates(question_text) - 单题查重，返回是否与已有题库重复
- generate_questions_draft(focus, count) - 生成初版题库 Markdown
- evaluate_quality(markdown) - LLM 自评，返回四维度评分
- submit_final(markdown, quality_score) - 提交最终题库，结束流程

执行规则：
1. 先调 search_jd 一轮；若返回 total_snippets_so_far < 3，换关键词再搜（最多 3 轮）
2. 调 read_resume 与 read_projects(max_tier=2)；若候选人有强项目背景，对最相关项目 max_tier=3 再读
3. 调 get_user_profile；将其 weaknesses / frequently_asked 列入题目重点方向
4. 调 generate_questions_draft 生成初版（focus 描述要重点考察的方向）
5. 抽样 2-3 道题调 check_duplicates；若重复率高则用 focus="避开XX题型" 重新生成
6. 调 evaluate_quality 对当前 markdown 自评；若 overall < 0.6 则迭代一次（最多 2 轮）
7. **必须**通过 submit_final 工具提交最终题库（markdown 来自最新的 generate_questions_draft 结果，
   quality_score 来自最近一次 evaluate_quality 的 overall）

版本管理（系统自动，你无需关心）：
- 每次 generate_questions_draft 生成一个版本；每次 evaluate_quality 后系统自动保留历史最高分版本
- submit_final 时若本次分数低于历史最佳，系统会静默使用最佳版本
- 你只需要照常调用 generate → evaluate → submit_final 即可

约束：
- 总 LLM 调用不超过 8 次
- 任何工具异常容错继续，不要因为单工具失败而终止
- 不在最终 markdown 中混入工具调用日志或中间说明
"""


# ──────────────────────────────────────────────
# Tool 实现（每个返回 dict，供 JSON 序列化回灌给 LLM）
# ──────────────────────────────────────────────

def _run_async(coro):
    """在可能已存在事件循环的场景下安全执行协程"""
    try:
        asyncio.get_running_loop()
        in_loop = True
    except RuntimeError:
        in_loop = False

    if in_loop:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=60)
    return asyncio.run(coro)


def _tool_search_jd(deps: PrepareDeps, query: str = "", max_results: int = 6) -> dict:
    ws = deps.web_searcher
    try:
        jd = _run_async(ws.search_jd(deps.company, deps.position, max_results))
        snippets = jd.get("jd_snippets", []) or []
        urls = jd.get("source_urls", []) or []

        new_snippets = [s for s in snippets if s and s not in deps.jd_snippets]
        new_urls = [u for u in urls if u and u not in deps.jd_urls]
        deps.jd_snippets.extend(new_snippets)
        deps.jd_urls.extend(new_urls)
        deps.search_rounds += 1

        return {
            "snippets_count": len(new_snippets),
            "urls_count": len(new_urls),
            "total_snippets_so_far": len(deps.jd_snippets),
            "preview": [s[:120] for s in new_snippets[:3]],
            "search_rounds": deps.search_rounds,
        }
    except Exception as e:
        logger.warning(f"search_jd 工具异常: {e}")
        return {
            "error": str(e),
            "snippets_count": 0,
            "total_snippets_so_far": len(deps.jd_snippets),
        }


def _tool_read_resume(deps: PrepareDeps) -> dict:
    try:
        from preparer import _load_resume_summary
        text = _load_resume_summary()
        return {"resume": text[:3000], "length": len(text)}
    except Exception as e:
        logger.warning(f"read_resume 工具异常: {e}")
        return {"resume": "", "length": 0, "error": str(e)}


def _tool_read_projects(deps: PrepareDeps, max_tier: int = 2) -> dict:
    try:
        reader = deps.project_reader
        blocks: list[str] = []
        project_names: list[str] = []
        for proj in getattr(reader, "_projects", []):
            name = proj.get("name", "")
            if not name:
                continue
            ctx_text = reader.get_context(name, max_tier=max_tier)
            if ctx_text:
                if len(ctx_text) > 2500:
                    ctx_text = ctx_text[:2500] + "\n... [项目文档已截断]"
                blocks.append(ctx_text)
                project_names.append(name)
        text = "\n\n".join(blocks)
        return {
            "projects_text": text,
            "project_names": project_names,
            "length": len(text),
            "tier": max_tier,
        }
    except Exception as e:
        logger.warning(f"read_projects 工具异常: {e}")
        return {"projects_text": "", "project_names": [], "length": 0, "error": str(e)}


def _tool_get_user_profile(deps: PrepareDeps) -> dict:
    try:
        pm = deps.profile_manager
        return {
            "summary": pm.get_profile_summary(),
            "strengths": list(pm.get_strengths())[:5],
            "weaknesses": list(pm.get_weaknesses())[:5],
            "frequently_asked": [
                t.get("topic", "") for t in pm.get_frequently_asked()[:5]
            ],
        }
    except Exception as e:
        logger.warning(f"get_user_profile 工具异常: {e}")
        return {
            "summary": "",
            "strengths": [],
            "weaknesses": [],
            "frequently_asked": [],
            "error": str(e),
        }


def _tool_check_duplicates(deps: PrepareDeps, question_text: str) -> dict:
    try:
        qb = deps.question_bank
        results = qb.search(question_text, top_k=3)
        best = results[0] if results else None
        return {
            "is_duplicate": bool(best and best.get("score", 0) >= 8.0),
            "best_match_id": best.get("id") if best else None,
            "best_match_text": (best.get("text", "") if best else "")[:80],
            "best_score": float(best.get("score", 0)) if best else 0.0,
        }
    except Exception as e:
        logger.warning(f"check_duplicates 工具异常: {e}")
        return {"is_duplicate": False, "error": str(e)}


def _tool_generate_questions_draft(deps: PrepareDeps, focus: str = "", count: int | None = None) -> dict:
    try:
        from preparer import _load_resume_summary, _load_projects_context, _load_existing_questions_brief

        resume = _load_resume_summary()
        projects = _load_projects_context()
        existing = _load_existing_questions_brief()
        qc = count or deps.question_count

        if deps.jd_snippets:
            jd_block_lines = [
                f"[片段 {i + 1}] {s}"
                for i, s in enumerate(deps.jd_snippets[:8])
            ]
            jd_block = "\n\n".join(jd_block_lines)
            if len(jd_block) > 4000:
                jd_block = jd_block[:4000] + "\n... [JD 片段已截断]"
            if deps.jd_urls:
                jd_block += "\n\n参考 URL：\n" + "\n".join(
                    f"- {u}" for u in deps.jd_urls[:8]
                )
        else:
            jd_block = "（未能检索到有效 JD 信息，请基于岗位常识合理推断）"

        prompt_file = PROMPTS_DIR / "prepare_system.md"
        if prompt_file.exists():
            system_prompt = prompt_file.read_text(encoding="utf-8")
        else:
            system_prompt = (
                "你是资深面试官。基于 JD 与简历项目生成 12-18 道针对性预测题，"
                "按 Q1/Q2 格式输出 Markdown，每题包含 来源、考察点、要点、💬 面试话术。"
            )

        user_parts = [
            f"## 公司与岗位\n- 公司：{deps.company}\n- 岗位：{deps.position}\n- 面试日期：{deps.date}\n- 期望题数：约 {qc} 题（允许 ±3）",
            f"## JD 片段（来自网络搜索）\n\n{jd_block}",
            f"## 候选人简历摘要\n\n{resume or '（简历未读取，请基于岗位合理出题）'}",
            f"## 候选人项目上下文\n\n{projects or '（暂无项目文档）'}",
            f"## 已有题库题目（请避免重复出题）\n\n{existing or '（题库为空或读取失败）'}",
        ]
        if focus:
            user_parts.append(f"## 本次生成重点方向\n\n{focus}")
        user_parts.append(
            "请按系统提示中的 Markdown 模板输出完整题库文件内容，**不要包含任何多余说明或代码围栏**。"
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]

        text = chat_completion(messages=messages, temperature=0.6, max_tokens=4096)

        body = text.strip()
        if body.startswith("```"):
            body = re.sub(r"^```[a-zA-Z]*\n", "", body, count=1)
            body = re.sub(r"\n```\s*$", "", body, count=1)

        deps.iterations_used += 1
        deps.version += 1
        deps.last_markdown = body
        deps.last_score = 0.0  # 等 evaluate_quality 回填
        q_count = len(re.findall(r"^#{2,4}\s*Q\d+[：:]", body, re.MULTILINE))

        return {
            "markdown": body,
            "question_count": q_count,
            "length": len(body),
            "iterations_used": deps.iterations_used,
        }
    except Exception as e:
        logger.error(f"generate_questions_draft 工具异常: {e}")
        return {"markdown": "", "question_count": 0, "error": str(e)}


def _tool_evaluate_quality(deps: PrepareDeps, markdown: str) -> dict:
    try:
        messages = [
            {
                "role": "system",
                "content": (
                    "你是面试题质量审核官。从 4 个维度评分（0-1，越高越好）：\n"
                    "- jd_coverage: JD 关键能力覆盖度\n"
                    "- project_depth: 项目深挖针对性\n"
                    "- profile_match: 与候选人短板/高频考点契合度\n"
                    "- dup_rate: 与常见八股的差异化程度（越独特越高）\n"
                    '严格输出 JSON：{"jd_coverage":0.x,"project_depth":0.x,"profile_match":0.x,"dup_rate":0.x,"comment":"一句话"}'
                ),
            },
            {"role": "user", "content": f"待评估题库内容：\n\n{markdown[:6000]}"},
        ]
        response = chat_completion(
            messages=messages,
            temperature=0.2,
            max_tokens=512,
            response_format={"type": "json_object"},
        )
        data = json.loads(response)
        scores = {
            "jd_coverage": float(data.get("jd_coverage", 0.7)),
            "project_depth": float(data.get("project_depth", 0.7)),
            "profile_match": float(data.get("profile_match", 0.7)),
            "dup_rate": float(data.get("dup_rate", 0.7)),
            "comment": str(data.get("comment", ""))[:200],
        }
        scores["overall"] = round(
            sum(scores[k] for k in ("jd_coverage", "project_depth", "profile_match", "dup_rate")) / 4,
            3,
        )
        # 版本管理：若当前版本优于历史最佳，自动升级 best
        deps.last_score = scores["overall"]
        if scores["overall"] > deps.best_score:
            deps.best_score = scores["overall"]
            deps.best_markdown = deps.last_markdown
        return scores
    except Exception as e:
        logger.warning(f"evaluate_quality 工具异常: {e}")
        return {
            "jd_coverage": 0.7,
            "project_depth": 0.7,
            "profile_match": 0.7,
            "dup_rate": 0.7,
            "overall": 0.7,
            "error": str(e),
        }


def _tool_submit_final(deps: PrepareDeps, markdown: str, quality_score: float = 0.7) -> dict:
    """终结工具：回填最终 markdown 与质量分，标记 finalized。

    版本管理：若本次提交的分数低于历史最佳，自动使用最佳版本。
    """
    md = (markdown or "").strip()
    if md.startswith("```"):
        md = re.sub(r"^```[a-zA-Z]*\n", "", md, count=1)
        md = re.sub(r"\n```\s*$", "", md, count=1)
    try:
        score = max(0.0, min(1.0, float(quality_score)))
    except Exception:
        score = 0.7

    # 防退化：若历史最佳版本分数更高，静默替换
    if deps.best_markdown and deps.best_score > score:
        logger.warning(
            f"LLM 提交版本 score={score:.2f} 低于历史最佳 best_score={deps.best_score:.2f}，"
            f"自动使用最佳版本"
        )
        deps.final_markdown = deps.best_markdown
        deps.final_quality = deps.best_score
    else:
        deps.final_markdown = md
        deps.final_quality = score
        # 最后提交的版本若是最佳，也更新 best
        if score > deps.best_score:
            deps.best_score = score
            deps.best_markdown = md

    deps.finalized = True
    return {
        "accepted": True,
        "length": len(deps.final_markdown),
        "quality_score": deps.final_quality,
        "used_best_version": deps.best_markdown and deps.best_score > score,
    }


# ──────────────────────────────────────────────
# Tool schema（OpenAI function calling 格式）
# ──────────────────────────────────────────────

_TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_jd",
            "description": "搜索公司+岗位 JD 信息。可多次调用换关键词扩展覆盖。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "自定义搜索词（留空则用默认 company+position 组合）"},
                    "max_results": {"type": "integer", "description": "单次返回结果上限", "default": 6},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_resume",
            "description": "读取候选人简历摘要",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_projects",
            "description": "读取候选人项目文档摘要。max_tier: 1=仅README, 2=启动层, 3=深挖。",
            "parameters": {
                "type": "object",
                "properties": {"max_tier": {"type": "integer", "default": 2}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_user_profile",
            "description": "获取候选人画像（含优势、短板、高频考点）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_duplicates",
            "description": "对单条题目文本在已有题库中查重",
            "parameters": {
                "type": "object",
                "properties": {"question_text": {"type": "string"}},
                "required": ["question_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_questions_draft",
            "description": "根据已收集的 JD/简历/项目/画像生成初版题库 Markdown",
            "parameters": {
                "type": "object",
                "properties": {
                    "focus": {"type": "string", "description": "重点方向提示"},
                    "count": {"type": "integer", "description": "期望题数"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_quality",
            "description": "LLM 自评题库质量，输出四维度评分（0-1）",
            "parameters": {
                "type": "object",
                "properties": {"markdown": {"type": "string"}},
                "required": ["markdown"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_final",
            "description": "提交最终题库 Markdown 与综合质量分（quality_score 0-1），结束 Agent 流程",
            "parameters": {
                "type": "object",
                "properties": {
                    "markdown": {"type": "string"},
                    "quality_score": {"type": "number", "default": 0.7},
                },
                "required": ["markdown"],
            },
        },
    },
]


def _build_tool_dispatcher(deps: PrepareDeps) -> dict[str, Callable[..., dict]]:
    """构造工具名 → 闭包函数的映射"""
    return {
        "search_jd": lambda **kw: _tool_search_jd(deps, **kw),
        "read_resume": lambda **kw: _tool_read_resume(deps, **kw),
        "read_projects": lambda **kw: _tool_read_projects(deps, **kw),
        "get_user_profile": lambda **kw: _tool_get_user_profile(deps, **kw),
        "check_duplicates": lambda **kw: _tool_check_duplicates(deps, **kw),
        "generate_questions_draft": lambda **kw: _tool_generate_questions_draft(deps, **kw),
        "evaluate_quality": lambda **kw: _tool_evaluate_quality(deps, **kw),
        "submit_final": lambda **kw: _tool_submit_final(deps, **kw),
    }


# ──────────────────────────────────────────────
# ReAct Loop 入口
# ──────────────────────────────────────────────

def run_prepare_agent(
    company: str,
    position: str,
    date: str,
    question_count: int,
    department: str = "",
) -> tuple[str, dict]:
    """运行岗位预测 Agent。

    Returns:
        (markdown_content, meta) 其中 meta 含 jd_snippet_count / jd_source_count /
        iterations_used / quality_score / search_rounds
    """
    from api.deps import question_bank, project_reader, profile_manager, web_searcher

    deps = PrepareDeps(
        company=company,
        position=position,
        date=date,
        question_count=question_count,
        department=department,
        web_searcher=web_searcher,
        question_bank=question_bank,
        project_reader=project_reader,
        profile_manager=profile_manager,
    )

    api_key, base_url, model_name = config.get_active_provider()
    if not api_key:
        raise RuntimeError("LLM API key 未配置，无法启动 prepare_agent")

    client = OpenAI(api_key=api_key, base_url=base_url)
    max_iters = max(3, int(getattr(config, "PREP_AGENT_MAX_ITERS", 8)))

    dept_hint = f"\n部门/团队：{department}" if department else ""
    user_prompt = (
        f"为「{company}」的「{position}」岗位生成针对性面试预测题（约 {question_count} 题，日期 {date}）。"
        f"{dept_hint}"
        f"\n按系统规则执行：搜 JD → 读简历/项目 → 结合用户画像 → 生成 → 自评 → 必要时迭代 → submit_final 提交。"
    )

    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    dispatcher = _build_tool_dispatcher(deps)

    logger.info(
        f"启动 prepare_agent: company={company}, position={position}, "
        f"date={date}, qc={question_count}, max_iters={max_iters}"
    )

    for step in range(1, max_iters + 1):
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=_TOOL_SCHEMAS,
            tool_choice="auto",
            temperature=0.3,
            max_tokens=2048,
        )
        msg = response.choices[0].message
        tool_calls = getattr(msg, "tool_calls", None) or []

        # 把 assistant 消息塞回历史（含可能的 tool_calls）
        assistant_entry: dict = {"role": "assistant", "content": msg.content or ""}
        if tool_calls:
            assistant_entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments or "{}",
                    },
                }
                for tc in tool_calls
            ]
        messages.append(assistant_entry)

        if not tool_calls:
            # 模型不再调工具：若已 finalized 则正常结束；否则强制再走一轮要求 submit_final
            if deps.finalized:
                break
            messages.append({
                "role": "user",
                "content": "请立刻调用 submit_final 工具提交最终题库 Markdown，不要再用自然语言回答。",
            })
            continue

        # 执行所有 tool_call
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            fn = dispatcher.get(name)
            if fn is None:
                result = {"error": f"unknown tool: {name}"}
            else:
                try:
                    result = fn(**args)
                except TypeError as e:
                    result = {"error": f"参数错误: {e}"}
                except Exception as e:
                    logger.warning(f"工具 {name} 执行异常: {e}")
                    result = {"error": str(e)}

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": name,
                "content": json.dumps(result, ensure_ascii=False)[:8000],
            })

        # 软护栏：JD 搜满 3 轮后注入提醒，防 LLM 钻牛角尖
        if deps.search_rounds >= 3 and any(
            tc.function.name == "search_jd" for tc in tool_calls
        ):
            messages.append({
                "role": "user",
                "content": (
                    "[系统提示] JD 搜索已达 3 轮上限，请立即进入下一步："
                    "read_resume → read_projects → get_user_profile → generate 出题，不要再搜 JD。"
                ),
            })

        if deps.finalized:
            break

    if not deps.final_markdown:
        raise RuntimeError("Agent 未通过 submit_final 提交最终题库（已达迭代上限）")

    meta = {
        "jd_snippet_count": len(deps.jd_snippets),
        "jd_source_count": len(deps.jd_urls),
        "iterations_used": int(deps.iterations_used or 1),
        "quality_score": float(deps.final_quality or 0.0),
        "search_rounds": deps.search_rounds,
    }

    logger.info(
        f"prepare_agent 完成: markdown_len={len(deps.final_markdown)}, "
        f"quality={meta['quality_score']:.2f}, iters={meta['iterations_used']}, "
        f"jd_snippets={meta['jd_snippet_count']}, search_rounds={meta['search_rounds']}"
    )

    return deps.final_markdown, meta
