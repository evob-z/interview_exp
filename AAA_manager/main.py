#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AAA_manager - 面经管理程序
统一入口，支持全流程同步和单模块独立执行。

用法:
    python main.py sync [--auto-commit] [--dry-run]
    python main.py sync <file> [--auto-commit] [--dry-run]
    python main.py sync --reflect
    python main.py sync <file> --reflect
    python main.py detect
    python main.py extract <file>
    python main.py archive <file>
    python main.py review [file]
    python main.py prepare 字节跳动_AI应用开发实习生-AI数据与安全_260512
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

# 确保可以 import 同目录模块
sys.path.insert(0, str(Path(__file__).parent))

try:
    from logger import get_logger
    from config import INTERVIEW_REPO_PATH, RAW_INPUT_DIR, REVIEW_OUTPUT_DIR, GIT_ENABLED
    import detector
    import extractor
    import archiver
    import reviewer
    import reflector
    if GIT_ENABLED:
        import git_ops
    import preparer
    import exporter
except ImportError as e:
    print(f"[错误] 模块导入失败: {e}")
    print("请确保已安装依赖: pip install -r requirements.txt")
    sys.exit(1)

logger = get_logger("main")


# ──────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────

def _resolve_file_path(file_arg: str) -> str:
    """将用户输入的文件路径解析为绝对路径"""
    p = Path(file_arg)
    if not p.is_absolute():
        # 相对路径基于仓库根目录解析
        p = INTERVIEW_REPO_PATH / p
    return str(p.resolve())


# 项目标签正则：匹配问题文本开头的 [项目名] 标签
_TAG_PATTERN = re.compile(r"^\[([^\]]+)\]\s*")


def _extract_category_from_tag(text: str) -> tuple[str, str]:
    """从问题文本中提取 [项目名] 标签，返回 (category, clean_text)"""
    match = _TAG_PATTERN.match(text)
    if not match:
        return "八股", text

    tag = match.group(1)
    clean_text = text[match.end():].strip()

    category = tag.split("/")[0].strip()
    return category, clean_text


def _parse_structured_questions(file_path: str) -> list[dict]:
    """
    从已结构化的面经文件中解析问题列表（当 extract 返回 None 时使用）。
    支持格式：
    - 数字编号列表: 1. 问题内容
    - Q编号格式: ## Q1：问题内容

    如果问题文本以 [项目名] 标签开头，则提取标签作为分类依据，
    并将标签从归档文本中移除。
    """
    import re
    path = Path(file_path)
    if not path.exists():
        return []

    content = path.read_text(encoding="utf-8")
    questions = []

    # 尝试匹配 Q{N} 格式
    q_pattern = re.compile(r"^#{2,4}\s*Q(\d+)[：:]\s*(.+)", re.MULTILINE)
    matches = q_pattern.findall(content)
    if matches:
        for q_id, q_text in matches:
            raw_text = q_text.strip()
            category, clean_text = _extract_category_from_tag(raw_text)
            questions.append({
                "id": int(q_id),
                "text": clean_text,
                "category_suggestion": category,
            })
        return questions

    # 尝试匹配编号列表
    num_pattern = re.compile(r"^\s*(\d+)[\.\.\、\)]\s*(.+)", re.MULTILINE)
    matches = num_pattern.findall(content)
    if matches:
        for q_id, q_text in matches:
            raw_text = q_text.strip()
            if len(raw_text) > 5:  # 过滤过短的项
                category, clean_text = _extract_category_from_tag(raw_text)
                questions.append({
                    "id": int(q_id),
                    "text": clean_text,
                    "category_suggestion": category,
                })
        return questions

    return questions


def _get_source_label_from_filename(file_path: str) -> str:
    """从文件名构造来源标签"""
    stem = Path(file_path).stem
    return stem


# ──────────────────────────────────────────────
# 子命令处理函数
# ──────────────────────────────────────────────

