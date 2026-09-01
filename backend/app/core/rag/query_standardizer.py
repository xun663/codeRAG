"""Query Standardizer — five-stage pipeline for transforming raw user input
into retrieval-optimized queries.

Stages:
  ① Context Resolution   — pronoun/entity resolution from conversation history
  ② Text Cleaning         — rule-based normalization (always on)
  ③ Query Rewriting       — LLM: colloquial → formal, term normalization (core)

    ╔══════════════════════════════════════════════════════════════════╗
    ║  Dynamic decision:                                             ║
    ║                                                                ║
    ║  ┌─ Retrieval-ready query (clear tech terms, no pronouns)      ║
    ║  │  → Skip LLM entirely. Use cleaned text as rewrite.          ║
    ║  │                                                             ║
    ║  └─ Vague / pronominal / open-ended query                      ║
    ║     → One merged LLM call: rewrite + keywords + sub-queries.   ║
    ║                                                                ║
    ║  Before: up to 3 LLM calls per query.                         ║
    ║  After:  0 calls (simple) or 1 call (complex).                ║
    ╚══════════════════════════════════════════════════════════════════╝
  ④ Query Expansion       — terminology table + LLM (merged into ③)
  ⑤ Multi-Query Generation — angle-diverse queries (merged into ③)

Modes:
  - Light: ② only (greeting / meta / short clarification)
  - Full:  ① → ② → (③+④+⑤ merged)  (knowledge / longer clarification)
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field

from app.core.rag.intent_classifier import KNOWLEDGE_KEYWORDS
from app.core.rag.terminology import expand_keywords, normalize_term


@dataclass
class StandardizationResult:
    """Container for standardization output."""

    original: str
    cleaned: str = ""
    rewritten: str = ""          # Primary retrieval query (stage ③ output)
    expanded_keywords: list[str] = field(default_factory=list)
    sub_queries: list[str] = field(default_factory=list)  # Stage ⑤ outputs
    used_llm: bool = False       # Whether LLM was called during processing
    fast_path: bool = False      # Whether the fast path was taken

    @property
    def primary_query(self) -> str:
        """The main query to use for vector retrieval."""
        return self.rewritten or self.cleaned

    @property
    def all_queries(self) -> list[str]:
        """All queries (primary + sub) for multi-vector retrieval."""
        queries = [self.primary_query]
        queries.extend(self.sub_queries)
        return queries


class QueryStandardizer:
    """Five-stage query standardization pipeline.

    Usage:
        standardizer = QueryStandardizer()
        result = await standardizer.process(
            query="那它咋用啊",
            history=[...],
            intent=Intent.KNOWLEDGE,
        )
        # result.primary_query → "元组 tuple 如何使用 创建 访问 方法"
        # result.all_queries → [primary, sub_query_1, sub_query_2]
    """

    # ── Stage ②: Text Cleaning (always on) ────────────────────────

    # Noise words to strip from beginning/end of messages
    _NOISE_PREFIXES = [
        r"^(嗯|呃|啊|哦|噢|那个|这个|就是|就是说|我想问|我想知道|请问一下|问一下|问个问题)",
        r"^(um+|uh+|er+|hmm+|well,?\s|so,?\s|like,?\s)",
        r"^(那个啥|那个什么|内个|那啥)",
    ]
    _NOISE_SUFFIXES = [
        r"(谢谢|感谢|多谢|3q|thanks?|thank\s?you)\s*$",
        r"(啊|吧|吗|呢|嘛|呗|呐|哦|噢|咯|啦|呀|哈)\s*$",
        r"(可以吗|行吗|对吗|好吗|OK吗|可以么|行么)\s*$",
    ]
    _NOISE_PREFIX_RE = re.compile("|".join(_NOISE_PREFIXES), re.IGNORECASE)
    _NOISE_SUFFIX_RE = re.compile("|".join(_NOISE_SUFFIXES), re.IGNORECASE)

    # Punctuation normalization (single-char replacements only for str.maketrans)
    _PUNCT_MAP = str.maketrans({
        "？": "?", "！": "!", "，": ",", "。": ".", "；": ";", "：": ":",
        "（": "(", "）": ")", "【": "[", "】": "]", "《": "<", "》": ">",
        "＂": '"', "＇": "'", "～": "~", "％": "%", "＠": "@", "＃": "#",
        "＆": "&", "＊": "*", "＋": "+", "－": "-", "／": "/", "＝": "=",
    })
    # Fullwidth common words — handled separately since maketrans is single-char only
    _FULLWIDTH_WORDS = {
        "ｐｙｔｈｏｎ": "python",
        "ＰＹＴＨＯＮ": "python",
    }
    _MULTI_SPACE_RE = re.compile(r"\s{2,}")
    _MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
    _CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

    def _clean_text(self, text: str) -> str:
        """Stage ②: Rule-based text cleaning. Zero LLM overhead."""
        cleaned = text.strip()

        # Strip noise prefixes/suffixes
        cleaned = self._NOISE_PREFIX_RE.sub("", cleaned).strip()
        cleaned = self._NOISE_SUFFIX_RE.sub("", cleaned).strip()

        # Normalize fullwidth → halfwidth punctuation
        cleaned = cleaned.translate(self._PUNCT_MAP)

        # Normalize fullwidth common words
        for fw, hw in self._FULLWIDTH_WORDS.items():
            cleaned = cleaned.replace(fw, hw)

        # Remove control characters (except newline, tab)
        cleaned = self._CONTROL_CHAR_RE.sub("", cleaned)

        # Collapse whitespace
        cleaned = self._MULTI_SPACE_RE.sub(" ", cleaned)
        cleaned = self._MULTI_NEWLINE_RE.sub("\n\n", cleaned)

        # Truncate excessively long queries
        if len(cleaned) > 512:
            cleaned = cleaned[:512]

        # If cleaning removed everything, return original
        return cleaned if cleaned else text.strip()

    # ── Stage ①: Context Resolution ───────────────────────────────

    _PRONOUN_PATTERNS = [
        (r"\b(它|他|她|这个|那个|这些|那些|其|该)\b", "entity"),
        (r"\b(这样|那样|这么|那么|这般|那般)\b", "manner"),
        (r"\b(上面|前面|以上|上述|之前|刚才|刚刚)\b", "prior_reference"),
        (r"\b(下面|以下|后面|之后)\b", "subsequent"),
    ]
    _PRONOUN_RE = re.compile(
        "|".join(f"({p})" for p, _ in _PRONOUN_PATTERNS), re.IGNORECASE
    )

    @staticmethod
    def _extract_entities_from_history(history: list[dict]) -> list[str]:
        """Extract key technical terms from recent conversation history.

        Looks at the last 3 assistant messages' content for capitalized terms,
        code blocks, and explicitly mentioned Python concepts.
        """
        entities = []
        # Simple heuristic: find terms that look like programming concepts
        code_term_re = re.compile(
            r"\b(tuple|list|dict|set|str|int|float|bool|class|def|"
            r"function|module|package|import|lambda|decorator|generator|"
            r"coroutine|async|await|thread|process|exception|error|"
            r"for|while|if|else|elif|with|try|except|raise|yield|return|"
            r"元组|列表|字典|集合|字符串|函数|类|模块|异常|循环|条件|"
            r"装饰器|生成器|协程|异步|线程|进程|变量|参数|返回值)\b",
            re.IGNORECASE,
        )

        for msg in history[-6:]:
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                found = code_term_re.findall(content)
                entities.extend(found)

        # Also extract from user's prior messages
        for msg in history[-6:]:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                found = code_term_re.findall(content)
                entities.extend(found)

        # Deduplicate, keep order, take last 5
        seen = set()
        unique = []
        for e in reversed(entities):
            if e.lower() not in seen:
                seen.add(e.lower())
                unique.append(e)
            if len(unique) >= 5:
                break
        return list(reversed(unique))

    def _resolve_context(
        self, query: str, history: list[dict] | None
    ) -> str:
        """Stage ①: Resolve pronouns and references from conversation history."""
        if not history:
            return query

        # Check if query has any pronoun/reference
        if not self._PRONOUN_RE.search(query):
            return query

        entities = self._extract_entities_from_history(history)
        if not entities:
            return query

        # Simple entity injection: prepend the most likely entity
        # For "它怎么用" → entity = last mentioned concept
        primary = entities[0] if entities else ""

        # Build resolved query based on pronoun type
        resolved = query

        # "它/他/她/这个/那个" → replace with entity name
        resolved = re.sub(
            r"\b(它|他|她|这个|那个|这些|那些)\b",
            primary if primary else r"\1",
            resolved,
        )

        # If no replacement happened but pronouns exist, prepend context
        if resolved == query and primary:
            resolved = f"{primary} {query}"

        return resolved

    # ── Fast-path heuristic ────────────────────────────────────────
    #
    # NOTE: \b (word boundary) does NOT work correctly with CJK characters
    # in Python's re module. CJK chars are \w so \b between two CJK chars
    # never matches. We use lookarounds or simpler substring checks instead.
    _PRONOUN_CHECK_RE = re.compile(
        r"(?:^|(?<=[\s（(]))(它|他|她|这个|那个|这些|那些|其|该|这样|那样|这么|那么)\s*(怎么|如何|是|有|能|会|可以|为什么)",
    )
    # Also check for standalone pronouns in CJK context (no preceding word boundary)
    _CJK_PRONOUN_RE = re.compile(
        r"(它|他|她|这个|那个|这些|那些|其|该|这样|那样)",
    )
    # Patterns that strongly suggest an open-ended analysis request
    _OPEN_ENDED_RE = re.compile(
        r"(分析|评价|比较|对比|说说|谈谈|看法|建议|你觉得|你认为|如何看|怎么看待|"
        r"有什么(建议|想法|意见|方法|方案)|哪个好|选哪个|举个)",
    )
    # Queries that are too short/incomplete for stand-alone retrieval
    _INCOMPLETE_RE = re.compile(
        r"^(什么|啥|哪个|怎么|为什么|为啥|哪一[个种]|好不好|能不能|会不会|"
        r"可不可以|多少钱|多久|多大|多少|谁|哪里|何时|为何)$",
    )
    # Second-person address — "你" (you) referencing the assistant
    # Also match bare "你" in CJK context (where \b doesn't help)
    _SECOND_PERSON_RE = re.compile(r"(你|您)")

    @staticmethod
    def _compile_tech_keywords() -> re.Pattern:
        """Compile KNOWLEDGE_KEYWORDS into a single pattern for fast matching."""
        # Filter to only meaningful technical terms (skip generic stopword-like entries)
        tech_terms = []
        for kw in sorted(KNOWLEDGE_KEYWORDS, key=len, reverse=True):
            # Skip very generic words that aren't specific technical signals
            if kw.strip().lower() in ("怎么", "如何", "怎样", "为什么", "什么", "什么时候", "怎么写", "怎么用"):
                continue
            tech_terms.append(re.escape(kw))
        return re.compile("|".join(tech_terms), re.IGNORECASE)

    _TECH_KEYWORD_RE = _compile_tech_keywords()

    def _is_already_retrieval_ready(self, query: str, history: list[dict] | None = None) -> bool:
        """Determine whether a query is already suitable for direct retrieval
        without LLM rewriting.

        A query is considered **retrieval-ready** when ALL of the following hold:

        1. Contains specific technical keywords (编程语言/框架/概念名).
        2. No unresolved pronouns / referring expressions.
        3. Not an open-ended analysis request.
        4. Not a second-person query (asking "you" = assistant).
        5. The query has minimal completeness (not a sentence fragment).
        6. Has conversation-independent meaning (no history-dependent references).
        """
        q = query.strip()

        # ── Rule 0: Empty / very short queries never qualify ──────
        if len(q) < 6:
            return False

        # ── Rule 1: Must contain at least one specific technical term ──
        # This is the *primary* signal — without tech keywords there's no
        # point searching the KB directly.
        if not self._TECH_KEYWORD_RE.search(q):
            return False

        # ── Rule 2: Must NOT have unresolved pronouns ──────────────
        # Check both ASCII-boundary pattern and CJK-substring pattern
        if self._PRONOUN_CHECK_RE.search(q):
            return False
        if self._CJK_PRONOUN_RE.search(q):
            # "这个" / "那个" in CJK context without word boundary
            return False

        # ── Rule 3: Must NOT be an open-ended analysis request ─────
        if self._OPEN_ENDED_RE.search(q):
            return False

        # ── Rule 4: Must NOT be addressing the assistant ───────────
        # Queries like "你帮我分析一下这个代码" need context understanding.
        if self._SECOND_PERSON_RE.search(q):
            return False

        # ── Rule 4b: Must NOT start with generic question words
        # where the only tech match is a generic performance attribute.
        # "为什么这样写性能不好" — "性能" is too generic alone.
        # "有什么好的优化方案" — vague request, needs LLM understanding.
        # "能不能举个实际的例子" — depends on context.
        _GENERIC_QUESTION_START = re.compile(
            r"^(为什么|怎么|如何|哪个|什么|怎样|有啥|为啥|好不好|能不能|会不会|可不可以|有没有|是不是|有什么)",
        )
        _GENERIC_TECH_ONLY = re.compile(
            r"^(?!.*?(?:python|java|redis|mysql|tcp|http|docker|"
            r"线程|进程|协程|锁|事务|索引|缓存|算法|数据结构|"
            r"协议|网络|操作系统|框架|库|类|对象|函数|接口))",
        )
        start_match = _GENERIC_QUESTION_START.match(q)
        if start_match:
            # Only flag if the query is a "why/how" about a generic concept,
            # not a specific named technology.
            if len(q) < 60 and not re.search(
                r"(python|java|redis|mysql|tcp|http|docker|线程|进程|"
                r"协程|锁|事务|索引|缓存|算法|数据结构|协议|网络|"
                r"操作系统|框架|库|类|对象|函数|接口|hashmap|jvm|"
                r"spring|docker|kubernetes)",
                q, re.IGNORECASE,
            ):
                return False

        # ── Rule 5: Must NOT be an incomplete fragment ─────────────
        if self._INCOMPLETE_RE.match(q):
            return False

        # ── Rule 6: Check for history-dependent context ────────────
        # If there's conversation history and the query references
        # prior context patterns like "上面", "刚才", pass through.
        if history and len(history) >= 2:
            prior_ref = re.search(r"(上面|前面|刚才|之前|上述)", q)
            if prior_ref:
                return False

        # All checks passed — query is retrieval-ready.
        return True

    # ── Stage ③+④+⑤: Merged LLM processing (single call) ────────

    _MERGED_SYSTEM_PROMPT = """\
