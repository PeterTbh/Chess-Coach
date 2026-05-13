"""Auto-pick user halfmoves worth explaining (Slice 4c).

Heuristic: the deviation ply (if any) plus the top N user halfmoves where
the position evaluation got noticeably worse for the user.

Eval drops are computed as (eval_after_user_move - eval_before_user_move),
sign-flipped for white (so a "drop against the user" is always a positive
number). Mate scores are saturated at ±2000 cp so a forced mate doesn't
dominate the sort. Plies whose before/after eval is missing are skipped.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_MATE_CP_SATURATION = 2000


def pick_critical_moments(
    diff: dict[str, Any] | None,
    evals: list[dict[str, Any] | None] | None,
    user_color: str,
    *,
    max_moments: int = 4,
    cp_threshold: int = 100,
) -> list[int]:
    """Return plies (chronological) where Panel 3 should request an explanation.

    Args:
        diff: ``/repertoire/diff`` response (or None).
        evals: list of eval-payloads parallel to game plies (index 0 = start).
            May contain ``None`` entries for plies where Lichess+SF both
            gave nothing. Truthy entries follow the ``/eval`` shape.
        user_color: ``"white"`` or ``"black"``.
        max_moments: upper bound on returned plies.
        cp_threshold: minimum (signed) drop in cp to consider a move blunder-worthy.
    """
    if max_moments <= 0:
        return []

    picked: set[int] = set()

    # 1) Always include the deviation ply when present.
    if diff is not None:
        dev = diff.get("deviation") or {}
        if dev.get("occurred") and dev.get("deviation_ply") is not None:
            picked.add(int(dev["deviation_ply"]))

    # 2) Compute eval drops at user halfmoves.
    drops = _user_eval_drops(evals or [], user_color)
    # Sort by largest drop against the user, take while under cap.
    drops.sort(key=lambda x: x[1], reverse=True)
    for ply, delta in drops:
        if len(picked) >= max_moments:
            break
        if delta < cp_threshold:
            break
        picked.add(ply)

    return sorted(picked)


def _user_eval_drops(
    evals: list[dict[str, Any] | None],
    user_color: str,
) -> list[tuple[int, int]]:
    """Return ``[(ply, delta_against_user), ...]`` for each user halfmove.

    Drops where either side of the eval is unavailable are silently dropped.
    """
    user_parity = 1 if user_color == "white" else 0
    sign = -1 if user_color == "white" else 1  # convert white-POV cp into "against user"
    out: list[tuple[int, int]] = []

    for ply in range(1, len(evals)):
        if ply % 2 != user_parity:
            continue
        cp_before = _eval_cp(evals[ply - 1])
        cp_after = _eval_cp(evals[ply])
        if cp_before is None or cp_after is None:
            continue
        delta = (cp_after - cp_before) * sign
        out.append((ply, delta))
    return out


def _eval_cp(payload: dict[str, Any] | None) -> int | None:
    """Extract a comparable cp value from a /eval payload. Saturate mates."""
    if payload is None:
        return None
    mate = payload.get("mate")
    if mate is not None:
        return _MATE_CP_SATURATION if mate > 0 else -_MATE_CP_SATURATION
    cp = payload.get("cp")
    if cp is None:
        return None
    return int(cp)
