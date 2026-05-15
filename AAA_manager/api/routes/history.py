"""会话历史记录 API"""
import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import APIRouter, HTTPException
from logger import get_logger

logger = get_logger("api.history")
router = APIRouter()

SESSIONS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "sessions"


def _ensure_dir():
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def _load_session(session_id: str) -> dict:
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_session(session: dict):
    _ensure_dir()
    path = SESSIONS_DIR / f"{session['id']}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(session, f, ensure_ascii=False, indent=2)


def create_session() -> dict:
    """创建新会话"""
    _ensure_dir()
    session = {
        "id": str(uuid.uuid4())[:8],
        "title": "新对话",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "messages": [],
    }
    _save_session(session)
    return session


def append_message(session_id: str, role: str, content: str, **kwargs):
    """向会话追加消息"""
    session = _load_session(session_id)
    if not session:
        # 如果会话不存在，创建一个
        session = create_session()
        session["id"] = session_id
    
    msg = {
        "role": role,
        "content": content,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        **kwargs,
    }
    session["messages"].append(msg)
    session["updated_at"] = datetime.now().isoformat(timespec="seconds")
    
    # 更新标题（取第一条用户消息的前25字）
    if session["title"] == "新对话" and role == "user":
        session["title"] = content[:25] + ("..." if len(content) > 25 else "")
    
    _save_session(session)
    return session


@router.get("/sessions")
async def list_sessions(limit: int = 30):
    """列出所有会话（按更新时间倒序）"""
    _ensure_dir()
    sessions = []
    for f in SESSIONS_DIR.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            sessions.append({
                "id": data["id"],
                "title": data["title"],
                "created_at": data["created_at"],
                "updated_at": data["updated_at"],
                "message_count": len(data["messages"]),
            })
        except Exception:
            continue
    
    sessions.sort(key=lambda x: x["updated_at"], reverse=True)
    return {"status": "ok", "sessions": sessions[:limit]}


@router.post("/sessions")
async def new_session():
    """创建新会话"""
    session = create_session()
    return {"status": "ok", "session": session}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """获取会话完整内容"""
    session = _load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "ok", "session": session}


@router.delete("/sessions/cleanup-empty")
async def cleanup_empty_sessions():
    """删除所有空会话（messages为空数组的会话，排除最近60秒内创建的）"""
    _ensure_dir()
    deleted = []
    now = datetime.now()
    for f in SESSIONS_DIR.glob("*.json"):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            if not data.get("messages"):
                # 只删除创建超过60秒的空会话，保护刚创建的会话
                created_at = data.get("created_at", "")
                if created_at:
                    try:
                        created_time = datetime.fromisoformat(created_at)
                        if (now - created_time).total_seconds() < 60:
                            continue  # 跳过最近创建的
                    except (ValueError, TypeError):
                        pass
                os.remove(f)
                deleted.append(data["id"])
        except Exception:
            continue
    return {"status": "ok", "deleted_count": len(deleted), "deleted_ids": deleted}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    path = SESSIONS_DIR / f"{session_id}.json"
    if path.exists():
        os.remove(path)
    return {"status": "ok", "message": "已删除"}


@router.post("/sessions/{session_id}/export")
async def export_session(session_id: str, body: dict = {}):
    """导出会话中的面试问题到面试原始问题目录"""
    from exporter import export_session_questions

    filename = body.get("filename", None)
    rewrite = body.get("rewrite", False)
    try:
        output_path, count = export_session_questions(session_id, filename, rewrite=rewrite)
        return {
            "status": "ok",
            "file": str(output_path.name),
            "count": count,
            "rewritten": rewrite,
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
