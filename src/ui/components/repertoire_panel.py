"""Panel 1 — Repertoire deviation (Feature 1.3).

Renders header + a Lichess-style compact movetext (move number on the
left, both halfmoves side-by-side) + the position at
``fen_before_deviation`` + a played-vs-expected table.

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
    all_plies: list[PlyView],
    user_color: str,
    *,
    evals: list[dict[str, Any] | None] | None = None,
) -> None:
    """Render Panel 1 in place. Side-effect-only.

    Mutates ``st.session_state["ply"]`` when a move is clicked and triggers
    a rerun so the position viewer below picks up the new ply.

    Args:
        diff: ``/repertoire/diff`` response payload, or ``None``.
        all_plies: full walk_pgn output, ply 0..N. The movetext renders
            both colours; only user halfmoves are status-coloured.
        user_color: ``"white"`` or ``"black"``.
        evals: optional parallel list of eval payloads. When present, each
            cell appends a compact eval annotation (`+0.30`, `#3`, etc.).
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

    # ---- Movetext list --------------------------------------------------
    move_plies = [p for p in all_plies if p.ply > 0]
    if move_plies:
        _render_movetext(
            move_plies,
            in_book_until_ply=in_book_until,
            deviation_ply=deviation_ply,
            user_color=user_color,
            evals=evals,
        )
    else:
        st.caption("No moves in this PGN.")

    # ---- Board + comparison table (only on deviation) -------------------
    if deviation["occurred"]:
        _render_deviation_detail(deviation)


def _render_movetext(
    move_plies: list[PlyView],
    *,
    in_book_until_ply: int,
    deviation_ply: int | None,
    user_color: str,
    evals: list[dict[str, Any] | None] | None,
) -> None:
    """Lichess-style full-move grid. One row per chess move number."""
    user_parity = 1 if user_color == "white" else 0
    clicked_ply: int | None = None

    # Group halfmoves into (white_view, black_view_or_None) pairs by move number.
    pairs: dict[int, dict[str, PlyView | None]] = {}
    for view in move_plies:
        move_number = (view.ply + 1) // 2
        side = "white" if view.ply % 2 == 1 else "black"
        pairs.setdefault(move_number, {"white": None, "black": None})[side] = view

    for move_number in sorted(pairs):
        white_view = pairs[move_number]["white"]
        black_view = pairs[move_number]["black"]
        cols = st.columns([1, 4, 4])
        cols[0].markdown(
            f"<div style='padding-top:0.45rem; color:#888;'>"
            f"{move_number}.</div>",
            unsafe_allow_html=True,
        )
        for col, view in [(cols[1], white_view), (cols[2], black_view)]:
            if view is None:
                col.markdown("&nbsp;", unsafe_allow_html=True)
                continue
            is_user_move = view.ply % 2 == user_parity
            status = (
                classify_halfmove(view.ply, in_book_until_ply, deviation_ply)
                if is_user_move
                else None
            )
            dot = _STATUS_DOT[status] if status else "·"
            label = _format_move_label(dot, view, evals)
            key = f"panel1_move_{view.ply}"
            if col.button(label, key=key, use_container_width=True):
                clicked_ply = view.ply

    if clicked_ply is not None:
        st.session_state["ply"] = clicked_ply
        st.rerun()


def _format_move_label(
    dot: str, view: PlyView, evals: list[dict[str, Any] | None] | None
) -> str:
    eval_str = ""
    if evals is not None and view.ply < len(evals):
        eval_str = _fmt_eval_compact(evals[view.ply])
    if eval_str:
        return f"{dot} {view.san}  {eval_str}"
    return f"{dot} {view.san}"


def _fmt_eval_compact(payload: dict[str, Any] | None) -> str:
    if payload is None:
        return ""
    if payload.get("mate") is not None:
        return f"#{payload['mate']}"
    cp = payload.get("cp")
    if cp is None:
        return ""
    sign = "+" if cp >= 0 else ""
    return f"{sign}{cp / 100:.2f}"


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
