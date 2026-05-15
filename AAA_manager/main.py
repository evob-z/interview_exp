#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
AAA_manager - 面经管理程序
统一入口，支持全流程同步和单模块独立执行。

用法:
    python main.py extract <file> [--type transcript|chat|structured]
    python main.py extract --from-session <session_id>
    python main.py review <file>              # file 必须在 面试原始问题/ 目录中
    python main.py archive <file>             # file 必须在 面试原始问题/ 目录中
    python main.py sync <file> [--type ...]   # 全流程：extract → review → archive
    python main.py prepare 字节跳动_AI应用开发实习生-AI数据与安全_260512
    python main.py export-session <session_id> [--rewrite]
"""

import argparse
import re
import sys
from pathlib import Path

# 确保可以 import 同目录模块
sys.path.insert(0, str(Path(__file__).parent))

try:
    from logger import get_logger
    from config import INTERVIEW_REPO_PATH, RAW_INPUT_DIR, REVIEW_OUTPUT_DIR
    import extractor
    import archiver
    import reviewer
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

    # 多项目标签取第一个
    first_project = tag.split("/")[0].strip()

    # 映射到 category
    category = f"项目-{first_project}"
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
    单文件全流程快捷方式：抽取 → 复盘 → 入库
    对指定输入文件依次执行 extract、review、archive 三步。
    """
    file_path = _resolve_file_path(args.file)

    if not Path(file_path).exists():
        print(f"[错误] 文件不存在: {file_path}")
        return

    file_type = getattr(args, "type", None)

    print("\n=== 单文件全流程同步 ===")
    print(f"输入文件: {Path(file_path).name}")
    if file_type:
        print(f"指定类型: {file_type}")
    print()

    # ── Step 1: 抽取 ──
    print("[1/3] 开始抽取问题...")
    try:
        output_path = extractor.extract_and_write(file_path, file_type=file_type)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"[错误] 抽取失败: {e}")
        print("  💡 可单独重试: python main.py extract", Path(file_path).name)
        return
    except Exception as e:
        logger.error(f"抽取失败: {e}", exc_info=True)
        print(f"[错误] 抽取失败: {e}")
        print("  💡 可单独重试: python main.py extract", Path(file_path).name)
        return

    print(f"[1/3] 抽取完成 → {Path(output_path).name}")
    print()

    # ── Step 2: 复盘 ──
    print("[2/3] 开始生成复盘分析...")
    try:
        valid, error_msg = reviewer.validate_review_input(output_path)
        if not valid:
            print(f"[错误] 复盘校验失败: {error_msg}")
            print(f"  💡 可单独重试: python main.py review {Path(output_path).name}")
        else:
            review_output_dir = Path(INTERVIEW_REPO_PATH) / REVIEW_OUTPUT_DIR
            review_output_dir.mkdir(parents=True, exist_ok=True)
            review_result = reviewer.generate_review_file(
                source_file=output_path,
                output_dir=str(review_output_dir),
            )
            print(f"[2/3] 复盘完成 → {Path(review_result.output_file).name}")
            if review_result.top_concerns:
                print(f"  面试官最关注: {', '.join(review_result.top_concerns[:3])}")
    except Exception as e:
        logger.error(f"复盘失败: {e}", exc_info=True)
        print(f"[错误] 复盘失败: {e}")
        print(f"  💡 可单独重试: python main.py review {Path(output_path).name}")

    print()

    # ── Step 3: 入库 ──
    print("[3/3] 开始归档入库（含AI回答生成）...")
    try:
        valid, error_msg = archiver.validate_archive_input(output_path)
        if not valid:
            print(f"[错误] 入库校验失败: {error_msg}")
            print(f"  💡 可单独重试: python main.py archive {Path(output_path).name}")
        else:
            questions_data = _parse_structured_questions(output_path)
            if not questions_data:
                print("[错误] 无法从文件中解析出问题")
                print(f"  💡 可单独重试: python main.py archive {Path(output_path).name}")
            else:
                source_label = _get_source_label_from_filename(output_path)
                archive_result = archiver.archive_questions(questions_data, source_label)

                if archive_result.archived_questions:
                    print(f"[3/3] 入库完成: 成功归档 {len(archive_result.archived_questions)} 个问题")
                    for aq in archive_result.archived_questions:
                        print(f"  - {aq['question_id']} → {aq['target_file']}")
                else:
                    print("[3/3] 无新问题归档（可能全部为重复题）")

                if archive_result.skipped_duplicates:
                    print(f"  [去重] 跳过 {len(archive_result.skipped_duplicates)} 个重复问题")
    except Exception as e:
        logger.error(f"入库失败: {e}", exc_info=True)
        print(f"[错误] 入库失败: {e}")
        print(f"  💡 可单独重试: python main.py archive {Path(output_path).name}")

    print("\n=== 完成 ===\n")



