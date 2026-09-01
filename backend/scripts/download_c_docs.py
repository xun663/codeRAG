#!/usr/bin/env python3
"""Download W3Schools C tutorial HTML pages for RAG knowledge base preprocessing.

用途: 收集公开 C 语言教程资料（模拟普通用户上传场景的原始语料）。

链接自动发现: 先下载首页 index.php，从侧边栏提取全部 c_*.php 教程页
（排除 challenges 练习页），再逐个下载。

Usage:
    python download_c_docs.py

Output:
    C:/Users/xun/Desktop/C语言资料/w3schools/  — Raw HTML files
"""

import re
import time
import urllib.request
from pathlib import Path

BASE_URL = "https://www.w3schools.com/c/"
HOME_URL = BASE_URL + "index.php"
OUTPUT_DIR = Path(r"C:\Users\xun\Desktop\C语言资料\w3schools")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read()
        try:
            return html.decode("utf-8")
        except UnicodeDecodeError:
            return html.decode("latin-1")


def discover_pages() -> list[str]:
    """Extract sidebar tutorial links from the home page (c_*.php, no challenges)."""
    home = fetch(HOME_URL)
    links = re.findall(r'href="([^"]*c_[a-z_]+\.php)"', home)
    seen: list[str] = []
    for l in links:
        if l not in seen:
            seen.append(l)
    pages = [l for l in seen if "challenge" not in l]
    return pages


def download_pages(pages: list[str]) -> tuple[int, int]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ok = 0
    fail = 0

    for page in pages:
        filename = page.split("/")[-1].replace(".php", ".html")
        output_path = OUTPUT_DIR / filename
        if output_path.exists():
            print(f"  [SKIP] {filename} (already exists)")
            ok += 1
            continue
        try:
            text = fetch(BASE_URL + page)
            output_path.write_text(text, encoding="utf-8")
            print(f"  [OK] {filename} ({len(text) // 1024}KB)")
            ok += 1
        except Exception as e:
            print(f"  [FAIL] {filename}: {e}")
            fail += 1
        time.sleep(2)  # rate limit — be polite to the source

    return ok, fail


def main():
    print(f"Discovering tutorial pages from {HOME_URL} ...")
    pages = discover_pages()
    print(f"Found {len(pages)} tutorial pages (challenges excluded)")
    print(f"Output: {OUTPUT_DIR}")
    print()

    ok, fail = download_pages(pages)

    total_size = sum(f.stat().st_size for f in OUTPUT_DIR.glob("*.html"))
    print(f"\nDone: {ok} OK, {fail} failed, {total_size // 1024}KB total")


if __name__ == "__main__":
    main()
