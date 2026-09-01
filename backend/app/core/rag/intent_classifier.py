"""Intent classifier for user queries — two-layer: fast rules + LLM fallback.

Output: "greeting" | "meta" | "tool" | "knowledge" | "clarification"

Used by ChatService to decide whether to run:
  - Tool handler (tool questions: time, date, calculation)
  - Full RAG pipeline (knowledge / clarification)
  - Pure LLM (greeting / meta)

And by QueryStandardizer to choose light vs full processing mode.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING

from app.core.rag.terminology import GREETING_PATTERNS, META_PATTERNS

if TYPE_CHECKING:
    pass


class Intent(StrEnum):
    GREETING = "greeting"            # Social chitchat: hello, thanks, bye
    META = "meta"                    # Questions about the system itself
    TOOL = "tool"                    # Real-time data: time, date, calc, weather
    KNOWLEDGE = "knowledge"          # Programming/technical questions
    CLARIFICATION = "clarification"  # Follow-up on previous answer


# ── Compiled regex patterns (fast path) ─────────────────────────────
_greeting_re = [re.compile(p, re.IGNORECASE) for p in GREETING_PATTERNS]
_meta_re = [re.compile(p, re.IGNORECASE) for p in META_PATTERNS]

# Clarification indicators — short messages that reference prior context
CLARIFICATION_INDICATORS = [
    r"^(什么|啥|哪个|怎么|为什么|为啥|能|可以|能不能|可不可以)",
    r"^(举个例子|举例|比如|例如|具体|详细|展开|再说)",
    r"^(没懂|不明白|不懂|不清楚|没理解|解释一下|再讲|再说一遍)",
    r"^(然后呢|接下来|继续|还有吗|还有呢)",
    r"^(就这|完了|就这样|没了)",
    r"^(不对|不是|错了|有问题|不行|不可以)",
    r"^(上面|前面|刚才|刚刚|之前).*(说|讲|提到|那个|这个)",
    r"^(代码|运行|执行|试试|测试).*",
]
_clarification_re = [re.compile(p, re.IGNORECASE) for p in CLARIFICATION_INDICATORS]

# Programming knowledge indicators — strong signal for knowledge intent
KNOWLEDGE_KEYWORDS = [
    # Chinese — programming concepts
    "python", "代码", "编程", "函数", "变量", "循环", "条件", "异常",
    "错误", "类", "对象", "模块", "导入", "文件", "字符串", "列表",
    "字典", "元组", "集合", "数组", "算法", "数据结构", "数据库",
    "前端", "后端", "框架", "库", "包", "接口", "API", "测试",
    "调试", "部署", "环境", "配置", "版本", "命令行", "终端",
    "怎么写", "怎么用", "如何", "怎样", "什么是", "什么意思",
    "区别", "对比", "比较", "优缺点", "选择", "什么时候",
    "报错", "出错", "不工作", "bug", "问题", "修复", "解决",
    "语法", "用法", "示例", "例子", "教程", "文档",
    "设计模式", "架构", "重构", "优化", "性能",
    # Chinese — protocols, databases, middleware
    "tcp", "http", "https", "redis", "mysql", "sql", "docker",
    "hashmap", "hashmap", "arraylist", "linkedlist", "hashset",
    "线程", "进程", "协程", "锁", "事务", "索引", "缓存",
    "队列", "消息队列", "中间件", "微服务", "分布式",
    "多线程", "线程池", "线程安全", "同步", "异步",
    "jvm", "jdk", "jre", "maven", "gradle", "tomcat",
    "spring", "springboot", "mybatis", "hibernate",
    # Chinese — networking & OS
    "三次握手", "四次挥手", "协议", "网络", "操作系统",
    "内存管理", "垃圾回收", "类加载", "反射",
    "容器", "kubernetes", "k8s", "devops",
    # Chinese — general CS
    "时间复杂度", "空间复杂度", "排序", "查找",
    "快速排序", "归并排序", "冒泡排序", "二分查找", "动态规划",
    "面向对象", "继承", "多态", "封装", "接口", "抽象类",
    # English — tech terms
    "how to", "what is", "why does", "explain", "define",
    "difference between", "compare", "example of", "tutorial",
    "syntax", "usage", "error", "exception", "function", "variable",
    "class", "object", "import", "module", "package", "framework",
    "algorithm", "data structure", "design pattern",
    "thread", "process", "coroutine", "mutex", "deadlock",
    "dependency injection", "ioc", "aop", "rest", "restful",
    "graphql", "websocket", "oauth", "jwt", "nosql",
]
_knowledge_re = re.compile(
    "|".join(re.escape(kw) for kw in sorted(KNOWLEDGE_KEYWORDS, key=len, reverse=True)),
    re.IGNORECASE,
)

# Max length for a clarification (longer messages are likely knowledge)
CLARIFICATION_MAX_LENGTH = 30

# ── Tool intent patterns ───────────────────────────────────────────
# These run before knowledge detection so tool queries don't
# accidentally match broad knowledge keywords.
_TOOL_PATTERNS = [
    # Time / date
    r"(现在|当前|目前)\s*(时间|时候|几点)",
    r"(今天|明天|昨天)\s*(日期|几号|星期|周)",
    r"(时间|日期|年月日)\s*(查询|查看|现在|当前)",
    # Calculator
    r"^\d+\s*[+\-*/×÷]\s*\d+",
    r"(等于|计算结果)",
    r"(加|减|乘|除|乘以|除以|plus|minus|times)",
    r"(多少)\s*(加|减|乘|除|plus|minus|times)",
    # Weather
    r"今天.*(天气|温度|下雨|下雪|刮风)",
    r"(天气|温度|下雨|下雪|刮风|台风|湿度)",
    # Conversion
    r"(换算|转换|转).*(单位|货币|汇率|美元|人民币|欧元|公里|英里|英尺|英寸|厘米|公斤|斤|磅)",
    r"(美元|人民币|欧元|日元|英镑).*(汇率|兑|换|换算|等于多少)",
    r"\d+\s*(公里|千米|米|厘米|毫米|英寸|英尺|公斤|斤|磅).*(多少|等于|换算)",
]
_tool_re = re.compile("|".join(_TOOL_PATTERNS), re.IGNORECASE)


def classify_intent_fast(text: str) -> Intent | None:
    """Fast rule-based intent classification. Returns None if uncertain.

    This runs on every message with near-zero overhead. Only the slow
    LLM path is gated behind uncertainty.
    """
    stripped = text.strip()

    # ── Check greetings ──────────────────────────────────────────
    for pattern in _greeting_re:
        if pattern.search(stripped):
            return Intent.GREETING

    # ── Check meta ───────────────────────────────────────────────
    for pattern in _meta_re:
        if pattern.search(stripped):
            return Intent.META

    # ── Check clarification ──────────────────────────────────────
    # Short messages matching clarification patterns
    if len(stripped) <= CLARIFICATION_MAX_LENGTH:
        is_clarification = False
        for pattern in _clarification_re:
            if pattern.search(stripped):
                is_clarification = True
                break

        if is_clarification:
            # Post-correction: if query also matches knowledge keywords,
            # it's a standalone knowledge question, not a clarification.
            if _knowledge_re.search(stripped):
                return Intent.KNOWLEDGE
            if _tool_re.search(stripped):
                return Intent.TOOL
            return Intent.CLARIFICATION

    # ── Check tool signals (before knowledge, to avoid false matches) ──
    if _tool_re.search(stripped):
        return Intent.TOOL

    # ── Check knowledge signals ──────────────────────────────────
    if _knowledge_re.search(stripped):
        return Intent.KNOWLEDGE

    # ── Heuristic: very short non-greeting → likely clarification ──
    if len(stripped) <= 8:
        return Intent.CLARIFICATION

    # ── Uncertain — needs LLM ────────────────────────────────────
    return None


async def classify_intent_llm(text: str) -> Intent:
    """Use a lightweight LLM call to classify intent when rules are uncertain."""
    from app.llm.factory import get_llm_provider

    llm = get_llm_provider()

    prompt = f"""Classify this user message into exactly one category. Reply with only the category name, nothing else.

