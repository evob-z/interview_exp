"""profile_manager.py 的单元测试。"""

import json

import pytest


def _new_manager(tmp_path, llm_client=None):
    from profile.profile_manager import ProfileManager
    path = tmp_path / "user_profile.json"
    return ProfileManager(str(path), llm_client=llm_client), path


# ────────── load ──────────

def test_load_missing_file_returns_empty_template(tmp_path):
    mgr, _ = _new_manager(tmp_path)
    data = mgr.load()
    assert "basic_info" in data
    assert data["interview_history"] == []
    assert data["application_stats"]["total_applied"] == 0


def test_load_broken_json_falls_back(tmp_path):
    mgr, path = _new_manager(tmp_path)
    path.write_text("{broken", encoding="utf-8")
    data = mgr.load()
    assert data["interview_history"] == []


def test_load_fills_missing_fields(tmp_path):
    mgr, path = _new_manager(tmp_path)
    path.write_text(json.dumps({"basic_info": {"name": "张三"}}), encoding="utf-8")
    data = mgr.load()
    assert data["basic_info"]["name"] == "张三"
    assert "interview_history" in data
    assert "application_stats" in data


def test_save_load_roundtrip(tmp_path):
    mgr, _ = _new_manager(tmp_path)
    mgr.load()
    mgr.profile["basic_info"]["name"] = "李四"
    mgr.save()

    mgr2, _ = _new_manager(tmp_path)
    data = mgr2.load()
    assert data["basic_info"]["name"] == "李四"
    assert data["last_updated"] is not None


# ────────── 纯逻辑函数 ──────────

def test_count_categories(tmp_path):
    mgr, _ = _new_manager(tmp_path)
    mgr.load()
    cats = mgr._count_categories([
        {"category": "八股"},
        {"category": "八股"},
        {"category": "AI_Coding"},
        {},  # 没 category 归"其他"
    ])
    assert cats == {"八股": 2, "AI_Coding": 1, "其他": 1}


def test_update_skill_map_adds_and_increments(tmp_path):
    mgr, _ = _new_manager(tmp_path)
    mgr.load()

    mgr._update_skill_map([{"category": "LangChain"}])
    mgr._update_skill_map([{"category": "LangChain"}])
    mgr._update_skill_map([{"category": "RAG"}])

    skills = {s["skill"]: s for s in mgr.profile["skill_map"]}
    assert skills["LangChain"]["asked_count"] == 2
    assert skills["LangChain"]["interview_verified"] is True
    assert skills["RAG"]["asked_count"] == 1


def test_update_frequently_asked_sorts_and_caps(tmp_path):
    mgr, _ = _new_manager(tmp_path)
    mgr.load()

    mgr._update_frequently_asked([{"category": "A"}, {"category": "B"}], "公司1")
    mgr._update_frequently_asked([{"category": "A"}, {"category": "A"}], "公司2")

    topics = {t["topic"]: t for t in mgr.profile["frequently_asked_topics"]}
    assert topics["A"]["count"] == 3
    assert "公司1" in topics["A"]["companies"]
    assert "公司2" in topics["A"]["companies"]
    assert topics["B"]["count"] == 1
    # 排序：A 在 B 之前
    assert mgr.profile["frequently_asked_topics"][0]["topic"] == "A"


def test_fallback_initialize_populates_stats(tmp_path):
    mgr, _ = _new_manager(tmp_path)
    mgr.load()
    records = [
        {"company": "蚂蚁", "questions": [{"category": "八股"}, {"category": "AI_Coding"}]},
        {"company": "美团", "questions": [{"category": "八股"}]},
    ]
    mgr._fallback_initialize("简历文本", records, excel_data={"total": 10})
    assert len(mgr.profile["interview_history"]) == 2
    topics = {t["topic"]: t for t in mgr.profile["frequently_asked_topics"]}
    assert topics["八股"]["count"] == 2


# ────────── 降级模板非空 ──────────

def test_fallback_templates_nonempty(tmp_path):
    mgr, _ = _new_manager(tmp_path)
    mgr.load()
    assert mgr._fallback_brief_overview()
    assert mgr._fallback_advice()
    assert mgr._fallback_encouragement()


# ────────── update_after_interview ──────────

class _FakeLLM:
    def __init__(self):
        self.calls = 0

    def chat_completion(self, messages, **kwargs):
        self.calls += 1
        return json.dumps({
            "strengths": ["表达清晰"],
            "weaknesses": ["算法基础薄弱"],
            "growth_trend": {
                "early_issues": [],
                "recent_improvements": ["对 Agent 理解更深"],
                "current_focus": ["算法"],
            },
        }, ensure_ascii=False)


def test_update_after_interview_updates_history_and_skills(tmp_path):
    fake = _FakeLLM()
    mgr, _ = _new_manager(tmp_path, llm_client=fake)
    mgr.load()

    mgr.update_after_interview(
        company="蚂蚁",
        questions=[{"category": "LangChain"}, {"category": "八股"}],
        review_content="整体表现尚可",
    )

    assert len(mgr.profile["interview_history"]) == 1
    assert mgr.profile["interview_history"][0]["company"] == "蚂蚁"
    assert mgr.profile["application_stats"]["interviews_completed"] == 1
    skills = {s["skill"] for s in mgr.profile["skill_map"]}
    assert "LangChain" in skills
    # LLM 被调用并写入优势/短板
    assert fake.calls >= 1
    assert mgr.profile["strengths"] == ["表达清晰"]


# ────────── get_brief_overview 缓存 ──────────

class _CountingLLM:
    def __init__(self):
        self.calls = 0

    def chat_completion(self, messages, **kwargs):
        self.calls += 1
        return "这是 LLM 生成的概括"


def test_get_brief_overview_caches(tmp_path):
    llm = _CountingLLM()
    mgr, _ = _new_manager(tmp_path, llm_client=llm)
    mgr.load()

    first = mgr.get_brief_overview()
    second = mgr.get_brief_overview()
    assert first == second
    # 第二次命中缓存
    assert llm.calls == 1
