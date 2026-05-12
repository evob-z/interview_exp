# 面试问题分类规则

## 分类目标文件

将面试问题分类到以下 5 个文件之一：

### 1. 项目-law_sea.md（海商法智能问答系统）
关键词：晓海、MLAW、海商法、新法老法、版本感知、法律条文、海事纠纷
特征：涉及海商法 RAG 系统的架构、实现、优化

### 2. 项目-compliance_checker.md（合规审查助手）
关键词：合规审查、风电手续、环评、完整性匹配、项目核准、BM25检索（项目场景中）
特征：涉及文件完整性核查、混合检索、清单匹配

### 3. 项目-Agent_SFT_SHENWEI.md（旅行顾问 Agent）
关键词：旅行顾问、预研助手、0.6B、微调部署、SFT数据、Function Calling、个人电脑部署
特征：涉及小模型微调、Agent工具链、推理优化

### 4. AI_Coding.md（AI 辅助编程）
关键词：Qoder、Cursor、AI Coding、Skill、Rules、MCP、代码生成、AI工具选择、幻觉避免（AI编码场景）
特征：涉及 AI 编程工具使用经验、工作流、效率提升

### 5. 八股.md（通用技术原理）
关键词：RAG原理、Embedding、Rerank、BM25原理、微调时机、Agent范式、ReAct、Plan-and-Execute、幻觉治理（通用层面）、HTTP、HTTPS、缓存
特征：考察通用技术概念理解，不针对具体项目

## 分类判断规则

1. **项目 > 通用**：如果问题既涉及具体项目细节又涉及通用原理，优先归入项目类
2. **场景决定归属**：同样是 BM25，问"你们项目里 BM25 怎么用的" → 项目类；问"BM25 的原理" → 八股
3. **不确定时**：标记为 "八股"（最通用的兜底类别）

## LLM 分类 Prompt 模板

当 category_suggestion 不确定或为空时，使用以下 prompt 让 LLM 辅助判断：

```
请根据以下分类规则，判断面试问题应归入哪个类别。

分类选项（只返回类别名）：
- 项目-law_sea
- 项目-compliance_checker
- 项目-Agent_SFT_SHENWEI
- AI_Coding
- 八股

判断规则：
1. 涉及具体项目细节 → 归入对应项目类
2. 涉及 AI 编程工具使用 → AI_Coding
3. 通用技术原理 → 八股
4. 不确定 → 八股

面试问题：{question_text}
来源面经：{source_label}

请只返回类别名，不要解释。
```
