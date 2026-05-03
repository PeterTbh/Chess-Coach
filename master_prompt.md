# Project: Caissa — Personal Chess Improvement System (Python-Only v1)

You are Opus 4.7 in Claude Code, working with the Get-Shit-Done 2.0 skill suite.
This is the founding turn. Your output here defines repo structure, the working
CLAUDE.md, and Phase 1 deliverables. Working directory is `~/Desktop/Chess-Coach`.

## Operator Profile

Solo developer with Business Administration + CS specialization background,
comfortable with Python, intermediate PyTorch, weak in CV pipelines. ~10 days
of focused work, ~50€ compute budget, Claude Max 20x with Opus 4.7. Tool runs
locally only, for personal use. Demo target: pre-recorded video for HSG
academic submission.

## Stack Mandate

Python-only. No TypeScript, no JavaScript, no Chrome extension. UI is Streamlit
on localhost:8501. If a feature seems to require browser-extension semantics,
redesign it as Streamlit interaction.

## Mission

Build the chess improvement system the user wants to use after every game.
After playing on Lichess or Chess.com, they open the local Streamlit app,
paste the game URL, and see three stacked panels:

1. Where they left their opening prep (repertoire diff against
   `data/repertoires/white.pgn` or `black.pgn`)
2. Where they went wrong tactically/positionally (eval from Lichess Cloud
   Eval API, fallback local Stockfish for chess.com positions)
3. What the position was actually about (fine-tuned Gemma 4 E4B trained on a
   curated corpus of English-language chess strategy books, producing
   analytical commentary in the voice of a club-level coach)

The intellectual contribution is the integration architecture and the extracted
book corpus, not novel ML research.

## Constraint Acknowledgement

The user has explicitly accepted these:

- Module C (Chessable export) is deferred to Phase 2. User provides PGNs
  manually from Chessable courses or Lichess Studies.
- Module E (YouTube reverse search) is deferred. Stub the API endpoint for
  graceful fallback.
- Four modules tackled in parallel; phase checkpoints provide discipline.
- Fine-tune may fail. Module A must work end-to-end via Anthropic API fallback
  even if QLoRA training yields nothing usable.
- Push back hard on scope creep that adds multi-user, auth-flow, or
  public-deployment work.

## The Modules in v1

### Module A — Strategic Advisor (CORE)

FEN → Position Classifier (rule-based: pawn structure, phase, material
imbalances) → RAG retrieval over book corpus → LLM call (Gemma 4 E4B
fine-tuned, with Anthropic API fallback) → formatted explanation with
citations.

PDF corpus (~50-150 curated English strategy books) will be placed in
`data/raw_pdfs/` by the user. PDF audit script will be built later.
Extraction pipeline (PyMuPDF + ChessVision per-diagram) is built fresh.

Voice: neutral analytical, English, calibrated to ~1500-2000 ELO. No
personalization, no ELO adaptation, no feedback loop.

Module A explains *ideas* of any position, including openings. Module B
handles *prep diff*. Both can fire on the same position; outputs stack in
the UI, not merge.

### Module B — Repertoire Deviation Detector

Input: PGN game. Output: first move number where user deviated from prepared
repertoire, plus the move they should have played.

Repertoire model: exactly two PGN files per user, `white.pgn` and `black.pgn`
under `data/repertoires/`. System reads user color from PGN headers, opens
correct repertoire file, walks both move lists in parallel until divergence.

### Module D — Streamlit Web App

Local Streamlit on localhost:8501. Workflow:

1. Top input: paste Lichess or Chess.com URL, or upload PGN file
2. App fetches PGN:
   - Lichess: `GET https://lichess.org/game/export/{game_id}.pgn`
   - Chess.com: Public Data API
     `GET https://api.chess.com/pub/player/{user}/games/{YYYY}/{MM}`
3. Three panels:
   - Panel 1 (Repertoire): "Deviation on move N. Played X, repertoire plays Y."
   - Panel 2 (Engine): Lichess Cloud Eval if available, else local Stockfish.
     Numerical eval graph across moves, best-move arrow at selected ply.
   - Panel 3 (Strategic): Module A output. Picks default ply by largest eval
     drop or deviation move from B. Click any ply to update.

Streamlit specifics:
- `st.session_state` for loaded game
- `st.cache_data` aggressively on LLM calls keyed by (FEN, classifier_tags)
- Layout: `st.columns([2, 3])` with chessboard left
- Board rendering: `streamlit.components.v1` with chessboard.js HTML embed
- Dark theme default in `.streamlit/config.toml`

### Module E — Stub

`/youtube_search` endpoint returns
`{"status": "deferred", "use_chessvision_extension_for_now": true}`.

## Architecture

Docker Compose for backend services. LLM inference outside Docker on the Mac
host (Apple Silicon Metal not available inside Docker).

