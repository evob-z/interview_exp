"""快速问答 API - 基于知识库的面试问答"""
import asyncio
import json
import os
import re
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.deps import question_bank, project_reader, profile_manager
from api.routes.history import append_message, _load_session
from api.routes.followup import async_generate_followups
from llm_client import chat_completion, chat_completion_stream
from logger import get_logger
import config
from config import PROJECT_ALIASES

logger = get_logger("api.qa")

router = APIRouter()

# 加载 QA System Prompt 模板
_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"
_QA_PROMPT_CACHE: str | None = None  # 惰性缓存，首次加载后存内存

# 混合匹配阈值：仅当 score >= 此值（即强匹配）时才直接返回已有回答
# 纯关键词≤10分 + 语义加成(cosine×10)，低于阈值走 LLM 路径
DIRECT_ANSWER_THRESHOLD = 9.5


def _detect_project_intent(question: str) -> tuple[list[str], list[str]]:
    """检测问题中的项目意图，一次遍历返回 (categories, matched_aliases)"""
    categories: set[str] = set()
    aliases: list[str] = []
    q_lower = question.lower()
    for alias, category in PROJECT_ALIASES.items():
        if alias.lower() in q_lower:
            if isinstance(category, list):
                categories.update(category)
            else:
                categories.add(category)
            aliases.append(alias)
    return (list(categories) if categories else [], aliases)


def _load_qa_prompt() -> str:
    """加载问答 system prompt 模板（惰性缓存，运行时只读一次）"""
    global _QA_PROMPT_CACHE
    if _QA_PROMPT_CACHE is not None:
        return _QA_PROMPT_CACHE
    prompt_file = _PROMPTS_DIR / "qa_system.md"
    try:
        if prompt_file.exists():
            _QA_PROMPT_CACHE = prompt_file.read_text(encoding="utf-8")
            return _QA_PROMPT_CACHE
    except Exception as e:
        logger.error(f"加载 QA prompt 失败: {e}")
    # Fallback
    _QA_PROMPT_CACHE = (
        "你是一个专业的面试教练助手。根据用户的问题和知识库内容，给出面试级别的回答。\n\n"
        "## 知识库上下文\n\n{context}\n\n## 用户画像\n\n{profile_summary}"
    )
    return _QA_PROMPT_CACHE


# ─── 过渡话术模板 ───

_FILLER_TEMPLATES = [
    "好的，关于{keyword}这个问题，让我来梳理一下...\n\n",
    "嗯，{keyword}是一个很好的问题，我从几个方面来回答...\n\n",
    "关于{keyword}，这确实是面试中的高频考点，让我详细说一下...\n\n",
    "好，{keyword}这个问题我来回答一下...\n\n",
]


def _generate_filler(question: str) -> str:
    """根据问题快速生成过渡话术（<1ms，纯模板）"""
    # 提取关键词：取问题前15字或到第一个标点
    keyword = question.strip()
    # 去掉开头的"请问"、"什么是"等
    for prefix in ["请问", "请解释", "什么是", "解释一下", "说一下", "讲一下"]:
        if keyword.startswith(prefix):
            keyword = keyword[len(prefix):]
            break
    # 截取关键部分
    for sep in ["？", "?", "，", "。", "的原理", "的区别", "的作用"]:
        idx = keyword.find(sep)
        if 0 < idx < 20:
            keyword = keyword[:idx]
            break
    if len(keyword) > 20:
        keyword = keyword[:20]
    keyword = keyword.strip()

    # 基于问题 hash 选择模板（确定性）
    template = _FILLER_TEMPLATES[hash(question) % len(_FILLER_TEMPLATES)]
    return template.format(keyword=keyword if keyword else "这个问题")


def _format_direct_answer(result: dict) -> str:
    """将问题库的匹配结果格式化为可直接使用的回答"""
    parts = []

    # 优先使用面试话术
    if result.get("speech"):
        parts.append(result["speech"])
    elif result.get("points"):
        # 没有话术就用要点组织
        parts.append("关于这个问题，核心要点如下：\n")
        for pt in result["points"]:
            parts.append(f"- {pt}")

    if not parts:
        return ""

    answer = "\n".join(parts)

    # 如果有要点且有话术，补充要点作为结构化补充
    if result.get("speech") and result.get("points"):
        answer += "\n\n**答题要点：**\n"
        for pt in result["points"]:
            answer += f"- {pt}\n"

    return answer


# ─── 请求/响应模型 ───


