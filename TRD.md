# TRD — PDF to Video Podcast Generator

> **项目代号**：Fogsight-Podcast  
> **版本**：v1.0  
> **日期**：2026-06-18  
> **状态**：Draft

---

## 1. 系统架构

### 1.1 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                        浏览器 (前端)                          │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐  ┌─────────┐  │
│  │ 上传页面   │  │ 进度页面   │  │ 结果页面   │  │ 历史页   │  │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └────┬────┘  │
│        │              │ WS            │              │       │
└────────┼──────────────┼───────────────┼──────────────┼──────┘
         │ HTTP         │ WebSocket     │ HTTP         │ HTTP
         ▼              ▼               ▼              ▼
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI 后端                              │
│                                                               │
│  ┌─────────┐  ┌──────────┐  ┌───────────┐  ┌────────────┐  │
│  │ API层    │  │ WebSocket │  │ 任务队列   │  │ 静态文件    │  │
│  │ Routes   │  │ Progress  │  │ JobQueue  │  │ Static     │  │
│  └────┬────┘  └─────┬────┘  └─────┬─────┘  └────────────┘  │
│       │             │             │                          │
│  ┌────▼─────────────▼─────────────▼──────────────────────┐  │
│  │                    Service 层                          │  │
│  │                                                        │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐            │  │
│  │  │PDF Parser│→ │LLM Script│→ │Animation │            │  │
│  │  │          │  │Generator │  │Generator │            │  │
│  │  └──────────┘  └──────────┘  └────┬─────┘            │  │
│  │                                     │                  │  │
│  │  ┌──────────┐  ┌──────────┐  ┌────▼─────┐            │  │
│  │  │Video     │← │Audio     │← │Podcast   │            │  │
│  │  │Composer  │  │Sync      │  │TTS       │            │  │
│  │  └────┬─────┘  └──────────┘  └──────────┘            │  │
│  │       │                                                │  │
│  │  ┌────▼─────┐                                         │  │
│  │  │Puppeteer │                                         │  │
│  │  │Recorder  │                                         │  │
│  │  └──────────┘                                         │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  Storage 层                                           │    │
│  │  ┌────────┐  ┌────────┐  ┌────────┐  ┌──────────┐   │    │
│  │  │Uploads │  │Temp    │  │Output  │  │SQLite DB │   │    │
│  │  │(PDF)   │  │(HTML/  │  │(MP4)   │  │(Jobs)    │   │    │
│  │  │        │  │ MP3)   │  │        │  │          │   │    │
│  │  └────────┘  └────────┘  └────────┘  └──────────┘   │    │
│  └──────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
         │                                              │
         ▼                                              ▼
