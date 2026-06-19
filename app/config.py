"""
应用配置，通过环境变量加载（pydantic-settings）
"""
import os
from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    # ── DeepSeek ──
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

    # ── 火山引擎 TTS ──
    volc_app_id: str = "7952479922"
    volc_access_token: str = ""
    volc_app_key: str = "aGjiRDfUWi"
    volc_resource_id: str = "volc.service_type.10050"

    # ── 应用配置 ──
    app_host: str = "0.0.0.0"
    app_port: int = 8012
    max_pdf_size_mb: int = 50
    max_pdf_pages: int = 100
    max_video_duration: int = 300
    max_concurrent_jobs: int = 5

    # ── 路径 ──
    upload_dir: str = "./uploads"
    output_dir: str = "./output"
    data_dir: str = "./data"

    # ── Puppeteer ──
    chrome_path: str = ""
    puppeteer_timeout: int = 120000

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

    @property
    def max_pdf_size_bytes(self) -> int:
        return self.max_pdf_size_mb * 1024 * 1024


# 单例
settings = Settings()

# 确保目录存在
for d in [settings.upload_dir, settings.output_dir, settings.data_dir]:
    os.makedirs(d, exist_ok=True)
