"""Panel 1 — Repertoire deviation (Feature 1.3).

Renders header + a two-board side-by-side comparison: the wrong move you
played (left, red highlight) vs. the repertoire's prepared move (right,
green highlight). When the repertoire prepares multiple alternatives a
selectbox above the boards picks which one to show.

The classifier helper is intentionally pure (no Streamlit), so it can be
unit-tested in isolation.
"""

from __future__ import annotations

from typing import Any, Literal

import chess
import chess.svg
import streamlit as st

from src.ui.components.game_walker import PlyView

HalfmoveStatus = Literal["in_book", "deviation", "after"]

_TINT_RED = "#ff6b6b"
_TINT_GREEN = "#51cf66"
_BOARD_SIZE = 300


def classify_halfmove(
    ply: int,
    in_book_until_ply: int,
    deviation_ply: int | None,
) -> HalfmoveStatus:
    """Status of a single user halfmove relative to the deviation report."""
    if deviation_ply is not None and ply == deviation_ply:
        return "deviation"
    if deviation_ply is not None and ply > deviation_ply:
        return "after"
    if ply <= in_book_until_ply:
        return "in_book"
    # Defensive fallback: ply beyond in_book_until_ply but no deviation_ply.
    # Treat as "after" (shouldn't occur in normal diff output).
    return "after"


def filter_user_halfmoves(
    all_plies: list[PlyView], user_color: str
) -> list[PlyView]:
    """Return only the plies where the user played the move."""
    parity = 1 if user_color == "white" else 0
    return [p for p in all_plies if p.ply > 0 and p.ply % 2 == parity]


def _render_move_board(
    fen_before: str, uci: str, tint: str, *, size: int = _BOARD_SIZE
) -> str:
    """Render position **after** the move with from/to squares painted in ``tint``."""
    board = chess.Board(fen_before)
    move = chess.Move.from_uci(uci)
    if move in board.legal_moves:
        board.push(move)
    fill = {move.from_square: tint, move.to_square: tint}
    return chess.svg.board(board, fill=fill, size=size, coordinates=True)


def render_deviation_panel(
    diff: dict[str, Any] | None,
    user_color: str,
) -> None:
    """Render Panel 1 in place. Side-effect-only."""
    st.subheader("Panel 1 — Repertoire deviation")

    if diff is None:
        st.caption(
            "Place your repertoire at "
            "`data/repertoires/white.pgn` or `black.pgn` to enable."
        )
        return

    deviation = diff["deviation"]
    in_book_until = int(diff.get("in_book_until_ply", 0))
    moves_in_book = diff.get("moves_in_book") or []

    # ---- Header banner --------------------------------------------------
    if deviation["occurred"]:
        n = len(moves_in_book)
        if n == 0:
            st.error(f"You deviated from your **{user_color}** repertoire on your first move.")
        elif n == 1:
            st.error("You played **1 move in prep** before deviating.")
        else:
            st.error(f"You played **{n} moves in prep** before deviating.")
        _render_deviation_detail(deviation)
    else:
        last_move_number = (in_book_until + 1) // 2
        if last_move_number > 0:
            st.success(f"You stayed in prep through move {last_move_number}.")
        else:
            st.info("No user moves recorded yet.")


def _render_deviation_detail(deviation: dict[str, Any]) -> None:
    fen_before = deviation.get("fen_before_deviation")
    played_san = deviation.get("move_played_san") or "?"
    played_uci = deviation.get("move_played_uci")
    expected = deviation.get("expected_moves_from_repertoire") or []

    if not fen_before or not played_uci:
        return

    # Pick which alternative to display on the right.
    selected = _select_alternative(expected)

    # Layout: two boards if expected available, single board otherwise.
    if selected is None:
        st.markdown(
            _render_move_board(fen_before, played_uci, _TINT_RED),
            unsafe_allow_html=True,
        )
        st.markdown(f"You played: **{played_san}**")
        return

    left_col, right_col = st.columns([1, 1])
    with left_col:
        st.markdown(
            _render_move_board(fen_before, played_uci, _TINT_RED),
            unsafe_allow_html=True,
        )
        st.markdown(f"You played: **{played_san}**")
    with right_col:
        st.markdown(
            _render_move_board(fen_before, selected["uci"], _TINT_GREEN),
            unsafe_allow_html=True,
        )
        line = selected.get("line_name")
        suffix = f" *({line})*" if line else ""
        st.markdown(f"Repertoire: **{selected['san']}**{suffix}")


def _select_alternative(expected: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the chosen alternative; ``None`` if the list is empty.

    Surfaces a selectbox above the boards when there is more than one option.
    """
    if not expected:
        return None
    if len(expected) == 1:
        return expected[0]
    labels = [
        f"{m['san']}" + (f" ({m['line_name']})" if m.get("line_name") else "")
        for m in expected
    ]
    idx = st.selectbox(
        "Choose repertoire alternative:",
        options=list(range(len(expected))),
        format_func=lambda i: labels[i],
        key="panel1_alt_select",
    )
    return expected[idx]