┌─────────────────┐                        ┌─────────────────┐
│  DeepSeek API   │                        │  火山引擎 TTS    │
│  (LLM 内容生成)  │                        │  (WebSocket)     │
└─────────────────┘                        └─────────────────┘
```

### 1.2 技术栈

| 层 | 技术 | 版本 | 用途 |
|----|------|------|------|
| **前端** | Vanilla JS + CSS3 | - | 轻量，无构建步骤 |
| **后端** | Python + FastAPI | 3.13 + 0.115+ | API + WebSocket + 静态文件 |
| **PDF 解析** | PyMuPDF (fitz) | 1.24+ | 高性能 PDF 文本提取 |
| **LLM** | DeepSeek API | deepseek-chat | 脚本 + 动画 HTML 生成 |
| **TTS** | 火山引擎播客 TTS | v3 WebSocket | 双人播客对谈音频 |
| **录屏** | Puppeteer + Chrome | 23+ | Headless 浏览器录屏 |
| **视频合成** | FFmpeg | 6+ | 音视频合并、转码 |
| **数据库** | SQLite | - | 任务记录、轻量存储 |
| **进程管理** | asyncio + ThreadPoolExecutor | - | 异步 IO + CPU 密集任务分离 |

---

## 2. 目录结构

```
fogsight-podcast/
├── PRD.md                         # 产品需求文档
├── TRD.md                         # 技术需求文档（本文档）
├── README.md                      # 项目说明
├── requirements.txt               # Python 依赖
├── .env.example                   # 环境变量模板
├── run.py                         # 启动入口
│
├── app/                           # 主应用
│   ├── __init__.py
│   ├── main.py                    # FastAPI app 实例 + 路由注册
│   ├── config.py                  # 配置管理（环境变量读取）
│   │
│   ├── models/                    # 数据模型
│   │   ├── __init__.py
│   │   ├── job.py                 # Job ORM 模型 (SQLite)
│   │   └── schemas.py             # Pydantic 请求/响应模型
│   │
│   ├── api/                       # API 路由层
│   │   ├── __init__.py
│   │   ├── routes.py              # REST API 端点
│   │   └── websocket.py           # WebSocket 进度推送
│   │
│   ├── services/                  # 业务逻辑层
│   │   ├── __init__.py
│   │   ├── pdf_parser.py          # PDF 文本提取
│   │   ├── content_generator.py   # LLM 脚本生成（DeepSeek）
│   │   ├── animation_engine.py    # 动画 HTML 生成（DeepSeek）
│   │   ├── podcast_tts.py         # 火山引擎播客 TTS 封装
│   │   ├── audio_sync.py          # 音画同步逻辑
│   │   ├── video_renderer.py      # Puppeteer 录屏
│   │   ├── video_composer.py      # FFmpeg 视频合成
│   │   └── pipeline.py            # Pipeline 编排器（串联所有步骤）
│   │
│   └── utils/                     # 工具
│       ├── __init__.py
│       ├── logger.py              # 日志配置
│       └── cleanup.py             # 临时文件清理
│
├── core/                          # 核心协议实现
│   ├── __init__.py
│   └── volcengine_protocol.py     # 火山引擎 WS 二进制协议
│
├── static/                        # 前端静态文件
│   ├── index.html                 # 主页面（SPA）
│   ├── css/
│   │   └── style.css
│   └── js/
│       └── app.js                 # 前端逻辑
│
├── templates/                     # Prompt 模板
│   ├── script_prompt.txt          # 脚本生成 Prompt
│   └── animation_prompt.txt       # 动画生成 Prompt
│
├── tests/                         # 测试
│   ├── __init__.py
│   ├── test_pdf_parser.py
│   ├── test_pipeline.py
│   └── fixtures/                  # 测试用 PDF
│
├── uploads/                       # 上传的 PDF（临时，.gitignore）
├── output/                        # 生成的视频（.gitignore）
└── data/                          # SQLite 数据库（.gitignore）
```

---

## 3. 模块设计

### 3.1 PDF Parser (`pdf_parser.py`)

**职责**：从 PDF 文件提取文本内容

```python
class PDFParser:
    def extract_text(self, pdf_path: str, max_pages: int = 100) -> PDFContent:
        """提取 PDF 文本，返回结构化内容"""
        # 返回: PDFContent(title, pages: list[str], total_text: str)
```

| 参数 | 说明 |
|------|------|
| pdf_path | PDF 文件路径 |
| max_pages | 最大解析页数（默认 100） |
| 返回 | PDFContent（标题、分页文本、全文） |

**技术选择**：PyMuPDF (fitz) — 比 pdfplumber 快 5-10x，原生支持中文

### 3.2 Content Generator (`content_generator.py`)

**职责**：LLM 将 PDF 内容转化为播客脚本

```python
class ContentGenerator:
    async def generate_script(
        self, pdf_content: PDFContent, target_duration: int = 60
    ) -> PodcastScript:
        """生成双人播客脚本"""
        # 返回: PodcastScript(topic, narration: list[NarrationItem], estimated_duration)
