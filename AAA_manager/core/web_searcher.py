"""
core/web_searcher.py - 网络搜索模块
提供网络搜索能力，在生成复盘时自动搜索公司信息和技术概念作为参考。
支持 Tavily / Bing / Serper 三种搜索 API provider。
"""

import asyncio
import time
import json
import re
from typing import Optional

import httpx

from logger import get_logger

logger = get_logger("web_searcher")


class WebSearcher:
    """网络搜索模块，支持多种搜索 API"""

    SUPPORTED_PROVIDERS = ("tavily", "bing", "serper")

    def __init__(self, api_key: str, provider: str = "tavily", enabled: bool = True):
        """
        初始化搜索器

        Args:
            api_key: 搜索 API 密钥
            provider: 搜索提供商 (tavily/bing/serper)
            enabled: 是否启用搜索
        """
        self.api_key = api_key
        self.provider = provider.lower()
        self.enabled = enabled
        self._timeout = 15.0  # 请求超时秒数
        self._max_retries = 1  # 失败重试次数

        if self.provider not in self.SUPPORTED_PROVIDERS:
            logger.warning(
                f"不支持的搜索提供商: {self.provider}，将使用 tavily 作为默认"
            )
            self.provider = "tavily"

        if self.enabled and not self.api_key:
            logger.warning("搜索 API 密钥未配置，搜索功能将被禁用")
            self.enabled = False

    # ------------------------------------------------------------------
    # 公共搜索接口
    # ------------------------------------------------------------------

    async def search(self, query: str, max_results: int = 5) -> list[dict]:
        """
        执行搜索

        Args:
            query: 搜索查询
            max_results: 最大结果数

        Returns:
            [{title, url, content, score}]
        """
        if not self.enabled:
            return []

        start_time = time.time()
        results: list[dict] = []

        dispatch = {
            "tavily": self._search_tavily,
            "bing": self._search_bing,
            "serper": self._search_serper,
        }

        search_fn = dispatch.get(self.provider, self._search_tavily)

        for attempt in range(1 + self._max_retries):
            try:
                results = await search_fn(query, max_results)
                break
            except Exception as e:
                if attempt < self._max_retries:
                    logger.warning(
                        f"搜索失败 (尝试 {attempt + 1})，即将重试: {e}"
                    )
                    await asyncio.sleep(0.5)
                else:
                    logger.error(f"搜索最终失败: {e}")
                    return []

        elapsed = time.time() - start_time
        logger.info(
            f"搜索完成: query='{query}' | 结果数={len(results)} | 耗时={elapsed:.2f}s"
        )
        return results

    def search_sync(self, query: str, max_results: int = 5) -> list[dict]:
        """同步版本的搜索（供非异步环境使用）"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # 已在事件循环中，创建新线程执行
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, self.search(query, max_results))
                return future.result(timeout=self._timeout + 5)
        else:
            return asyncio.run(self.search(query, max_results))

    # ------------------------------------------------------------------
    # 高层搜索方法
    # ------------------------------------------------------------------

    async def search_company(self, company_name: str) -> dict:
        """
        搜索公司信息

        Returns:
            {company, business, tech_stack, culture, interview_style, raw_results}
        """
        result = {
            "company": company_name,
            "business": "",
            "tech_stack": "",
            "culture": "",
            "interview_style": "",
            "raw_results": [],
        }

        if not self.enabled:
            return result

        # 搜索面试经验和技术栈
        query1 = f"{company_name} 面试经验 技术栈"
        results1 = await self.search(query1, max_results=3)

        # 搜索业务方向和团队
        query2 = f"{company_name} 业务方向 团队"
        results2 = await self.search(query2, max_results=3)

        all_results = results1 + results2
        result["raw_results"] = all_results

        # 从搜索结果中提取摘要信息
        contents = [r.get("content", "") for r in all_results if r.get("content")]
        combined_text = "\n".join(contents)

        if combined_text:
            result["business"] = self._extract_snippet(combined_text, "业务")
            result["tech_stack"] = self._extract_snippet(combined_text, "技术")
            result["culture"] = self._extract_snippet(combined_text, "文化")
            result["interview_style"] = self._extract_snippet(combined_text, "面试")

        return result

    async def search_jd(self, company: str, position: str, max_results: int = 6) -> dict:
        """
        搜索近期岗位 JD（职位描述）信息。

        策略：组装招聘关键词 + 时限词汇，优先从招聘主流站点返回的结果中
        提取技术能力要求、工作职责、加分项。

        Args:
            company: 公司名称（如 字节跳动）
            position: 岗位名称（如 AI应用开发实习生）
            max_results: 最大搜索条数

        Returns:
            {company, position, jd_snippets: [str], source_urls: [str], raw_results: list}
        """
        result = {
            "company": company,
            "position": position,
            "jd_snippets": [],
            "source_urls": [],
            "raw_results": [],
        }

        if not self.enabled:
            logger.info("搜索未启用，跳过 JD 搜索")
            return result

        # 多条 query 覆盖不同维度：JD 正文 / 职责 / 要求
        queries = [
            f"{company} {position} 招聘 JD 岗位职责 要求",
            f"{company} {position} 实习生 招聘公告 技术栈",
            f"{company} {position} boss直聘 拉勾 牛客 前程无忧",
        ]

        all_results: list[dict] = []
        seen_urls: set[str] = set()
        for q in queries:
            try:
                rs = await self.search(q, max_results=max_results)
                for r in rs:
                    u = r.get("url", "")
                    if u and u in seen_urls:
                        continue
                    if u:
                        seen_urls.add(u)
                    all_results.append(r)
            except Exception as e:
                logger.warning(f"JD 搜索某轮失败，忽略: {e}")

        result["raw_results"] = all_results
        result["source_urls"] = [r.get("url", "") for r in all_results if r.get("url")]
        # 收集有效长度的内容片段，作为 JD 上下文给 LLM
        for r in all_results:
            snippet = (r.get("content") or "").strip()
            if len(snippet) >= 40:
                result["jd_snippets"].append(snippet)

        logger.info(
            f"JD 搜索完成: company={company}, position={position}, "
            f"有效片段={len(result['jd_snippets'])}, 源 URL={len(result['source_urls'])}"
        )
        return result

    async def search_tech_concept(self, concept: str) -> dict:
        """
        搜索技术概念

        Returns:
            {concept, explanation, key_points, raw_results}
        """
        result = {
            "concept": concept,
            "explanation": "",
            "key_points": [],
            "raw_results": [],
        }

        if not self.enabled:
            return result

        query = f"{concept} 面试题 详解"
        results = await self.search(query, max_results=3)
        result["raw_results"] = results

        # 提取解释和要点
        contents = [r.get("content", "") for r in results if r.get("content")]
        if contents:
            result["explanation"] = contents[0][:500] if contents[0] else ""
            # 提取关键要点（取每个结果的前200字符作为要点）
            result["key_points"] = [
                c[:200] for c in contents[:3] if c
            ]

        return result

    # ------------------------------------------------------------------
    # 复盘上下文生成
    # ------------------------------------------------------------------

    def format_for_review(self, company_info: dict, tech_concepts: list[dict]) -> str:
        """
        将搜索结果格式化为可注入复盘 prompt 的 context

        Returns:
            格式化的 markdown 文本
        """
        sections = []

        # 公司信息部分
        if company_info and any(
            company_info.get(k) for k in ("business", "tech_stack", "culture", "interview_style")
        ):
            sections.append(f"## 公司背景: {company_info.get('company', '未知')}")
            if company_info.get("business"):
                sections.append(f"- **业务方向**: {company_info['business']}")
            if company_info.get("tech_stack"):
                sections.append(f"- **技术栈**: {company_info['tech_stack']}")
            if company_info.get("culture"):
                sections.append(f"- **公司文化**: {company_info['culture']}")
            if company_info.get("interview_style"):
                sections.append(f"- **面试风格**: {company_info['interview_style']}")
            sections.append("")

        # 技术概念部分
        if tech_concepts:
            sections.append("## 相关技术概念")
            for tc in tech_concepts:
                if tc.get("explanation"):
                    sections.append(f"\n### {tc['concept']}")
                    sections.append(tc["explanation"][:300])
                    if tc.get("key_points"):
                        sections.append("**关键要点:**")
                        for point in tc["key_points"][:3]:
                            sections.append(f"- {point[:150]}")
            sections.append("")

        if not sections:
            return ""

        return "\n".join(sections)

    async def enrich_review_context(self, company: str, questions: list[str]) -> str:
        """
        为复盘生成搜索上下文

        Args:
            company: 公司名称
            questions: 面试问题列表

        Returns:
            格式化的搜索结果文本，可直接注入 prompt
        """
        if not self.enabled:
            return ""

        # 1. 搜索公司信息
        company_info = await self.search_company(company)

        # 2. 从问题中提取关键技术概念
        tech_keywords = self._extract_tech_keywords(questions)

        # 3. 搜索每个概念（限制数量，最多3个）
        tech_concepts = []
        for keyword in tech_keywords[:3]:
            concept_info = await self.search_tech_concept(keyword)
            if concept_info.get("explanation"):
                tech_concepts.append(concept_info)

        # 4. 格式化输出
        context = self.format_for_review(company_info, tech_concepts)

        if context:
            logger.info(
                f"搜索上下文生成完成: 公司={company}, 技术概念数={len(tech_concepts)}"
            )
        else:
            logger.info(f"搜索未获取到有效上下文: 公司={company}")

        return context

    # ------------------------------------------------------------------
    # Provider 实现
    # ------------------------------------------------------------------

    async def _search_tavily(self, query: str, max_results: int) -> list[dict]:
        """Tavily API 搜索"""
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "basic",
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        results = []
        for item in data.get("results", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
                "score": item.get("score", 0.0),
            })
        return results

    async def _search_bing(self, query: str, max_results: int) -> list[dict]:
        """Bing Search API"""
        url = "https://api.bing.microsoft.com/v7.0/search"
        headers = {"Ocp-Apim-Subscription-Key": self.api_key}
        params = {"q": query, "count": max_results, "mkt": "zh-CN"}

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

        results = []
        for item in data.get("webPages", {}).get("value", []):
            results.append({
                "title": item.get("name", ""),
                "url": item.get("url", ""),
                "content": item.get("snippet", ""),
                "score": 0.0,
            })
        return results

    async def _search_serper(self, query: str, max_results: int) -> list[dict]:
        """Serper API (Google 搜索)"""
        url = "https://google.serper.dev/search"
        headers = {"X-API-KEY": self.api_key, "Content-Type": "application/json"}
        payload = {"q": query, "num": max_results, "gl": "cn", "hl": "zh-cn"}

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        results = []
        for item in data.get("organic", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "content": item.get("snippet", ""),
                "score": item.get("position", 0),
            })
        return results

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_snippet(text: str, keyword: str, max_len: int = 200) -> str:
        """从文本中提取包含关键词的片段"""
        idx = text.find(keyword)
        if idx == -1:
            return ""
        start = max(0, idx - 20)
        end = min(len(text), idx + max_len)
        snippet = text[start:end].strip()
        # 去掉不完整的首尾
        if start > 0:
            first_punct = -1
            for i, ch in enumerate(snippet):
                if ch in "。，、；！？.?,;!":
                    first_punct = i
                    break
            if first_punct > 0:
                snippet = snippet[first_punct + 1:]
        return snippet.strip()

    @staticmethod
    def _extract_tech_keywords(questions: list[str]) -> list[str]:
        """
        从面试问题列表中提取关键技术概念

        简单实现：提取常见技术术语模式
        """
        # 常见技术关键词模式
        tech_patterns = [
            r"(?:什么是|解释|介绍|讲讲|说说|谈谈)\s*(.+?)(?:[？?。，,]|$)",
            r"(.+?)(?:的原理|的区别|的优缺点|怎么实现|如何实现)",
        ]

        keywords = []
        seen = set()

        for q in questions:
            if not q:
                continue
            # 尝试模式匹配
            for pattern in tech_patterns:
                matches = re.findall(pattern, q)
                for m in matches:
                    term = m.strip()
                    if 2 <= len(term) <= 20 and term not in seen:
                        keywords.append(term)
                        seen.add(term)

            # 如果模式匹配没有提取到，使用问题本身（去除常见前缀）
            if not keywords or q not in str(keywords):
                cleaned = re.sub(
                    r"^(请|你|能|能否|可以)?(简单)?(介绍|讲讲|说说|解释|谈谈|描述)(一下)?",
                    "",
                    q.strip(),
                )
                cleaned = cleaned.strip("？?。，, ")
                if 2 <= len(cleaned) <= 30 and cleaned not in seen:
                    keywords.append(cleaned)
                    seen.add(cleaned)

        return keywords[:5]  # 最多返回5个关键词
