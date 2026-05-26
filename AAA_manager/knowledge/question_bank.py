"""
question_bank.py - 问题库检索模块
解析问题库目录下的 .md 文件，建立问题索引，支持关键词搜索。
"""

import os
import re
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class QuestionBank:
    def __init__(self, bank_dir: str, extra_dirs: list[str] | None = None):
        """初始化，加载问题库目录

        Args:
            bank_dir: 主问题库目录（如 问题库/）
            extra_dirs: 额外的题库目录列表（如 岗位预测/），
                        这些目录下的 md 文件会被视为问题库补充，
                        以 _ 开头的文件会被排除（预留给非题库文档）。
        """
        self.bank_dir = Path(bank_dir)
        self.extra_dirs = [Path(d) for d in (extra_dirs or [])]
        self.questions: list[dict] = []
        self._categories: list[str] = []
        self._loaded = False

    def load(self):
        """解析所有 .md 文件，建立索引"""
        self.questions = []
        self._categories = []

        # 汇总待扫描文件：主目录 + 额外目录
        md_files: list[Path] = []
        if self.bank_dir.exists():
            md_files.extend(sorted(self.bank_dir.glob("*.md")))
        else:
            logger.warning(f"问题库目录不存在: {self.bank_dir}")

        for extra in self.extra_dirs:
            if extra.exists():
                # 排除 _ 开头文件（例如未来可能的速查档、草稿）
                md_files.extend(sorted(f for f in extra.glob("*.md") if not f.name.startswith("_")))
                logger.info(f"额外题库目录已纳入: {extra}")
            else:
                logger.debug(f"额外题库目录不存在，跳过: {extra}")

        for md_file in md_files:
            stem = md_file.stem
            # 来自岗位预测目录的文件，分类加 [预测] 前缀以便与真实题区分
            is_prep = any(md_file.parent == extra for extra in self.extra_dirs)
            category = f"[预测]{stem}" if is_prep else stem
            if category not in self._categories:
                self._categories.append(category)
            try:
                content = md_file.read_text(encoding="utf-8")
                questions = self._parse_md(content, category)
                self.questions.extend(questions)
            except Exception as e:
                logger.warning(f"解析文件失败 {md_file}: {e}")

        self._loaded = True
        logger.info(f"问题库加载完成：{len(self._categories)} 个分类，{len(self.questions)} 道题目")

    def _parse_md(self, content: str, category: str) -> list[dict]:
        """解析单个 md 文件中的所有问题"""
        questions = []
        # 匹配 ## Q{N}：或 ### Q{N}：格式的问题标题
        # 支持中文冒号和英文冒号
        pattern = re.compile(r'^#{2,3}\s+Q(\d+)[：:]\s*(.+)$', re.MULTILINE)

        matches = list(pattern.finditer(content))
        for i, match in enumerate(matches):
            qid = int(match.group(1))
            text = match.group(2).strip()
            # 提取该问题到下一个问题之间的内容
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            body = content[start:end].strip()

            question = {
                "id": qid,
                "text": text,
                "category": category,
                "source": self._extract_source(body),
                "points": self._extract_points(body),
                "speech": self._extract_speech(body),
                "raw_body": body,
            }
            questions.append(question)

        return questions

    def _extract_source(self, body: str) -> str:
        """提取来源信息，剥离 wikilink 括号"""
        match = re.search(r'[*-]\s*\*{0,2}来源\*{0,2}[：:]\s*(.+)', body)
        if not match:
            return ""
        source = match.group(1).strip()
        # 从 frontmatter_utils 复用 wikilink 解析，精确剥离 [[...]] 格式
        try:
            from frontmatter_utils import parse_wikilinks
            wikilinks = parse_wikilinks(source)
            if wikilinks:
                # 替换第一个 wikilink 为其纯文本标签
                replaced = source.replace(f"[[{wikilinks[0]}]]", wikilinks[0], 1)
                return replaced
        except Exception:
            logger.debug("wikilink 解析失败，保留原始来源文本", exc_info=True)
        return source

    def _extract_points(self, body: str) -> list[str]:
        """提取答题要点/要点/答题方向"""
        points = []
        # 查找要点段落（支持多种标题格式）
        pattern = re.compile(
            r'\*{0,2}(?:答题要点|要点|答题方向|AI Coding 特定对策)\*{0,2}[：:]\s*\n((?:\s*[-*]\s+.+\n?)+)',
            re.MULTILINE
        )
        match = pattern.search(body)
        if match:
            points_text = match.group(1)
            for line in points_text.strip().split('\n'):
                line = line.strip()
                if line.startswith(('-', '*')):
                    # 去掉列表标记
                    point = re.sub(r'^[-*]\s+', '', line).strip()
                    if point:
                        points.append(point)
        return points

    def _extract_speech(self, body: str) -> str:
        """提取面试话术"""
        # 匹配 💬 面试话术 或 面试话术 后面的引用块
        pattern = re.compile(
            r'\*{0,2}(?:💬\s*)?面试话术\*{0,2}[：:]\s*\n((?:\s*>.*\n?)+)',
            re.MULTILINE
        )
        match = pattern.search(body)
        if match:
            speech_lines = match.group(1).strip().split('\n')
            # 去掉引用符号 >
            cleaned = []
            for line in speech_lines:
                line = re.sub(r'^\s*>\s?', '', line)
                cleaned.append(line)
            return '\n'.join(cleaned).strip()
        return ""

    def search(self, query: str, top_k: int = 5, boost_categories: list[str] = None) -> list[dict]:
        """关键词搜索问题
        返回: [{id, text, source, category, points, speech, score}]

        Args:
            query: 搜索关键词
            top_k: 返回前 K 条结果
            boost_categories: 需要限定的 category 列表。
                当提供时，优先返回该 category 的结果；
                若目标 category 结果不足 top_k，用该 category 的条目兜底填充。
        """
        if not self._loaded:
            self.load()

        if not query or not self.questions:
            return []

        results = []
        query_lower = query.lower()

        for q in self.questions:
            score = self._compute_score(query_lower, q)
            if score > 0:
                results.append({
                    "id": q["id"],
                    "text": q["text"],
                    "source": q["source"],
                    "category": q["category"],
                    "points": q["points"],
                    "speech": q["speech"],
                    "score": score,
                })

        # 当有明确项目意图时，硬过滤：只保留目标 category 的结果
        if boost_categories:
            results = [r for r in results if r["category"] in boost_categories]

        # 按分数降序排列
        results.sort(key=lambda x: x["score"], reverse=True)

        # Category fallback: 如果目标 category 结果不足 top_k，
        # 直接拉取该 category 的条目作为兜底
        if boost_categories and len(results) < top_k:
            seen_ids = {r["id"] for r in results}
            for q in self.questions:
                if q["category"] in boost_categories and q["id"] not in seen_ids:
                    results.append({
                        "id": q["id"],
                        "text": q["text"],
                        "source": q["source"],
                        "category": q["category"],
                        "points": q["points"],
                        "speech": q["speech"],
                        "score": 3.0,
                    })
                if len(results) >= top_k:
                    break

        return results[:top_k]

    def _compute_score(self, query: str, question: dict) -> float:
        """计算查询词与问题的匹配分数"""
        score = 0.0
        text_lower = question["text"].lower()
        body_lower = question["raw_body"].lower()

        # 1. 精确子串匹配（双向）
        if query in text_lower:
            score += 10.0
        elif text_lower in query:
            # 题目是用户输入的子串（如题库"http和https区别" in 用户"http和https的区别"）
            score += 9.0

        # 2. 精确匹配正文内容（中分）
        if query in body_lower:
            score += 5.0

        # 3. 基于 n-gram 字符重叠度的模糊匹配
        if score == 0:
            ngram_score = self._ngram_similarity(query, text_lower)
            score += ngram_score * 10.0  # 提高权重，最高 10 分

        # 4. 单字符匹配（补充分数）
        if score == 0:
            char_overlap = sum(1 for c in query if c in text_lower)
            if len(query) > 0:
                overlap_ratio = char_overlap / len(query)
                if overlap_ratio >= 0.5:
                    score += overlap_ratio * 3.0

        return round(score, 3)

    def _ngram_similarity(self, query: str, text: str, n: int = 2) -> float:
        """基于字符 n-gram 的相似度计算"""
        if len(query) < n:
            # 查询太短，退化为字符匹配
            return 1.0 if query in text else 0.0

        query_ngrams = set()
        for i in range(len(query) - n + 1):
            query_ngrams.add(query[i:i + n])

        if not query_ngrams:
            return 0.0

        text_ngrams = set()
        for i in range(len(text) - n + 1):
            text_ngrams.add(text[i:i + n])

        overlap = query_ngrams & text_ngrams
        return len(overlap) / len(query_ngrams)

    def get_question(self, category: str, qid: int) -> dict:
        """获取特定问题的完整内容"""
        if not self._loaded:
            self.load()

        for q in self.questions:
            if q["category"] == category and q["id"] == qid:
                return {
                    "id": q["id"],
                    "text": q["text"],
                    "source": q["source"],
                    "category": q["category"],
                    "points": q["points"],
                    "speech": q["speech"],
                }
        return {}

    def get_stats(self) -> dict:
        """返回统计信息：各分类题目数量、总题数、最近更新等"""
        if not self._loaded:
            self.load()

        category_counts = {}
        for q in self.questions:
            cat = q["category"]
            category_counts[cat] = category_counts.get(cat, 0) + 1

        # 获取最近更新时间
        last_modified = None
        if self.bank_dir.exists():
            for md_file in self.bank_dir.glob("*.md"):
                mtime = os.path.getmtime(md_file)
                if last_modified is None or mtime > last_modified:
                    last_modified = mtime

        return {
            "total": len(self.questions),
            "categories": category_counts,
            "category_count": len(self._categories),
            "last_modified": (
                datetime.fromtimestamp(last_modified).isoformat()
                if last_modified else None
            ),
        }

    def get_all_categories(self) -> list[str]:
        """返回所有分类列表"""
        if not self._loaded:
            self.load()
        return list(self._categories)
