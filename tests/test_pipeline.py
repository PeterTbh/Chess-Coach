"""Tests for the /advise orchestration pipeline (Slice 4c)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from src.advisor import pipeline as pipe
from src.advisor.corpus import (
    FakeEmbedder,
    build_or_refresh_corpus,
    get_client,
    get_or_create_collection,
)
from src.advisor.llm import LlmApiError, LlmHallucinationError
from src.shared.schemas import AdviseRequest, EngineAnalysisInput

FEN_OPENING = "rnbq1rk1/pp2bppp/2p1pn2/3p4/2PP4/2N2NP1/PP2PPBP/R1BQK2R w KQ - 0 7"
FEN_STARTING = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class _FakeChatClient:
    is_configured = lambda self: True  # noqa: E731

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def chat_completions_create(self, *, model: str, messages: list) -> str:
        self.calls += 1
        if not self._responses:
            raise AssertionError("FakeChatClient out of responses")
        return self._responses.pop(0)


class _NotConfigured:
    def is_configured(self) -> bool:
        return False

    def chat_completions_create(self, *, model: str, messages: list) -> str:
        raise AssertionError("not-configured client must not be called")


def _engine_input() -> EngineAnalysisInput:
    return EngineAnalysisInput(
        eval_cp=18,
        mate=None,
        best_move_uci="e1g1",
        best_move_san="O-O",
        pv=["e1g1", "b8d7", "b1c3"],
        depth=22,
    )


def _request(with_engine: bool = True) -> AdviseRequest:
    return AdviseRequest(
        fen=FEN_OPENING,
        user_color="white",
        engine_analysis=_engine_input() if with_engine else None,
        game_phase_hint="opening",
    )


@pytest.fixture
def small_corpus(tmp_path: Path):
    """Tiny fake-embedded collection so retrieval returns deterministic hits."""
    seed = tmp_path / "seed.json"
    seed.write_text(
        '[{"id": "test-iqp", "tags": ["isolated_queen_pawn"], '
        '"source": "Test - Book", "page": 1, '
        '"snippet": "IQP positions favor active piece play."}]',
        encoding="utf-8",
    )
    client = get_client(tmp_path / "chroma")
    coll = get_or_create_collection(client, FakeEmbedder(), name="test_pipeline_corpus")
    build_or_refresh_corpus(coll, seed, force=True)
    return coll


# ---- Happy path ----------------------------------------------------------

def test_advise_returns_full_response(small_corpus) -> None:
    fake_or = _FakeChatClient([
        "White should castle with O-O to complete development; the engine "
        "preference reflects king safety and the natural plan in this "
        "structure. The IQP-style central tension means activity matters "
        "more than long-term pawn integrity. After O-O the rook on f1 "
        "supports later breaks and the queen retains flexible squares. "
        "Continuing with development before any commitment is the engine's "
        "preferred plan, and the small evaluation edge confirms that the "
        "position is balanced enough to favour patience over forcing play. "
        "This approach mirrors classical IQP guidance: keep pieces active "
        "and avoid early simplifications. Twelve moves in, castling is "
        "the natural waypoint before the middlegame's strategic decisions. "
        "Castling sets up the rook's potential for the f-file and improves "
        "the king's safety in a single tempo. After Nbd7 black completes "
        "development; the position remains balanced with chances for both "
        "sides depending on later structural decisions."
    ])
    resp = pipe.advise(
        _request(),
        collection=small_corpus,
        llm_kwargs={"openrouter_client": fake_or, "openai_client": _NotConfigured()},
    )
    assert resp.fen == FEN_OPENING
    assert resp.model_used == "openrouter"
    assert resp.classifier_tags == sorted(resp.classifier_tags)
    assert resp.engine_input_echo.best_move_san == "O-O"
    assert resp.engine_input_echo.eval_cp == 18
    assert len(resp.citations) == 1
    assert resp.citations[0].source == "Test - Book"
    assert fake_or.calls == 1


def test_advise_uses_provided_engine_without_calling_engine_helpers(
    small_corpus, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _fail(*_a, **_k):  # noqa: ANN002,ANN003
        raise AssertionError("engine helper must not be called when engine provided")

    monkeypatch.setattr(pipe, "_fetch_engine", _fail)
    fake_or = _FakeChatClient(["A balanced opening position with development to complete."])
    pipe.advise(
        _request(with_engine=True),
        collection=small_corpus,
        llm_kwargs={"openrouter_client": fake_or, "openai_client": _NotConfigured()},
    )


def test_advise_fetches_engine_from_lichess_when_not_provided(
    small_corpus, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.engine import lichess_eval
    from src.shared.schemas import EvalResponse

    def _fake_lichess(fen: str) -> EvalResponse:
        return EvalResponse(
            fen=fen, cp=24, mate=None,
            best_move_uci="g1f3", pv=["g1f3"], source="lichess_cloud",
        )
    monkeypatch.setattr(lichess_eval, "fetch_cloud_eval", _fake_lichess)
    # Also patch the symbol the pipeline module imported.
    monkeypatch.setattr(pipe, "fetch_cloud_eval", _fake_lichess)

    fake_or = _FakeChatClient(["A balanced central position with normal development."])
    resp = pipe.advise(
        _request(with_engine=False),
        collection=small_corpus,
        llm_kwargs={"openrouter_client": fake_or, "openai_client": _NotConfigured()},
    )
    assert resp.engine_input_echo.eval_cp == 24
    assert resp.engine_input_echo.best_move_san  # converted via UCI→SAN


def test_advise_falls_back_to_stockfish_on_lichess_miss(
    small_corpus, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.engine.lichess_eval import PositionNotInCloudError
    from src.shared.schemas import EvalResponse

    def _miss(_fen: str):
        raise PositionNotInCloudError("not cached")

    def _fake_sf(_fen: str, **_kw) -> EvalResponse:
        return EvalResponse(
            fen=_fen, cp=10, mate=None,
            best_move_uci="g1f3", pv=["g1f3"], source="local_stockfish",
        )

    monkeypatch.setattr(pipe, "fetch_cloud_eval", _miss)
    monkeypatch.setattr(pipe, "analyse_position", _fake_sf)

    fake_or = _FakeChatClient(["A central position with development still to do."])
    resp = pipe.advise(
        _request(with_engine=False),
        collection=small_corpus,
        llm_kwargs={"openrouter_client": fake_or, "openai_client": _NotConfigured()},
    )
    assert resp.engine_input_echo.eval_cp == 10


def test_advise_raises_when_both_engines_fail(
    small_corpus, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.engine.lichess_eval import LichessEvalError
    from src.engine.stockfish import StockfishUnavailableError

    monkeypatch.setattr(
        pipe, "fetch_cloud_eval",
        lambda _f: (_ for _ in ()).throw(LichessEvalError("network down")),
    )
    monkeypatch.setattr(
        pipe, "analyse_position",
        lambda _f, **_kw: (_ for _ in ()).throw(StockfishUnavailableError("no binary")),
    )
    with pytest.raises(pipe.AdviseError):
        pipe.advise(
            _request(with_engine=False),
            collection=small_corpus,
            llm_kwargs={
                "openrouter_client": _FakeChatClient([]),
                "openai_client": _NotConfigured(),
            },
        )


# ---- Tag echo + citation passthrough ------------------------------------

def test_classifier_tags_are_echoed(small_corpus) -> None:
    fake_or = _FakeChatClient(["A balanced central position with normal development."])
    resp = pipe.advise(
        _request(),
        collection=small_corpus,
        llm_kwargs={"openrouter_client": fake_or, "openai_client": _NotConfigured()},
    )
    # The starting-ish opening has at least one structural tag.
    assert isinstance(resp.classifier_tags, list)


def test_citations_pass_through_source_page_snippet(small_corpus) -> None:
    fake_or = _FakeChatClient(["A balanced central position with normal development."])
    resp = pipe.advise(
        _request(),
        collection=small_corpus,
        llm_kwargs={"openrouter_client": fake_or, "openai_client": _NotConfigured()},
    )
    assert len(resp.citations) == 1
    cit = resp.citations[0]
    assert cit.source == "Test - Book"
    assert cit.page == 1
    assert "IQP" in cit.snippet


# ---- Soft acceptance ----------------------------------------------------

def test_short_explanation_logs_warning_but_returns(small_corpus, caplog) -> None:
    caplog.set_level(logging.WARNING, logger="src.advisor.pipeline")
    fake_or = _FakeChatClient(["Too short."])  # 2 words
    resp = pipe.advise(
        _request(),
        collection=small_corpus,
        llm_kwargs={"openrouter_client": fake_or, "openai_client": _NotConfigured()},
    )
    assert resp.explanation == "Too short."
    assert any("word count" in rec.message for rec in caplog.records)


def test_missing_tag_mention_logs_warning(small_corpus, caplog) -> None:
    caplog.set_level(logging.WARNING, logger="src.advisor.pipeline")
    # Long enough to pass word count, no tag keywords ("center", "endgame", etc.).
    text = " ".join(["plain"] * 120)
    fake_or = _FakeChatClient([text])
    pipe.advise(
        _request(),
        collection=small_corpus,
        llm_kwargs={"openrouter_client": fake_or, "openai_client": _NotConfigured()},
    )
    assert any("does not mention any classifier tag" in r.message for r in caplog.records)


# ---- Error propagation --------------------------------------------------

def test_llm_hallucination_propagates(small_corpus) -> None:
    """Pipeline doesn't swallow LlmHallucinationError — route maps it to 502."""
    fake_or = _FakeChatClient([
        "Bad: Nh3 is mandatory.", "Still Nh3.",  # both bad; OpenAI not configured
    ])
    with pytest.raises(LlmHallucinationError):
        pipe.advise(
            _request(),
            collection=small_corpus,
            llm_kwargs={"openrouter_client": fake_or, "openai_client": _NotConfigured()},
        )


def test_llm_api_error_propagates(small_corpus) -> None:
    class _Failing:
        def is_configured(self): return True
        def chat_completions_create(self, **_): raise LlmApiError("provider down")

    with pytest.raises(LlmApiError):
        pipe.advise(
            _request(),
            collection=small_corpus,
            llm_kwargs={"openrouter_client": _Failing(), "openai_client": _NotConfigured()},
        )
