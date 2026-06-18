"""
火山引擎豆包播客 TTS WebSocket 协议实现 (v2 - 生产优化版)

改进：
- duration 从 PodcastRoundEnd.audio_duration 累计，不依赖 PodcastEnd.meta_info
- 精简日志：仅打印轮次级别，不打印每条 PodcastRoundResponse
- 超时保护完整
"""
import asyncio
import ssl
import struct
import io
import json
import uuid
from enum import IntEnum
from typing import Optional, List, Tuple, Callable
import websockets

from app.utils.logger import logger


# ──────────────────────────────────────────────────────
# 枚举定义
# ──────────────────────────────────────────────────────

class MsgType(IntEnum):
    Invalid = 0
    FullClientRequest = 0b0001
    AudioOnlyClient = 0b0010
    FullServerResponse = 0b1001
    AudioOnlyServer = 0b1011
    Error = 0b1111


class MsgTypeFlagBits(IntEnum):
    NoSeq = 0
    PositiveSeq = 0b0001
    LastNoSeq = 0b0010
    NegativeSeq = 0b0011
    WithEvent = 0b0100


class EventType(IntEnum):
    None_ = 0
    StartConnection = 1
    FinishConnection = 2
    ConnectionStarted = 50
    ConnectionFailed = 51
    ConnectionFinished = 52
    StartSession = 100
    CancelSession = 101
    FinishSession = 102
    SessionStarted = 150
    SessionCancelled = 151
    SessionFinished = 152
    SessionFailed = 153
    UsageResponse = 154
    PodcastRoundStart = 360
    PodcastRoundResponse = 361
    PodcastRoundEnd = 362
    PodcastEnd = 363


# ──────────────────────────────────────────────────────
# 异常
# ──────────────────────────────────────────────────────

class ProtocolError(Exception):
    pass


class TTSConnectionError(ProtocolError):
    pass


class TTSSessionError(ProtocolError):
    pass


# ──────────────────────────────────────────────────────
# 二进制协议：打包
# ──────────────────────────────────────────────────────

def build_message(
    msg_type: MsgType,
    flag: MsgTypeFlagBits,
    event: EventType = EventType.None_,
    session_id: str = "",
    payload: bytes = b"",
) -> bytes:
    buffer = io.BytesIO()

    buffer.write(bytes([
        (1 << 4) | 1,
        (msg_type << 4) | flag,
        (1 << 4) | 0,
        0,
    ]))

    if flag == MsgTypeFlagBits.WithEvent:
        buffer.write(struct.pack(">i", event))

        if event not in (
            EventType.StartConnection,
            EventType.FinishConnection,
            EventType.ConnectionStarted,
            EventType.ConnectionFailed,
            EventType.ConnectionFinished,
        ):
            session_bytes = session_id.encode("utf-8")
            buffer.write(struct.pack(">I", len(session_bytes)))
            if session_bytes:
                buffer.write(session_bytes)

    buffer.write(struct.pack(">I", len(payload)))
    if payload:
        buffer.write(payload)

    return buffer.getvalue()


# ──────────────────────────────────────────────────────
# 二进制协议：解包
# ──────────────────────────────────────────────────────

def parse_message(data: bytes) -> dict:
    if isinstance(data, str):
        raise ValueError(f"Unexpected text message: {data}")

    buffer = io.BytesIO(data)
    byte0 = buffer.read(1)[0]
    byte1 = buffer.read(1)[0]
    byte2 = buffer.read(1)[0]
    byte3 = buffer.read(1)[0]

    msg_type = MsgType(byte1 >> 4)
    flag = MsgTypeFlagBits(byte1 & 0x0F)

    event = EventType.None_
    session_id = ""
    payload = b""

    if flag == MsgTypeFlagBits.WithEvent:
        event_bytes = buffer.read(4)
        if event_bytes:
            event = EventType(struct.unpack(">i", event_bytes)[0])

        if event not in (
            EventType.StartConnection,
            EventType.FinishConnection,
            EventType.ConnectionStarted,
            EventType.ConnectionFailed,
            EventType.ConnectionFinished,
        ):
            size_bytes = buffer.read(4)
            if size_bytes:
                size = struct.unpack(">I", size_bytes)[0]
                if size > 0:
                    session_id = buffer.read(size).decode("utf-8")

    # 连接确认事件含 connect_id 字段
    if event in (
        EventType.ConnectionStarted,
        EventType.ConnectionFailed,
        EventType.ConnectionFinished,
    ):
        size_bytes = buffer.read(4)
        if size_bytes:
            size = struct.unpack(">I", size_bytes)[0]
            if size > 0:
                buffer.read(size)

    size_bytes = buffer.read(4)
    if size_bytes:
        size = struct.unpack(">I", size_bytes)[0]
        if size > 0:
            payload = buffer.read(size)

    return {
        "msg_type": msg_type,
        "flag": flag,
        "event": event,
        "session_id": session_id,
        "payload": payload,
    }


