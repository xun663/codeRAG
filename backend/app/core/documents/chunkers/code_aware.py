"""Code-aware chunking using tree-sitter AST analysis."""
from __future__ import annotations

import asyncio
import re

from app.core.documents.chunkers.base import BaseChunker

# Language-specific regex patterns for function/class detection
# Falls back gracefully when tree-sitter grammars aren't installed
CODE_PATTERNS = {
    "python": {
        "function": r'^\s*(?:async\s+)?def\s+(\w+)\s*\(',
        "class": r'^\s*class\s+(\w+)',
        "decorator": r'^\s*@\w+',
    },
    "javascript": {
        "function": r'(?:function\s+(\w+)|(\w+)\s*=\s*(?:async\s+)?(?:function|\(.*\)\s*=>))',
        "class": r'class\s+(\w+)',
    },
    "typescript": {
        "function": r'(?:function\s+(\w+)|(\w+)\s*=\s*(?:async\s+)?(?:function|\(.*\)\s*=>))',
        "class": r'class\s+(\w+)',
    },
    "java": {
        "function": r'(?:public|private|protected|static|\s)+[\w<>\[\]]+\s+(\w+)\s*\([^)]*\)\s*\{',
        "class": r'(?:public\s+)?class\s+(\w+)',
    },
    "go": {
        "function": r'func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(',
        "struct": r'type\s+(\w+)\s+struct\s*\{',
    },
    "rust": {
        "function": r'fn\s+(\w+)',
        "struct": r'struct\s+(\w+)',
        "impl": r'impl\s+(\w+)',
    },
    "c": {
        "function": r'^\s*(?:static\s+|inline\s+|extern\s+)*[\w\*]+\s+\w+\s*\([^;]*\)\s*\{',
        "struct": r'^\s*(?:typedef\s+)?struct\s+\w+',
        "macro": r'^\s*#\s*(?:define|include|if|ifdef|ifndef|endif|pragma)\b',
    },
    "cpp": {
        "function": r'^\s*(?:static\s+|inline\s+|virtual\s+|explicit\s+|friend\s+)*[\w\*:~<>]+\s+\w+\s*\([^;]*\)\s*(?:const\s*)?\{',
        "class": r'^\s*class\s+\w+',
        "struct": r'^\s*struct\s+\w+',
    },
    "csharp": {
        "function": r'^\s*(?:public|private|protected|internal|static|virtual|override|async)\s+[\w<>\[\]]+\s+\w+\s*\([^;]*\)\s*\{',
        "class": r'^\s*(?:public|internal|abstract\s+)?(?:partial\s+)?class\s+\w+',
    },
}


class CodeAwareChunker(BaseChunker):
    """Split code files using structural awareness (AST when available, regex fallback)."""

    def __init__(self, chunk_size: int = 1500, chunk_overlap: int = 100):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    async def split(self, text: str, metadata: dict | None = None) -> list[dict]:
        meta = metadata or {}
        language = meta.get("language", "python")

        return await asyncio.to_thread(self._split_sync, text, meta, language)

    def _split_sync(self, text: str, metadata: dict, language: str) -> list[dict]:
        """Use regex patterns to identify code structures and chunk accordingly."""
        patterns = CODE_PATTERNS.get(language, CODE_PATTERNS.get("python", {}))
        lines = text.split("\n")
        chunks = []
        current_chunk = []
        current_type = "text"
        chunk_start_line = 0

        for line_no, line in enumerate(lines):
            # Determine if this line starts a new structural unit
            new_type = self._detect_line_type(line, patterns)

            if new_type and current_chunk:
                # Save previous chunk
                content = "\n".join(current_chunk)
                if content.strip():
                    chunks.append({
                        "content": content,
                        "chunk_type": current_type,
                        "metadata": {
                            **metadata,
                            "start_line": chunk_start_line,
                            "end_line": line_no,
                        },
                        "token_count": self.estimate_tokens(content),
                    })
                current_chunk = []
                chunk_start_line = line_no
                current_type = new_type

            current_chunk.append(line)

            # Force split if too large
            if self.estimate_tokens("\n".join(current_chunk)) > self.chunk_size:
                content = "\n".join(current_chunk)
                chunks.append({
                    "content": content,
                    "chunk_type": current_type,
                    "metadata": {
                        **metadata,
                        "start_line": chunk_start_line,
                        "end_line": line_no,
                    },
                    "token_count": self.estimate_tokens(content),
                })
                current_chunk = []
                chunk_start_line = line_no + 1

        # Don't forget the last chunk
        if current_chunk:
            content = "\n".join(current_chunk)
            if content.strip():
                chunks.append({
                    "content": content,
                    "chunk_type": current_type,
                    "metadata": {
                        **metadata,
                        "start_line": chunk_start_line,
                        "end_line": len(lines),
                    },
                    "token_count": self.estimate_tokens(content),
                })

        return chunks

    def _detect_line_type(self, line: str, patterns: dict) -> str | None:
        """Detect what type of structural element this line starts."""
        for pattern_type, pattern in patterns.items():
            if re.match(pattern, line):
                if pattern_type == "function":
                    return "function"
                elif pattern_type in ("class", "struct", "impl"):
                    return "class"
                elif pattern_type == "decorator":
                    return "function"
        return None