def cmd_extract(args):
    """对指定文件抽取问题并写入 面试原始问题/ 目录"""
    print(f"\n=== 问题抽取 ===")

    # --from-session 模式：从会话导出
    if getattr(args, "from_session", None):
        session_id = args.from_session
        print(f"会话ID: {session_id}")
        try:
            output_path, count = exporter.export_session_questions(
                session_id=session_id,
                rewrite=True,
            )
        except FileNotFoundError as e:
            print(f"[错误] {e}")
            return
        except ValueError as e:
            print(f"[错误] {e}")
            return
        except Exception as e:
            logger.error(f"会话导出失败: {e}", exc_info=True)
            print(f"[错误] 导出失败: {e}")
            return

        print(f"\n[完成] 导出 {count} 个面试问题")
        print(f"  文件: {output_path}")
        print("\n=== 完成 ===\n")
        return

    # 文件模式
    if not getattr(args, "file", None):
        print("[错误] 请指定输入文件或使用 --from-session")
        return

    file_path = _resolve_file_path(args.file)
    if not Path(file_path).exists():
        print(f"[错误] 文件不存在: {file_path}")
        return

    file_type = getattr(args, "type", None)
    print(f"目标文件: {Path(file_path).name}")
    if file_type:
        print(f"指定类型: {file_type}")
    print()

    try:
        output_path = extractor.extract_and_write(file_path, file_type=file_type)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"[错误] {e}")
        return
    except Exception as e:
        logger.error(f"抽取失败: {e}", exc_info=True)
        print(f"[错误] 抽取失败: {e}")
        return

    print(f"[完成] 问题已写入: {output_path}")
    print("\n=== 完成 ===\n")


def cmd_archive(args):
    """对 面试原始问题/ 中的文件入库（含AI回答生成）"""
    file_path = _resolve_file_path(args.file)

    if not Path(file_path).exists():
        print(f"[错误] 文件不存在: {file_path}")
        return

    print(f"\n=== 归档入库 ===")
    print(f"目标文件: {Path(file_path).name}\n")

    # 1. 输入校验
    valid, error_msg = archiver.validate_archive_input(file_path)
    if not valid:
        print(f"[错误] {error_msg}")
        return

    # 2. 解析问题
    questions_data = _parse_structured_questions(file_path)
    if not questions_data:
        print("[错误] 无法从文件中解析出问题")
        return

    source_label = _get_source_label_from_filename(file_path)

    # 3. 归档（含回答生成）
    print(f"[入库] 开始处理 {len(questions_data)} 个问题（每题需生成回答，请耐心等待）...")
    result = archiver.archive_questions(questions_data, source_label)

    # 4. 输出结果
    if result.archived_questions:
        print(f"\n[完成] 成功入库 {len(result.archived_questions)} 个问题（含要点+话术）")
        for aq in result.archived_questions:
            print(f"  - {aq['question_id']} → {aq['target_file']}")
    else:
        print("\n[归档] 无新问题归档（可能全部为重复题）")

    if result.skipped_duplicates:
        print(f"[去重] 跳过 {len(result.skipped_duplicates)} 个重复问题")

    print("\n=== 完成 ===\n")


