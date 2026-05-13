"""Tests for the SQLite-backed repertoire store (Feature 1.1)."""

from __future__ import annotations

from pathlib import Path

import chess
import pytest

from src.repertoire.store import (
    ExpectedMove,
    LoadStats,
    RepertoireNotFoundError,
    RepertoireParseError,
    find_expected_moves_from,
    find_node_by_fen_after,
    get_repertoire_id,
    init_db,
    load_repertoire_into_db,
)

# Same fixture as the in-memory parser tests so behaviour is comparable.
SPANISH_PLUS_ITALIAN_PGN = """
[Event "Spanish mainline"]
[Site "?"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 (3. Bc4 Bc5) a6 4. Ba4 Nf6 *

[Event "Italian"]
[Site "?"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 3. Bc4 Bc5 *
""".strip()


SINGLE_LINE_BLACK_PGN = """
[Event "Caro-Kann"]
[Result "*"]

1. e4 c6 2. d4 d5 *
""".strip()


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _board_after(sans: list[str]) -> chess.Board:
    board = chess.Board()
    for san in sans:
        board.push_san(san)
    return board


# ---- init_db -------------------------------------------------------------

def test_init_db_creates_schema(tmp_path: Path) -> None:
    db = tmp_path / "caissa.sqlite"
    conn = init_db(db)
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "repertoires" in tables
    assert "repertoire_nodes" in tables


def test_init_db_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "caissa.sqlite"
    init_db(db)
    # Second call must not raise even though tables already exist.
    init_db(db)


# ---- load_repertoire_into_db --------------------------------------------

def test_load_returns_stats(tmp_path: Path) -> None:
    db = tmp_path / "caissa.sqlite"
    pgn = _write(tmp_path, "white.pgn", SPANISH_PLUS_ITALIAN_PGN)
    conn = init_db(db)
    stats = load_repertoire_into_db(conn, pgn, "white")
    assert isinstance(stats, LoadStats)
    assert stats.color == "white"
    assert stats.variations == 2  # Spanish + Italian (two top-level games)
    assert stats.positions > 0


def test_load_inserts_starting_move(tmp_path: Path) -> None:
    """Scope F1.1 acceptance: a known FEN-after must be findable."""
    db = tmp_path / "caissa.sqlite"
    pgn = _write(tmp_path, "white.pgn", SPANISH_PLUS_ITALIAN_PGN)
    conn = init_db(db)
    load_repertoire_into_db(conn, pgn, "white")

    board = chess.Board()
    board.push_san("e4")
    node = find_node_by_fen_after(conn, "white", board.fen())
    assert node is not None
    assert node.san_move == "e4"
    assert node.uci_move == "e2e4"
    assert node.move_color == "white"
    assert node.parent_node_id is None  # root move


def test_san_sequence_reconstructable_from_chain(tmp_path: Path) -> None:
    """Scope F1.1 acceptance #2: the SAN path back to the root must be recoverable."""
    db = tmp_path / "caissa.sqlite"
    pgn = _write(tmp_path, "white.pgn", SPANISH_PLUS_ITALIAN_PGN)
    conn = init_db(db)
    load_repertoire_into_db(conn, pgn, "white")

    # Position after 1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 4.Ba4
    target = _board_after(["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4"])
    node = find_node_by_fen_after(conn, "white", target.fen())
    assert node is not None
    assert node.san_move == "Ba4"

    # Walk parents back to the root → reconstruct the SAN sequence.
    sans: list[str] = []
    current = node
    while current is not None:
        sans.append(current.san_move)
        if current.parent_node_id is None:
            break
        row = conn.execute(
            "SELECT * FROM repertoire_nodes WHERE id = ?",
            (current.parent_node_id,),
        ).fetchone()
        from src.repertoire.store import _row_to_node
        current = _row_to_node(row)
    assert list(reversed(sans)) == ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4"]


def test_load_indexes_sideline(tmp_path: Path) -> None:
    """3.Bc4 sideline should be queryable from the same parent as 3.Bb5."""
    db = tmp_path / "caissa.sqlite"
    pgn = _write(tmp_path, "white.pgn", SPANISH_PLUS_ITALIAN_PGN)
    conn = init_db(db)
    load_repertoire_into_db(conn, pgn, "white")

    fen_before_move3 = _board_after(["e4", "e5", "Nf3", "Nc6"]).fen()
    expected = find_expected_moves_from(conn, "white", fen_before_move3, "white")
    sans = [m.san for m in expected]
    # Both Bb5 (mainline) and Bc4 (sideline) — Bb5 first.
    assert sans == ["Bb5", "Bc4"]


