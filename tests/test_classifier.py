"""Tests for src.advisor.classifier (Phase 3 Slice 5)."""

from __future__ import annotations

from src.advisor.classifier import classify
from src.shared.chess_utils import STARTING_FEN


def test_classify_invalid_fen_returns_empty() -> None:
    assert classify("garbage") == []


def test_classify_starting_position() -> None:
    tags = classify(STARTING_FEN)
    # Closed center (4 central pawns), queens on, no castling yet.
    assert "closed_center" in tags
    assert "queens_off" not in tags
    assert "endgame_phase" not in tags


def test_classify_opposite_side_castling() -> None:
    # White castled long (Kc1), black castled short (Kg8).
    fen = "r4rk1/ppp2ppp/2n2n2/3pp3/3PP3/2N2N2/PPP2PPP/2KR3R w - - 0 1"
    tags = classify(fen)
    assert "opposite_side_castling" in tags


def test_classify_same_side_castling() -> None:
    fen = "r4rk1/ppp2ppp/2n2n2/3pp3/3PP3/2N2N2/PPP2PPP/R4RK1 w - - 0 1"
    tags = classify(fen)
    assert "same_side_castling" in tags


def test_classify_isolated_queen_pawn() -> None:
    # White has d-pawn, no c or e. Black has c+d+e + flank pawns.
    fen = "rnbqkbnr/ppp1pppp/8/8/3P4/8/PP3PPP/RNBQKBNR w KQkq - 0 1"
    tags = classify(fen)
    assert "isolated_queen_pawn" in tags


def test_classify_queens_off() -> None:
    fen = "rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNB1KBNR w KQkq - 0 1"
    tags = classify(fen)
    assert "queens_off" in tags


def test_classify_endgame_phase() -> None:
    # K+R+P vs K+R+P
    fen = "4k3/4p3/8/8/8/8/4P3/4K3 w - - 0 1"
    # Add rooks to make it K+R vs K+R.
    fen = "4k2r/4p3/8/8/8/8/4P3/4K2R w - - 0 1"
    tags = classify(fen)
    assert "endgame_phase" in tags
    assert "queens_off" in tags


def test_classify_open_center() -> None:
    # No pawns on d/e files for either side.
    fen = "rnbqkbnr/ppp2ppp/8/8/8/8/PPP2PPP/RNBQKBNR w KQkq - 0 1"
    tags = classify(fen)
    assert "open_center" in tags


def test_classify_opposite_colored_bishops() -> None:
    # Each side has one bishop on opposite colours; nothing else but K+P.
    fen = "4k3/4p3/8/8/3B4/8/4P3/3b3K w - - 0 1"
    tags = classify(fen)
    assert "opposite_colored_bishops" in tags


def test_classify_returns_sorted_list() -> None:
    tags = classify(STARTING_FEN)
    assert tags == sorted(tags)


def test_classify_hanging_pawns() -> None:
    # White has c+d on rank 4 with no b or e pawns of own colour.
    fen = "rnbqkbnr/pp3ppp/8/8/2PP4/8/P4PPP/RNBQKBNR w KQkq - 0 1"
    tags = classify(fen)
    assert "hanging_pawns" in tags
