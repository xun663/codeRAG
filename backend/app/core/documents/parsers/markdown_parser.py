"""Markdown document parser."""
from __future__ import annotations

import asyncio

from app.core.documents.parsers.base import BaseParser


class MarkdownParser(BaseParser):
    async def parse(self, file_path: str) -> str:
        def _parse():
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        return await asyncio.to_thread(_parse)

    async def supports(self, mime_type: str) -> bool:
        return mime_type in ("text/markdown", "text/x-markdown", "text/plain")
