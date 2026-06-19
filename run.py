#!/usr/bin/env python3
"""
启动入口
Usage: python run.py
"""
import os
import sys

# 把项目根目录加入 PYTHONPATH
sys.path.insert(0, os.path.dirname(__file__))

# 加载 .env
from dotenv import load_dotenv
load_dotenv()

import uvicorn
from app.config import settings

if __name__ == "__main__":
    print(f"启动 Fogsight Podcast 服务")
    print(f"访问地址：http://{settings.app_host}:{settings.app_port}")
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,
        log_level="info",
    )