class QARequest(BaseModel):
    question: str
    mode: str = "interview"  # interview / explain / quick
    session_id: str = ""  # 当前会话ID


class QAResponse(BaseModel):
    answer: str
    sources: list[dict]  # [{category, question_id, text}]


# ─── 内部辅助 ───


def _build_context(question: str) -> tuple[str, list[dict]]:
    """
    搜索知识库并构建 context 字符串。
    返回 (context_text, sources)
    结果按项目(category)分组展示，避免模型混淆不同项目的内容。
    """
    sources: list[dict] = []
    context_parts: list[str] = []

    # 1. 搜索问题库
    qa_results = []
    try:
        boost, matched_aliases = _detect_project_intent(question)
        allowed_cats = list(config.CATEGORY_FILE_MAP.keys())
        qa_results = question_bank.search(question, top_k=5, boost_categories=boost or allowed_cats)
    except Exception as e:
        logger.error(f"问题库搜索失败: {e}")

    # 2. 搜索项目文档：用命中的别名逐个检索，合并去重
    project_results = []
    try:
        search_terms = matched_aliases if matched_aliases else [question]
        seen: set[tuple] = set()
        for term in search_terms:
            for pr in (project_reader.search_in_projects(term) or []):
                key = (pr.get("project_name"), pr.get("file"))
                if key not in seen:
                    seen.add(key)
                    project_results.append(pr)
        logger.info(f"项目文档检索: terms={search_terms} → {len(project_results)} 条结果")
    except Exception as e:
        logger.warning(f"项目文档搜索失败: {e}")

    logger.info(f"_build_context: qa={len(qa_results)} proj={len(project_results)} boost={boost}")

    # 2.5 当检测到明确项目意图时，过滤项目文档结果，只保留目标项目
    if boost and project_results:
        # 从 boost categories 提取项目名（如 "项目-law_sea" → "law_sea"）
        boost_project_names = {cat.replace("项目-", "") for cat in boost}
        filtered = [pr for pr in project_results
                    if pr.get("project_name", "") in boost_project_names]
        # 只有过滤后还有结果时才替换，否则保留原始结果
        if filtered:
            project_results = filtered

    # 3. 按 category/项目 分组组织上下文
    if qa_results or project_results:
        # 按 category 分组问题库结果
        from collections import defaultdict
        grouped_qa: dict[str, list] = defaultdict(list)
        for r in qa_results:
            grouped_qa[r["category"]].append(r)
            sources.append({
                "category": r["category"],
                "question_id": f"Q{r['id']}",
                "text": r["text"],
            })

        # 按项目名分组项目文档结果
        grouped_proj: dict[str, list] = defaultdict(list)
        for pr in project_results[:3]:
            grouped_proj[pr.get("project_name", "未知项目")].append(pr)

        # 收集所有出现的项目名，统一输出
        all_categories = list(dict.fromkeys(
            list(grouped_qa.keys()) + [f"项目-{k}" for k in grouped_proj.keys()]
        ))

        for cat in all_categories:
            cat_parts = []
            # 问题库条目
            if cat in grouped_qa:
                for r in grouped_qa[cat]:
                    entry = f"**Q{r['id']}: {r['text']}**\n"
                    if r.get("points"):
                        entry += "答题要点:\n"
                        for pt in r["points"]:
                            entry += f"  - {pt}\n"
                    if r.get("speech"):
                        entry += f"面试话术:\n> {r['speech']}\n"
                    cat_parts.append(entry)

            # 项目文档条目（匹配同一项目）
            proj_name = cat.replace("项目-", "") if cat.startswith("项目-") else cat
            if proj_name in grouped_proj:
                for pr in grouped_proj[proj_name]:
                    cat_parts.append(
                        f"项目文档（{pr['file']}）:\n  {pr['context']}\n"
                    )

            if cat_parts:
                context_parts.append(f"### {cat}\n")
                context_parts.extend(cat_parts)

    context_text = "\n".join(context_parts) if context_parts else "（知识库中无相关内容）"
    return context_text, sources


def _build_messages(question: str, mode: str) -> tuple[list[dict], list[dict]]:
    """构建 LLM 消息列表，返回 (messages, sources)"""
    # 获取 context
    context_text, sources = _build_context(question)

    # 获取画像摘要
    try:
        profile_summary = profile_manager.get_profile_summary()
    except Exception:
        profile_summary = "画像尚未初始化"

    # 构建 system prompt
    template = _load_qa_prompt()
    system_prompt = template.replace("{context}", context_text).replace(
        "{profile_summary}", profile_summary
    )

    # 用户消息附带 mode 提示
    mode_hint = {
        "interview": "请以面试话术风格回答，可以直接在面试中使用。",
        "explain": "请详细解释，包含原理、使用场景、优缺点。",
        "quick": "请用一两句话快速回答核心要点。",
    }

    user_content = f"[回答模式: {mode}] {mode_hint.get(mode, '')}\n\n问题: {question}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    return messages, sources


