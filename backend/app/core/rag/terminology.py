"""Python terminology table — Chinese-English mappings and synonym expansion.

Used by QueryStandardizer stage ④ (Query Expansion) to supplement short queries
with related terms, improving recall without an extra LLM call.
"""

from __future__ import annotations

# ── Core concept mappings ──────────────────────────────────────────
# Format: "canonical_key" → {"en": [...], "zh": [...], "related": [...]}
# - en: English forms (preferred in code documents)
# - zh: Chinese forms
# - related: semantically related concepts for expansion

PYTHON_TERMINOLOGY: dict[str, dict[str, list[str]]] = {
    # ── Data Types ──
    "元组": {
        "en": ["tuple"],
        "zh": ["元组"],
        "related": ["不可变序列", "打包", "解包", "immutable", "packing", "unpacking"],
    },
    "列表": {
        "en": ["list"],
        "zh": ["列表", "数组"],
        "related": ["可变序列", "append", "pop", "切片", "索引", "mutable"],
    },
    "字典": {
        "en": ["dict", "dictionary"],
        "zh": ["字典", "映射"],
        "related": ["key", "value", "键值对", "hash", "items", "keys"],
    },
    "集合": {
        "en": ["set"],
        "zh": ["集合"],
        "related": ["frozenset", "去重", "交集", "并集", "差集", "hash"],
    },
    "字符串": {
        "en": ["str", "string"],
        "zh": ["字符串", "文本"],
        "related": ["format", "f-string", "切片", "join", "split", "encode"],
    },
    "数字": {
        "en": ["int", "float", "complex", "number"],
        "zh": ["数字", "整数", "浮点数", "复数"],
        "related": ["decimal", "运算", "算术", "类型转换"],
    },
    "布尔": {
        "en": ["bool", "boolean"],
        "zh": ["布尔", "真假"],
        "related": ["True", "False", "逻辑运算", "比较"],
    },
    "None": {
        "en": ["None", "null"],
        "zh": ["空值", "None"],
        "related": ["is None", "判空", "默认值"],
    },

    # ── Data Types (compound term for CJK matching safety) ──
    # NOTE: Must appear BEFORE "类" to prevent "数据类型" from matching
    # the "类" (class/OOP) entry via CJK substring matching.
    "数据类型": {
        "en": ["data type", "type system"],
        "zh": ["数据类型"],
        "related": ["int", "float", "str", "list", "dict", "tuple", "set",
                     "数字", "字符串", "列表", "元组", "字典", "集合", "布尔",
                     "序列", "映射", "类型转换", "type", "可变", "不可变",
                     "mutable", "immutable"],
    },

    # ── Control Flow ──
    "循环": {
        "en": ["loop", "for", "while"],
        "zh": ["循环", "遍历"],
        "related": ["迭代", "break", "continue", "range", "enumerate", "迭代器"],
    },
    "条件": {
        "en": ["if", "elif", "else", "conditional"],
        "zh": ["条件", "判断", "分支"],
        "related": ["match", "switch", "三元运算符", "布尔表达式"],
    },
    "异常": {
        "en": ["exception", "error", "try", "except", "raise"],
        "zh": ["异常", "错误", "异常处理"],
        "related": ["finally", "traceback", "自定义异常", "AssertionError", "with"],
    },
    "上下文管理器": {
        "en": ["context manager", "with statement"],
        "zh": ["上下文管理器", "with语句"],
        "related": ["__enter__", "__exit__", "资源管理", "文件操作"],
    },

    # ── Functions ──
    "函数": {
        "en": ["function", "def"],
        "zh": ["函数", "方法"],
        "related": ["参数", "返回值", "lambda", "装饰器", "作用域", "闭包"],
    },
    "参数": {
        "en": ["argument", "parameter", "arg", "kwargs"],
        "zh": ["参数", "实参", "形参"],
        "related": ["默认参数", "关键字参数", "可变参数", "解包", "*args", "**kwargs"],
    },
    "lambda": {
        "en": ["lambda", "anonymous function"],
        "zh": ["lambda", "匿名函数"],
        "related": ["一行函数", "高阶函数", "map", "filter", "sort key"],
    },
    "装饰器": {
        "en": ["decorator", "@"],
        "zh": ["装饰器", "注解"],
        "related": ["@property", "@staticmethod", "@classmethod", "wraps", "闭包"],
    },
    "生成器": {
        "en": ["generator", "yield"],
        "zh": ["生成器", "yield"],
        "related": ["迭代器", "惰性求值", "send", "协程", "generator expression"],
    },
    "递归": {
        "en": ["recursion", "recursive"],
        "zh": ["递归"],
        "related": ["基线条件", "栈溢出", "尾递归", "分治"],
    },

    # ── OOP ──
    "类": {
        "en": ["class", "object", "OOP"],
        "zh": ["类", "对象", "面向对象"],
        "related": ["继承", "多态", "封装", "__init__", "self", "实例", "属性"],
    },
    "继承": {
        "en": ["inheritance", "subclass", "super"],
        "zh": ["继承", "子类", "父类"],
        "related": ["多继承", "MRO", "方法重写", "isinstance", "抽象类"],
    },
    "魔术方法": {
        "en": ["dunder", "magic method", "special method"],
        "zh": ["魔术方法", "双下划线方法"],
        "related": ["__init__", "__str__", "__repr__", "__eq__", "__getitem__", "__len__"],
    },

    # ── Common Patterns / Modules ──
    "列表推导式": {
        "en": ["list comprehension"],
        "zh": ["列表推导式", "列表生成式"],
        "related": ["推导式", "生成器表达式", "字典推导式", "集合推导式", "for"],
    },
    "切片": {
        "en": ["slice", "slicing"],
        "zh": ["切片", "截取"],
        "related": ["索引", "步长", "start:stop:step", "[::-1]"],
    },
    "import": {
        "en": ["import", "module", "package"],
        "zh": ["导入", "模块", "包"],
        "related": ["from import", "as", "pip", "venv", "sys.path"],
    },
    "文件操作": {
        "en": ["file", "open", "read", "write"],
        "zh": ["文件", "读写"],
        "related": ["with open", "路径", "csv", "json", "编码", "二进制"],
    },
    "正则表达式": {
        "en": ["regex", "regular expression", "re"],
        "zh": ["正则", "正则表达式"],
        "related": ["match", "search", "pattern", "替换", "提取"],
    },
    "多线程": {
        "en": ["threading", "thread", "GIL"],
        "zh": ["线程", "多线程"],
        "related": ["并发", "锁", "Queue", "asyncio", "协程", "进程"],
    },
    "异步": {
        "en": ["async", "await", "asyncio", "coroutine"],
        "zh": ["异步", "协程"],
        "related": ["事件循环", "Future", "Task", "并发", "非阻塞"],
    },

    # ── Operations ──
    "赋值": {
        "en": ["assignment", "="],
        "zh": ["赋值", "等于"],
        "related": ["变量", "类型推断", "多重赋值", "解包赋值", "walrus :="],
    },
    "比较": {
        "en": ["comparison", "==", "is"],
        "zh": ["比较", "相等"],
        "related": ["is vs ==", "大于", "小于", "布尔"],
    },
    "类型转换": {
        "en": ["type conversion", "cast", "int()", "str()"],
        "zh": ["类型转换", "转型"],
        "related": ["显式转换", "隐式转换", "isinstance", "鸭子类型"],
    },
    "打印输出": {
        "en": ["print", "output", "stdout"],
        "zh": ["打印", "输出", "显示"],
        "related": ["format", "f-string", "日志", "logging"],
    },
}

