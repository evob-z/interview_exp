# interview_exp - AI 面试准备助手

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Web-009688.svg)](https://fastapi.tiangolo.com/)
[![Tests](https://img.shields.io/badge/tests-pytest-0a9edc.svg)](AAA_manager/tests)

> 一站式 AI 面试准备系统：自动复盘分析、知识积累归档、智能问答、语音输入、用户画像，帮助持续提升面试表现。

---

## 核心价值

- **自动化复盘**：输入面试原始问题，自动生成结构化复盘报告（含面试官画像分析）
- **知识积累**：面试问题自动分类归档到 5 个问题库，形成个人知识资产
- **智能问答**：Web 界面随时查询知识库，支持面试话术 / 详细解释 / 快速回答三种模式
- **语音输入**：集成讯飞 ASR，支持边说边转的实时语音识别
- **会话管理**：多会话支持，每个会话独立存储为 JSON 文件
- **智能辅助**：网络搜索增强、追问预测、分层项目理解、用户画像分析
- **岗位备战**：联网搜 JD + LLM 出题，写入题库供模拟面试检索

---

## 功能概览

| 功能模块 | 说明 | 入口 |
|---------|------|------|
| 面试复盘流水线 | 原始问题 → 抽取 → 复盘 → 归档 | CLI `sync` / 单步命令 / Web API |
| 问题抽取与归档 | LLM 自动分类到 5 个问题库（八股、项目、AI_Coding 等） | CLI `extract` / `archive` |
| 智能问答 | 基于知识库的 RAG 问答，3 种回答模式，流式响应 | Web 界面 |
| 语音输入 | 讯飞 ASR WebSocket 流式语音识别，边说边转 | Web 界面麦克风按钮 |
| 会话历史 | 一个会话一个 JSON 文件，支持新建 / 切换 / 删除 | Web 界面 |
| 追问预测 | 回答后后台静默生成深入追问与相关问题 | Web 界面卡片 |
| 用户画像 | 综合简历、面试记录、投递情况生成画像摘要 / 建议 / 鼓励 | Web API |
| 网络搜索 | 问答与复盘时自动搜索公司信息和技术概念 | 自动触发 |
| 分层项目理解 | 4 层渐进式文档读取，智能构建项目上下文 | 问答时自动调用 |
| 投递状态追踪 | Excel 颜色自动识别投递状态（红 / 橙 / 黄 / 绿） | Web 画像面板 |
| 多轮截断 | 自动保留最近 N 轮对话，控制上下文长度 | 自动 |
| 岗位针对性备战 | 面试前联网搜 JD → LLM 出题 → 写入 `岗位预测/` 且自动入题库 | CLI `prepare` / Web |
| 统计面板 | 题库统计、面试次数、投递情况汇总 | Web API |
| 空对话自动清理 | 启动时自动删除无消息空会话（保护 60 秒内新建） | 自动 |
| 历史对话批量处理 | 删除 / 一条龙（导出 → 复盘 → 入库）历史会话 | Web 左侧边栏 |
| 会话导出 | 从 session 导出面试问题（支持 LLM 上下文感知改写） | CLI `export-session` |

---

## 仓库结构

```
interview_exp/
├── AAA_manager/                # 主程序（FastAPI Web + CLI）
│   ├── api/routes/             # FastAPI 路由（qa / profile / history / followup / asr / sync / stats / prepare）
│   ├── core/                   # web_searcher.py / asr_xunfei.py
│   ├── knowledge/              # question_bank / project_reader / resume_reader / excel_reader
│   ├── profile/                # 用户画像
│   ├── frontend/static/        # Web 前端
│   ├── prompts/                # LLM Prompt 模板
│   ├── tests/                  # pytest 单元 + API 冒烟测试
│   ├── data/                   # 会话与画像（gitignore）
│   ├── logs/                   # 运行日志（gitignore）
│   ├── app.py main.py          # Web / CLI 入口
│   ├── config.py llm_client.py # 配置 / LLM 调用
│   ├── extractor.py archiver.py reviewer.py preparer.py
│   ├── .env.example            # 环境变量模板
│   └── requirements.txt
├── 面试原始问题/               # 原始面试问题（个人数据，gitignore）
├── 面试复盘/                   # 自动生成的复盘报告（个人数据）
├── 问题库/                     # 分类问题库（个人数据）
├── 个人情况/                   # 简历、画像（个人数据）
├── 公司投递情况/               # 投递记录（个人数据）
├── 岗位预测/                   # 岗位针对性预测题（个人数据）
├── .rules.example              # 项目规则模板
├── .pre-commit-config.yaml     # 提交前自动跑 pytest
├── LICENSE                     # MIT
├── CONTRIBUTING.md             # 贡献指南
├── SECURITY.md                 # 安全策略
├── CODE_OF_CONDUCT.md          # 行为准则
└── README.md                   # 本文件
```

> 中文目录均存放个人面经数据，已在 [.gitignore](.gitignore) 中排除，仅保留 `.gitkeep` 占位。

---

## 快速开始

### 1. 克隆并准备环境

```bash
git clone <your-fork-url>
cd interview_exp

conda create -n interview_exp python=3.11 -y
conda activate interview_exp
```

### 2. 安装依赖

```bash
cd AAA_manager
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env：填入 DEEPSEEK_API_KEY 等密钥，按本机修改路径配置
```

### 4. 配置项目规则（可选）

```bash
cd ..
cp .rules.example .rules
# 编辑 .rules：声明本地项目路径与名称映射，用于问答时检索项目上下文
```

> `.rules` 含本地路径，已在 `.gitignore` 中排除，不会被提交。

### 5. 启动 Web 服务

```bash
cd AAA_manager
python app.py
# 浏览器访问 http://127.0.0.1:8000
```

### 6. 第一次使用

1. 将面试原始问题文件放入 `面试原始问题/` 目录（文件名格式：`公司_类型_YYMMDD_轮次.md`）
2. 运行 `python main.py sync 文件名.md` 执行全流程
3. 查看 `面试复盘/` 目录下生成的复盘文件
4. 打开 Web 界面进行快速问答

---

## 使用方式

### Web 界面

三栏布局：

| 区域 | 宽度 | 内容 |
|------|------|------|
| 左侧边栏 | 260px | 会话历史 + 新对话 + 批量操作（删除 / 一条龙） |
| 中间主区域 | flex:1 | 聊天消息区 + 模式切换（面试话术 / 详细解释 / 快速回答） |
| 右侧边栏 | 300px | 统计概览 + 个人画像 + 快捷操作（岗位备战等） |

- **响应式**：768px 以下左侧边栏自动隐藏，通过汉堡菜单唤出
- **流式响应**：基于 SSE，逐字输出
- **语音输入**：点击麦克风边说边转
- **追问预测**：回答后自动生成深入追问与相关问题卡片
- **空对话自动清理**：启动时自动删除无消息空会话（保护 60 秒内新建会话）

### CLI 命令

```bash
# 抽取问题（支持指定输入类型）
python main.py extract <file> [--type transcript|chat|structured]
python main.py extract --from-session <session_id>          # 从模拟面试会话导出

# 复盘 / 归档（file 必须在 面试原始问题/ 目录）
python main.py review <file>
python main.py archive <file>

# 全流程串联：extract → review → archive
python main.py sync <file> [--type transcript|chat|structured]

# 岗位针对性备战：搜 JD + LLM 出题，写入 岗位预测/ 并自动入题库
python main.py prepare 字节跳动_AI应用开发实习生-AI数据与安全_260512
# 或显式参数
python main.py prepare --company 字节跳动 --position "AI应用开发实习生" --date 260512 --count 15

# 会话导出
python main.py export-session <session_id> [--name 文件名] [--rewrite]
```

---

## 配置说明

所有配置通过 `AAA_manager/.env` 管理：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | - |
| `DEEPSEEK_BASE_URL` | DeepSeek API 地址 | `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL` | DeepSeek 模型 | `deepseek-chat` |
| `QWEN_API_KEY` | Qwen API 密钥（备选） | - |
| `QWEN_BASE_URL` | Qwen API 地址 | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| `QWEN_MODEL` | Qwen 模型 | `qwen-plus` |
| `DEFAULT_PROVIDER` | 默认 LLM 提供商 | `deepseek` |
| `INTERVIEW_REPO_PATH` | 面经仓库根目录 | 项目上级目录 |
| `PROJECT_PATHS` | 项目代码路径（逗号分隔） | - |
| `RAW_INPUT_DIR` | 原始问题输入目录 | `面试原始问题` |
| `REVIEW_OUTPUT_DIR` | 复盘输出目录 | `面试复盘` |
| `RESUME_DIR` | 简历所在目录 | `个人情况/简历` |
| `COMPANY_EXCEL_PATH` | 投递记录 Excel 路径 | - |
| `PREP_OUTPUT_DIR` | 岗位预测题库目录 | `岗位预测` |
| `PREP_QUESTION_COUNT` | 岗位预测默认题数 | `15` |
| `PROJECT_CONFIGS` | 项目文档配置（`名称:路径:文件;...`） | - |
| `ENABLE_WEB_SEARCH` | 是否启用网络搜索 | `true` |
| `SEARCH_API_KEY` | 搜索 API 密钥 | - |
| `SEARCH_API_PROVIDER` | 搜索提供商（tavily / bing / serper） | `tavily` |
| `XUNFEI_APP_ID` / `XUNFEI_API_KEY` / `XUNFEI_API_SECRET` | 讯飞 ASR 凭证 | - |
| `WEB_HOST` / `WEB_PORT` | Web 服务监听 | `127.0.0.1:8000` |

### PROJECT_CONFIGS 详解

`PROJECT_CONFIGS` 是**项目理解能力的入口**。注册后，`ProjectReader` 会对每个项目自动执行 4 层渐进式文档发现：

| 层级 | 内容 | 加载时机 |
|------|------|----------|
| Tier 1 | AI 工具总结（`.qoder/repowiki/`、`.cursor/rules/`、`.rules`） | 启动时 |
| Tier 2 | 设计文档（`README.md`、`ARCHITECTURE.md`、`docs/`） | 启动时 |
| Tier 3 | 零散文档（根目录其他 `.md`） | 按需加载 |
| Tier 4 | 代码文件（`.py`、`.js` 等） | 锁定，需用户批准 |

**格式**：`项目名:路径:向后兼容文件列表`，多个项目用 `;` 分隔

```env
PROJECT_CONFIGS=project_a:/path/to/project_a:README.md;project_b:/path/to/project_b:README.md
```

> 未在此注册的项目无法被 `archive` 入库时获取项目上下文。新增项目后务必同步更新此配置。

### 配置开关（在 `config.py` 中）

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `ENABLE_FOLLOWUP_PREDICTION` | 是否启用追问预测 | `False` |
| `ENABLE_VOICE_INPUT` | 是否启用语音输入 | `True` |
| `MAX_CONTEXT_TURNS` | 多轮截断保留轮数 | `6` |
| `FOLLOWUP_COUNT` | 追问预测生成数量 | `3` |

---

## API 接口

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/qa` / `/api/qa/stream` | POST | 智能问答（非流式 / SSE 流式） |
| `/api/profile` | GET | 完整用户画像 |
| `/api/profile/summary` / `advice` / `encouragement` | GET | 摘要 / 建议 / 鼓励 |
| `/api/profile/initialize` | POST | 初始化 / 重建用户画像 |
| `/api/history/sessions` | GET / POST | 会话列表 / 创建 |
| `/api/history/sessions/{id}` | GET / DELETE | 详情 / 删除 |
| `/api/history/sessions/cleanup-empty` | DELETE | 清理空会话 |
| `/api/followup/predict` | POST | 触发追问预测 |
| `/api/followup/result/{id}` | GET | 获取追问结果 |
| `/api/asr/ws` | WebSocket | 语音识别（讯飞流式） |
| `/api/sync/run` | POST | 触发全流程同步 |
| `/api/sync/session-pipeline/{session_id}` | POST | 会话一条龙处理 |
| `/api/sync/status` | GET | 同步状态 |
| `/api/prepare/run` / `list` | POST / GET | 岗位预测题生成 / 列出 |
| `/api/stats` | GET | 综合统计 |

请求示例：

```json
{
  "question": "什么是 RAG？",
  "mode": "interview",
  "session_id": "optional-session-uuid"
}
```

---

## 测试

项目内置 pytest 单元测试 + FastAPI 冒烟测试，**离线可跑、不依赖任何 API Key**：

```bash
cd AAA_manager
pytest
```

覆盖模块：`config` / `detector` / `extractor` / `archiver` / `profile_manager` + 主要 API 路由。外部依赖（LLM、讯飞 ASR、Git 远程、网络搜索）全部 mock，测试在 `tmp_path` 中执行，不会写入真实 `data/` 与 `问题库/`。

### 提交前自动跑测试（推荐）

```bash
pip install pre-commit
pre-commit install
```

之后每次 `git commit` 若触及 `AAA_manager/` 会自动运行 pytest。

---

## 技术栈

Python 3.11 · FastAPI + Uvicorn · OpenAI SDK（DeepSeek / Qwen 兼容）· websockets（讯飞 ASR）· pdfplumber · openpyxl · httpx · GitPython · python-dotenv

---

## 贡献

欢迎 PR！请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。

- 报 Bug / 提需求：打开 Issue（模板在 `.github/ISSUE_TEMPLATE/`）
- 安全问题：参见 [SECURITY.md](SECURITY.md)，**请勿在公开 Issue 中披露**
- 行为准则：[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

---

## 免责声明

本工具仅用于**面试结束后的复盘分析与知识管理**，旨在帮助使用者梳理、归纳和巩固所学知识。

**本工具不得用于：**

- 面试过程中的实时作弊（如边面试边查询答案）
- 任何违反面试评估公平性的行为
- 代替真实学习与能力提升

作者不对滥用本工具导致的任何后果承担责任。请在遵守相关法律法规和职业道德的前提下使用。

---

## 许可证

本项目以 [MIT](LICENSE) 协议开源。
