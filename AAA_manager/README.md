# AAA_manager

主程序目录：FastAPI Web 服务 + CLI 工具。

> **完整文档请阅读仓库根目录的 [README.md](../README.md)**，包括：
>
> - 功能概览与架构
> - 快速开始（环境准备、依赖安装、配置）
> - Web 界面与 CLI 命令
> - 配置项详解（含 `PROJECT_CONFIGS`）
> - API 接口列表
> - 测试与贡献指南

---

## 目录速查

| 子目录 / 文件 | 作用 |
|---|---|
| `app.py` | FastAPI Web 入口 |
| `main.py` | CLI 入口（extract / review / archive / sync / prepare / export-session） |
| `config.py` | 配置（从 `.env` 加载） |
| `llm_client.py` | LLM 调用封装（OpenAI SDK 兼容 DeepSeek / Qwen） |
| `extractor.py` `archiver.py` `reviewer.py` `preparer.py` | 复盘流水线核心模块 |
| `detector.py` `git_ops.py` `logger.py` | 变更检测 / Git 操作 / 日志 |
| `api/routes/` | FastAPI 路由：qa / profile / history / followup / asr / sync / stats / prepare |
| `core/` | `web_searcher.py`（Tavily / Bing / Serper）、`asr_xunfei.py`（讯飞流式 ASR） |
| `knowledge/` | `question_bank.py` / `project_reader.py` / `resume_reader.py` / `excel_reader.py` |
| `profile/` | `profile_manager.py`（用户画像） |
| `frontend/static/` | Web 前端（index.html / app.js / style.css） |
| `prompts/` | LLM Prompt 模板（Markdown） |
| `tests/` | pytest 单元 + API 冒烟测试 |
| `data/` | 会话与画像（gitignore） |
| `logs/` | 运行日志（gitignore） |
| `.env.example` | 环境变量模板 |
| `requirements.txt` | 依赖列表 |

---

## 本地启动（速查）

```bash
conda create -n interview_exp python=3.11 -y
conda activate interview_exp

cd AAA_manager
pip install -r requirements.txt
cp .env.example .env   # 填入 API Key

python app.py          # 启动 Web (http://127.0.0.1:8000)
# 或
python main.py sync <file.md>   # 命令行全流程
```

## 测试

```bash
cd AAA_manager
pytest
```

外部依赖（LLM / ASR / Git 远程 / 网络搜索）全部 mock，离线可跑。
