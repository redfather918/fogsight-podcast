"""
Pydantic 请求/响应模型
"""
from typing import Optional, Literal, List
from datetime import datetime
from pydantic import BaseModel


JobStatus = Literal[
    "pending", "parsing", "scripting", "animating",
    "tts", "syncing", "recording", "composing", "done", "failed"
]


class JobResult(BaseModel):
    video_url: str
    duration: float
    file_size: int
    title: str
    resolution: str = "1920x1080"


class JobCreatedResponse(BaseModel):
    job_id: str
    status: Literal["pending"] = "pending"
    created_at: datetime


class JobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: int
    stage: str
    message: Optional[str] = None
    result: Optional[JobResult] = None
    error: Optional[str] = None
    pdf_filename: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class JobListItem(BaseModel):
    job_id: str
    status: JobStatus
    progress: int
    pdf_filename: Optional[str] = None
    title: Optional[str] = None
    created_at: datetime


class JobListResponse(BaseModel):
    jobs: List[JobListItem]
    total: int


# WebSocket 消息结构（用于类型提示）
class WsProgress(BaseModel):
    type: Literal["progress"] = "progress"
    stage: str
    progress: int
    message: str


class WsLog(BaseModel):
    type: Literal["log"] = "log"
    level: Literal["info", "warn", "error"] = "info"
    message: str
    timestamp: str


class WsDone(BaseModel):
    type: Literal["done"] = "done"
    video_url: str
    duration: float
    file_size: int


class WsError(BaseModel):
    type: Literal["error"] = "error"
    message: str
    stage: str