# ─── API 端点 ───


@router.post("", response_model=QAResponse)
async def ask_question(req: QARequest):
    """快速问答 - 非流式"""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    try:
        # 先尝试直接匹配（跳过无内容的空壳条目）
        boost, _ = _detect_project_intent(req.question)
        allowed_cats = list(config.CATEGORY_FILE_MAP.keys())
        qa_results = question_bank.search(req.question, top_k=5, boost_categories=boost or allowed_cats)
        for candidate in qa_results:
            if candidate["score"] < DIRECT_ANSWER_THRESHOLD:
                break
            direct_answer = _format_direct_answer(candidate)
            if direct_answer:
                sources = [{"category": candidate["category"], "question_id": f"Q{candidate['id']}", "text": candidate["text"]}]
                try:
                    if req.session_id:
                        append_message(req.session_id, "user", req.question, mode=req.mode)
                        append_message(req.session_id, "assistant", direct_answer, sources=[candidate["text"]])
                except Exception:
                    pass
                return QAResponse(answer=direct_answer, sources=sources)

        messages, sources = _build_messages(
            req.question, req.mode
        )

        answer = chat_completion(
            messages=messages,
            temperature=0.7,
            max_tokens=2048,
        )

        # 保存历史记录
        try:
            if req.session_id:
                append_message(req.session_id, "user", req.question, mode=req.mode)
                append_message(req.session_id, "assistant", answer, sources=[s.get("text", "") for s in sources] if sources else [])
        except Exception as e:
            logger.error(f"保存历史记录失败: {e}")

        return QAResponse(
            answer=answer,
            sources=sources,
        )
    except Exception as e:
        logger.error(f"问答失败: {e}")
        raise HTTPException(status_code=500, detail=f"问答生成失败: {str(e)}")


