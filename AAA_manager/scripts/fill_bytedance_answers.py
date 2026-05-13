"""
fill_bytedance_answers.py - 第二步：根据人工筛选后的 10 题填答

读候选人对 15 题的筛选意见，整合成最终 10 题，填要点+话术+追问。
输出：岗位预测/字节跳动_大厂_260513_AI数据与安全一面.md（覆盖正式题库）

跑法：
    cd AAA_manager
    python scripts/fill_bytedance_answers.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from logger import get_logger
from config import INTERVIEW_REPO_PATH, PREP_OUTPUT_DIR
from llm_client import chat_completion
from knowledge.project_reader import ProjectReader

logger = get_logger("fill_bytedance_answers")

COMPANY = "字节跳动"
POSITION_LABEL = "AI应用开发实习生-AI数据与安全"
DATE = "260513"
OUTPUT_FILENAME = f"{COMPANY}_大厂_{DATE}_AI数据与安全一面.md"

PROJECTS = [
    {"name": "law_sea", "path": "D:/AI_model/law_sea"},
    {"name": "compliance_checker", "path": "D:/AI_model/compliance_checker"},
    {"name": "Agent_SFT_SHENWEI", "path": "D:/AI_model/Agent+SFT_SHENWEI"},
]
EXPERIENCE_FILE = Path(INTERVIEW_REPO_PATH) / "面经参考" / "字节_AI安全.md"

MAX_CHARS_PER_PROJECT = 6000
MAX_CHARS_EXPERIENCE = 3000

# ===== 人工筛选后的最终 10 题（含候选人约束） =====
# 字段说明：
#   id: 新编号
#   label: 🟢实锤 / 🟡推断 / 🔴面经真题 / 🟣安全岗必问
#   anchor: 锚点项目
#   topic: 主题标签
#   question: 具体题面
#   constraint: 候选人对这题的具体要求/实情约束（llm 必须遵守）
#   source_memo: 合并/新增说明（写入题目的"来源"字段）
QUESTIONS = [
    {
        "id": "Q1",
        "label": "🟢",
        "anchor": "Agent_SFT_SHENWEI + law_sea",
        "topic": "数据生成与清洗",
        "question": "介绍一下你在项目中做过的数据生成与清洗流程：Agent_SFT_SHENWEI 里 SFT 问答对是怎么从旅游攻略构造出来的？law_sea 的合同/风险点库数据是怎么清洗的？请说明自动化方法、人工介入时机和质量评估指标。",
        "constraint": "这题候选人要主讲：(1) Agent_SFT 的 SFT 数据构造流程（攻略→问答对→清洗→标注→评估）；(2) law_sea 的数据清洗——候选人明确说过'law_sea 真有做清洗'。注意：字节该岗位面经披露'岗位其实是为 Seed 提供数据'，这题是**主推题**。",
        "source_memo": "原 Q1（SFT 构造）+ 原 Q4（数据清洗）合并",
    },
    {
        "id": "Q2",
        "label": "🟢",
        "anchor": "compliance_checker",
        "topic": "清单/ZIP 数据安全防御",
        "question": "compliance_checker 项目接收用户上传的 ZIP 压缩包（含 S-01 清单表格 + S-02 附件），你如何防御来自清单或 ZIP 的攻击？请覆盖：(a) 结构化解析过程中的输入校验；(b) ZIP bomb（解压炸弹、嵌套过深）防御；(c) 路径穿越（`../` 溢出）防御；(d) 恶意文件类型过滤（可执行文件、宏文档等）。",
        "constraint": "严格锚定 compliance_checker 的 S-01/S-02 Spec。候选人的原话：'怎么防止来自清单或者 ZIP 的攻击'。要点必须结合文档中 S-02 ZIP 解压向量化的实际流程，不能瞎编没有的模块。",
        "source_memo": "原 Q3（清单/ZIP 结构化）+ 原 Q8（ZIP bomb/路径穿越）合并，方向改为防御",
    },
    {
        "id": "Q3",
        "label": "🟢",
        "anchor": "law_sea + Agent_SFT_SHENWEI",
        "topic": "Prompt 注入/越狱 + 敏感词拦截",
        "question": "在 law_sea 合同审查 Agent 和 Agent_SFT_SHENWEI 旅行 Agent 里，你如何防御 Prompt 注入和越狱攻击？以及你在 law_sea 里做的敏感词拦截，具体是怎么实现的（词库构建、拦截策略、误杀/漏放平衡）？",
        "constraint": "**重要：敏感词拦截在 law_sea 项目里真实做过**（候选人原话：'这个 law_sea 真有'）。要点要明确把敏感词写成 law_sea 的实锤，结合 law_sea 项目文档里'安全边界'场景（参考 rag_module_report / 场景三：意图识别与安全边界）。Prompt 注入部分可以结合两个 Agent 的用户输入入口谈防御。",
        "source_memo": "原 Q5（Prompt 注入）+ 原 Q6（敏感词，面经第7题）合并。面经真题 🔴。",
    },
    {
        "id": "Q4",
        "label": "🟢",
        "anchor": "compliance_checker",
        "topic": "多租户数据隔离",
        "question": "compliance_checker 是 B 端产品，多个项目/用户同时上传 ZIP 进行合规审查，你如何保证多租户数据隔离？请说明数据库层、文件系统层、会话/缓存层的隔离方案，以及防止越权访问（如通过 uploads/<uuid> 路径直接下载他人文件）的措施。",
        "constraint": "锚定 compliance_checker 的 uploads 目录结构（文档里看到 `uploads\\a29952e1-302e-4e4f-8d75-8ed168bc09d6\\checklist.md` 这种 UUID 路径，说明已有按会话/项目隔离的目录设计）。",
        "source_memo": "原 Q7 保留",
    },
    {
        "id": "Q5",
        "label": "🟢",
        "anchor": "law_sea + compliance_checker",
        "topic": "数据出境/涉密合规",
        "question": "law_sea 涉及海商法合同文本，compliance_checker 涉及企业项目手续，这些数据都可能包含敏感或涉密信息。你如何确保数据不出境、满足合规要求？请说明你在项目中采用的具体方案。",
        "constraint": "**重要：候选人的实际答案是'本地部署模型'**（候选人原话：'保留，实际上本地部署模型'）。要点要写清楚本地部署的具体方案（可能用了哪些开源模型在本地跑、对比云端 LLM 的优劣、部署架构）。不要只停留在'数据脱敏'这类泛谈。",
        "source_memo": "原 Q9 保留，答案方向：本地部署模型",
    },
    {
        "id": "Q6",
        "label": "🟡",
        "anchor": "compliance_checker",
        "topic": "VLM 对抗样本/印章伪造",
        "question": "compliance_checker 用 Qwen-VL 做印章和签字视觉检查。如果攻击者上传 PS 伪造或对抗样本的印章图片，VLM 可能误判为真。你会怎么设计防御方案？",
        "constraint": "**重要：候选人说'与甲方讨论过不做这个，但应该有一些想法'**。话术要**先坦诚项目里没落地这个防御**（甲方评估后认为风险可控），然后给出候选人自己思考的方案（图像元数据校验、噪声检测、多模态交叉验证、置信度阈值+人工兜底等）。这样既不编造又展现思考深度。标 🟡。",
        "source_memo": "原 Q10 保留，候选人：项目里未实现但有思路",
    },
    {
        "id": "Q7",
        "label": "🟣",
        "anchor": "Agent_SFT_SHENWEI",
        "topic": "数据/模型投毒检测",
        "question": "Agent_SFT_SHENWEI 用 LoRA 微调 Qwen3-0.6B。如果训练数据被恶意投毒（插入后门触发词），微调后的模型可能在特定输入下输出有害内容。你如何检测和防御数据投毒？",
        "constraint": "项目文档里没明确做过投毒检测，这题属于安全岗必问的开放题。要点可以走：训练数据异常检测（困惑度异常、分布偏移）、触发词扫描、微调后模型红队测试、关键输入的行为审计。要诚实标注项目里没具体实施，给思路。",
        "source_memo": "原 Q13 保留",
    },
    {
        "id": "Q8",
        "label": "🟣",
        "anchor": "Agent_SFT_SHENWEI",
        "topic": "模型权重泄露/LoRA 分发",
        "question": "Agent_SFT_SHENWEI 微调出的 LoRA checkpoint（qwen3-0_6b_lora_v1/v2）需要分发到生产环境。如果权重被窃取，可能被逆向还原训练数据或注入恶意行为。你如何保护 LoRA 权重安全？",
        "constraint": "锚定文档里真实存在的 `qwen3-0_6b_lora_v1_last_assistant/checkpoint-229` 和 `qwen3-0_6b_lora_v2_last_assistant/checkpoint-276`。要点包含加密存储、访问控制、分发链路完整性校验、模型水印等。标 🟣 安全岗必问。",
        "source_memo": "原 Q14 保留",
    },
    {
        "id": "Q9",
        "label": "🟣",
        "anchor": "全项目",
        "topic": "OWASP LLM Top 10 体系化",
        "question": "请从整体角度，结合 OWASP LLM Top 10（Prompt 注入、不安全输出处理、训练数据投毒、拒绝服务、供应链漏洞、敏感信息泄露、不安全插件设计、过度代理、过度依赖、模型窃取），说明你在 AI 应用开发中如何构建端到端安全体系（数据采集→训练→部署→交互四阶段）。请结合你 3 个项目的实际落地实践举例。",
        "constraint": "体系化收尾题。每个阶段挑 1-2 个项目实锤落地点举例（数据采集：law_sea 敏感词 / 训练：Agent_SFT 数据清洗 / 部署：本地模型 / 交互：compliance_checker 多租户）。展现候选人对安全的整体视野。",
        "source_memo": "原 Q15 保留",
    },
    {
        "id": "Q10",
        "label": "🟢",
        "anchor": "全项目",
        "topic": "HITL（Human-in-the-Loop）",
        "question": "在你 3 个项目中，哪些环节做了 Human-in-the-Loop（人机协同）？为什么选择在这些环节做 HITL 而不是全自动化？具体的 HITL 交互是怎么设计的（触发条件、人工操作界面、结果回流）？",
        "constraint": "**候选人新增题**。要覆盖 3 个项目的真实 HITL 场景：(1) law_sea 合同精审——用户手动选合同类型+审查立场（文档实锤）、最终报告可能需人工审阅；(2) compliance_checker——视觉检查置信度低时标记'待人工确认'（文档提到 CC_* 置信度阈值）、S-13 multimatch 场景的人工兜底（`s13_match_result_manual.md`）；(3) Agent_SFT——SFT 数据标注中人工审核问答对。结合 AI 数据安全视角谈：HITL 是缓解幻觉和对抗性输入的重要防线。",
        "source_memo": "候选人新增：Q16 = HITL",
    },
]


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
        logger.info(f"[{name}] loaded.")
    return "\n\n".join(blocks)


def load_experience() -> str:
    if not EXPERIENCE_FILE.exists():
        return ""
    raw = EXPERIENCE_FILE.read_text(encoding="utf-8").strip()
    return raw[:MAX_CHARS_EXPERIENCE] + ("\n... [面经已截断]" if len(raw) > MAX_CHARS_EXPERIENCE else "")


SYSTEM_PROMPT = """你是资深大厂 AI 面试官兼候选人教练，已和候选人一起筛选了 10 道最终题。现在你的任务是为这 10 题逐一写出**要点 + 面试话术 + 追问**。

