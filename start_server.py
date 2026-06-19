#!/usr/bin/env python3
"""
干净启动服务器（不依赖 .env 端口配置，直接指定 8001）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from dotenv import load_dotenv
load_dotenv()

import uvicorn

if __name__ == "__main__":
    print("启动 Fogsight Podcast 服务 -> http://localhost:8002")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8002,
        reload=False,   # 不 reload，避免卡死
        log_level="info",
    )
