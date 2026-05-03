# Chess-Coach — CLAUDE.md

## Project overview
Personal chess coaching tool (Caissa). Fetches, structures, and serves chess
repertoire data for study and training.

## Current status
- **Module A** (Lichess repertoire importer): pending
- **Module B** (Stockfish analysis pipeline): pending

## Key conventions
- Python ≥ 3.11, async-first
- PGN output must round-trip cleanly through `python-chess`
- Secrets in `.env` (gitignored); template in `.env.example`
