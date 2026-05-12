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

logger = get_logger("api.qa")

router = APIRouter()

# 加载 QA System Prompt 模板
_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"

# 相似度阈值：score >= 此值时直接返回已有回答
DIRECT_ANSWER_THRESHOLD = 5.5


def _load_qa_prompt() -> str:
    """加载问答 system prompt 模板"""
    prompt_file = _PROMPTS_DIR / "qa_system.md"
    try:
        if prompt_file.exists():
            return prompt_file.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"加载 QA prompt 失败: {e}")
    # Fallback
    return (
        "你是一个专业的面试教练助手。根据用户的问题和知识库内容，给出面试级别的回答。\n\n"
        "## 知识库上下文\n\n{context}\n\n## 用户画像\n\n{profile_summary}"
    )


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
    """
    sources: list[dict] = []
    context_parts: list[str] = []

    # 1. 搜索问题库
    try:
        qa_results = question_bank.search(question, top_k=5)
        if qa_results:
            context_parts.append("### 问题库匹配结果\n")
            for r in qa_results:
                entry = f"**Q{r['id']}（{r['category']}）: {r['text']}**\n"
                if r.get("points"):
                    entry += "答题要点:\n"
                    for pt in r["points"]:
                        entry += f"  - {pt}\n"
                if r.get("speech"):
                    entry += f"面试话术:\n> {r['speech']}\n"
                context_parts.append(entry)

                sources.append({
                    "category": r["category"],
                    "question_id": f"Q{r['id']}",
                    "text": r["text"],
                })

    except Exception as e:
        logger.warning(f"问题库搜索失败: {e}")

    # 2. 搜索项目文档
    try:
        project_results = project_reader.search_in_projects(question)
        if project_results:
            context_parts.append("\n### 项目文档匹配\n")
            for pr in project_results[:3]:
                context_parts.append(
                    f"- 项目 {pr['project_name']}（{pr['file']}）:\n"
                    f"  {pr['context']}\n"
                )
    except Exception as e:
        logger.warning(f"项目文档搜索失败: {e}")

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
        qa_results = question_bank.search(req.question, top_k=5)
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
            logger.warning(f"保存历史记录失败: {e}")

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
    qa_results = question_bank.search(req.question, top_k=5)
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

            # 2. 网络搜索（异步，不阻塞事件循环）
            search_snippets = ""
            try:
                from api.deps import web_searcher
                search_results = await web_searcher.search(req.question, max_results=3)
                if search_results:
                    # 格式化搜索摘要
                    search_snippets = "\U0001f4ce **相关资料：**\n"
                    for sr in search_results[:3]:
                        title = sr.get("title", "")
                        content = sr.get("content", "")[:150]
                        if title or content:
                            search_snippets += f"- **{title}**: {content}\n"
                    search_snippets += "\n---\n\n"
                    # 输出搜索摘要给用户
                    yield f"data: {json.dumps({'type': 'content', 'data': search_snippets}, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.warning(f"网络搜索失败: {e}")

            # 3. 构建 LLM 消息（在线程池，因为可能有同步IO）
            try:
                loop = asyncio.get_event_loop()
                messages, sources = await loop.run_in_executor(
                    None, lambda: _build_messages(req.question, req.mode)
                )

                # 多轮对话上下文截断
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
                        complete_answer = search_snippets + full_answer
                        append_message(req.session_id, "assistant", complete_answer, sources=[s.get("text", "") for s in sources] if sources else [])
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
