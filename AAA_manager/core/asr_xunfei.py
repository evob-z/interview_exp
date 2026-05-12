"""
讯飞语音听写（流式版）WebSocket 客户端
支持 "边说边转" 模式，实时返回识别结果。
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime
from time import mktime
from typing import AsyncGenerator
from urllib.parse import urlencode
from wsgiref.handlers import format_date_time

import websockets

logger = logging.getLogger(__name__)


class XunfeiASR:
    """讯飞语音听写流式版客户端"""

    WS_URL = "wss://iat-api.xfyun.cn/v2/iat"

    def __init__(self, app_id: str, api_key: str, api_secret: str):
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret
        self._ws = None
        self._result_queue: asyncio.Queue = asyncio.Queue()
        self._receive_task = None
        self._sentences: list[str] = []  # pgs 模式下维护的句子列表
        self._closed = False

    def _create_auth_url(self) -> str:
        """生成带鉴权参数的 WebSocket URL"""
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))

        signature_origin = f"host: iat-api.xfyun.cn\ndate: {date}\nGET /v2/iat HTTP/1.1"
        signature_sha = hmac.new(
            self.api_secret.encode("utf-8"),
            signature_origin.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        signature = base64.b64encode(signature_sha).decode()

        authorization_origin = (
            f'api_key="{self.api_key}", algorithm="hmac-sha256", '
            f'headers="host date request-line", signature="{signature}"'
        )
        authorization = base64.b64encode(authorization_origin.encode("utf-8")).decode()

        params = {
            "authorization": authorization,
            "date": date,
            "host": "iat-api.xfyun.cn",
        }
        return self.WS_URL + "?" + urlencode(params)

    async def start(self):
        """开始新的识别会话，连接讯飞 WebSocket"""
        self._sentences = []
        self._closed = False
        url = self._create_auth_url()
        self._ws = await websockets.connect(url)
        # 启动后台接收任务
        self._receive_task = asyncio.create_task(self._receive_loop())
        logger.info("讯飞 ASR WebSocket 已连接")

    async def send_audio(self, audio_data: bytes):
        """发送音频数据帧到讯飞

        Args:
            audio_data: PCM 16bit 16kHz 单声道音频数据
        """
        if not self._ws or self._closed:
            return

        # 判断是否为第一帧（检查 _sentences 和内部状态）
        if not hasattr(self, "_first_frame_sent") or not self._first_frame_sent:
            # 第一帧，带参数
            frame = {
                "common": {"app_id": self.app_id},
                "business": {
                    "language": "zh_cn",
                    "domain": "iat",
                    "accent": "mandarin",
                    "vad_eos": 3000,
                    "dwa": "wpgs",  # 开启 pgs 动态修正
                },
                "data": {
                    "status": 0,
                    "format": "audio/L16;rate=16000",
                    "encoding": "raw",
                    "audio": base64.b64encode(audio_data).decode(),
                },
            }
            self._first_frame_sent = True
        else:
            # 中间帧
            frame = {
                "data": {
                    "status": 1,
                    "format": "audio/L16;rate=16000",
                    "encoding": "raw",
                    "audio": base64.b64encode(audio_data).decode(),
                }
            }

        try:
            await self._ws.send(json.dumps(frame))
        except Exception as e:
            logger.error(f"发送音频帧失败: {e}")

    async def stop(self):
        """发送结束帧，通知讯飞音频传输完毕"""
        if not self._ws or self._closed:
            return

        frame = {
            "data": {
                "status": 2,
                "format": "audio/L16;rate=16000",
                "encoding": "raw",
                "audio": "",
            }
        }
        try:
            await self._ws.send(json.dumps(frame))
        except Exception as e:
            logger.error(f"发送结束帧失败: {e}")

    async def close(self):
        """关闭连接并清理资源"""
        self._closed = True
        self._first_frame_sent = False
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        # 放入结束标记
        await self._result_queue.put(None)
        logger.info("讯飞 ASR 连接已关闭")

    async def _receive_loop(self):
        """后台循环接收讯飞返回的识别结果"""
        try:
            async for message in self._ws:
                if self._closed:
                    break
                try:
                    result = json.loads(message)
                    self._process_result(result)
                except json.JSONDecodeError:
                    logger.warning(f"无法解析讯飞返回: {message}")
        except websockets.exceptions.ConnectionClosed:
            logger.info("讯飞 WebSocket 连接已关闭")
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"接收讯飞结果异常: {e}")
        finally:
            # 接收循环结束，放入结束标记
            await self._result_queue.put(None)

    def _process_result(self, result: dict):
        """解析讯飞返回的识别结果，处理 pgs 追加/替换逻辑"""
        code = result.get("code", -1)
        if code != 0:
            logger.error(f"讯飞返回错误 code={code}, msg={result.get('message', '')}")
            return

        data = result.get("data", {})
        res = data.get("result", {})
        status = data.get("status", 0)

        if not res:
            return

        # 提取文字：遍历 ws 数组，拼接每个 cw[0].w
        ws_list = res.get("ws", [])
        text = "".join(cw.get("w", "") for ws in ws_list for cw in ws.get("cw", []))

        # pgs 动态修正逻辑
        pgs = res.get("pgs", "")
        if pgs == "apd":
            # 追加
            self._sentences.append(text)
        elif pgs == "rpl":
            # 替换
            rg = res.get("rg", [])
            if len(rg) == 2:
                start, end = rg[0], rg[1]
                # 替换 [start, end] 范围的句子
                self._sentences[start: end + 1] = [text]
        else:
            # 无 pgs 字段时直接追加
            self._sentences.append(text)

        # 拼接所有句子为完整文本
        full_text = "".join(self._sentences)

        # 判断是最终结果还是中间结果
        result_type = "final" if status == 2 else "partial"

        # 放入队列
        self._result_queue.put_nowait({
            "type": result_type,
            "text": full_text,
        })

    async def receive_results(self) -> AsyncGenerator[dict, None]:
        """异步生成器，逐个产出识别结果

        Yields:
            {"type": "partial"/"final", "text": "识别文字"}
        """
        while True:
            result = await self._result_queue.get()
            if result is None:
                break
            yield result
