"""
动画 HTML 生成服务（DeepSeek LLM）
"""
import json
import re
from typing import Optional, Callable
from openai import AsyncOpenAI
from app.config import settings
from app.services.content_generator import PodcastScript
from app.utils.logger import logger


ANIMATION_SYSTEM_PROMPT = """你是一位专业的交互动画工程师，擅长用纯 HTML + Canvas + GSAP 生成精美的科普动画页面。

生成规范（必须严格遵守）：
1. 输出完整的 HTML 文件（<!DOCTYPE html>...）
2. 视口：1920x1080，16:9 横屏
3. 配色：浅色系，背景白/浅灰，文字深色
4. 动画：用 Canvas + requestAnimationFrame 驱动，流畅且有视觉冲击力
5. 字幕系统：
   - 页面底部显示当前字幕（来自 NARRATION_DATA）
   - 显示说话人名称 + 文本
   - 根据音频进度自动切换（若有音频）
6. 必须包含以下全局变量（window 对象上）：
   - window.NARRATION_DATA = {narration_json}  // 字幕数据
   - window.ANIMATION_DURATION = {duration}    // 动画总时长（秒）
   - window.PODCAST_AUDIO_PATH = ""            // 音频路径（后端注入，初始为空）
7. 音频同步：
   - 页面加载时检查 window.PODCAST_AUDIO_PATH
   - 若不为空，创建 <audio> 并自动播放
   - 用 audio.currentTime 驱动字幕切换
   - 若为空，用 requestAnimationFrame 计时器模拟
8. 动画内容要与主题相关，要有创意，不要单调
9. 不要使用外部字体（避免网络请求失败）

主题：{topic}"""

ANIMATION_USER_TEMPLATE = """请为以下播客脚本生成完整的动画 HTML：

主题：{topic}
目标时长：{duration} 秒

旁白数据（NARRATION_DATA）：
{narration_json}

生成要求：
- 动画要生动有趣，与主题 "{topic}" 视觉相关
- Canvas 动画要有粒子/几何/数据可视化等视觉元素
- 字幕实时同步显示
- 整体感觉：科技感 + 知识感

直接输出完整 HTML，不需要其他说明。"""


class AnimationEngine:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )

    async def generate_html(
        self,
        script: PodcastScript,
        target_duration: int = 60,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> str:
        narration_data = script.to_narration_data()
        narration_json = json.dumps(narration_data, ensure_ascii=False, indent=2)
        duration = max(target_duration, int(script.estimated_duration))

        system = ANIMATION_SYSTEM_PROMPT.format(
            narration_json=narration_json,
            duration=duration,
            topic=script.topic,
        )
        user = ANIMATION_USER_TEMPLATE.format(
            topic=script.topic,
            duration=duration,
            narration_json=narration_json,
        )

        if progress_callback:
            progress_callback("LLM 正在生成动画 HTML...")

        logger.info(f"生成动画 HTML：主题={script.topic!r}，时长={duration}s")

        resp = await self.client.chat.completions.create(
            model=settings.deepseek_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.6,
            max_tokens=8192,
        )

        html = resp.choices[0].message.content.strip()

        # 确保提取纯 HTML（去掉 markdown 代码块）
        html = self._extract_html(html)

        # 校验关键变量存在
        html = self._ensure_globals(html, narration_data, duration)

        logger.info(f"动画 HTML 生成完成：{len(html)} 字符")
        if progress_callback:
            progress_callback(f"动画 HTML 生成完成（{len(html):,} 字符）")

        return html

    def _extract_html(self, raw: str) -> str:
        """从 LLM 输出提取纯 HTML"""
        m = re.search(r"```html\s*([\s\S]+?)\s*```", raw)
        if m:
            return m.group(1).strip()
        m = re.search(r"```\s*(<!DOCTYPE[\s\S]+?)\s*```", raw)
        if m:
            return m.group(1).strip()
        if "<!DOCTYPE" in raw or "<html" in raw:
            start = raw.find("<!DOCTYPE")
            if start == -1:
                start = raw.find("<html")
            return raw[start:].strip()
        return raw

    def _ensure_globals(self, html: str, narration_data: list, duration: int) -> str:
        """确保 window.NARRATION_DATA / ANIMATION_DURATION / PODCAST_AUDIO_PATH 存在"""
        narration_json = json.dumps(narration_data, ensure_ascii=False)

        if "NARRATION_DATA" not in html:
            inject = f"""
<script>
window.NARRATION_DATA = {narration_json};
window.ANIMATION_DURATION = {duration};
window.PODCAST_AUDIO_PATH = "";
</script>"""
            html = html.replace("</head>", inject + "\n</head>", 1)
            if "</head>" not in html:
                html = inject + html

        if "PODCAST_AUDIO_PATH" not in html:
            inject = """
<script>
if (typeof window.PODCAST_AUDIO_PATH === 'undefined') {
    window.PODCAST_AUDIO_PATH = "";
}
</script>"""
            html = html.replace("</head>", inject + "\n</head>", 1)

        return html
