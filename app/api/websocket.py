"""
WebSocket 进度推送管理
"""
import json
import asyncio
from typing import Dict, List
from fastapi import WebSocket
from app.utils.logger import logger


class ConnectionManager:
    """管理所有活跃的 WebSocket 连接"""

    def __init__(self):
        # job_id -> [WebSocket, ...]
        self.connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, job_id: str, ws: WebSocket):
        await ws.accept()
        if job_id not in self.connections:
            self.connections[job_id] = []
        self.connections[job_id].append(ws)
        logger.info(f"WS 连接：job={job_id}，当前连接数={len(self.connections[job_id])}")

    def disconnect(self, job_id: str, ws: WebSocket):
        if job_id in self.connections:
            self.connections[job_id].discard(ws) if hasattr(self.connections[job_id], 'discard') else None
            try:
                self.connections[job_id].remove(ws)
            except ValueError:
                pass
            if not self.connections[job_id]:
                del self.connections[job_id]

    async def send(self, job_id: str, data: dict):
        """向指定 job 的所有连接推送消息"""
        if job_id not in self.connections:
            return
        dead = []
        for ws in self.connections[job_id]:
            try:
                await ws.send_text(json.dumps(data, ensure_ascii=False))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(job_id, ws)

    def has_connections(self, job_id: str) -> bool:
        return bool(self.connections.get(job_id))


# 全局单例
manager = ConnectionManager()