def cmd_sync(args):
    """
    全流程同步:
    1. 指定文件模式（args.file 非空）或检测变更模式（扫描 面试原始问题/）
    2. 对每个新文件:
       a. extract - 抽取问题（如果需要）
       b. [--reflect] 反思交互
       c. archive - 归档入问题库
       d. review - 生成独立复盘文件到 面试复盘/
    3. commit - 提交所有变更（如果 --auto-commit）
    """
    logger.info("=== 面经同步 ===")

    # 确保输出目录存在
    review_output_path = Path(INTERVIEW_REPO_PATH) / REVIEW_OUTPUT_DIR
    review_output_path.mkdir(parents=True, exist_ok=True)
    raw_input_path = Path(INTERVIEW_REPO_PATH) / RAW_INPUT_DIR
    raw_input_path.mkdir(parents=True, exist_ok=True)

    # 1. 检测变更（或使用指定文件）
    single_file_mode = bool(args.file)
    if single_file_mode:
        file_path = _resolve_file_path(args.file)
        if not Path(file_path).exists():
            logger.error(f"[错误] 文件不存在: {file_path}")
            return
        logger.info(f"[指定文件] {Path(file_path).name}")
        all_new_files = [file_path]
    else:
        result = detector.detect_changes()
        if not result.has_changes:
            logger.info("[检测] 无需同步，没有发现变更")
            logger.info("=== 完成 ===")
            return

        logger.info(f"[检测] {result.summary()}")
        if result.new_raw_inputs:
            logger.info("  原始问题新文件:")
            for f in result.new_raw_inputs:
                logger.info(f"    - {Path(f).name}")
        if result.new_interviews:
            logger.info("  根目录面试记录（兼容模式）:")
            for f in result.new_interviews:
                logger.info(f"    - {Path(f).name}")

        # 合并待处理文件列表：优先 new_raw_inputs，再 new_interviews
        all_new_files = result.new_raw_inputs + result.new_interviews

    # 跟踪所有变更文件（用于 auto-commit）
    changed_files: list[str] = []
    # 跟踪归档摘要（用于 commit message）
    sync_summary = {
        "archived_files": [],
        "question_count": 0,
        "updated_banks": set(),
        "reviewed": False,
        "review_files": [],
    }

    # 2. 处理每个新面试记录
    for interview_file in all_new_files:
        filename = Path(interview_file).name
        is_raw_input = (
            interview_file in result.new_raw_inputs
            if not single_file_mode else
            str(Path(INTERVIEW_REPO_PATH) / RAW_INPUT_DIR) in str(Path(interview_file).parent.resolve())
        )
        logger.info(f"--- 处理: {filename} {'(原始问题)' if is_raw_input else '(根目录)'} ---")

        # 对根目录文件执行文件名规范化（原始问题目录文件不强制规范化）
        if not is_raw_input:
            normalized_path = archiver.normalize_filename(interview_file)
            if normalized_path != interview_file:
                logger.info(f"[重命名] {filename} → {Path(normalized_path).name}")
                interview_file = normalized_path
                filename = Path(interview_file).name

        changed_files.append(interview_file)

        # a. 抽取问题
        questions_data = []
        source_label = _get_source_label_from_filename(interview_file)
        extracted_meta = None  # 用于传给 reviewer 推断文件名

        try:
            extraction = extractor.extract_questions(interview_file)
            if extraction:
                logger.info(f"[抽取] 从 {filename} 抽取 {len(extraction.questions)} 个问题")
                # 尝试从文件名解析日期
                date_str = ""
                date_match = re.search(r"(\d{6})", Path(interview_file).stem)
                if date_match:
                    date_str = date_match.group(1)

                source_label = f"{extraction.company}_{extraction.company_type}_{date_str}_{extraction.round}" if date_str else f"{extraction.company}_{extraction.company_type}_{extraction.round}"
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
            else:
                # 文件已结构化，尝试直接解析
                questions_data = _parse_structured_questions(interview_file)
                if questions_data:
                    logger.info(f"[解析] 从 {filename} 解析 {len(questions_data)} 个已有问题")
                else:
                    logger.info(f"[跳过] {filename} 无法解析出问题")
        except Exception as e:
            logger.error(f"抽取阶段出错: {e}", exc_info=True)

        # b. 反思交互（--reflect 模式）
        refl = None
        enhanced_ctx = None
        if hasattr(args, 'reflect') and args.reflect and questions_data:
            logger.info("[反思] 启动面试反思对话...")
            try:
                refl = reflector.reflect_interview(interview_file)
                enhanced_ctx = refl.enhanced_review_context if refl else None
                if refl and refl.review_content:
                    logger.info("[反思] 反思完成，复盘报告将融入实际回答表现")
            except Exception as e:
                logger.warning(f"反思失败，回退原流程: {e}")
                enhanced_ctx = None

        # c. 归档入问题库（--reflect 模式下移到复盘之后，此处为非 reflect 模式）
        if questions_data and not (hasattr(args, 'reflect') and args.reflect):
            try:
                archive_result = archiver.archive_questions(questions_data, source_label)
                if archive_result.archived_questions:
                    # 按目标文件分组统计
                    by_file = defaultdict(list)
                    for aq in archive_result.archived_questions:
                        by_file[aq["target_file"]].append(aq["question_id"])

                    logger.info("[归档] 归档完成：")
                    for target_file, q_ids in by_file.items():
                        id_range = f"{q_ids[0]}-{q_ids[-1]}" if len(q_ids) > 1 else q_ids[0]
                        logger.info(f"  - {target_file}: +{len(q_ids)} 题 ({id_range})")
                        sync_summary["updated_banks"].add(target_file)
                        # 记录变更的问题库文件
                        bank_path = str(Path(INTERVIEW_REPO_PATH) / "问题库" / target_file)
                        changed_files.append(bank_path)

                    sync_summary["archived_files"].append(filename)
                    sync_summary["question_count"] += len(archive_result.archived_questions)

                if archive_result.skipped_duplicates:
                    logger.info(f"  [去重] 跳过 {len(archive_result.skipped_duplicates)} 个重复问题")
            except Exception as e:
                logger.error(f"归档阶段出错: {e}", exc_info=True)

        # d. 生成独立复盘文件到 面试复盘/（可能带反思上下文）
        try:
            review_result = reviewer.generate_review_file(
                source_file=interview_file,
                extracted_data=extracted_meta,
                output_dir=str(review_output_path),
                reflection_context=enhanced_ctx,
            )
            logger.info(f"[复盘] 独立复盘文件已生成: {Path(review_result.output_file).name}")
            if review_result.top_concerns:
                logger.info(f"  面试官最关注: {', '.join(review_result.top_concerns[:3])}")
            sync_summary["reviewed"] = True
            sync_summary["review_files"].append(Path(review_result.output_file).name)
            changed_files.append(review_result.output_file)
        except Exception as e:
            logger.error(f"复盘阶段出错: {e}", exc_info=True)

        # e. 归档入问题库（--reflect 模式下，复盘之后再入库）
        if questions_data and hasattr(args, 'reflect') and args.reflect:
            try:
                archive_result = archiver.archive_questions(questions_data, source_label)
                if archive_result.archived_questions:
                    by_file = defaultdict(list)
                    for aq in archive_result.archived_questions:
                        by_file[aq["target_file"]].append(aq["question_id"])

                    logger.info("[归档] 归档完成：")
                    for target_file, q_ids in by_file.items():
                        id_range = f"{q_ids[0]}-{q_ids[-1]}" if len(q_ids) > 1 else q_ids[0]
                        logger.info(f"  - {target_file}: +{len(q_ids)} 题 ({id_range})")
                        sync_summary["updated_banks"].add(target_file)
                        bank_path = str(Path(INTERVIEW_REPO_PATH) / "问题库" / target_file)
                        changed_files.append(bank_path)

                    sync_summary["archived_files"].append(filename)
                    sync_summary["question_count"] += len(archive_result.archived_questions)

                if archive_result.skipped_duplicates:
                    logger.info(f"  [去重] 跳过 {len(archive_result.skipped_duplicates)} 个重复问题")
            except Exception as e:
                logger.error(f"归档阶段出错: {e}", exc_info=True)

        # f. 反思成功后更新画像
        if refl and refl.review_content:
            try:
                from profile.profile_manager import ProfileManager

                profile_path = str(Path(__file__).parent / "data" / "user_profile.json")
                pm = ProfileManager(profile_path)
                pm.load()

                questions_for_profile = [
                    {"question": q["text"], "category": q.get("category_suggestion", "八股")}
                    for q in questions_data
                ]

                refl_meta = reflector._parse_interview_meta(interview_file)
                pm.update_after_interview(
                    company=refl_meta["company"],
                    questions=questions_for_profile,
                    review_content=refl.review_content,
                )
                logger.info("[反思] 用户画像已更新")
            except Exception as e:
                logger.warning(f"更新画像失败: {e}")

    # 3. 更新同步时间
    detector.update_last_sync_time()

    # 4. 提交变更（如果 --auto-commit）
    if hasattr(args, 'auto_commit') and args.auto_commit:
        repo_path = str(INTERVIEW_REPO_PATH)
        # 去重
        changed_files = list(set(changed_files))

        # 生成 commit message
        commit_summary = {
            "archived_files": sync_summary["archived_files"],
            "question_count": sync_summary["question_count"],
            "updated_banks": list(sync_summary["updated_banks"]),
            "reviewed": sync_summary["reviewed"],
        }
        message = git_ops.generate_commit_message(commit_summary)

        # stage 和 commit
        git_ops.stage_files(repo_path, changed_files)
        success = git_ops.commit_changes(repo_path, message, dry_run=args.dry_run)

        if args.dry_run:
            print(f"[提交] [DRY-RUN] {message}")
        elif success:
            print(f"[提交] {message}")
        else:
            print("[提交] 提交失败或暂存区无更改")

    # 最终摘要
    logger.info("=== 完成 ===")


