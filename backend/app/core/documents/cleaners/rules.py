"""Text cleaning rule implementations.

Each rule is a self-contained cleaner that addresses one type of noise.
Rules are designed to be safe for code-heavy content where applicable.
"""
from __future__ import annotations

import re
import unicodedata

from app.core.documents.cleaners.base import BaseCleaner


# ═══════════════════════════════════════════════════════════════
#  Whitespace normalizer
# ═══════════════════════════════════════════════════════════════

class WhitespaceNormalizer(BaseCleaner):
    """Normalize line endings, collapse excessive blank lines, trim.

    Academic purpose — text normalisation ensures consistent input
    for downstream chunking and embedding, reducing edge cases
    caused by platform-specific line endings.
    """

    @property
    def name(self) -> str:
        return "whitespace_normalizer"

    async def clean(self, text: str, metadata: dict | None = None) -> str:
        # 1. Normalise line endings → \n
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # 2. Collapse 3+ consecutive blank lines to 2
        text = re.sub(r"\n{3,}", "\n\n", text)
        # 3. Strip leading / trailing whitespace
        text = text.strip()
        return text


# ═══════════════════════════════════════════════════════════════
#  Unicode sanitizer
# ═══════════════════════════════════════════════════════════════

class UnicodeSanitizer(BaseCleaner):
    """Normalise unicode — fullwidth → halfwidth, remove control chars.

    Academic purpose — unicode normalisation prevents the same
    character encoded differently from fragmenting retrieval,
    which is critical for multilingual code documentation.
    """

    @property
    def name(self) -> str:
        return "unicode_sanitizer"

    # Mapping for common fullwidth ASCII equivalents
    _FULLWIDTH_TO_ASCII = str.maketrans({
        chr(0xFF01 + i): chr(0x21 + i) for i in range(94)  # FF01-FF5E → 21-7E
    })

    async def clean(self, text: str, metadata: dict | None = None) -> str:
        # 0. Non-breaking spaces → regular spaces
        text = text.replace("\xa0", " ").replace(" ", " ")
        # 1. Remove non-printable control chars (keep \t \n \r)
        text = "".join(
            ch if ch in ("\t", "\n", "\r") or unicodedata.category(ch) not in ("Cc", "Cf")
            else "" for ch in text
        )
        # 2. Fullwidth → halfwidth (letters, digits, symbols)
        text = text.translate(self._FULLWIDTH_TO_ASCII)
        # 3. NFC normalise (compose combined characters)
        text = unicodedata.normalize("NFC", text)
        return text


# ═══════════════════════════════════════════════════════════════
#  HTML residue cleaner
# ═══════════════════════════════════════════════════════════════

class HTMLResidueCleaner(BaseCleaner):
    """Strip leftover HTML / XML tags that parsers may have missed.

    Academic purpose — URL imports may retain inline tags after
    BeautifulSoup extraction; these degrade chunk quality.

    NOTE: the tag pattern is deliberately strict (real tag-name grammar,
    not a blanket ``<[^>]*>``). A blanket pattern corrupts programming
    tutorials — C code like ``#include <stdio.h>`` or comparisons like
    ``a < b`` would be eaten as "tags". ``<stdio.h>`` is not matched
    because ``.`` is not valid inside a tag name.
    """

    _TAG_RE = re.compile(
        r"</?[a-zA-Z][a-zA-Z0-9-]*"   # opening/closing tag name
        r"(?:\s+[^<>]*?)?\s*/?>"      # optional attributes, then close
    )

    @property
    def name(self) -> str:
        return "html_residue_cleaner"

    async def clean(self, text: str, metadata: dict | None = None) -> str:
        # Only applied to documents that look like they came from the web
        if metadata and metadata.get("file_type") in ("text/html",):
            text = self._TAG_RE.sub("", text)
            # Clean up leftover whitespace from tag removal
            text = re.sub(r" +\n", "\n", text)
            text = re.sub(r"\n +", "\n", text)
        return text


# ═══════════════════════════════════════════════════════════════
#  Noise line filter
# ═══════════════════════════════════════════════════════════════

