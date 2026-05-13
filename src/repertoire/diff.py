"""Module B diff (Feature 1.2): first user deviation from the SQLite repertoire.

Walks the played PGN move-by-move. For each user halfmove we look up the
resulting FEN in ``repertoire_nodes``; the first miss is the deviation.
Opponent halfmoves are skipped — per scope they're not checked, and if
the opponent leaves prep the user's next halfmove simply won't find its
FEN in the store, which surfaces as a deviation with empty
``expected_moves_from_repertoire``. That edge case is intentional.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from pathlib import Path

import chess

from src.repertoire.store import (
    Color,
    ensure_loaded,
    find_expected_moves_from,
    find_node_by_fen_after,
)
from src.shared.chess_utils import extract_user_color, parse_pgn
from src.shared.schemas import (
    DeviationDetail,
    DeviationReport,
    MoveInBook,
    RepertoireExpectedMove,
)

logger = logging.getLogger(__name__)


class DiffError(Exception):
    """Inputs to :func:`diff_game` could not be reconciled."""


# Lichess / Chess.com game id from a [Site] URL header, e.g.
#   "https://lichess.org/abcd1234"           -> "abcd1234"
#   "https://www.chess.com/game/live/12345"  -> "12345"
_GAME_ID_TAIL_RE = re.compile(r"([A-Za-z0-9]+)/?$")


def _derive_game_id(pgn_game: chess.pgn.Game, fallback: str = "unknown") -> str:
    site = pgn_game.headers.get("Site", "").strip()
    if site:
        m = _GAME_ID_TAIL_RE.search(site)
        if m:
            return m.group(1)
    # Some PGNs carry an explicit GameId tag.
    explicit = pgn_game.headers.get("GameId", "").strip()
    return explicit or fallback


def diff_game(
    pgn: str,
    username: str,
    conn: sqlite3.Connection,
    *,
    game_id: str | None = None,
    repertoire_path: Path | str | None = None,
) -> DeviationReport:
    """Compare a played PGN against the SQLite repertoire for the user's colour.

    The repertoire is lazy-loaded from ``repertoire_path`` (or the default
    location) if the store has no rows yet, or if the PGN file is newer
    than the last load.

    Args:
        pgn: Full PGN of the played game.
        username: User's username, matched (case-insensitive) against
            ``[White]`` / ``[Black]`` PGN headers.
        conn: SQLite connection produced by ``store.init_db``.
        game_id: Optional override. Auto-derived from ``[Site]`` or
            ``[GameId]`` if missing.
        repertoire_path: Optional override for the source PGN to lazy-load.
    """
    game = parse_pgn(pgn)
    # python-chess returns a Game with placeholder "?" headers and zero
    # moves for garbage input — treat that as unparseable.
    if game is None or not list(game.mainline_moves()):
        raise DiffError("PGN could not be parsed")

    user_color = extract_user_color(pgn, username)
    if user_color is None:
        raise DiffError(
            f"Username {username!r} not found in PGN [White]/[Black] headers"
        )

    ensure_loaded(conn, user_color, repertoire_path)

    resolved_game_id = game_id or _derive_game_id(game)
    user_turn = chess.WHITE if user_color == "white" else chess.BLACK

    moves_in_book: list[MoveInBook] = []
    in_book_until_ply = 0
    deepest_match_id: int | None = None

    board = game.board()
    for move in game.mainline_moves():
        is_user_turn = board.turn == user_turn

        if not is_user_turn:
            board.push(move)
            continue

        fen_before = board.fen()
        try:
            san = board.san(move)
        except (ValueError, AssertionError) as exc:
            raise DiffError(f"PGN contains illegal move: {move.uci()}") from exc
        uci = move.uci()
        move_number_before = board.fullmove_number

        board.push(move)
        fen_after = board.fen()
        ply_after = board.ply()

        node = find_node_by_fen_after(conn, user_color, fen_after)
        if node is None:
            return DeviationReport(
                game_id=resolved_game_id,
                user_color=user_color,
                in_book_until_ply=in_book_until_ply,
                deviation=DeviationDetail(
                    occurred=True,
                    deviation_ply=ply_after,
                    deviation_move_number=move_number_before,
                    move_played_san=san,
                    move_played_uci=uci,
                    fen_before_deviation=fen_before,
                    expected_moves_from_repertoire=_expected(
                        conn, user_color, fen_before
                    ),
                    deepest_repertoire_match_node_id=deepest_match_id,
                ),
                moves_in_book=moves_in_book,
            )

        # In book — record and continue.
        in_book_until_ply = ply_after
        deepest_match_id = node.id
        moves_in_book.append(
            MoveInBook(ply=ply_after, san=san, user_color=user_color)
        )

    # Walked the entire game with no user deviation.
    return DeviationReport(
        game_id=resolved_game_id,
        user_color=user_color,
        in_book_until_ply=in_book_until_ply,
        deviation=DeviationDetail(
            occurred=False,
            deviation_ply=None,
            deviation_move_number=None,
            move_played_san=None,
            move_played_uci=None,
            fen_before_deviation=None,
            expected_moves_from_repertoire=[],
            deepest_repertoire_match_node_id=deepest_match_id,
        ),
        moves_in_book=moves_in_book,
    )


def _expected(
    conn: sqlite3.Connection, user_color: Color, fen_before: str
) -> list[RepertoireExpectedMove]:
    return [
        RepertoireExpectedMove(san=em.san, uci=em.uci, line_name=em.line_name)
        for em in find_expected_moves_from(conn, user_color, fen_before, user_color)
    ]
