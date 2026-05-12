# interview_exp - AI 面试准备助手

> 一站式 AI 面试准备系统：自动复盘分析、知识积累归档、智能问答、语音输入、用户画像，帮助持续提升面试表现。

## 核心价值

- **自动化复盘**：输入面试原始问题，自动生成结构化复盘报告（含面试官画像分析）
- **知识积累**：面试问题自动分类归档到 5 个问题库，形成个人知识资产
- **智能问答**：Web 界面随时查询知识库，支持面试话术/详细解释/快速回答三种模式
- **语音输入**：集成讯飞 ASR，支持边说边转的实时语音识别
- **会话管理**：多会话支持，每个会话独立存储为 JSON 文件
- **智能辅助**：网络搜索增强、追问预测、分层项目理解、用户画像分析

---

## 功能概览

| 功能模块 | 说明 | 入口 |
|---------|------|------|
| 面试复盘流水线 | 原始问题 → 抽取 → 归档 → 结构化复盘 | CLI `sync` / Web API |
| 问题抽取与归档 | LLM 自动分类到 5 个问题库（八股、项目、AI_Coding 等） | CLI `extract` / `archive` |
| 智能问答 | 基于知识库的 RAG 问答，3 种回答模式，流式响应 | Web 界面 |
| 语音输入 | 讯飞 ASR WebSocket 流式语音识别，边说边转 | Web 界面麦克风按钮 |
| 会话历史 | 一个会话一个 JSON 文件，支持新建/切换/删除 | Web 界面 |
| 追问预测 | 回答后后台静默生成深入追问与相关问题 | Web 界面卡片 |
| 用户画像 | 综合简历、面试记录、投递情况生成画像摘要/建议/鼓励 | Web API |
| 网络搜索 | 问答与复盘时自动搜索公司信息和技术概念 | 自动触发 |
| 分层项目理解 | 4 层渐进式文档读取，智能构建项目上下文 | 问答时自动调用 |
| 投递状态追踪 | Excel 颜色自动识别投递状态（红/橙/黄/绿） | Web 画像面板 |
| 多轮截断 | 自动保留最近 N 轮对话，控制上下文长度 | 自动 |
| 统计面板 | 题库统计、面试次数、投递情况汇总 | Web API |
| CLI 命令集 | sync / detect / extract / archive / review | 命令行 |

---

## 系统架构

```
AAA_manager/
├── main.py              # CLI 入口（sync/detect/extract/archive/review）
├── app.py               # Web 服务入口（FastAPI）
├── config.py            # 统一配置管理（从 .env 加载）
├── llm_client.py        # LLM 调用封装（OpenAI SDK 兼容）
├── core/
│   ├── web_searcher.py  # 网络搜索（Tavily/Bing/Serper）
│   └── asr_xunfei.py   # 讯飞语音识别 WebSocket 客户端
├── knowledge/
│   ├── question_bank.py # 问题库管理（搜索、统计、去重）
│   ├── project_reader.py# 分层项目文档理解（4层）
│   ├── resume_reader.py # 简历读取（PDF）
│   └── excel_reader.py  # 投递记录读取（Excel + 颜色状态）
├── profile/
│   └── profile_manager.py # 用户画像（初始化、摘要、建议、鼓励）
├── api/
│   ├── deps.py          # 依赖注入（单例管理）
│   └── routes/
│       ├── qa.py        # 智能问答 API（流式 + 非流式）
│       ├── profile.py   # 用户画像 API
│       ├── history.py   # 会话历史 API（CRUD）
│       ├── followup.py  # 追问预测 API
│       ├── asr.py       # 语音识别 WebSocket 端点
│       ├── sync.py      # 同步触发 API
│       └── stats.py     # 统计信息 API
├── frontend/static/
│   ├── index.html       # Web 前端页面
│   ├── app.js           # 前端逻辑（会话管理、语音、追问）
│   └── style.css        # 样式
├── prompts/             # LLM Prompt 模板
│   ├── review_template.md # 复盘模板
│   ├── extract_system.md  # 抽取 prompt
│   └── archive_rules.md   # 归档规则
├── data/
│   ├── user_profile.json  # 用户画像持久化
│   └── sessions/          # 会话历史（每会话一个 JSON）
├── scripts/
│   └── read_interview_dates.py  # 面试日期提取工具
├── logs/                # 运行日志
├── detector.py          # 变更检测
├── extractor.py         # 问题抽取
├── archiver.py          # 归档分类
├── reviewer.py          # 复盘生成
├── git_ops.py           # Git 操作
└── logger.py            # 日志模块
```

---

## 快速开始

### 1. 环境准备

```bash
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
# 编辑 .env，填入 API Key 和路径配置
```

### 4. 配置项目规则

```bash
cp .rules.example .rules
# 编辑 .rules，填入你的项目路径和项目映射
```

`.rules` 文件配置你的个人项目信息，用于智能问答时提供项目上下文。包含：
- 项目代码存储路径
- 项目名称与问题库文件的映射关系
- 面经文件命名规范

> 此文件含个人路径，已加入 `.gitignore`，不会被提交。

### 5. 启动 Web 服务

```bash
python app.py
# 访问 http://127.0.0.1:8000
```

### 6. 第一次使用

1. 将面试原始问题文件放入 `面试原始问题/` 目录（文件名格式：`公司_类型_YYMMDD_轮次.md`）
2. 运行 `python main.py sync --auto-commit` 执行全流程
3. 查看 `面试复盘/` 目录下生成的复盘文件
4. 打开 Web 界面进行快速问答

---

## 使用方式

### Web 界面

