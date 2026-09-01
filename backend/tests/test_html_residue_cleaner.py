"""Tests for HTMLResidueCleaner — the strict tag regex must not corrupt code.

Regression: the old blanket pattern ``<[^>]*>`` deleted C code like
``#include <stdio.h>`` and comparisons ``a < b`` from programming
tutorials (found via the C-language user-upload test, 2026-08-16).
"""
from __future__ import annotations

import pytest

from app.core.documents.cleaners.rules import HTMLResidueCleaner


@pytest.fixture
def cleaner() -> HTMLResidueCleaner:
    return HTMLResidueCleaner()


async def run(cleaner: HTMLResidueCleaner, text: str) -> str:
    return await cleaner.clean(text, {"file_type": "text/html"})


@pytest.mark.asyncio
async def test_removes_real_html_tags(cleaner):
    out = await run(cleaner, '<div class="main">hello</div>')
    assert out == "hello"


@pytest.mark.asyncio
async def test_removes_closing_and_self_closing_tags(cleaner):
    assert await run(cleaner, "</div>") == ""
    assert await run(cleaner, "<br/>") == ""


@pytest.mark.asyncio
async def test_preserves_c_include_directive(cleaner):
    """C 代码 `#include <stdio.h>` 不能被当 HTML 标签删掉（回归用例）。"""
    code = '#include <stdio.h>\nint main() { return 0; }'
    assert await run(cleaner, code) == code


@pytest.mark.asyncio
async def test_preserves_comparison_operators(cleaner):
    code = "if (a < b && c > d) { printf(\"%d\", x); }"
    assert await run(cleaner, code) == code


@pytest.mark.asyncio
async def test_real_html_tags_still_removed(cleaner):
    """设计权衡：合法的 HTML 标签形态（<div class='box'>）仍会被删除。

    HTMLResidueCleaner 无代码块上下文感知，只能按形态区分——合法标签删，
    非合法形态（<stdio.h>、a < b）保留。
    """
    code = "<div class='box'>content</div>"
    assert await run(cleaner, code) == "content"


@pytest.mark.asyncio
async def test_does_not_run_without_html_file_type(cleaner):
    """非 text/html 源不启用该清洗器。"""
    text = "<div>not cleaned</div>"
    out = await cleaner.clean(text, {"file_type": "text/plain"})
    assert out == text


@pytest.mark.asyncio
async def test_cleans_whitespace_after_tag_removal(cleaner):
    out = await run(cleaner, "a\n  <span>  \nb")
    # tags removed, then trailing/leading whitespace normalised
    assert "\n  " not in out or "b" in out
