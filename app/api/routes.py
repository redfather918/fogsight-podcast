"""
REST API 路由
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response

from app.config import settings
from app.models.job import (
    create_job, get_job, list_jobs, delete_job, update_job
)
from app.models.schemas import (
    JobCreatedResponse, JobStatusResponse, JobResult, JobListResponse, JobListItem
)
from app.api.websocket import manager
from app.services.pipeline import Pipeline
from app.utils.logger import logger

router = APIRouter()


# ── 创建任务（上传 PDF）──────────────────────────────────

@router.post("/jobs", response_model=JobCreatedResponse)
async def create_job_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    target_duration: int = Query(60, ge=30, le=300),
    speech_rate: int = Query(0, ge=-50, le=100),
):
    # 校验文件类型
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "只支持 PDF 文件")

    # 校验文件大小
    content = await file.read()
    if len(content) > settings.max_pdf_size_bytes:
        raise HTTPException(400, f"文件大小超限（最大 {settings.max_pdf_size_mb}MB）")

    # 保存上传文件
    os.makedirs(settings.upload_dir, exist_ok=True)
    safe_name = f"{uuid.uuid4()}.pdf"
    pdf_path = os.path.join(settings.upload_dir, safe_name)
    with open(pdf_path, "wb") as f:
        f.write(content)

    # 创建数据库记录
    job_id = await create_job(file.filename, pdf_path)

    # 后台异步执行 Pipeline
    background_tasks.add_task(
        _run_pipeline_bg, job_id, pdf_path, target_duration, speech_rate
    )

    logger.info(f"创建任务：job_id={job_id}，文件={file.filename}，目标时长={target_duration}s")
    return JobCreatedResponse(
        job_id=job_id,
        status="pending",
        created_at=datetime.now(timezone.utc),
    )


async def _run_pipeline_bg(job_id: str, pdf_path: str, target_duration: int, speech_rate: int):
    """后台任务：运行 Pipeline 并推送 WebSocket 进度"""
    async def ws_send(data: dict):
        await manager.send(job_id, data)

    pipeline = Pipeline(ws_send=ws_send)
    try:
        await pipeline.run(job_id, pdf_path, target_duration, speech_rate)
    except Exception as e:
        logger.error(f"Pipeline 后台任务失败：{e}")


# ── 查询任务状态 ──────────────────────────────────────────

@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    job = await get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")

    result = None
    if job["status"] == "done" and job.get("video_path"):
        result = JobResult(
            video_url=f"/api/jobs/{job_id}/animation",
            duration=job.get("video_duration") or 0,
            file_size=job.get("video_size") or 0,
            title=job.get("video_title") or job.get("pdf_filename") or "",
            resolution="1920x1080",
        )

    return JobStatusResponse(
        job_id=job_id,
        status=job["status"],
        progress=job.get("progress", 0),
        stage=job.get("stage", ""),
        message=job.get("message"),
        result=result,
        error=job.get("error"),
        pdf_filename=job.get("pdf_filename"),
        created_at=datetime.fromisoformat(job["created_at"]),
        updated_at=datetime.fromisoformat(job["updated_at"]),
    )


# ── 下载视频 ──────────────────────────────────────────────

@router.get("/jobs/{job_id}/animation")
async def get_animation(job_id: str):
    """返回音画同步的 HTML 动画页面"""
    job = await get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    if job["status"] != "done":
        raise HTTPException(400, "动画尚未生成完成")

    html_path = job.get("video_path")
    if not html_path or not os.path.exists(html_path):
        raise HTTPException(404, "动画文件不存在")

    return FileResponse(html_path, media_type="text/html")


# ── 下载 HTML（作为文件附件）─────────────────────────────

@router.get("/jobs/{job_id}/animation/download")
async def download_animation(job_id: str):
    """将音画同步 HTML 作为附件下载"""
    job = await get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")
    if job["status"] != "done":
        raise HTTPException(400, "动画尚未生成完成")

    html_path = job.get("video_path")
    if not html_path or not os.path.exists(html_path):
        raise HTTPException(404, "动画文件不存在")

    filename = (job.get("video_title") or "podcast-animation").replace(" ", "-")
    return FileResponse(
        html_path,
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}.html"'},
    )


# ── 下载音频（供音画同步使用）────────────────────────────

@router.get("/jobs/{job_id}/audio")
async def get_audio(job_id: str):
    audio_path = os.path.join(settings.output_dir, f"{job_id}_audio.mp3")
    if not os.path.exists(audio_path):
        raise HTTPException(404, "音频文件不存在")
    return FileResponse(audio_path, media_type="audio/mpeg")


# ── 查询任务列表 ──────────────────────────────────────────

@router.get("/jobs", response_model=JobListResponse)
async def list_jobs_endpoint(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
):
    jobs_raw, total = await list_jobs(page, limit)
    jobs = []
    for j in jobs_raw:
        jobs.append(JobListItem(
            job_id=j["id"],
            status=j["status"],
            progress=j.get("progress", 0),
            pdf_filename=j.get("pdf_filename"),
            title=j.get("video_title"),
            created_at=datetime.fromisoformat(j["created_at"]),
        ))
    return JobListResponse(jobs=jobs, total=total)


# ── 删除任务 ──────────────────────────────────────────────

@router.delete("/jobs/{job_id}")
async def delete_job_endpoint(job_id: str):
    job = await get_job(job_id)
    if not job:
        raise HTTPException(404, "任务不存在")

    # 删除视频文件
    if job.get("video_path") and os.path.exists(job["video_path"]):
        try:
            os.remove(job["video_path"])
        except OSError:
            pass

    ok = await delete_job(job_id)
    return {"success": ok}


# ── WebSocket 进度 ────────────────────────────────────────

@router.websocket("/ws/{job_id}")
async def websocket_progress(ws: WebSocket, job_id: str):
    await manager.connect(job_id, ws)
    try:
        # 发送当前状态
        job = await get_job(job_id)
        if job:
            await ws.send_text(
                f'{{"type":"progress","stage":"{job["stage"]}","progress":{job["progress"]},"message":"{job.get("message","")}"}}')

        # 保持连接
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                # 心跳 ping
                await ws.send_text('{"type":"ping"}')
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(job_id, ws)
