"""Rule-based FEN → structural tags classifier (Module A foundation).

Phase 3 deliverable. Tags feed Phase 4 RAG retrieval (the corpus is
keyed on the same vocabulary). Pure function over a FEN: no external
deps beyond python-chess.

Tag vocabulary (initial):
- ``opposite_side_castling`` — kings on opposite flanks (file diff ≥ 4).
- ``same_side_castling`` — kings on same flank, both castled.
- ``isolated_queen_pawn`` — exactly one d-pawn for either side, no
  c/e pawn of that colour.
- ``hanging_pawns`` — same side has c+d pawns with no b/e pawns of
  that colour and the c+d pawns on the same rank.
- ``queens_off`` — no queens on the board.
- ``opposite_colored_bishops`` — each side has exactly one bishop and
  they sit on opposite-colour squares.
- ``open_center`` / ``closed_center`` / ``semi_open_center`` — based on
  pawn count on d/e files.
- ``endgame_phase`` — total non-king material ≤ 24 (rough cutoff: a
  rook+minor each side, or queen+minor each side).
"""

from __future__ import annotations

import chess

from src.shared.chess_utils import validate_fen


def classify(fen: str) -> list[str]:
    """Return a sorted list of structural tags for ``fen``.

    Returns ``[]`` if the FEN is invalid.
    """
    if not validate_fen(fen):
        return []
    board = chess.Board(fen)
    tags: set[str] = set()

    tags.update(_castling_tags(board))
    tags.update(_pawn_structure_tags(board))
    tags.update(_material_tags(board))
    tags.update(_bishop_tags(board))

    return sorted(tags)


# ---- Helpers --------------------------------------------------------------

def _castling_tags(board: chess.Board) -> set[str]:
    wk = board.king(chess.WHITE)
    bk = board.king(chess.BLACK)
    if wk is None or bk is None:
        return set()
    wf = chess.square_file(wk)
    bf = chess.square_file(bk)
    # Heuristic: a "castled" king is off the e-file on its back rank.
    white_castled = chess.square_rank(wk) == 0 and wf in {1, 2, 6}
    black_castled = chess.square_rank(bk) == 7 and bf in {1, 2, 6}
    if not (white_castled and black_castled):
        return set()
    same_side = (wf <= 3) == (bf <= 3)
    return {"same_side_castling" if same_side else "opposite_side_castling"}


def _pawn_structure_tags(board: chess.Board) -> set[str]:
    tags: set[str] = set()
    files = {chess.WHITE: _file_pawn_count(board, chess.WHITE), chess.BLACK: _file_pawn_count(board, chess.BLACK)}

    for color in (chess.WHITE, chess.BLACK):
        f = files[color]
        # Isolated queen pawn: exactly one d-pawn, no c or e pawns of same colour.
        if f[3] == 1 and f[2] == 0 and f[4] == 0:
            tags.add("isolated_queen_pawn")
        # Hanging pawns: c+d duo with no b/e pawns of same colour, and same rank.
        if f[2] >= 1 and f[3] >= 1 and f[1] == 0 and f[4] == 0:
            ranks_c = _pawn_ranks_on_file(board, color, 2)
            ranks_d = _pawn_ranks_on_file(board, color, 3)
            if ranks_c and ranks_d and ranks_c[0] == ranks_d[0]:
                tags.add("hanging_pawns")

    # Center file pawn count for open/closed/semi-open classification.
    center_count = files[chess.WHITE][3] + files[chess.WHITE][4] + files[chess.BLACK][3] + files[chess.BLACK][4]
    if center_count == 0:
        tags.add("open_center")
    elif center_count >= 3:
        tags.add("closed_center")
    else:
        tags.add("semi_open_center")
    return tags


def _file_pawn_count(board: chess.Board, color: chess.Color) -> list[int]:
    counts = [0] * 8
    for sq in board.pieces(chess.PAWN, color):
        counts[chess.square_file(sq)] += 1
    return counts


def _pawn_ranks_on_file(
    board: chess.Board, color: chess.Color, file: int
) -> list[int]:
    return sorted(
        chess.square_rank(sq)
        for sq in board.pieces(chess.PAWN, color)
        if chess.square_file(sq) == file
    )


def _material_tags(board: chess.Board) -> set[str]:
    tags: set[str] = set()
    queens = (
        len(board.pieces(chess.QUEEN, chess.WHITE))
        + len(board.pieces(chess.QUEEN, chess.BLACK))
    )
    if queens == 0:
        tags.add("queens_off")

    values = {
        chess.PAWN: 1,
        chess.KNIGHT: 3,
        chess.BISHOP: 3,
        chess.ROOK: 5,
        chess.QUEEN: 9,
    }
    total = 0
    for piece_type, val in values.items():
        total += val * len(board.pieces(piece_type, chess.WHITE))
        total += val * len(board.pieces(piece_type, chess.BLACK))
    if total <= 24:
        tags.add("endgame_phase")
    return tags


def _bishop_tags(board: chess.Board) -> set[str]:
    wb = list(board.pieces(chess.BISHOP, chess.WHITE))
    bb = list(board.pieces(chess.BISHOP, chess.BLACK))
    if len(wb) == 1 and len(bb) == 1:
        # Square colour: (file + rank) % 2.
        wcolor = (chess.square_file(wb[0]) + chess.square_rank(wb[0])) % 2
        bcolor = (chess.square_file(bb[0]) + chess.square_rank(bb[0])) % 2
        if wcolor != bcolor:
            return {"opposite_colored_bishops"}
    return set()
