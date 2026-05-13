"""Slice 4c orchestrator: classify → retrieve → LLM → AdviseResponse.

The :func:`advise` function is what ``/advise`` calls. It is deliberately
client-agnostic — engine and LLM clients can be injected for testing.
"""

from __future__ import annotations

import logging
from typing import Any

import chess
from chromadb.api.models.Collection import Collection

from src.advisor.classifier import classify
from src.advisor.corpus import BgeEmbedder, get_client, get_or_create_collection
from src.advisor.llm import (
    Citation as LlmCitation,
)
from src.advisor.llm import (
    EngineAnalysis,
    LlmRequest,
    generate_explanation,
)
from src.advisor.retrieval import retrieve_top_k
from src.engine.lichess_eval import (
    LichessEvalError,
    PositionNotInCloudError,
    fetch_cloud_eval,
)
from src.engine.stockfish import StockfishError, analyse_position
from src.shared.schemas import (
    AdviseRequest,
    AdviseResponse,
    BookCitation,
    EngineAnalysisInput,
    EngineInputEcho,
)

logger = logging.getLogger(__name__)


class AdviseError(Exception):
    """Pipeline could not complete (e.g. no engine source available)."""


# Acceptance thresholds (scope F2). Soft — we log, never reject.
WORD_COUNT_MIN = 100
WORD_COUNT_MAX = 350


# ---- Public entrypoint ---------------------------------------------------


def advise(
    req: AdviseRequest,
    *,
    collection: Collection | None = None,
    llm_kwargs: dict[str, Any] | None = None,
) -> AdviseResponse:
    """Build a full :class:`AdviseResponse` for a single position.

    ``collection`` defaults to the on-disk corpus (lazy-initialised).
    ``llm_kwargs`` are forwarded into :func:`generate_explanation` so tests
    can inject fake clients.
    """
    tags = classify(req.fen)

    engine = (
        _engine_from_request(req.engine_analysis)
        if req.engine_analysis is not None
        else _fetch_engine(req.fen)
    )

    coll = collection if collection is not None else _default_collection()
    hits = retrieve_top_k(
        coll,
        fen=req.fen,
        tags=tags,
        best_move_san=engine.best_move_san,
        k=3,
    )

    llm_citations = [
        LlmCitation(source=h.source, page=h.page, snippet=h.snippet) for h in hits
    ]
    llm_req = LlmRequest(
        fen=req.fen,
        tags=tags,
        user_color=req.user_color,
        game_phase_hint=req.game_phase_hint,
        engine=engine,
        citations=llm_citations,
    )
    llm_result = generate_explanation(llm_req, **(llm_kwargs or {}))
    _check_soft_acceptance(llm_result.explanation, tags)

    return AdviseResponse(
        fen=req.fen,
        explanation=llm_result.explanation,
        citations=[
            BookCitation(source=h.source, page=h.page, snippet=h.snippet)
            for h in hits
        ],
        classifier_tags=tags,
        model_used=llm_result.model_used,
        engine_input_echo=EngineInputEcho(
            eval_cp=engine.eval_cp,
            mate=engine.mate,
            best_move_san=engine.best_move_san,
        ),
    )


# ---- Engine helpers ------------------------------------------------------


def _engine_from_request(payload: EngineAnalysisInput) -> EngineAnalysis:
    return EngineAnalysis(
        eval_cp=payload.eval_cp,
        mate=payload.mate,
        best_move_uci=payload.best_move_uci,
        best_move_san=payload.best_move_san,
        pv_uci=list(payload.pv),
        depth=payload.depth,
    )


def _fetch_engine(fen: str) -> EngineAnalysis:
    """Lichess Cloud Eval primary, local Stockfish silent fallback."""
    try:
        eval_resp = fetch_cloud_eval(fen)
        logger.info("advise: engine from Lichess for %s", fen)
        return _eval_response_to_engine(fen, eval_resp.model_dump())
    except PositionNotInCloudError:
        logger.info("advise: Lichess miss for %s — falling back to Stockfish", fen)
    except LichessEvalError as exc:
        logger.warning("advise: Lichess error for %s (%s) — falling back to Stockfish", fen, exc)

    try:
        sf_resp = analyse_position(fen)
        return _eval_response_to_engine(fen, sf_resp.model_dump())
    except StockfishError as exc:
        raise AdviseError(
            f"No engine source returned a result for {fen!r}: {exc}"
        ) from exc


def _eval_response_to_engine(fen: str, payload: dict[str, Any]) -> EngineAnalysis:
    """Convert ``EvalResponse``-shaped dict → :class:`EngineAnalysis` with SAN."""
    best_uci = payload.get("best_move_uci") or ""
    best_san = _uci_to_san(fen, best_uci) if best_uci else ""
    pv = list(payload.get("pv") or [])
    return EngineAnalysis(
        eval_cp=payload.get("cp"),
        mate=payload.get("mate"),
        best_move_uci=best_uci,
        best_move_san=best_san,
        pv_uci=pv,
        depth=None,
    )


def _uci_to_san(fen: str, uci: str) -> str:
    try:
        board = chess.Board(fen)
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            return uci
        return board.san(move)
    except (ValueError, AssertionError):
        return uci


# ---- Soft acceptance checks ---------------------------------------------


def _check_soft_acceptance(explanation: str, tags: list[str]) -> None:
    words = explanation.split()
    if not (WORD_COUNT_MIN <= len(words) <= WORD_COUNT_MAX):
        logger.warning(
            "advise: explanation word count %d outside [%d, %d]",
            len(words), WORD_COUNT_MIN, WORD_COUNT_MAX,
        )
    if tags and not _mentions_any_tag(explanation, tags):
        logger.warning(
            "advise: explanation does not mention any classifier tag (%s)", tags
        )


def _mentions_any_tag(text: str, tags: list[str]) -> bool:
    lower = text.lower()
    for tag in tags:
        normalised = tag.replace("_", " ").lower()
        # Whole-tag match.
        if normalised in lower:
            return True
        # Loose match on substantive keywords inside the tag.
        for token in normalised.split():
            if len(token) >= 5 and token in lower:
                return True
    return False


# ---- Collection helper ---------------------------------------------------


def _default_collection() -> Collection:
    client = get_client()
    return get_or_create_collection(client, BgeEmbedder())
