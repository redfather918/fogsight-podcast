"""
Pipeline 编排器：串联所有步骤，管理状态和 WebSocket 进度推送
"""
import asyncio
import os
import json
from typing import Optional, Callable, Awaitable
from app.config import settings
from app.models.job import update_job
from app.services.pdf_parser import PDFParser
from app.services.content_generator import ContentGenerator
from app.services.animation_engine import AnimationEngine
from app.services.podcast_tts import PodcastTTSService
from app.services.audio_sync import AudioSync
from app.services.video_renderer import VideoRenderer
from app.utils.logger import logger
from app.utils.cleanup import safe_delete


# 进度区间定义
PROGRESS_MAP = {
    "parsing":   (0,  10),
    "scripting": (10, 25),
    "animating": (25, 45),
    "tts":       (45, 70),
    "syncing":   (70, 72),
    "recording": (72, 92),
    "composing": (92, 100),
    "done":      (100, 100),
}

STAGE_LABELS = {
    "parsing":   "PDF 解析",
    "scripting": "脚本生成",
    "animating": "动画生成",
    "tts":       "音频生成",
    "syncing":   "音画同步",
    "recording": "视频录制",
    "composing": "视频合成",
    "done":      "完成",
}


class Pipeline:
    def __init__(self, ws_send: Optional[Callable[[dict], Awaitable[None]]] = None):
        """
        ws_send: 异步函数，用于向前端推送 WebSocket 消息
        """
        self.ws_send = ws_send
        self.pdf_parser = PDFParser()
        self.content_gen = ContentGenerator()
        self.anim_engine = AnimationEngine()
        self.audio_sync = AudioSync()
        self.renderer = VideoRenderer()

    async def _push(self, job_id: str, stage: str, progress: int, message: str):
        """更新数据库 + 推送 WebSocket"""
        await update_job(
            job_id,
            status=stage if stage != "done" else "done",
            stage=stage,
            progress=progress,
            message=message,
        )
        if self.ws_send:
            await self.ws_send({
                "type": "progress",
                "stage": stage,
                "progress": progress,
                "message": message,
            })

    async def _log_ws(self, message: str, level: str = "info"):
        if self.ws_send:
            from datetime import datetime, timezone
            await self.ws_send({
                "type": "log",
                "level": level,
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    def _make_tts_callback(self, job_id: str, stage: str) -> Callable[[str], None]:
        def callback(msg: str):
            # 同步 log 推送（非 await，在协程外调用）
            asyncio.get_event_loop().create_task(self._log_ws(msg))
        return callback

    async def run(
        self,
        job_id: str,
        pdf_path: str,
        target_duration: int = 60,
        speech_rate: int = 0,
    ):
        """执行完整 Pipeline"""
        logger.info(f"Pipeline 开始：job_id={job_id}，pdf={pdf_path}")
        output_dir = os.path.abspath(settings.output_dir)
        temp_files = []

        try:
            # ── Step 1: PDF 解析 ──────────────────────────
            await self._push(job_id, "parsing", 5, "正在解析 PDF...")
            pdf_content = self.pdf_parser.extract_text(pdf_path, settings.max_pdf_pages)
            await self._push(job_id, "parsing", 10, f"PDF 解析完成：{pdf_content.page_count} 页，标题：{pdf_content.title}")
            await update_job(job_id, video_title=pdf_content.title)

            # ── Step 2: 脚本生成 ──────────────────────────
            await self._push(job_id, "scripting", 12, "LLM 生成播客脚本中...")

            async def script_progress(msg):
                await self._log_ws(msg)

            script = await self.content_gen.generate_script(
                pdf_content,
                target_duration=target_duration,
                progress_callback=lambda m: asyncio.get_event_loop().create_task(self._log_ws(m)),
            )
            await self._push(job_id, "scripting", 25,
                             f"脚本生成完成：{len(script.rounds)} 轮对话，预估 {script.estimated_duration:.0f}s")

            # ── Step 3: 动画生成 ──────────────────────────
            await self._push(job_id, "animating", 27, "LLM 生成动画 HTML...")
            html = await self.anim_engine.generate_html(
                script,
                target_duration=target_duration,
                progress_callback=lambda m: asyncio.get_event_loop().create_task(self._log_ws(m)),
            )

            # 保存 HTML 到临时文件
            html_path = os.path.join(output_dir, f"{job_id}_animation.html")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)
            temp_files.append(html_path)
            await self._push(job_id, "animating", 45,
                             f"动画 HTML 生成完成（{len(html):,} 字符）")

            # ── Step 4: 音频生成 ──────────────────────────
            await self._push(job_id, "tts", 47, "火山引擎 TTS 生成音频中...")

            tts_service = PodcastTTSService(
                progress_callback=lambda m: asyncio.get_event_loop().create_task(self._log_ws(m))
            )
            script_text = script.to_text()
            audio_result = await tts_service.generate(
                text=script_text,
                speech_rate=speech_rate,
                estimated_duration=float(target_duration),
            )

            # 保存音频
            audio_path = os.path.join(output_dir, f"{job_id}_audio.mp3")
            await tts_service.save(audio_result, audio_path)
            temp_files.append(audio_path)

            await self._push(job_id, "tts", 70,
                             f"音频生成完成：{audio_result.size:,} bytes，时长 {audio_result.duration:.1f}s")

            # ── Step 5: 音画同步 ──────────────────────────
            await self._push(job_id, "syncing", 71, "注入音频到动画 HTML...")

            audio_filename = f"/api/jobs/{job_id}/audio"  # 前端访问路径
            synced_html = self.audio_sync.inject(html, audio_filename, audio_result.duration)

            synced_html_path = os.path.join(output_dir, f"{job_id}_synced.html")
            with open(synced_html_path, "w", encoding="utf-8") as f:
                f.write(synced_html)
            temp_files.append(synced_html_path)
            await self._push(job_id, "syncing", 72, "音画同步完成")

            # ── Step 6: 视频录制 ──────────────────────────
            await self._push(job_id, "recording", 74, "Puppeteer 录制视频...")

            renderer = VideoRenderer(
                progress_callback=lambda m: asyncio.get_event_loop().create_task(self._log_ws(m))
            )
            mp4_path = await renderer.record(
                html_path=synced_html_path,
                audio_path=audio_path,
                output_dir=output_dir,
                job_id=job_id,
                duration=audio_result.duration,
            )

            await self._push(job_id, "recording", 92, "视频录制完成")

            # ── Done ──────────────────────────────────────
            video_size = os.path.getsize(mp4_path) if os.path.exists(mp4_path) else 0
            await update_job(
                job_id,
                status="done",
                stage="done",
                progress=100,
                message="视频生成完成！",
                video_path=mp4_path,
                video_duration=audio_result.duration,
                video_size=video_size,
                video_title=pdf_content.title,
            )

            if self.ws_send:
                await self.ws_send({
                    "type": "done",
                    "video_url": f"/api/jobs/{job_id}/video",
                    "duration": audio_result.duration,
                    "file_size": video_size,
                    "title": pdf_content.title,
                })

            logger.info(f"Pipeline 完成：job_id={job_id}，视频={mp4_path}，大小={video_size:,} bytes")

        except Exception as e:
            err_msg = str(e)
            logger.error(f"Pipeline 失败：job_id={job_id}，错误={err_msg}")

            # 友好的错误提示
            friendly_msg = err_msg
            if "400" in err_msg or "rejected" in err_msg or "WebSocket" in err_msg:
                friendly_msg = "语音合成服务连接失败（请检查火山引擎凭证配置）"
            elif "timeout" in err_msg.lower() or "TimeoutError" in err_msg:
                friendly_msg = "处理超时，请稍后重试"
            elif "API key" in err_msg.lower() or "auth" in err_msg.lower():
                friendly_msg = "API 密钥无效或已过期"
            elif "pdf" in err_msg.lower() or "PDF" in err_msg:
                friendly_msg = "PDF 解析失败，请检查文件格式"
            else:
                friendly_msg = f"生成失败：{err_msg[:100]}"

            await update_job(job_id, status="failed", error=err_msg, message=friendly_msg)
            if self.ws_send:
                await self.ws_send({
                    "type": "error",
                    "message": friendly_msg,
                    "stage": "unknown",
                })
            raise

        finally:
            # 清理 PDF 上传文件
            safe_delete(pdf_path)