You are a search query optimizer for a programming documentation knowledge base. \
Given a user's raw question, produce a structured JSON output with three fields:

{
  "rewritten_query": "Clean, formal, self-contained query string suitable for vector search.",
  "keywords": ["term1", "term2", "term3"],
  "sub_queries": ["Alternative angle 1", "Alternative angle 2"]
}

RULES:
1. **rewritten_query**: Convert colloquial/spoken expressions to formal written language. \
Add bilingual term equivalents (e.g. "列表" ↔ "list"). Remove filler. Preserve code snippets. \
If the query is already clean, return it mostly unchanged with minor normalization.
   Max 100 characters.

2. **keywords**: 3-5 related technical keywords or synonyms that would help \
expand recall. Include both Chinese and English variants. \
   Example: ["tuple", "元组", "immutable", "序列类型", "不可变序列"]

3. **sub_queries**: 0-2 alternative phrasings of the same information need from \
different angles. Only generate when the query has multiple facets or is ambiguous. \
   Example for "Python列表和元组的区别":
     ["列表 list 可变序列 增删改操作", "元组 tuple 不可变序列 使用场景"]

IMPORTANT: Output ONLY valid JSON. No markdown, no explanation, no extra text."""

    _MERGED_USER_TEMPLATE = 'Raw question: "{query}"\n\nJSON output:'

    async def _process_complex_query(self, query: str) -> dict:
        """Stage ③+④+⑤ merged: one LLM call that returns rewrite, keywords, and sub-queries.

        Returns:
            dict with keys: rewritten_query, keywords, sub_queries
            Falls back to query-as-is + empty lists on any error.
        """
        from app.llm.factory import get_llm_provider

        llm = get_llm_provider()
        prompt = self._MERGED_USER_TEMPLATE.format(query=query)

        try:
            result = await llm.generate(
                prompt=prompt,
                system_prompt=self._MERGED_SYSTEM_PROMPT,
                max_tokens=300,       # keep it cheap — 300 tokens is plenty
                temperature=0.1,       # low temperature for deterministic output
            )

            # Parse JSON from the response (handle possible markdown fences)
            cleaned = result.strip()
            if cleaned.startswith("```"):
                # Strip markdown code fences
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                cleaned = re.sub(r"\s*```$", "", cleaned)

            parsed = json.loads(cleaned)
            return {
                "rewritten_query": parsed.get("rewritten_query", query)[:200],
                "keywords": parsed.get("keywords", [])[:8],
                "sub_queries": parsed.get("sub_queries", [])[:3],
            }
        except Exception:
            # Graceful fallback: return original query with empty expansions
            return {
                "rewritten_query": query,
                "keywords": [],
                "sub_queries": [],
            }

    # ── Legacy single-stage prompts (kept for reference, no longer called) ──

    _REWRITE_SYSTEM_PROMPT = """\
