"""去同源化评估出题器 — 从 Chunk 生成"真实用户问法"的检索评估问题。

背景：CodeRAG 是用户自建知识库系统，不能要求用户人工标注 GT。复用「Chunk →
LLM 出题」能力可自动构造评估数据：从 chunk 出题 → 该 chunk 天然是答案所在。

但直接复用复习模块的《选择题》prompt 会引入**同源词汇偏差**：题目沿用 chunk
原文术语，检索（尤其 BM25/Dense）极易命中，导致指标虚高——测的是"检索和语料
自洽"，不是"真实用户能不能找到答案"。

本模块是**评估专用**出题器：
  - 产出**自然语言检索问题**（非选择题），问题可直接作为 RAG 检索 query。
  - Prompt 硬性要求"学习者口吻 / 改写避原文术语 / 用同义与解释性表达"，
    把题目从"chunk 的镜子"改成"学习者的真实问法"，逼近真实检索难度。
  - 不写库、无 db 依赖，仅读 chunk 内容与文档标题，可脱离 ORM 单独调用。
"""
from __future__ import annotations

import json
import logging

from app.llm.factory import get_llm_provider

logger = logging.getLogger(__name__)

# 评估问题类型（Phase 2 将按题型分指标统计）
QUESTION_TYPES = (
    "concept",      # 概念理解
    "comparison",   # 概念比较
    "usage",        # 使用场景
    "code",         # 代码理解
    "debugging",    # 错误诊断
    "reasoning",    # 需结合多句推理
)

_SYSTEM_PROMPT = """你是 RAG 检索质量评估的出题器。你的任务是根据给定的知识库切片内容，生成若干条"真实用户可能会提出的检索问题"。

核心要求 —— 问题必须模拟真实学习者提问，而不能是原文的复述：
1. 使用学习者口吻，尽可能用自然口语化表达。
2. 不要直接复制原文句子。
3. 避免机械重复切片中连续出现的专业术语；优先用同义表达、解释性表达（例如原文写 "tuple 是不可变序列"，可问 "Python 里有没有一种容器创建之后里面的内容就不能改了？"）。
4. 可以使用"怎么理解 / 有什么区别 / 什么时候用 / 为什么"等真实问法。
5. 不要为了避开关键词而制造不自然、绕弯的问题；改写后仍要通顺。
6. 问题必须能够仅依据该知识库内容回答（不得问切片中不存在的内容）。
7. 每道题必须能明确指向来源切片（答案确实在这段内容里）。
8. 出题要覆盖不同角度，题型分布尽量多样。
9. 禁止生成"导航 / 元信息 / 前置路径 / 页面外壳"类问题：不要问"该先学哪个部分""页面上有什么入口可以点""这份资料是哪个版本/谁翻译的""目录里有哪些章节"，也不要问**网页外壳/UI 元素**（如"页面上那个分享按钮/导航菜单/搜索框是干什么的""社交分享按钮有哪些显示模式"）——这些只有文档目录、页面结构、元信息或网页 chrome 才能回答，必须问切片正文里的知识内容。
10. 禁止生成过于泛化的"文档 / 教程概述"类问题：不要问"这个文档讲的是什么""这份教程覆盖哪些内容"——这类问题没有明确的检索目标。问题应聚焦切片正文里的**具体知识点**（某个概念 / 某个函数 / 某个用法），确保检索有明确的命中目标。

仅输出合法 JSON，不要输出任何解释或 Markdown。"""

_USER_PROMPT = """知识库文档标题：{doc_title}

切片内容：
---
{content}
---

为上面的切片生成 {count} 道"真实用户问法"的检索评估问题。
输出 JSON 格式：
{{
  "questions": [
    {{
      "question": "自然语言问题（学习者口吻，不照抄原文）",
      "type": "concept | comparison | usage | code | debugging | reasoning",
      "difficulty": "easy | medium | hard"
    }}
  ]
}}"""


class AutoQuestionGenerator:
    """从 chunk 内容生成去同源化的自然语言检索评估问题。"""

    @staticmethod
    async def generate(
        chunk_content: str,
        doc_title: str = "",
        count: int = 2,
        max_attempts: int = 2,
    ) -> list[dict]:
        """Generate natural-language retrieval questions from a chunk.

        Args:
            chunk_content: Chunk 文本内容（截断 2000 字符以内）。
            doc_title: 来源文档标题（用于 prompt 上下文）。
            count: 每 chunk 生成的问题数。
            max_attempts: LLM 返回非 JSON / 空结果时的重试次数（默认 2）。

        Returns:
            list of {question, type, difficulty}；多次失败后返回 []。
        """
        content = (chunk_content or "").strip()
        if not content:
            return []
        if len(content) > 2000:
            content = content[:2000]

        llm = get_llm_provider()
        user_prompt = _USER_PROMPT.format(
            doc_title=doc_title or "未知文档",
            content=content,
            count=max(1, min(count, 5)),
        )

        last_exc: Exception | None = None
        for attempt in range(1, max(1, max_attempts) + 1):
            try:
                raw = await llm.generate(prompt=user_prompt, system_prompt=_SYSTEM_PROMPT)
                questions = AutoQuestionGenerator._parse_questions(raw)
                if questions:
                    return questions
                # 合法 JSON 但无有效问题 → 值得重试一次（LLM 偶发输出空结构）
            except Exception as exc:
                last_exc = exc
                logger.warning("Auto question generation attempt %d/%d failed: %s",
                               attempt, max_attempts, exc)
        if last_exc:
            logger.warning("Auto question generation failed after %d attempts: %s",
                           max_attempts, last_exc)
        else:
            logger.warning("Auto question generation returned no valid questions after %d attempts",
                           max_attempts)
        return []

    @staticmethod
    def _parse_questions(raw: str) -> list[dict]:
        """Strip markdown fences (if any) and parse the LLM JSON output."""
        raw = (raw or "").strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1]
            if raw.endswith("```"):
                raw = raw[:-3].strip()
        data = json.loads(raw)
        questions = data.get("questions", [])
        return [q for q in questions if q.get("question")]
