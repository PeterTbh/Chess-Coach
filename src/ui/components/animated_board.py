"""Animated chessboard component for the position viewer.

Wraps chessboard.js inside a ``streamlit.components.v1.html()`` iframe so
piece movements slide smoothly when the ply slider changes — Streamlit's
SVG-via-markdown path can't animate because it replaces the DOM wholesale
on every rerun.

The iframe is rebuilt every Streamlit rerun, but chessboard.js is
initialised at ``prev_fen`` first and then animates to ``target_fen``
via ``board.position(fen, useAnimation=true)``. The caller tracks
``prev_fen`` in ``st.session_state["last_displayed_fen"]``.

Pulls jQuery + chessboard.js from the unpkg CDN (~150 KB total on the
first load, cached thereafter). Online-only — an offline run will see
an empty iframe.
"""

from __future__ import annotations

import json

import streamlit.components.v1 as components

_CDN_JS = "https://unpkg.com/@chrisoakman/chessboardjs@1.0.0/dist/chessboard-1.0.0.min.js"
_CDN_CSS = "https://unpkg.com/@chrisoakman/chessboardjs@1.0.0/dist/chessboard-1.0.0.min.css"
_CDN_JQUERY = "https://code.jquery.com/jquery-3.6.0.min.js"
_PIECE_THEME = (
    "https://unpkg.com/@chrisoakman/chessboardjs@1.0.0/"
    "website/img/chesspieces/wikipedia/{piece}.png"
)


def render_animated_board(
    *,
    fen: str,
    prev_fen: str | None = None,
    last_move_uci: str | None = None,
    size: int = 400,
    move_speed_ms: int = 120,
) -> None:
    """Render the board with a sliding animation from ``prev_fen`` to ``fen``.

    Args:
        fen: target position to display.
        prev_fen: position the board should start at; ``None`` skips the
            animation and snaps to ``fen`` immediately.
        last_move_uci: 4-5 char UCI of the move that produced ``fen``;
            we highlight its origin + destination squares.
        size: board edge in CSS pixels.
        move_speed_ms: animation duration per piece movement.
    """
    iframe_height = size + 24
    html = _build_html(
        fen=fen,
        prev_fen=prev_fen,
        last_move_uci=last_move_uci,
        size=size,
        move_speed_ms=move_speed_ms,
    )
    components.html(html, height=iframe_height, scrolling=False)


def _build_html(
    *,
    fen: str,
    prev_fen: str | None,
    last_move_uci: str | None,
    size: int,
    move_speed_ms: int,
) -> str:
    target = json.dumps(fen)
    prev = json.dumps(prev_fen) if prev_fen else "null"
    last_move = json.dumps(last_move_uci) if last_move_uci else "null"
    piece_theme = json.dumps(_PIECE_THEME)

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<link rel="stylesheet" href="{_CDN_CSS}"/>
<style>
  html, body {{ margin: 0; padding: 0; background: transparent; }}
  #board {{ width: {size}px; margin: 0 auto; }}
  .square-highlight {{
    box-shadow: inset 0 0 0 3px rgba(255, 215, 0, 0.7);
  }}
</style>
</head>
<body>
  <div id="board"></div>
  <script src="{_CDN_JQUERY}"></script>
  <script src="{_CDN_JS}"></script>
  <script>
    const TARGET_FEN = {target};
    const PREV_FEN   = {prev};
    const LAST_MOVE  = {last_move};
    const cfg = {{
      position: PREV_FEN || TARGET_FEN,
      pieceTheme: {piece_theme},
      moveSpeed: {move_speed_ms},
      showNotation: true,
    }};
    const board = Chessboard('board', cfg);

    function highlightLastMove() {{
      $('#board .square-55d63').removeClass('square-highlight');
      if (!LAST_MOVE || LAST_MOVE.length < 4) return;
      const from = LAST_MOVE.slice(0, 2);
      const to = LAST_MOVE.slice(2, 4);
      $('#board .square-' + from).addClass('square-highlight');
      $('#board .square-' + to).addClass('square-highlight');
    }}

    if (PREV_FEN && PREV_FEN !== TARGET_FEN) {{
      // Slight delay so the user sees the start position before the slide.
      setTimeout(function() {{
        board.position(TARGET_FEN, true);
        // Re-apply highlight after pieces settle.
        setTimeout(highlightLastMove, {move_speed_ms} + 50);
      }}, 40);
    }} else {{
      highlightLastMove();
    }}
  </script>
</body>
</html>
"""
