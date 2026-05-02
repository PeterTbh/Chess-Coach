"""Caissa — Streamlit landing page (Phase 1)."""

from __future__ import annotations

import os

import httpx
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000")

st.set_page_config(page_title="Caissa", page_icon="♞", layout="wide")

st.title("Caissa ♞")
st.caption("Personal chess improvement system — local post-mortem")

st.text_input(
    "Game URL",
    key="game_url",
    placeholder="Paste a Lichess or Chess.com game URL (Phase 2 wires this up)",
)

st.divider()
st.subheader("Coming online phase by phase")
st.markdown(
    """
- **Panel 1 — Repertoire deviation** *(Phase 3)*
- **Panel 2 — Engine evaluation** *(Phase 3)*
- **Panel 3 — Strategic commentary** *(Phase 4)*
"""
)

# Footer: API health
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