def cmd_detect(args):
    """仅检测并输出变更报告"""
    print("\n=== 变更检测 ===")

    result = detector.detect_changes()

    if not result.has_changes:
        print("未检测到任何变更")
        print("=== 完成 ===\n")
        return

    print(f"检测结果: {result.summary()}\n")

    if result.new_raw_inputs:
        print(f"📝 原始问题新文件 ({len(result.new_raw_inputs)}):")
        for f in result.new_raw_inputs:
            print(f"  - {Path(f).name}")

    if result.new_interviews:
        print(f"📝 新面试记录 ({len(result.new_interviews)}):")
        for f in result.new_interviews:
            print(f"  - {Path(f).name}")

    if result.modified_questions:
        print(f"\n📚 问题库变更 ({len(result.modified_questions)}):")
        for f in result.modified_questions:
            print(f"  - {Path(f).name}")

    if result.modified_docs:
        print(f"\n📄 文档变更 ({len(result.modified_docs)}):")
        for f in result.modified_docs:
            print(f"  - {Path(f).name}")

    if result.untracked_files:
        print(f"\n❓ 未追踪文件 ({len(result.untracked_files)}):")
        for f in result.untracked_files:
            print(f"  - {Path(f).name}")

    print("\n=== 完成 ===\n")


def cmd_extract(args):
    """对指定文件抽取问题"""
    file_path = _resolve_file_path(args.file)

    if not Path(file_path).exists():
        print(f"[错误] 文件不存在: {file_path}")
        return

    print(f"\n=== 问题抽取 ===")
    print(f"目标文件: {Path(file_path).name}\n")

    try:
        result = extractor.extract_questions(file_path)
    except Exception as e:
        print(f"[错误] 抽取失败: {e}")
        return

    if result is None:
        print("文件已是结构化格式，无需抽取。")
        # 尝试解析已有问题
        questions = _parse_structured_questions(file_path)
        if questions:
            print(f"已解析 {len(questions)} 个现有问题。")
    else:
        print(f"公司: {result.company} ({result.company_type})")
        print(f"轮次: {result.round}")
        print(f"问题数: {len(result.questions)}\n")
        print("--- 问题列表 ---")
        for q in result.questions:
            followup = " [追问]" if q.is_followup else ""
            print(f"  {q.id:2d}. [{q.category_suggestion}] {q.text}{followup}")

    print("\n=== 完成 ===\n")


