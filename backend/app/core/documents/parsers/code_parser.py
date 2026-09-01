"""Code file parser with syntax detection."""
from __future__ import annotations

import asyncio

from pygments.lexers import get_lexer_for_filename, guess_lexer
from pygments.util import ClassNotFound

from app.core.documents.parsers.base import BaseParser


class CodeParser(BaseParser):
    async def parse(self, file_path: str) -> str:
        def _parse():
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            # Try to detect language
            try:
                lexer = get_lexer_for_filename(file_path)
                lang = lexer.name
            except ClassNotFound:
                try:
                    lexer = guess_lexer(content[:1000])
                    lang = lexer.name
                except ClassNotFound:
                    lang = "unknown"

            # Add language metadata header
            return f"# Language: {lang}\n# File: {file_path}\n\n{content}"

        return await asyncio.to_thread(_parse)

    async def supports(self, mime_type: str) -> bool:
        return mime_type in (
            "text/x-python", "text/x-java", "text/x-c",
            "text/x-c++", "text/x-go", "text/x-rust",
            "text/javascript", "text/x-typescript",
            "application/x-httpd-php", "application/json",
            "text/plain",
        )