You are a query rewriter. Your task is to transform colloquial, informal, or \
incomplete user questions into clean, formal, self-contained retrieval queries \
suitable for searching a programming documentation knowledge base.

RULES:
1. Convert colloquial/spoken expressions to formal written language.
   - "咋整" → "如何使用", "搞不懂" → "不理解", "这玩意儿" → use the actual concept name
2. Add missing Chinese/English term equivalents.
   - If the user says "list", also include "列表"
   - If the user says "元组", also include "tuple"
3. If the query contains code snippets (e.g. `for i in range(10)`), keep the \
code but describe its purpose in words.
4. Remove filler, politeness, and meta-commentary.
   - "请问一下..." → remove the prefix
   - "谢谢" → remove
5. Output ONLY the rewritten query — no explanation, no markdown, no quotes.
6. If the original query is already a clean, well-formed retrieval query, \
return it unchanged.
7. Keep the query concise (1-2 sentences max)."""

    _REWRITE_USER_TEMPLATE = 'Original: "{query}"\n\nRewritten query:'

    async def _rewrite_query(self, query: str) -> str:
        """Stage ③: LLM-based query rewriting.

        NOTE: Only called when the fast-path heuristic is inconclusive
        and ``_process_complex_query`` is used instead for the merged flow.
        This method is kept for backward compatibility / testing.
        """
        from app.llm.factory import get_llm_provider

        llm = get_llm_provider()
        prompt = self._REWRITE_USER_TEMPLATE.format(query=query)

        try:
            rewritten = await llm.generate(
                prompt=prompt,
                system_prompt=self._REWRITE_SYSTEM_PROMPT,
            )
            rewritten = rewritten.strip().strip('"').strip("'")
            # If LLM returns empty or just noise, keep original
            if not rewritten or len(rewritten) < 3:
                return query
            return rewritten
        except Exception:
            return query

    # ── Stage ④: Query Expansion ──────────────────────────────────

    _EXPAND_SYSTEM_PROMPT = """\
