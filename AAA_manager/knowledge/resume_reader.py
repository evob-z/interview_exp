"""
resume_reader.py - 简历 PDF 读取模块
用 pdfplumber 读取简历 PDF，提取原始文本。
结构化解析（教育、技能、经历）留给 LLM 在使用时完成。
"""

import os
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    import pdfplumber
except ImportError:
    pdfplumber = None
    logger.warning("pdfplumber 未安装，简历读取功能将不可用。请执行: pip install pdfplumber")


class ResumeReader:
    def __init__(self, resume_dir: str):
        """初始化，指定简历目录"""
        self.resume_dir = Path(resume_dir)

    def find_resume(self) -> str:
        """查找目录下的 PDF 文件（取最新的一个）
        返回: PDF 文件的完整路径，未找到则返回空字符串
        """
        if not self.resume_dir.exists():
            logger.warning(f"简历目录不存在: {self.resume_dir}")
            return ""

        pdf_files = list(self.resume_dir.glob("*.pdf"))
        if not pdf_files:
            # 尝试大写扩展名
            pdf_files = list(self.resume_dir.glob("*.PDF"))

        if not pdf_files:
            logger.warning(f"简历目录下未找到 PDF 文件: {self.resume_dir}")
            return ""

        # 按修改时间排序，取最新的
        pdf_files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
        return str(pdf_files[0])

    def extract_text(self, pdf_path: str = None) -> str:
        """提取 PDF 全文文本
        Args:
            pdf_path: PDF 文件路径，不指定则自动查找最新的
        返回: 提取的文本内容，失败返回空字符串
        """
        if pdfplumber is None:
            logger.error("pdfplumber 未安装，无法提取 PDF 文本")
            return ""

        if pdf_path is None:
            pdf_path = self.find_resume()

        if not pdf_path:
            return ""

        pdf_file = Path(pdf_path)
        if not pdf_file.exists():
            logger.warning(f"PDF 文件不存在: {pdf_path}")
            return ""

        try:
            text_parts = []
            with pdfplumber.open(pdf_file) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
            return "\n\n".join(text_parts)
        except Exception as e:
            logger.error(f"提取 PDF 文本失败 {pdf_path}: {e}")
            return ""

    def get_resume_info(self) -> dict:
        """返回简历信息
        返回: {
            raw_text: str,          # 原始文本
            file_path: str,         # 文件路径
            file_name: str,         # 文件名
            last_modified: str,     # 最后修改时间（ISO 格式）
        }
        """
        pdf_path = self.find_resume()
        if not pdf_path:
            return {
                "raw_text": "",
                "file_path": "",
                "file_name": "",
                "last_modified": "",
            }

        raw_text = self.extract_text(pdf_path)
        pdf_file = Path(pdf_path)

        try:
            mtime = os.path.getmtime(pdf_file)
            last_modified = datetime.fromtimestamp(mtime).isoformat()
        except Exception:
            last_modified = ""

        return {
            "raw_text": raw_text,
            "file_path": str(pdf_file),
            "file_name": pdf_file.name,
            "last_modified": last_modified,
        }
