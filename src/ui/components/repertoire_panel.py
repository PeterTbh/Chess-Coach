"""Panel 1 — Repertoire deviation (Feature 1.3).

Renders header + clickable user-halfmove list (green/red/grey) + the
position at ``fen_before_deviation`` + a played-vs-expected table.

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

_STATUS_DOT: dict[HalfmoveStatus, str] = {
    "in_book": "🟢",
    "deviation": "🔴",
    "after": "⚪",
}

_BUTTONS_PER_ROW = 4


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


def _render_board_svg(fen: str, last_move_uci: str | None = None) -> str:
    board = chess.Board(fen)
    last_move = chess.Move.from_uci(last_move_uci) if last_move_uci else None
    return chess.svg.board(board, lastmove=last_move, size=380, coordinates=True)


def render_deviation_panel(
    diff: dict[str, Any] | None,
    user_halfmoves: list[PlyView],
    user_color: str,
) -> None:
    """Render Panel 1 in place. Side-effect-only.

    Mutates ``st.session_state["ply"]`` when a move button is clicked and
    triggers a rerun so the position viewer below picks up the new ply.
    """
    st.subheader("Panel 1 — Repertoire deviation")

    if diff is None:
        st.caption(
            "Place your repertoire at "
            "`data/repertoires/white.pgn` or `black.pgn` to enable."
        )
        return

    deviation = diff["deviation"]
    in_book_until = int(diff.get("in_book_until_ply", 0))
    deviation_ply: int | None = deviation.get("deviation_ply")

    # ---- Header banner --------------------------------------------------
    if deviation["occurred"]:
        st.error(
            f"You deviated from your **{user_color}** repertoire on move "
            f"**{deviation['deviation_move_number']}**."
        )
    else:
        last_move_number = (in_book_until + 1) // 2
        if last_move_number > 0:
            st.success(f"You stayed in prep through move {last_move_number}.")
        else:
            st.info("No user moves recorded yet.")

    # ---- Move list ------------------------------------------------------
    if user_halfmoves:
        _render_move_buttons(
            user_halfmoves,
            in_book_until_ply=in_book_until,
            deviation_ply=deviation_ply,
        )
    else:
        st.caption("No user halfmoves in this PGN.")

    # ---- Board + comparison table (only on deviation) -------------------
    if deviation["occurred"]:
        _render_deviation_detail(deviation)


def _render_move_buttons(
    halfmoves: list[PlyView],
    *,
    in_book_until_ply: int,
    deviation_ply: int | None,
) -> None:
    """Grid of buttons, one per user halfmove. Click → jump position viewer."""
    rows = [
        halfmoves[i : i + _BUTTONS_PER_ROW]
        for i in range(0, len(halfmoves), _BUTTONS_PER_ROW)
    ]
    clicked_ply: int | None = None
    for row in rows:
        cols = st.columns(_BUTTONS_PER_ROW)
        for col, view in zip(cols, row, strict=False):
            status = classify_halfmove(view.ply, in_book_until_ply, deviation_ply)
            dot = _STATUS_DOT[status]
            move_number = (view.ply + 1) // 2
            label = f"{dot} {move_number}. {view.san}"
            key = f"panel1_move_{view.ply}"
            if col.button(label, key=key, use_container_width=True):
                clicked_ply = view.ply

    if clicked_ply is not None:
        st.session_state["ply"] = clicked_ply
        st.rerun()


def _render_deviation_detail(deviation: dict[str, Any]) -> None:
    fen_before = deviation.get("fen_before_deviation")
    if not fen_before:
        return

    board_col, table_col = st.columns([1, 1])
    with board_col:
        st.markdown(_render_board_svg(fen_before), unsafe_allow_html=True)
        st.caption("Position before your move.")

    with table_col:
        played = deviation.get("move_played_san") or "—"
        st.markdown(f"**You played:** `{played}`")
        expected = deviation.get("expected_moves_from_repertoire") or []
        if expected:
            st.markdown("**Repertoire prepares:**")
            for m in expected:
                line = m.get("line_name")
                suffix = f" *({line})*" if line else ""
                st.markdown(f"- **{m['san']}**{suffix}")
        else:
            st.markdown(
                "_Opponent left prep first — no prepared move from this position._"
            )
