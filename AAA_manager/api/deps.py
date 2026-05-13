"""API 依赖 - 初始化共享服务实例"""
import os
import sys

# 确保上层目录在 path 中，以便导入 config, llm_client 等
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import llm_client as _llm_module
from knowledge import QuestionBank, ProjectReader, ResumeReader, ExcelReader
from profile.profile_manager import ProfileManager

# 初始化知识模块
repo_path = str(config.INTERVIEW_REPO_PATH)
question_bank = QuestionBank(
    os.path.join(repo_path, "问题库"),
    extra_dirs=[os.path.join(repo_path, config.PREP_OUTPUT_DIR)],
)
question_bank.load()

project_reader = ProjectReader(config.PROJECT_CONFIGS)
project_reader.load_startup()
resume_reader = ResumeReader(os.path.join(repo_path, config.RESUME_DIR))
excel_reader = ExcelReader(os.path.join(repo_path, config.COMPANY_EXCEL_PATH))

# 初始化画像模块（传入 llm_client 模块以支持 LLM 生成功能）
profile_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "user_profile.json"
)
profile_manager = ProfileManager(profile_path, llm_client=_llm_module)
profile_manager.load()

from core.web_searcher import WebSearcher

# 初始化网络搜索模块
web_searcher = WebSearcher(
    api_key=config.SEARCH_API_KEY,
    provider=config.SEARCH_API_PROVIDER,
    enabled=config.ENABLE_WEB_SEARCH,
)
