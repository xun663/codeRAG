"""Recursive text chunker based on separators."""
from __future__ import annotations

import re

from app.core.documents.chunkers.base import BaseChunker


class RecursiveTextChunker(BaseChunker):
    """Split text recursively by separators, keeping chunks under max_size."""

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = ["\n\n", "\n", ". ", " ", ""]

    async def split(self, text: str, metadata: dict | None = None) -> list[dict]:
        import asyncio
        return await asyncio.to_thread(self._split_sync, text, metadata or {})

    def _split_sync(self, text: str, metadata: dict) -> list[dict]:
        chunks = []
        current = ""
        pos = 0

        paragraphs = text.split("\n\n")

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if self.estimate_tokens(current + para) <= self.chunk_size:
                current = (current + "\n\n" + para).strip()
            else:
                if current:
                    chunks.append({
                        "content": current,
                        "chunk_type": "text",
                        "metadata": {**metadata, "start": pos},
                        "token_count": self.estimate_tokens(current),
                    })
                    # Overlap: take last chunk's end
                    overlap_text = current[-self.chunk_overlap:] if self.chunk_overlap < len(current) else ""
                    current = overlap_text + para
                    pos += 1
                else:
                    # Single paragraph larger than chunk_size → split by sentences
                    sentences = re.split(r'(?<=[.!?])\s+', para)
                    for sentence in sentences:
                        if self.estimate_tokens(current + sentence) <= self.chunk_size:
                            current = (current + " " + sentence).strip()
                        else:
                            if current:
                                chunks.append({
                                    "content": current,
                                    "chunk_type": "text",
                                    "metadata": {**metadata, "start": pos},
                                    "token_count": self.estimate_tokens(current),
                                })
                                pos += 1
                            current = sentence

        if current.strip():
            chunks.append({
                "content": current.strip(),
                "chunk_type": "text",
                "metadata": {**metadata, "start": pos},
                "token_count": self.estimate_tokens(current.strip()),
            })

        return chunks
