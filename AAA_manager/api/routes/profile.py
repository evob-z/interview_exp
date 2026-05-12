"""用户画像 API - 查看画像、获取建议和鼓励"""
from fastapi import APIRouter, HTTPException

from api.deps import profile_manager, resume_reader, excel_reader, question_bank
from logger import get_logger

logger = get_logger("api.profile")

router = APIRouter()


@router.get("")
async def get_profile():
    """获取完整用户画像"""
    try:
        profile_manager.load()
        profile = profile_manager.profile
        if not profile:
            return {"status": "empty", "message": "画像尚未初始化", "data": {}}
        return {"status": "ok", "data": profile}
    except Exception as e:
        logger.error(f"获取画像失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取画像失败: {str(e)}")


@router.get("/summary")
async def get_profile_summary():
    """获取画像摘要（包含 LLM 概括）"""
    try:
        brief = profile_manager.get_brief_overview()
        strengths = profile_manager.get_strengths()
        weaknesses = profile_manager.get_weaknesses()
        frequently_asked = profile_manager.get_frequently_asked()
        return {
            "status": "ok",
            "brief": brief,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "frequently_asked": frequently_asked,
        }
    except Exception as e:
        logger.error(f"获取画像摘要失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取画像摘要失败: {str(e)}")


@router.get("/advice")
async def get_advice():
    """获取改进建议"""
    try:
        advice = profile_manager.generate_advice()
        return {"status": "ok", "advice": advice}
    except Exception as e:
        logger.error(f"获取建议失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取建议失败: {str(e)}")


@router.get("/encouragement")
async def get_encouragement():
    """获取鼓励话语"""
    try:
        encouragement = profile_manager.generate_encouragement()
        return {"status": "ok", "encouragement": encouragement}
    except Exception as e:
        logger.error(f"获取鼓励失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取鼓励失败: {str(e)}")


@router.post("/initialize")
async def initialize_profile():
    """初始化/重建用户画像 - 从简历、面试记录、投递情况综合构建"""
    try:
        # 1. 读取简历
        resume_info = resume_reader.get_resume_info()
        resume_text = resume_info.get("raw_text", "")

        # 2. 收集面试记录（从问题库统计）
        interview_records: list[dict] = []
        try:
            # 从问题库中提取面试来源信息
            for q in question_bank.questions:
                source = q.get("source", "")
                if source and "_" in source:
                    parts = source.split(" ")[0].split("_")
                    if len(parts) >= 3:
                        company = parts[0]
                        # 避免重复
                        if not any(r["company"] == company for r in interview_records):
                            interview_records.append({
                                "company": company,
                                "company_type": parts[1] if len(parts) > 1 else "",
                                "date": parts[2] if len(parts) > 2 else "",
                                "round": parts[3] if len(parts) > 3 else "",
                                "questions": [
                                    {"question": qq["text"], "category": qq["category"]}
                                    for qq in question_bank.questions
                                    if qq.get("source", "").startswith(company)
                                ],
                            })
        except Exception as e:
            logger.warning(f"从问题库收集面试记录失败: {e}")

        # 3. 读取投递情况
        excel_data = None
        try:
            excel_data = excel_reader.read()
        except Exception as e:
            logger.warning(f"读取投递情况失败: {e}")

        # 4. 初始化画像
        profile = profile_manager.initialize(
            resume_text=resume_text,
            interview_records=interview_records,
            excel_data=excel_data,
        )

        return {
            "status": "ok",
            "message": "画像初始化完成",
            "data": profile,
        }
    except Exception as e:
        logger.error(f"初始化画像失败: {e}")
        raise HTTPException(status_code=500, detail=f"初始化画像失败: {str(e)}")