class NoiseLineFilter(BaseCleaner):
    """Remove lines that match common noise patterns.

    Academic purpose — web-scraped content often carries navigation
    chrome, copyright boilerplate, and other non-informative lines
    that dilute embedding quality.
    """

    # Patterns that indicate a line is likely noise
    _NOISE_PATTERNS: list[re.Pattern] = [
        re.compile(r"^\s*$"),                              # empty / whitespace-only
        re.compile(r"^[\s\-–—*=+_~#°•·‣⁃◦●○◆◇▪▫■□▸▹►▻▼▽]+$"),  # decorative
        # Legal / corporate
        re.compile(r"^copyright|©|all rights reserved", re.I),
        re.compile(r"^privacy policy|terms of service|免责声明|隐私政策|cookie", re.I),
        # Social / sharing
        re.compile(r"^(share|tweet|pin|like|follow)\s", re.I),
        re.compile(r"^(advertisement|sponsored|推广|广告)", re.I),
        re.compile(r"^(page\s*\d+|第\s*\d+\s*页)$", re.I),
        # HTML remnants
        re.compile(r"^<!--.*-->$"),                         # HTML comment remnants
        re.compile(r"^<[/!]?(div|span|a|p|li|ul|ol|section|article|header|main|script|style|button|input)[^>]*>.*$", re.I),  # 残留标签行
        re.compile(r"^<[/!]?[a-zA-Z][a-zA-Z0-9-]*[^>]*>\s*$", re.I),  # 裸标签行
        # W3Schools 新版 UI 文本（2024+ 布局）
        re.compile(r"^(Earn XP|Streaks|Leagues|Your Own Space|See More|Search field|Sign In|user-anonymous)\b", re.I),
        re.compile(r"^\[(\*\*|★|\+1|×)\]", re.I),
        re.compile(r"^(Menu|Home|Tutorials|References|Exercises|Certificates|Bootcamps|Services)\s*$", re.I),
        re.compile(r"^\s*(original:|ny:|MainLeaderboard|Leaderboard|start\s*$)", re.I),
        re.compile(r"^\[(❮|❯|Previous|Next)[^\]]*\]\(", re.I),
        re.compile(r"^\[(Sign in|Log in|Create a free|Start learning|Track your progress|Go to)\b[^\]]*\]\(", re.I),
        # W3Schools 页面布局示例（教程页底部的页面结构演示，特征: w3- 前缀 + 单引号属性）
        re.compile(r"^\s*<[a-zA-Z]+[^>]*class=['\"]w3-[^'\"]*['\"][^>]*>", re.I),
        re.compile(r"^\s*</?[a-zA-Z]+[^>]*\s*>?\s*$"),
        re.compile(r"^(\[\*\*$|\[\★$|\+1\]\(|Copy link\.|Shares the page URL)", re.I),
        re.compile(r"^/\s*(LinkedIn|Twitter|Facebook|Copy link)\b", re.I),
        # W3Schools / tutorial site patterns
        re.compile(r"^(❮|❯|Previous|Next|previous|next)\s*(❮|❯|Previous|Next|previous|next|\||$)", re.I),
        re.compile(r"^(ADVERTISEMENT|AD\b|\[advertisement\])", re.I),
        re.compile(r"^(Track your progress|Log in|Sign up|Create a free|Report Error|Report error|Try it Yourself)", re.I),
        re.compile(r"^(Contact|Contact Sales|Sales|Send us an e-mail)", re.I),
        re.compile(r"^(Video:|Video Course|Course Navigation|Video Course Navigation)", re.I),
        re.compile(r"^(Exercise\??|Exercises|Test Yourself|Quiz|QUIZ)\s*\??\s*$", re.I),
        re.compile(r"^(Reset Score|Reset score|Close This Menu|Close this menu|Hide Ads|Hide ads)", re.I),
        re.compile(r"^.+?(Log in|Sign Up|signup|login)\s*(now|today|to|for|free)", re.I),
        re.compile(r"^(W3Schools|w3schools)\s+(is|offers|provides|Home|Tutorials|References|Exercises)", re.I),
        re.compile(r"^(The W3Schools online code editor|With our online)", re.I),
        # Navigation artifacts
        re.compile(r"^(Home|Back to|Return to|Go to)\s+(top|home|previous|next|tutorial|menu|page)", re.I),
        re.compile(r"^(Main Navigation|Site Navigation|Breadcrumb|breadcrumb)", re.I),
        # Page metadata
        re.compile(r"^(Last (updated|modified)|Published|Posted)\s*(on|:)", re.I),
        re.compile(r"^Tags?:(\s*[#\w\-,]+\s*)+$", re.I),
        # Empty headings / structure without content
        re.compile(r"^#+\s*$"),                             # bare heading markers
        re.compile(r"^#{1,6}\s*(Example|Examples?|Note|Notes?|Tip|Tips?|Warning|See Also|See also)\s*:?\s*$", re.I),
        re.compile(r"^#{1,6}\s*(Demo|Try it|Exercise|Practice|Test|Challenge|Task)\s*:?\s*$", re.I),
    ]

    @property
    def name(self) -> str:
        return "noise_line_filter"

    async def clean(self, text: str, metadata: dict | None = None) -> str:
        lines = text.split("\n")
        filtered: list[str] = []
        removed = 0
        for line in lines:
            if any(p.search(line) for p in self._NOISE_PATTERNS):
                removed += 1
            else:
                filtered.append(line)
        return "\n".join(filtered)


