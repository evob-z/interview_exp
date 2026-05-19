"""
config.py - 项目配置模块
从 .env + projects.yaml 加载配置，提供统一的配置访问接口。
"""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

# 定位 AAA_manager 目录（基于本文件位置）
BASE_DIR = Path(__file__).resolve().parent

# 加载 .env 文件
load_dotenv(BASE_DIR / ".env")

# DeepSeek 配置
DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# Qwen 配置
QWEN_API_KEY: str = os.getenv("QWEN_API_KEY", "")
QWEN_BASE_URL: str = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
QWEN_MODEL: str = os.getenv("QWEN_MODEL", "qwen-plus")

# 默认 provider
DEFAULT_PROVIDER: str = os.getenv("DEFAULT_PROVIDER", "deepseek")

# 路径配置
INTERVIEW_REPO_PATH: Path = Path(os.getenv("INTERVIEW_REPO_PATH", str(BASE_DIR.parent)))
PROJECT_PATHS: list[str] = [
    p.strip() for p in os.getenv("PROJECT_PATHS", "").split(",") if p.strip()
]
QUESTION_BANK_PATH: Path = INTERVIEW_REPO_PATH / "问题库"
LAST_SYNC_FILE: Path = BASE_DIR / ".last_sync_time"
LOG_DIR: Path = BASE_DIR / "logs"


# === 新增路径配置 ===
RAW_INPUT_DIR = os.getenv("RAW_INPUT_DIR", "面试原始问题")
REVIEW_OUTPUT_DIR = os.getenv("REVIEW_OUTPUT_DIR", "面试复盘")
RESUME_DIR = os.getenv("RESUME_DIR", "个人情况/简历")
COMPANY_EXCEL_PATH = os.getenv("COMPANY_EXCEL_PATH", "公司投递情况/投递记录.xlsx")

# === 岗位预测配置（面试前针对性备战）===
PREP_OUTPUT_DIR = os.getenv("PREP_OUTPUT_DIR", "岗位预测")
PREP_OUTPUT_PATH: Path = INTERVIEW_REPO_PATH / PREP_OUTPUT_DIR
PREP_QUESTION_COUNT = int(os.getenv("PREP_QUESTION_COUNT", "20"))  # 默认每次生成的预测题数

# === 岗位预测 Agent（Pydantic AI）配置 ===
# Agent 总 LLM 请求次数上限（含工具调用循环）；超限抛 UsageLimitExceeded
PREP_AGENT_MAX_ITERS = int(os.getenv("PREP_AGENT_MAX_ITERS", "8"))
# Agent 异常时是否回退到旧线性流水线（默认 true，零回归保底）
PREP_AGENT_FALLBACK = os.getenv("PREP_AGENT_FALLBACK", "true").lower() == "true"

# 项目文档配置：格式 "项目名:路径:文档文件1,文档文件2;项目名2:路径2:文档文件"
# 优先级：.env 中的 PROJECT_CONFIGS > projects.yaml 自动派生
PROJECT_CONFIGS = os.getenv("PROJECT_CONFIGS", "")

# === 网络搜索配置 ===
ENABLE_WEB_SEARCH = os.getenv("ENABLE_WEB_SEARCH", "true").lower() == "true"
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY", "")
SEARCH_API_PROVIDER = os.getenv("SEARCH_API_PROVIDER", "tavily")

# === 追问预测 ===
ENABLE_FOLLOWUP_PREDICTION = False
FOLLOWUP_COUNT = 3  # 生成追问数量

# === 多轮对话 ===
MAX_CONTEXT_TURNS = 6  # 最多保留最近6轮对话作为上下文

# === 语音输入配置 ===
ENABLE_VOICE_INPUT = os.getenv("ENABLE_VOICE_INPUT", "false").lower() == "true"
XUNFEI_APP_ID: str = os.getenv("XUNFEI_APP_ID", "")
XUNFEI_API_KEY: str = os.getenv("XUNFEI_API_KEY", "")
XUNFEI_API_SECRET: str = os.getenv("XUNFEI_API_SECRET", "")

# === Web 服务配置 ===
WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "8000"))

# === Git 集成 ===
GIT_ENABLED = os.getenv("GIT_ENABLED", "false").lower() == "true"


# =============================================================================
# 项目元信息（唯一真相源：projects.yaml）
# 派生 PROJECT_ALIASES / CATEGORY_FILE_MAP / 兜底 PROJECT_CONFIGS
# =============================================================================
PROJECTS_FILE: Path = BASE_DIR / "projects.yaml"


def _load_projects_meta() -> dict:
    """加载 projects.yaml；不存在或解析失败时返回空结构（不阻塞启动）。"""
    if not PROJECTS_FILE.exists():
        return {"projects": [], "generic_categories": []}
    try:
        with PROJECTS_FILE.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        data.setdefault("projects", [])
        data.setdefault("generic_categories", [])
        return data
    except Exception:
        # 启动期不抛错；让上层 logger 在使用时报警
        return {"projects": [], "generic_categories": []}


PROJECTS_META: dict = _load_projects_meta()

# 项目别名 → category 映射（用于检索加权）
PROJECT_ALIASES: dict[str, str] = {
    alias: f"项目-{p['name']}"
    for p in PROJECTS_META.get("projects", [])
    if p.get("name")
    for alias in (p.get("aliases") or [])
}

# category → 题库文件名映射（archiver 入库依据）
CATEGORY_FILE_MAP: dict[str, str] = {
    f"项目-{p['name']}": f"项目-{p['name']}.md"
    for p in PROJECTS_META.get("projects", [])
    if p.get("name")
}
for _g in PROJECTS_META.get("generic_categories", []):
    if _g.get("name"):
        CATEGORY_FILE_MAP[_g["name"]] = f"{_g['name']}.md"

# 兜底：保证 "八股" 永远存在，避免 projects.yaml 缺失/未配置时 archiver 失败
CATEGORY_FILE_MAP.setdefault("八股", "八股.md")

# 若 .env 未提供 PROJECT_CONFIGS，则从 projects.yaml 自动派生
if not PROJECT_CONFIGS:
    _parts: list[str] = []
    for _p in PROJECTS_META.get("projects", []):
        _path = _p.get("path")
        if not _path or not _p.get("name"):
            continue
        _docs = _p.get("docs") or ["README.md"]
        _parts.append(f"{_p['name']}:{_path}:{','.join(_docs)}")
    if _parts:
        PROJECT_CONFIGS = ";".join(_parts)


# === 面试反思配置 ===
REFLECT_MAX_ROUNDS = int(os.getenv("REFLECT_MAX_ROUNDS", "12"))
REFLECT_COVERAGE_THRESHOLD = int(os.getenv("REFLECT_COVERAGE_THRESHOLD", "70"))
NOTEPAD_MAX_CHARS = int(os.getenv("NOTEPAD_MAX_CHARS", "16000"))
NOTEPAD_MAX_SECTION_CHARS = int(os.getenv("NOTEPAD_MAX_SECTION_CHARS", "2400"))


def get_active_provider(provider: str = None) -> tuple[str, str, str]:
    """
    返回当前激活 provider 的 (api_key, base_url, model) 三元组。
    
    Args:
        provider: 指定 provider 名称，不指定则使用 DEFAULT_PROVIDER
    
    Returns:
        (api_key, base_url, model)
    """
    name = (provider or DEFAULT_PROVIDER).lower()
    if name == "qwen":
        return QWEN_API_KEY, QWEN_BASE_URL, QWEN_MODEL
    # 默认返回 deepseek
    return DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
