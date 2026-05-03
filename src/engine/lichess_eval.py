"""Lichess Cloud Eval HTTP client.

Wraps ``GET https://lichess.org/api/cloud-eval`` — Lichess returns the
deep-cached evaluation of any position they have analyzed. Positions
outside the cloud return HTTP 404.

Response shape (single-PV form, what we request):
    {
      "fen": "...",
      "knodes": 695524,
      "depth": 75,
      "pvs": [
        {"moves": "e2e4 e7e5 ...", "cp": 19}        # or "mate": 5
      ]
    }

We surface a normalized :class:`EvalResponse` with ``source="lichess_cloud"``.
"""

from __future__ import annotations

import logging

import httpx

from src.shared.chess_utils import validate_fen
from src.shared.schemas import EvalResponse

logger = logging.getLogger(__name__)

LICHESS_CLOUD_EVAL_URL = "https://lichess.org/api/cloud-eval"
DEFAULT_TIMEOUT_SECONDS = 5.0
SOURCE_NAME = "lichess_cloud"


class LichessEvalError(Exception):
    """Base class for Lichess cloud-eval client errors."""


class PositionNotInCloudError(LichessEvalError):
    """Lichess has no cached eval for this FEN (HTTP 404)."""


class InvalidFenError(LichessEvalError):
    """FEN failed local validation before sending."""


def fetch_cloud_eval(
    fen: str,
    *,
    multi_pv: int = 1,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    client: httpx.Client | None = None,
) -> EvalResponse:
    """Fetch a single-PV cloud eval for ``fen``.

    Args:
        fen: Position FEN. Validated locally first.
        multi_pv: PVs requested. We only consume the first.
        timeout: Per-request timeout in seconds.
        client: Optional pre-built ``httpx.Client`` (used in tests).

    Raises:
        InvalidFenError: ``fen`` does not parse to a legal position.
        PositionNotInCloudError: Lichess returned 404 for this position.
        LichessEvalError: Any other HTTP/network failure or malformed body.
    """
    if not validate_fen(fen):
        raise InvalidFenError(f"Invalid FEN: {fen!r}")

    params = {"fen": fen, "multiPv": str(multi_pv)}
    owns_client = client is None
    http = client or httpx.Client(timeout=timeout)
    try:
        try:
            resp = http.get(LICHESS_CLOUD_EVAL_URL, params=params)
        except httpx.HTTPError as exc:
            raise LichessEvalError(f"Network error: {exc}") from exc
    finally:
        if owns_client:
            http.close()

    if resp.status_code == 404:
        raise PositionNotInCloudError(f"No cloud eval for {fen}")
    if resp.status_code != 200:
        raise LichessEvalError(
            f"Lichess returned HTTP {resp.status_code}: {resp.text[:200]}"
        )

    try:
        body = resp.json()
    except ValueError as exc:
        raise LichessEvalError(f"Malformed JSON: {exc}") from exc

    return _parse_eval_body(fen, body)


def _parse_eval_body(fen: str, body: dict) -> EvalResponse:
    pvs = body.get("pvs") or []
    if not pvs:
        raise LichessEvalError(f"Cloud eval response missing pvs: {body!r}")

    head = pvs[0]
    moves_str = (head.get("moves") or "").strip()
    pv_list = moves_str.split() if moves_str else []
    best_move = pv_list[0] if pv_list else None

    cp = head.get("cp")
    mate = head.get("mate")
    if cp is None and mate is None:
        raise LichessEvalError(f"PV missing both cp and mate: {head!r}")

    return EvalResponse(
        fen=fen,
        cp=cp,
        mate=mate,
        best_move_uci=best_move,
        pv=pv_list,
        source=SOURCE_NAME,
    )
