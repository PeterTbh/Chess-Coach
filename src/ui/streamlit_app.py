"""Caissa — Streamlit landing page.

Phase 3: paste a Lichess/Chess.com URL → render game metadata, move
navigation, repertoire-deviation panel, and engine-evaluation panel.
Strategic-commentary panel (Phase 4) remains a placeholder.
"""

from __future__ import annotations

import os
from typing import Any

import chess
import chess.svg
import httpx
import streamlit as st

from src.ui.components.explain_panel import render_explain_panel
from src.ui.components.game_walker import PlyView, walk_pgn
from src.ui.components.repertoire_panel import (
    filter_user_halfmoves,
    render_deviation_panel,
)

API_URL = os.environ.get("API_URL", "http://localhost:8000")
FETCH_TIMEOUT_SECONDS = 15.0
DIFF_TIMEOUT_SECONDS = 15.0
EVAL_TIMEOUT_SECONDS = 10.0

st.set_page_config(page_title="Caissa", page_icon="♞", layout="wide")

st.title("Caissa ♞")
st.caption("Personal chess improvement system — local post-mortem")


# ---- Cached helpers -------------------------------------------------------


@st.cache_data(show_spinner=False)
def _walk_pgn_cached(pgn: str) -> list[PlyView]:
    return walk_pgn(pgn)


