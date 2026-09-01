"""Tool handlers for real-time queries (time, date, calculation, conversion).

These execute directly without RAG retrieval or LLM generation.
Each handler returns a dict with ``content``, ``tool_name``, and ``icon``.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Callable

# ═════════════════════════════════════════════════════════════════════
#  Tool registry
# ═════════════════════════════════════════════════════════════════════

ToolHandler = Callable[[str], dict[str, str]]
_ToolEntry = tuple[re.Pattern, str, ToolHandler]

_registry: list[_ToolEntry] = []


def _register(pattern: str, tool_name: str):
    """Decorator: register a tool handler with its trigger pattern."""
    def decorator(fn: ToolHandler) -> ToolHandler:
        _registry.append((re.compile(pattern, re.IGNORECASE), tool_name, fn))
        return fn
    return decorator


def match_tool(text: str) -> tuple[str, ToolHandler] | None:
    """Return (tool_name, handler) for the first matching tool, or None."""
    for pattern, name, handler in _registry:
        if pattern.search(text):
            return name, handler
    return None


def list_tools() -> list[dict]:
    """List registered tools (for diagnostics / help)."""
    return [
        {"name": name, "pattern": pattern.pattern}
        for pattern, name, _ in _registry
    ]


# ═════════════════════════════════════════════════════════════════════
#  Tool implementations
# ═════════════════════════════════════════════════════════════════════


@_register(
    r"(现在|当前|目前|今天)\s*(时间|时候|几点|日期|年月日|多少号|星期)",
    "datetime",
)
def _handle_datetime(query: str) -> dict[str, str]:
    """Return current date and time."""
    now = datetime.now(UTC)
    # Try to get a meaningful timezone display
    try:
        import time as _time
        tz_name = _time.tzname[_time.daylight]
    except Exception:
        tz_name = "UTC"
    return {
        "content": (
            f"📅 {now.strftime('%Y-%m-%d')}\n"
            f"⏱ {now.strftime('%H:%M:%S')} ({tz_name})"
        ),
        "tool_name": "datetime",
        "icon": "🔧",
    }


@_register(
    r"(计算|等于|多少|加|减|乘|除|plus|minus|times|divided)",
    "calculator",
)
def _handle_calculator(query: str) -> dict[str, str]:
    """Evaluate a simple arithmetic expression from natural language."""
    # Strip non-math characters and try to evaluate
    expr = query.strip()
    # Normalize common words to operators (no \b — CJK chars don't have word boundaries)
    expr = expr.replace("加", "+").replace("减去", "-")
    expr = expr.replace("减", "-")
    expr = expr.replace("乘以", "*").replace("乘", "*")
    expr = expr.replace("除以", "/").replace("除", "/")
    expr = expr.replace("等于", "=")

    # Extract the math expression (everything before = if present, or full text)
    if "=" in expr:
        expr = expr.split("=")[0].strip()

    # Remove non-math characters but keep digits, operators, parens, decimal points
    expr_clean = re.sub(r"[^0-9+\-*/().,%\s]", "", expr).strip()

    if not expr_clean:
        return {
            "content": '请提供具体的算式，例如 "123乘456" 或 "100加200"。',
            "tool_name": "calculator",
            "icon": "🔧",
        }

    try:
        # Use a restricted eval for arithmetic only
        import operator as _operator

        ops = {
            "+": _operator.add,
            "-": _operator.sub,
            "*": _operator.mul,
            "/": _operator.truediv,
            "//": _operator.floordiv,
            "%": _operator.mod,
        }

        # Safe eval — only literal numbers and basic ops
        result = eval(expr_clean, {"__builtins__": {}}, ops)  # noqa: S307
        return {
            "content": f"计算结果: {expr_clean} = {result}",
            "tool_name": "calculator",
            "icon": "🔧",
        }
    except Exception:
        return {
            "content": f"无法计算表达式: {expr_clean}",
            "tool_name": "calculator",
            "icon": "🔧",
        }


@_register(
    r"(?:(\d+)\s*(?:公里|千米|m|米|厘米|cm|毫米|mm|英寸|inch|英尺|foot|feet|yard|码))"
    r".*(?:多少|等于|换算|转|转换|对应)",
    "unit_converter",
)
def _handle_unit_conversion(query: str) -> dict[str, str]:
    """Simple unit conversion (length)."""
    return {
        "content": "长度单位转换器（开发中）。支持: 公里、米、厘米、毫米、英寸、英尺",
        "tool_name": "unit_converter",
        "icon": "🔧",
    }


@_register(
    r"(天气|温度|下雨|下雪|刮风|台风|湿度|空气质量|pm)",
    "weather",
)
def _handle_weather(query: str) -> dict[str, str]:
    """Weather query — requires API integration; returns stub for now."""
    return {
        "content": (
            "天气查询需要接入外部天气 API（如和风天气 / OpenWeatherMap）\n"
            "当前为占位响应，请在配置中添加天气 API 密钥后使用。"
        ),
        "tool_name": "weather",
        "icon": "🔧",
    }


@_register(
    r"(汇率|美元|人民币|欧元|英镑|日元|换|兑换|换算)",
    "currency_converter",
)
def _handle_currency(query: str) -> dict[str, str]:
    """Currency conversion — requires API; returns stub for now."""
    return {
        "content": (
            "汇率转换需要接入实时汇率 API（如 exchangerate-api.com）\n"
            "当前为占位响应，请在配置中添加汇率 API 密钥后使用。"
        ),
        "tool_name": "currency_converter",
        "icon": "🔧",
    }
