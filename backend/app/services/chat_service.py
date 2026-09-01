"""Chat service — Intent Router for multi-path answer generation.

Architecture::

    User Message
        │
        ▼
    Intent Router (classify_intent)
        │
        ├─ TOOL      ─→ Tool handler (time, date, calc, weather)
        ├─ KNOWLEDGE ─→ RAG pipeline (retrieve → rerank → LLM)
        ├─ CLARIFICATION ─→ RAG pipeline (with context)
        ├─ GREETING  ─→ Pure LLM (warm greeting)
        └─ META      ─→ Pure LLM (system intro)

Each response carries a ``source_metadata`` dict recording the actual
execution path, used by the frontend to display the correct icon:

    - 🔧 Tool   (tool_used=True)
    - 📚 Knowledge (retrieval_used=True, llm_used=True)
    - 🔀 Hybrid (retrieval_used=True, llm_used=True, has supplemental reasoning)
    - 🤖 LLM   (llm_used=True, no retrieval, no tool)
"""
from __future__ import annotations

import uuid
import time
from typing import AsyncGenerator

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import NotFoundException
from app.models.conversation import Conversation, Message
from app.models.user import User
from app.schemas.chat import MessageSend
from app.core.rag.pipeline import RAGPipeline
from app.core.rag.intent_classifier import Intent, classify_intent, is_rag_needed
from app.core.tools import match_tool


# ── Source metadata helpers ────────────────────────────────────────────

_SOURCE_META: dict[str, dict] = {
    "tool": {
        "source_type": "tool",
        "tool_used": True,
        "retrieval_used": False,
        "llm_used": False,
        "icon": "🔧",
        "label": "工具调用",
    },
    "knowledge": {
        "source_type": "knowledge",
        "tool_used": False,
        "retrieval_used": True,
        "llm_used": True,
        "icon": "📚",
        "label": "知识库回答",
    },
    "hybrid": {
        "source_type": "hybrid",
        "tool_used": False,
        "retrieval_used": True,
        "llm_used": True,
        "icon": "🔀",
        "label": "混合回答",
    },
    "pure_llm": {
        "source_type": "pure_llm",
        "tool_used": False,
        "retrieval_used": False,
        "llm_used": True,
        "icon": "🤖",
        "label": "纯模型生成",
    },
}


def _build_footer(source_meta: dict) -> str:
    """Build the standardized source footer based on execution metadata."""
    icon = source_meta.get("icon", "🤖")
    label = source_meta.get("label", "纯模型生成")
    source_type = source_meta.get("source_type", "pure_llm")

    footers = {
        "tool": (
            f"\n\n---\n{icon} **{label}**\n"
            "此回答通过系统工具实时获取，未使用知识库。"
        ),
        "knowledge": (
            f"\n\n---\n{icon} **{label}**\n"
            "此回答基于知识库中的文档内容生成，核心概念、示例和规范均源自检索到的文档。"
        ),
        "hybrid": (
            f"\n\n---\n{icon} **{label}**\n"
            "知识库提供了核心概念与代码示例，模型在此基础上进行了补充推理与解释。"
        ),
        "pure_llm": (
            f"\n\n---\n{icon} **{label}**\n"
            "此回答为模型基于训练数据生成，未引用特定外部知识库。建议通过官方文档或实际运行验证代码正确性。"
        ),
    }
    return footers.get(source_type, footers["pure_llm"])


# ── Pure LLM system prompts (no KB injection) ───────────────────────

_SYSTEM_PROMPT_GREETING = """\
You are CodeRAG, a friendly programming learning assistant. The user is \
exchanging greetings or casual conversation. Respond naturally and concisely. \
Do NOT mention the knowledge base, suggest topics, or try to steer the \
conversation toward programming unless the user asks. Keep it warm but brief."""

_SYSTEM_PROMPT_META = """\
You are CodeRAG, a programming learning assistant powered by RAG (Retrieval- \
Augmented Generation). You can answer programming questions by searching a \
knowledge base of coding documentation. Describe your capabilities briefly \
and naturally. Do NOT fabricate specific knowledge base content."""

_SYSTEM_PROMPT_PURE_LLM = """\
You are CodeRAG, a programming learning assistant. Answer helpfully using your \
training knowledge. Be concise and natural — do not force programming suggestions \
if the user isn't asking for them."""


# ── Chat Service ──────────────────────────────────────────────────────