def cmd_archive(args):
    """对指定文件归档入库（先 extract 再 archive）"""
    file_path = _resolve_file_path(args.file)

    if not Path(file_path).exists():
        print(f"[错误] 文件不存在: {file_path}")
        return

    print(f"\n=== 归档入库 ===")
    print(f"目标文件: {Path(file_path).name}\n")

    # 先尝试 extract
    questions_data = []
    source_label = _get_source_label_from_filename(file_path)

    try:
        extraction = extractor.extract_questions(file_path)
        if extraction:
            print(f"[抽取] 成功抽取 {len(extraction.questions)} 个问题")
            source_label = f"{extraction.company}_{extraction.company_type}_{Path(file_path).stem.split('_')[2]}_{extraction.round}"
            questions_data = [
                {
                    "id": q.id,
                    "text": q.text,
                    "category_suggestion": q.category_suggestion,
                }
                for q in extraction.questions
            ]
        else:
            # 文件已结构化，尝试解析
            questions_data = _parse_structured_questions(file_path)
            if questions_data:
                print(f"[解析] 从结构化文件解析 {len(questions_data)} 个问题")
            else:
                print("[跳过] 未能解析出任何问题，无法归档")
                return
    except Exception as e:
        print(f"[错误] 抽取阶段失败: {e}")
        return

    # 执行归档
    try:
        result = archiver.archive_questions(questions_data, source_label)
    except Exception as e:
        print(f"[错误] 归档失败: {e}")
        return

    if result.archived_questions:
        by_file = defaultdict(list)
        for aq in result.archived_questions:
            by_file[aq["target_file"]].append(aq["question_id"])

        print("\n[归档] 归档完成：")
        for target_file, q_ids in by_file.items():
            id_range = f"{q_ids[0]}-{q_ids[-1]}" if len(q_ids) > 1 else q_ids[0]
            print(f"  - {target_file}: +{len(q_ids)} 题 ({id_range})")
    else:
        print("\n[归档] 无新问题归档（可能全部为重复题）")

    if result.skipped_duplicates:
        print(f"\n[去重] 跳过 {len(result.skipped_duplicates)} 个重复问题")

    print("\n=== 完成 ===\n")


