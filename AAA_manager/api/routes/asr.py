"""语音识别 WebSocket 路由"""

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import config
from core.asr_xunfei import XunfeiASR

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws")
async def asr_websocket(ws: WebSocket):
    """语音识别 WebSocket 端点

    前端发送：文本 "START" 开始识别
    前端发送：二进制音频帧（PCM 16bit 16kHz）
    前端发送：文本 "STOP" 结束识别

    后端返回：JSON {"type": "partial"/"final", "text": "识别文字"}
    """
    await ws.accept()

    asr = XunfeiASR(
        app_id=config.XUNFEI_APP_ID,
        api_key=config.XUNFEI_API_KEY,
        api_secret=config.XUNFEI_API_SECRET,
    )

    forward_task = None

    try:
        while True:
            data = await ws.receive()
            if "text" in data:
                cmd = data["text"]
                if cmd == "START":
                    # 开始新的识别会话
                    await asr.start()
                    # 启动后台任务接收讯飞结果并转发给前端
                    forward_task = asyncio.create_task(
                        _forward_results(asr, ws)
                    )
                elif cmd == "STOP":
                    # 发送结束帧
                    await asr.stop()
            elif "bytes" in data:
                # 音频数据帧，拆分为不超过 7800 字节的块发送
                audio_bytes = data["bytes"]
                chunk_size = 7800  # 略小于 8000，保证安全
                for i in range(0, len(audio_bytes), chunk_size):
                    chunk = audio_bytes[i: i + chunk_size]
                    await asr.send_audio(chunk)
    except WebSocketDisconnect:
        logger.info("前端 WebSocket 断开连接")
    except Exception as e:
        logger.error(f"ASR WebSocket 异常: {e}")
    finally:
        await asr.close()
        if forward_task and not forward_task.done():
            forward_task.cancel()
            try:
                await forward_task
            except asyncio.CancelledError:
                pass


async def _forward_results(asr: XunfeiASR, ws: WebSocket):
    """从讯飞接收结果并转发给前端"""
    try:
        async for result in asr.receive_results():
            try:
                await ws.send_json(result)
            except Exception:
                break
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"转发识别结果异常: {e}")
