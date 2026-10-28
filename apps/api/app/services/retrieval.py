import time
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.embeddings import get_embeddings
from app.services.policies import memory_is_relevant
from app.services.ranking import RankedItem, dedupe_texts, fuse_candidates, select_within_budget
from app.services.textutil import escape_like, identifiers, vector_literal


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    content: str
    page_start: int | None
    page_end: int | None
    section: str | None
    label: str
    filename: str
    extension: str
    score: float
    semantic_rank: int | None
    keyword_rank: int | None
    semantic_similarity: float | None


@dataclass
class RetrievedMemory:
    memory_id: uuid.UUID
    content: str
    source: str
    score: float


@dataclass
class RetrievalOutcome:
    chunks: list[RetrievedChunk]
    retrieved_count: int
    latency_ms: float


def _filters(user_id: uuid.UUID, document_id: uuid.UUID | None, extension: str | None, uploaded_after: datetime | None):
    clauses = ["d.user_id = :user_id", "c.user_id = :user_id"]
    params: dict = {"user_id": user_id}
    if document_id is not None:
        clauses.append("d.id = :document_id")
        params["document_id"] = document_id
    if extension is not None:
        clauses.append("d.extension = :extension")
        params["extension"] = extension
    if uploaded_after is not None:
        clauses.append("d.created_at >= :uploaded_after")
        params["uploaded_after"] = uploaded_after
    return " AND ".join(clauses), params


def _row_chunk(row, *, score: float, semantic_rank, keyword_rank, similarity) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        content=row.content,
        page_start=row.page_start,
        page_end=row.page_end,
        section=row.section,
        label=row.label,
        filename=row.filename,
        extension=row.extension,
        score=score,
        semantic_rank=semantic_rank,
        keyword_rank=keyword_rank,
        semantic_similarity=similarity,
    )


async def _semantic(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    vector: list[float],
    document_id: uuid.UUID | None,
    extension: str | None,
    uploaded_after: datetime | None,
    limit: int,
) -> list:
    where, params = _filters(user_id, document_id, extension, uploaded_after)
    params.update({"query_vector": vector_literal(vector), "limit": limit})
    statement = text(
        f"""
        SELECT c.id AS chunk_id, c.document_id, c.content, c.page_start, c.page_end, c.section,
               d.label, d.filename, d.extension,
               1 - (e.embedding <=> CAST(:query_vector AS vector)) AS similarity
        FROM document_embeddings e
        JOIN document_chunks c ON c.id = e.chunk_id
        JOIN documents d ON d.id = c.document_id
        WHERE e.user_id = :user_id AND {where}
        ORDER BY e.embedding <=> CAST(:query_vector AS vector)
        LIMIT :limit
        """
    )
    result = await session.execute(statement, params)
    return list(result)


async def _keyword(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    query: str,
    document_id: uuid.UUID | None,
    extension: str | None,
    uploaded_after: datetime | None,
    limit: int,
) -> list:
    hits = []
    seen: set = set()
    where, params = _filters(user_id, document_id, extension, uploaded_after)
    for token in identifiers(query):
        token_params = dict(params)
        token_params["pattern"] = f"%{escape_like(token)}%"
        token_params["limit"] = limit
        statement = text(
            f"""
            SELECT c.id AS chunk_id, c.document_id, c.content, c.page_start, c.page_end, c.section,
                   d.label, d.filename, d.extension, 1.0 AS rank
            FROM document_chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE {where} AND c.content ILIKE :pattern ESCAPE '\\'
            LIMIT :limit
            """
        )
        rows = list(await session.execute(statement, token_params))
        for row in rows:
            if row.chunk_id in seen:
                continue
            seen.add(row.chunk_id)
            hits.append(row)
    params.update({"query": query, "limit": limit})
    statement = text(
        f"""
        SELECT c.id AS chunk_id, c.document_id, c.content, c.page_start, c.page_end, c.section,
               d.label, d.filename, d.extension,
               ts_rank_cd(c.content_tsv, websearch_to_tsquery('english', :query)) AS rank
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE {where}
          AND c.content_tsv @@ websearch_to_tsquery('english', :query)
        ORDER BY rank DESC
        LIMIT :limit
        """
    )
    try:
        rows = list(await session.execute(statement, params))
    except Exception:
        rows = []
    for row in rows:
        if row.chunk_id in seen:
            continue
        seen.add(row.chunk_id)
        hits.append(row)
    return hits


