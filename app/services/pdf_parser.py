"""
PDF 文本提取服务
"""
import fitz  # PyMuPDF
from dataclasses import dataclass, field
from typing import List
from app.utils.logger import logger


@dataclass
class PDFContent:
    title: str
    pages: List[str]
    total_text: str
    page_count: int


class PDFParser:
    def extract_text(self, pdf_path: str, max_pages: int = 100) -> PDFContent:
        try:
            doc = fitz.open(pdf_path)
        except Exception as e:
            raise ValueError(f"无法打开 PDF: {e}")

        page_count = min(len(doc), max_pages)
        pages = []
        for i in range(page_count):
            page = doc[i]
            text = page.get_text("text").strip()
            if text:
                pages.append(text)

        # 标题：优先元数据，其次第一页前 50 字
        meta = doc.metadata or {}
        title = (meta.get("title") or "").strip()
        if not title and pages:
            first_line = pages[0].split("\n")[0].strip()
            title = first_line[:80] if first_line else "未知文档"

        doc.close()

        total_text = "\n\n".join(pages)
        logger.info(f"PDF 解析完成：{page_count} 页，{len(total_text)} 字符，标题={title!r}")
        return PDFContent(
            title=title,
            pages=pages,
            total_text=total_text,
            page_count=page_count,
        )
