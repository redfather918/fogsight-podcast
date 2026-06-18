"""
播客 TTS 服务（火山引擎）封装
"""
import os
from dataclasses import dataclass
from typing import Optional, Callable
from app.config import settings
from app.utils.logger import logger
from core.volcengine_protocol import VolcenginePodcastTTS


@dataclass
class AudioResult:
    audio_data: bytes
    duration: float     # 秒
    format: str = "mp3"
    size: int = 0

    def __post_init__(self):
        self.size = len(self.audio_data)


class PodcastTTSService:
    def __init__(self, progress_callback: Optional[Callable[[str], None]] = None):
        self.client = VolcenginePodcastTTS(
            app_id=settings.volc_app_id,
            access_token=settings.volc_access_token,
            app_key=settings.volc_app_key,
            progress_callback=progress_callback,
        )

    async def generate(
        self,
        text: str,
        speech_rate: int = 0,
        estimated_duration: float = 60.0,
    ) -> AudioResult:
        """
        生成播客音频。
        speech_rate: -50~100，负数变慢，正数变快
        estimated_duration: 动画估算时长，duration=0 时的 fallback
        """
        logger.info(f"开始生成 TTS，文本长度 {len(text)} 字，speech_rate={speech_rate}")

        audio_data, duration = await self.client.generate_podcast(
            text=text,
            speech_rate=speech_rate,
        )

        # duration fallback：若 API 无法返回，用估算值
        if not duration or duration <= 0:
            logger.warning("API 未返回有效时长，使用动画估算时长作为 fallback")
            duration = estimated_duration

        result = AudioResult(audio_data=audio_data, duration=duration)
        logger.info(f"TTS 完成：{result.size:,} bytes，时长 {result.duration:.1f}s")
        return result

    async def save(self, audio_result: AudioResult, output_path: str):
        """保存音频到文件"""
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_result.audio_data)
        logger.info(f"音频已保存：{output_path}")
