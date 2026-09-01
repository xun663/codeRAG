#!/usr/bin/env python3
"""Re-index knowledge bases — one document at a time with per-doc commit.

Usage:
    cd backend && HF_HUB_OFFLINE=0 PYTHONUTF8=1 python scripts/reindex_kbs.py
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.document import Document, DocumentChunk
from app.models.knowledge_base import KnowledgeBase
from app.core.documents.pipeline import DocumentPipeline
from app.vector_store.factory import get_vector_store

KB_IDS = {
    "python": uuid.UUID("126739c2-e665-4e69-ad59-14218fe5c95d"),
    "java": uuid.UUID("34139461-a995-4f77-86bd-ced21883929d"),
}


async def main():
    store = get_vector_store()
    pipeline = DocumentPipeline()

    for name, kb_id in KB_IDS.items():
        print(f"\n{'=' * 60}")
        print(f"  Processing {name.upper()} KB")
        print(f"{'=' * 60}")

        collection = f"kb_{kb_id}"

        async with async_session_factory() as db:
            docs = (
                (await db.execute(select(Document).where(Document.kb_id == kb_id)))
                .scalars()
                .all()
            )
            print(f"  Documents: {len(docs)}")

            total_chunks = 0
            for doc in docs:
                if not doc.file_path or not Path(doc.file_path).exists():
                    print(f"    ⏭️  {doc.title}: file not found")
                    continue

                try:
                    # Process through pipeline → writes to ChromaDB
                    result = await pipeline.process_file(
                        file_path=str(doc.file_path),
                        kb_id=str(kb_id),
                        mime_type=doc.mime_type,
                        doc_id=str(doc.id),
                        doc_title=doc.title,
                    )

                    # Save chunks to DB
                    for i, c in enumerate(result["chunks"]):
                        chunk_id = c.get("id", str(uuid.uuid4()))
                        chunk = DocumentChunk(
                            id=uuid.UUID(chunk_id),
                            doc_id=doc.id,
                            kb_id=kb_id,
                            chunk_index=i,
                            content=c["content"],
                            content_preview=c["content"][:200],
                            token_count=c.get("token_count", 0),
                            vector_id=chunk_id,
                            chunk_type=c.get("chunk_type", "text"),
                            metadata_json=c.get("metadata", {}),
                        )
                        db.add(chunk)

                    doc.status = "indexed"
                    await db.flush()  # ← commit per-document
                    total_chunks += len(result["chunks"])

                    # Verify ChromaDB write
                    chroma_check = await store.get_all_documents(collection)
                    chroma_ids = set(d2["id"] for d2 in chroma_check)
                    db_ids = set(
                        str(c2.id)
                        for c2 in (
                            await db.execute(
                                select(DocumentChunk).where(DocumentChunk.doc_id == doc.id)
                            )
                        ).scalars().all()
                    )
                    overlap = len(chroma_ids & db_ids)
                    status = f"{len(result['chunks'])} chunks"
                    if overlap != len(result["chunks"]):
                        status += f" ⚠️  ChromaDB/DB mismatch ({overlap}/{len(result['chunks'])})"
                    else:
                        status += " ✅"
                    print(f"    {doc.title:30s} → {status}")

                except Exception as e:
                    print(f"    ❌ {doc.title}: {e}")
                    await db.rollback()
                    # Resume a new transaction for the next doc
                    continue

            # Final verification
            chroma_final = await store.get_all_documents(collection)
            await db.commit()
            print(f"\n  ✅ Done! ChromaDB: {len(chroma_final)}, DB chunks committed.")


if __name__ == "__main__":
    asyncio.run(main())