def cmd_prepare(args):
    """岗位针对性预测题生成：搜 JD → 结合简历项目 → LLM 出题 → 写入 岗位预测/"""
    # 优先使用 spec 位置参数，否则使用 --company/--position/--date
    if getattr(args, "spec", None):
        company, position, date = preparer.parse_spec(args.spec)
        # 允许 --date 覆盖 spec 中的日期
        if getattr(args, "date", None):
            date = args.date
    else:
        company = getattr(args, "company", "") or ""
        position = getattr(args, "position", "") or ""
        date = getattr(args, "date", None)

    if not company or not position:
        print("[错误] 必须提供公司与岗位。示例：python main.py prepare 字节跳动_AI应用开发实习生_260512")
        print("      或：python main.py prepare --company 字节跳动 --position AI应用开发实习生")
        return

    print("\n=== 岗位预测题生成 ===")
    print(f"公司: {company}")
    print(f"岗位: {position}")
    print(f"日期: {date or '今天'}")

    try:
        result = preparer.prepare_interview(
            company=company,
            position=position,
            date=date,
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
    """对 面试原始问题/ 中的文件生成复盘分析"""
    file_path = _resolve_file_path(args.file)

    # 1. 输入校验
    valid, error_msg = reviewer.validate_review_input(file_path)
    if not valid:
        print(f"[错误] {error_msg}")
        return

    print(f"\n=== 复盘分析 ===")
    print(f"目标文件: {Path(file_path).name}\n")

    # 2. 生成复盘
    review_output_path = Path(INTERVIEW_REPO_PATH) / REVIEW_OUTPUT_DIR
    review_output_path.mkdir(parents=True, exist_ok=True)

    try:
        result = reviewer.generate_review_file(
            source_file=file_path,
            output_dir=str(review_output_path),
        )
    except Exception as e:
        print(f"[错误] 复盘失败: {e}")
        return

    # 3. 输出结果
    print(f"分析问题数: {result.question_count}")
    if result.top_concerns:
        print(f"面试官最关注:")
        for i, concern in enumerate(result.top_concerns, 1):
            print(f"  {i}. {concern}")
    print(f"\n[完成] 复盘文件已生成: {Path(result.output_file).name}")
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


# ──────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="面经管理程序 - AAA_manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py extract 蚂蚁_大厂_260423_一面技术.md              抽取问题
  python main.py extract --from-session abc12345                 从会话导出
  python main.py review 面试原始问题/字节跳动_大厂_260513_技术一面.md  复盘分析
  python main.py archive 面试原始问题/蚂蚁_大厂_260423_一面技术.md   归档入库
  python main.py sync 蚂蚁_大厂_260423_一面技术.md                 全流程
  python main.py sync 蚂蚁_大厂_260423_一面技术.md --type chat      强制指定类型
  python main.py prepare 字节跳动_AI应用开发实习生_260512            岗位预测出题
        """,
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # sync 子命令
    sync_parser = subparsers.add_parser("sync", help="单文件全流程：抽取 → 复盘 → 入库")
    sync_parser.add_argument("file", help="输入文件路径")
    sync_parser.add_argument(
        "--type", choices=["transcript", "chat", "structured"],
        default=None, help="强制指定文件类型给 extract（跳过自动识别）"
    )

    # extract 子命令
    extract_parser = subparsers.add_parser("extract", help="从面经文件抽取问题并写入 面试原始问题/")
    extract_parser.add_argument("file", nargs="?", default=None, help="目标面经文件路径")
    extract_parser.add_argument(
        "--type", choices=["transcript", "chat", "structured"],
        default=None, help="强制指定文件类型（跳过自动识别）"
    )
    extract_parser.add_argument(
        "--from-session", default=None,
        help="从模拟面试会话导出问题（会话ID，8位hex）"
    )

    # archive 子命令
    archive_parser = subparsers.add_parser("archive", help="归档问题到问题库（含AI回答生成，必须是 面试原始问题/ 中的文件）")
    archive_parser.add_argument("file", help="目标文件路径（必须是 面试原始问题/ 中的已结构化文件）")

    # review 子命令
    review_parser = subparsers.add_parser("review", help="对 面试原始问题/ 中的文件生成复盘分析")
    review_parser.add_argument(
        "file", help="目标文件路径（必须是 面试原始问题/ 中的文件）"
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
        help="简写格式：公司_岗位_YYMMDD（日期可省略）"
    )
    prepare_parser.add_argument("--company", help="公司名（与 spec 二选一）")
    prepare_parser.add_argument("--position", help="岗位名")
    prepare_parser.add_argument("--date", help="面试日期 YYMMDD，默认今天")
    prepare_parser.add_argument("--count", type=int, default=None, help="期望题数（默认读 config）")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # 路由到对应处理函数
    commands = {
        "sync": cmd_sync,
        "extract": cmd_extract,
        "archive": cmd_archive,
        "review": cmd_review,
        "prepare": cmd_prepare,
        "export-session": cmd_export_session,
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
