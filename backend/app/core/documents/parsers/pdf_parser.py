"""PDF document parser."""
from __future__ import annotations

import asyncio

from app.core.documents.parsers.base import BaseParser


class PDFParser(BaseParser):
    async def parse(self, file_path: str) -> str:
        import pypdf

        def _parse():
            reader = pypdf.PdfReader(file_path)
            text = ""
            for page in reader.pages:
                text += page.extract_text() or ""
            return text

        return await asyncio.to_thread(_parse)

    async def supports(self, mime_type: str) -> bool:
        return mime_type == "application/pdf"
