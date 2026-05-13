"""Tests for the critical-moment auto-picker (Slice 4c)."""

from __future__ import annotations

from typing import Any

from src.advisor.critical_moments import pick_critical_moments


def _eval(cp: int | None = None, mate: int | None = None) -> dict[str, Any]:
    return {"cp": cp, "mate": mate, "best_move_uci": None, "pv": [], "source": "test"}


def _diff(occurred: bool, ply: int | None = None) -> dict[str, Any]:
    return {
        "deviation": {
            "occurred": occurred,
            "deviation_ply": ply,
            "deviation_move_number": (ply + 1) // 2 if ply else None,
            "move_played_san": "Bd2" if occurred else None,
            "move_played_uci": "c1d2" if occurred else None,
            "fen_before_deviation": "x" if occurred else None,
            "expected_moves_from_repertoire": [],
            "deepest_repertoire_match_node_id": None,
        }
    }


# ---- Deviation inclusion -------------------------------------------------

def test_includes_deviation_ply_when_occurred() -> None:
    out = pick_critical_moments(
        _diff(True, ply=15),
        evals=[_eval(0)] * 20,
        user_color="white",
    )
    assert 15 in out


def test_excludes_deviation_when_not_occurred() -> None:
    """No deviation + no drops → empty."""
    out = pick_critical_moments(
        _diff(False),
        evals=[_eval(10)] * 10,
        user_color="white",
    )
    assert out == []


def test_handles_none_diff() -> None:
    out = pick_critical_moments(
        None,
        evals=[_eval(10)] * 10,
        user_color="white",
    )
    assert out == []


# ---- Eval-drop picking ---------------------------------------------------

def test_picks_top_drops_for_white_user() -> None:
    """White plays at odd plies. Eval drop = cp_after - cp_before < 0."""
    evals: list[dict | None] = [
        _eval(0),     # ply 0 start
        _eval(20),    # ply 1 (white) — improved
        _eval(20),    # ply 2 (black)
        _eval(-150),  # ply 3 (white) — DROP of 170 against white
        _eval(-150),  # ply 4 (black)
        _eval(-300),  # ply 5 (white) — DROP of 150 against white
    ]
    out = pick_critical_moments(
        _diff(False), evals=evals, user_color="white", max_moments=3, cp_threshold=100,
    )
    assert sorted(out) == [3, 5]


def test_picks_top_drops_for_black_user_with_sign_flipped() -> None:
    """Black plays at even plies. Drop against black = cp rises."""
    evals: list[dict | None] = [
        _eval(0),    # ply 0
        _eval(0),    # ply 1 (white)
        _eval(200), # ply 2 (black) — rise of 200 cp (bad for black)
        _eval(200), # ply 3 (white)
        _eval(50),  # ply 4 (black) — drop of 150 cp (good for black)
    ]
    out = pick_critical_moments(
        _diff(False), evals=evals, user_color="black", max_moments=3, cp_threshold=100,
    )
    assert 2 in out
    assert 4 not in out  # this was good for black, not a blunder


def test_ignores_opponent_plies() -> None:
    """Only user halfmoves are considered."""
    evals: list[dict | None] = [
        _eval(0),
        _eval(0),       # ply 1 (white) — flat
        _eval(-300),    # ply 2 (black) — big drop, but white is user
        _eval(-300),    # ply 3 (white) — flat
    ]
    out = pick_critical_moments(
        _diff(False), evals=evals, user_color="white", cp_threshold=100,
    )
    assert out == []


def test_caps_at_max_moments() -> None:
    evals: list[dict | None] = [_eval(i * -100) for i in range(11)]  # ply 0..10
    out = pick_critical_moments(
        _diff(True, ply=1),
        evals=evals,
        user_color="white",
        max_moments=3,
    )
    assert len(out) == 3
    # Output should remain sorted chronologically.
    assert out == sorted(out)


def test_dedupes_when_deviation_is_also_top_drop() -> None:
    evals: list[dict | None] = [
        _eval(0),
        _eval(0),
        _eval(0),
        _eval(-500),  # ply 3 — huge drop
        _eval(-500),
    ]
    out = pick_critical_moments(
        _diff(True, ply=3), evals=evals, user_color="white",
    )
    assert out.count(3) == 1


def test_saturates_mates() -> None:
    """A mate score shouldn't outrank everything else by 9999 cp."""
    evals: list[dict | None] = [
        _eval(0),
        _eval(0),
        _eval(0),
        _eval(mate=-3),  # ply 3 — mate against white
        _eval(0),
        _eval(-150),     # ply 5 — normal blunder
    ]
    out = pick_critical_moments(
        _diff(False), evals=evals, user_color="white", max_moments=2,
    )
    assert 3 in out
    assert 5 in out


def test_skips_plies_with_missing_evals() -> None:
    evals: list[dict | None] = [
        _eval(0),
        None,           # ply 1 missing
        _eval(0),
        _eval(-300),    # ply 3 — drop of 300 but...
        _eval(-300),
        None,           # ply 5 missing
    ]
    out = pick_critical_moments(
        _diff(False), evals=evals, user_color="white",
    )
    assert 3 in out
    assert 1 not in out
    assert 5 not in out


def test_returns_empty_when_max_moments_zero() -> None:
    out = pick_critical_moments(
        _diff(True, ply=15), evals=[_eval(0)] * 20,
        user_color="white", max_moments=0,
    )
    assert out == []
