"""Tests for the seed corpus loader + ChromaDB indexer (Slice 4a)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from src.advisor.corpus import (
    CorpusEntry,
    CorpusNotFoundError,
    CorpusValidationError,
    FakeEmbedder,
    build_or_refresh_corpus,
    get_client,
    get_or_create_collection,
    load_seed,
)

_VALID_ENTRY = {
    "id": "test-1",
    "tags": ["isolated_queen_pawn", "middlegame"],
    "source": "Test - A Test Book",
    "page": 42,
    "snippet": "Test snippet about IQP positions.",
}


def _write_seed(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "corpus_seed.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    return p


def _fresh_collection(tmp_path: Path):
    client = get_client(tmp_path / "chroma")
    return get_or_create_collection(
        client, FakeEmbedder(), name=f"test_{os.getpid()}_{time.time_ns()}"
    )


# ---- load_seed -----------------------------------------------------------

def test_load_seed_returns_entries(tmp_path: Path) -> None:
    seed = _write_seed(tmp_path, [_VALID_ENTRY])
    entries = load_seed(seed)
    assert len(entries) == 1
    assert isinstance(entries[0], CorpusEntry)
    assert entries[0].id == "test-1"
    assert entries[0].tags == ["isolated_queen_pawn", "middlegame"]


def test_load_seed_raises_not_found(tmp_path: Path) -> None:
    with pytest.raises(CorpusNotFoundError):
        load_seed(tmp_path / "missing.json")


def test_load_seed_raises_on_bad_json(tmp_path: Path) -> None:
    p = tmp_path / "broken.json"
    p.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(CorpusValidationError, match="JSON"):
        load_seed(p)


def test_load_seed_raises_on_non_list_root(tmp_path: Path) -> None:
    p = tmp_path / "wrong.json"
    p.write_text('{"foo": "bar"}', encoding="utf-8")
    with pytest.raises(CorpusValidationError, match="list"):
        load_seed(p)


def test_load_seed_raises_on_missing_fields(tmp_path: Path) -> None:
    bad = {"id": "x", "tags": [], "page": 1, "snippet": "s"}  # no source
    seed = _write_seed(tmp_path, [bad])
    with pytest.raises(CorpusValidationError, match="source"):
        load_seed(seed)


def test_load_seed_raises_on_wrong_tag_type(tmp_path: Path) -> None:
    bad = dict(_VALID_ENTRY)
    bad["tags"] = "not a list"
    seed = _write_seed(tmp_path, [bad])
    with pytest.raises(CorpusValidationError, match="tags"):
        load_seed(seed)


# ---- build_or_refresh_corpus ---------------------------------------------

def test_build_writes_all_rows(tmp_path: Path) -> None:
    seed = _write_seed(tmp_path, [_VALID_ENTRY, dict(_VALID_ENTRY, id="test-2")])
    coll = _fresh_collection(tmp_path)
    written = build_or_refresh_corpus(coll, seed)
    assert written == 2
    assert coll.count() == 2


def test_build_is_idempotent_on_unchanged_mtime(tmp_path: Path) -> None:
    seed = _write_seed(tmp_path, [_VALID_ENTRY])
    coll = _fresh_collection(tmp_path)
    build_or_refresh_corpus(coll, seed)
    second = build_or_refresh_corpus(coll, seed)
    assert second == 0
    assert coll.count() == 1


def test_build_wipes_and_refreshes_on_changed_mtime(tmp_path: Path) -> None:
    seed = _write_seed(tmp_path, [_VALID_ENTRY])
    coll = _fresh_collection(tmp_path)
    build_or_refresh_corpus(coll, seed)

    # Overwrite with different content, bump mtime.
    seed.write_text(
        json.dumps([dict(_VALID_ENTRY, id="test-x", snippet="changed")]),
        encoding="utf-8",
    )
    new_mtime = time.time() + 2
    os.utime(seed, (new_mtime, new_mtime))

    written = build_or_refresh_corpus(coll, seed)
    assert written == 1
    rows = coll.get(include=["metadatas"])
    assert rows["ids"] == ["test-x"]


def test_build_with_empty_seed_writes_zero(tmp_path: Path) -> None:
    seed = _write_seed(tmp_path, [])
    coll = _fresh_collection(tmp_path)
    written = build_or_refresh_corpus(coll, seed)
    assert written == 0
    assert coll.count() == 0


def test_build_raises_when_seed_missing(tmp_path: Path) -> None:
    coll = _fresh_collection(tmp_path)
    with pytest.raises(CorpusNotFoundError):
        build_or_refresh_corpus(coll, tmp_path / "no_such.json")


def test_build_force_reindexes_even_when_mtime_unchanged(tmp_path: Path) -> None:
    seed = _write_seed(tmp_path, [_VALID_ENTRY])
    coll = _fresh_collection(tmp_path)
    build_or_refresh_corpus(coll, seed)
    written = build_or_refresh_corpus(coll, seed, force=True)
    assert written == 1


# ---- Real seed file -------------------------------------------------------

def test_committed_seed_loads_and_indexes(tmp_path: Path) -> None:
    """Sanity check: the seed in data/corpus_seed.json is valid + indexable."""
    seed_path = Path("data/corpus_seed.json")
    if not seed_path.is_file():
        pytest.skip("committed seed not present")
    entries = load_seed(seed_path)
    assert len(entries) >= 15  # we wrote ~22

    coll = _fresh_collection(tmp_path)
    written = build_or_refresh_corpus(coll, seed_path)
    assert written == len(entries)
