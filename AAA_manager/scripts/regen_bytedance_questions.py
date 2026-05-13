"""
regen_bytedance_questions.py - 只出题、不填答（第一步）

配合"面试题整理强制两步流程：先出题后填答"。按第一轮「数据+安全」双视角
的 15 题设计重跑一遍，只输出问题清单，供候选人人工审核。

输出：岗位预测/_draft_字节跳动_260513_questions.md（不覆盖正式题库文件）

跑法：
    cd AAA_manager
    python scripts/regen_bytedance_questions.py
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logger import get_logger
from config import INTERVIEW_REPO_PATH, PREP_OUTPUT_DIR
from llm_client import chat_completion
from knowledge.project_reader import ProjectReader

logger = get_logger("regen_bytedance_questions")

# ===== 本次任务参数 =====
COMPANY = "字节跳动"
POSITION_LABEL = "AI应用开发实习生-AI数据与安全"
DATE = "260513"
OUTPUT_FILENAME = "_draft_字节跳动_260513_questions.md"

PROJECTS = [
    {"name": "law_sea", "path": "D:/AI_model/law_sea"},
    {"name": "compliance_checker", "path": "D:/AI_model/compliance_checker"},
    {"name": "Agent_SFT_SHENWEI", "path": "D:/AI_model/Agent+SFT_SHENWEI"},
]

EXPERIENCE_FILE = Path(INTERVIEW_REPO_PATH) / "面经参考" / "字节_AI安全.md"

MAX_CHARS_PER_PROJECT = 6000
MAX_CHARS_EXPERIENCE = 3000


def load_projects_context() -> str:
    reader = ProjectReader(projects=PROJECTS)
    reader.load_startup()
    blocks: list[str] = []
    for proj in PROJECTS:
        name = proj["name"]
        reader.load_tier(name, 3)
        ctx = reader.get_context(name, max_tier=3)
        if not ctx:
            continue
        if len(ctx) > MAX_CHARS_PER_PROJECT:
            ctx = ctx[:MAX_CHARS_PER_PROJECT] + f"\n... [项目 {name} 文档已截断]"
        blocks.append(ctx)
        summary = reader.get_tier_summary(name)
        logger.info(f"[{name}] tiers: {summary}")
    return "\n\n".join(blocks)


def load_experience() -> str:
    if not EXPERIENCE_FILE.exists():
        logger.warning(f"面经文件不存在: {EXPERIENCE_FILE}")
        return ""
    raw = EXPERIENCE_FILE.read_text(encoding="utf-8").strip()
    return raw[:MAX_CHARS_EXPERIENCE] + ("\n... [面经已截断]" if len(raw) > MAX_CHARS_EXPERIENCE else "")


SYSTEM_PROMPT = """你是资深大厂 AI 面试官。目标：为字节跳动「AI应用开发实习生-AI数据与安全」岗生成 15 道高命中预测题的**问题清单**（只出题，不写答案）。

## 关键情报（必须体现到题目里）
- 岗位核心是「AI 数据与安全」——定位通常是为 Seed/大模型团队提供训练/评估数据，安全方向覆盖数据清洗 / Prompt 注入 / 越狱 / 敏感词 / 多租户 / 数据出境 / 投毒
- 候选人 3 个项目：
  - **law_sea**：海商法 RAG + 合同精审（3 个 Agent 基于 DeepSeek-V3，风险点库 K-means 聚类，SSE 流式）
  - **compliance_checker**：手续合规审查（Clean Architecture 五层，MCP 协议，多模态 Qwen-VL 视觉检查，ZIP 解压+清单表格解析 S-01~S-07，涉及多上传用户场景）
  - **Agent_SFT_SHENWEI**：Qwen3-0.6B LoRA 微调 + Flask RAG 微服务（Milvus 混合检索 RRF，旅行 Agent Function Call）
- 面经真题清单见上下文中的「字节_AI安全.md」，需要**显式复现**至少 3 题

## 15 题结构（严格按此设计）
- **Q1-Q4 数据侧（4 题）**：
  - Q1 Agent_SFT SFT 数据构造全流程（怎么从攻略→问答对→清洗→标注→评估）
  - Q2 law_sea 风险点库数据加工（案例+法条+模板如何汇合，K-means 怎么归一化）
  - Q3 compliance_checker 清单/ZIP 数据如何结构化（S-01 表格解析 + S-02 ZIP 向量化）
  - Q4 数据清洗与质量评估（去重/低质过滤/人工审核成本怎么权衡）
