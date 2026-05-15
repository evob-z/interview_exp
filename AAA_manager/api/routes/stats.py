"""统计信息 API - 题库、面试、投递等综合统计"""
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException

import config
from api.deps import question_bank, excel_reader
from detector import get_last_sync_time
from logger import get_logger

logger = get_logger("api.stats")

router = APIRouter()


def _count_interview_files() -> list[dict]:
    """扫描面试记录文件，统计面试次数和最近面试信息"""
    repo_path = Path(str(config.INTERVIEW_REPO_PATH))
    interviews: list[dict] = []

    # 匹配 {公司}_{类型}_{YYMMDD}_{场次}.md 格式
    pattern = re.compile(r"^(.+?)_(.+?)_(\d{6})_(.+?)\.md$")

    # 搜索根目录
    for md_file in repo_path.glob("*.md"):
        match = pattern.match(md_file.name)
        if match:
            interviews.append({
                "company": match.group(1),
                "company_type": match.group(2),
                "date": match.group(3),
                "round": match.group(4),
                "file": md_file.name,
            })

    # 搜索 面试原始问题/ 目录
    raw_input_path = repo_path / config.RAW_INPUT_DIR
    if raw_input_path.is_dir():
        for md_file in raw_input_path.glob("*.md"):
            match = pattern.match(md_file.name)
            if match:
                interviews.append({
                    "company": match.group(1),
                    "company_type": match.group(2),
                    "date": match.group(3),
                    "round": match.group(4),
                    "file": md_file.name,
                })

    # 搜索 面试复盘/ 目录
    review_path = repo_path / config.REVIEW_OUTPUT_DIR
    if review_path.is_dir():
        for md_file in review_path.glob("*.md"):
            match = pattern.match(md_file.name)
            if match:
                # 避免重复：检查是否已在列表中
                existing = any(
                    i["company"] == match.group(1) and i["date"] == match.group(3)
                    for i in interviews
                )
                if not existing:
                    interviews.append({
                        "company": match.group(1),
                        "company_type": match.group(2),
                        "date": match.group(3),
                        "round": match.group(4),
                        "file": md_file.name,
                    })

    # 按日期降序排序
    interviews.sort(key=lambda x: x["date"], reverse=True)
    return interviews


@router.get("")
async def get_stats():
    """获取总统计信息"""
    try:
        # 1. 题库统计
        qb_stats = question_bank.get_stats()

        # 2. 面试记录统计
        interviews = _count_interview_files()
        unique_companies = list({i["company"] for i in interviews})

        # 3. 投递情况
        excel_stats = {}
        try:
            excel_stats = excel_reader.get_stats()
        except Exception as e:
            logger.debug(f"读取投递统计失败: {e}")

        # 4. 最近面试
        recent_interviews = interviews[:5]

        # 5. 上次同步时间
        last_sync = get_last_sync_time()

        return {
            "status": "ok",
            "question_bank": {
                "total_questions": qb_stats.get("total", 0),
                "categories": qb_stats.get("categories", {}),
                "category_count": qb_stats.get("category_count", 0),
                "last_modified": qb_stats.get("last_modified"),
            },
            "interviews": {
                "total_count": len(interviews),
                "unique_companies": len(unique_companies),
                "companies": unique_companies,
                "recent": recent_interviews,
            },
            "applications": {
                "total": excel_stats.get("total", 0),
                "status_counts": excel_stats.get("status_counts", {}),
                "file_exists": excel_stats.get("file_exists", False),
            },
            "last_sync_time": last_sync,
        }
    except Exception as e:
        logger.error(f"获取统计信息失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")
