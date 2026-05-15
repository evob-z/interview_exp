"""同步触发 API - 触发全流程同步（detect → extract → archive → review）"""
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

import config
import detector
import extractor
import archiver
import reviewer
from logger import get_logger

logger = get_logger("api.sync")

router = APIRouter()

# 简单的同步状态跟踪
_sync_state = {
    "running": False,
    "last_run": None,
    "last_result": None,
}


def _get_source_label(file_path: str) -> str:
    """从文件名构造来源标签"""
    return Path(file_path).stem


def _parse_structured_questions(file_path: str) -> list[dict]:
    """从已结构化的面经文件中解析问题列表"""
    path = Path(file_path)
    if not path.exists():
        return []

    content = path.read_text(encoding="utf-8")
    questions = []

    # Q{N} 格式
    q_pattern = re.compile(r"^#{2,4}\s*Q(\d+)[：:]\s*(.+)", re.MULTILINE)
    matches = q_pattern.findall(content)
    if matches:
        for q_id, q_text in matches:
            questions.append({
                "id": int(q_id),
                "text": q_text.strip(),
                "category_suggestion": "八股",
            })
        return questions

    # 编号列表
    num_pattern = re.compile(r"^\s*(\d+)[\.\、\)]\s*(.+)", re.MULTILINE)
    matches = num_pattern.findall(content)
    if matches:
        for q_id, q_text in matches:
            text = q_text.strip()
            if len(text) > 5:
                questions.append({
                    "id": int(q_id),
                    "text": text,
                    "category_suggestion": "八股",
                })

    return questions


@router.post("/run")
async def trigger_sync(dry_run: bool = False):
    """
    触发全流程同步：detect → extract → archive → review

    Args:
        dry_run: 仅预览，不实际执行归档和复盘
    """
    global _sync_state

    if _sync_state["running"]:
        raise HTTPException(status_code=409, detail="同步正在进行中，请稍后再试")

    _sync_state["running"] = True

    try:
        repo_path = str(config.INTERVIEW_REPO_PATH)
        review_output_path = Path(repo_path) / config.REVIEW_OUTPUT_DIR
        review_output_path.mkdir(parents=True, exist_ok=True)

        # 1. 检测变更
        detection = detector.detect_changes()

        if not detection.has_changes:
            result = {
                "status": "no_changes",
                "message": "没有检测到需要处理的变更",
            }
            _sync_state["last_run"] = datetime.now().isoformat(timespec="seconds")
            _sync_state["last_result"] = result
            return result

        all_new_files = detection.new_raw_inputs + detection.new_interviews
        processed_files = []

        if dry_run:
            # 预览模式：仅列出待处理文件
            result = {
                "status": "dry_run",
                "message": f"发现 {len(all_new_files)} 个待处理文件（预览模式）",
                "summary": detection.summary(),
                "pending_files": [Path(f).name for f in all_new_files],
            }
            _sync_state["last_run"] = datetime.now().isoformat(timespec="seconds")
            _sync_state["last_result"] = result
            return result

        # 2. 对每个文件执行 extract → archive → review
        total_questions = 0
        updated_banks: set[str] = set()
        review_files: list[str] = []
        errors: list[str] = []

        for file_path in all_new_files:
            filename = Path(file_path).name
            file_result = {"file": filename, "steps": []}

            # a. 抽取
            questions_data = []
            source_label = _get_source_label(file_path)
            extracted_meta = None

            try:
                extraction = extractor.extract_questions(file_path)
                if extraction:
                    date_str = ""
                    date_match = re.search(r"(\d{6})", Path(file_path).stem)
                    if date_match:
                        date_str = date_match.group(1)

                    source_label = (
                        f"{extraction.company}_{extraction.company_type}_"
                        f"{date_str}_{extraction.round}"
                        if date_str
                        else f"{extraction.company}_{extraction.company_type}_{extraction.round}"
                    )
                    extracted_meta = {
                        "company": extraction.company,
                        "company_type": extraction.company_type,
                        "round": extraction.round,
                        "date": date_str,
                    }
                    questions_data = [
                        {
                            "id": q.id,
                            "text": q.text,
                            "category_suggestion": q.category_suggestion,
                        }
                        for q in extraction.questions
                    ]
                    file_result["steps"].append(
                        f"抽取成功: {len(extraction.questions)} 个问题"
                    )
                else:
                    questions_data = _parse_structured_questions(file_path)
                    if questions_data:
                        file_result["steps"].append(
                            f"解析已有问题: {len(questions_data)} 个"
                        )
                    else:
                        file_result["steps"].append("无法解析出问题，跳过")
            except Exception as e:
                file_result["steps"].append(f"抽取失败: {str(e)}")
                errors.append(f"{filename}: 抽取失败 - {str(e)}")

            # b. 归档
            if questions_data:
                try:
                    archive_result = archiver.archive_questions(
                        questions_data, source_label
                    )
                    archived_count = len(archive_result.archived_questions)
                    skipped_count = len(archive_result.skipped_duplicates)
                    total_questions += archived_count

                    for aq in archive_result.archived_questions:
                        updated_banks.add(aq["target_file"])

                    file_result["steps"].append(
                        f"归档完成: +{archived_count} 新增, {skipped_count} 跳过(重复)"
                    )
                except Exception as e:
                    file_result["steps"].append(f"归档失败: {str(e)}")
                    errors.append(f"{filename}: 归档失败 - {str(e)}")

            # c. 复盘
            try:
                review_result = reviewer.generate_review_file(
                    source_file=file_path,
                    extracted_data=extracted_meta,
                    output_dir=str(review_output_path),
                )
                review_files.append(Path(review_result.output_file).name)
                file_result["steps"].append(
                    f"复盘完成: {Path(review_result.output_file).name}"
                )
            except Exception as e:
                file_result["steps"].append(f"复盘失败: {str(e)}")
                errors.append(f"{filename}: 复盘失败 - {str(e)}")

            processed_files.append(file_result)

        # 3. 更新同步时间
        detector.update_last_sync_time()

        result = {
            "status": "ok",
            "message": f"同步完成: 处理 {len(all_new_files)} 个文件",
            "summary": {
                "processed_files": len(all_new_files),
                "total_new_questions": total_questions,
                "updated_banks": list(updated_banks),
                "review_files": review_files,
                "errors": errors,
            },
            "details": processed_files,
        }

        _sync_state["last_run"] = datetime.now().isoformat(timespec="seconds")
        _sync_state["last_result"] = result
        return result

    except Exception as e:
        logger.error(f"同步执行失败: {e}")
        raise HTTPException(status_code=500, detail=f"同步执行失败: {str(e)}")
    finally:
        _sync_state["running"] = False


