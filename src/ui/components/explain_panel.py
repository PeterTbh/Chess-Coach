"""Panel 3 — Strategic commentary (Feature 2).

Renders an auto-suggested checklist of critical user halfmoves, lets the
user adjust the selection, and on submit calls ``/advise`` once per ply.
Each result is rendered as a card with board thumbnail + explanation +
citations + model attribution.

Results are cached for the Streamlit session by ``(fen, sorted_tags)`` so
re-renders don't re-bill the LLM. Single-ply failures show inline instead
of aborting the whole panel.
"""

from __future__ import annotations

import logging
from typing import Any

import chess
import chess.svg
import httpx
import streamlit as st

from src.advisor.critical_moments import pick_critical_moments
from src.ui.components.game_walker import PlyView

logger = logging.getLogger(__name__)

ADVISE_TIMEOUT_SECONDS = 60.0


def render_explain_panel(
    *,
    api_url: str,
    game: dict[str, Any],
    plies: list[PlyView],
    user_halfmoves: list[PlyView],
    diff: dict[str, Any] | None,
    evals: list[dict[str, Any] | None] | None,
) -> None:
    st.subheader("Panel 3 — Strategic commentary")

    if not user_halfmoves:
        st.caption("No user halfmoves in this game.")
        return

    if not evals:
        st.caption("Click *Compute evaluations* in Panel 2 first to enable explanations.")
        return

    auto_picks = set(
        pick_critical_moments(diff, evals, game["user_color"])
    )

    # ---- Checkbox grid -------------------------------------------------
    st.markdown(
        "Pick positions to explain. **Auto-suggested** moments are pre-checked "
        "(deviation + biggest eval drops). Uncheck or add as you like."
    )
    selected = _render_checkboxes(user_halfmoves, auto_picks, evals)

    if not selected:
        st.caption("Select at least one position above, then click *Explain selected*.")
        return

    if not st.button("Explain selected positions", type="primary"):
        return

    # ---- Card rendering ------------------------------------------------
    for ply in selected:
        _render_card(api_url=api_url, ply=ply, plies=plies, evals=evals, game=game)


# ---- Internals -----------------------------------------------------------

def _render_checkboxes(
    user_halfmoves: list[PlyView],
    auto_picks: set[int],
    evals: list[dict[str, Any] | None],
) -> list[int]:
    """4-column grid; returns the plies the user kept checked."""
    selected: list[int] = []
    rows = [user_halfmoves[i : i + 4] for i in range(0, len(user_halfmoves), 4)]
    for row in rows:
        cols = st.columns(4)
        for col, view in zip(cols, row, strict=False):
            move_number = (view.ply + 1) // 2
            cp = _fmt_cp(evals[view.ply]) if view.ply < len(evals) else "—"
            label = f"{move_number}. {view.san}  ·  {cp}"
            default = view.ply in auto_picks
            key = f"explain_pick_{view.ply}"
            if col.checkbox(label, value=default, key=key):
                selected.append(view.ply)
    return selected


def _render_card(
    *,
    api_url: str,
    ply: int,
    plies: list[PlyView],
    evals: list[dict[str, Any] | None],
    game: dict[str, Any],
) -> None:
    if ply >= len(plies):
        return
    view = plies[ply]
    move_number = (view.ply + 1) // 2
    eval_before = _fmt_cp(evals[ply - 1]) if ply - 1 < len(evals) else "—"
    eval_after = _fmt_cp(evals[ply]) if ply < len(evals) else "—"

    st.divider()
    st.markdown(
        f"### Move {move_number}: **{view.san}**  ·  eval {eval_before} → {eval_after}"
    )

    fen_before = plies[ply - 1].fen if ply - 1 >= 0 else plies[0].fen
    body = _fetch_advise_cached(api_url, fen_before, game["user_color"])

    board_col, text_col = st.columns([1, 1])
    with board_col:
        st.markdown(_render_board_svg(fen_before, view.move_uci), unsafe_allow_html=True)
        st.caption("Position before this move.")

    with text_col:
        if isinstance(body, _AdviseError):
            st.error(body.message)
            return
        st.markdown(body["explanation"])
        st.caption(f"Model: {body.get('model_used', '?')}")
        cits = body.get("citations") or []
        if cits:
            st.markdown("**Citations:**")
            for c in cits:
                st.markdown(f"- {c['source']}, p.{c['page']}: *{c['snippet'][:140]}…*")


@st.cache_data(show_spinner=False)
def _fetch_advise_cached(
    api_url: str, fen: str, user_color: str
) -> dict[str, Any] | _AdviseError:
    """Single-call wrapper around POST /advise. Cached by (fen, user_color)."""
    try:
        with st.spinner(f"Generating explanation for {fen[:32]}…"):
            resp = httpx.post(
                f"{api_url}/advise",
                json={"fen": fen, "user_color": user_color},
                timeout=ADVISE_TIMEOUT_SECONDS,
            )
    except httpx.HTTPError as exc:
        return _AdviseError(f"Network error reaching {api_url}/advise: {exc}")
    if resp.status_code == 200:
        return resp.json()
    try:
        detail = resp.json().get("detail", resp.text)
    except ValueError:
        detail = resp.text
    return _AdviseError(f"/advise HTTP {resp.status_code}: {detail}")


def _render_board_svg(fen: str, last_move_uci: str | None) -> str:
    board = chess.Board(fen)
    last_move = chess.Move.from_uci(last_move_uci) if last_move_uci else None
    return chess.svg.board(board, lastmove=last_move, size=300, coordinates=True)


def _fmt_cp(eval_payload: dict[str, Any] | None) -> str:
    if eval_payload is None:
        return "—"
    if eval_payload.get("mate") is not None:
        return f"#{eval_payload['mate']}"
    cp = eval_payload.get("cp")
    if cp is None:
        return "—"
    sign = "+" if cp >= 0 else ""
    return f"{sign}{cp / 100:.2f}"


class _AdviseError:
    """Sentinel for cards that failed to render — keeps the cache happy."""

    def __init__(self, message: str) -> None:
        self.message = message