@st.cache_data(show_spinner=False)
def _fetch_eval_cached(fen: str, source: str) -> dict[str, Any] | None:
    """Call /eval; return parsed body on 200, None on 404, raise on others."""
    try:
        resp = httpx.post(
            f"{API_URL}/eval",
            json={"fen": fen, "source": source},
            timeout=EVAL_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        st.warning(f"/eval network error for {fen[:40]}…: {exc}")
        return None
    if resp.status_code == 200:
        return resp.json()
    if resp.status_code == 404:
        return None
    st.warning(f"/eval HTTP {resp.status_code}: {resp.text[:120]}")
    return None


def _post_diff(pgn: str, username: str) -> dict[str, Any] | None:
    try:
        resp = httpx.post(
            f"{API_URL}/repertoire/diff",
            json={"pgn": pgn, "username": username},
            timeout=DIFF_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        st.error(f"/repertoire/diff network error: {exc}")
        return None
    if resp.status_code == 200:
        return resp.json()
    try:
        detail = resp.json().get("detail", resp.text)
    except ValueError:
        detail = resp.text
    if resp.status_code == 404:
        st.info(f"Repertoire missing: {detail}")
    else:
        st.error(f"/repertoire/diff HTTP {resp.status_code}: {detail}")
    return None


def _render_board_svg(fen: str, last_move_uci: str | None) -> str:
    board = chess.Board(fen)
    last_move = chess.Move.from_uci(last_move_uci) if last_move_uci else None
    return chess.svg.board(
        board, lastmove=last_move, size=380, coordinates=True
    )


def _format_eval(eval_payload: dict[str, Any] | None) -> str:
    if eval_payload is None:
        return "—"
    if eval_payload.get("mate") is not None:
        m = eval_payload["mate"]
        return f"#{m}" if m > 0 else f"#{m}"
    cp = eval_payload.get("cp")
    if cp is None:
        return "—"
    sign = "+" if cp >= 0 else ""
    return f"{sign}{cp / 100:.2f}"


# ---- Game fetch form ------------------------------------------------------

with st.form("fetch_form"):
    url = st.text_input(
        "Game URL",
        placeholder="https://lichess.org/abcd1234  or  https://chess.com/game/live/12345678",
    )
    submitted = st.form_submit_button("Fetch game")

if submitted and url:
    try:
        resp = httpx.post(
            f"{API_URL}/game/fetch",
            json={"url": url},
            timeout=FETCH_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        st.error(f"Could not reach API at {API_URL}: {exc}")
    else:
        if resp.status_code == 200:
            st.session_state["game"] = resp.json()
            # Reset per-game state when a new game is loaded.
            st.session_state.pop("ply", None)
            st.session_state.pop("evals", None)
            st.session_state.pop("diff", None)
        else:
            try:
                detail = resp.json().get("detail", resp.text)
            except ValueError:
                detail = resp.text
            st.error(f"Fetch failed (HTTP {resp.status_code}): {detail}")


# ---- Metadata + main view -------------------------------------------------

game: dict[str, Any] | None = st.session_state.get("game")

if game:
    st.subheader("Game metadata")
    cols = st.columns(4)
    cols[0].metric("Site", game["site"])
    cols[1].metric("White", game["white_username"])
    cols[2].metric("Black", game["black_username"])
    cols[3].metric("Result", game["result"])

    tc_cols = st.columns(4)
    tc_cols[0].metric("Time class", game.get("time_class", "unknown"))
    tc_cols[1].metric("Time control", game.get("time_control") or "?")
    tc_cols[2].metric("You played", game["user_color"])
    tc_cols[3].metric("Game ID", game["game_id"])

    with st.expander("PGN"):
        st.code(game["pgn"], language="text")

    # ---- Walk plies once; reused by Panel 1 + position viewer + Panel 2 --

    plies = _walk_pgn_cached(game["pgn"])
    if not plies:
        st.warning("PGN could not be walked — no moves to navigate.")
    else:
        # ---- Panel 1: Repertoire deviation -------------------------------

        st.divider()

        if "diff" not in st.session_state:
            user_color = game["user_color"]
            username = game[f"{user_color}_username"]
            with st.spinner(f"Comparing against {user_color}.pgn…"):
                st.session_state["diff"] = _post_diff(game["pgn"], username)

        diff = st.session_state.get("diff")
        user_halfmoves = filter_user_halfmoves(plies, game["user_color"])
        render_deviation_panel(diff, user_halfmoves, game["user_color"])

        # ---- Position viewer (slider + board) ----------------------------

        st.divider()
        st.subheader("Position viewer")

        max_ply = len(plies) - 1
        default_ply = min(st.session_state.get("ply", 0), max_ply)
        selected_ply = st.slider(
            "Move",
            min_value=0,
            max_value=max_ply,
            value=default_ply,
            help="0 = starting position; increments are half-moves (plies).",
        )
        st.session_state["ply"] = selected_ply
        view = plies[selected_ply]

        board_col, info_col = st.columns([2, 3])
        with board_col:
            svg = _render_board_svg(view.fen, view.move_uci)
            st.markdown(svg, unsafe_allow_html=True)

        with info_col:
            label = (
                f"After {view.fullmove_number - 1}…{view.san}"
                if view.san and view.side_to_move == "white"
                else (
                    f"After {view.fullmove_number}.{view.san}"
                    if view.san
                    else "Starting position"
                )
            )
            st.markdown(f"**{label}**  ·  ply {view.ply} / {max_ply}")
            st.caption(f"FEN: `{view.fen}`")
            if view.move_uci:
                st.caption(f"Last move: `{view.move_uci}`")

        # ---- Panel 2: Engine evaluation ----------------------------------

        st.divider()
        st.subheader("Panel 2 — Engine evaluation")

        if st.button(
            "Compute evaluations",
            help=(
                "Fetches /eval for every ply. Lichess Cloud Eval first; "
                "Stockfish fallback for unknown positions."
            ),
        ):
            evals: list[dict[str, Any] | None] = []
            progress = st.progress(0.0, text="Evaluating…")
            for i, pv in enumerate(plies):
                evals.append(_fetch_eval_cached(pv.fen, "any"))
                progress.progress((i + 1) / len(plies))
            progress.empty()
            st.session_state["evals"] = evals

        evals = st.session_state.get("evals")
        if evals is None:
            st.caption("Click *Compute evaluations* to fetch /eval for every ply.")
        else:
            current = evals[selected_ply] if selected_ply < len(evals) else None
            ev_cols = st.columns(3)
            ev_cols[0].metric("Eval at this ply", _format_eval(current))
            if current and current.get("best_move_uci"):
                ev_cols[1].metric("Best move (UCI)", current["best_move_uci"])
                ev_cols[2].metric("Source", current.get("source", "?"))

            # Eval graph: cp series across plies, missing → 0.
            cps: list[float] = []
            for e in evals:
                if e is None:
                    cps.append(0.0)
                elif e.get("mate") is not None:
                    # Saturate mates at ±2000 cp for plotting only.
                    cps.append(2000.0 if e["mate"] > 0 else -2000.0)
                elif e.get("cp") is not None:
                    cps.append(float(e["cp"]))
                else:
                    cps.append(0.0)
            st.line_chart(
                {"cp (white POV)": cps},
                use_container_width=True,
            )

        # ---- Panel 3: Strategic commentary -------------------------------

        st.divider()
        render_explain_panel(
            api_url=API_URL,
            game=game,
            plies=plies,
            user_halfmoves=user_halfmoves,
            diff=diff,
            evals=st.session_state.get("evals"),
        )


# ---- Footer: API health ---------------------------------------------------

st.divider()
api_col, _ = st.columns([1, 4])
with api_col:
    try:
        resp = httpx.get(f"{API_URL}/health", timeout=2.0)
        if resp.status_code == 200:
            data = resp.json()
            st.success(f"API healthy — v{data.get('version', '?')}")
        else:
            st.error(f"API status {resp.status_code}")
    except httpx.HTTPError as exc:
        st.error(f"API unreachable at {API_URL}: {exc}")
