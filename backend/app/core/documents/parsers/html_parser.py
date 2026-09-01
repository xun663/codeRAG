"""HTML / web page parser — 转换为结构化 Markdown。

将 HTML 文档解析为干净的 Markdown，保留标题层级、列表、代码块、
表格等结构。同时执行噪声清洗（移除导航/页脚/侧边栏/脚本等），
确保提取的内容纯粹自包含，适合 RAG 知识库存储。

用法:
    parser = HTMLParser()
    text = await parser.parse("path/to/file.html")
    text = await parser.parse_url("https://example.com")
"""
from __future__ import annotations

import asyncio

import httpx
from bs4 import BeautifulSoup

from app.core.documents.converters.html_to_md import (
    HTMLNoiseCleaner,
    HTMLToMarkdownConverter,
)
from app.core.documents.parsers.base import BaseParser


class HTMLParser(BaseParser):
    """HTML 文档解析器：清洗噪声 → 转为结构化 Markdown。"""

    def __init__(self) -> None:
        self.cleaner = HTMLNoiseCleaner()
        self.converter = HTMLToMarkdownConverter()

    async def parse_url(self, url: str) -> str:
        """从 URL 获取 HTML 并解析为 Markdown。"""
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()

            def _parse() -> str:
                soup = BeautifulSoup(response.text, "html.parser")
                soup = self.cleaner.clean(soup)
                return self.converter.convert(soup)

            return await asyncio.to_thread(_parse)

    async def parse(self, file_path: str) -> str:
        """从本地文件解析 HTML 为 Markdown。"""
        def _parse() -> str:
            with open(file_path, "r", encoding="utf-8") as f:
                soup = BeautifulSoup(f.read(), "html.parser")
            soup = self.cleaner.clean(soup)
            return self.converter.convert(soup)

        return await asyncio.to_thread(_parse)

    async def supports(self, mime_type: str) -> bool:
        return mime_type in ("text/html", "application/xhtml+xml")
