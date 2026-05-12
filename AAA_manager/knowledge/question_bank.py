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
    def __init__(self, bank_dir: str):
        """初始化，加载问题库目录"""
        self.bank_dir = Path(bank_dir)
        self.questions: list[dict] = []
        self._categories: list[str] = []
        self._loaded = False

    def load(self):
        """解析所有 .md 文件，建立索引"""
        self.questions = []
        self._categories = []

        if not self.bank_dir.exists():
            logger.warning(f"问题库目录不存在: {self.bank_dir}")
            self._loaded = True
            return

        md_files = sorted(self.bank_dir.glob("*.md"))
        for md_file in md_files:
            category = md_file.stem  # 文件名（不含扩展名）作为分类
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
        """提取来源信息"""
        match = re.search(r'[*-]\s*\*{0,2}来源\*{0,2}[：:]\s*(.+)', body)
        return match.group(1).strip() if match else ""

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

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """关键词搜索问题
        返回: [{id, text, source, category, points, speech, score}]
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

        # 按分数降序排列
        results.sort(key=lambda x: x["score"], reverse=True)
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
