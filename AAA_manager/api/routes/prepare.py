"""岗位针对性预测题 API - 面试前输入公司+岗位，生成预测题库并写入 岗位预测/"""
import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import config
import preparer
from api.deps import question_bank
from logger import get_logger

logger = get_logger("api.prepare")

router = APIRouter()


class PrepareRequest(BaseModel):
    company: str
    position: str
    date: str | None = None
    count: int | None = None


# 运行态（避免并发重复出题）
_prepare_state = {"running": False}


@router.post("/run")
async def run_prepare(req: PrepareRequest):
    """触发岗位预测题生成。

    流程：联网搜 JD → 读简历/项目 → LLM 出题 → 写入 岗位预测/{公司}_{岗位}_{日期}.md。
    完成后会刷新 question_bank 索引，使新题立刻能被「模拟面试」检索到。
    """
    if _prepare_state["running"]:
        raise HTTPException(status_code=409, detail="已有岗位预测任务在执行，请稍后再试")

    company = (req.company or "").strip()
    position = (req.position or "").strip()
    if not company or not position:
        raise HTTPException(status_code=400, detail="company 和 position 均为必填")

    _prepare_state["running"] = True
    try:
        # preparer.prepare_interview 是同步函数内部包装了 asyncio，这里放线程池避免阻塞事件循环
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: preparer.prepare_interview(
                company=company,
                position=position,
                date=(req.date or None),
                question_count=req.count,
            ),
        )

        # 刷新题库索引，使预测题立刻能被模拟面试检索
        try:
            question_bank.load()
        except Exception as e:
            logger.warning(f"刷新 question_bank 失败: {e}")

        return {
            "status": "ok",
            "message": f"生成完成：共 {result.question_count} 题",
            "company": result.company,
            "position": result.position,
            "date": result.date,
            "output_file": result.output_file,
            "output_filename": Path(result.output_file).name,
            "question_count": result.question_count,
            "jd_snippet_count": result.jd_snippet_count,
            "jd_source_count": result.jd_source_count,
            "elapsed_sec": round(result.elapsed_sec, 2),
            "hint": "已自动纳入模拟面试检索，可直接搜索复习",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"岗位预测执行失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"岗位预测失败: {str(e)}")
    finally:
        _prepare_state["running"] = False


@router.get("/list")
async def list_prepared():
    """列出已生成的岗位预测文件。"""
    prep_dir = Path(config.INTERVIEW_REPO_PATH) / config.PREP_OUTPUT_DIR
    if not prep_dir.exists():
        return {"status": "ok", "items": [], "dir": str(prep_dir)}

    items = []
    for f in sorted(prep_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        if f.name.startswith("_"):
            continue
        try:
            stat = f.stat()
            items.append({
                "filename": f.name,
                "size": stat.st_size,
                "modified_at": stat.st_mtime,
            })
        except Exception:
            continue

    return {"status": "ok", "items": items, "dir": str(prep_dir), "count": len(items)}