## 候选人三个项目（事实锚点）
- **law_sea**：海商法 RAG + 合同精审；3 Agent（Agent1 验证合同类型 / Agent2 风险点并发审查 / Agent3 合并建议）基于 DeepSeek-V3；K-means 聚类风险点库（`<BB05>` 编码 + 频次码）；SSE 流式；**真实做过敏感词拦截**
- **compliance_checker**：手续合规审查 B 端系统；Clean Architecture 五层；MCP 协议；Qwen-VL（qwen3-vl-flash）视觉检查；S-01 清单表格解析 + S-02 ZIP 向量化 + S-03 完整性 + S-04 时效 + S-05 印章签名 + S-06 LangGraph 编排 + S-07 前后端；uploads/<uuid> 按项目隔离
- **Agent_SFT_SHENWEI**：Qwen3-0.6B + LoRA（v1 checkpoint-229 / v2 checkpoint-276）；Flask RAG 微服务 + Milvus（milvus-lite/Docker Standalone）+ RRF 混合检索；旅行 Agent Function Call（天气/路线/酒店）

## 核心原则（违反即不合格）
1. **严格遵守每题的"候选人约束"字段**——这是候选人亲自给的实情/方向，不能违背
2. **零编造**：要点必须有项目文档依据，关键事实带 `[来源: 文件名]` 溯源
3. **不确定就标注** `[?待候选人确认]`，禁止瞎填数字参数（LoRA rank、学习率、样本量等）
4. **面试话术口语化**：像候选人本人在讲，引用真实模块名/文件名
5. **HITL（Q10）必须找项目里真实的人工介入点**，不能光讲理论