# ── Greeting / meta patterns (for intent classifier) ───────────────
GREETING_PATTERNS: list[str] = [
    r"^(hi|hey|hello|yo|sup|hola|heya)([\s!,\.]|$)",
    r"^(你好|您好|嗨|喂|哈喽|早|晚上好|下午好|各位好)",
    r"^(good\s)?(morning|afternoon|evening|night)",
    r"^(bye|goodbye|see\s?you|88|拜拜|再见|回见)",
    r"^(thanks?|thank\s?you|thx|谢谢|多谢|感谢|3q)",
    r"^say\s+(hi|hello|hey|bye)",
    r"^(ok|okay|好的|收到|明白了|知道了|嗯嗯|哦哦)\s*$",
    r"^(how\s+are\s+you|你怎么样|最近如何)",
]

META_PATTERNS: list[str] = [
    r"(你能做什么|你可以做什么|你能干嘛|what\s+can\s+you\s+do)",
    r"(你是谁|你叫什么|who\s+are\s+you|你是什么)",
    r"(怎么用你|如何使用|how\s+to\s+use|help|帮助|使用说明)",
    r"(你支持什么|你有哪些功能|你有什么能力)",
    r"(你是谁开发的|谁做的|谁创造了你)",
]

# ── Query expansion helper ─────────────────────────────────────────

