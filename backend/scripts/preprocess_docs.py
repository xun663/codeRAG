#!/usr/bin/env python3
"""RAG 知识库文档预处理脚本：HTML → 干净 Markdown + YAML 元数据。

用法:
    # 处理单个文件
    python preprocess_docs.py --input 知识库资料/index.html --output 知识库资料_clean/

    # 批量处理目录
    python preprocess_docs.py --input-dir 知识库资料/ --output-dir 知识库资料_clean/

    # 仅列出文件主题映射
    python preprocess_docs.py --input-dir 知识库资料/ --list-topics

清洗规则（匹配 docs/data-cleaning.md）:
    1. 格式统一 — 标题层级、列表、代码块、表格全部转为 Markdown
    2. 噪声清洗 — 删除导航/页脚/侧边栏/广告/评论区
    3. 元数据标注 — YAML front matter（source/version/topic/language/type）
    4. 代码预处理 — 为纯代码文件生成功能摘要
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup, Tag

# ─── 主题映射表 ────────────────────────────────────────────────────
# 文件名 → (topic, type) 元组，用于 YAML 元数据
TOPIC_MAP: dict[str, tuple[str, str]] = {
    "index":      ("Overview",           "tutorial"),
    "appetite":   ("Introduction",       "tutorial"),
    "interpreter":("Interpreter",        "tutorial"),
    "introduction":("Data Types",        "tutorial"),
    "controlflow":("Control Flow",       "tutorial"),
    "datastructures":("Data Structures", "tutorial"),
    "modules":    ("Modules",            "tutorial"),
    "inputoutput":("Input and Output",   "tutorial"),
    "errors":     ("Errors and Exceptions", "tutorial"),
    "classes":    ("Classes",            "tutorial"),
    "stdlib":     ("Standard Library",   "tutorial"),
    "venv":       ("Virtual Environments", "tutorial"),
    "whatnow":    ("Next Steps",         "tutorial"),
    "interactive":("Interactive Editing","tutorial"),
    "floatingpoint":("Floating Point",   "reference"),
    "appendix":   ("Appendix",           "reference"),
    "glossary":   ("Glossary",           "reference"),
}

# ─── 代码语言映射 ──────────────────────────────────────────────────
# NOTE: 本脚本保持独立可运行，未依赖 backend app 包。
# 共享的转换核心位于 app/core/documents/converters/html_to_md.py。
# 更新转换逻辑时请同步修改两处，或考虑后续统一。
LANG_MAP: dict[str, str] = {
    "python": "python", "pycon": "python", "py": "python",
    "python3": "python", "python2": "python",
    "javascript": "javascript", "js": "javascript",
    "typescript": "typescript", "ts": "typescript",
    "java": "java", "c": "c", "cpp": "cpp", "c++": "cpp",
    "go": "go", "rust": "rust", "rs": "rust",
    "bash": "bash", "sh": "bash", "shell": "bash",
    "sql": "sql", "html": "html", "xml": "xml",
    "json": "json", "yaml": "yaml", "yml": "yaml",
    "css": "css", "ruby": "ruby", "rb": "ruby",
    "php": "php", "swift": "swift", "kotlin": "kotlin",
    "text": "text", "none": "", "default": "",
}


# ═════════════════════════════════════════════════════════════════
#  一、格式统一：HTML → Markdown
# ═════════════════════════════════════════════════════════════════

class HTMLToMarkdownConverter:
    """将 HTML 片段转换为 Markdown。

    保留标题层级、列表、代码块、表格、链接、强调等结构。
    """

    def convert(self, soup: BeautifulSoup) -> str:
        """将清洗后的 BeautifulSoup 转换为 Markdown 字符串。"""
        body = soup.find("body")
        if body is None:
            body = soup
        parts: list[str] = []
        for element in body.children:
            if isinstance(element, Tag):
                parts.append(self._convert_element(element, 0))
        return self._post_process("\n".join(parts))

    def _convert_element(self, el: Tag, indent: int) -> str:
        method = getattr(self, f"_tag_{el.name}", self._tag_default)
        return method(el, indent)

    # ── 标题 ────────────────────────────────────────────────
    def _tag_h1(self, el: Tag, _: int) -> str:
        return f"# {self._inner_text(el).strip()}\n"

    def _tag_h2(self, el: Tag, _: int) -> str:
        return f"## {self._inner_text(el).strip()}\n"

    def _tag_h3(self, el: Tag, _: int) -> str:
        return f"### {self._inner_text(el).strip()}\n"

    def _tag_h4(self, el: Tag, _: int) -> str:
        return f"#### {self._inner_text(el).strip()}\n"

    def _tag_h5(self, el: Tag, _: int) -> str:
        return f"##### {self._inner_text(el).strip()}\n"

    def _tag_h6(self, el: Tag, _: int) -> str:
        return f"###### {self._inner_text(el).strip()}\n"

    # ── 段落和文本 ───────────────────────────────────────────
    def _tag_p(self, el: Tag, _: int) -> str:
        text = self._inner_text(el).strip()
        return f"{text}\n\n" if text else ""

    def _tag_div(self, el: Tag, indent: int) -> str:
        return self._convert_children(el, indent)

    def _tag_span(self, el: Tag, _: int) -> str:
        return self._inner_text(el)

    def _tag_default(self, el: Tag, indent: int) -> str:
        """Fallback for unknown tags: convert children."""
        return self._convert_children(el, indent)

    # ── 列表 ─────────────────────────────────────────────────
    def _tag_ul(self, el: Tag, _: int) -> str:
        lines: list[str] = []
        for li in el.find_all("li", recursive=False):
            text = self._inner_text(li).strip()
            # Handle nested lists
            nested = ""
            for child in li.children:
                if isinstance(child, Tag) and child.name in ("ul", "ol"):
                    nested = self._convert_element(child, 1)
                    break
            prefix = "-   "
            if nested:
                lines.append(f"{prefix}{text}")
                # Indent nested list lines
                for nline in nested.split("\n"):
                    lines.append(f"    {nline}" if nline.strip() else "")
            else:
                lines.append(f"{prefix}{text}")
        return "\n".join(lines) + "\n\n"

    def _tag_ol(self, el: Tag, _: int) -> str:
        lines: list[str] = []
        for i, li in enumerate(el.find_all("li", recursive=False), 1):
            text = self._inner_text(li).strip()
            nested = ""
            for child in li.children:
                if isinstance(child, Tag) and child.name in ("ul", "ol"):
                    nested = self._convert_element(child, 1)
                    break
            if nested:
                lines.append(f"{i}.  {text}")
                for nline in nested.split("\n"):
                    lines.append(f"    {nline}" if nline.strip() else "")
            else:
                lines.append(f"{i}.  {text}")
        return "\n".join(lines) + "\n\n"

    def _tag_dl(self, el: Tag, _: int) -> str:
        lines: list[str] = []
        for child in el.children:
            if isinstance(child, Tag):
                if child.name == "dt":
                    lines.append(f"**{self._inner_text(child).strip()}**")
                elif child.name == "dd":
                    lines.append(f":   {self._inner_text(child).strip()}")
        return "\n".join(lines) + "\n\n"

    # ── 代码块 ──────────────────────────────────────────────
    def _tag_pre(self, el: Tag, _: int) -> str:
        code = el.find("code")
        if code:
            lang = self._detect_language(el) or self._detect_language(code)
            text = code.get_text()
        else:
            # Sphinx docs often put code directly in <pre> without <code>
            lang = self._detect_language(el)
            text = el.get_text()
        # Clean up indentation
        lines = text.split("\n")
        # Remove leading/trailing empty lines
        while lines and lines[0].strip() == "":
            lines.pop(0)
        while lines and lines[-1].strip() == "":
            lines.pop()
        text = "\n".join(lines)
        return f"```{lang}\n{text}\n```\n\n"

    def _detect_language(self, tag: Tag) -> str:
        """Detect programming language from a tag's CSS class.

        Handles Sphinx doc formats: ``highlight-python3``, ``highlight-default``,
        Sphinx generic ``highlight`` (defaults to python for Python docs),
        as well as plain language names like ``python``.
        """
        classes = tag.get("class", [])
        if isinstance(classes, str):
            classes = classes.split()

        for cls in classes:
            # Sphinx: "highlight-python3" → "python"
            if cls.startswith("highlight-"):
                lang = cls[10:].lower()
                return LANG_MAP.get(lang, lang)
            # Sphinx generic highlight (Python docs default)
            if cls == "highlight":
                return "python"
            # Plain language name
            if cls in LANG_MAP:
                return LANG_MAP[cls]

        # Check parent for highlight language (when <code> itself has no language class)
        for candidate in tag.parents:
            parent_classes = candidate.get("class", [])
            if isinstance(parent_classes, str):
                parent_classes = parent_classes.split()
            for cls in parent_classes:
                if cls.startswith("highlight-"):
                    lang = cls[10:].lower()
                    return LANG_MAP.get(lang, lang)
                if cls == "highlight":
                    return "python"
                if cls in LANG_MAP:
                    return LANG_MAP[cls]
            # Don't go too far up
            if candidate.name in ("body", "html"):
                break
        return ""

    # ── 内联代码 ────────────────────────────────────────────
    def _tag_code(self, el: Tag, _: int) -> str:
        text = el.get_text()
        if "\n" in text:
            # Block code handled by _tag_pre
            return f"`{text}`"
        return f"`{text}`"

    # ── 表格 ─────────────────────────────────────────────────
    def _tag_table(self, el: Tag, _: int) -> str:
        rows = el.find_all("tr")
        if not rows:
            return ""
        md_rows: list[list[str]] = []
        for row in rows:
            cells = [self._inner_text(c).strip() for c in row.find_all(["th", "td"])]
            md_rows.append(cells)
        if not md_rows:
            return ""
        # Build markdown table
        lines: list[str] = []
        # Header row
        lines.append("| " + " | ".join(md_rows[0]) + " |")
        # Separator
        lines.append("| " + " | ".join("---" for _ in md_rows[0]) + " |")
        # Data rows
        for row in md_rows[1:]:
            # Pad or truncate to match header count
            while len(row) < len(md_rows[0]):
                row.append("")
            lines.append("| " + " | ".join(row[:len(md_rows[0])]) + " |")
        return "\n".join(lines) + "\n\n"

    # ── 链接和图片 ───────────────────────────────────────────
    def _tag_a(self, el: Tag, _: int) -> str:
        href = el.get("href", "")
        text = self._inner_text(el).strip()
        if not text:
            return href
        # Skip anchor-only links
        if href.startswith("#"):
            return text
        return f"[{text}]({href})"

    def _tag_img(self, el: Tag, _: int) -> str:
        src = el.get("src", "")
        alt = el.get("alt", "")
        return f"![{alt}]({src})"

    # ── 强调 ─────────────────────────────────────────────────
    def _tag_strong(self, el: Tag, _: int) -> str:
        return f"**{self._inner_text(el)}**"

    def _tag_em(self, el: Tag, _: int) -> str:
        return f"*{self._inner_text(el)}*"

    def _tag_b(self, el: Tag, _: int) -> str:
        return f"**{self._inner_text(el)}**"

    def _tag_i(self, el: Tag, _: int) -> str:
        return f"*{self._inner_text(el)}*"

    def _tag_blockquote(self, el: Tag, _: int) -> str:
        text = self._inner_text(el).strip()
        lines = [f"> {line}" for line in text.split("\n")]
        return "\n".join(lines) + "\n\n"

    def _tag_hr(self, el: Tag, _: int) -> str:
        return "---\n\n"

    # ── 辅助方法 ─────────────────────────────────────────────
    def _inner_text(self, el: Tag) -> str:
        """Get text content of an element, converting inline children."""
        parts: list[str] = []
        for child in el.children:
            if isinstance(child, Tag):
                if child.name in ("script", "style"):
                    continue
                parts.append(self._convert_element(child, 0))
            elif isinstance(child, str):
                parts.append(child)
            else:
                parts.append(str(child))
        return "".join(parts)

    def _convert_children(self, el: Tag, indent: int) -> str:
        """Convert all child elements, joining with newlines."""
        parts: list[str] = []
        for child in el.children:
            if isinstance(child, Tag):
                parts.append(self._convert_element(child, indent))
            elif isinstance(child, str) and child.strip():
                parts.append(child.strip())
        return "\n".join(parts)

    def _post_process(self, text: str) -> str:
        """Final cleanup pass on the generated Markdown."""
        # Collapse 3+ consecutive newlines to 2
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Remove trailing whitespace
        text = re.sub(r"[ \t]+\n", "\n", text)
        # Ensure file ends with single newline
        text = text.strip() + "\n"
        # Fix common broken patterns
        text = re.sub(r"\n{2,}(#{1,6}\s)", r"\n\n\1", text)  # heading spacing
        return text


# ═════════════════════════════════════════════════════════════════
#  二、噪声清洗
# ═════════════════════════════════════════════════════════════════

class HTMLNoiseCleaner:
    """从 HTML 中移除导航、页脚、侧边栏等无关内容。"""

    # CSS 选择器模式：需要移除的噪声元素
    NOISE_SELECTORS: list[str] = [
        # 导航
        "nav", ".nav", ".navbar", "#nav", "#navbar", ".navigation",
        ".topnav", ".main-nav", ".site-nav", ".global-nav",
        ".breadcrumb", ".breadcrumbs",
        # 侧边栏
        ".sidebar", "#sidebar", ".side-bar", ".side-menu",
        ".toc", ".toctree", ".contents", ".local-toc",
        # 页脚
        "footer", ".footer", "#footer", ".site-footer",
        ".copyright", ".footer-links",
        # 广告和推广
        ".advertisement", ".ad", ".ads", ".adsbygoogle",
        ".sponsor", ".sponsored", ".promotion",
        # 评论区
        ".comments", "#comments", ".comment-list", ".comment-area",
        ".disqus", "#disqus_thread",
        # 搜索
        ".searchbox", ".search-form", "#searchbox",
        # 其它 UI 元素
        ".social-share", ".share-buttons",
        ".back-to-top", ".go-to-top",
        ".skip-link", ".skip-to-content",
        ".headerlink", ".headerlink",  # ¶ link in Python docs
        ".edit-this-page", ".improve-page",
        ".related-pages", ".related",
        ".prev-next", ".pager", ".pagination",
        ".only-mobile", ".only-small",
    ]

    def clean(self, soup: BeautifulSoup) -> BeautifulSoup:
        """移除噪声元素，返回清理后的 soup。"""
        # 1. 移除脚本和样式
        for tag in soup(["script", "style"]):
            tag.decompose()

        # 2. 按选择器移除噪声
        for selector in self.NOISE_SELECTORS:
            for element in soup.select(selector):
                element.decompose()

        # 3. 移除空链接（¶ headerlink 等）
        for a in soup.find_all("a", class_="headerlink"):
            a.decompose()

        # 4. 移除仅含图标的元素
        for el in soup.find_all(class_=re.compile(r"(icon|glyph|svg)", re.I)):
            # Only remove if it has no meaningful text
            text = el.get_text(strip=True)
            if not text or len(text) < 3:
                el.decompose()

        return soup


# ═════════════════════════════════════════════════════════════════
#  三、YAML 元数据生成
# ═════════════════════════════════════════════════════════════════

def generate_yaml_front_matter(filename: str, page_title: str = "") -> str:
    """生成 YAML front matter, 使用 topic_map 中的映射关系。

    Args:
        filename: HTML 文件名（不含路径）
        page_title: 页面标题（在 HTML 中提取到的 <title>）

    Returns:
        YAML 格式的 front matter 字符串（包含前后的 --- 分隔符）
    """
    stem = Path(filename).stem.lower()
    topic, doc_type = TOPIC_MAP.get(stem, (stem.capitalize(), "reference"))

    # 从标题提取版本号
    version = "3.13"
    if "3." in page_title:
        m = re.search(r"(\d+\.\d+)", page_title)
        if m:
            version = m.group(1)

    parts = [
        "---",
        f'source: "Python Official Tutorial (zh-CN)"',
        f'version: "{version}"',
        f'topic: "{topic}"',
        f'language: "Python"',
        f'type: "{doc_type}"',
        "---",
        "",
    ]
    return "\n".join(parts)


# ═════════════════════════════════════════════════════════════════
#  四、主流程
# ═════════════════════════════════════════════════════════════════

def extract_title(soup: BeautifulSoup) -> str:
    """从 HTML 中提取页面标题。"""
    title_tag = soup.find("title")
    if title_tag:
        return title_tag.get_text(strip=True)
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return ""


def process_html_file(html_path: Path, output_dir: Path) -> Path | None:
    """处理单个 HTML 文件，输出 Markdown 文件。

    Args:
        html_path: 输入 HTML 文件路径
        output_dir: 输出目录

    Returns:
        输出文件的 Path，如果处理失败则返回 None
    """
    # 读取 HTML
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
    except Exception as e:
        print(f"  [ERR] 读取失败: {e}", file=sys.stderr)
        return None

    # 解析
    soup = BeautifulSoup(html_content, "html.parser")

    # 提取标题（用于元数据）
    page_title = extract_title(soup)

    # 噪声清洗
    cleaner = HTMLNoiseCleaner()
    soup = cleaner.clean(soup)

    # 格式转换（HTML → Markdown）
    converter = HTMLToMarkdownConverter()
    markdown_content = converter.convert(soup)

    # 如果内容太少，可能是清洗过度，打印警告
    word_count = len(markdown_content.split())
    if word_count < 50 and html_path.name != "whatnow.html":
        print(f"  [WARN] 内容过少 ({word_count} 词)，可能清洗过度", file=sys.stderr)

    # 生成 YAML front matter
    yaml_header = generate_yaml_front_matter(html_path.name, page_title)

    # 写入输出
    output_filename = html_path.with_suffix(".md").name
    output_path = output_dir / output_filename
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(yaml_header)
            f.write(markdown_content)
        print(f"  [OK]  {output_path.name}  ({word_count} 词, {output_path.stat().st_size // 1024}KB)")
    except Exception as e:
        print(f"  [ERR] 写入失败: {e}", file=sys.stderr)
        return None

    return output_path


def list_topics(input_dir: Path) -> None:
    """列出文件到主题的映射关系（预览用）。"""
    files = sorted(input_dir.glob("*.html"))
    print(f"\n{'文件名':<30} {'主题':<25} {'类型':<15}")
    print("-" * 70)
    for f in files:
        stem = f.stem.lower()
        topic, doc_type = TOPIC_MAP.get(stem, (stem.capitalize(), "reference"))
        print(f"{f.name:<30} {topic:<25} {doc_type:<15}")
    print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RAG 文档预处里：HTML → 干净 Markdown + YAML 元数据",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/preprocess_docs.py --input-dir 知识库资料/ --output-dir 知识库资料_clean/
  python scripts/preprocess_docs.py --input 知识库资料/index.html --output 知识库资料_clean/
  python scripts/preprocess_docs.py --input-dir 知识库资料/ --list-topics
        """,
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input", type=str, help="单个 HTML 文件")
    input_group.add_argument("--input-dir", type=str, help="输入目录（包含 .html 文件）")
    parser.add_argument("--output-dir", type=str, default="知识库资料_clean", help="输出目录（默认: 知识库资料_clean）")
    parser.add_argument("--list-topics", action="store_true", help="仅列出文件 主题映身，不处理文件")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_dir: Path | None = None
    files: list[Path] = []

    if args.input_dir:
        input_dir = Path(args.input_dir).resolve()
        if not input_dir.is_dir():
            print(f"错误: 输入目录不存在: {input_dir}", file=sys.stderr)
            sys.exit(1)
        files = sorted(input_dir.glob("*.html"))
        if not files:
            print(f"错误: 目录中没有 .html 文件: {input_dir}", file=sys.stderr)
            sys.exit(1)
        print(f"找到 {len(files)} 个 HTML 文件")

        if args.list_topics:
            list_topics(input_dir)
            return

    elif args.input:
        input_path = Path(args.input).resolve()
        if not input_path.is_file():
            print(f"错误: 文件不存在: {input_path}", file=sys.stderr)
            sys.exit(1)
        files = [input_path]
        input_dir = input_path.parent

    # 确保输出目录存在
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"来源: Python Official Tutorial (zh-CN)")
    print(f"版本: 3.14")
    print(f"输入: {input_dir}")
    print(f"输出: {output_dir}")
    print(f"{'='*60}\n")

    # 处理每个文件
    ok = 0
    fail = 0
    for f in files:
        result = process_html_file(f, output_dir)
        if result:
            ok += 1
        else:
            fail += 1

    # 输出统计
    print(f"\n{'='*60}")
    print(f"处理完成: {ok} 成功, {fail} 失败")
    total_size = sum(f.stat().st_size for f in output_dir.glob("*.md"))
    print(f"输出目录: {output_dir} ({total_size // 1024}KB)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