## 输出 Markdown 格式（严格）

# 字节跳动_大厂_260513_AI数据与安全一面（人工筛选后填答版）

> 岗位：AI应用开发实习生-AI数据与安全
> 日期：2026-05-13
> 生成依据：面经 1 份（字节_AI安全.md）+ 3 个项目文档全层扫描 + 候选人人工筛选 10 题
> 标签：🟢=项目实锤 / 🟡=合理推断需确认 / 🔴=面经真题 / 🟣=安全岗必问

## Q1：[标签][锚点项目] 具体问题？

- **来源**：（从 source_memo 写，例如"原Q1+Q4合并 / 面经真题 / 候选人新增"）
- **考察点**：这题面试官想验证什么
- **要点**：
  - 事实1 [来源: 文件名]
  - 事实2 [来源: 文件名]
  - [?待候选人确认] 具体数字/参数
- **💬 面试话术**：
  > 候选人口吻的一段话，带项目真实模块名
- **追问**：
  - 追问1
  - 追问2
  - 追问3

（然后 Q2...Q10，**严格按顺序**）

## 考场提醒

3-5 条候选人明天上场前要特别注意的事项（针对这 10 题容易踩坑的地方，比如"Q5 本地部署方案具体用什么模型要答得出来"、"Q6 要先坦诚项目里没做再给思路"）。

