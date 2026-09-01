#!/usr/bin/env python3
"""Download Java tutorial HTML pages for RAG knowledge base preprocessing.

Usage:
    python download_java_docs.py

Output:
    D:\coderag\知识库资料\Java\w3schools\  — Raw HTML files
"""

import time
import urllib.request
from pathlib import Path

# ── W3Schools Java Tutorial pages ──────────────────────────────────
W3SCHOOLS_PAGES: list[tuple[str, str]] = [
    # (url, filename)
    ("https://www.w3schools.com/java/default.asp", "java_home.html"),
    ("https://www.w3schools.com/java/java_intro.asp", "java_intro.html"),
    ("https://www.w3schools.com/java/java_getstarted.asp", "java_getstarted.html"),
    ("https://www.w3schools.com/java/java_syntax.asp", "java_syntax.html"),
    ("https://www.w3schools.com/java/java_comments.asp", "java_comments.html"),
    ("https://www.w3schools.com/java/java_variables.asp", "java_variables.html"),
    ("https://www.w3schools.com/java/java_data_types.asp", "java_data_types.html"),
    ("https://www.w3schools.com/java/java_type_casting.asp", "java_type_casting.html"),
    ("https://www.w3schools.com/java/java_operators.asp", "java_operators.html"),
    ("https://www.w3schools.com/java/java_strings.asp", "java_strings.html"),
    ("https://www.w3schools.com/java/java_math.asp", "java_math.html"),
    ("https://www.w3schools.com/java/java_booleans.asp", "java_booleans.html"),
    ("https://www.w3schools.com/java/java_conditions.asp", "java_conditions.html"),
    ("https://www.w3schools.com/java/java_switch.asp", "java_switch.html"),
    ("https://www.w3schools.com/java/java_while_loop.asp", "java_while_loop.html"),
    ("https://www.w3schools.com/java/java_for_loop.asp", "java_for_loop.html"),
    ("https://www.w3schools.com/java/java_break.asp", "java_break.html"),
    ("https://www.w3schools.com/java/java_arrays.asp", "java_arrays.html"),
    ("https://www.w3schools.com/java/java_methods.asp", "java_methods.html"),
    ("https://www.w3schools.com/java/java_methods_param.asp", "java_methods_param.html"),
    ("https://www.w3schools.com/java/java_methods_overloading.asp", "java_methods_overloading.html"),
    ("https://www.w3schools.com/java/java_scope.asp", "java_scope.html"),
    ("https://www.w3schools.com/java/java_recursion.asp", "java_recursion.html"),
    ("https://www.w3schools.com/java/java_oop.asp", "java_oop.html"),
    ("https://www.w3schools.com/java/java_classes.asp", "java_classes.html"),
    ("https://www.w3schools.com/java/java_constructors.asp", "java_constructors.html"),
    ("https://www.w3schools.com/java/java_modifiers.asp", "java_modifiers.html"),
    ("https://www.w3schools.com/java/java_encapsulation.asp", "java_encapsulation.html"),
    ("https://www.w3schools.com/java/java_inheritance.asp", "java_inheritance.html"),
    ("https://www.w3schools.com/java/java_polymorphism.asp", "java_polymorphism.html"),
    ("https://www.w3schools.com/java/java_inner_classes.asp", "java_inner_classes.html"),
    ("https://www.w3schools.com/java/java_abstract.asp", "java_abstract.html"),
    ("https://www.w3schools.com/java/java_interface.asp", "java_interface.html"),
    ("https://www.w3schools.com/java/java_enums.asp", "java_enums.html"),
    ("https://www.w3schools.com/java/java_arraylist.asp", "java_arraylist.html"),
    ("https://www.w3schools.com/java/java_linkedlist.asp", "java_linkedlist.html"),
    ("https://www.w3schools.com/java/java_hashmap.asp", "java_hashmap.html"),
    ("https://www.w3schools.com/java/java_hashset.asp", "java_hashset.html"),
    ("https://www.w3schools.com/java/java_iterator.asp", "java_iterator.html"),
    ("https://www.w3schools.com/java/java_wrapper_classes.asp", "java_wrapper_classes.html"),
    ("https://www.w3schools.com/java/java_exceptions.asp", "java_exceptions.html"),
    ("https://www.w3schools.com/java/java_try_catch.asp", "java_try_catch.html"),
    ("https://www.w3schools.com/java/java_regex.asp", "java_regex.html"),
    ("https://www.w3schools.com/java/java_threads.asp", "java_threads.html"),
    ("https://www.w3schools.com/java/java_lambda.asp", "java_lambda.html"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def download_pages(output_dir: Path) -> tuple[int, int]:
    """Download all pages to output_dir. Returns (ok, fail) counts."""
    output_dir.mkdir(parents=True, exist_ok=True)

    ok = 0
    fail = 0

    for url, filename in W3SCHOOLS_PAGES:
        output_path = output_dir / filename
        if output_path.exists():
            print(f"  [SKIP] {filename} (already exists)")
            ok += 1
            continue

        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                html = resp.read()
                # W3Schools declares charset in meta, but response may claim utf-8
                # Try to detect and handle encoding
                try:
                    text = html.decode("utf-8")
                except UnicodeDecodeError:
                    text = html.decode("latin-1")

            output_path.write_text(text, encoding="utf-8")
            size_kb = len(text) // 1024
            print(f"  [OK] {filename} ({size_kb}KB)")
            ok += 1
        except Exception as e:
            print(f"  [FAIL] {filename}: {e}")
            fail += 1

        # Rate limit
        time.sleep(2)

    return ok, fail


def main():
    output_dir = Path(r"D:\coderag\知识库资料\Java\w3schools")
    print(f"Downloading {len(W3SCHOOLS_PAGES)} W3Schools Java tutorial pages...")
    print(f"Output: {output_dir}")
    print()

    ok, fail = download_pages(output_dir)

    total_size = sum(f.stat().st_size for f in output_dir.glob("*.html"))
    print(f"\nDone: {ok} OK, {fail} failed, {total_size // 1024}KB total")


if __name__ == "__main__":
    main()
