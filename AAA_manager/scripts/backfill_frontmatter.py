"""
backfill_frontmatter.py - 存量数据回填脚本

为问题库文件中已有的 Q 块追加初始 inline 元数据（mastery/review_count/last_reviewed），
将来源行的面试记录引用转换为 [[wikilink]] 格式，
为面试复盘目录下的文件补打 YAML frontmatter。

幂等：已有字段不重复写入。

用法：
    cd AAA_manager
    python scripts/backfill_frontmatter.py          # 回填全部
    python scripts/backfill_frontmatter.py --dry-run  # 预览变更
    python scripts/backfill_frontmatter.py --no-wikilink  # 仅回填 mastery
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

# 确保能导入 AAA_manager 模块
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import INTERVIEW_REPO_PATH, QUESTION_BANK_PATH
from frontmatter_utils import read_frontmatter, write_frontmatter, upsert_inline_metadata

logger = logging.getLogger("backfill")
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

# ── 面试记录文件名的 wikilink 模式（公司_类型_YYMMDD_场次）──
INTERVIEW_LINK_PATTERN = re.compile(
    r"([\u4e00-\u9fff]+_(?:大厂|中厂|小厂|国企|外企)_\d{6}_[^\s#;、，]+)"
    r"(?=\s*[#;、，]|\s*$)"
)


def _convert_source_to_wikilink(source_line: str) -> str:
    """将来源行中的面试记录引用转为 [[wikilink]] 格式。"""
    def _wrap(m: re.Match) -> str:
        target = m.group(1)
        return f"[[{target}]]"

    return INTERVIEW_LINK_PATTERN.sub(_wrap, source_line)


def _infer_meta_from_filename(file_path: Path) -> dict[str, str]:
    """从文件名 {公司}_{类型}_{YYMMDD}_{场次}.md 推断元信息。"""
    stem = file_path.stem
    parts = stem.split("_")
    meta: dict[str, str] = {"doc_type": "面试复盘"}

    if len(parts) >= 1:
        meta["company"] = parts[0]
    if len(parts) >= 2:
        meta["company_type"] = parts[1]
    if len(parts) >= 3:
        meta["date"] = f"20{parts[2][:2]}-{parts[2][2:4]}-{parts[2][4:6]}"
    if len(parts) >= 4:
        meta["round"] = parts[3]

    return meta


def backfill_question_bank(dry_run: bool = False, convert_wikilink: bool = True) -> dict:
    """回填问题库：每题追加初始 inline 元数据 + 来源行 wikilink 化。"""
    stats = {"files": 0, "q_blocks": 0, "wikilink_converted": 0, "skipped": 0}

    if not QUESTION_BANK_PATH.exists():
        logger.warning(f"问题库目录不存在: {QUESTION_BANK_PATH}")
        return stats

    for md_file in sorted(QUESTION_BANK_PATH.glob("*.md")):
        if md_file.name in (".gitkeep",):
            continue

        stats["files"] += 1
        content = md_file.read_text(encoding="utf-8")
        original = content

        # 统计 Q 块数量并追加 inline 元数据
        q_pattern = re.compile(r"^#{2,4}\s+Q(\d+)[：:]", re.MULTILINE)
        qids = [int(m.group(1)) for m in q_pattern.finditer(content)]

        for qid in qids:
            if dry_run:
                stats["q_blocks"] += 1
            else:
                try:
                    upsert_inline_metadata(
                        md_file, qid,
                        {"mastery": "unset", "last_reviewed": "null", "review_count": "0"},
                    )
                    stats["q_blocks"] += 1
                except Exception:
                    logger.warning(f"  Q{qid} inline 写入失败（{md_file.name}），跳过", exc_info=True)
                    stats["skipped"] += 1

        # wikilink 格式转换
        if convert_wikilink and not dry_run:
            content_after = md_file.read_text(encoding="utf-8")
            converted = 0
            lines = content_after.split("\n")
            new_lines = []
            for line in lines:
                if line.startswith("- **来源**"):
                    new_line = _convert_source_to_wikilink(line)
                    if new_line != line:
                        converted += 1
                    new_lines.append(new_line)
                else:
                    new_lines.append(line)

            if converted > 0:
                md_file.write_text("\n".join(new_lines), encoding="utf-8")
                stats["wikilink_converted"] += converted
                logger.info(f"  {md_file.name}: {len(qids)} 题 + {converted} 处 wikilink 转换")
            else:
                logger.info(f"  {md_file.name}: {len(qids)} 题")
        elif dry_run:
            logger.info(f"  [DRY-RUN] {md_file.name}: {len(qids)} 题待处理")

    return stats


def backfill_review_files(dry_run: bool = False) -> dict:
    """回填复盘文件：补打 YAML frontmatter。"""
    stats = {"files": 0, "with_frontmatter": 0, "skipped": 0, "new_frontmatter": 0}

    review_dir = INTERVIEW_REPO_PATH / "面试复盘"
    if not review_dir.exists():
        logger.warning(f"复盘目录不存在: {review_dir}")
        return stats

    for md_file in sorted(review_dir.glob("*.md")):
        if md_file.name in (".gitkeep",):
            continue

        stats["files"] += 1
        existing, _ = read_frontmatter(md_file)

        if "doc_type" in existing:
            stats["with_frontmatter"] += 1
            continue

        meta = _infer_meta_from_filename(md_file)
        if not meta.get("company"):
            logger.warning(f"  无法从文件名推断元信息: {md_file.name}")
            stats["skipped"] += 1
            continue

        if dry_run:
            logger.info(f"  [DRY-RUN] {md_file.name}: 待写入 {meta}")
            stats["new_frontmatter"] += 1
        else:
            try:
                write_frontmatter(md_file, meta)
                stats["new_frontmatter"] += 1
                logger.info(f"  {md_file.name}: frontmatter 已写入")
            except Exception:
                logger.warning(f"  {md_file.name}: frontmatter 写入失败", exc_info=True)
                stats["skipped"] += 1

    return stats


def backfill_prep_files(dry_run: bool = False) -> dict:
    """回填岗位预测文件：补打 YAML frontmatter。"""
    stats = {"files": 0, "with_frontmatter": 0, "new_frontmatter": 0}

    prep_dir = INTERVIEW_REPO_PATH / "岗位预测"
    if not prep_dir.exists():
        return stats

    for md_file in sorted(prep_dir.glob("*.md")):
        if md_file.name in (".gitkeep",):
            continue

        stats["files"] += 1
        existing, _ = read_frontmatter(md_file)

        if "prep_type" in existing:
            stats["with_frontmatter"] += 1
            continue

        # 文件名格式：{公司}_{部门}_{岗位}_{YYMMDD}.md 或 {公司}_{岗位}_{YYMMDD}.md
        stem = md_file.stem
        meta: dict[str, str] = {"prep_type": "岗位预测"}
        parts = stem.split("_")

        if len(parts) >= 1:
            meta["company"] = parts[0]

        # 倒数第一个是日期（6位数字）
        date_idx = None
        for i in range(len(parts) - 1, 0, -1):
            if re.match(r"^\d{6}$", parts[i]):
                date_idx = i
                break

        if date_idx and len(parts) >= date_idx:
            meta["date"] = f"20{parts[date_idx][:2]}-{parts[date_idx][2:4]}-{parts[date_idx][4:6]}"
            meta["position"] = parts[date_idx - 1]
            if date_idx - 2 >= 1:
                meta["department"] = parts[date_idx - 2]

        if dry_run:
            logger.info(f"  [DRY-RUN] {md_file.name}: 待写入 {meta}")
            stats["new_frontmatter"] += 1
        else:
            try:
                write_frontmatter(md_file, meta)
                stats["new_frontmatter"] += 1
                logger.info(f"  {md_file.name}: frontmatter 已写入")
            except Exception:
                logger.warning(f"  {md_file.name}: frontmatter 写入失败", exc_info=True)

    return stats


def main():
    parser = argparse.ArgumentParser(description="存量数据回填：inline 元数据 + wikilink + frontmatter")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际写入")
    parser.add_argument("--no-wikilink", action="store_true", help="跳过 wikilink 格式转换")
    parser.add_argument("--question-bank-only", action="store_true", help="仅回填问题库")
    parser.add_argument("--review-only", action="store_true", help="仅回填复盘文件")
    args = parser.parse_args()

    dry_run = args.dry_run
    if dry_run:
        logger.info("=== DRY-RUN 模式：以下为预览，不会实际写入 ===")

    do_qb = not args.review_only
    do_review = not args.question_bank_only
    do_prep = not args.question_bank_only and not args.review_only

    # ── 问题库回填 ──
    if do_qb:
        logger.info("\n📚 问题库回填（inline 元数据 + wikilink）")
        qb_stats = backfill_question_bank(dry_run=dry_run, convert_wikilink=not args.no_wikilink)
        logger.info(
            f"  文件 {qb_stats['files']} 个，Q 块 {qb_stats['q_blocks']} 个，"
            f"wikilink {qb_stats['wikilink_converted']} 处，跳过 {qb_stats['skipped']} 个"
        )

    # ── 复盘文件回填 ──
    if do_review:
        logger.info("\n📝 复盘文件回填（frontmatter）")
        rev_stats = backfill_review_files(dry_run=dry_run)
        logger.info(
            f"  文件 {rev_stats['files']} 个，已有 frontmatter {rev_stats['with_frontmatter']} 个，"
            f"新写入 {rev_stats['new_frontmatter']} 个，跳过 {rev_stats['skipped']} 个"
        )

    # ── 岗位预测回填 ──
    if do_prep:
        logger.info("\n🎯 岗位预测回填（frontmatter）")
        prep_stats = backfill_prep_files(dry_run=dry_run)
        logger.info(
            f"  文件 {prep_stats['files']} 个，已有 frontmatter {prep_stats['with_frontmatter']} 个，"
            f"新写入 {prep_stats['new_frontmatter']} 个"
        )

    if dry_run:
        logger.info("\n=== DRY-RUN 结束：未做任何实际修改 ===")
    else:
        logger.info("\n✅ 回填完成")


if __name__ == "__main__":
    main()
