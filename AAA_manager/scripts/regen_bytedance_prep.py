"""
regen_bytedance_prep.py - 一次性重生成字节 AI 数据与安全岗预测题

相比 `python main.py prepare` 命令补了三个洞：
1. 手动传 3 个项目（绕过 .env PROJECT_CONFIGS 缺 compliance_checker 的问题）
2. ProjectReader max_tier 从 2 抬到 3（纳入 .qoder/repowiki + 零散设计报告）
3. 注入「面经参考/字节_AI安全.md」（V1 面经驱动需求的最小实现）

输出：岗位预测/字节跳动_大厂_260513_AI数据与安全一面.md（覆盖原文件）

跑法：
    cd AAA_manager
    python scripts/regen_bytedance_prep.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

# 让脚本能 import AAA_manager 包内模块
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logger import get_logger
from config import INTERVIEW_REPO_PATH, PREP_OUTPUT_DIR, RESUME_DIR
from llm_client import chat_completion
from knowledge.project_reader import ProjectReader
from knowledge.resume_reader import ResumeReader
from knowledge.question_bank import QuestionBank

logger = get_logger("regen_bytedance_prep")

# ===== 硬编码的本次任务参数 =====
COMPANY = "字节跳动"
POSITION_LABEL = "AI应用开发实习生-AI数据与安全"
DATE = "260513"
OUTPUT_FILENAME = f"{COMPANY}_大厂_{DATE}_AI数据与安全一面.md"

# 3 个目标项目（与 .rules 一致，含 compliance_checker）
PROJECTS = [
    {"name": "law_sea", "path": "D:/AI_model/law_sea"},
    {"name": "compliance_checker", "path": "D:/AI_model/compliance_checker"},
    {"name": "Agent_SFT_SHENWEI", "path": "D:/AI_model/Agent+SFT_SHENWEI"},
]

# 面经参考文件
EXPERIENCE_FILE = Path(INTERVIEW_REPO_PATH) / "面经参考" / "字节_AI安全.md"

# 上下文长度上限（避免超模型窗口）
MAX_CHARS_PER_PROJECT = 6000   # Tier 1+2+3 合计
MAX_CHARS_RESUME = 3000
MAX_CHARS_EXPERIENCE = 3000
MAX_CHARS_EXISTING = 4000


def load_projects_context() -> str:
    """直接用 ProjectReader 拉 Tier 1+2+3"""
    reader = ProjectReader(projects=PROJECTS)
    reader.load_startup()  # Tier 1+2

    blocks: list[str] = []
    for proj in PROJECTS:
        name = proj["name"]
        # 额外触发 Tier 3
        reader.load_tier(name, 3)
        ctx = reader.get_context(name, max_tier=3)
        if not ctx:
            continue
        if len(ctx) > MAX_CHARS_PER_PROJECT:
            ctx = ctx[:MAX_CHARS_PER_PROJECT] + f"\n... [项目 {name} 文档已截断]"
        blocks.append(ctx)

        # 打印摘要方便调试
        summary = reader.get_tier_summary(name)
        logger.info(f"[{name}] tiers: {summary}")
    return "\n\n".join(blocks)


def load_resume() -> str:
    try:
        reader = ResumeReader(str(Path(INTERVIEW_REPO_PATH) / RESUME_DIR))
        raw = (reader.get_resume_info().get("raw_text") or "").strip()
        return raw[:MAX_CHARS_RESUME] + ("\n... [简历已截断]" if len(raw) > MAX_CHARS_RESUME else "")
    except Exception as e:
        logger.warning(f"简历读取失败: {e}")
        return ""


def load_experience() -> str:
    if not EXPERIENCE_FILE.exists():
        logger.warning(f"面经文件不存在: {EXPERIENCE_FILE}")
        return ""
    raw = EXPERIENCE_FILE.read_text(encoding="utf-8").strip()
    return raw[:MAX_CHARS_EXPERIENCE] + ("\n... [面经已截断]" if len(raw) > MAX_CHARS_EXPERIENCE else "")


def load_existing_brief() -> str:
    try:
        qb = QuestionBank(str(Path(INTERVIEW_REPO_PATH) / "问题库"))
        qb.load()
        lines = []
        by_cat: dict[str, list[str]] = {}
        for q in qb.questions:
            by_cat.setdefault(q["category"], []).append(f"Q{q['id']}：{q['text']}")
        for cat, items in by_cat.items():
            lines.append(f"[{cat}] 前 8 条：")
            for it in items[:8]:
                lines.append(f"  - {it}")
        text = "\n".join(lines)
        return text[:MAX_CHARS_EXISTING]
    except Exception as e:
        logger.warning(f"题库读取失败: {e}")
        return ""


SYSTEM_PROMPT = """你是一位资深大厂 AI 面试官，目标是为候选人生成**高度贴合真实项目细节**的面试预测题。