def cmd_prepare(args):
    """岗位针对性预测题生成：搜 JD → 结合简历项目 → LLM 出题 → 写入 岗位预测/"""
    # 优先使用 spec 位置参数，否则使用 --company/--position/--department/--date
    department = getattr(args, "department", "") or ""
    if getattr(args, "spec", None):
        company, position, date, spec_dept = preparer.parse_spec(args.spec)
        # --department 显式参数优先于 spec 解析出的部门
        if not department and spec_dept:
            department = spec_dept
        # 允许 --date 覆盖 spec 中的日期
        if getattr(args, "date", None):
            date = args.date
    else:
        company = getattr(args, "company", "") or ""
        position = getattr(args, "position", "") or ""
        date = getattr(args, "date", None)

    if not company or not position:
        print("[错误] 必须提供公司与岗位。示例：python main.py prepare 京东_后端开发工程师")
        print("      或：python main.py prepare --company 京东 --position 后端开发工程师 --department CHO体系")
        return

    print("\n=== 岗位预测题生成 ===")
    print(f"公司: {company}")
    print(f"岗位: {position}")
    if department:
        print(f"部门: {department}")
    print(f"日期: {date or '今天'}")

    try:
        result = preparer.prepare_interview(
            company=company,
            position=position,
            date=date,
            department=department,
            question_count=getattr(args, "count", None),
        )
    except Exception as e:
        logger.error(f"岗位预测失败: {e}", exc_info=True)
        print(f"[错误] {e}")
        return

    print(f"\n[完成] 生成 {result.question_count} 题")
    print(f"  文件: {result.output_file}")
    print(f"  JD 片段: {result.jd_snippet_count} 条，来源 URL: {result.jd_source_count} 个")
    print(f"  耗时: {result.elapsed_sec:.1f}s")
    print("  💡 提示: 该题库已自动被模拟面试检索纳入，可直接在 Web 端搜索复习")
    print("\n=== 完成 ===\n")


