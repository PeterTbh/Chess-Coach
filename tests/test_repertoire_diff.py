"""Tests for Module B diff (Feature 1.2) — SQLite-backed."""

from __future__ import annotations

import os
import time
from pathlib import Path

import chess
import chess.pgn
import pytest

from src.repertoire.diff import DiffError, diff_game
from src.repertoire.store import (
    RepertoireNotFoundError,
    init_db,
    load_repertoire_into_db,
)

# ---- Fixtures -------------------------------------------------------------

SPANISH_REP_PGN = """
[Event "Spanish mainline"]
[Site "?"]
[Result "*"]

1. e4 e5 2. Nf3 Nc6 3. Bb5 (3. Bc4 Bc5) a6 4. Ba4 Nf6 5. O-O Be7 6. Re1 b5 7. Bb3 d6 8. c3 O-O *
""".strip()

E4_ONLY_REP_PGN = """
[Event "King-pawn only"]
[Result "*"]

1. e4 *
""".strip()

BLACK_CARO_REP_PGN = """
[Event "Caro-Kann"]
[Result "*"]

1. e4 c6 2. d4 d5 3. Nc3 dxe4 4. Nxe4 *
""".strip()


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _played_pgn(
    *,
    moves: list[str],
    white: str = "alice",
    black: str = "bob",
    site: str = "https://lichess.org/abcd1234",
) -> str:
    """Build a played-game PGN with the given SAN sequence."""
    game = chess.pgn.Game()
    game.headers["White"] = white
    game.headers["Black"] = black
    game.headers["Site"] = site
    game.headers["Result"] = "*"
    node = game
    board = chess.Board()
    for san in moves:
        move = board.parse_san(san)
        node = node.add_variation(move)
        board.push(move)
    return str(game)


def _load_rep(tmp_path: Path, pgn_text: str, color: str):
    """Init DB in tmp dir, load the given repertoire text under `color`."""
    db = tmp_path / "caissa.sqlite"
    conn = init_db(db)
    rep_pgn = _write(tmp_path, f"{color}.pgn", pgn_text)
    load_repertoire_into_db(conn, rep_pgn, color)
    return conn, rep_pgn


# ---- Scope F1.2 acceptance ------------------------------------------------

def test_deviation_on_move_8_returns_move_number_8(tmp_path: Path) -> None:
    """Spanish mainline through white's move 7, then white plays Bc4 on move 8."""
    conn, _ = _load_rep(tmp_path, SPANISH_REP_PGN, "white")
    pgn = _played_pgn(
        moves=[
            "e4", "e5",
            "Nf3", "Nc6",
            "Bb5", "a6",
            "Ba4", "Nf6",
            "O-O", "Be7",
            "Re1", "b5",
            "Bb3", "d6",
            "Bc4",  # white's 8th, NOT in repertoire (rep prepares 8.c3)
        ],
        white="alice", black="bob",
    )
    report = diff_game(pgn, "alice", conn)

    assert report.deviation.occurred is True
    assert report.deviation.deviation_move_number == 8
    # 8th full move, white's halfmove → ply 15 (white has played 8 plies).
    assert report.deviation.deviation_ply == 15
    assert report.deviation.move_played_san == "Bc4"
    assert report.deviation.fen_before_deviation is not None
    assert report.deviation.move_played_uci is not None
    sans = [m.san for m in report.deviation.expected_moves_from_repertoire]
    assert "c3" in sans
    assert report.in_book_until_ply == 13  # last in-book user ply was Bb3
    assert report.user_color == "white"


def test_fully_in_book_returns_no_deviation(tmp_path: Path) -> None:
    """Player follows the Spanish mainline through move 8 — no deviation."""
    conn, _ = _load_rep(tmp_path, SPANISH_REP_PGN, "white")
    pgn = _played_pgn(
        moves=[
            "e4", "e5",
            "Nf3", "Nc6",
            "Bb5", "a6",
            "Ba4", "Nf6",
            "O-O", "Be7",
            "Re1", "b5",
            "Bb3", "d6",
            "c3", "O-O",
        ],
        white="alice", black="bob",
    )
    report = diff_game(pgn, "alice", conn)

    assert report.deviation.occurred is False
    assert report.deviation.deviation_ply is None
    assert report.in_book_until_ply == 15
    assert [m.ply for m in report.moves_in_book] == [1, 3, 5, 7, 9, 11, 13, 15]


def test_immediate_deviation_on_move_1(tmp_path: Path) -> None:
    """Repertoire prepares only 1.e4; played PGN opens 1.d4."""
    conn, _ = _load_rep(tmp_path, E4_ONLY_REP_PGN, "white")
    pgn = _played_pgn(moves=["d4"], white="alice", black="bob")
    report = diff_game(pgn, "alice", conn)

    assert report.deviation.occurred is True
    assert report.deviation.deviation_move_number == 1
    assert report.deviation.deviation_ply == 1
    assert report.deviation.move_played_san == "d4"
    assert report.in_book_until_ply == 0
    assert report.moves_in_book == []
    assert report.deviation.deepest_repertoire_match_node_id is None


# ---- Secondary coverage ---------------------------------------------------

