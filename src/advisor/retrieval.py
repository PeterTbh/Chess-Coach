"""Top-k retrieval over the seed corpus (Slice 4a).

Query construction per scope F2 step 2:
    "Embedding der Eingabe (FEN + Tags + Engine-Move)"

We concatenate FEN, space-joined tags, and the best move into a single
string; the collection's embedding function turns it into a vector and
ChromaDB returns the top-k by cosine similarity. Scores are converted
from "distance" (lower is better, 0..2 for cosine) into "score" (higher
is better) so callers can sort intuitively.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from chromadb.api.models.Collection import Collection

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CorpusHit:
    id: str
    source: str
    page: int
    snippet: str
    tags: list[str]
    score: float  # 1 - cosine_distance; higher = closer match


def build_query(fen: str, tags: list[str], best_move_san: str) -> str:
    """Single query string used for embedding. Stable for caching/testing."""
    tag_str = " ".join(sorted(tags))
    return f"FEN: {fen} | tags: {tag_str} | best_move: {best_move_san}"


def retrieve_top_k(
    collection: Collection,
    *,
    fen: str,
    tags: list[str],
    best_move_san: str,
    k: int = 3,
) -> list[CorpusHit]:
    """Return up to ``k`` corpus hits ranked by similarity to the query."""
    query = build_query(fen, tags, best_move_san)
    collection_size = collection.count()
    if collection_size == 0:
        return []
    n = min(k, collection_size)
    result = collection.query(
        query_texts=[query],
        n_results=n,
        include=["metadatas", "documents", "distances"],
    )
    return _rows_to_hits(result)


def _rows_to_hits(result: dict) -> list[CorpusHit]:
    ids_batch = result.get("ids") or [[]]
    metas_batch = result.get("metadatas") or [[]]
    dists_batch = result.get("distances") or [[]]
    if not ids_batch or not ids_batch[0]:
        return []
    ids = ids_batch[0]
    metas = metas_batch[0] if metas_batch else []
    dists = dists_batch[0] if dists_batch else []

    hits: list[CorpusHit] = []
    for i, hit_id in enumerate(ids):
        meta = metas[i] if i < len(metas) else {}
        dist = dists[i] if i < len(dists) else 0.0
        tags_csv = (meta or {}).get("tags_csv", "")
        hits.append(
            CorpusHit(
                id=hit_id,
                source=(meta or {}).get("source", ""),
                page=int((meta or {}).get("page", 0)),
                snippet=(meta or {}).get("snippet", ""),
                tags=[t for t in tags_csv.split(",") if t],
                score=1.0 - float(dist),
            )
        )
    return hits