- **Q5-Q7 安全侧（3 题）**：
  - Q5 Prompt 注入/越狱防护（合同审查/旅行 Agent 场景里怎么拦）
  - Q6 敏感词拦截（面经真题，可以打八股 + 一点项目结合）
  - Q7 多租户数据隔离（锚定 compliance_checker，多用户上传 ZIP 如何互不可见）
- **Q8/Q10/Q14 攻击面（3 题）**：
  - Q8 ZIP bomb / 路径穿越（锚定 compliance_checker S-02 ZIP 解压）
  - Q10 VLM 对抗样本 / 印章伪造（锚定 Qwen-VL 视觉检查）
  - Q14 模型权重泄露 / LoRA 权重分发风险（锚定 Agent_SFT LoRA checkpoint）
- **Q9 合规（1 题）**：数据出境 / 涉密信息（海商法文本 + 项目手续都有合规压力）
- **Q11-Q12 面经真题复现（2 题）**：
  - Q11 RAG 切片粒度（面经第5题）
  - Q12 Function Call 流程（面经第13题）
- **Q13 + Q15 体系化收尾（2 题）**：
  - Q13 数据/模型投毒检测
  - Q15 OWASP LLM Top 10 / 整体安全体系

## 输出格式（严格）

# 字节跳动_大厂_260513_AI数据与安全一面（问题清单·待人工筛选）

> 岗位：AI应用开发实习生-AI数据与安全
> 用途：**这一步只出题**，待候选人人工圈选/修改后，再触发第二步"填答"
> 标签：🟢=项目文档实锤 / 🟡=合理推断需确认 / 🔴=面经真题 / 🟣=安全岗核心必问

## 题目清单

| 编号 | 标签 | 锚点项目 | 类别 | 考察点 | 问题 |
|---|---|---|---|---|---|
| Q1 | 🟢 | Agent_SFT_SHENWEI | 数据侧 | SFT数据构造 | ...具体问题... |
| Q2 | ... | ... | ... | ... | ... |
（共 15 行）

## 设计说明
逐题一句话说明为什么挑这题、情报依据是什么（比如"来自面经第X题"或"compliance_checker 的 S-02 Spec 明确了 ZIP 解压流程"）。

## 人工筛选模板
请在下方标注每题处理意见（保留/修改/删除+原因），确认后执行第二步填答：

- [ ] Q1：
- [ ] Q2：
- ...
- [ ] Q15：

---

## 禁止事项（违反直接不合格）
1. 禁止写「要点」「面试话术」「追问」「答案」——**这一步只出题**
2. 禁止锚点项目选错：多租户必须 compliance_checker，SFT 微调必须 Agent_SFT，合同审查必须 law_sea
3. 禁止编造文档里没有的模块名
4. 每题必须在「设计说明」段给出一句情报依据（面经第X题 / 文档X.md / 岗位JD推断）

直接输出 Markdown 正文，不要任何前后缀。"""


def main():
    start = datetime.now()
    logger.info(f"开始出题（只出问题清单，输出：{OUTPUT_FILENAME}）")

    projects_ctx = load_projects_context()
    experience_ctx = load_experience()

    logger.info(f"上下文：projects={len(projects_ctx)}, experience={len(experience_ctx)}")

    user_parts = [
        f"## 公司与岗位\n- 公司：{COMPANY}\n- 岗位：{POSITION_LABEL}\n- 日期：{DATE}",
        f"## 面经参考（字节同岗位一面真题，必须显式复现 ≥3 题）\n\n{experience_ctx or '（未提供）'}",
        f"## 3 个项目文档上下文（Tier 1+2+3）\n\n{projects_ctx or '（未读取到）'}",
        "请严格按系统提示输出 15 题问题清单，**只出题目，不写答案/要点/话术/追问**。",
    ]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]

    logger.info("调用 LLM...")
    body = chat_completion(messages=messages, temperature=0.3, max_tokens=4000).strip()

    if body.startswith("```"):
        import re as _re
        body = _re.sub(r"^```[a-zA-Z]*\n", "", body, count=1)
        body = _re.sub(r"\n```\s*$", "", body, count=1)

    out_dir = Path(INTERVIEW_REPO_PATH) / PREP_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / OUTPUT_FILENAME
    out_path.write_text(body + "\n", encoding="utf-8")

    elapsed = (datetime.now() - start).total_seconds()
    logger.info(f"完成：{out_path} | 耗时={elapsed:.1f}s")
    print(f"\n✅ 问题清单（草稿）：{out_path}")
    print(f"⏱ 耗时：{elapsed:.1f}s")
    print("\n下一步：人工审核 15 题 → 确认后触发填答脚本（覆盖正式题库文件）")


if __name__ == "__main__":
    main()