Categories:
- greeting: Social chitchat — hello, hi, thanks, bye, how are you, good morning
- meta: Question about the system — what can you do, who are you, help, how to use
- tool: Request for real-time data — current time, date, weather, calculation, unit/currency conversion
- knowledge: Programming/technical question — concepts, syntax, errors, code examples, how-to
- clarification: Follow-up on a previous answer — asking for examples, saying "I don't understand", asking for more detail

User message: "{text}"

Category:"""

    try:
        result = await llm.generate(prompt, system_prompt="You are a classifier. Output only one word.")
        result = result.strip().lower()

        for intent in Intent:
            if intent.value in result:
                return intent

        # If LLM returns something unexpected, check for partial matches
        if any(w in result for w in ["greet", "hello", "hi", "chat", "social"]):
            return Intent.GREETING
        if any(w in result for w in ["meta", "system", "capability", "help"]):
            return Intent.META
        if any(w in result for w in ["tool", "time", "date", "weather", "calc", "convert"]):
            return Intent.TOOL
        if any(w in result for w in ["clarif", "follow", "detail", "example", "explain more"]):
            return Intent.CLARIFICATION

        return Intent.KNOWLEDGE  # default fallback
    except Exception:
        return Intent.KNOWLEDGE  # safe default on error


async def classify_intent(
    text: str,
    conversation_history: list[dict] | None = None,
) -> Intent:
    """Full intent classification: fast rules first, LLM fallback.

    Args:
        text: The user's current message.
        conversation_history: Recent messages for context (used to
            upgrade CLARIFICATION when prior context is thin).

    Returns:
        Classified intent.
    """
    # ── Layer 1: Fast rule-based ──────────────────────────────────
    intent = classify_intent_fast(text)
    if intent is not None:
        return intent

    # ── Layer 2: LLM fallback ─────────────────────────────────────
    intent = await classify_intent_llm(text)

    # ── Post-correction: upgrade CLARIFICATION → KNOWLEDGE ────────
    # If there's no conversation history to clarify against, a short
    # ambiguous message is more likely a standalone knowledge question.
    if intent == Intent.CLARIFICATION:
        has_prior_context = (
            conversation_history is not None
            and len(conversation_history) >= 2  # at least one exchange
        )
        if not has_prior_context:
            # First message in a conversation — can't be a clarification
            return Intent.KNOWLEDGE

    return intent


def is_rag_needed(intent: Intent, kb_id: str | None) -> bool:
    """Determine if full RAG pipeline should run based on intent and KB availability.

    Returns ``False`` for tool, greeting, and meta intents — those should
    either be handled by a tool handler or by pure LLM.
    """
    if not kb_id:
        return False
    if intent == Intent.TOOL:
        return False
    return intent in (Intent.KNOWLEDGE, Intent.CLARIFICATION)
