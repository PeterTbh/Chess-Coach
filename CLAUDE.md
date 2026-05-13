# CLAUDE.md — Caissa

**Status: shipped.** Three-panel post-mortem app works end-to-end. Tests pass at
204, ruff clean.

## Mission

Local, single-user chess post-mortem tool. The user pastes a Lichess game URL,
the Streamlit UI renders three stacked panels:

1. **Repertoire deviation** — first move the user left their prep
   (`data/repertoires/{white,black}.pgn`), with the alternatives the rep
   actually prepared.
2. **Engine evaluation** — Lichess Cloud Eval primary, local Stockfish 18
   silent fallback. Per-ply cp graph plus current-position metric.
3. **Strategic commentary** — for a handful of critical moments (the
   deviation plus the biggest eval drops), a 150-250-word neutral analytical
   explanation, grounded in a small RAG corpus of canonical chess strategy
   passages and citing the source + page.

## Architecture

Two host processes on localhost:

- **FastAPI** (`:8000`) — `src/api/main.py`. Routes: `/health`,
  `/game/fetch`, `/repertoire/diff`, `/eval`, `/advise`.
- **Streamlit** (`:8501`) — `src/ui/streamlit_app.py` + panel components.

The UI talks to the backend over HTTP; nothing else listens on those ports.

## Tech stack

| Layer | Choice |
|---|---|
| Python | 3.11 + uv |
| Backend | FastAPI + Uvicorn |
| UI | Streamlit, board rendering via `chess.svg` |
| Repertoire store | SQLite (`data/caissa.sqlite`) |
| Engine | Lichess Cloud Eval → local Stockfish 18 (host binary, `STOCKFISH_PATH`) |
| Vector DB | ChromaDB persistent client at `data/chroma/` (embedded, not the dockerised server) |
| Embeddings | `BAAI/bge-small-en-v1.5` via sentence-transformers |
| LLM | OpenAI `gpt-5-mini` via the openai SDK |
| PGN | python-chess |
| Game APIs | Lichess Open API, Chess.com Public Data |

## Modules (current)

- **A — Strategic Advisor.** `src/advisor/`. Pipeline: `classify(FEN) →
  retrieve top-3 → LLM with anti-hallucination retry → AdviseResponse`.
  Classifier is rule-based (~10 structural tags); corpus is the
  hand-written seed at `data/corpus_seed.json`.
- **B — Repertoire Deviation Detector.** `src/repertoire/`. SQLite-backed,
  walks the played PGN halfmove-by-halfmove against the user's rep,
  emits `DeviationReport`.
- **D — Streamlit UI.** `src/ui/`. Three panels + position viewer.

Modules C (Chessable export) and E (YouTube reverse search) were always
deferred and were excised when we cleaned up legacy context. They can be
revisited later if there's a use case.

## Demo scenario

User pastes a Lichess Catalan game URL where they deviated on move 9.

- Panel 1: "You deviated on move 9. You played Bd2; repertoire prepares Qc2."
- Panel 2: cp graph showing drop from +0.4 to −0.7 over moves 9-12.
- Panel 3: explanation card for that ply citing Watson MCO vol. 1 p. 142.

User clicks the deviation move in Panel 1's list → Position viewer jumps to
that ply → Panel 3's card stays consistent.

## Code conventions

- Type hints everywhere; no `Any` outside SDK seams.
- Pydantic for all I/O at module boundaries.
- `ruff` lint, `pytest` tests.
- Streamlit: `st.session_state`, `st.cache_data` / `st.cache_resource`.
- stdlib `logging`; no `print()` in `src/`.
- Secrets in `.env`; `.env.example` shows schema.
- Conventional commits, feature branches per slice.

## Running it

Host mode:

```
uv run uvicorn src.api.main:app --reload      # API on :8000
uv run streamlit run src/ui/streamlit_app.py  # UI on :8501
```

Required env (`.env`): `OPENAI_API_KEY`, `LICHESS_USERNAME`,
`STOCKFISH_PATH`. Optional: `CHESSCOM_USERNAME` if you want Chess.com URLs.

Required filesystem: `data/repertoires/white.pgn` and/or `black.pgn` for
Panel 1 to do anything; Panels 2-3 work without them.

## Tests

`uv run pytest` — 204 passed, 0 skipped.
`uv run ruff check src tests` — clean.

Streamlit panels use `streamlit.testing.v1.AppTest`; LLM calls are mocked
through a fake chat client (no live API hits in CI).
