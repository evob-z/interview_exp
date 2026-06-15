"""
profile_manager.py - 用户画像管理器
综合简历、面试记录、投递情况等数据源，构建全面的求职者画像。
"""

import json
import os
import sys
from datetime import datetime
from typing import Optional

# 将上层目录加入 path，便于导入 llm_client
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logger import get_logger

logger = get_logger("profile_manager")

# 默认空画像模板
_EMPTY_PROFILE = {
    "basic_info": {
        "name": "",
        "education": "",
        "target_role": "",
        "skills": [],
        "experience_summary": "",
    },
    "skill_map": [],
    "interview_history": [],
    "strengths": [],
    "weaknesses": [],
    "frequently_asked_topics": [],
    "growth_trend": {
        "early_issues": [],
        "recent_improvements": [],
        "current_focus": [],
    },
    "application_stats": {
        "total_applied": 0,
        "interviews_completed": 0,
        "offers": 0,
        "target_companies": [],
    },
    "last_updated": None,
}


class ProfileManager:
    """用户画像管理器 - 构建、更新和查询求职者综合画像"""

    def __init__(self, profile_path: str, llm_client=None):
        """
        Args:
            profile_path: 画像 JSON 文件路径 (data/user_profile.json)
            llm_client: LLM 客户端模块（需要有 chat_completion 函数）
        """
        self.profile_path = profile_path
        self.llm_client = llm_client
        self.profile: dict = {}
        self._prompts_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts"
        )

    # ------------------------------------------------------------------
    # 基础 IO
    # ------------------------------------------------------------------

    def load(self) -> dict:
        """加载现有画像数据"""
        if not os.path.exists(self.profile_path):
            logger.info("画像文件不存在，使用空模板")
            self.profile = json.loads(json.dumps(_EMPTY_PROFILE))
            return self.profile

        try:
            with open(self.profile_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 补全可能缺失的字段
            for key, default in _EMPTY_PROFILE.items():
                if key not in data:
                    data[key] = json.loads(json.dumps(default))
            self.profile = data
            logger.info("画像加载成功")
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"画像文件读取失败，使用空模板: {e}")
            self.profile = json.loads(json.dumps(_EMPTY_PROFILE))

        return self.profile

    def save(self):
        """保存画像到文件"""
        self.profile["last_updated"] = datetime.now().isoformat(timespec="seconds")
        os.makedirs(os.path.dirname(self.profile_path), exist_ok=True)
        with open(self.profile_path, "w", encoding="utf-8") as f:
            json.dump(self.profile, f, ensure_ascii=False, indent=2)
        logger.info("画像已保存")

    # ------------------------------------------------------------------
    # 初始化 & 更新
    # ------------------------------------------------------------------

    def initialize(
        self,
        resume_text: str,
        interview_records: list[dict],
        excel_data: dict = None,
    ) -> dict:
        """
        初始化画像 - 从所有数据源批量构建

        Args:
            resume_text: 简历原始文本
            interview_records: 面试记录列表 [{company, date, questions, review}]
            excel_data: 投递情况 Excel 数据

        Returns:
            完整画像 dict
        """
        if not self.profile:
            self.load()

        # 尝试用 LLM 做综合分析
        if self.llm_client:
            try:
                profile_data = self._llm_initialize(
                    resume_text, interview_records, excel_data
                )
                self.profile.update(profile_data)
            except Exception as e:
                logger.warning(f"LLM 分析失败，降级为纯数据统计: {e}")
                self._fallback_initialize(resume_text, interview_records, excel_data)
        else:
            # 降级：纯数据统计
            self._fallback_initialize(resume_text, interview_records, excel_data)

        # 无论哪种路径，都补充存储面试历史和投递统计（LLM 可能不返回这些）
        if interview_records:
            history = []
            for rec in interview_records:
                history.append({
                    "company": rec.get("company", ""),
                    "company_type": rec.get("company_type", ""),
                    "date": rec.get("date", ""),
                    "round": rec.get("round", ""),
                    "question_count": len(rec.get("questions", [])),
                })
            self.profile["interview_history"] = history

        if excel_data:
            rows = excel_data.get("rows", [])
            status_counts = excel_data.get("status_counts", {})
            self.profile["application_stats"] = {
                "total_applied": excel_data.get("total", len(rows)),
                "interviews_completed": len(interview_records) if interview_records else 0,
                "offers": status_counts.get("offer", 0),
                "in_progress": status_counts.get("流程中", 0),
                "rejected": status_counts.get("已结束", 0),
                "no_response": status_counts.get("无消息", 0),
                "just_applied": status_counts.get("已投递", 0),
                "status_counts": status_counts,  # 完整状态分布
                "applications": rows,  # 保存完整投递记录供后续分析
            }

        self.save()

        # 清除旧的 brief 缓存并重新生成
        self.profile.pop("_cached_brief", None)
        self.save()
        self.get_brief_overview()  # 重新生成并缓存

        return self.profile

    def _llm_initialize(
        self, resume_text: str, interview_records: list[dict], excel_data: dict = None
    ) -> dict:
        """使用 LLM 分析并构建画像"""
        system_prompt = self._load_prompt("profile_system.md")

        # 构造用户消息
        user_content = "请根据以下数据源分析并构建求职者画像。\n\n"
        user_content += f"## 简历内容\n\n{resume_text}\n\n"

        if interview_records:
            user_content += "## 面试记录\n\n"
            for rec in interview_records:
                user_content += f"### {rec.get('company', '未知')} - {rec.get('date', '')}\n"
                questions = rec.get("questions", [])
                if questions:
                    for q in questions[:20]:  # 限制长度
                        if isinstance(q, dict):
                            user_content += f"- {q.get('question', '')}\n"
                        else:
                            user_content += f"- {q}\n"
                review = rec.get("review", "")
                if review:
                    user_content += f"\n复盘: {review[:500]}\n\n"

        if excel_data:
            user_content += f"## 投递情况\n\n{json.dumps(excel_data, ensure_ascii=False, indent=2)[:2000]}\n"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        response = self.llm_client.chat_completion(
            messages=messages,
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        return json.loads(response)

    def _fallback_initialize(
        self, resume_text: str, interview_records: list[dict], excel_data: dict = None
    ):
        """降级：纯数据统计构建画像"""
        # 基础统计面试记录
        if interview_records:
            history = []
            topic_counter: dict[str, dict] = {}
            for rec in interview_records:
                entry = {
                    "company": rec.get("company", ""),
                    "company_type": rec.get("company_type", ""),
                    "date": rec.get("date", ""),
                    "round": rec.get("round", ""),
                    "question_count": len(rec.get("questions", [])),
                    "categories": {},
                    "key_feedback": "",
                }
                history.append(entry)

                # 统计高频话题
                for q in rec.get("questions", []):
                    topic = q.get("category", "") if isinstance(q, dict) else ""
                    if topic:
                        if topic not in topic_counter:
                            topic_counter[topic] = {"count": 0, "companies": set()}
                        topic_counter[topic]["count"] += 1
                        topic_counter[topic]["companies"].add(rec.get("company", ""))

            self.profile["interview_history"] = history
            self.profile["frequently_asked_topics"] = [
                {
                    "topic": t,
                    "count": info["count"],
                    "companies": list(info["companies"]),
                }
                for t, info in sorted(
                    topic_counter.items(), key=lambda x: x[1]["count"], reverse=True
                )[:10]
            ]

        # 投递统计
        if excel_data:
            stats = self.profile["application_stats"]
            stats["total_applied"] = excel_data.get("total", 0)
            stats["interviews_completed"] = len(interview_records) if interview_records else 0

    def update_after_interview(
        self, company: str, questions: list[dict], review_content: str
    ) -> dict:
        """
        面试后增量更新画像

        Args:
            company: 公司名
            questions: 抽取的问题列表 [{question, category, ...}]
            review_content: 复盘内容

        Returns:
            更新后的画像
        """
        if not self.profile:
            self.load()

        # 1. 追加面试历史
        new_entry = {
            "company": company,
            "company_type": "",
            "date": datetime.now().strftime("%y%m%d"),
            "round": "",
            "question_count": len(questions),
            "categories": self._count_categories(questions),
            "key_feedback": review_content[:200] if review_content else "",
        }
        self.profile.setdefault("interview_history", []).append(new_entry)

        # 2. 更新技能验证
        self._update_skill_map(questions)

        # 3. 更新高频话题
        self._update_frequently_asked(questions, company)

        # 4. 如果 LLM 可用，更新优势/短板
        if self.llm_client and review_content:
            try:
                self._llm_update_analysis(company, questions, review_content)
            except Exception as e:
                logger.warning(f"LLM 增量分析失败: {e}")

        # 5. 更新统计
        stats = self.profile.setdefault("application_stats", {})
        stats["interviews_completed"] = len(self.profile.get("interview_history", []))

        self.save()
        return self.profile

    def _count_categories(self, questions: list[dict]) -> dict:
        """统计问题分类计数"""
        cats: dict[str, int] = {}
        for q in questions:
            cat = q.get("category", "其他") if isinstance(q, dict) else "其他"
            cats[cat] = cats.get(cat, 0) + 1
        return cats

    def _update_skill_map(self, questions: list[dict]):
        """根据新问题更新技能图谱"""
        skill_map = self.profile.setdefault("skill_map", [])
        skill_index = {s["skill"]: s for s in skill_map}

        for q in questions:
            if not isinstance(q, dict):
                continue
            # 从 category 或 tags 提取技能关键词
            skills_mentioned = []
            if q.get("category"):
                skills_mentioned.append(q["category"])
            if q.get("tags"):
                skills_mentioned.extend(q["tags"] if isinstance(q["tags"], list) else [q["tags"]])

            for skill in skills_mentioned:
                if skill in skill_index:
                    skill_index[skill]["asked_count"] += 1
                    skill_index[skill]["interview_verified"] = True
                    skill_index[skill]["last_asked"] = datetime.now().strftime("%y%m%d")
                else:
                    new_skill = {
                        "skill": skill,
                        "level": "待评估",
                        "interview_verified": True,
                        "asked_count": 1,
                        "last_asked": datetime.now().strftime("%y%m%d"),
                    }
                    skill_map.append(new_skill)
                    skill_index[skill] = new_skill

    def _update_frequently_asked(self, questions: list[dict], company: str):
        """更新高频被问话题"""
        topics = self.profile.setdefault("frequently_asked_topics", [])
        topic_index = {t["topic"]: t for t in topics}

        for q in questions:
            if not isinstance(q, dict):
                continue
            topic = q.get("category", "")
            if not topic:
                continue
            if topic in topic_index:
                topic_index[topic]["count"] += 1
                if company not in topic_index[topic]["companies"]:
                    topic_index[topic]["companies"].append(company)
            else:
                new_topic = {"topic": topic, "count": 1, "companies": [company]}
                topics.append(new_topic)
                topic_index[topic] = new_topic

        # 按频次排序，保留 top 15
        topics.sort(key=lambda x: x["count"], reverse=True)
        self.profile["frequently_asked_topics"] = topics[:15]

    def _llm_update_analysis(
        self, company: str, questions: list[dict], review_content: str
    ):
        """用 LLM 增量更新优势/短板分析"""
        current_strengths = self.profile.get("strengths", [])
        current_weaknesses = self.profile.get("weaknesses", [])

        prompt = (
            "根据以下最新面试信息，更新求职者的优势和短板列表。\n"
            "保留已有的合理条目，添加新发现，删除已改善的短板。\n\n"
            f"当前优势: {json.dumps(current_strengths, ensure_ascii=False)}\n"
            f"当前短板: {json.dumps(current_weaknesses, ensure_ascii=False)}\n\n"
            f"最新面试 - {company}:\n"
            f"问题数量: {len(questions)}\n"
            f"复盘内容: {review_content[:800]}\n\n"
            '请以 JSON 格式返回: {"strengths": [...], "weaknesses": [...], '
            '"growth_trend": {"early_issues": [...], "recent_improvements": [...], "current_focus": [...]}}'
        )

        messages = [
            {"role": "system", "content": "你是面试教练，负责分析求职者表现趋势。输出纯 JSON。"},
            {"role": "user", "content": prompt},
        ]

        response = self.llm_client.chat_completion(
            messages=messages,
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        result = json.loads(response)
        if "strengths" in result:
            self.profile["strengths"] = result["strengths"]
        if "weaknesses" in result:
            self.profile["weaknesses"] = result["weaknesses"]
        if "growth_trend" in result:
            self.profile["growth_trend"] = result["growth_trend"]

    # ------------------------------------------------------------------
    # 查询方法
    # ------------------------------------------------------------------

    def get_profile_summary(self) -> str:
        """获取画像摘要（用于注入 prompt）"""
        if not self.profile:
            self.load()

        p = self.profile
        basic = p.get("basic_info", {})

        parts = []
        if basic.get("name"):
            parts.append(f"姓名: {basic['name']}")
        if basic.get("target_role"):
            parts.append(f"目标岗位: {basic['target_role']}")
        if basic.get("education"):
            parts.append(f"学历: {basic['education']}")

        skills = basic.get("skills", [])
        if skills:
            parts.append(f"核心技能: {', '.join(skills[:8])}")

        strengths = p.get("strengths", [])
        if strengths:
            parts.append(f"优势: {'; '.join(strengths[:3])}")

        weaknesses = p.get("weaknesses", [])
        if weaknesses:
            parts.append(f"短板: {'; '.join(weaknesses[:3])}")

        history = p.get("interview_history", [])
        if history:
            parts.append(f"已完成面试: {len(history)} 场")
            recent = history[-3:]
            companies = [h.get("company", "") for h in recent if h.get("company")]
            if companies:
                parts.append(f"近期面试: {', '.join(companies)}")

        topics = p.get("frequently_asked_topics", [])
        if topics:
            top_topics = [t["topic"] for t in topics[:5]]
            parts.append(f"高频考点: {', '.join(top_topics)}")

        return "\n".join(parts) if parts else "画像尚未初始化"

    def get_brief_overview(self) -> str:
        """使用 LLM 生成一段精简的概括性画像描述（含成长趋势，带缓存）"""
        if not self.profile:
            self.load()

        # 如果有缓存，直接返回
        cached = self.profile.get("_cached_brief", "")
        if cached:
            return cached

        if not self.llm_client:
            return self._fallback_brief_overview()

        try:
            summary = self.get_profile_summary()
            strengths = self.profile.get("strengths", [])
            weaknesses = self.profile.get("weaknesses", [])
            topics = self.profile.get("frequently_asked_topics", [])
            growth = self.profile.get("growth_trend", {})
            app_stats = self.profile.get("application_stats", {})
            history = self.profile.get("interview_history", [])

            user_content = (
                "请用4-6句话概括这位求职者的当前状态，要求：\n"
                "1. 核心竞争力（1句）\n"
                "2. 成长变化（对比早期和近期表现，体现进步，1-2句）\n"
                "3. 当前短板和建议方向（1-2句）\n"
                "4. 求职进展概况（1句）\n\n"
                "要求：简洁有力，纯叙述文字，体现时间维度的变化和成长，不超过200字。\n\n"
                f"基础画像:\n{summary}\n\n"
                f"优势: {json.dumps(strengths[:3], ensure_ascii=False)}\n"
                f"短板: {json.dumps(weaknesses[:3], ensure_ascii=False)}\n"
                f"高频考点: {json.dumps([t['topic'] for t in topics[:5]], ensure_ascii=False)}\n\n"
                f"成长趋势:\n"
                f"  早期问题: {json.dumps(growth.get('early_issues', []), ensure_ascii=False)}\n"
                f"  近期改善: {json.dumps(growth.get('recent_improvements', []), ensure_ascii=False)}\n"
                f"  当前重点: {json.dumps(growth.get('current_focus', []), ensure_ascii=False)}\n\n"
                f"求职进展: 已投递{app_stats.get('total_applied', 0)}家，"
                f"完成面试{len(history)}场（请使用以上精确数字，不要自行估算）\n"
            )

            messages = [
                {"role": "system", "content": "你是面试教练，请用简洁概括的语言描述求职者画像。要体现出人的成长和变化，而非静态标签。输出纯文本。"},
                {"role": "user", "content": user_content},
            ]

            result = self.llm_client.chat_completion(
                messages=messages, temperature=0.3
            )

            # 生成完成后缓存
            self.profile["_cached_brief"] = result
            self.save()
            return result
        except Exception as e:
            logger.warning(f"LLM 概括失败: {e}")
            return self._fallback_brief_overview()

    def _fallback_brief_overview(self) -> str:
        """LLM 不可用时的简短概括"""
        p = self.profile
        basic = p.get("basic_info", {})
        strengths = p.get("strengths", [])
        weaknesses = p.get("weaknesses", [])

        name = basic.get("name", "用户")
        role = basic.get("target_role", "目标岗位未知")
        s = f"；优势：{strengths[0][:20]}" if strengths else ""
        w = f"；需提升：{weaknesses[0][:20]}" if weaknesses else ""
        return f"{name}，目标{role}{s}{w}。"

    def get_strengths(self) -> list[str]:
        """获取优势列表"""
        if not self.profile:
            self.load()
        return self.profile.get("strengths", [])

    def get_weaknesses(self) -> list[str]:
        """获取短板列表"""
        if not self.profile:
            self.load()
        return self.profile.get("weaknesses", [])

    def get_frequently_asked(self) -> list[dict]:
        """获取高频被问问题（反复出现的知识点）"""
        if not self.profile:
            self.load()
        return self.profile.get("frequently_asked_topics", [])

    def get_improvement_trend(self) -> dict:
        """获取成长趋势（早期 vs 近期表现对比）"""
        if not self.profile:
            self.load()
        return self.profile.get("growth_trend", {
            "early_issues": [],
            "recent_improvements": [],
            "current_focus": [],
        })

    # ------------------------------------------------------------------
    # LLM 生成建议 & 鼓励
    # ------------------------------------------------------------------

    def generate_advice(self) -> str:
        """
        生成个性化建议（使用 LLM）
        - 基于短板给出具体改进建议
        - 基于高频问题给出重点复习方向
        - 如果近期表现好，给予正面鼓励
        """
        if not self.profile:
            self.load()

        if not self.llm_client:
            return self._fallback_advice()

        try:
            system_prompt = self._load_prompt("advice_system.md")
            summary = self.get_profile_summary()
            weaknesses = self.get_weaknesses()
            topics = self.get_frequently_asked()
            trend = self.get_improvement_trend()

            user_content = (
                "请根据以下用户画像，给出个性化面试改进建议。\n\n"
                f"## 画像摘要\n{summary}\n\n"
                f"## 当前短板\n{json.dumps(weaknesses, ensure_ascii=False)}\n\n"
                f"## 高频考点\n{json.dumps(topics[:5], ensure_ascii=False)}\n\n"
                f"## 成长趋势\n{json.dumps(trend, ensure_ascii=False)}\n"
            )

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ]

            return self.llm_client.chat_completion(
                messages=messages, temperature=0.7
            )
        except Exception as e:
            logger.warning(f"生成建议失败: {e}")
            return self._fallback_advice()

    def generate_encouragement(self) -> str:
        """
        生成鼓励和安慰（使用 LLM）
        - 肯定进步和优势
        - 正面引导情绪
        - 给出下一步行动建议
        """
        if not self.profile:
            self.load()

        if not self.llm_client:
            return self._fallback_encouragement()

        try:
            system_prompt = self._load_prompt("advice_system.md")
            strengths = self.get_strengths()
            trend = self.get_improvement_trend()
            history = self.profile.get("interview_history", [])

            user_content = (
                "请给这位求职者一些真诚的鼓励和安慰。\n\n"
                f"## 优势\n{json.dumps(strengths, ensure_ascii=False)}\n\n"
                f"## 成长趋势\n{json.dumps(trend, ensure_ascii=False)}\n\n"
                f"## 面试经历\n已完成 {len(history)} 场面试\n"
            )

            if trend.get("recent_improvements"):
                user_content += f"\n近期进步: {', '.join(trend['recent_improvements'])}\n"

            messages = [
                {"role": "system", "content": system_prompt + "\n\n当前任务：生成鼓励和安慰，而非改进建议。"},
                {"role": "user", "content": user_content},
            ]

            return self.llm_client.chat_completion(
                messages=messages, temperature=0.8
            )
        except Exception as e:
            logger.warning(f"生成鼓励失败: {e}")
            return self._fallback_encouragement()

    # ------------------------------------------------------------------
    # 降级模板
    # ------------------------------------------------------------------

    def _fallback_advice(self) -> str:
        """LLM 不可用时的固定建议模板"""
        weaknesses = self.get_weaknesses()
        topics = self.get_frequently_asked()

        lines = ["📋 面试改进建议：\n"]

        if weaknesses:
            lines.append("【需要改进的方向】")
            for i, w in enumerate(weaknesses[:3], 1):
                lines.append(f"  {i}. {w}")
            lines.append("")

        if topics:
            lines.append("【高频考点 - 建议重点复习】")
            for t in topics[:5]:
                lines.append(f"  - {t['topic']}（被问 {t['count']} 次）")
            lines.append("")

        if not weaknesses and not topics:
            lines.append("暂无足够数据生成建议，请先完成更多面试记录的录入。")

        return "\n".join(lines)

    def _fallback_encouragement(self) -> str:
        """LLM 不可用时的固定鼓励模板"""
        strengths = self.get_strengths()
        history = self.profile.get("interview_history", [])
        trend = self.get_improvement_trend()

        lines = ["💪 加油！\n"]

        if history:
            lines.append(f"你已经完成了 {len(history)} 场面试，每一场都是宝贵的经验积累。")

        if strengths:
            lines.append(f"\n你的优势很明显：{'; '.join(strengths[:2])}。")

        if trend.get("recent_improvements"):
            lines.append(f"\n近期进步：{', '.join(trend['recent_improvements'])}。")
            lines.append("这说明你的努力正在看到回报！")

        lines.append("\n继续保持，相信下一次面试会更好。每次面试都让你离目标更近一步。")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def _load_prompt(self, filename: str) -> str:
        """加载 prompt 文件"""
        path = os.path.join(self._prompts_dir, filename)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        logger.warning(f"Prompt 文件不存在: {path}")
        return ""