```

**Prompt 策略**：
1. System Prompt 定义角色：知识科普编剧
2. 输入 PDF 全文（超长则摘要前 5000 字）
3. 输出 NARRATION_DATA JSON 数组：`{timestamp, text_cn, text_en}`
4. 约束：总时长接近 target_duration，双语字幕，口语化表达

### 3.3 Animation Engine (`animation_engine.py`)

**职责**：生成动画 HTML

```python
class AnimationEngine:
    async def generate_html(
        self, script: PodcastScript, target_duration: int = 60
    ) -> str:
        """生成包含 Canvas 动画 + 字幕 + 音频接口的 HTML"""
```

**HTML 规范**：
- 必须包含 `window.NARRATION_DATA`（JSON 数组）
- 必须包含 `window.ANIMATION_DURATION`（数字）
- 必须包含 `window.PODCAST_AUDIO_PATH`（空字符串，后端注入）
- Canvas + requestAnimationFrame 驱动
- 浅色配色，2K 分辨率容器
- 音频存在时用 `audio.currentTime` 驱动动画进度

### 3.4 Podcast TTS (`podcast_tts.py`)

**职责**：调用火山引擎生成双人播客音频

```python
class PodcastTTS:
    async def generate(
        self, text: str, speech_rate: int = 0
    ) -> AudioResult:
        """生成播客音频"""
        # 返回: AudioResult(audio_data: bytes, duration: float, format: "mp3")
```

**协议要点**（已在 Prototype 验证）：

| 步骤 | 事件 | 方向 | 说明 |
|------|------|------|------|
| 1 | StartConnection | C→S | 建立连接 |
| 2 | ConnectionStarted | S→C | 连接确认 |
| 3 | StartSession (action=0) | C→S | 提交文本 |
| 4 | SessionStarted | S→C | 会话确认 |
| 5 | FinishSession | C→S | 触发生成 |
| 6 | PodcastRoundStart | S→C | 每轮对话开始（含 speaker + text） |
| 7 | PodcastRoundResponse | S→C | 音频分片（多次） |
| 8 | PodcastRoundEnd | S→C | 每轮结束（含 audio_duration） |
| 9 | UsageResponse | S→C | Token 用量 |
| 10 | PodcastEnd | S→C | 全部结束（含 meta_info） |
| 11 | SessionFinished | S→C | 会话结束 |
| 12 | FinishConnection | C→S | 断开连接 |

**Speaker 配对**：

| 角色 | Speaker ID |
|------|-----------|
| 男声（大艺先生） | `zh_male_dayixiansheng_v2_saturn_bigtts` |
| 女声（咪仔同学） | `zh_female_mizaitongxue_v2_saturn_bigtts` |

**认证头**：
```
X-Api-App-Id: {APP_ID}
X-Api-Access-Key: {ACCESS_TOKEN}
X-Api-Resource-Id: volc.service_type.10050
X-Api-App-Key: {APP_KEY}
X-Api-Connect-Id: {UUID}
```

**Endpoint**: `wss://openspeech.bytedance.com/api/v3/sami/podcasttts`

### 3.5 Audio Sync (`audio_sync.py`)

**职责**：将音频注入动画 HTML

```python
class AudioSync:
    def inject(
        self, html: str, audio_filename: str, audio_duration: float
    ) -> str:
        """注入音频路径 + 更新动画时长"""
```

**同步策略**（优先级从高到低）：

| 策略 | 方法 | 精度 | 适用场景 |
|------|------|------|----------|
| 1. 音频驱动 | `audio.currentTime` 作为动画 elapsed | 精确 | 首选 |
| 2. 时长对齐 | `ANIMATION_DURATION = audio.duration` | ±0.1s | 动画自适应 |
| 3. 语速调整 | `speech_rate` 调整 TTS 速度 | ±5% | 音频适配动画 |
| 4. 文本裁剪 | 增减旁白条目 | 粗略 | 大幅偏差时 |

### 3.6 Video Renderer (`video_renderer.py`)

**职责**：Puppeteer 录制动画 HTML 为视频

```python
class VideoRenderer:
    async def record(
        self, html_path: str, duration: float,
        width: int = 1920, height: int = 1080, fps: int = 30
    ) -> str:
        """录制 HTML 动画为 WebM"""
        # 返回: webm_path
```