## 禁止事项
- 禁止在 Q5 答案方向偏离"本地部署模型"
- 禁止在 Q6 硬说项目里做了对抗样本防御（候选人原话：项目里没做）
- 禁止在 Q3 把敏感词写成"行业常见方案"，敏感词是 law_sea 真实做过的
- 禁止代码围栏包裹整份答案

直接输出 Markdown 正文，不要任何前后缀说明。"""


def main():
    start = datetime.now()
    logger.info(f"开始填答 10 题 → {OUTPUT_FILENAME}")

    projects_ctx = load_projects_context()
    experience_ctx = load_experience()

    questions_json = json.dumps(QUESTIONS, ensure_ascii=False, indent=2)

    user_parts = [
        f"## 公司与岗位\n- 公司：{COMPANY}\n- 岗位：{POSITION_LABEL}\n- 日期：{DATE}",
        f"## 面经参考\n\n{experience_ctx}",
        f"## 3 个项目文档上下文（Tier 1+2+3）\n\n{projects_ctx}",
        f"## 人工筛选后的 10 题（含候选人约束）\n\n```json\n{questions_json}\n```",
        "请严格按系统提示 + 每题 constraint 字段填答，输出完整 Markdown 正文（Q1-Q10 + 考场提醒）。",
    ]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(user_parts)},
    ]

    logger.info("调用 LLM（10 题填答，预计 80-120s）...")
    body = chat_completion(messages=messages, temperature=0.3, max_tokens=8000).strip()

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
    print(f"\n✅ 正式题库：{out_path}")
    print(f"📊 题数：{q_count} / 预期 10  |  ⏱ 耗时：{elapsed:.1f}s")


if __name__ == "__main__":
    main()
