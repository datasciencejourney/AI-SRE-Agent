from pathlib import Path

from sqlalchemy import select

from app.db.models import KnowledgeChunk
from app.db.session import SessionLocal
from app.rag.embeddings import embed

RUNBOOK_DIR = Path(__file__).resolve().parents[2] / "runbooks"


async def upsert_chunk(source_type: str, source_id: str, title: str, content: str) -> None:
    async with SessionLocal() as session:
        existing = (
            await session.execute(select(KnowledgeChunk).where(KnowledgeChunk.source_id == source_id))
        ).scalars().first()
        vector = embed(f"{title}\n{content}")
        if existing:
            existing.title, existing.content, existing.embedding = title, content, vector
        else:
            session.add(
                KnowledgeChunk(
                    source_type=source_type, source_id=source_id, title=title, content=content, embedding=vector
                )
            )
        await session.commit()


async def seed_runbooks() -> int:
    count = 0
    for path in sorted(RUNBOOK_DIR.glob("*.md")):
        text = path.read_text()
        title = text.splitlines()[0].lstrip("# ").strip()
        await upsert_chunk("runbook", f"runbook:{path.stem}", title, text)
        count += 1
    return count


async def search_knowledge(query: str, k: int = 3) -> list[dict]:
    vec = embed(query)
    distance = KnowledgeChunk.embedding.cosine_distance(vec).label("distance")
    async with SessionLocal() as session:
        rows = (
            await session.execute(select(KnowledgeChunk, distance).order_by(distance).limit(k))
        ).all()
    return [
        {
            "source_type": chunk.source_type,
            "source_id": chunk.source_id,
            "title": chunk.title,
            "similarity": round(1 - float(dist), 3),
            "snippet": chunk.content[:300],
        }
        for chunk, dist in rows
    ]