**技术方案**：
- Node.js Puppeteer 库（通过 `subprocess` 调用）
- Headless Chrome，设置 viewport = 1920x1080
- 使用 `MediaRecorder` API 录制 Canvas + 页面
- 录制时长 = `audio_duration + 2s`（缓冲）
- 输出 WebM（VP8/VP9）

**Puppeteer 录屏脚本核心逻辑**：
```javascript
// 注入到页面的录屏逻辑
const stream = canvas.captureStream(fps);
const recorder = new MediaRecorder(stream, { mimeType: 'video/webm' });
const chunks = [];
recorder.ondataavailable = e => chunks.push(e.data);
recorder.onstop = () => {
    const blob = new Blob(chunks, { type: 'video/webm' });
    // 通过 CDP / fetch 回传给 Node 端
};
recorder.start();
setTimeout(() => recorder.stop(), duration * 1000);
```

### 3.7 Video Composer (`video_composer.py`)

**职责**：FFmpeg 合成最终 MP4

```python
class VideoComposer:
    async def compose(
        self, video_path: str, audio_path: str, output_path: str
    ) -> str:
        """合并视频 + 音频为 MP4"""
```

**FFmpeg 命令**：
```bash
ffmpeg -i video.webm -i audio.mp3 \
    -c:v libx264 -preset fast -crf 20 \
    -c:a aac -b:a 128k \
    -shortest -movflags +faststart \
    output.mp4
```

### 3.8 Pipeline Orchestrator (`pipeline.py`)

**职责**：编排所有步骤，管理状态和进度

```python
class Pipeline:
    async def run(self, job_id: str, pdf_path: str, options: JobOptions):
        """执行完整 Pipeline"""
        # 每个步骤更新 job 状态 + 推送 WebSocket 进度
        
        # Step 1: PDF 解析
        await self._update_progress(job_id, "parsing", 5)
        pdf_content = self.pdf_parser.extract_text(pdf_path)
        
        # Step 2: 脚本生成
        await self._update_progress(job_id, "scripting", 15)
        script = await self.content_gen.generate_script(pdf_content)
        
        # Step 3: 动画生成
        await self._update_progress(job_id, "animating", 30)
        html = await self.anim_engine.generate_html(script)
        
        # Step 4: 音频生成
        await self._update_progress(job_id, "tts", 50)
        audio = await self.tts.generate(script.to_text())
        
        # Step 5: 音画同步
        await self._update_progress(job_id, "syncing", 72)
        synced_html = self.audio_sync.inject(html, audio)
        
        # Step 6: 视频录制
        await self._update_progress(job_id, "recording", 75)
        webm = await self.renderer.record(synced_html, audio.duration)
        
        # Step 7: 视频合成
        await self._update_progress(job_id, "composing", 92)
        mp4 = await self.composer.compose(webm, audio.path)
        
        # Done
        await self._update_progress(job_id, "done", 100)
```

---

## 4. API 设计

### 4.1 REST API

| 方法 | 路径 | 说明 | 请求 | 响应 |
|------|------|------|------|------|
| POST | `/api/jobs` | 上传 PDF，创建任务 | `multipart/form-data` (file) | `{job_id, status}` |
| GET | `/api/jobs/{id}` | 查询任务状态 | - | `{job_id, status, progress, result?}` |
| GET | `/api/jobs/{id}/video` | 下载视频 | - | `video/mp4` |
| GET | `/api/jobs` | 任务列表 | `?page=1&limit=10` | `{jobs: [...], total}` |
| DELETE | `/api/jobs/{id}` | 删除任务 | - | `{success: true}` |

### 4.2 Job 状态机

```
pending → parsing → scripting → animating → tts → syncing → recording → composing → done
    │         │          │           │        │         │          │           │
    └─────────┴──────────┴───────────┴────────┴─────────┴──────────┴───────────┘
                                    ↓ (任何阶段失败)
                                  failed
```