def cmd_review(args):
    """复盘指定/最新面经"""
    if args.file:
        file_path = _resolve_file_path(args.file)
    else:
        file_path = reviewer.find_latest_interview()

    if not file_path:
        print("[错误] 未找到面经文件")
        return

    if not Path(file_path).exists():
        print(f"[错误] 文件不存在: {file_path}")
        return

    print(f"\n=== 复盘分析 ===")
    print(f"目标文件: {Path(file_path).name}\n")

    try:
        if args.standalone:
            # 独立文件模式：输出到 面试复盘/
            review_output_path = Path(INTERVIEW_REPO_PATH) / REVIEW_OUTPUT_DIR
            review_output_path.mkdir(parents=True, exist_ok=True)
            result = reviewer.generate_review_file(
                source_file=file_path,
                output_dir=str(review_output_path),
            )
            print(f"分析问题数: {result.question_count}")
            if result.top_concerns:
                print(f"面试官最关注:")
                for i, concern in enumerate(result.top_concerns, 1):
                    print(f"  {i}. {concern}")
            print(f"\n独立复盘文件已生成: {Path(result.output_file).name}")
        else:
            # 追加模式（向后兼容）
            result = reviewer.review_interview(file_path)
            print(f"分析问题数: {result.question_count}")
            if result.top_concerns:
                print(f"面试官最关注:")
                for i, concern in enumerate(result.top_concerns, 1):
                    print(f"  {i}. {concern}")
            print(f"\n复盘报告已追加到原文件: {Path(result.source_file).name}")
    except Exception as e:
        print(f"[错误] 复盘失败: {e}")
        return

    print("\n=== 完成 ===\n")


def cmd_export_session(args):
    """从模拟面试会话中导出原始问题列表"""
    print(f"\n=== 会话问题导出 ===")
    print(f"会话ID: {args.session_id}")

    try:
        output_path, count = exporter.export_session_questions(
            session_id=args.session_id,
            filename=args.name,
            rewrite=args.rewrite,
        )
    except FileNotFoundError as e:
        print(f"[错误] {e}")
        return
    except ValueError as e:
        print(f"[错误] {e}")
        return
    except Exception as e:
        logger.error(f"导出失败: {e}", exc_info=True)
        print(f"[错误] 导出失败: {e}")
        return

    print(f"\n[完成] 导出 {count} 个面试问题")
    print(f"  文件: {output_path}")
    print("\n=== 完成 ===\n")


def cmd_reflect(args):
    """面试反思：LLM 询问实际回答表现，分析后更新画像"""
    file_path = _resolve_file_path(args.file)

    if not Path(file_path).exists():
        print(f"[错误] 文件不存在: {file_path}")
        return

    print(f"\n=== 面试反思 ===")
    print(f"目标文件: {Path(file_path).name}")

    # 加载 LLM 客户端
    llm = None
    try:
        import llm_client
        llm = llm_client
    except Exception as e:
        logger.warning(f"LLM 客户端加载失败，将使用默认问题: {e}")

    try:
        result = reflector.reflect_interview(file_path, llm_client=llm)
    except (FileNotFoundError, ValueError) as e:
        print(f"[错误] {e}")
        return
    except KeyboardInterrupt:
        print("\n\n[中断] 用户取消操作")
        return
    except Exception as e:
        logger.error(f"反思流程出错: {e}", exc_info=True)
        print(f"[错误] {e}")
        return

    # 打印分析报告
    reflector.print_reflection_report(result)
    print("\n=== 完成 ===\n")


