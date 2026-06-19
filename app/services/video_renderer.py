"""
Puppeteer 录屏服务：HTML 动画 → WebM 视频
"""
import asyncio
import json
import os
import subprocess
import tempfile
from typing import Optional, Callable
from app.config import settings
from app.utils.logger import logger

# Puppeteer 录屏脚本（Node.js）
PUPPETEER_SCRIPT = """
const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

async function record(htmlPath, outputPath, duration, width, height, fps) {
    const browser = await puppeteer.launch({
        headless: 'new',
        executablePath: process.env.CHROME_PATH || undefined,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-web-security',
            '--allow-file-access-from-files',
        ],
    });

    const page = await browser.newPage();
    await page.setViewport({ width, height, deviceScaleFactor: 1 });

    const fileUrl = 'file://' + path.resolve(htmlPath);
    console.error('Loading: ' + fileUrl);
    await page.goto(fileUrl, { waitUntil: 'networkidle0', timeout: 60000 });

    // 等待动画初始化（容忍没有 ANIMATION_DURATION 的情况）
    try {
        await page.waitForFunction(
            () => typeof window.ANIMATION_DURATION !== 'undefined',
            { timeout: 15000 }
        );
        console.error('ANIMATION_DURATION detected');
    } catch(e) {
        console.warn('ANIMATION_DURATION not found, using parameter duration=' + duration);
    }

    // 额外等待页面渲染
    await new Promise(r => setTimeout(r, 2000));
    console.error('Starting screencast...');

    // 使用 CDP 截帧方式录制
    const client = await page.createCDPSession();
    await client.send('Page.startScreencast', {
        format: 'jpeg',
        quality: 80,
        maxWidth: width,
        maxHeight: height,
        everyNthFrame: 1,
    });

    const frames = [];
    const frameDir = outputPath + '_frames';
    fs.mkdirSync(frameDir, { recursive: true });

    let frameIdx = 0;
    const recordDuration = duration * 1000;
    const startTime = Date.now();

    client.on('Page.screencastFrame', async (event) => {
        if (Date.now() - startTime > recordDuration) return;
        const framePath = path.join(frameDir, `frame_${String(frameIdx).padStart(5,'0')}.jpg`);
        fs.writeFileSync(framePath, Buffer.from(event.data, 'base64'));
        frames.push(framePath);
        frameIdx++;
        if (frameIdx % 30 === 0) {
            console.error(`Captured ${frameIdx} frames (${Math.round((Date.now()-startTime)/1000)}s/${duration}s)`);
        }
        await client.send('Page.screencastFrameAck', { sessionId: event.sessionId });
    });

    // 录制指定时长（加缓冲）
    await new Promise(r => setTimeout(r, recordDuration + 2000));

    await client.send('Page.stopScreencast');
    await browser.close();

    console.log(JSON.stringify({ frames: frameDir, count: frameIdx }));
}

const [, , htmlPath, outputPath, duration, width, height, fps] = process.argv;
record(htmlPath, outputPath, parseFloat(duration), parseInt(width), parseInt(height), parseInt(fps))
    .catch(e => { console.error('RECORD_ERROR: ' + e.message); process.exit(1); });
"""


class VideoRenderer:
    def __init__(self, progress_callback: Optional[Callable[[str], None]] = None):
        self.progress_callback = progress_callback

    def _log(self, msg: str):
        logger.info(f"[Renderer] {msg}")
        if self.progress_callback:
            self.progress_callback(msg)

    async def record(
        self,
        html_path: str,
        audio_path: str,
        output_dir: str,
        job_id: str,
        duration: float,
        width: int = 1920,
        height: int = 1080,
        fps: int = 30,
    ) -> str:
        """
        录制 HTML 动画并与音频合成为 MP4。
        返回：mp4 输出路径
        """
        self._log(f"开始录屏：时长 {duration:.1f}s，分辨率 {width}x{height}")
        os.makedirs(output_dir, exist_ok=True)

        frames_dir = os.path.join(output_dir, f"{job_id}_frames")
        webm_path = os.path.join(output_dir, f"{job_id}.webm")
        mp4_path = os.path.join(output_dir, f"{job_id}.mp4")

        # 写 Puppeteer 脚本到临时文件
        script_path = os.path.join(output_dir, f"{job_id}_record.js")
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(PUPPETEER_SCRIPT)

        # 查找 Node.js
        node_path = self._find_node()
        self._log(f"使用 Node: {node_path}")

        # 执行录屏（设置 NODE_PATH 以便找到 puppeteer 模块）
        node_modules = r"C:\Users\HUAWEI\.workbuddy\binaries\node\workspace\node_modules"
        env = {**os.environ, "NODE_PATH": node_modules}

        cmd = [
            node_path, script_path,
            os.path.abspath(html_path),
            os.path.abspath(frames_dir),
            str(duration + 2),
            str(width), str(height), str(fps),
        ]

        timeout = max(duration * 2, 120)  # 至少 2 倍时长或 120s
        self._log("正在录制帧序列...")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"Puppeteer 录屏超时（{timeout}s）")

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="ignore")[-1000:]
            raise RuntimeError(f"Puppeteer 录屏失败: {err}")

        stdout_str = stdout.decode("utf-8", errors="ignore").strip()
        self._log(f"Puppeteer 输出: {stdout_str[:200]}")

        # 用 FFmpeg 将帧序列 + 音频合成 MP4
        self._log("用 FFmpeg 合成 MP4...")
        mp4_path = await self._frames_to_mp4(
            frames_dir, audio_path, mp4_path, fps, duration
        )

        # 清理临时文件
        try:
            os.remove(script_path)
            import shutil
            shutil.rmtree(frames_dir, ignore_errors=True)
        except Exception:
            pass

        self._log(f"录屏完成：{mp4_path}")
        return mp4_path

    async def _frames_to_mp4(
        self, frames_dir: str, audio_path: str, output_path: str,
        fps: int, duration: float
    ) -> str:
        """帧序列 + 音频 → MP4"""
        frame_pattern = os.path.join(frames_dir, "frame_%05d.jpg")

        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", frame_pattern,
            "-i", audio_path,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-c:a", "aac",
            "-b:a", "128k",
            "-shortest",
            "-movflags", "+faststart",
            "-t", str(duration + 1),
            output_path,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=max(duration * 3, 180))

        if proc.returncode != 0:
            err = stderr.decode("utf-8", errors="ignore")[-1000:]
            raise RuntimeError(f"FFmpeg 合成失败: {err}")

        return output_path

    def _find_node(self) -> str:
        """查找 Node.js 可执行文件"""
        candidates = [
            r"C:\Users\HUAWEI\.workbuddy\binaries\node\versions\22.22.2\node.exe",
            r"C:\Program Files\nodejs\node.exe",
            "node",
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return "node"