```bash
python app.py
# 默认地址：http://127.0.0.1:8000
```

功能：
- **智能问答**：输入问题，选择回答模式（面试话术 / 详细解释 / 快速回答），支持流式响应
- **语音输入**：点击麦克风按钮，边说边转文字
- **会话管理**：新建对话、切换历史会话、删除会话
- **追问预测**：回答后自动生成深入追问与相关问题卡片，点击即可继续提问
- **用户画像**：查看综合画像摘要、获取改进建议和鼓励
- **统计面板**：查看题库统计、面试次数、投递状态分布

### CLI 命令

```bash
# 全流程同步（检测 → 抽取 → 归档 → 复盘 → 提交）
python main.py sync --auto-commit

# 预览模式（不实际提交）
python main.py sync --dry-run

# 仅检测变更
python main.py detect

# 对指定文件抽取问题
python main.py extract <file>

# 对指定文件归档入库
python main.py archive <file>

# 复盘最新面经（追加到原文件）
python main.py review

# 复盘指定文件，生成独立复盘文件到 面试复盘/ 目录
python main.py review <file> --standalone
```

---

## 配置说明

所有配置通过 `.env` 文件管理：

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
| `PROJECT_CONFIGS` | 项目文档配置（`名称:路径:文件;...`） | - |
| `ENABLE_WEB_SEARCH` | 是否启用网络搜索 | `true` |
| `SEARCH_API_KEY` | 搜索 API 密钥 | - |
| `SEARCH_API_PROVIDER` | 搜索提供商（tavily/bing/serper） | `tavily` |
| `XUNFEI_APP_ID` | 讯飞语音识别 APP ID | - |
| `XUNFEI_API_KEY` | 讯飞 API Key | - |
| `XUNFEI_API_SECRET` | 讯飞 API Secret | - |
| `WEB_HOST` | Web 服务监听地址 | `127.0.0.1` |
| `WEB_PORT` | Web 服务端口 | `8000` |

---

## API 接口

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/qa` | POST | 智能问答（非流式） |
| `/api/qa/stream` | POST | 流式问答（SSE） |
| `/api/profile` | GET | 获取完整用户画像 |
| `/api/profile/summary` | GET | 获取画像摘要 |
| `/api/profile/advice` | GET | 获取改进建议 |
| `/api/profile/encouragement` | GET | 获取鼓励话语 |
| `/api/profile/initialize` | POST | 初始化/重建用户画像 |
| `/api/history/sessions` | GET | 获取会话列表 |
| `/api/history/sessions/{id}` | GET | 获取会话详情 |
| `/api/history/sessions` | POST | 创建新会话 |
| `/api/history/sessions/{id}` | DELETE | 删除会话 |
| `/api/followup/predict` | POST | 触发追问预测 |
| `/api/followup/result/{id}` | GET | 获取追问预测结果 |
| `/api/asr/ws` | WebSocket | 语音识别（讯飞流式转写） |
| `/api/sync/run` | POST | 触发全流程同步 |
| `/api/sync/status` | GET | 获取同步状态 |
| `/api/stats` | GET | 获取综合统计信息 |

### 问答请求示例

```json
{
  "question": "什么是 RAG？",
  "mode": "interview",
  "session_id": "optional-session-uuid"
}
```

---

## 项目理解策略

系统采用 **4 层渐进式文档读取策略**，为问答和复盘提供项目上下文：

| 层级 | 名称 | 内容 | 加载时机 |
|------|------|------|----------|
| Tier 1 | AI 工具总结 | `.qoder/repowiki`、`.cursorrules`、`.rules` 等 | 启动时 |
| Tier 2 | 设计文档 | `README.md`、`docs/`、`spec/` | 启动时 |
| Tier 3 | 零散文档 | 根目录及浅层子目录的其他 `.md` 文件 | 搜索时按需 |
| Tier 4 | 代码文件 | `.py`、`.js`、`.ts` 等源代码 | 锁定，需用户批准 |

**搜索策略**：优先搜索 Tier 1-2，结果不足时自动加载 Tier 3 搜索，Tier 4 仅在用户明确授权后读取。

---

## 技术栈

- **Python 3.11** / conda env: `interview_assistant`
- **FastAPI + Uvicorn** — Web 服务框架（含 WebSocket 支持）
- **OpenAI SDK** — LLM 调用（兼容 DeepSeek / Qwen API）
- **websockets** — 讯飞 ASR WebSocket 客户端
- **pdfplumber** — PDF 简历解析
- **openpyxl** — Excel 投递记录读取（含单元格颜色解析）
- **httpx** — 网络搜索 HTTP 客户端
- **GitPython** — Git 操作（变更检测、自动提交）
- **python-dotenv** — 环境变量管理

---

## 配置开关

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `ENABLE_FOLLOWUP_PREDICTION` | 是否启用追问预测 | `False` |
| `ENABLE_VOICE_INPUT` | 是否启用语音输入 | `True` |
| `MAX_CONTEXT_TURNS` | 多轮截断保留轮数 | `6` |
| `FOLLOWUP_COUNT` | 追问预测生成数量 | `3` |

> 以上开关在 `config.py` 中管理，可按需调整。

---

## 免责声明

本工具仅用于**面试后的复盘分析与知识管理**，旨在帮助用户在面试结束后梳理、归纳和巩固所学知识。

**本工具不应用于：**
- 面试过程中的实时作弊（如边面试边查询答案）
- 任何违反面试评估公平性的行为
- 代替真实学习和能力提升

作者不对任何滥用本工具导致的后果承担责任。请在遵守相关法律法规和职业道德的前提下使用。