### 4.3 WebSocket API

```
WS /api/ws/{job_id}

# 服务端 → 客户端
{
    "type": "progress",
    "stage": "tts",
    "progress": 55,
    "message": "已接收 45% 音频数据"
}

{
    "type": "log",
    "level": "info",
    "message": "[WS] Speaker: 大艺先生",
    "timestamp": "2026-06-18T21:15:02Z"
}

{
    "type": "done",
    "video_url": "/api/jobs/abc123/video",
    "duration": 83.5,
    "file_size": 8912896
}

{
    "type": "error",
    "message": "TTS 生成失败：超时",
    "stage": "tts"
}
```

### 4.4 请求/响应模型

```python
# 创建任务响应
class JobCreatedResponse(BaseModel):
    job_id: str
    status: Literal["pending"]
    created_at: datetime

# 任务状态响应
class JobStatusResponse(BaseModel):
    job_id: str
    status: Literal["pending", "parsing", "scripting", "animating", 
                     "tts", "syncing", "recording", "composing", 
                     "done", "failed"]
    progress: int  # 0-100
    stage: str
    message: Optional[str]
    result: Optional[JobResult]
    error: Optional[str]
    created_at: datetime
    updated_at: datetime

class JobResult(BaseModel):
    video_url: str
    duration: float
    file_size: int
    title: str
    resolution: str  # "1920x1080"
```

---

## 5. 数据模型

### 5.1 SQLite Schema

```sql
CREATE TABLE jobs (
    id          TEXT PRIMARY KEY,          -- UUID
    status      TEXT NOT NULL DEFAULT 'pending',
    stage       TEXT DEFAULT '',
    progress    INTEGER DEFAULT 0,
    message     TEXT DEFAULT '',
    
    -- 输入
    pdf_filename    TEXT,
    pdf_path        TEXT,
    
    -- 输出
    video_path      TEXT,
    video_duration  REAL,
    video_size      INTEGER,
    video_title     TEXT,
    
    -- 选项
    target_duration INTEGER DEFAULT 60,
    speech_rate     INTEGER DEFAULT 0,
    resolution      TEXT DEFAULT '1920x1080',
    
    -- 元数据
    error           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    completed_at    TEXT
);

CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_jobs_created ON jobs(created_at DESC);
```

---

## 6. 配置管理

### 6.1 环境变量 (`.env`)

```bash
# ── DeepSeek (LLM) ──
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat

# ── 火山引擎 (TTS) ──
VOLC_APP_ID=7952479922
VOLC_ACCESS_TOKEN=xxx
VOLC_APP_KEY=aGjiRDfUWi
VOLC_RESOURCE_ID=volc.service_type.10050

# ── 应用配置 ──
APP_HOST=0.0.0.0
APP_PORT=8000
MAX_PDF_SIZE_MB=50
MAX_PDF_PAGES=100
MAX_VIDEO_DURATION=300
MAX_CONCURRENT_JOBS=5

# ── 路径 ──
UPLOAD_DIR=./uploads
OUTPUT_DIR=./output
DATA_DIR=./data

# ── Puppeteer ──
CHROME_PATH=          # 留空则自动查找
PUPPETEER_TIMEOUT=120000
```

### 6.2 配置加载 (`config.py`)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    deepseek_api_key: str
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"
    
    volc_app_id: str
    volc_access_token: str
    volc_app_key: str = "aGjiRDfUWi"
    volc_resource_id: str = "volc.service_type.10050"
    
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    max_pdf_size_mb: int = 50
    max_pdf_pages: int = 100
    max_video_duration: int = 300
    max_concurrent_jobs: int = 5
    
    upload_dir: str = "./uploads"
    output_dir: str = "./output"
    data_dir: str = "./data"
    
    class Config:
        env_file = ".env"