class PipelineRequest(BaseModel):
    filename: Optional[str] = None


@router.post("/session-pipeline/{session_id}")
async def session_pipeline(session_id: str, req: PipelineRequest = PipelineRequest()):
    """
    会话一条龙处理：导出 → 复盘 → 入库
    复用现有工具链
    """
    from exporter import export_session_questions

    results = {"steps": []}

    # Step 1: 导出（含 LLM 改写）
    try:
        output_path, count = export_session_questions(session_id, filename=req.filename, rewrite=True)
        results["steps"].append({"step": "extract", "status": "ok", "file": str(output_path.name), "count": count})
    except Exception as e:
        results["steps"].append({"step": "extract", "status": "error", "error": str(e)})
        results["status"] = "partial"
        return results

    output_path_str = str(output_path)

    # Step 2: 复盘
    try:
        valid, error_msg = reviewer.validate_review_input(output_path_str)
        if valid:
            review_output_dir = Path(str(config.INTERVIEW_REPO_PATH)) / config.REVIEW_OUTPUT_DIR
            review_output_dir.mkdir(parents=True, exist_ok=True)
            review_result = reviewer.generate_review_file(
                source_file=output_path_str,
                output_dir=str(review_output_dir),
            )
            results["steps"].append({
                "step": "review", "status": "ok",
                "file": str(Path(review_result.output_file).name),
                "top_concerns": review_result.top_concerns[:3] if review_result.top_concerns else []
            })
        else:
            results["steps"].append({"step": "review", "status": "skipped", "reason": error_msg})
    except Exception as e:
        results["steps"].append({"step": "review", "status": "error", "error": str(e)})

    # Step 3: 入库
    try:
        valid, error_msg = archiver.validate_archive_input(output_path_str)
        if valid:
            questions_data = _parse_structured_questions(output_path_str)
            if questions_data:
                source_label = Path(output_path_str).stem
                archive_result = archiver.archive_questions(questions_data, source_label)
                results["steps"].append({
                    "step": "archive", "status": "ok",
                    "archived_count": len(archive_result.archived_questions),
                    "skipped_count": len(archive_result.skipped_duplicates),
                })
            else:
                results["steps"].append({"step": "archive", "status": "skipped", "reason": "无法解析出问题"})
        else:
            results["steps"].append({"step": "archive", "status": "skipped", "reason": error_msg})
    except Exception as e:
        results["steps"].append({"step": "archive", "status": "error", "error": str(e)})

    results["status"] = "ok"
    return results


@router.get("/status")
async def get_sync_status():
    """获取同步状态（上次同步时间、待处理文件等）"""
    try:
        # 上次同步时间
        last_sync_time = detector.get_last_sync_time()

        # 当前待处理文件
        detection = detector.detect_changes()
        pending_files = []
        if detection.new_raw_inputs:
            for f in detection.new_raw_inputs:
                pending_files.append({"file": Path(f).name, "type": "原始问题"})
        if detection.new_interviews:
            for f in detection.new_interviews:
                pending_files.append({"file": Path(f).name, "type": "根目录面试记录"})

        return {
            "status": "ok",
            "running": _sync_state["running"],
            "last_sync_time": last_sync_time or _sync_state.get("last_run"),
            "pending_files": pending_files,
            "pending_count": len(pending_files),
            "has_changes": detection.has_changes,
            "change_summary": detection.summary(),
        }
    except Exception as e:
        logger.error(f"获取同步状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取同步状态失败: {str(e)}")