You are a search query expander for a Python programming knowledge base. \
Given a query, output 3-5 related keywords or short phrases that would help \
find relevant documentation. Output only the keywords separated by commas, \
no explanation.

Example:
Query: "元组和列表的区别"
Output: 不可变, mutable, 序列类型, 性能对比, 使用场景"""

    _MIN_LENGTH_FOR_EXPANSION = 15  # chars — shorter queries get expansion

    def _expand_query(self, query: str) -> list[str]:
        """Stage ④: Expand query with related terminology.

        First uses the terminology table (fast), then optionally LLM.
        """
        # Layer 1: Terminology table lookup
        table_keywords = expand_keywords(query, max_keywords=5)

        # If table found enough keywords, return immediately
        if len(table_keywords) >= 3:
            return table_keywords

        # Layer 2: LLM expansion only for short/ambiguous queries
        if len(query) <= self._MIN_LENGTH_FOR_EXPANSION:
            return table_keywords  # LLM expansion is async — skip in sync path

        return table_keywords  # Base version: table only; LLM expansion optional

    async def _expand_query_llm(self, query: str) -> list[str]:
        """Stage ④ LLM path: generate additional keywords.

        NOTE: In the merged flow this is handled by ``_process_complex_query``.
        This method is kept for backward compatibility / testing.
        """
        from app.llm.factory import get_llm_provider

        llm = get_llm_provider()
        try:
            result = await llm.generate(
                prompt=f'Query: "{query}"\nKeywords:',
                system_prompt=self._EXPAND_SYSTEM_PROMPT,
            )
            keywords = [k.strip() for k in result.split(",") if k.strip()]
            return keywords[:5]
        except Exception:
            return []

    # ── Stage ⑤: Multi-Query Generation ──────────────────────────

    _MULTI_QUERY_SYSTEM_PROMPT = """\