def test_load_handles_transposition_dedupes_by_san(tmp_path: Path) -> None:
    """Italian Bc5 from two PGN paths must appear exactly once."""
    db = tmp_path / "caissa.sqlite"
    pgn = _write(tmp_path, "white.pgn", SPANISH_PLUS_ITALIAN_PGN)
    conn = init_db(db)
    load_repertoire_into_db(conn, pgn, "white")

    fen_before = _board_after(["e4", "e5", "Nf3", "Nc6", "Bc4"]).fen()
    expected = find_expected_moves_from(conn, "white", fen_before, "black")
    assert [m.san for m in expected] == ["Bc5"]


def test_load_replaces_existing_repertoire_for_color(tmp_path: Path) -> None:
    """Re-loading the same colour wipes the prior rows; no stale duplicates."""
    db = tmp_path / "caissa.sqlite"
    pgn1 = _write(tmp_path, "white.pgn", SPANISH_PLUS_ITALIAN_PGN)
    conn = init_db(db)
    load_repertoire_into_db(conn, pgn1, "white")
    count_first = conn.execute(
        "SELECT COUNT(*) AS c FROM repertoire_nodes"
    ).fetchone()["c"]

    # Reload smaller file.
    small = _write(tmp_path, "small.pgn", '[Event "Tiny"]\n\n1. d4 *')
    load_repertoire_into_db(conn, small, "white")
    count_second = conn.execute(
        "SELECT COUNT(*) AS c FROM repertoire_nodes"
    ).fetchone()["c"]
    assert count_second == 1  # only 1.d4
    assert count_second < count_first


def test_load_keeps_white_and_black_separate(tmp_path: Path) -> None:
    db = tmp_path / "caissa.sqlite"
    white = _write(tmp_path, "white.pgn", SPANISH_PLUS_ITALIAN_PGN)
    black = _write(tmp_path, "black.pgn", SINGLE_LINE_BLACK_PGN)
    conn = init_db(db)
    load_repertoire_into_db(conn, white, "white")
    load_repertoire_into_db(conn, black, "black")

    assert get_repertoire_id(conn, "white") != get_repertoire_id(conn, "black")
    # 1.e4 c6 lands at a FEN only present in the black rep.
    fen_after_c6 = _board_after(["e4", "c6"]).fen()
    assert find_node_by_fen_after(conn, "black", fen_after_c6) is not None
    assert find_node_by_fen_after(conn, "white", fen_after_c6) is None


def test_line_name_propagates(tmp_path: Path) -> None:
    db = tmp_path / "caissa.sqlite"
    pgn = _write(tmp_path, "white.pgn", SPANISH_PLUS_ITALIAN_PGN)
    conn = init_db(db)
    load_repertoire_into_db(conn, pgn, "white")

    # First move of the Spanish chapter must carry "Spanish mainline".
    node = find_node_by_fen_after(conn, "white", _board_after(["e4"]).fen())
    assert node is not None and node.line_name == "Spanish mainline"


# ---- Errors --------------------------------------------------------------

def test_load_raises_not_found(tmp_path: Path) -> None:
    db = tmp_path / "caissa.sqlite"
    conn = init_db(db)
    with pytest.raises(RepertoireNotFoundError):
        load_repertoire_into_db(conn, tmp_path / "nope.pgn", "white")


def test_load_raises_parse_error_on_empty(tmp_path: Path) -> None:
    db = tmp_path / "caissa.sqlite"
    pgn = _write(tmp_path, "empty.pgn", "")
    conn = init_db(db)
    with pytest.raises(RepertoireParseError):
        load_repertoire_into_db(conn, pgn, "white")


# ---- Query helpers -------------------------------------------------------

def test_find_node_returns_none_for_unknown_fen(tmp_path: Path) -> None:
    db = tmp_path / "caissa.sqlite"
    pgn = _write(tmp_path, "white.pgn", SPANISH_PLUS_ITALIAN_PGN)
    conn = init_db(db)
    load_repertoire_into_db(conn, pgn, "white")
    # 1.d4 is not in this repertoire.
    fen_after = _board_after(["d4"]).fen()
    assert find_node_by_fen_after(conn, "white", fen_after) is None


def test_find_expected_returns_empty_for_unknown_fen(tmp_path: Path) -> None:
    db = tmp_path / "caissa.sqlite"
    pgn = _write(tmp_path, "white.pgn", SPANISH_PLUS_ITALIAN_PGN)
    conn = init_db(db)
    load_repertoire_into_db(conn, pgn, "white")
    assert find_expected_moves_from(
        conn, "white", _board_after(["d4"]).fen(), "black"
    ) == []


def test_expected_move_is_immutable() -> None:
    em = ExpectedMove(san="e4", uci="e2e4", line_name="X")
    with pytest.raises((AttributeError, TypeError)):
        em.san = "d4"  # type: ignore[misc]
