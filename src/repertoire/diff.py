"""Module B diff: detect first user deviation from a repertoire.

Walks the played PGN move-by-move alongside the FEN-keyed
:class:`~src.repertoire.parser.Repertoire` index produced by Phase 2.
Reports the **first move** the user played that the repertoire did not
prepare for, or ``deviated=False`` if the user stayed in book throughout
(or the repertoire/game simply ran out).

Opponent novelties (a move outside repertoire by the *opponent*) are not
deviations and do not error — the walk continues; if the resulting
position is no longer indexed, we exit cleanly with no deviation.
"""

from __future__ import annotations

import logging

import chess

from src.repertoire.parser import Repertoire
from src.shared.chess_utils import extract_user_color, parse_pgn
from src.shared.schemas import RepertoireDeviation

logger = logging.getLogger(__name__)


class DiffError(Exception):
    """Inputs to :func:`diff_game` could not be reconciled."""


def diff_game(
    pgn: str,
    username: str,
    repertoire: Repertoire,
) -> RepertoireDeviation:
    """Compare a played game against a repertoire and report first deviation.

    Args:
        pgn: Full PGN text of the played game.
        username: User's username as it appears in the PGN ``[White]`` or
            ``[Black]`` header. Match is case-insensitive.
        repertoire: Indexed repertoire whose ``color`` must match the side
            ``username`` played.

    Returns:
        :class:`RepertoireDeviation`. ``deviated`` is True only when the
        user (not opponent) played a move outside their repertoire from a
        position the repertoire actually covers.

    Raises:
        DiffError: PGN is unparseable, username not in headers, or
            repertoire color does not match user's color.
    """
    game = parse_pgn(pgn)
    if game is None:
        raise DiffError("PGN could not be parsed")

    user_color = extract_user_color(pgn, username)
    if user_color is None:
        raise DiffError(
            f"Username {username!r} not found in PGN [White]/[Black] headers"
        )
    if user_color != repertoire.color:
        raise DiffError(
            f"Repertoire is for {repertoire.color}, but {username!r} "
            f"played {user_color}"
        )

    user_turn = chess.WHITE if user_color == "white" else chess.BLACK
    board = game.board()
    last_known_line_name: str | None = None

    for move in game.mainline_moves():
        parent_fen = board.fen()
        is_user_turn = board.turn == user_turn

        if is_user_turn:
            if not repertoire.covers(parent_fen):
                # User's position never indexed — repertoire ended (or
                # opponent took us into uncharted territory). Not a
                # deviation by the user.
                return _no_deviation(last_known_line_name)

            expected = repertoire.expected_at(parent_fen)
            played_san = board.san(move)
            match = next((em for em in expected if em.san == played_san), None)

            if match is None:
                # First user move outside repertoire — this is the deviation.
                return RepertoireDeviation(
                    deviated=True,
                    deviation_move_number=board.fullmove_number,
                    move_played=played_san,
                    move_expected=expected[0].san,  # mainline first
                    fen_at_deviation=parent_fen,
                    repertoire_line_name=(
                        expected[0].line_name or last_known_line_name
                    ),
                )

            # User stayed in book — track which line they're following.
            if match.line_name is not None:
                last_known_line_name = match.line_name

        board.push(move)

    # Game ended with user in book throughout (or out of book via
    # opponent only). No deviation by the user.
    return _no_deviation(last_known_line_name)


def _no_deviation(line_name: str | None) -> RepertoireDeviation:
    return RepertoireDeviation(
        deviated=False,
        deviation_move_number=None,
        move_played=None,
        move_expected=None,
        fen_at_deviation=None,
        repertoire_line_name=line_name,
    )
