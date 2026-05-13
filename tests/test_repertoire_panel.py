"""Tests for the Panel 1 component (Feature 1.3).

Classifier helpers are pure functions — unit-tested directly. The full
panel is smoke-tested via Streamlit's ``AppTest`` runtime.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from src.ui.components.game_walker import PlyView
from src.ui.components.repertoire_panel import (
    classify_halfmove,
    filter_user_halfmoves,
)

# ---- classify_halfmove ----------------------------------------------------


def test_in_book_when_ply_at_or_below_in_book_until() -> None:
    # All three white halfmoves are within the in-book range.
    for ply in [1, 3, 5]:
        assert (
            classify_halfmove(ply, in_book_until_ply=5, deviation_ply=None)
            == "in_book"
        )


def test_deviation_when_ply_matches_deviation_ply() -> None:
    assert (
        classify_halfmove(15, in_book_until_ply=13, deviation_ply=15)
        == "deviation"
    )


def test_after_when_ply_greater_than_deviation_ply() -> None:
    assert (
        classify_halfmove(17, in_book_until_ply=13, deviation_ply=15)
        == "after"
    )


def test_fully_in_book_marks_every_played_ply_green() -> None:
    for ply in [1, 3, 5, 7, 9, 11, 13, 15]:
        assert (
            classify_halfmove(ply, in_book_until_ply=15, deviation_ply=None)
            == "in_book"
        )


def test_move_1_deviation_has_no_greens() -> None:
    """When deviation_ply=1 and in_book_until_ply=0, ply 1 is red."""
    assert (
        classify_halfmove(1, in_book_until_ply=0, deviation_ply=1)
        == "deviation"
    )


# ---- filter_user_halfmoves ------------------------------------------------


def _view(ply: int, san: str) -> PlyView:
    return PlyView(
        ply=ply,
        fen="dummy",
        san=san,
        move_uci=f"u{ply}",
        fullmove_number=(ply + 1) // 2,
        side_to_move="white" if ply % 2 == 0 else "black",
    )


def test_filter_white_keeps_odd_plies_only() -> None:
    plies = [
        _view(0, ""),
        _view(1, "e4"),
        _view(2, "e5"),
        _view(3, "Nf3"),
        _view(4, "Nc6"),
    ]
    out = filter_user_halfmoves(plies, "white")
    assert [p.ply for p in out] == [1, 3]
    assert [p.san for p in out] == ["e4", "Nf3"]


def test_filter_black_keeps_even_plies_only() -> None:
    plies = [
        _view(0, ""),
        _view(1, "e4"),
        _view(2, "c6"),
        _view(3, "d4"),
        _view(4, "d5"),
    ]
    out = filter_user_halfmoves(plies, "black")
    assert [p.ply for p in out] == [2, 4]


# ---- AppTest smoke --------------------------------------------------------

APP_PATH = str(Path(__file__).parent.parent / "src" / "ui" / "streamlit_app.py")

# A real-ish PGN so walk_pgn yields 16 plies (8 user halfmoves for white).
_FULL_PGN = (
    '[White "alice"]\n'
    '[Black "bob"]\n'
    '[Site "https://lichess.org/abcd1234"]\n'
    '[Result "*"]\n\n'
    "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 "
    "5. O-O Be7 6. Re1 b5 7. Bb3 d6 8. Bc4 O-O *"
)


def _mock_game() -> dict[str, Any]:
    return {
        "site": "lichess",
        "game_id": "abcd1234",
        "white_username": "alice",
        "black_username": "bob",
        "user_color": "white",
        "result": "*",
        "time_control": "300+0",
        "time_class": "blitz",
        "pgn": _FULL_PGN,
    }


def _mock_diff_deviation() -> dict[str, Any]:
    """Deviation on white's 8th move (ply 15)."""
    return {
        "game_id": "abcd1234",
        "user_color": "white",
        "in_book_until_ply": 13,
        "deviation": {
            "occurred": True,
            "deviation_ply": 15,
            "deviation_move_number": 8,
            "move_played_san": "Bc4",
            "move_played_uci": "b3c4",
            "fen_before_deviation": (
                "r1bq1rk1/2p1bppp/p1np1n2/1p2p3/4P3/1BP2N2/PP1P1PPP/RNBQR1K1 w - - 0 8"
            ),
            "expected_moves_from_repertoire": [
                {"san": "c3", "uci": "c2c3", "line_name": "Spanish mainline"},
            ],
            "deepest_repertoire_match_node_id": 99,
        },
        "moves_in_book": [
            {"ply": p, "san": s, "user_color": "white"}
            for p, s in [
                (1, "e4"), (3, "Nf3"), (5, "Bb5"),
                (7, "Ba4"), (9, "O-O"), (11, "Re1"), (13, "Bb3"),
            ]
        ],
    }


def _mock_diff_fully_in_book() -> dict[str, Any]:
    return {
        "game_id": "abcd1234",
        "user_color": "white",
        "in_book_until_ply": 15,
        "deviation": {
            "occurred": False,
            "deviation_ply": None,
            "deviation_move_number": None,
            "move_played_san": None,
            "move_played_uci": None,
            "fen_before_deviation": None,
            "expected_moves_from_repertoire": [],
            "deepest_repertoire_match_node_id": 123,
        },
        "moves_in_book": [
            {"ply": p, "san": s, "user_color": "white"}
            for p, s in [
                (1, "e4"), (3, "Nf3"), (5, "Bb5"), (7, "Ba4"),
                (9, "O-O"), (11, "Re1"), (13, "Bb3"), (15, "Bc4"),
            ]
        ],
    }


@pytest.fixture
def app_test() -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=10)
    return at


def test_panel_renders_deviation_without_error(app_test: AppTest) -> None:
    app_test.session_state["game"] = _mock_game()
    app_test.session_state["diff"] = _mock_diff_deviation()
    app_test.run()
    assert not app_test.exception

    # The scope header copy should appear somewhere in the output.
    error_texts = [el.value for el in app_test.error]
    assert any("deviated" in t.lower() and "move" in t.lower() for t in error_texts)


def test_panel_renders_fully_in_book_without_error(app_test: AppTest) -> None:
    app_test.session_state["game"] = _mock_game()
    app_test.session_state["diff"] = _mock_diff_fully_in_book()
    app_test.run()
    assert not app_test.exception

    success_texts = [el.value for el in app_test.success]
    assert any("stayed in prep through move 8" in t for t in success_texts)


def test_move_button_click_updates_session_ply(app_test: AppTest) -> None:
    """Clicking the deviation move's button jumps the position viewer to ply 15."""
    app_test.session_state["game"] = _mock_game()
    app_test.session_state["diff"] = _mock_diff_deviation()
    app_test.run()
    assert not app_test.exception

    target_key = "panel1_move_15"
    target = next((b for b in app_test.button if b.key == target_key), None)
    assert target is not None, f"button {target_key} not found"
    target.click().run()
    assert app_test.session_state["ply"] == 15


def test_opponent_halfmoves_are_clickable(app_test: AppTest) -> None:
    """The Lichess-style movetext renders both sides; clicking an opponent
    halfmove (even ply for a white user) jumps the position viewer."""
    app_test.session_state["game"] = _mock_game()
    app_test.session_state["diff"] = _mock_diff_deviation()
    app_test.run()
    assert not app_test.exception

    # Ply 2 = black's first halfmove for a white user.
    target = next((b for b in app_test.button if b.key == "panel1_move_2"), None)
    assert target is not None, "opponent halfmove button missing"
    target.click().run()
    assert app_test.session_state["ply"] == 2
