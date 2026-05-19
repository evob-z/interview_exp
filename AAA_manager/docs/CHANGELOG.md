# 文档变更记录

本文件记录项目文档的所有重要变更，便于追踪文档演进历史。

## 格式说明

每次变更记录包含：
- **日期**：变更发生日期
- **文档**：涉及的文档名称
- **类型**：新增 / 更新 / 修订 / 删除
- **摘要**：简要描述变更内容

---

## [2026-05-17] 文档体系初始化

| 文档 | 类型 | 摘要 |
|------|------|------|
| 01_需求文档.md | 新增 | 项目功能需求、业务逻辑和用户场景初稿 |
| 02_技术选型报告.md | 新增 | 各技术栈选择理由与对比分析初稿 |
| 03_系统架构设计.md | 新增 | 整体架构、模块划分和组件关系初稿 |
| 04_API接口文档.md | 新增 | 接口定义、参数和调用示例初稿 |
| 05_部署配置文档.md | 新增 | 环境搭建、配置项和部署流程初稿 |
| 06_开发规范文档.md | 新增 | 代码风格、提交规范和协作流程初稿 |
| 07_测试策略文档.md | 新增 | 测试范围、方法和质量标准初稿 |
| CHANGELOG.md | 新增 | 文档变更记录机制建立 |

---

## [2026-05-17] 岗位预测 Agent 重构 + 部门字段

### 代码层改动

| 文件 | 类型 | 摘要 |
|------|------|------|
| `core/prepare_agent.py` | 新增 | 手写 ReAct Loop（OpenAI function calling），8工具 + submit_final 终结，替代 Pydantic AI 方案 |
| `preparer.py` | 更新 | `parse_spec` 支持四元组解析（公司/岗位/日期/部门）；`PrepareResult` / `prepare_interview` / `_legacy_prepare` / `_build_output_filename` 全链路透传 `department` |
| `main.py` | 更新 | `cmd_prepare` 解包四元组；argparse 新增 `--department`；epilog 示例更新 |
| `api/routes/prepare.py` | 更新 | `PrepareRequest` 加 `department`；响应补全 12 字段 |
| `requirements.txt` | 更新 | 移除 `pydantic-ai-slim`，改为零新增依赖方案 |
| `tests/unit/test_prepare_agent.py` | 重写 | 6 测试全过（含 `submit_final` / fallback / agent_meta 覆盖） |

### 文档同步

| 01_需求文档.md | 更新 | 岗位预测功能描述扩展（Agent 自主决策、部门可选字段、ReAct 闭环） |
| 02_技术选型报告.md | 更新 | 新增 §2.5 Agent 层选型（手写 ReAct Loop vs Pydantic AI vs LangChain）；章节号重编号 |
| 03_系统架构设计.md | 更新 | core/ 模块表加 `prepare_agent.py`；AI 层描述更新 |
| 04_API接口文档.md | 更新 | `/api/prepare` 请求体补 `department`/`count`，响应补全 12 字段 |
| 05_部署配置文档.md | 更新 | 配置项表新增 `PREP_AGENT_MAX_ITERS` / `PREP_AGENT_FALLBACK` |
| 07_测试策略文档.md | 更新 | 补充 `prepare_agent` 测试覆盖 |

---

## [2026-05-18] 面试反思 Agent 重构（PydanticAI 双 Agent）

### 代码层改动

| 文件 | 类型 | 摘要 |
|------|------|------|
| `reflector.py` | 重写 | 全部重写：PydanticAI 双 Agent（Conversation + Summary）+ 渐进式披露 tools（lookup_project_doc / search_project_doc / list_project_tier）+ 5 维度覆盖度评分停止策略 |
| `prompts/reflect_agent_system.md` | 新增 | Conversation Agent 提示词：维度定义、提问策略、停止条件 |
| `prompts/reflect_summary_system.md` | 新增 | Summary Agent 提示词：6 字段输出、review_content ≥100 字硬约束 |
| `prompts/reflect_system.md` | 删除 | 旧版 prompt 废弃 |
| `prompts/reflect_analyze_system.md` | 删除 | 旧版 prompt 废弃 |
| `requirements.txt` | 更新 | 新增 `pydantic-ai>=1.97.0` |
| `config.py` | 更新 | 新增 `REFLECT_MAX_ROUNDS`(8) / `REFLECT_COVERAGE_THRESHOLD`(70) |
| `main.py` | 更新 | `cmd_sync` 新增 `--reflect` 开关；reflect 模式下流水线重排为 extract→reflect→review→archive，复盘后更新画像 |
| `reviewer.py` | 更新 | `generate_review_file()` 新增 `reflection_context` 可选参数 |
| `tests/unit/test_reflector.py` | 新增 | 22 个测试用例（覆盖度停止 / max_rounds / /stop / 异常降级 / 辅助函数） |

### 核心特性
- **双 Agent 架构**：Conversation Agent（多轮提问 + 项目文档 tools）+ Summary Agent（汇总为结构化反思）
- **渐进式披露**：项目背景仅注入文件清单（~200 字），Agent 通过 PydanticAI tools 按需查阅
- **维度覆盖度停止**：5 维度 0-100 评分，全部 ≥70 自动停止，支持软底线回调
- **零回归**：不带 `--reflect` 保持原 extract→archive→review 流程

### 文档同步
| 01_需求文档.md | 更新 | 新增面试反思交互功能需求描述 |
| 03_系统架构设计.md | 更新 | 模块表新增 `reflector.py`；sync 数据流补充 --reflect 分支 |
| 05_部署配置文档.md | 更新 | 依赖清单新增 pydantic-ai；配置项表新增反思配置项；CLI 命令补充 --reflect |
| .env.example | 更新 | 新增反思配置段 |
| README.md | 更新 | 目录速查更新 |

---

## 持续更新机制

### 触发更新的场景
1. **新功能上线**：同步更新需求文档、架构文档和API文档
2. **技术栈变更**：更新技术选型报告和部署配置文档
3. **接口变更**：更新API接口文档，标注版本号
4. **流程调整**：更新开发规范或测试策略文档
5. **Bug修复涉及架构调整**：更新架构设计文档

### 更新规范
- 每次文档变更必须在本文件追加记录
- 重大变更需标注影响范围
- 建议结合Git提交一并更新文档
