from dataclasses import dataclass

from app.services.textutil import containment, identifiers, tokenize


def reciprocal_rank_fusion(ranked_id_lists: list[list[str]], *, k: int = 60) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranked in ranked_id_lists:
        for rank, item_id in enumerate(ranked, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return scores


def overlap_ratio(query: str, text: str) -> float:
    query_tokens = tokenize(query)
    if not query_tokens:
        return 0.0
    return len(query_tokens & tokenize(text)) / len(query_tokens)


@dataclass
class RankedItem:
    item_id: str
    text: str
    semantic_rank: int | None = None
    keyword_rank: int | None = None
    semantic_similarity: float | None = None
    score: float = 0.0


def fuse_candidates(items: list[RankedItem], query: str) -> list[RankedItem]:
    """Score only items that were already retrieved. Never adds a new id."""
    unique: dict[str, RankedItem] = {}
    for item in items:
        current = unique.get(item.item_id)
        if current is None:
            unique[item.item_id] = item
            continue
        if item.semantic_rank is not None:
            current.semantic_rank = item.semantic_rank
            current.semantic_similarity = item.semantic_similarity
        if item.keyword_rank is not None:
            current.keyword_rank = item.keyword_rank
        if not current.text and item.text:
            current.text = item.text
    semantic_ids = [
        item.item_id
        for item in sorted(
            (item for item in unique.values() if item.semantic_rank is not None),
            key=lambda item: item.semantic_rank or 0,
        )
    ]
    keyword_ids = [
        item.item_id
        for item in sorted(
            (item for item in unique.values() if item.keyword_rank is not None),
            key=lambda item: item.keyword_rank or 0,
        )
    ]
    fused = reciprocal_rank_fusion([semantic_ids, keyword_ids])
    ident_tokens = [token.lower() for token in identifiers(query)]
    scored: list[RankedItem] = []
    for item_id, rrf in fused.items():
        item = unique.get(item_id)
        if item is None:
            continue
        score = rrf + (0.15 * overlap_ratio(query, item.text))
        if any(token in item.text.lower() for token in ident_tokens):
            score += 0.25
        item.score = score
        scored.append(item)
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored


def dedupe_texts(items: list[tuple[str, str]], *, threshold: float = 0.9) -> list[str]:
    """Drop later items whose tokens are almost entirely contained in an earlier item."""
    kept: list[str] = []
    token_sets: list[set[str]] = []
    for item_id, text in items:
        tokens = tokenize(text)
        if any(containment(tokens, previous) >= threshold for previous in token_sets):
            continue
        kept.append(item_id)
        token_sets.append(tokens)
    return kept


def select_within_budget(texts: list[tuple[str, str]], budget: int) -> list[str]:
    selected: list[str] = []
    used = 0
    for item_id, text in texts:
        cost = len(text)
        if not selected and cost > budget:
            selected.append(item_id)
            break
        if used + cost > budget:
            break
        selected.append(item_id)
        used += cost
    return selected
