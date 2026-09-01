"""Regression tests for the chunkers.

Covers the 2026-08-26 fix:
  1. HTML-converted-to-Markdown docs (.html) must split by headings —
     previously routed to RecursiveTextChunker and became one giant chunk.
  2. C/C++/C# source files must split on function/struct boundaries —
     previously fell back to Python regex and did not split.
"""

from __future__ import annotations

import pytest

from app.core.documents.chunkers.hybrid import HybridChunker
from app.core.documents.chunkers.code_aware import CodeAwareChunker


@pytest.mark.asyncio
async def test_html_tutorial_splits_by_heading():
    """W3Schools 风格 HTML 转 Markdown 后应按标题切成多个小 chunk。"""
    md = """# C Arrays
## Arrays
Arrays are used to store multiple values in a single variable.
To create an array, define the data type and the name followed by brackets.

## Access the Elements of an Array
To access an array element, refer to its index number.
Array indexes start with 0.

## Change an Array Element
To change the value of a specific element, refer to the index number.

## Set Array Size
Another common way to create arrays is to specify the size.
"""
    chunker = HybridChunker()
    chunks = await chunker.split(md, {"file_extension": ".html", "mime_type": "text/html"})
    assert len(chunks) >= 3, f"HTML 教程应被标题切开，实际 {len(chunks)} 个 chunk"


@pytest.mark.asyncio
async def test_c_source_splits_on_functions():
    """C 源码应按函数/结构体边界切分。"""
    code = """#include <stdio.h>

int add(int a, int b) {
    return a + b;
}

struct Point {
    int x;
    int y;
};

void print_point(struct Point p) {
    printf("%d,%d", p.x, p.y);
}

int main(void) {
    return 0;
}
"""
    chunker = CodeAwareChunker()
    chunks = await chunker.split(code, {"language": "c"})
    types = [c["chunk_type"] for c in chunks]
    assert len(chunks) >= 4, f"C 源码应按函数/struct 切分，实际 {len(chunks)} 个 chunk"
    assert "function" in types
    assert "class" in types  # struct → class 类型


@pytest.mark.asyncio
async def test_cpp_source_splits_on_functions_and_classes():
    """C++ 源码应按函数/类边界切分。"""
    code = """#include <iostream>
using namespace std;

class Animal {
public:
    void speak() {
        cout << "..." << endl;
    }
};

int main() {
    Animal a;
    a.speak();
    return 0;
}
"""
    chunker = CodeAwareChunker()
    chunks = await chunker.split(code, {"language": "cpp"})
    types = [c["chunk_type"] for c in chunks]
    assert len(chunks) >= 3, f"C++ 源码应按类/函数切分，实际 {len(chunks)} 个 chunk"
    assert "class" in types