Generate 2 alternative search queries for the same information need, from \
different angles. Output each query on a new line, no numbering, no explanation.

Example:
Original: "Python元组和列表的区别"
不可变序列 tuple 的特性 和使用场景
可变序列 list 的修改操作方法"""

    async def _generate_sub_queries(self, query: str) -> list[str]:
        """Stage ⑤: Generate angle-diverse sub-queries for multi-vector retrieval.

        NOTE: In the merged flow this is handled by ``_process_complex_query``.
        This method is kept for backward compatibility / testing.
        """
        from app.llm.factory import get_llm_provider

        llm = get_llm_provider()
        try:
            result = await llm.generate(
                prompt=f'Original: "{query}"',
                system_prompt=self._MULTI_QUERY_SYSTEM_PROMPT,
            )
            lines = [line.strip() for line in result.split("\n") if line.strip()]
            # Filter out lines that are too short or just numbers
            sub_queries = [
                re.sub(r"^\d+[\.\)]\s*", "", line)
                for line in lines
                if len(line) > 5
            ]
            return sub_queries[:3]
        except Exception:
            return []

    # ── Main pipeline entry ───────────────────────────────────────

    async def process(
        self,
        query: str,
        history: list[dict] | None = None,
        intent: Intent = None,  # type: ignore  # imported below to avoid circular
    ) -> StandardizationResult:
        """Process a raw user query through the standardization pipeline.

        Args:
            query: The raw user input.
            history: Recent conversation messages for context resolution.
            intent: Classified intent — determines light vs full mode.

        Returns:
            StandardizationResult with cleaned/rewritten/expanded queries.
        """
        # Deferred import to avoid circular dependency at module level
        from app.core.rag.intent_classifier import Intent as _Intent
        if intent is None:
            intent = _Intent.KNOWLEDGE

        result = StandardizationResult(original=query)

        # ── Light mode: greeting / meta → clean only ───────────────
        if intent in (_Intent.GREETING, _Intent.META):
            result.cleaned = self._clean_text(query)
            result.fast_path = True
            return result

        # ── Full mode: knowledge / clarification ──────────────────

        # Stage ①: Context Resolution
        resolved = self._resolve_context(query, history)

        # Stage ②: Text Cleaning
        result.cleaned = self._clean_text(resolved)

        # Normalize known abbreviations
        result.cleaned = normalize_term(result.cleaned)

        # ── Dynamic decision: fast path vs. LLM path ───────────────
        #
        #         ┌──────────────────────────────────────┐
        #         │  _is_already_retrieval_ready()        │
        #         │  • Has tech keywords                  │
        #         │  • No pronouns                        │
        #         │  • Not open-ended                     │
        #         │  • Not incomplete                     │
        #         └────────────┬─────────────────────────┘
        #                      │
        #          ┌───────────┴───────────┐
        #          │ YES                   │ NO
        #          ▼                       ▼
        #   ┌──────────────┐    ┌──────────────────────┐
        #   │ Fast path    │    │ Merged LLM (1 call)  │
        #   │ Skip LLM     │    │ rewrite + keywords   │
        #   │ cleaned=     │    │ + sub_queries        │
        #   │ rewritten    │    └──────────────────────┘
        #   └──────────────┘
        #

        if self._is_already_retrieval_ready(result.cleaned, history):
            # ── Fast path: no LLM needed ──────────────────────────
            result.rewritten = result.cleaned
            result.used_llm = False
            result.fast_path = True

            # Still do terminology table expansion (zero LLM cost)
            table_kw = self._expand_query(result.primary_query)
            result.expanded_keywords = list(dict.fromkeys(table_kw))[:8]

            # Append expanded keywords to the rewritten query for better recall
            if result.expanded_keywords:
                new_kw = [kw for kw in result.expanded_keywords[:5]
                          if kw.lower() not in result.rewritten.lower()]
                if new_kw:
                    result.rewritten = f"{result.rewritten} {' '.join(new_kw)}"

        else:
            # ── Complex query: one merged LLM call ────────────────
            result.used_llm = True
            result.fast_path = False

            merged = await self._process_complex_query(result.cleaned)

            result.rewritten = merged.get("rewritten_query", result.cleaned)
            result.expanded_keywords = merged.get("keywords", [])
            result.sub_queries = merged.get("sub_queries", [])

        return result


# ── Singleton ──────────────────────────────────────────────────────
_standardizer: QueryStandardizer | None = None


def get_query_standardizer() -> QueryStandardizer:
    """Get the singleton QueryStandardizer instance."""
    global _standardizer
    if _standardizer is None:
        _standardizer = QueryStandardizer()
    return _standardizer