def test_expected_moves_contains_all_alternatives(tmp_path: Path) -> None:
    """After 1.e4 e5 2.Nf3 Nc6 rep prepares both Bb5 (main) and Bc4 (sideline)."""
    conn, _ = _load_rep(tmp_path, SPANISH_REP_PGN, "white")
    pgn = _played_pgn(
        moves=["e4", "e5", "Nf3", "Nc6", "Nc3"],  # Nc3 is off-rep
        white="alice", black="bob",
    )
    report = diff_game(pgn, "alice", conn)
    assert report.deviation.occurred is True
    sans = sorted(m.san for m in report.deviation.expected_moves_from_repertoire)
    assert sans == ["Bb5", "Bc4"]


def test_black_repertoire_flags_blacks_first_off_book_move(tmp_path: Path) -> None:
    conn, _ = _load_rep(tmp_path, BLACK_CARO_REP_PGN, "black")
    pgn = _played_pgn(
        moves=["e4", "c6", "d4", "e6"],  # 2...e6 is off the Caro
        white="alice", black="bob",
    )
    report = diff_game(pgn, "bob", conn)
    assert report.user_color == "black"
    assert report.deviation.occurred is True
    assert report.deviation.move_played_san == "e6"
    assert report.deviation.deviation_move_number == 2
    # Black's 2nd halfmove = ply 4.
    assert report.deviation.deviation_ply == 4


def test_opponent_novelty_yields_empty_expected_moves(tmp_path: Path) -> None:
    """Strict scope reading: opponent off-rep -> user's next halfmove is flagged
    with empty expected_moves_from_repertoire."""
    conn, _ = _load_rep(tmp_path, SPANISH_REP_PGN, "white")
    pgn = _played_pgn(
        # 1...c5 is not in the rep (rep expects 1...e5). White's 2.Nf3 reaches
        # a position the rep never indexed.
        moves=["e4", "c5", "Nf3"],
        white="alice", black="bob",
    )
    report = diff_game(pgn, "alice", conn)
    assert report.deviation.occurred is True
    assert report.deviation.expected_moves_from_repertoire == []


def test_moves_in_book_only_contains_user_halfmoves(tmp_path: Path) -> None:
    conn, _ = _load_rep(tmp_path, SPANISH_REP_PGN, "white")
    pgn = _played_pgn(
        moves=["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4"],
        white="alice", black="bob",
    )
    report = diff_game(pgn, "alice", conn)
    assert report.deviation.occurred is False
    for entry in report.moves_in_book:
        assert entry.ply % 2 == 1  # white halfmoves only
        assert entry.user_color == "white"


def test_game_id_extracted_from_site_header(tmp_path: Path) -> None:
    conn, _ = _load_rep(tmp_path, SPANISH_REP_PGN, "white")
    pgn = _played_pgn(
        moves=["e4"], site="https://lichess.org/abcd1234",
        white="alice", black="bob",
    )
    report = diff_game(pgn, "alice", conn)
    assert report.game_id == "abcd1234"


def test_explicit_game_id_wins_over_site_header(tmp_path: Path) -> None:
    conn, _ = _load_rep(tmp_path, SPANISH_REP_PGN, "white")
    pgn = _played_pgn(moves=["e4"], site="https://lichess.org/abcd1234")
    report = diff_game(pgn, "alice", conn, game_id="override-123")
    assert report.game_id == "override-123"


def test_game_id_falls_back_to_unknown(tmp_path: Path) -> None:
    conn, _ = _load_rep(tmp_path, SPANISH_REP_PGN, "white")
    pgn = _played_pgn(moves=["e4"], site="")
    report = diff_game(pgn, "alice", conn)
    assert report.game_id == "unknown"


# ---- Error paths ----------------------------------------------------------

def test_pgn_unparseable_raises_diff_error(tmp_path: Path) -> None:
    conn, _ = _load_rep(tmp_path, SPANISH_REP_PGN, "white")
    with pytest.raises(DiffError, match="parsed"):
        diff_game("not a pgn at all", "alice", conn)


def test_username_not_in_headers_raises_diff_error(tmp_path: Path) -> None:
    conn, _ = _load_rep(tmp_path, SPANISH_REP_PGN, "white")
    pgn = _played_pgn(moves=["e4"], white="alice", black="bob")
    with pytest.raises(DiffError, match="not found"):
        diff_game(pgn, "carol", conn)


def test_diff_raises_when_repertoire_missing(tmp_path: Path) -> None:
    """No rows for this colour AND no PGN file at the explicit path."""
    db = tmp_path / "caissa.sqlite"
    conn = init_db(db)
    pgn = _played_pgn(moves=["e4"], white="alice", black="bob")
    missing = tmp_path / "no_such_file.pgn"
    with pytest.raises(RepertoireNotFoundError):
        diff_game(pgn, "alice", conn, repertoire_path=missing)


# ---- ensure_loaded mtime reload (exercised through diff) ------------------

def test_ensure_loaded_reloads_when_file_mtime_newer(tmp_path: Path) -> None:
    """Editing the source PGN must be picked up on the next diff call."""
    db = tmp_path / "caissa.sqlite"
    conn = init_db(db)
    rep_path = _write(tmp_path, "white.pgn", E4_ONLY_REP_PGN)
    pgn = _played_pgn(moves=["d4"], white="alice", black="bob")

    r1 = diff_game(pgn, "alice", conn, repertoire_path=rep_path)
    assert r1.deviation.occurred is True

    rep_path.write_text('[Event "QGD"]\n\n1. d4 *\n', encoding="utf-8")
    new_mtime = time.time() + 2
    os.utime(rep_path, (new_mtime, new_mtime))

    r2 = diff_game(pgn, "alice", conn, repertoire_path=rep_path)
    assert r2.deviation.occurred is False
