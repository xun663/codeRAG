"""HTML → Markdown 转换器。

将 HTML 文档转换为结构化的 Markdown，保留标题层级、列表、
代码块、表格、链接、强调等结构。同时提供噪声清洗功能，
移除导航、页脚、侧边栏等无关内容。

用法:
    from app.core.documents.converters.html_to_md import HTMLToMarkdownConverter, HTMLNoiseCleaner

    cleaner = HTMLNoiseCleaner()
    soup = cleaner.clean(soup)

    converter = HTMLToMarkdownConverter()
    markdown = converter.convert(soup)
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

# ═════════════════════════════════════════════════════════════════
#  代码语言映射
# ═════════════════════════════════════════════════════════════════

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
#  噪声清洗
# ═════════════════════════════════════════════════════════════════

class HTMLNoiseCleaner:
    """从 HTML 中移除导航、页脚、侧边栏等无关内容。"""

    NOISE_SELECTORS: list[str] = [
        # 导航
        "nav", ".nav", ".navbar", "#nav", ".navigation",
        ".topnav", ".main-nav", ".site-nav", ".global-nav",
        ".breadcrumb", ".breadcrumbs",
        # 侧边栏
        ".sidebar", "#sidebar", ".side-bar", ".side-menu",
        ".toc", ".toctree", ".contents", ".local-toc",
        # 页脚
        "footer", ".footer", "#footer", ".site-footer",
        ".copyright", ".footer-links",
        # 广告
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
        ".headerlink",
        ".edit-this-page", ".improve-page",
        ".related-pages", ".related",
        ".prev-next", ".pager", ".pagination",
        ".only-mobile", ".only-small",
        # ── W3Schools 新版布局（2024+，C 教程等新站点使用）──
        # 顶部导航（tnb = top navigation bar）
        "[id^='tnb-']", "[id^='tnb_']",
        "#top-nav-bar", "#pagetop", "#subtopnav", "#menubtn_container",
        "#dropdown-nav-outer-wrapper", "#dropdown-nav-inner-wrapper",
        # 侧边栏教程导航（每块都是 .tut_overview；外层容器 #sidenav 一并移除）
        ".tut_overview",
        "#sidenav", "#leftmenuinner", "#leftmenuinnerinner", ".w3-sidebar",
        # 页脚与版权
        "#footerwrapper", "#spacemyfooter",
        # 广告区
        "#bottomads", "#midcontentadcontainer", "#skyscraper",
        "#stickyadcontainer", "#stickypos",
        # 搜索
        "#googleSearch", "[id^='tnb-google-search']",
        # 认证/导航卡片区（certifications / references / exercises）
        "[id^='certnav_']", "[id^='refnav_']", "[id^='exnav_']",
        "#certified_list", "#references_list", "#tutorials_list", "#exercises_list",
        # 用户激励卡片（Earn XP / Streaks / Leagues）
        ".servicebox",
        # 其它 UI
        "#scroll_left_btn", "#scroll_right_btn", "#err_message",
        "#upperfeatureshowcase-text",
        # W3Schools 右侧栏（分享/广告区）
        ".sharethis", "#right",
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

        # 3. 移除空链接（headerlink 等）
        for a in soup.find_all("a", class_="headerlink"):
            a.decompose()

        # 4. 移除仅含图标的元素
        for el in soup.find_all(class_=re.compile(r"(icon|glyph|svg)", re.I)):
            text = el.get_text(strip=True)
            if not text or len(text) < 3:
                el.decompose()

        return soup


# ═════════════════════════════════════════════════════════════════
#  HTML → Markdown 转换器
# ═════════════════════════════════════════════════════════════════

class HTMLToMarkdownConverter:
    """将清理后的 HTML (BeautifulSoup) 转换为 Markdown。

    保留标题层级、列表、代码块、表格、链接、强调等结构。
    Sphinx 文档（Python 官方文档等）的 HTML 结构已针对处理。
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
        return self._convert_children(el, indent)

    # ── 列表 ─────────────────────────────────────────────────
    def _tag_ul(self, el: Tag, _: int) -> str:
        lines: list[str] = []
        for li in el.find_all("li", recursive=False):
            text = self._inner_text(li).strip()
            nested = ""
            for child in li.children:
                if isinstance(child, Tag) and child.name in ("ul", "ol"):
                    nested = self._convert_element(child, 1)
                    break
            if nested:
                lines.append(f"-   {text}")
                for nline in nested.split("\n"):
                    lines.append(f"    {nline}" if nline.strip() else "")
            else:
                lines.append(f"-   {text}")
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
            # Sphinx: code directly in <pre> without <code>
            lang = self._detect_language(el)
            text = el.get_text()
        lines = text.split("\n")
        while lines and lines[0].strip() == "":
            lines.pop(0)
        while lines and lines[-1].strip() == "":
            lines.pop()
        text = "\n".join(lines)
        return f"```{lang}\n{text}\n```\n\n"

    def _detect_language(self, tag: Tag) -> str:
        """从 CSS class 中检测编程语言。"""
        classes = tag.get("class", [])
        if isinstance(classes, str):
            classes = classes.split()

        for cls in classes:
            if cls.startswith("highlight-"):
                lang = cls[10:].lower()
                return LANG_MAP.get(lang, lang)
            if cls == "highlight":
                return "python"
            if cls in LANG_MAP:
                return LANG_MAP[cls]

        # Check parents
        for candidate in tag.parents:
            pc = candidate.get("class", [])
            if isinstance(pc, str):
                pc = pc.split()
            for cls in pc:
                if cls.startswith("highlight-"):
                    lang = cls[10:].lower()
                    return LANG_MAP.get(lang, lang)
                if cls == "highlight":
                    return "python"
                if cls in LANG_MAP:
                    return LANG_MAP[cls]
            if candidate.name in ("body", "html", "[document]"):
                break
        return ""

    # ── 内联代码 ────────────────────────────────────────────
    def _tag_code(self, el: Tag, _: int) -> str:
        text = el.get_text()
        return f"`{text}`" if "\n" not in text else f"`{text}`"

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
        lines: list[str] = []
        lines.append("| " + " | ".join(md_rows[0]) + " |")
        lines.append("| " + " | ".join("---" for _ in md_rows[0]) + " |")
        for row in md_rows[1:]:
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

    def _tag_hr(self, _el: Tag, __: int) -> str:
        return "---\n\n"

    # ── 辅助方法 ─────────────────────────────────────────────
    def _inner_text(self, el: Tag) -> str:
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
        parts: list[str] = []
        for child in el.children:
            if isinstance(child, Tag):
                parts.append(self._convert_element(child, indent))
            elif isinstance(child, str) and child.strip():
                parts.append(child.strip())
        return "\n".join(parts)

    def _post_process(self, text: str) -> str:
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = text.strip() + "\n"
        text = re.sub(r"\n{2,}(#{1,6}\s)", r"\n\n\1", text)
        return text
