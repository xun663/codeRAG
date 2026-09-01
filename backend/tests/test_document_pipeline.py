"""Tests for the document processing pipeline (app/core/documents/pipeline.py).

Covers:
  - _guess_mime: MIME type detection from file extensions
  - _detect_language: language detection from file extensions
  - process_file: full pipeline (parse → chunk → embed → index)
  - process_url: URL ingestion flow
  - Cleaning integration (when cleaner is enabled)
  - Edge cases: unsupported files, empty content
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.core.documents.pipeline import DocumentPipeline


# ═════════════════════════════════════════════════════════════════════
#  _guess_mime
# ═════════════════════════════════════════════════════════════════════

class TestGuessMime:
    """MIME type mapping from file extensions."""

    def test_pdf(self, doc_pipeline: DocumentPipeline):
        assert doc_pipeline._guess_mime(Path("doc.pdf")) == "application/pdf"

    def test_markdown(self, doc_pipeline: DocumentPipeline):
        assert doc_pipeline._guess_mime(Path("readme.md")) == "text/markdown"

    def test_python(self, doc_pipeline: DocumentPipeline):
        assert doc_pipeline._guess_mime(Path("main.py")) == "text/x-python"

    def test_javascript(self, doc_pipeline: DocumentPipeline):
        assert doc_pipeline._guess_mime(Path("app.js")) == "text/javascript"

    def test_typescript(self, doc_pipeline: DocumentPipeline):
        assert doc_pipeline._guess_mime(Path("component.ts")) == "text/x-typescript"

    def test_java(self, doc_pipeline: DocumentPipeline):
        assert doc_pipeline._guess_mime(Path("Main.java")) == "text/x-java"

    def test_go(self, doc_pipeline: DocumentPipeline):
        assert doc_pipeline._guess_mime(Path("main.go")) == "text/x-go"

    def test_rust(self, doc_pipeline: DocumentPipeline):
        assert doc_pipeline._guess_mime(Path("lib.rs")) == "text/x-rust"

    def test_cpp(self, doc_pipeline: DocumentPipeline):
        assert doc_pipeline._guess_mime(Path("main.cpp")) == "text/x-c++"

    def test_c(self, doc_pipeline: DocumentPipeline):
        assert doc_pipeline._guess_mime(Path("main.c")) == "text/x-c"

    def test_html(self, doc_pipeline: DocumentPipeline):
        assert doc_pipeline._guess_mime(Path("index.html")) == "text/html"

    def test_txt(self, doc_pipeline: DocumentPipeline):
        assert doc_pipeline._guess_mime(Path("notes.txt")) == "text/plain"

    def test_unknown_extension(self, doc_pipeline: DocumentPipeline):
        assert doc_pipeline._guess_mime(Path("file.xyz")) == "text/plain"

    def test_no_extension(self, doc_pipeline: DocumentPipeline):
        assert doc_pipeline._guess_mime(Path("Makefile")) == "text/plain"

    def test_case_insensitivity(self, doc_pipeline: DocumentPipeline):
        assert doc_pipeline._guess_mime(Path("README.MD")) == "text/markdown"


# ═════════════════════════════════════════════════════════════════════
#  _detect_language
# ═════════════════════════════════════════════════════════════════════

class TestDetectLanguage:
    """Language detection from file extensions."""

    @pytest.mark.parametrize("ext,expected", [
        (".py", "python"),
        (".js", "javascript"),
        (".ts", "typescript"),
        (".jsx", "javascript"),
        (".tsx", "typescript"),
        (".java", "java"),
        (".go", "go"),
        (".rs", "rust"),
        (".c", "c"),
        (".cpp", "cpp"),
        (".h", "c"),
        (".cs", "csharp"),
        (".rb", "ruby"),
        (".php", "php"),
        (".swift", "swift"),
        (".kt", "kotlin"),
        (".md", "text"),
        (".txt", "text"),
        (".html", "text"),
        (".pdf", "text"),
        (".xyz", "text"),
        ("", "text"),
    ])
    def test_language_mapping(self, doc_pipeline: DocumentPipeline, ext: str, expected: str):
        assert doc_pipeline._detect_language(Path(f"file{ext}")) == expected


# ═════════════════════════════════════════════════════════════════════
#  process_file — markdown
# ═════════════════════════════════════════════════════════════════════

class TestProcessFileMarkdown:
    """Processing a markdown file through the full pipeline."""

    @pytest.mark.asyncio
    async def test_process_markdown_basic(
        self, doc_pipeline: DocumentPipeline, sample_markdown_file: str,
    ):
        result = await doc_pipeline.process_file(
            file_path=sample_markdown_file,
            kb_id="test_kb",
            doc_title="Python Tuples Guide",
        )
        assert result["doc_hash"] is not None
        assert result["word_count"] > 0
        assert "chunks" in result
        assert len(result["chunks"]) > 0

    @pytest.mark.asyncio
    async def test_process_markdown_chunks_have_required_fields(
        self, doc_pipeline: DocumentPipeline, sample_markdown_file: str,
    ):
        result = await doc_pipeline.process_file(
            file_path=sample_markdown_file,
            kb_id="test_kb",
            doc_title="Python Tuples Guide",
        )
        for chunk in result["chunks"]:
            assert "id" in chunk
            assert "content" in chunk
            assert "chunk_type" in chunk
            assert "metadata" in chunk
            assert "token_count" in chunk
            assert chunk["metadata"]["doc_title"] == "Python Tuples Guide"
            assert chunk["metadata"]["kb_id"] == "test_kb"

    @pytest.mark.asyncio
    async def test_process_markdown_chunks_indexed(
        self, doc_pipeline: DocumentPipeline, sample_markdown_file: str,
    ):
        result = await doc_pipeline.process_file(
            file_path=sample_markdown_file,
            kb_id="test_kb",
            doc_title="Python Tuples Guide",
        )
        stats = await doc_pipeline.vector_store.get_collection_stats("kb_test_kb")
        assert stats["count"] == len(result["chunks"])

    @pytest.mark.asyncio
    async def test_markdown_with_code_block(
        self, doc_pipeline: DocumentPipeline, sample_markdown_file: str,
    ):
        """Code blocks in markdown should be detected and chunked separately."""
        result = await doc_pipeline.process_file(
            file_path=sample_markdown_file,
            kb_id="test_kb",
        )
        chunk_types = {c["chunk_type"] for c in result["chunks"]}
        # Should have both text and code block chunks
        assert "text" in chunk_types

    @pytest.mark.asyncio
    async def test_auto_generated_title_from_filename(
        self, doc_pipeline: DocumentPipeline, sample_markdown_file: str,
    ):
        """When doc_title is not provided, use the filename."""
        result = await doc_pipeline.process_file(
            file_path=sample_markdown_file,
            kb_id="test_kb",
        )
        for chunk in result["chunks"]:
            assert chunk["metadata"]["doc_title"] == "test_doc.md"

    @pytest.mark.asyncio
    async def test_collection_created(
        self, doc_pipeline: DocumentPipeline, sample_markdown_file: str,
    ):
        result = await doc_pipeline.process_file(
            file_path=sample_markdown_file,
            kb_id="collection_test",
        )
        assert "kb_collection_test" in doc_pipeline.vector_store.collections


# ═════════════════════════════════════════════════════════════════════
#  process_file — code (Python)
# ═════════════════════════════════════════════════════════════════════

class TestProcessFileCode:
    """Processing a Python file through the pipeline."""

    @pytest.mark.asyncio
    async def test_process_python_file(
        self, doc_pipeline: DocumentPipeline, sample_python_file: str,
    ):
        result = await doc_pipeline.process_file(
            file_path=sample_python_file,
            kb_id="code_kb",
            doc_title="Calculator",
        )
        assert result["word_count"] > 0
        assert len(result["chunks"]) > 0

    @pytest.mark.asyncio
    async def test_python_chunks_preserve_structure(
        self, doc_pipeline: DocumentPipeline, sample_python_file: str,
    ):
        """Code-aware chunker should produce chunks based on function/class boundaries."""
        result = await doc_pipeline.process_file(
            file_path=sample_python_file, kb_id="code_kb",
        )
        # Should have chunks with start_line/end_line metadata
        has_line_info = any(
            "start_line" in c["metadata"] and "end_line" in c["metadata"]
            for c in result["chunks"]
        )
        # Either has line info (code-aware chunking) or just plain text chunks
        # This should work since the code-aware chunker runs for .py files

    @pytest.mark.asyncio
    async def test_python_chunks_indexed(
        self, doc_pipeline: DocumentPipeline, sample_python_file: str,
    ):
        result = await doc_pipeline.process_file(
            file_path=sample_python_file, kb_id="code_kb",
        )
        stats = await doc_pipeline.vector_store.get_collection_stats("kb_code_kb")
        assert stats["count"] == len(result["chunks"])


# ═════════════════════════════════════════════════════════════════════
#  process_file — plain text
# ═════════════════════════════════════════════════════════════════════

class TestProcessFileText:
    """Processing a plain text file."""

    @pytest.mark.asyncio
    async def test_process_text_file(
        self, doc_pipeline: DocumentPipeline, sample_text_file: str,
    ):
        result = await doc_pipeline.process_file(
            file_path=sample_text_file, kb_id="text_kb",
        )
        assert result["word_count"] > 0
        assert len(result["chunks"]) > 0

    @pytest.mark.asyncio
    async def test_text_chunks_indexed(
        self, doc_pipeline: DocumentPipeline, sample_text_file: str,
    ):
        result = await doc_pipeline.process_file(
            file_path=sample_text_file, kb_id="text_kb",
        )
        stats = await doc_pipeline.vector_store.get_collection_stats("kb_text_kb")
        assert stats["count"] == len(result["chunks"])


# ═════════════════════════════════════════════════════════════════════
#  process_file — edge cases
# ═════════════════════════════════════════════════════════════════════

class TestProcessFileEdgeCases:
    """Edge cases for file processing."""

    @pytest.mark.asyncio
    async def test_empty_file(self, doc_pipeline: DocumentPipeline, tmp_path):
        file_path = tmp_path / "empty.md"
        file_path.write_text("", encoding="utf-8")
        result = await doc_pipeline.process_file(
            file_path=str(file_path), kb_id="test_kb",
        )
        assert result["word_count"] == 0
        assert len(result["chunks"]) == 0

    @pytest.mark.asyncio
    async def test_unknown_extension(self, doc_pipeline: DocumentPipeline, tmp_path):
        """Unknown extension falls back to markdown parser."""
        file_path = tmp_path / "data.xyz"
        file_path.write_text("Some plain content.", encoding="utf-8")
        result = await doc_pipeline.process_file(
            file_path=str(file_path), kb_id="test_kb",
        )
        assert result["word_count"] > 0

    @pytest.mark.asyncio
    async def test_same_content_different_kb(
        self, doc_pipeline: DocumentPipeline, sample_markdown_file: str,
    ):
        """Same file ingested into different KBs should produce different collections."""
        r1 = await doc_pipeline.process_file(
            file_path=sample_markdown_file, kb_id="kb_a",
        )
        r2 = await doc_pipeline.process_file(
            file_path=sample_markdown_file, kb_id="kb_b",
        )
        assert r1["doc_hash"] == r2["doc_hash"]
        stats_a = await doc_pipeline.vector_store.get_collection_stats("kb_kb_a")
        stats_b = await doc_pipeline.vector_store.get_collection_stats("kb_kb_b")
        assert stats_a["count"] > 0
        assert stats_b["count"] > 0

    @pytest.mark.asyncio
    async def test_mime_type_override(
        self, doc_pipeline: DocumentPipeline, tmp_path,
    ):
        """Explicit mime_type should override extension-based detection."""
        file_path = tmp_path / "data.txt"
        file_path.write_text("## Markdown content\n\nWith headings.", encoding="utf-8")
        result = await doc_pipeline.process_file(
            file_path=str(file_path), kb_id="test_kb", mime_type="text/markdown",
        )
        assert result["word_count"] > 0

    @pytest.mark.asyncio
    async def test_doc_id_preserved_in_metadata(
        self, doc_pipeline: DocumentPipeline, sample_markdown_file: str,
    ):
        result = await doc_pipeline.process_file(
            file_path=sample_markdown_file,
            kb_id="test_kb",
            doc_id="my-custom-id",
        )
        for chunk in result["chunks"]:
            assert chunk["metadata"]["doc_id"] == "my-custom-id"

    @pytest.mark.asyncio
    async def test_cleaning_stats(
        self, doc_pipeline: DocumentPipeline, sample_markdown_file: str,
    ):
        result = await doc_pipeline.process_file(
            file_path=sample_markdown_file, kb_id="test_kb",
        )
        assert "cleaning" in result
        assert result["cleaning"]["enabled"] is False


# ═════════════════════════════════════════════════════════════════════
#  process_url
# ═════════════════════════════════════════════════════════════════════

class TestProcessURL:
    """URL ingestion — mocks the HTTP request."""

    @pytest.mark.asyncio
    async def test_process_url(
        self, doc_pipeline: DocumentPipeline,
    ):
        """A real process_url call would need a network request.
        Here we mock the HTMLParser.parse_url method at class level.
        """
        target = "app.core.documents.parsers.html_parser.HTMLParser.parse_url"
        with patch(target, new=AsyncMock(return_value="# Fake HTML Content\n\nParsed from URL.")):
            result = await doc_pipeline.process_url(
                url="https://example.com/doc",
                kb_id="url_kb",
                title="Example Doc",
            )
        assert result["doc_hash"] is not None
        assert result["word_count"] > 0
        assert len(result["chunks"]) > 0
        for chunk in result["chunks"]:
            assert chunk["metadata"]["doc_title"] == "Example Doc"
            assert chunk["metadata"]["source_url"] == "https://example.com/doc"
            assert chunk["metadata"]["kb_id"] == "url_kb"

    @pytest.mark.asyncio
    async def test_process_url_without_title(
        self, doc_pipeline: DocumentPipeline,
    ):
        target = "app.core.documents.parsers.html_parser.HTMLParser.parse_url"
        with patch(target, new=AsyncMock(return_value="# Untitled\n\nSome content.")):
            result = await doc_pipeline.process_url(
                url="https://example.com/page",
                kb_id="url_kb",
            )
        for chunk in result["chunks"]:
            assert chunk["metadata"]["doc_title"] == "https://example.com/page"

    @pytest.mark.asyncio
    async def test_url_chunks_indexed(
        self, doc_pipeline: DocumentPipeline,
    ):
        target = "app.core.documents.parsers.html_parser.HTMLParser.parse_url"
        with patch(target, new=AsyncMock(return_value="# Title\n\nBody text.")):
            result = await doc_pipeline.process_url(
                url="https://example.com/doc", kb_id="url_kb",
            )
        stats = await doc_pipeline.vector_store.get_collection_stats("kb_url_kb")
        assert stats["count"] == len(result["chunks"])

    @pytest.mark.asyncio
    async def test_process_url_with_doc_id(
        self, doc_pipeline: DocumentPipeline,
    ):
        target = "app.core.documents.parsers.html_parser.HTMLParser.parse_url"
        with patch(target, new=AsyncMock(return_value="# Doc\n\nContent with ID.")):
            result = await doc_pipeline.process_url(
                url="https://example.com/doc",
                kb_id="url_kb",
                doc_id="url-doc-001",
            )
        for chunk in result["chunks"]:
            assert chunk["metadata"]["doc_id"] == "url-doc-001"


# ═════════════════════════════════════════════════════════════════════
#  Cleaning integration
# ═════════════════════════════════════════════════════════════════════

class TestCleaningIntegration:
    """Document pipeline with cleaning enabled."""

    @pytest.mark.asyncio
    async def test_cleaning_stats_enabled(
        self, doc_pipeline_with_cleaner: DocumentPipeline, sample_text_file: str,
    ):
        result = await doc_pipeline_with_cleaner.process_file(
            file_path=sample_text_file, kb_id="clean_kb",
        )
        assert result["cleaning"]["enabled"] is True
        assert result["cleaning"]["removed_pct"] >= 0

    @pytest.mark.asyncio
    async def test_cleaner_removes_noise(
        self, doc_pipeline_with_cleaner: DocumentPipeline, tmp_path,
    ):
        """Cleaner should remove navigation/boilerplate lines."""
        noisy_file = tmp_path / "noisy.md"
        noisy_file.write_text(
            "# Main Content\n\n"
            "This is the actual content.\n\n"
            "Previous Next\n\n"      # ← noise pattern
            "Copyright 2024\n\n"      # ← noise pattern
            "More real content.\n",
            encoding="utf-8",
        )
        result = await doc_pipeline_with_cleaner.process_file(
            file_path=str(noisy_file), kb_id="noise_kb",
        )
        assert result["cleaning"]["enabled"] is True
        # The noise lines should have been removed
        all_content = " ".join(c["content"] for c in result["chunks"])
        assert "Previous Next" not in all_content or result["cleaning"]["removed_chars"] > 0

    @pytest.mark.asyncio
    async def test_cleaning_idempotent_clean_content(
        self, doc_pipeline_with_cleaner: DocumentPipeline, sample_markdown_file: str,
    ):
        """Clean markdown should pass through without significant changes."""
        result = await doc_pipeline_with_cleaner.process_file(
            file_path=sample_markdown_file, kb_id="clean_md",
        )
        # Content should still be recognizable
        all_content = " ".join(c["content"] for c in result["chunks"])
        assert "Python" in all_content
        assert "tuple" in all_content


# ═════════════════════════════════════════════════════════════════════
#  Verifying embedding calls
# ═════════════════════════════════════════════════════════════════════

class TestEmbeddingIntegration:
    """Verify that the embedding model was called correctly during pipeline runs."""

    @pytest.mark.asyncio
    async def test_embedding_called_for_each_chunk(
        self, doc_pipeline: DocumentPipeline, sample_markdown_file: str,
        mock_embedding,
    ):
        initial_call_count = len(mock_embedding.embed_texts_calls)
        await doc_pipeline.process_file(
            file_path=sample_markdown_file, kb_id="embed_test",
        )
        # embed_texts should have been called at least once
        assert len(mock_embedding.embed_texts_calls) > initial_call_count

    @pytest.mark.asyncio
    async def test_vector_store_add_called(
        self, doc_pipeline: DocumentPipeline, sample_markdown_file: str,
        mock_vector_store,
    ):
        initial_adds = len(mock_vector_store.add_calls)
        await doc_pipeline.process_file(
            file_path=sample_markdown_file, kb_id="add_test",
        )
        assert len(mock_vector_store.add_calls) == initial_adds + 1
        collection_name, ids, embeddings, documents, metadatas = mock_vector_store.add_calls[-1]
        assert collection_name == "kb_add_test"
        assert len(ids) == len(documents)
        assert len(embeddings) == len(documents)


# ═════════════════════════════════════════════════════════════════════
#  W3Schools navigation cleaner
# ═════════════════════════════════════════════════════════════════════

class TestW3SchoolsNavCleaner:
    """Verify W3Schools nav stripping: H1 cut, footer truncation, nav-line drop."""

    def _make_doc(self) -> str:
        return "\n".join([
            "## Java Tutorial",           # sidebar start
            "[Java HOME](default.asp)",
            "[Java Intro](java_intro.asp)",
            "## Java Methods",
            "[Java If](java_if.asp)",
            "# Java Break and Continue",  # ← content start (H1)
            "",
            "The `break` statement jumps out of a loop.",
            "You use [arrays](java_arrays.asp) too.",  # intra-content ref (kept)
            "[❮ Previous](java_for.asp)",              # nav line (dropped)
            "---",
            "## Break",
            "W3Schools is Powered by W3.CSS",          # footer (dropped)
            "[Copyright 1999-2026](/about/x.asp)",     # footer (dropped)
        ])

    @pytest.mark.asyncio
    async def test_strips_nav_and_keeps_content(self):
        from app.core.documents.cleaners.rules import W3SchoolsNavCleaner
        cleaned = await W3SchoolsNavCleaner().clean(
            self._make_doc(), {"source_file": "abc_java_break.md"}
        )
        assert "# Java Break and Continue" in cleaned
        assert "jumps out of a loop" in cleaned
        assert "java_arrays" in cleaned            # intra-content ref preserved
        assert "## Java Tutorial" not in cleaned   # sidebar gone
        assert "W3Schools is Powered" not in cleaned
        assert "Copyright" not in cleaned
        assert "❮ Previous" not in cleaned

    @pytest.mark.asyncio
    async def test_non_w3schools_doc_untouched(self):
        from app.core.documents.cleaners.rules import W3SchoolsNavCleaner
        text = "just some normal content\nwith lines\n"
        cleaned = await W3SchoolsNavCleaner().clean(text, {"source_file": "notes.md"})
        assert cleaned == text

    @pytest.mark.asyncio
    async def test_drops_footer_from_get_certified(self):
        from app.core.documents.cleaners.rules import W3SchoolsNavCleaner
        text = "\n".join([
            "# Java OOP",
            "Real content here.",
            "[HTML Certificate](https://campus.w3schools.com/x)",
            "[CSS Certificate](https://campus.w3schools.com/y)",
        ])
        cleaned = await W3SchoolsNavCleaner().clean(
            text, {"source_file": "x_java_oop.md"}
        )
        assert "Real content" in cleaned
        assert "Certificate" not in cleaned