# ──────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="面经管理程序 - AAA_manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py sync --auto-commit       全流程同步并自动提交
  python main.py sync --dry-run           预览模式（不实际提交）
  python main.py detect                   仅检测变更
  python main.py extract 蚂蚁_大厂_260423_一面技术.md
  python main.py archive 蚂蚁_大厂_260423_一面技术.md
  python main.py review                   复盘最新面经
  python main.py prepare 字节跳动_AI应用开发实习生_260512   岗位预测出题
  python main.py prepare 京东_CHO体系-企业信息化部_后端开发工程师   带部门
  python main.py reflect 字节跳动_大厂_260513_技术一面.md   面试反思
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # sync 子命令
    sync_parser = subparsers.add_parser("sync", help="全流程同步")
    sync_parser.add_argument(
        "file", nargs="?", default=None,
        help="可选：指定面经文件路径（不指定则自动检测 面试原始问题/ 下新增文件）"
    )
    sync_parser.add_argument(
        "--auto-commit", action="store_true", help="自动提交所有变更到 Git"
    ) if GIT_ENABLED else None
    sync_parser.add_argument(
        "--dry-run", action="store_true", help="仅预览不实际执行提交"
    )
    sync_parser.add_argument(
        "--reflect", action="store_true",
        help="在复盘前启动反思对话，收集实际回答表现（抽题→反思→复盘→入库）"
    )

    # detect 子命令
    subparsers.add_parser("detect", help="检测仓库变更")

    # extract 子命令
    extract_parser = subparsers.add_parser("extract", help="从面经文件抽取问题")
    extract_parser.add_argument("file", help="目标面经文件路径")

    # archive 子命令
    archive_parser = subparsers.add_parser("archive", help="归档问题到问题库")
    archive_parser.add_argument("file", help="目标面经文件路径")

    # review 子命令
    review_parser = subparsers.add_parser("review", help="生成复盘分析报告")
    review_parser.add_argument(
        "file", nargs="?", default=None, help="目标面经文件（默认使用最新面经）"
    )
    review_parser.add_argument(
        "--standalone", action="store_true",
        help="生成独立复盘文件到 面试复盘/ 目录（默认追加到原文件）"
    )

    # export-session 子命令
    export_parser = subparsers.add_parser(
        "export-session", help="从模拟面试会话中导出原始问题列表"
    )
    export_parser.add_argument("session_id", help="会话ID（8位hex）")
    export_parser.add_argument(
        "--name", default=None, help="输出文件名（不含.md），默认 模拟面试_{YYMMDD}"
    )
    export_parser.add_argument(
        "--rewrite", action="store_true",
        help="调用 LLM 改写问题（使其自包含、归属项目、便于复习）"
    )

    # prepare 子命令
    prepare_parser = subparsers.add_parser(
        "prepare", help="岗位针对性预测题生成（写入 岗位预测/，自动被模拟面试检索）"
    )
    prepare_parser.add_argument(
        "spec", nargs="?", default=None,
        help="简写格式：公司_[部门_...]岗位_[YYMMDD]（日期可省略，部门可选）"
    )
    prepare_parser.add_argument("--company", help="公司名（与 spec 二选一）")
    prepare_parser.add_argument("--position", help="岗位名")
    prepare_parser.add_argument("--department", help="部门/团队名（可选）")
    prepare_parser.add_argument("--date", help="面试日期 YYMMDD，默认今天")
    prepare_parser.add_argument("--count", type=int, default=None, help="期望题数（默认读 config）")

    # reflect 子命令
    reflect_parser = subparsers.add_parser(
        "reflect", help="面试反思：LLM 询问实际回答表现，分析后更新画像"
    )
    reflect_parser.add_argument("file", help="目标面经文件路径")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # 路由到对应处理函数
    commands = {
        "sync": cmd_sync,
        "detect": cmd_detect,
        "extract": cmd_extract,
        "archive": cmd_archive,
        "review": cmd_review,
        "prepare": cmd_prepare,
        "export-session": cmd_export_session,
        "reflect": cmd_reflect,
    }

    handler = commands.get(args.command)
    if handler:
        try:
            handler(args)
        except KeyboardInterrupt:
            print("\n\n[中断] 用户取消操作")
            sys.exit(130)
        except Exception as e:
            logger.error(f"执行出错: {e}", exc_info=True)
            print(f"\n[致命错误] {e}")
            sys.exit(1)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