```

---

## 7. 前端设计

### 7.1 技术选择

- **Vanilla JS** — 无框架依赖，无构建步骤，单文件部署
- **WebSocket** — 原生 API，实时进度
- **CSS Grid/Flexbox** — 响应式布局

### 7.2 前端状态管理

```javascript
const App = {
    state: {
        currentJob: null,
        ws: null,
        view: 'upload',  // upload | processing | result | history
    },
    
    // 页面路由（hash-based SPA）
    routes: {
        '#/': showUpload,
        '#/job/:id': showProcessing,
        '#/job/:id/result': showResult,
        '#/history': showHistory,
    }
};
```

### 7.3 核心交互

1. **拖拽上传**：dragover/drop 事件，支持点击选择
2. **实时进度**：WebSocket 连接，接收 progress/log/done/error 消息
3. **视频预览**：HTML5 `<video>` 标签，支持下载

---

## 8. 部署方案

### 8.1 开发环境

```bash
# 1. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 安装 Puppeteer Chrome
npm install puppeteer  # 或 npx puppeteer browsers install chrome

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API 密钥

# 5. 启动
python run.py
# 访问 http://localhost:8000
```

### 8.2 依赖清单 (`requirements.txt`)

```
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
python-multipart>=0.0.9
pydantic>=2.0
pydantic-settings>=2.0
PyMuPDF>=1.24.0
openai>=1.0
websockets>=12.0
aiosqlite>=0.20.0
python-dotenv>=1.0
```

### 8.3 系统依赖

| 依赖 | 用途 | 安装方式 |
|------|------|----------|
| Chrome/Chromium | Puppeteer 录屏 | `npx puppeteer browsers install chrome` |
| FFmpeg | 视频合成 | 系统包管理器 / 官网下载 |
| Node.js 18+ | Puppeteer 运行时 | nvm / 官网下载 |

---

## 9. 错误处理与重试

### 9.1 错误分类

| 类型 | 场景 | 处理 |
|------|------|------|
| **用户错误** | PDF 过大/格式错误/页数超限 | 立即返回 400，提示用户 |
| **LLM 错误** | DeepSeek API 超时/限流 | 重试 3 次，指数退避 |
| **TTS 错误** | 火山引擎 WS 断连/超时 | 重试 2 次，记录错误日志 |
| **录屏错误** | Chrome 崩溃/OOM | 重试 1 次，降级为静态截图 |
| **合成错误** | FFmpeg 编码失败 | 重试 1 次，检查输入文件 |

### 9.2 超时策略

| 阶段 | 超时 | 动作 |
|------|------|------|
| PDF 解析 | 30s | 超时返回错误 |
| LLM 脚本 | 60s | 重试 |
| LLM 动画 | 90s | 重试 |
| TTS 音频 | 180s | 重试 |
| Puppeteer 录屏 | duration + 30s | 杀进程重试 |
| FFmpeg 合成 | 60s | 重试 |

---

## 10. 安全考量

| 风险 | 措施 |
|------|------|
| API 密钥泄露 | 环境变量管理，不硬编码，不进 Git |
| 恶意 PDF | 文件类型校验 + 大小限制 + PyMuPDF 安全解析 |
| 路径穿越 | UUID 命名所有文件，禁止用户输入路径 |
| XSS | 前端不直接渲染 LLM 输出的 HTML（Puppeteer 隔离执行） |
| 资源耗尽 | 并发任务限制 + 任务超时 + 临时文件定期清理 |
| 数据留存 | PDF 处理完即删；视频保留 24h 后自动清理 |

---

## 11. 性能预估

| 场景 | 耗时 | 瓶颈 |
|------|------|------|
| 10 页 PDF → 60s 视频 | ~2 min | TTS 音频生成 |
| 50 页 PDF → 120s 视频 | ~3.5 min | LLM 动画生成 + TTS |
| 100 页 PDF → 180s 视频 | ~5 min | 全链路 |

**优化方向**：
1. LLM 请求流式输出（提前开始下一步）
2. TTS 音频分片接收时并行启动 Puppeteer 准备
3. PDF 预处理阶段并行提取图片（未来支持图文动画）
