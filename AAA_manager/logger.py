"""
logger.py - 日志模块
提供统一的日志配置，支持控制台彩色输出和文件轮转记录。
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import LOG_DIR

# 确保日志目录存在
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 根 logger 配置：防止第三方库（如 FastAPI、httpx）刷屏
logging.getLogger().setLevel(logging.WARNING)


class ColorFormatter(logging.Formatter):
    """控制台彩色日志格式化器"""

    COLORS = {
        logging.DEBUG: "\033[36m",     # 青色
        logging.INFO: "\033[32m",      # 绿色
        logging.WARNING: "\033[33m",   # 黄色
        logging.ERROR: "\033[31m",     # 红色
        logging.CRITICAL: "\033[35m",  # 紫色
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, self.RESET)
        levelname = record.levelname
        formatted = (
            f"{color}[{self.formatTime(record, '%Y-%m-%d %H:%M:%S')}.{record.msecs:03.0f}] "
            f"[{levelname}] [{record.name}:{record.lineno}] "
            f"{record.getMessage()}{self.RESET}"
        )
        if record.exc_info:
            formatted += f"\n{self.formatException(record.exc_info)}"
        return formatted


class FileFormatter(logging.Formatter):
    """文件日志格式化器"""

    def format(self, record: logging.LogRecord) -> str:
        formatted = (
            f"[{self.formatTime(record, '%Y-%m-%d %H:%M:%S')}.{record.msecs:03.0f}] "
            f"[{record.levelname}] [{record.name}:{record.lineno}] "
            f"{record.getMessage()}"
        )
        if record.exc_info:
            formatted += f"\n{self.formatException(record.exc_info)}"
        return formatted


def get_logger(name: str) -> logging.Logger:
    """
    获取指定名称的 logger，自动配置控制台和文件输出。

    Args:
        name: 模块名称，用于标识日志来源

    Returns:
        配置好的 logging.Logger 实例
    """
    logger = logging.getLogger(name)

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # 控制台 handler（带颜色）
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(ColorFormatter())
    logger.addHandler(console_handler)

    # 文件 handler（轮转策略：单文件最大 5MB，保留 5 个备份）
    log_file = LOG_DIR / "app.log"
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(FileFormatter())
    logger.addHandler(file_handler)

    return logger


def is_debug_enabled(name: str) -> bool:
    """检查指定 logger 是否启用了 DEBUG 级别"""
    return logging.getLogger(name).isEnabledFor(logging.DEBUG)
