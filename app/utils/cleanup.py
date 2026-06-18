"""
临时文件清理工具
"""
import os
import glob
import time
from app.utils.logger import logger


def cleanup_old_files(directory: str, max_age_hours: int = 24):
    """清理超过指定时间的文件"""
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for f in glob.glob(os.path.join(directory, "**", "*"), recursive=True):
        if os.path.isfile(f) and os.path.getmtime(f) < cutoff:
            try:
                os.remove(f)
                removed += 1
            except OSError as e:
                logger.warning(f"无法删除文件 {f}: {e}")
    if removed:
        logger.info(f"清理 {directory}: 删除 {removed} 个过期文件")


def safe_delete(path: str):
    """安全删除单个文件"""
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass
