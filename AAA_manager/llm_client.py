"""
llm_client.py - LLM 客户端模块
基于 OpenAI SDK 封装，支持 DeepSeek 和 Qwen 切换，带重试和日志。
"""

import time
from openai import OpenAI

from config import get_active_provider
from logger import get_logger

logger = get_logger("llm_client")


def chat_completion(
    messages: list[dict],
    model: str = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    response_format: dict = None,
    provider: str = None,
    max_retries: int = 3,
) -> str:
    """
    调用 LLM 并返回回复文本。

    Args:
        messages: 对话消息列表，格式为 [{"role": "...", "content": "..."}]
        model: 模型名称，不指定则使用当前 provider 默认模型
        temperature: 生成温度，默认 0.7
        max_tokens: 最大生成 token 数，默认 4096
        response_format: 响应格式，如 {"type": "json_object"}
        provider: 指定 provider（"deepseek" 或 "qwen"），不指定则用默认
        max_retries: 最大重试次数，默认 3

    Returns:
        LLM 回复的文本内容
    """
    api_key, base_url, default_model = get_active_provider(provider)
    use_model = model or default_model

    client = OpenAI(api_key=api_key, base_url=base_url)

    kwargs = {
        "model": use_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        kwargs["response_format"] = response_format

    provider_name = (provider or "default").upper()
    logger.info(f"调用 LLM [{provider_name}] 模型: {use_model}")

    for attempt in range(1, max_retries + 1):
        try:
            response = client.chat.completions.create(**kwargs)

            # 记录 token 用量
            usage = response.usage
            if usage:
                logger.debug(
                    f"Token 用量 - input: {usage.prompt_tokens}, "
                    f"output: {usage.completion_tokens}, "
                    f"total: {usage.total_tokens}"
                )

            content = response.choices[0].message.content
            logger.info(f"LLM 调用成功 (第 {attempt} 次尝试)")
            return content

        except Exception as e:
            logger.warning(f"LLM 调用失败 (第 {attempt}/{max_retries} 次): {e}")
            if attempt < max_retries:
                wait_time = 2 ** attempt  # 指数退避: 2s, 4s, 8s
                logger.info(f"等待 {wait_time}s 后重试...")
                time.sleep(wait_time)
            else:
                logger.error(f"LLM 调用最终失败，已重试 {max_retries} 次: {e}")
                raise


def chat_completion_stream(
    messages: list[dict],
    model: str = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    provider: str = None,
):
    """
    流式调用 LLM，返回生成器，逐 chunk 产出文本。

    Yields:
        str: 每个 chunk 的文本片段
    """
    api_key, base_url, default_model = get_active_provider(provider)
    use_model = model or default_model
    client = OpenAI(api_key=api_key, base_url=base_url)

    provider_name = (provider or "default").upper()
    logger.info(f"流式调用 LLM [{provider_name}] 模型: {use_model}")

    response = client.chat.completions.create(
        model=use_model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )

    for chunk in response:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
