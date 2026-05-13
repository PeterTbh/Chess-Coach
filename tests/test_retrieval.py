"""Tests for top-k retrieval over the corpus (Slice 4a)."""

from __future__ import annotations

import json
from pathlib import Path

from src.advisor.corpus import (
    FakeEmbedder,
    build_or_refresh_corpus,
    get_client,
    get_or_create_collection,
)
from src.advisor.retrieval import build_query, retrieve_top_k


def _seed(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "corpus_seed.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    return p


def _populated_collection(tmp_path: Path, rows: list[dict]):
    seed = _seed(tmp_path, rows)
    client = get_client(tmp_path / "chroma")
    coll = get_or_create_collection(
        client, FakeEmbedder(), name="test_retrieval"
    )
    build_or_refresh_corpus(coll, seed, force=True)
    return coll


def _entry(id_: str, snippet: str, tags: list[str] | None = None) -> dict:
    return {
        "id": id_,
        "tags": tags or ["test_tag"],
        "source": f"Source {id_}",
        "page": 1,
        "snippet": snippet,
    }


# ---- build_query ---------------------------------------------------------

def test_build_query_includes_fen_tags_and_best_move() -> None:
    q = build_query(
        fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        tags=["isolated_queen_pawn", "middlegame"],
        best_move_san="d4",
    )
    assert "rnbqkbnr" in q
    assert "isolated_queen_pawn" in q
    assert "middlegame" in q
    assert "d4" in q


def test_build_query_tag_order_is_stable() -> None:
    """Different tag orderings must yield the same query string (cache-safe)."""
    q1 = build_query("fen-x", ["b", "a", "c"], "e4")
    q2 = build_query("fen-x", ["c", "a", "b"], "e4")
    assert q1 == q2


# ---- retrieve_top_k ------------------------------------------------------

def test_retrieve_returns_at_most_k_hits(tmp_path: Path) -> None:
    coll = _populated_collection(
        tmp_path,
        [_entry(f"r{i}", f"snippet {i}") for i in range(5)],
    )
    hits = retrieve_top_k(coll, fen="x", tags=["t"], best_move_san="e4", k=3)
    assert len(hits) == 3


def test_retrieve_caps_at_collection_size(tmp_path: Path) -> None:
    coll = _populated_collection(tmp_path, [_entry("r0", "only one")])
    hits = retrieve_top_k(coll, fen="x", tags=["t"], best_move_san="e4", k=5)
    assert len(hits) == 1
    assert hits[0].id == "r0"


def test_retrieve_includes_source_page_snippet_tags(tmp_path: Path) -> None:
    coll = _populated_collection(
        tmp_path,
        [
            {
                "id": "single",
                "tags": ["alpha", "beta"],
                "source": "Author - Book",
                "page": 99,
                "snippet": "the contents",
            }
        ],
    )
    hits = retrieve_top_k(coll, fen="x", tags=["alpha"], best_move_san="e4", k=1)
    assert len(hits) == 1
    h = hits[0]
    assert h.source == "Author - Book"
    assert h.page == 99
    assert h.snippet == "the contents"
    assert set(h.tags) == {"alpha", "beta"}


def test_retrieve_score_is_higher_for_better_match(tmp_path: Path) -> None:
    """Score = 1 - cosine_distance; identical query string ~ score near 1."""
    coll = _populated_collection(
        tmp_path,
        [
            _entry("close", "isolated_queen_pawn middlegame d4 advance"),
            _entry("far", "totally unrelated content about endgames"),
        ],
    )
    hits = retrieve_top_k(
        coll,
        fen="x",
        tags=["isolated_queen_pawn", "middlegame"],
        best_move_san="d4",
        k=2,
    )
    assert len(hits) == 2
    # Higher score should be ranked first by Chroma's ordering.
    assert hits[0].score >= hits[1].score


def test_retrieve_empty_collection_returns_empty(tmp_path: Path) -> None:
    client = get_client(tmp_path / "chroma")
    coll = get_or_create_collection(client, FakeEmbedder(), name="empty")
    hits = retrieve_top_k(coll, fen="x", tags=["t"], best_move_san="e4", k=3)
    assert hits == []


def test_retrieve_uses_full_query_in_embedding(tmp_path: Path) -> None:
    """The embedder must see a string containing FEN, tags, and move."""
    coll = _populated_collection(tmp_path, [_entry("r0", "anything")])

    calls: list[list[str]] = []
    real_fn = coll._embedding_function

    class _Spy:
        is_legacy = True

        def __call__(self, input):
            calls.append(list(input))
            return real_fn(input)

        def embed_query(self, input):
            calls.append(list(input))
            return real_fn(input)

        def name(self):
            return "spy"

    coll._embedding_function = _Spy()

    retrieve_top_k(
        coll,
        fen="rnbq...",
        tags=["isolated_queen_pawn"],
        best_move_san="Nf3",
        k=1,
    )
    assert calls, "embedder was not called"
    joined = " ".join(calls[-1])
    assert "rnbq" in joined
    assert "isolated_queen_pawn" in joined
    assert "Nf3" in joined