class ChatService:
    @staticmethod
    async def list_conversations(db: AsyncSession, user: User, page: int = 1, page_size: int = 20) -> tuple[list[Conversation], int]:
        count_r = await db.execute(select(func.count(Conversation.id)).where(Conversation.user_id == user.id))
        total = count_r.scalar_one()
        offset = (page - 1) * page_size
        r = await db.execute(
            select(Conversation).where(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc()).offset(offset).limit(page_size)
        )
        return list(r.scalars().all()), total

    @staticmethod
    async def create_conversation(db: AsyncSession, user: User, kb_id=None, title: str | None = None) -> Conversation:
        # 绑定知识库的对话必须校验读取权限（防止凭 kb_id 探测私有库）
        if kb_id:
            from app.services.kb_service import KBService
            await KBService.check_kb_access(db, kb_id, user)
        conv = Conversation(
            id=uuid.uuid4(), user_id=user.id, kb_id=kb_id,
            title=title or "New Conversation",
        )
        db.add(conv)
        await db.flush()
        return conv

    @staticmethod
    async def get_conversation(db: AsyncSession, conv_id, user: User) -> Conversation:
        uid = uuid.UUID(str(conv_id)) if not isinstance(conv_id, uuid.UUID) else conv_id
        r = await db.execute(select(Conversation).where(Conversation.id == uid, Conversation.user_id == user.id))
        conv = r.scalar_one_or_none()
        if not conv:
            raise NotFoundException("Conversation not found")
        return conv

    @staticmethod
    async def delete_conversation(db: AsyncSession, conv_id, user: User) -> None:
        conv = await ChatService.get_conversation(db, conv_id, user)
        await db.delete(conv)
        await db.flush()

    @staticmethod
    async def list_messages(db: AsyncSession, conv_id, user: User, page: int = 1, page_size: int = 50) -> tuple[list[Message], int]:
        await ChatService.get_conversation(db, conv_id, user)
        uid = uuid.UUID(str(conv_id)) if not isinstance(conv_id, uuid.UUID) else conv_id
        count_r = await db.execute(select(func.count(Message.id)).where(Message.conversation_id == uid))
        total = count_r.scalar_one()
        offset = (page - 1) * page_size
        r = await db.execute(
            select(Message).where(Message.conversation_id == uid)
            .order_by(Message.created_at.asc()).offset(offset).limit(page_size)
        )
        return list(r.scalars().all()), total

    @staticmethod
    async def _get_recent_history(db: AsyncSession, conv_id, limit: int = 10) -> list[dict]:
        """Fetch recent messages from a conversation for context."""
        uid = uuid.UUID(str(conv_id)) if not isinstance(conv_id, uuid.UUID) else conv_id
        r = await db.execute(
            select(Message)
            .where(Message.conversation_id == uid)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = list(r.scalars().all())
        # Reverse to chronological order for prompt building
        messages.reverse()
        return [{"role": m.role, "content": m.content} for m in messages]

    # ── Intent Router: execute and return (answer, source_meta) ─────

    @staticmethod
    async def _route_tool(query: str) -> dict:
        """Execute a tool handler and return the result."""
        tool_match = match_tool(query)
        if tool_match:
            tool_name, handler = tool_match
            result = handler(query)
            footer = _build_footer(_SOURCE_META["tool"])
            answer = result["content"] + footer
            return {
                "answer": answer,
                "source_meta": {**_SOURCE_META["tool"], "tool_name": tool_name},
                "sources": [],
                "latency_ms": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
            }
        # Fallback — shouldn't happen since intent was already classified as TOOL
        from app.llm.factory import get_llm_provider
        llm = get_llm_provider()
        answer_text = await llm.generate(
            prompt=query,
            system_prompt=_SYSTEM_PROMPT_PURE_LLM,
        )
        footer = _build_footer(_SOURCE_META["pure_llm"])
        return {
            "answer": answer_text + footer,
            "source_meta": _SOURCE_META["pure_llm"],
            "sources": [],
            "latency_ms": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }

    @staticmethod
    async def _route_pure_llm(query: str, intent: Intent, history: list[dict] | None = None) -> dict:
        """Generate a pure LLM response without retrieval."""
        from app.llm.factory import get_llm_provider
        llm = get_llm_provider()

        if intent == Intent.GREETING:
            system_prompt = _SYSTEM_PROMPT_GREETING
            source_key = "pure_llm"
        elif intent == Intent.META:
            system_prompt = _SYSTEM_PROMPT_META
            source_key = "pure_llm"
        else:
            system_prompt = _SYSTEM_PROMPT_PURE_LLM
            source_key = "pure_llm"

        history_text = ""
        if history:
            for msg in history[-6:]:
                role = "User" if msg["role"] == "user" else "Assistant"
                history_text += f"{role}: {msg['content']}\n"

        prompt = query
        if history_text:
            prompt = f"Conversation History:\n{history_text}\n\nCurrent Question: {query}"

        answer_text = await llm.generate(prompt=prompt, system_prompt=system_prompt)
        footer = _build_footer(_SOURCE_META[source_key])

        return {
            "answer": answer_text + footer,
            "source_meta": _SOURCE_META[source_key],
            "sources": [],
            "latency_ms": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }

    @staticmethod
    async def _route_rag(query: str, kb_id: str, history: list[dict] | None, intent: Intent) -> dict:
        """Run the full RAG pipeline."""
        pipeline = RAGPipeline()
        result = await pipeline.generate_answer(
            query=query,
            kb_id=kb_id,
            conversation_history=history,
            intent=intent,
        )

        # Determine source type based on whether LLM supplemented the answer
        # "hybrid" if the answer went beyond pure knowledge restructuring
        is_hybrid = any(
            marker in (result.get("answer", "") or "")
            for marker in ("🔀",)
        )
        if is_hybrid or len(result.get("sources", [])) < 2:
            source_key = "hybrid"
        else:
            source_key = "knowledge"

        source_meta = _SOURCE_META[source_key].copy()
        source_meta["reference_count"] = len(result.get("sources", []))

        return {
            "answer": result["answer"],
            "source_meta": source_meta,
            "sources": result.get("sources", []),
            "latency_ms": result.get("latency_ms", 0),
            "prompt_tokens": result.get("prompt_tokens", 0),
            "completion_tokens": result.get("completion_tokens", 0),
        }

    # ── Non-streaming endpoint ─────────────────────────────────────

    @staticmethod
    async def send_message_and_get_answer(db: AsyncSession, conv_id, user: User, data: MessageSend) -> Message:
        conv = await ChatService.get_conversation(db, conv_id, user)
        kb_id = str(data.kb_id) if data.kb_id else (str(conv.kb_id) if conv.kb_id else None)

        user_msg = Message(id=uuid.uuid4(), conversation_id=conv.id, role="user", content=data.content, content_type="markdown")
        db.add(user_msg)
        conv.message_count += 1
        await db.flush()

        # Fetch recent conversation history for context
        history = await ChatService._get_recent_history(db, conv_id, limit=10)

        # ── Intent Router ──────────────────────────────────────────
        start = time.monotonic()
        intent = await classify_intent(data.content, history)

        if intent == Intent.TOOL:
            # ── Tool route ────────────────────────────────────────
            result = await ChatService._route_tool(data.content)
            retrieval_config = {
                "kb_id": kb_id, "intent": intent.value,
                "source_type": result["source_meta"]["source_type"],
                "tool_used": True,
            }

        elif is_rag_needed(intent, kb_id):
            # ── RAG route ─────────────────────────────────────────
            result = await ChatService._route_rag(data.content, kb_id, history, intent)
            retrieval_config = {
                "kb_id": kb_id, "intent": intent.value,
                "source_type": result["source_meta"]["source_type"],
                "retrieval_used": True,
            }

        else:
            # ── Pure LLM route ────────────────────────────────────
            result = await ChatService._route_pure_llm(data.content, intent, history)
            retrieval_config = {
                "kb_id": kb_id, "intent": intent.value,
                "source_type": result["source_meta"]["source_type"],
                "mode": "pure_llm",
            }

        latency_ms = int((time.monotonic() - start) * 1000)
        result["latency_ms"] = latency_ms

        assistant_msg = Message(
            id=uuid.uuid4(), conversation_id=conv.id, role="assistant",
            content=result["answer"], content_type="markdown",
            retrieval_config=retrieval_config,
            retrieved_chunks=result.get("sources", []),
            llm_provider="openai", llm_model="default",
            prompt_tokens=result.get("prompt_tokens", 0),
            completion_tokens=result.get("completion_tokens", 0),
            latency_ms=latency_ms,
        )
        db.add(assistant_msg)
        conv.message_count += 1
        await db.flush()
        return assistant_msg

    # ── Streaming endpoint ────────────────────────────────────────

    @staticmethod
    async def stream_answer(db: AsyncSession, conv_id, user: User, data: MessageSend) -> AsyncGenerator[dict, None]:
        conv = await ChatService.get_conversation(db, conv_id, user)
        kb_id = str(data.kb_id) if data.kb_id else (str(conv.kb_id) if conv.kb_id else None)

        user_msg = Message(id=uuid.uuid4(), conversation_id=conv.id, role="user", content=data.content, content_type="markdown")
        db.add(user_msg)
        conv.message_count += 1
        await db.flush()

        # Fetch recent conversation history for context
        history = await ChatService._get_recent_history(db, conv_id, limit=10)

        # ── Intent Router ──────────────────────────────────────────
        start = time.monotonic()
        intent = await classify_intent(data.content, history)

        if intent == Intent.TOOL:
            # ── Tool route (non-streaming, but yield as single token) ──
            result = await ChatService._route_tool(data.content)
            yield {"type": "phase", "phase": "tool", "message": "正在调用工具..."}
            yield {"type": "token", "content": result["answer"]}
            latency_ms = int((time.monotonic() - start) * 1000)
            # ⚠️ 必须先入库再 yield done：event_stream 收到 done 即 break，
            #    生成器在 yield 点被 aclose() 关闭，yield 之后的代码永远不执行
            assistant_msg = Message(
                id=uuid.uuid4(), conversation_id=conv.id, role="assistant",
                content=result["answer"], content_type="markdown",
                retrieval_config={
                    "kb_id": kb_id, "intent": intent.value,
                    "source_type": "tool", "tool_used": True,
                },
                retrieved_chunks=[],
                latency_ms=latency_ms,
            )
            db.add(assistant_msg)
            conv.message_count += 1
            await db.flush()
            yield {
                "type": "done",
                "content": result["answer"],
                "sources": [],
                "source_meta": result["source_meta"],
                "latency_ms": latency_ms,
            }

        elif is_rag_needed(intent, kb_id):
            # ── RAG route ─────────────────────────────────────────
            pipeline = RAGPipeline()
            async for chunk in pipeline.generate_stream(
                query=data.content,
                kb_id=kb_id,
                conversation_history=history,
                intent=intent,
            ):
                if chunk.get("type") == "done":
                    # ⚠️ 先入库再 yield done（event_stream 收到 done 即 break，
                    #    生成器在 yield 点被 aclose() 关闭，yield 之后的代码不执行）
                    # Determine source type (heuristic based on retrieval depth)
                    source_meta = _SOURCE_META["knowledge"].copy()
                    source_meta["reference_count"] = len(chunk.get("sources", []))
                    chunk["source_meta"] = source_meta

                    assistant_msg = Message(
                        id=uuid.uuid4(), conversation_id=conv.id, role="assistant",
                        content=chunk.get("content", ""), content_type="markdown",
                        retrieval_config={
                            "kb_id": kb_id, "intent": intent.value,
                            "source_type": "knowledge",
                        },
                        retrieved_chunks=chunk.get("sources", []),
                        latency_ms=chunk.get("latency_ms", 0),
                    )
                    db.add(assistant_msg)
                    conv.message_count += 1
                    await db.flush()
                yield chunk

        else:
            # ── Pure LLM stream ────────────────────────────────────
            from app.llm.factory import get_llm_provider
            llm = get_llm_provider()

            if intent == Intent.GREETING:
                system_prompt = _SYSTEM_PROMPT_GREETING
            elif intent == Intent.META:
                system_prompt = _SYSTEM_PROMPT_META
            else:
                system_prompt = _SYSTEM_PROMPT_PURE_LLM

            history_text = ""
            if history:
                for msg in history[-6:]:
                    role = "User" if msg["role"] == "user" else "Assistant"
                    history_text += f"{role}: {msg['content']}\n"
            prompt = data.content
            if history_text:
                prompt = f"Conversation History:\n{history_text}\n\nCurrent Question: {data.content}"

            full = ""
            async for token in llm.generate_stream(
                prompt=prompt,
                system_prompt=system_prompt,
            ):
                full += token
                yield {"type": "token", "content": token}

            footer = _build_footer(_SOURCE_META["pure_llm"])
            full += footer

            # ⚠️ 先入库再 yield done（event_stream 收到 done 即 break，
            #    生成器在 yield 点被 aclose() 关闭，yield 之后的代码不执行）
            assistant_msg = Message(
                id=uuid.uuid4(), conversation_id=conv.id, role="assistant",
                content=full, content_type="markdown",
                retrieval_config={
                    "kb_id": kb_id, "intent": intent.value,
                    "source_type": "pure_llm", "mode": "pure_llm",
                },
            )
            db.add(assistant_msg)
            conv.message_count += 1
            await db.flush()

            yield {
                "type": "done",
                "content": full,
                "sources": [],
                "source_meta": _SOURCE_META["pure_llm"],
            }