# ═══════════════════════════════════════════════════════════════
#  Duplicate paragraph deduplicator
# ═══════════════════════════════════════════════════════════════

class DuplicateParagraphDeduplicator(BaseCleaner):
    """Remove consecutive duplicate paragraphs.

    Academic purpose — repeated passages inflate token counts
    and skew embedding similarity; deduplication improves
    retrieval precision.
    """

    @property
    def name(self) -> str:
        return "duplicate_deduplicator"

    async def clean(self, text: str, metadata: dict | None = None) -> str:
        paragraphs = text.split("\n\n")
        deduped: list[str] = []
        seen: set[str] = set()
        for para in paragraphs:
            normalized = para.strip().lower()
            # Only skip if it's an exact repeat of the last paragraph
            if normalized and normalized == (deduped[-1].strip().lower() if deduped else None):
                continue
            deduped.append(para)
        return "\n\n".join(deduped)


# ═══════════════════════════════════════════════════════════════
#  W3Schools navigation stripper
# ═══════════════════════════════════════════════════════════════

class W3SchoolsNavCleaner(BaseCleaner):
    """Strip W3Schools tutorial navigation chrome from scraped markdown.

    W3Schools HTML→MD conversion leaves ~2/3 of each file as navigation:
    top banner / login UI, left sidebar (``## Java Tutorial`` + ``[x](x.asp)``
    link lists), inter-page Previous/Next, and footer boilerplate.

    Strategy: locate the real content start — the first H1 heading
    (``# Java ...``, single ``#``, capitalised) — and drop everything
    before it. Then remove navigation/footer lines that survive inside
    the content region.

    Academic purpose — nav chrome has no semantic content but dominates
    embedding vectors (esp. with title-enhanced indexing), so it must be
    removed before chunking to make retrieval precision measurable.
    """

    # First H1 heading (single '#', capitalised start)
    _H1_RE = re.compile(r"^#\s+[A-Z]")
    # Footer start — everything from here to EOF is nav chrome
    _FOOTER_START_RE = re.compile(r"^(\[?(#####\s+)?)?Get Certified|\[.*Certificate\]\(.*campus\.w3schools", re.I)
    # Navigation lines that appear inside the content region.
    # NB: intra-content references like ``[arrays](java_arrays.asp)`` are
    # legitimate and kept — only chrome lines (bare nav/footer) are dropped.
    _NAV_LINE_RE = [
        re.compile(r"^\[❮ Previous\]\(.*\)\s*$"),                 # prev/next
        re.compile(r"^\[Next ❯\]\(.*\)\s*$"),
        re.compile(r"^\[.*(Previous|Next).*\]\(.*\.asp\)\s*$", re.I),
        re.compile(r"^\[.*Examples\]\(/(html|css|javascript|sql|python|php|jquery|xml|bootstrap|w3css|java)/.*\.asp\)\s*$", re.I),  # sidebar example links
        # Footer / banner chrome (not intra-content references)
        re.compile(r"^W3Schools is Powered by", re.I),
        re.compile(r"^\[?Copyright\s+19\d\d-20\d\d", re.I),
        re.compile(r"^by Refsnes Data\.\s*All Rights Reserved\.", re.I),
        re.compile(r"^\[?terms of use\]?", re.I),
        re.compile(r"^\[?cookies\]?\(\)?\s*$", re.I),
        re.compile(r"^\[?privacy policy\]?", re.I),
        re.compile(r"^\[W3Schools is Powered by W3\.CSS\]", re.I),
        re.compile(r"^Tutorials, references, and examples are constantly reviewed", re.I),
        re.compile(r"^\[(HTML|CSS|JavaScript|SQL|Python|PHP|jQuery|XML|Bootstrap|W3\.CSS|Java|React|Angular|Node\.js|TypeScript|Django|PostgreSQL|Excel|Google Sheets|Machine Learning|R|C|C\+\+|C#|Go|Kotlin|Django|Spring|MySQL|MongoDB|Git|AWS|AI|Data Science|Cybersecurity)\s+Tutorial\]\(/", re.I),  # other-language sidebar links
        re.compile(r"^\[(REMOVE ADS|PLUS|GET CERTIFIED|Get Certified|Sign in to track progress|Sign In|Log In|Register|Login|Upgrade|Academy)\]\(", re.I),
        re.compile(r"^\[(HTML|CSS|JavaScript|SQL|Python|PHP|jQuery|XML|Bootstrap|W3\.CSS|Java|AngularJS)\s+(Reference|Colors?|Examples?|Tutorial)\]\(/", re.I),  # footer reference/example blocks
        re.compile(r"^\[How To (Tutorial|Examples?)\]\(/howto", re.I),
        re.compile(r"^\[(Color Picker|Code Game|Get Certified|HTML Certificate|CSS Certificate|JavaScript Certificate|Front End Certificate|SQL Certificate|Python Certificate|PHP Certificate|jQuery Certificate|Java Certificate|C\+\+ Certificate|C# Certificate|XML Certificate)\]\(", re.I),  # footer cert links
        re.compile(r"^#####\s+Top (References|Examples)\s*$", re.I),  # footer block titles
        re.compile(r"^\[\*\*\]\(//?www\.w3schools\.com\)\s*$", re.I),  # logo link
        re.compile(r"^\[★\s*$", re.I),                                 # star icon line
        re.compile(r"^\[SPACES\]\(.*\)\s*$", re.I),                    # SPACES nav
        re.compile(r"^\[![^\]]*\]\(.*campus\.w3schools.*\)$", re.I),  # banner images
        re.compile(r"^\[?\*?[uf][0-9a-f]{3,5}\*?\]?\(https://(www\.)?(youtube|linkedin|discord|facebook|instagram|tiktok|twitter|x)\.com", re.I),  # social icons
        re.compile(r"^https://(www\.)?(youtube|linkedin|discord|facebook|instagram|tiktok|twitter|x)\.com", re.I),
        re.compile(r"^If you want to (use W3Schools|report an error)", re.I),
        re.compile(r"^send us an e-mail", re.I),
        re.compile(r"^\+1\]\(https://profile\.w3schools", re.I),
    ]

    @property
    def name(self) -> str:
        return "w3schools_nav_stripper"

    async def clean(self, text: str, metadata: dict | None = None) -> str:
        src = (metadata or {}).get("source_file", "") or ""
        # Only applies to W3Schools-sourced Java tutorial docs
        if "_java_" not in src:
            return text

        lines = text.split("\n")

        # 1. Find content start = first H1 heading
        start_idx = None
        for i, line in enumerate(lines):
            if self._H1_RE.match(line):
                start_idx = i
                break
        if start_idx is None:
            return text  # no H1 found — leave untouched (safer)

        # 2. Drop everything before content start
        content = lines[start_idx:]

        # 3. Truncate at footer start (Get Certified / Certificate links)
        cut_idx = len(content)
        for i, line in enumerate(content):
            if self._FOOTER_START_RE.match(line):
                cut_idx = i
                break
        content = content[:cut_idx]

        # 4. Remove nav lines that survive inside content
        filtered = [
            line for line in content
            if not any(p.match(line) for p in self._NAV_LINE_RE)
        ]
        # 5. Drop trailing empty lines (from footer truncation)
        while filtered and not filtered[-1].strip():
            filtered.pop()
        return "\n".join(filtered)

class TrailingWhitespaceRemover(BaseCleaner):
    """Remove trailing whitespace from each line.

    Academic purpose — trailing whitespace is a common artifact
    from PDF and HTML extraction that inflates token counts
    and creates false chunk boundaries.
    """

    _TRAILING_RE = re.compile(r"[ \t]+$", re.MULTILINE)

    @property
    def name(self) -> str:
        return "trailing_whitespace_remover"

    async def clean(self, text: str, metadata: dict | None = None) -> str:
        return self._TRAILING_RE.sub("", text)
