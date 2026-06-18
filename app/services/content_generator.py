"""
LLM 内容生成：PDF → 播客脚本
"""
import json
import re
from typing import Optional, Callable
from openai import AsyncOpenAI
from app.config import settings
from app.services.pdf_parser import PDFContent
from app.utils.logger import logger


SCRIPT_SYSTEM_PROMPT = """你是一位顶级知识科普编剧，擅长将复杂文档转化为引人入胜的双人播客对谈脚本。
你的播客由两位主持人组成：
- 大艺先生（男，理性分析派，喜欢讲原理）
- 咪仔同学（女，活泼好奇派，善于类比和追问）

要求：
1. 对谈自然流畅，口语化，有互动感
2. 脚本总时长约 {duration} 秒（按正常语速，每秒约 3-4 个字）
3. 输出格式：严格的 JSON 数组，每条格式为：
   {{"speaker": "大艺先生" 或 "咪仔同学", "text": "说话内容（中文）"}}
4. 总条数：约 {rounds} 条对话
5. 只输出 JSON 数组，不要有任何其他文字

示例输出：
[
  {{"speaker": "大艺先生", "text": "今天我们来聊一个超级有意思的话题——黑洞。"}},
  {{"speaker": "咪仔同学", "text": "对！黑洞这个词听起来就很酷，但它到底是什么？"}},
  {{"speaker": "大艺先生", "text": "简单说，黑洞是空间中引力强到连光都逃不掉的区域。"}}
]"""

SCRIPT_USER_TEMPLATE = """请根据以下文档内容，生成一段双人播客对谈脚本：

文档标题：{title}

文档内容：
{content}

要求时长约 {duration} 秒，输出纯 JSON 数组。"""


class PodcastScript:
    def __init__(self, topic: str, rounds: list, estimated_duration: float = 0):
        self.topic = topic
        self.rounds = rounds  # [{"speaker": str, "text": str}]
        self.estimated_duration = estimated_duration

    def to_text(self) -> str:
        """把脚本转成纯文本，供 TTS 使用"""
        return "\n".join(f"{r['speaker']}：{r['text']}" for r in self.rounds)

    def to_narration_data(self) -> list:
        """转成动画 HTML 需要的 NARRATION_DATA 格式"""
        result = []
        # 估算时间戳（按 3.5 字/秒）
        t = 0.0
        for r in self.rounds:
            chars = len(r["text"])
            duration = max(chars / 3.5, 1.0)
            result.append({
                "timestamp": round(t, 1),
                "speaker": r["speaker"],
                "text_cn": r["text"],
                "duration": round(duration, 1),
            })
            t += duration + 0.3  # 间隔
        return result


class ContentGenerator:
    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )

    async def generate_script(
        self,
        pdf_content: PDFContent,
        target_duration: int = 60,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> PodcastScript:
        # 估算轮数：目标时长 / 每轮平均 8s
        rounds = max(int(target_duration / 8), 6)

        # 截取内容（避免超出 LLM 上下文）
        content = pdf_content.total_text
        if len(content) > 6000:
            content = content[:6000] + "\n...(内容过长，已截取前部分)"

        system = SCRIPT_SYSTEM_PROMPT.format(duration=target_duration, rounds=rounds)
        user = SCRIPT_USER_TEMPLATE.format(
            title=pdf_content.title,
            content=content,
            duration=target_duration,
        )

        if progress_callback:
            progress_callback("LLM 正在生成脚本...")

        logger.info(f"生成播客脚本：目标 {target_duration}s，约 {rounds} 轮")

        resp = await self.client.chat.completions.create(
            model=settings.deepseek_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.7,
            max_tokens=4096,
        )

        raw = resp.choices[0].message.content.strip()

        # 解析 JSON
        script_rounds = self._parse_json(raw)
        if not script_rounds:
            logger.warning("LLM 输出无法解析为 JSON，使用默认脚本")
            script_rounds = [
                {"speaker": "大艺先生", "text": f"今天我们来解读这篇文档：{pdf_content.title}"},
                {"speaker": "咪仔同学", "text": "好的！请讲解一下核心内容吧。"},
            ]

        # 估算实际时长
        total_chars = sum(len(r["text"]) for r in script_rounds)
        estimated = total_chars / 3.5

        logger.info(f"脚本生成完成：{len(script_rounds)} 轮，预估 {estimated:.0f}s")
        if progress_callback:
            progress_callback(f"脚本生成完成：{len(script_rounds)} 轮对话")

        return PodcastScript(
            topic=pdf_content.title,
            rounds=script_rounds,
            estimated_duration=estimated,
        )

    def _parse_json(self, raw: str) -> list:
        # 尝试直接解析
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass

        # 提取代码块内容
        m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
        if m:
            try:
                data = json.loads(m.group(1))
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass

        # 提取 [...] 块
        m = re.search(r"\[[\s\S]+\]", raw)
        if m:
            try:
                data = json.loads(m.group(0))
                if isinstance(data, list):
                    return data
            except json.JSONDecodeError:
                pass

        return []