async def retrieve_chunks(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    query: str,
    document_id: uuid.UUID | None = None,
    extension: str | None = None,
    uploaded_after: datetime | None = None,
    limit: int | None = None,
) -> RetrievalOutcome:
    started = time.perf_counter()
    top_k = limit or settings.retrieval_top_k
    candidate_limit = max(settings.retrieval_candidates, top_k)
    embeddings = get_embeddings()
    vector = (await embeddings.embed([query]))[0]
    semantic_rows = await _semantic(
        session,
        user_id=user_id,
        vector=vector,
        document_id=document_id,
        extension=extension,
        uploaded_after=uploaded_after,
        limit=candidate_limit,
    )
    keyword_rows = await _keyword(
        session,
        user_id=user_id,
        query=query,
        document_id=document_id,
        extension=extension,
        uploaded_after=uploaded_after,
        limit=candidate_limit,
    )
    by_id: dict[uuid.UUID, RetrievedChunk] = {}
    ranked_items: list[RankedItem] = []
    for rank, row in enumerate(semantic_rows, start=1):
        by_id[row.chunk_id] = _row_chunk(
            row,
            score=0,
            semantic_rank=rank,
            keyword_rank=None,
            similarity=float(row.similarity or 0),
        )
        ranked_items.append(
            RankedItem(
                item_id=str(row.chunk_id),
                text=row.content,
                semantic_rank=rank,
                semantic_similarity=float(row.similarity or 0),
            )
        )
    for rank, row in enumerate(keyword_rows, start=1):
        if row.chunk_id not in by_id:
            by_id[row.chunk_id] = _row_chunk(
                row, score=0, semantic_rank=None, keyword_rank=rank, similarity=None
            )
        else:
            by_id[row.chunk_id].keyword_rank = rank
        ranked_items.append(RankedItem(item_id=str(row.chunk_id), text=row.content, keyword_rank=rank))
    fused = fuse_candidates(ranked_items, query)
    ordered = []
    for item in fused:
        chunk = by_id.get(uuid.UUID(item.item_id))
        if chunk is None:
            continue
        chunk.score = item.score
        ordered.append(chunk)
    deduped_ids = dedupe_texts([(str(chunk.chunk_id), chunk.content) for chunk in ordered])
    deduped = [chunk for chunk in ordered if str(chunk.chunk_id) in set(deduped_ids)]
    limited = deduped[:top_k]
    allowed = set(
        select_within_budget([(str(chunk.chunk_id), chunk.content) for chunk in limited], settings.context_char_budget)
    )
    selected = [chunk for chunk in limited if str(chunk.chunk_id) in allowed]
    elapsed = (time.perf_counter() - started) * 1000
    return RetrievalOutcome(chunks=selected, retrieved_count=len(by_id), latency_ms=elapsed)


async def retrieve_memories(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    query: str,
    limit: int = 3,
) -> list[RetrievedMemory]:
    embeddings = get_embeddings()
    vector = (await embeddings.embed([query]))[0]
    statement = text(
        """
        SELECT m.id AS memory_id, m.content, m.source,
               1 - (e.embedding <=> CAST(:query_vector AS vector)) AS similarity
        FROM memory_embeddings e
        JOIN memories m ON m.id = e.memory_id
        WHERE e.user_id = :user_id
          AND m.user_id = :user_id
          AND m.status = 'active'
        ORDER BY e.embedding <=> CAST(:query_vector AS vector)
        LIMIT :limit
        """
    )
    rows = list(
        await session.execute(
            statement,
            {"user_id": user_id, "query_vector": vector_literal(vector), "limit": max(limit * 4, 8)},
        )
    )
    from app.services.textutil import tokenize

    query_tokens = tokenize(query)
    provider = embeddings.provider
    kept: list[RetrievedMemory] = []
    for row in rows:
        overlap = bool(query_tokens & tokenize(row.content))
        similarity = float(row.similarity or 0)
        if not memory_is_relevant(similarity=similarity, overlap=overlap, embedding_provider=provider):
            continue
        kept.append(
            RetrievedMemory(
                memory_id=row.memory_id,
                content=row.content,
                source=row.source,
                score=similarity if overlap is False else max(similarity, 0.5),
            )
        )
        if len(kept) >= limit:
            break
    return kept
