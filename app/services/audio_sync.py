"""
音画同步：将音频注入动画 HTML
"""
import re
from app.utils.logger import logger


# 注入到 HTML 中的音频播放脚本模板
AUDIO_INJECT_SCRIPT = """
<script>
(function() {{
    var audioPath = "{audio_filename}";
    var animDuration = {audio_duration};

    // 更新全局变量
    window.PODCAST_AUDIO_PATH = audioPath;
    window.ANIMATION_DURATION = animDuration;

    // 等待 DOM 就绪后创建音频元素
    function setupAudio() {{
        var existingAudio = document.getElementById('_podcast_audio');
        if (existingAudio) return;

        var audio = document.createElement('audio');
        audio.id = '_podcast_audio';
        audio.src = audioPath;
        audio.preload = 'auto';
        audio.style.display = 'none';
        document.body.appendChild(audio);

        // 通知页面音频已就绪
        window._podcastAudio = audio;
        window.dispatchEvent(new CustomEvent('podcastAudioReady', {{ detail: {{ audio: audio, duration: animDuration }} }}));

        // 自动播放（需用户交互触发）
        audio.play().catch(function(e) {{
            console.log('[Fogsight] 自动播放被阻止，等待用户交互:', e.message);
            document.addEventListener('click', function() {{
                audio.play();
            }}, {{ once: true }});
        }});
    }}

    if (document.readyState === 'loading') {{
        document.addEventListener('DOMContentLoaded', setupAudio);
    }} else {{
        setupAudio();
    }}
}})();
</script>
"""


class AudioSync:
    def inject(
        self,
        html: str,
        audio_filename: str,
        audio_duration: float,
    ) -> str:
        """
        将音频路径和时长注入到动画 HTML。

        策略：
        1. 替换 window.PODCAST_AUDIO_PATH = "" 为实际路径
        2. 替换 window.ANIMATION_DURATION = xxx 为实际音频时长
        3. 在 </body> 前注入音频加载脚本
        """
        # 1. 替换音频路径
        html = re.sub(
            r'window\.PODCAST_AUDIO_PATH\s*=\s*["\'].*?["\']',
            f'window.PODCAST_AUDIO_PATH = "{audio_filename}"',
            html,
        )

        # 2. 替换动画时长
        html = re.sub(
            r'window\.ANIMATION_DURATION\s*=\s*[\d.]+',
            f'window.ANIMATION_DURATION = {audio_duration:.1f}',
            html,
        )

        # 3. 注入音频控制脚本
        inject = AUDIO_INJECT_SCRIPT.format(
            audio_filename=audio_filename,
            audio_duration=round(audio_duration, 1),
        )

        if "</body>" in html:
            html = html.replace("</body>", inject + "\n</body>", 1)
        else:
            html += inject

        logger.info(f"音画同步注入完成：audio={audio_filename}，duration={audio_duration:.1f}s")
        return html