```
Chess-Coach/
├── CLAUDE.md
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── .env.example
├── .gitignore
├── .streamlit/config.toml
├── data/
│   ├── raw_pdfs/                 # user provides PDFs later
│   ├── repertoires/              # white.pgn, black.pgn
│   ├── extracted/                # SQLite of (FEN, commentary) rows
│   ├── db/                       # ChromaDB persistent dir
│   └── models/                   # GGUF + LoRA adapter
├── src/
│   ├── shared/
│   │   ├── chess_utils.py        # FEN/PGN helpers
│   │   ├── db.py                 # SQLite + ChromaDB connection
│   │   ├── schemas.py            # Pydantic models
│   │   ├── settings.py           # pydantic-settings
│   │   └── game_fetcher.py       # Lichess + Chess.com PGN fetch
│   ├── advisor/                  # Module A
│   ├── repertoire/               # Module B
│   ├── engine/                   # lichess_cloud, local_stockfish
│   ├── api/                      # FastAPI
│   ├── audit/                    # PDF audit (built in Phase 2)
│   └── ui/
│       ├── streamlit_app.py      # Module D
│       └── components/
├── notebooks/
│   └── PHASE2_IDEAS.md           # scope-creep dumping ground
├── scripts/
└── tests/
```

## Pydantic Schemas (define in src/shared/schemas.py)

```python
from pydantic import BaseModel
from typing import Literal

class GameFetchRequest(BaseModel):
    url: str
    pgn_override: str | None = None

class GameMetadata(BaseModel):
    site: Literal["lichess", "chesscom", "manual"]
    game_id: str
    white_username: str
    black_username: str
    user_color: Literal["white", "black"]
    result: str
    pgn: str

class AdviseRequest(BaseModel):
    fen: str
    game_url: str | None = None
    player_color: Literal["white", "black"] | None = None

class BookCitation(BaseModel):
    source: str
    page: int
    snippet: str

class AdviseResponse(BaseModel):
    fen: str
    explanation: str
    citations: list[BookCitation]
    classifier_tags: list[str]
    model_used: Literal["gemma_local", "anthropic_fallback"]

class RepertoireDiffRequest(BaseModel):
    pgn: str
    username: str

class RepertoireDeviation(BaseModel):
    deviated: bool
    deviation_move_number: int | None
    move_played: str | None
    move_expected: str | None
    fen_at_deviation: str | None
    repertoire_line_name: str | None

class EvalRequest(BaseModel):
    fen: str
    source: Literal["lichess_cloud", "local_stockfish", "any"]

class EvalResponse(BaseModel):
    fen: str
    cp: int | None
    mate: int | None
    best_move_uci: str | None
    pv: list[str]
    source: str

class GameEvalSeries(BaseModel):
    plies: list[EvalResponse]
    largest_drop_ply: int | None
```

## Tech Stack (Locked)

| Layer | Choice |
|---|---|
| Python | 3.11 + uv |
| PDF | PyMuPDF |
| Engine | Stockfish 17 (Docker, fallback only) + Lichess Cloud Eval |
| Vision | gudbrandtandberg/ChessVision (later) |
| Embeddings | bge-small-en-v1.5 |
| Vector DB | ChromaDB (Docker) |
| LLM dev | Anthropic API (Sonnet 4.6) |
| LLM prod | llama.cpp + GGUF Gemma 4 E4B (host) |
| Fine-tune | Unsloth + QLoRA on Colab Pro |
| Backend | FastAPI + Uvicorn (Docker) |
| UI | Streamlit (Docker, port 8501) |
| Game APIs | Lichess Open API, Chess.com Public Data |
| PGN | python-chess |
| Board render | streamlit.components.v1 with chessboard.js |

## Phase-Based Build Plan

User works in their own rhythm. Move to next phase only when current phase's
acceptance is met.

### Phase 1 — Scaffold (THIS TURN)
Repo structure, Docker, FastAPI stubs, Streamlit landing page, schemas,
chess_utils.

Acceptance: `docker compose up` works, /health 200, Streamlit loads.

### Phase 2 — Foundations
Game fetcher (Lichess + Chess.com), Streamlit URL input → metadata display,
PDF extraction on 1 book, Module B PGN parser.

### Phase 3 — Scale & Engine Source
Extraction on top 50 books (≥5,000 rows). Module B diff logic. Lichess Cloud
Eval client.

### Phase 4 — RAG & Wire-Up
ChromaDB indexed. /advise endpoint returns valid AdviseResponse via Anthropic
fallback. All three Streamlit panels render real data.

### Phase 5 — SHIP GATE
End-to-end Lichess flow + Chess.com flow with local Stockfish.
If failing: cut chess.com support, do not start fine-tune Phase 6.

### Phase 6 — Fine-tune Dataset
Generate ~2,000 instruction pairs. Cost ≤€15. Output:
`data/extracted/finetune_dataset.jsonl`.

### Phase 7 — QLoRA Fine-tune
Unsloth on Colab Pro, 2-4 hours. Save adapter, convert to GGUF.