def expand_keywords(query: str, max_keywords: int = 5) -> list[str]:
    """Match query against terminology table and return related keywords.

    Returns up to `max_keywords` related terms not already present in the query.

    NOTE: Keys are matched by longest-first length to avoid CJK substring traps
    where a shorter term (e.g. "类") is accidentally matched inside a longer
    compound word (e.g. "数据类型").  Longer keys are checked first so that
    "数据类型" claims the match before "类" can.
    """
    query_lower = query.lower()
    found: list[str] = []

    # Sort keys by length descending: longest-first for CJK safety
    sorted_keys = sorted(PYTHON_TERMINOLOGY, key=len, reverse=True)
    for key in sorted_keys:
        mapping = PYTHON_TERMINOLOGY[key]
        # Check if any form of this term appears in the query
        all_forms = mapping["en"] + mapping["zh"] + [key]
        if any(form.lower() in query_lower for form in all_forms):
            # Collect related terms not already in query
            for term in mapping["related"]:
                if term.lower() not in query_lower and term not in found:
                    found.append(term)
                    if len(found) >= max_keywords:
                        return found
            # Also add English terms if query uses Chinese (and vice versa)
            if any(zh in query for zh in mapping["zh"]):
                for en_term in mapping["en"][:2]:
                    if en_term.lower() not in query_lower and en_term not in found:
                        found.append(en_term)
                        if len(found) >= max_keywords:
                            return found
            if any(en.lower() in query_lower for en in mapping["en"]):
                for zh_term in mapping["zh"][:2]:
                    if zh_term not in query and zh_term not in found:
                        found.append(zh_term)
                        if len(found) >= max_keywords:
                            return found

    return found


def normalize_term(text: str) -> str:
    """Replace known abbreviations/slang with canonical terminology."""
    replacements = {
        "oop": "面向对象编程",
        "OOP": "面向对象编程",
        "Oop": "面向对象编程",
        "ml": "机器学习",
        "ML": "机器学习",
        "dl": "深度学习",
        "DL": "深度学习",
        "nlp": "自然语言处理",
        "NLP": "自然语言处理",
        "api": "API 接口",
        "sdk": "SDK 开发工具包",
        "ide": "IDE 集成开发环境",
        "cli": "CLI 命令行",
        "rest": "REST API",
        "crud": "CRUD 增删改查",
        "sql": "SQL 数据库查询",
        "nosql": "NoSQL 非关系型数据库",
        "json": "JSON 数据格式",
        "csv": "CSV 文件",
        "yaml": "YAML 配置文件",
        "git": "Git 版本控制",
        "http": "HTTP 协议",
        "https": "HTTPS 协议",
        "ssh": "SSH 远程连接",
    }
    result = text
    for abbr, full in replacements.items():
        if abbr in result:
            result = result.replace(abbr, full)
    return result
