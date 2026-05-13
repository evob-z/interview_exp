"""
config.py - 项目配置模块
从 .env 文件加载配置，提供统一的配置访问接口。
"""

import os
from pathlib import Path
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

# 项目文档配置：格式 "项目名:路径:文档文件1,文档文件2;项目名2:路径2:文档文件"
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


# 项目别名 → category 映射（用于检索加权）
PROJECT_ALIASES: dict[str, str] = {
    "旅行助手": "项目-Agent_SFT_SHENWEI",
    "旅行顾问": "项目-Agent_SFT_SHENWEI",
    "SHENWEI": "项目-Agent_SFT_SHENWEI",
    "Agent_SFT": "项目-Agent_SFT_SHENWEI",
    "微调": "项目-Agent_SFT_SHENWEI",
    "晓海": "项目-law_sea",
    "MLAW": "项目-law_sea",
    "海商法": "项目-law_sea",
    "law_sea": "项目-law_sea",
    "实习": "项目-law_sea",
    "合规": "项目-compliance_checker",
    "中能建": "项目-compliance_checker",
    "compliance": "项目-compliance_checker",
    "合规审查": "项目-compliance_checker",
}


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
