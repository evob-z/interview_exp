"""追问预测 API"""
import json
import asyncio
from pathlib import Path
from fastapi import APIRouter
from pydantic import BaseModel

from llm_client import chat_completion
from logger import get_logger
import config

logger = get_logger("api.followup")
router = APIRouter()

# 内存缓存：session_id -> {question: str, followups: list}
_followup_cache: dict[str, dict] = {}


class FollowupRequest(BaseModel):
    question: str
    answer: str
    session_id: str = ""


def generate_followups(question: str, answer: str) -> list[dict]:
    """同步生成追问列表"""
    messages = [
        {"role": "system", "content": (
            "你是一位资深技术面试官和面试教练。基于候选人刚回答的问题，"
            "生成相关的深入问题，包括：\n"
            "1. 面试官最可能的追问（对回答中某个点的深入探究）\n"
            "2. 相关联的延伸问题（同一知识领域的其他常见面试题）\n"
            "返回 JSON 数组格式，每项包含 question 和 brief_answer 字段。"
            "brief_answer 是候选人应该准备的要点（50-100字）。"
            "问题应该由浅入深排列。"
        )},
        {"role": "user", "content": (
            f"面试问题：{question}\n\n"
            f"候选人回答：{answer}\n\n"
            f"请生成 {config.FOLLOWUP_COUNT} 个最可能被追问或相关的面试问题，返回 JSON 数组："
        )},
    ]
    try:
        result = chat_completion(messages, temperature=0.7, max_tokens=1024)
        # 解析 JSON
        text = result.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        followups = json.loads(text)
        if isinstance(followups, list):
            return followups[:config.FOLLOWUP_COUNT]
    except Exception as e:
        logger.warning(f"生成追问失败: {e}")
    return []


async def async_generate_followups(question: str, answer: str, session_id: str):
    """异步生成追问（后台任务）"""
    loop = asyncio.get_event_loop()
    followups = await loop.run_in_executor(None, generate_followups, question, answer)
    if followups and session_id:
        _followup_cache[session_id] = {
            "question": question,
            "followups": followups,
        }
        logger.info(f"追问生成完成: session={session_id}, count={len(followups)}")


@router.get("/{session_id}")
async def get_followups(session_id: str):
    """获取某会话的追问预测"""
    data = _followup_cache.get(session_id)
    if not data:
        return {"status": "ok", "followups": [], "ready": False}
    return {"status": "ok", "followups": data["followups"], "ready": True}
