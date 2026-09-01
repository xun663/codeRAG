"""Hybrid chunker: code-aware for code, recursive text for prose."""
from __future__ import annotations

from app.core.documents.chunkers.base import BaseChunker
from app.core.documents.chunkers.code_aware import CodeAwareChunker
from app.core.documents.chunkers.recursive_text import RecursiveTextChunker


class HybridChunker(BaseChunker):
    """Automatically select chunking strategy based on content type."""

    CODE_EXTENSIONS = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
        ".c", ".cpp", ".h", ".hpp", ".cs", ".rb", ".php", ".swift",
        ".kt", ".scala", ".r", ".m", ".sh", ".bash", ".sql", ".yml",
        ".yaml", ".toml", ".ini", ".cfg",
    }

    def __init__(self):
        self.code_chunker = CodeAwareChunker()
        self.text_chunker = RecursiveTextChunker()

    async def split(self, text: str, metadata: dict | None = None) -> list[dict]:
        meta = metadata or {}
        file_ext = meta.get("file_extension", "").lower()
        mime_type = meta.get("mime_type", "")

        # Determine chunking strategy
        # HTML/HTM 已在解析阶段转为 Markdown，按标题分块；否则教程页会整篇一个大 chunk
        if file_ext in self.CODE_EXTENSIONS or "code" in meta.get("language", ""):
            return await self.code_chunker.split(text, metadata)
        elif "markdown" in mime_type or file_ext in (".md", ".html", ".htm"):
            return await self._split_markdown(text, metadata)
        else:
            return await self.text_chunker.split(text, metadata)

    async def _split_markdown(self, text: str, metadata: dict | None = None) -> list[dict]:
        """Split markdown by headings and code blocks."""
        import asyncio
        meta = metadata or {}

        def _split():
            chunks = []
            current = ""
            current_type = "text"
            in_code_block = False
            code_lang = ""

            for line in text.split("\n"):
                # Detect code block boundaries
                if line.strip().startswith("```"):
                    if not in_code_block:
                        in_code_block = True
                        code_lang = line.strip()[3:].strip()
                        if current.strip():
                            chunks.append({
                                "content": current.strip(),
                                "chunk_type": "text",
                                "metadata": {**meta},
                                "token_count": self.estimate_tokens(current.strip()),
                            })
                            current = ""
                        current = line + "\n"
                        current_type = f"code_block_{code_lang}" if code_lang else "code_block"
                        continue
                    else:
                        in_code_block = False
                        current += line
                        if current.strip():
                            chunks.append({
                                "content": current.strip(),
                                "chunk_type": current_type,
                                "metadata": {**meta, "language": code_lang},
                                "token_count": self.estimate_tokens(current.strip()),
                            })
                            current = ""
                            current_type = "text"
                        continue

                # Heading detection
                if line.startswith("#") and not in_code_block:
                    if current.strip():
                        chunks.append({
                            "content": current.strip(),
                            "chunk_type": current_type,
                            "metadata": {**meta},
                            "token_count": self.estimate_tokens(current.strip()),
                        })
                    current = line + "\n"
                    current_type = "text_heading"
                    continue

                current += line + "\n"

                # Split long sections
                if self.estimate_tokens(current) > 1500:
                    chunks.append({
                        "content": current.strip(),
                        "chunk_type": current_type,
                        "metadata": {**meta},
                        "token_count": self.estimate_tokens(current.strip()),
                    })
                    current = ""

            if current.strip():
                chunks.append({
                    "content": current.strip(),
                    "chunk_type": current_type,
                    "metadata": {**meta},
                    "token_count": self.estimate_tokens(current.strip()),
                })

            # Filter out chunks that are too short to be useful
            # (orphan headings, noise fragments, etc.)
            MIN_CONTENT_CHARS = 30
            chunks = [c for c in chunks if len(c["content"]) >= MIN_CONTENT_CHARS]
            return chunks

        return await asyncio.to_thread(_split)