# ──────────────────────────────────────────────────────
# 主客户端类
# ──────────────────────────────────────────────────────

class VolcenginePodcastTTS:
    ENDPOINT = "wss://openspeech.bytedance.com/api/v3/sami/podcasttts"
    DEFAULT_APP_KEY = "aGjiRDfUWi"
    DEFAULT_SPEAKERS = [
        "zh_male_dayixiansheng_v2_saturn_bigtts",
        "zh_female_mizaitongxue_v2_saturn_bigtts",
    ]

    def __init__(
        self,
        app_id: str,
        access_token: str,
        app_key: str = DEFAULT_APP_KEY,
        endpoint: str = ENDPOINT,
        progress_callback: Optional[Callable[[str], None]] = None,
    ):
        self.app_id = app_id
        self.access_token = access_token
        self.app_key = app_key
        self.endpoint = endpoint
        self.progress_callback = progress_callback

    def _log(self, msg: str, level: str = "info"):
        if level == "info":
            logger.info(f"[TTS] {msg}")
        elif level == "warn":
            logger.warning(f"[TTS] {msg}")
        if self.progress_callback:
            self.progress_callback(msg)

    def _get_headers(self) -> dict:
        return {
            "X-Api-App-Id": self.app_id,
            "X-Api-Access-Key": self.access_token,
            "X-Api-Resource-Id": "volc.service_type.10050",
            "X-Api-App-Key": self.app_key,
            "X-Api-Connect-Id": str(uuid.uuid4()),
        }

    async def _send(self, ws, msg_type, flag, event=EventType.None_, session_id="", payload=b""):
        frame = build_message(msg_type, flag, event, session_id, payload)
        await ws.send(frame)

    async def _recv(self, ws, timeout: float = 30.0) -> dict:
        data = await asyncio.wait_for(ws.recv(), timeout=timeout)
        return parse_message(data)

    async def _wait_for(self, ws, expected: EventType, timeout: float = 30.0) -> dict:
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise TimeoutError(f"等待 {expected.name} 超时 ({timeout}s)")
            msg = await asyncio.wait_for(self._recv(ws, timeout=remaining), timeout=remaining)
            if msg["event"] == expected:
                return msg
            if msg["event"] == EventType.ConnectionFailed:
                raise TTSConnectionError(msg["payload"].decode("utf-8", errors="ignore"))
            if msg["event"] == EventType.SessionFailed:
                raise TTSSessionError(msg["payload"].decode("utf-8", errors="ignore"))
            if msg["msg_type"] == MsgType.Error:
                code = struct.unpack(">I", msg["payload"][:4])[0] if len(msg["payload"]) >= 4 else 0
                err = msg["payload"][4:].decode("utf-8", errors="ignore")
                raise ProtocolError(f"Error {code}: {err}")

    def _build_payload(
        self,
        text: str,
        action: int = 0,
        speakers: Optional[List[str]] = None,
        use_head_music: bool = False,
        use_tail_music: bool = False,
        output_format: str = "mp3",
        sample_rate: int = 24000,
        speech_rate: int = 0,
    ) -> dict:
        return {
            "input_id": str(uuid.uuid4()),
            "input_text": text,
            "action": action,
            "use_head_music": use_head_music,
            "use_tail_music": use_tail_music,
            "audio_config": {
                "format": output_format,
                "sample_rate": sample_rate,
                "speech_rate": speech_rate,
            },
            "speaker_info": {
                "random_order": True,
                "speakers": speakers or self.DEFAULT_SPEAKERS,
            },
        }

    async def generate_podcast(
        self,
        text: str,
        speakers: Optional[List[str]] = None,
        use_head_music: bool = False,
        use_tail_music: bool = False,
        output_format: str = "mp3",
        sample_rate: int = 24000,
        speech_rate: int = 0,
    ) -> Tuple[bytes, Optional[float]]:
        """
        生成播客音频。
        返回：(音频二进制数据, 音频时长秒数)

        duration 提取策略（精度从高到低）：
        1. 累计各轮 PodcastRoundEnd.audio_duration（最精确）
        2. PodcastEnd.meta_info.duration
        3. UsageResponse.duration
        """
        if len(text) > 32000:
            text = text[:32000]
            self._log("文本超过 32000 字符，已截断", "warn")

        headers = self._get_headers()
        session_id = str(uuid.uuid4())

        audio_data = b""
        total_duration = 0.0  # 从各轮累计
        fallback_duration: Optional[float] = None
        round_idx = 0

        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        self._log("正在连接 WebSocket...")

        async with websockets.connect(
            self.endpoint,
            additional_headers=headers,
            ssl=ssl_ctx,
            open_timeout=15,
            close_timeout=5,
            ping_interval=10,
            ping_timeout=10,
        ) as ws:
            # 1. StartConnection
            await self._send(ws, MsgType.FullClientRequest, MsgTypeFlagBits.WithEvent,
                             EventType.StartConnection, payload=b"{}")
            await self._wait_for(ws, EventType.ConnectionStarted, timeout=15)
            self._log("连接建立")

            # 2. StartSession
            payload_bytes = json.dumps(
                self._build_payload(
                    text=text, action=0,
                    speakers=speakers,
                    use_head_music=use_head_music,
                    use_tail_music=use_tail_music,
                    output_format=output_format,
                    sample_rate=sample_rate,
                    speech_rate=speech_rate,
                ),
                ensure_ascii=False,
            ).encode("utf-8")

            await self._send(ws, MsgType.FullClientRequest, MsgTypeFlagBits.WithEvent,
                             EventType.StartSession, session_id, payload_bytes)
            await self._wait_for(ws, EventType.SessionStarted, timeout=30)
            self._log("会话启动，发送 FinishSession 触发生成...")

            # 3. FinishSession
            await self._send(ws, MsgType.FullClientRequest, MsgTypeFlagBits.WithEvent,
                             EventType.FinishSession, session_id, payload=b"{}")

            # 4. 接收数据
            chunk_count = 0
            while True:
                msg = await self._recv(ws, timeout=120)
                ev = msg["event"]

                if ev == EventType.PodcastRoundStart:
                    round_idx += 1
                    try:
                        info = json.loads(msg["payload"].decode("utf-8")) if msg["payload"] else {}
                        speaker = info.get("speaker", "?")
                        text_preview = info.get("text", "")[:30]
                    except Exception:
                        speaker, text_preview = "?", ""
                    self._log(f"第 {round_idx} 轮开始 — {speaker}: {text_preview}...")

                elif ev == EventType.PodcastRoundResponse:
                    audio_data += msg["payload"]
                    chunk_count += 1
                    # 不打印每个 chunk，仅统计

                elif ev == EventType.PodcastRoundEnd:
                    try:
                        info = json.loads(msg["payload"].decode("utf-8")) if msg["payload"] else {}
                        # 关键修复：从每轮 audio_duration 累计
                        round_dur = (
                            info.get("audio_duration")
                            or info.get("duration")
                            or 0.0
                        )
                        total_duration += float(round_dur)
                    except Exception:
                        pass
                    self._log(f"第 {round_idx} 轮结束，累计时长 {total_duration:.1f}s")

                elif ev == EventType.PodcastEnd:
                    try:
                        info = json.loads(msg["payload"].decode("utf-8")) if msg["payload"] else {}
                        meta = info.get("meta_info", {})
                        fallback_duration = (
                            meta.get("duration")
                            or info.get("duration")
                        )
                    except Exception:
                        pass

                elif ev == EventType.UsageResponse:
                    try:
                        info = json.loads(msg["payload"].decode("utf-8")) if msg["payload"] else {}
                        if not fallback_duration:
                            fallback_duration = info.get("duration")
                    except Exception:
                        pass

                elif ev == EventType.SessionFinished:
                    break

            self._log(
                f"接收完成：{round_idx} 轮对话，{chunk_count} 个音频分片，"
                f"{len(audio_data):,} bytes，时长 {total_duration:.1f}s"
            )

            # 5. FinishConnection
            await self._send(ws, MsgType.FullClientRequest, MsgTypeFlagBits.WithEvent,
                             EventType.FinishConnection, payload=b"{}")
            try:
                await self._wait_for(ws, EventType.ConnectionFinished, timeout=10)
            except Exception:
                pass  # 连接关闭时允许超时

        # 时长最终值：累计优先，fallback 备用
        final_duration = total_duration if total_duration > 0 else (fallback_duration or 0.0)
        if final_duration == 0.0:
            self._log("警告：无法获取准确时长，将由调用方推算", "warn")

        return audio_data, final_duration
