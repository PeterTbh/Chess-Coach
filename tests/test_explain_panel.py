"""AppTest-level tests for Panel 3 — Strategic commentary (Slice 4c)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

APP_PATH = str(Path(__file__).parent.parent / "src" / "ui" / "streamlit_app.py")

_PGN = (
    '[White "alice"]\n'
    '[Black "bob"]\n'
    '[Site "https://lichess.org/abcd1234"]\n'
    '[Result "*"]\n\n'
    "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 *"
)


def _game() -> dict[str, Any]:
    return {
        "site": "lichess",
        "game_id": "abcd1234",
        "white_username": "alice",
        "black_username": "bob",
        "user_color": "white",
        "result": "*",
        "time_control": "300+0",
        "time_class": "blitz",
        "pgn": _PGN,
    }


def _no_deviation_diff() -> dict[str, Any]:
    return {
        "game_id": "abcd1234",
        "user_color": "white",
        "in_book_until_ply": 7,
        "deviation": {
            "occurred": False, "deviation_ply": None, "deviation_move_number": None,
            "move_played_san": None, "move_played_uci": None,
            "fen_before_deviation": None, "expected_moves_from_repertoire": [],
            "deepest_repertoire_match_node_id": 99,
        },
        "moves_in_book": [
            {"ply": p, "san": s, "user_color": "white"}
            for p, s in [(1, "e4"), (3, "Nf3"), (5, "Bb5"), (7, "Ba4")]
        ],
    }


def _eval_sequence() -> list[dict[str, Any]]:
    """One eval per ply (0..8 inclusive). Big drop at ply 5 (Bb5)."""
    cps = [0, 25, 20, 30, 25, -180, -170, -160, -150]
    return [
        {"cp": cp, "mate": None, "best_move_uci": None, "pv": [], "source": "lichess_cloud"}
        for cp in cps
    ]


def test_panel_shows_gate_when_evals_missing() -> None:
    at = AppTest.from_file(APP_PATH, default_timeout=10)
    at.session_state["game"] = _game()
    at.session_state["diff"] = _no_deviation_diff()
    # No evals in session.
    at.run()
    assert not at.exception
    captions = [c.value for c in at.caption]
    assert any("Compute evaluations" in t for t in captions)


def test_panel_renders_checkboxes_when_evals_present() -> None:
    at = AppTest.from_file(APP_PATH, default_timeout=10)
    at.session_state["game"] = _game()
    at.session_state["diff"] = _no_deviation_diff()
    at.session_state["evals"] = _eval_sequence()
    at.run()
    assert not at.exception
    # One checkbox per user halfmove (4 for white user in this PGN).
    keys = [cb.key for cb in at.checkbox if cb.key and cb.key.startswith("explain_pick_")]
    assert set(keys) == {"explain_pick_1", "explain_pick_3", "explain_pick_5", "explain_pick_7"}


def test_auto_pick_pre_checks_critical_moments() -> None:
    """Ply 5 (Bb5) has the biggest eval drop — should be auto-checked."""
    at = AppTest.from_file(APP_PATH, default_timeout=10)
    at.session_state["game"] = _game()
    at.session_state["diff"] = _no_deviation_diff()
    at.session_state["evals"] = _eval_sequence()
    at.run()
    assert not at.exception
    by_key = {cb.key: cb for cb in at.checkbox if cb.key}
    assert by_key["explain_pick_5"].value is True


def test_explain_button_calls_advise_and_renders_card() -> None:
    """Click 'Explain selected positions' — /advise mocked to return a fixed body."""
    fixed_body = {
        "fen": "any",
        "explanation": "This is a strategic explanation for testing purposes.",
        "citations": [
            {"source": "Test - Book", "page": 42, "snippet": "A snippet from the book."},
        ],
        "classifier_tags": ["semi_open_center"],
        "model_used": "openrouter",
        "engine_input_echo": {"eval_cp": -180, "mate": None, "best_move_san": "O-O"},
    }

    class _Resp:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return fixed_body

    at = AppTest.from_file(APP_PATH, default_timeout=20)
    at.session_state["game"] = _game()
    at.session_state["diff"] = _no_deviation_diff()
    at.session_state["evals"] = _eval_sequence()

    with patch("src.ui.components.explain_panel.httpx.post", return_value=_Resp()):
        at.run()
        # Find the "Explain selected positions" button and click it.
        explain_btn = next(
            b for b in at.button if b.label == "Explain selected positions"
        )
        explain_btn.click().run()

    assert not at.exception
    # The mocked explanation text should now appear in the markdown.
    body_texts = " ".join(m.value for m in at.markdown if isinstance(m.value, str))
    assert "strategic explanation for testing" in body_texts
    assert "Test - Book" in body_texts