@router.post("/stream")
async def ask_question_stream(req: QARequest):
    """流式问答（SSE）- 支持直接匹配和过渡话术+LLM两种模式"""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="问题不能为空")

    # 第一步：快速搜索问题库（<50ms）
    boost, _ = _detect_project_intent(req.question)
    allowed_cats = list(config.CATEGORY_FILE_MAP.keys())
    qa_results = question_bank.search(req.question, top_k=5, boost_categories=boost or allowed_cats)
    # 找第一个有内容且分数达标的结果（跳过空壳重复条目）
    best_match = None
    for r in qa_results:
        if r["score"] >= DIRECT_ANSWER_THRESHOLD and _format_direct_answer(r):
            best_match = r
            break
    has_direct_answer = best_match is not None

    async def event_generator():
        sources = []

        if has_direct_answer:
            # ─── 路径A：直接返回已有回答，不走LLM ───
            direct_answer = _format_direct_answer(best_match)
            sources = [{"category": best_match["category"], "question_id": f"Q{best_match['id']}", "text": best_match["text"]}]

            # 发送来源
            yield f"data: {json.dumps({'type': 'sources', 'data': sources}, ensure_ascii=False)}\n\n"

            # 直接发送完整回答
            yield f"data: {json.dumps({'type': 'content', 'data': direct_answer}, ensure_ascii=False)}\n\n"

            yield f"data: {json.dumps({'type': 'done'})}\n\n"

            logger.info(f"直接匹配回答: Q{best_match['id']} (score={best_match['score']:.1f})")

            # 保存历史
            try:
                if req.session_id:
                    append_message(req.session_id, "user", req.question, mode=req.mode)
                    append_message(req.session_id, "assistant", direct_answer, sources=[best_match["text"]])
            except Exception:
                pass

            # 触发追问预测（路径A）
            if config.ENABLE_FOLLOWUP_PREDICTION and req.session_id:
                asyncio.create_task(async_generate_followups(req.question, direct_answer, req.session_id))

        else:
            # ─── 路径B：网络搜索过渡 + LLM 真流式 ───

            # 1. 立即发送引导语
            _guide_msg = json.dumps({"type": "content", "data": "正在搜索相关资料...\n\n"}, ensure_ascii=False)
            yield f"data: {_guide_msg}\n\n"
            await asyncio.sleep(0)

            # 2. 并发：网络搜索 + 本地检索（互不依赖，重叠 I/O 等待时间）
            loop = asyncio.get_event_loop()

            async def _search_web():
                try:
                    from api.deps import web_searcher
                    return await web_searcher.search(req.question, max_results=3)
                except Exception as e:
                    logger.error(f"网络搜索失败: {e}")
                    return []

            web_task = asyncio.create_task(_search_web())
            local_future = loop.run_in_executor(None, lambda: _build_messages(req.question, req.mode))

            # 3. 构建 LLM 消息 + 等待网络搜索结果
            try:
                # 先等待本地检索（通常是瓶颈 ~4s），网络搜索可能已并行完成
                messages, sources = await local_future
                search_results = await web_task
            except Exception as e:
                logger.error(f"检索构建失败: {e}")
                err_msg = f"\n\n抱歉，生成回答时出错: {str(e)}"
                yield f"data: {json.dumps({'type': 'content', 'data': err_msg}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return

            # 格式化网络搜索摘要，输出给用户
            search_snippets = ""
            if search_results:
                search_snippets = "\U0001f4ce **相关资料：**\n"
                for sr in search_results[:3]:
                    title = sr.get("title", "")
                    content = sr.get("content", "")[:150]
                    if title or content:
                        search_snippets += f"- **{title}**: {content}\n"
                search_snippets += "\n---\n\n"
                yield f"data: {json.dumps({'type': 'content', 'data': search_snippets}, ensure_ascii=False)}\n\n"

            # 4. LLM 流式输出（含历史上下文注入）
            try:
                if req.session_id:
                    session = _load_session(req.session_id)
                    if session and session.get("messages"):
                        # 只取最近 MAX_CONTEXT_TURNS 轮
                        recent_msgs = session["messages"][-(config.MAX_CONTEXT_TURNS * 2):]
                        context_messages = []
                        for msg in recent_msgs:
                            if msg["role"] in ("user", "assistant"):
                                context_messages.append({"role": msg["role"], "content": msg["content"]})
                        # 在 system prompt 后插入历史上下文，用户新问题前
                        if context_messages:
                            messages = [
                                messages[0],  # system prompt
                                *context_messages,
                                {"role": "user", "content": messages[-1]["content"]},
                            ]

                # 如果有搜索结果，追加到 context
                if search_snippets:
                    # 在 system message 中追加搜索结果
                    messages[0]["content"] += f"\n\n## 网络搜索参考\n\n{search_snippets}"

                # 发送来源
                yield f"data: {json.dumps({'type': 'sources', 'data': sources}, ensure_ascii=False)}\n\n"

                # 4. LLM 真流式输出
                full_answer = ""
                stream_gen = chat_completion_stream(
                    messages=messages, temperature=0.7, max_tokens=2048
                )

                # 在线程池中运行同步生成器
                import queue
                import threading

                chunk_queue = queue.Queue()

                def _run_stream():
                    try:
                        for chunk in stream_gen:
                            chunk_queue.put(chunk)
                    except Exception as e:
                        chunk_queue.put(e)
                    finally:
                        chunk_queue.put(None)  # sentinel

                thread = threading.Thread(target=_run_stream, daemon=True)
                thread.start()

                while True:
                    # 非阻塞等待，让出事件循环
                    while chunk_queue.empty():
                        await asyncio.sleep(0.02)

                    item = chunk_queue.get()
                    if item is None:
                        break
                    if isinstance(item, Exception):
                        raise item

                    full_answer += item
                    yield f"data: {json.dumps({'type': 'content', 'data': item}, ensure_ascii=False)}\n\n"

                yield f"data: {json.dumps({'type': 'done'})}\n\n"

                # 保存历史
                try:
                    if req.session_id:
                        append_message(req.session_id, "user", req.question, mode=req.mode)
                        append_message(req.session_id, "assistant", full_answer, sources=[s.get("text", "") for s in sources] if sources else [])
                except Exception:
                    pass

                # 触发追问预测（路径B）
                if config.ENABLE_FOLLOWUP_PREDICTION and req.session_id and full_answer:
                    asyncio.create_task(async_generate_followups(req.question, full_answer, req.session_id))

            except Exception as e:
                logger.error(f"LLM 调用失败: {e}")
                err_msg = f"\n\n抱歉，生成回答时出错: {str(e)}"
                yield f"data: {json.dumps({'type': 'content', 'data': err_msg}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