## 核心原则（违反直接不合格）
1. **零编造**：每一条「要点」必须有候选人项目文档中的事实依据，禁止任何行业通用假设被写成项目事实
2. **强制溯源**：每条关键事实后用 `[来源: {文件名}]` 标注出处（来自候选人项目上下文章节中出现的文件名）
3. **不确定就标注**：项目文档没有明确写的细节，不要瞎填数字/参数，改成 `[?待候选人确认]` 或者省略
4. **面经优先**：面经里真实出现过的问题必须复现（标注"[面经真题]"），并结合候选人项目给出话术
5. **面试话术接地气**：话术要"像候选人本人在面试当场说话"，引用候选人文档里的模块名、文件名、真实数据

## 输出 Markdown 模板（严格遵守）
```
# {公司}_大厂_{日期}_{岗位}（预测题）

> 岗位：{岗位全称}
> 生成依据：面经 1 份 + 3 个项目（law_sea / compliance_checker / Agent_SFT_SHENWEI）文档全层扫描
> 使用说明：🟢=项目文档实锤 / 🟡=合理推断需确认 / 🔴=面经真题 / 纯 Q=自由发挥题

## Q1：[🟢/🟡/🔴][题目主题] 具体问题？
- **来源**：岗位预测（或[面经真题]/[项目深挖-{项目名}]）
- **考察点**：这题面试官想验证什么能力
- **要点**：
  - 事实点 1 [来源: README.md]
  - 事实点 2 [来源: project_understanding.md]
  - [?待候选人确认] 具体数字/参数你项目里是多少
- **💬 面试话术**：
  > 结合项目真实模块名、文件名的口语化回答...
- **追问**：
  - 追问 1
  - 追问 2
```

## 题量与分布
- 总计 12-15 题
- 🔴 面经真题复现：3-5 题（必有「敏感词拦截」「Function Call 原理」「RAG 切片粒度」「Python 装饰器」「数据构造/评估」等面经命中题）
- 🟢 项目实锤深挖：6-8 题（每个项目 2-3 题，基于文档真实事实）
- 🟡 合理推断题：1-3 题（项目明显有该模块但文档细节未覆盖）

## 禁止事项
- 禁止写"业界常见做法是..."然后套到候选人项目上
- 禁止编造具体数字（例如 "LoRA rank=16"、"k1=1.2"、"样本几百条" 除非文档原文出现）
- 禁止编造不存在的模块名/文件名
- 禁止输出代码围栏（```）包裹整份答案

直接输出 Markdown 正文，不要任何前后缀说明。"""


def main():
    start = datetime.now()
    logger.info(f"开始重生成：{OUTPUT_FILENAME}")

    projects_ctx = load_projects_context()
    resume_ctx = load_resume()
    experience_ctx = load_experience()
    existing_ctx = load_existing_brief()

    logger.info(
        f"上下文长度：projects={len(projects_ctx)}, resume={len(resume_ctx)}, "
        f"experience={len(experience_ctx)}, existing={len(existing_ctx)}"
    )

    user_parts = [
        f"## 公司与岗位\n- 公司：{COMPANY}\n- 岗位：{POSITION_LABEL}\n- 日期：{DATE}",
        f"## 面经参考（同公司/同方向真实一面，请重点复现其中问题）\n\n{experience_ctx or '（未提供）'}",
        f"## 候选人简历\n\n{resume_ctx or '（未读取到）'}",
        f"## 候选人三个项目的完整文档上下文（Tier 1+2+3）\n\n{projects_ctx or '（未读取到）'}",
        f"## 现有题库摘要（避免重复出题）\n\n{existing_ctx or '（空）'}",
        "请严格按系统提示的原则和模板输出，重要：要点必须带 [来源: 文件名] 溯源，拿不到出处用 [?待候选人确认]。",
    ]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]

    logger.info("调用 LLM...")
    body = chat_completion(messages=messages, temperature=0.3, max_tokens=6000).strip()

    # 剥代码围栏
    if body.startswith("```"):
        import re as _re
        body = _re.sub(r"^```[a-zA-Z]*\n", "", body, count=1)
        body = _re.sub(r"\n```\s*$", "", body, count=1)

    out_dir = Path(INTERVIEW_REPO_PATH) / PREP_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / OUTPUT_FILENAME
    out_path.write_text(body + "\n", encoding="utf-8")

    elapsed = (datetime.now() - start).total_seconds()
    import re as _re
    q_count = len(_re.findall(r"^#{2,4}\s*Q\d+[：:]", body, _re.MULTILINE))
    logger.info(f"完成：{out_path} | 题数={q_count} | 耗时={elapsed:.1f}s")
    print(f"\n✅ 输出文件：{out_path}")
    print(f"📊 题数：{q_count}  |  耗时：{elapsed:.1f}s")


if __name__ == "__main__":
    main()
