#!/usr/bin/env python3
"""RAG 知识库 Java 文档预处理：HTML → 干净 Markdown + YAML 元数据。

用法:
    cd backend
    python scripts/preprocess_java_docs.py

清洗规则:
    1. 格式统一 — 标题层级、列表、代码块、表格全部转为 Markdown
    2. 噪声清洗 — 删除导航/页脚/侧边栏/广告/评论区
    3. 元数据标注 — YAML front matter（source/topic/language/type）
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Ensure backend/ is on sys.path for app imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bs4 import BeautifulSoup
from app.core.documents.converters.html_to_md import (
    HTMLToMarkdownConverter,
    HTMLNoiseCleaner,
)

# ── Java W3Schools 主题映射表 ──────────────────────────────────────
JAVA_TOPIC_MAP: dict[str, tuple[str, str]] = {
    "java_home":               ("Java Overview",            "tutorial"),
    "java_intro":              ("Introduction to Java",     "tutorial"),
    "java_getstarted":         ("Getting Started",          "tutorial"),
    "java_syntax":             ("Java Syntax",              "tutorial"),
    "java_comments":           ("Java Comments",            "tutorial"),
    "java_variables":          ("Java Variables",           "tutorial"),
    "java_data_types":         ("Java Data Types",          "tutorial"),
    "java_type_casting":       ("Java Type Casting",        "tutorial"),
    "java_operators":          ("Java Operators",           "tutorial"),
    "java_strings":            ("Java Strings",             "tutorial"),
    "java_math":               ("Java Math",                "tutorial"),
    "java_booleans":           ("Java Booleans",            "tutorial"),
    "java_conditions":         ("Java If...Else",           "tutorial"),
    "java_switch":             ("Java Switch",              "tutorial"),
    "java_while_loop":         ("Java While Loop",          "tutorial"),
    "java_for_loop":           ("Java For Loop",            "tutorial"),
    "java_break":              ("Java Break and Continue",  "tutorial"),
    "java_arrays":             ("Java Arrays",              "tutorial"),
    "java_methods":            ("Java Methods",             "tutorial"),
    "java_methods_param":      ("Java Method Parameters",   "tutorial"),
    "java_methods_overloading":("Java Method Overloading",  "tutorial"),
    "java_scope":              ("Java Scope",               "tutorial"),
    "java_recursion":          ("Java Recursion",           "tutorial"),
    "java_oop":                ("Java OOP Concepts",        "tutorial"),
    "java_classes":            ("Java Classes and Objects", "tutorial"),
    "java_constructors":       ("Java Constructors",        "tutorial"),
    "java_modifiers":          ("Java Modifiers",           "tutorial"),
    "java_encapsulation":      ("Java Encapsulation",       "tutorial"),
    "java_inheritance":        ("Java Inheritance",         "tutorial"),
    "java_polymorphism":       ("Java Polymorphism",        "tutorial"),
    "java_inner_classes":      ("Java Inner Classes",       "tutorial"),
    "java_abstract":           ("Java Abstraction",         "tutorial"),
    "java_interface":          ("Java Interfaces",          "tutorial"),
    "java_enums":              ("Java Enums",               "tutorial"),
    "java_arraylist":          ("Java ArrayList",           "tutorial"),
    "java_linkedlist":         ("Java LinkedList",          "tutorial"),
    "java_hashmap":            ("Java HashMap",             "tutorial"),
    "java_hashset":            ("Java HashSet",             "tutorial"),
    "java_iterator":           ("Java Iterator",            "tutorial"),
    "java_wrapper_classes":    ("Java Wrapper Classes",     "tutorial"),
    "java_try_catch":          ("Java Try Catch",           "tutorial"),
    "java_regex":              ("Java Regular Expressions", "tutorial"),
    "java_threads":            ("Java Threads",             "tutorial"),
    "java_lambda":             ("Java Lambda Expressions",  "tutorial"),
}


def extract_title(soup: BeautifulSoup) -> str:
    """从 HTML 中提取页面标题。"""
    title_tag = soup.find("title")
    if title_tag:
        text = title_tag.get_text(strip=True)
        # W3Schools titles are like "Java Tutorial" — strip site name
        text = re.sub(r"\s*-\s*W3Schools\s*$", "", text, flags=re.I)
        text = re.sub(r"\s*\|.*$", "", text)  # Remove "| Learn Java" etc.
        return text.strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return ""


def generate_java_yaml_front_matter(filename: str, page_title: str = "") -> str:
    """生成 Java 文档的 YAML front matter。"""
    stem = Path(filename).stem.lower()
    topic, doc_type = JAVA_TOPIC_MAP.get(stem, (stem.replace("_", " ").title(), "reference"))

    parts = [
        "---",
        'source: "W3Schools Java Tutorial"',
        'language: "Java"',
        f'topic: "{topic}"',
        f'type: "{doc_type}"',
        "---",
        "",
    ]
    return "\n".join(parts)


def clean_markdown_noise(md: str) -> str:
    """Remove W3Schools-specific noise from generated Markdown.

    Applied after HTML→MD conversion, before writing output.
    """
    lines = md.split("\n")
    kept: list[str] = []
    skip_patterns = [
        # Navigation / UI text
        r"^(❮|❯)\s*(Previous|Next|previous|next)",
        r"^(Previous|Next)\s*(❮|❯)?\s*$",
        r"^(ADVERTISEMENT|\[advertisement\])",
        r"^(Track your progress|Log in|Sign Up|Sign up|Create a free)",
        r"^(Contact Sales|Report Error|Try it Yourself|Try it)",
        r"^(Video Course|Course Navigation|Video:)\s",
        r"^(Exercise\??|Exercises|Test Yourself|Quiz|QUIZ)\s*$",
        r"^(Reset Score|Reset score|Close This Menu|Hide Ads)",
        r"^(W3Schools|w3schools)\s+(is|offers|provides|Home)",
        r"^(The W3Schools online code editor|With our online)",
        r"^(Home|Back to|Return to|Go to)\s+(top|home|previous|next)",
        # Utility text
        r"^.*?\b(Log in|Sign Up|signup|login)\s+(now|today|to|for|free)\b",
        r"^(Learn how|Get certified|Become a|Why not get|Start your)",
        # Empty headings (no content after #)
        r"^#{1,6}\s*$",
        # Orphan headings — common in tutorial pages where content was cleaned
        r"^#{1,6}\s*(Example|Examples?|Note|Notes?|Tip|Tips?|Warning|See Also|See also)\s*:?\s*$",
        r"^#{1,6}\s*(Demo|Try it|Exercise|Practice|Test|Challenge|Task)\s*:?\s*$",
        r"^#{1,6}\s*(Syntax|Definition|Usage|Description|Output|Result)\s*:?\s*$",
        # Code-only headings (class names, variable names as bare headings)
        r"^#{1,6}\s*(class|interface|enum|record)\s+\w+\s*$",
        r"^#{1,6}\s*(public|private|protected|static|final|abstract)\s+(class|void|int|String|boolean)\s+\w+\s*$",
    ]
    compiled = [re.compile(p, re.I) for p in skip_patterns]

    for line in lines:
        if any(p.search(line) for p in compiled):
            continue
        kept.append(line)

    return "\n".join(kept)


def process_html_file(html_path: Path, output_dir: Path) -> Path | None:
    """处理单个 HTML 文件：清洗 + 转换 → 输出 Markdown。"""
    # 读取
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            html_content = f.read()
    except Exception as e:
        print(f"  [ERR] 读取失败: {e}", file=sys.stderr)
        return None

    # 解析
    soup = BeautifulSoup(html_content, "html.parser")

    # 提取标题（供元数据用）
    page_title = extract_title(soup)

    # ── 噪声清洗 ──
    cleaner = HTMLNoiseCleaner()
    soup = cleaner.clean(soup)

    # ── 格式转换：HTML → Markdown ──
    converter = HTMLToMarkdownConverter()
    markdown_content = converter.convert(soup)

    # ── Markdown 级噪声清洗 ──
    markdown_content = clean_markdown_noise(markdown_content)

    # 内容质量检查
    word_count = len(markdown_content.split())
    if word_count < 100:
        print(f"  [WARN] 内容过少 ({word_count} 词)，可能清洗过度", file=sys.stderr)

    # ── 生成 YAML front matter ──
    yaml_header = generate_java_yaml_front_matter(html_path.name, page_title)

    # 写入
    output_filename = html_path.with_suffix(".md").name
    output_path = output_dir / output_filename
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(yaml_header)
            f.write(markdown_content)
        size_kb = output_path.stat().st_size // 1024
        print(f"  [OK] {output_path.name:<30} {word_count:>5} 词  {size_kb:>4}KB")
    except Exception as e:
        print(f"  [ERR] 写入失败: {e}", file=sys.stderr)
        return None

    return output_path


def main():
    # Paths
    input_dir = Path(r"D:\coderag\知识库资料\Java\w3schools")
    output_dir = Path(r"D:\coderag\知识库资料_clean\Java\w3schools")
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(input_dir.glob("*.html"))
    if not files:
        print(f"错误: 目录中没有 .html 文件: {input_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'='*65}")
    print(f"Java 文档预处理：HTML → 干净 Markdown + YAML")
    print(f"来源:   W3Schools Java Tutorial")
    print(f"输入:   {input_dir} ({len(files)} 个 HTML 文件)")
    print(f"输出:   {output_dir}")
    print(f"管道:   解析 → HTMLNoiseCleaner → HTMLToMarkdownConverter → YAML")
    print(f"{'='*65}\n")

    ok = 0
    fail = 0
    for f in files:
        result = process_html_file(f, output_dir)
        if result:
            ok += 1
        else:
            fail += 1

    total_size = sum(f.stat().st_size for f in output_dir.glob("*.md"))
    print(f"\n{'='*65}")
    print(f"完成: {ok} 成功, {fail} 失败")
    print(f"输出: {output_dir} ({total_size // 1024}KB)")
    print(f"下一步: 导入 backend 知识库 → 验证 RAG 检索效果")
    print(f"{'='*65}")


if __name__ == "__main__":
    main()
