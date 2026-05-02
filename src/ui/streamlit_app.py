"""Caissa — Streamlit landing page.

Phase 2 slice 1: paste a Lichess URL → render game metadata.
Other panels (repertoire, eval, advisor) remain placeholders.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000")
FETCH_TIMEOUT_SECONDS = 15.0

st.set_page_config(page_title="Caissa", page_icon="♞", layout="wide")

st.title("Caissa ♞")
st.caption("Personal chess improvement system — local post-mortem")


# ---- Game fetch form ------------------------------------------------------

with st.form("fetch_form"):
    url = st.text_input(
        "Game URL",
        placeholder="https://lichess.org/abcd1234   (Chess.com lands in slice 2)",
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
        else:
            try:
                detail = resp.json().get("detail", resp.text)
            except ValueError:
                detail = resp.text
            st.error(f"Fetch failed (HTTP {resp.status_code}): {detail}")


# ---- Metadata display -----------------------------------------------------

game: dict[str, Any] | None = st.session_state.get("game")

if game:
    st.subheader("Game metadata")
    cols = st.columns(4)
    cols[0].metric("Site", game["site"])
    cols[1].metric("White", game["white_username"])
    cols[2].metric("Black", game["black_username"])
    cols[3].metric("Result", game["result"])
    st.caption(
        f"Game ID: `{game['game_id']}` · You played: **{game['user_color']}**"
    )
    with st.expander("PGN"):
        st.code(game["pgn"], language="text")


# ---- Future panels --------------------------------------------------------

st.divider()
st.subheader("Coming online phase by phase")
st.markdown(
    """
- **Panel 1 — Repertoire deviation** *(Phase 3)*
- **Panel 2 — Engine evaluation** *(Phase 3)*
- **Panel 3 — Strategic commentary** *(Phase 4)*
"""
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
