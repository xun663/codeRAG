#!/usr/bin/env python3
"""Re-index KBs — clean, single-purpose, no async issues.

Usage:
    cd backend && PYTHONUTF8=1 python scripts/reindex_kbs_clean.py
"""
from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from sqlalchemy import select, text

from app.db.session import async_session_factory
from app.models.document import Document
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
            # Get all documents directly (no relationships to avoid lazy load issues)
            r = await db.execute(
                select(Document).where(Document.kb_id == kb_id).order_by(Document.created_at)
            )
            docs = r.scalars().all()

            # Pre-fetch file paths
            doc_list = []
            for doc in docs:
                fp = doc.file_path
                title = doc.title or "untitled"
                mime = doc.mime_type
                doc_id = doc.id
                doc_list.append((doc_id, title, fp, mime))

            print(f"  Documents: {len(doc_list)}")

            total_chunks = 0
            for doc_id, title, fp, mime in doc_list:
                if not fp or not Path(fp).exists():
                    print(f"    ⏭️  {title}: file not found ({fp})")
                    continue

                try:
                    result = await pipeline.process_file(
                        file_path=str(fp),
                        kb_id=str(kb_id),
                        mime_type=mime,
                        doc_id=str(doc_id),
                        doc_title=title,
                    )

                    # Update document status
                    await db.execute(
                        text("UPDATE documents SET status = 'indexed' WHERE id = :id"),
                        {"id": doc_id},
                    )
                    await db.flush()

                    total_chunks += len(result["chunks"])
                    print(f"    ✅ {title:30s} → {len(result['chunks'])} chunks")

                except Exception as e:
                    print(f"    ❌ {title}: {e}")
                    await db.rollback()
                    continue

            # Verify
            chroma = await store.get_all_documents(collection)
            await db.commit()
            print(f"\n  ✅ Done! ChromaDB: {len(chroma)} chunks total")


if __name__ == "__main__":
    asyncio.run(main())