### Phase 8 — Local Inference Swap
Module A primary = llama.cpp, fallback = Anthropic. Streamlit side-by-side
toggle.

### Phase 9 — Edge Cases & Hardening
PGN edge cases, error handling, 5 real games end-to-end.

### Phase 10 — Polish & Demo
UI tightening, operational README, demo video recorded (3-5 min, 2-3 takes).

## Get-Shit-Done 2.0 Hooks

Per turn:
1. State module(s) being touched
2. State smallest testable end-to-end slice
3. Write code, run it, show output
4. End with: working / stubbed / next slice

Per session:
- Read CLAUDE.md first
- Run previous phase's acceptance before new work
- Scope creep → notebooks/PHASE2_IDEAS.md

## Code Conventions

- Type hints everywhere, no `Any`
- Pydantic for all I/O
- ruff lint, pytest tests
- Streamlit: `st.session_state`, `st.cache_data`/`st.cache_resource`
- stdlib `logging`, no `print()` in `src/`
- Secrets in `.env`, `.env.example` shows schema
- Conventional commits, feature branches per module

## Failure Mode Cuts (in order)

1. Module E stub (already deferred)
2. Chess.com support (Lichess-only)
3. Position classifier sophistication
4. Gemma fine-tune itself (Anthropic stays primary)

Don't cut: Module A RAG, Module B diff, Streamlit panels on Lichess.

## Demo Scenario (Phase 10)

User pastes Lichess Catalan game URL where they deviated on move 9.
Three panels render:
- Panel 1: "Deviation on move 9. You played Bd2; repertoire plays Qc2."
- Panel 2: Eval graph showing drop from +0.4 to -0.7 over moves 9-12.
- Panel 3: Analytical paragraph on Catalan plan with citation.

User clicks move 22 (IQP middlegame). Panel 3 updates with IQP-specific
explanation citing Watson MCO vol. 1 p. 142.

Build for this exact walkthrough. Nothing else.

## Phase 1 Deliverables — Your Tasks Right Now

In this turn, do exactly the following, in order:

1. Print a one-paragraph project pitch in your own words (your understanding,
   not a copy-paste).
2. Create the repo structure as specified above. Note: `README.md` already
   exists; do not overwrite it. If empty, populate with a brief project
   summary.
3. Write `CLAUDE.md` containing: mission, modules, build order, tech stack,
   code conventions, "current status: Phase 1 in progress".
4. Write `pyproject.toml` with all needed deps:
   - core: pymupdf, python-chess, chromadb, sentence-transformers, fastapi,
     uvicorn, pydantic, pydantic-settings, anthropic, tqdm, pandas,
     sqlalchemy, httpx, streamlit, stockfish
   - training extras (optional): torch, transformers, peft, trl, bitsandbytes,
     datasets
   - dev extras: ruff, pytest, ipykernel
5. Write `docker-compose.yml` with three services: api, chromadb, streamlit.
6. Minimal `Dockerfile` (Python 3.11 slim, uv-based install).
7. `.streamlit/config.toml` with dark theme + `server.headless = true`.
8. `.env.example` with: ANTHROPIC_API_KEY, LICHESS_USERNAME,
   CHESSCOM_USERNAME.
9. `.gitignore` for: data/raw_pdfs/, data/extracted/, data/db/, data/models/,
   data/repertoires/, *.pdf, *.sqlite, *.db, *.gguf, .env, __pycache__/,
   .venv/, *.egg-info/, .pytest_cache/, .ruff_cache/, .ipynb_checkpoints/,
   .streamlit/secrets.toml, .DS_Store
10. FastAPI at `src/api/main.py` with `/health` and stub endpoints `/advise`,
    `/repertoire/diff`, `/eval`, `/game/fetch`, `/youtube_search` returning
    placeholder responses matching the schema contracts.
11. `src/shared/schemas.py` with all Pydantic models from above.
12. `src/shared/chess_utils.py` with FEN validation, PGN parser, color
    extractor from headers.
13. `src/ui/streamlit_app.py` minimal landing page: title "Caissa",
    `st.text_input` for game URL, footer with API health status from
    localhost:8000/health.
14. `tests/test_smoke.py`: import schemas, call /health via TestClient,
    assert `validate_fen(STARTING_FEN) is True`.
15. `notebooks/PHASE2_IDEAS.md` empty template (header + "ideas to consider
    after Phase 10").
16. Run `docker compose up --build`. Confirm:
    - `curl localhost:8000/health` returns 200
    - localhost:8501 loads landing page
    - Streamlit shows API health
17. Commit as `chore: phase 1 scaffold`.
18. End with status report in this exact format:

```
## Phase 1 Complete

WORKING:
- [list]

STUBBED:
- [list]

NEXT (Phase 2):
- [list]

OPEN QUESTIONS:
- [if any]
```

Do not start Module A's PDF extraction in this turn. Phase 1 is scaffold only.
Phase 2 starts in a fresh turn.

Begin.
