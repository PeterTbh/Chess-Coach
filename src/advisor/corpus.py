"""Seed corpus loader + ChromaDB indexer (Slice 4a).

The seed corpus at ``data/corpus_seed.json`` is a hand-written placeholder
keyed on the classifier's tag vocabulary. Each entry is one row in the
``caissa_corpus_v1`` collection of an on-disk ChromaDB persistent client.

When real PDFs land, the extraction pipeline will produce JSON of the
same shape and this indexer keeps working unchanged.

The indexer is idempotent: it compares the seed file's mtime against
``collection.metadata["seed_mtime"]`` and skips when unchanged. To force
a rebuild, touch the seed file or pass ``force=True``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from chromadb.config import Settings as ChromaSettings

from src.shared.settings import settings

logger = logging.getLogger(__name__)


# ---- Errors ---------------------------------------------------------------

class CorpusError(Exception):
    """Base for corpus errors."""


class CorpusNotFoundError(CorpusError):
    """The seed file does not exist."""


class CorpusValidationError(CorpusError):
    """A seed entry is missing required fields or has wrong types."""


# ---- Data shapes ----------------------------------------------------------

@dataclass(frozen=True)
class CorpusEntry:
    id: str
    tags: list[str]
    source: str
    page: int
    snippet: str

    def to_metadata(self) -> dict[str, Any]:
        """Chroma metadata must be JSON-scalar; encode tags as comma-string."""
        return {
            "source": self.source,
            "page": self.page,
            "tags_csv": ",".join(self.tags),
            "snippet": self.snippet,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> CorpusEntry:
        missing = {"id", "tags", "source", "page", "snippet"} - d.keys()
        if missing:
            raise CorpusValidationError(
                f"seed entry missing fields: {sorted(missing)}"
            )
        if not isinstance(d["tags"], list) or not all(
            isinstance(t, str) for t in d["tags"]
        ):
            raise CorpusValidationError(
                f"seed entry {d['id']!r}: tags must be list[str]"
            )
        if not isinstance(d["page"], int):
            raise CorpusValidationError(
                f"seed entry {d['id']!r}: page must be int"
            )
        return CorpusEntry(
            id=str(d["id"]),
            tags=list(d["tags"]),
            source=str(d["source"]),
            page=int(d["page"]),
            snippet=str(d["snippet"]),
        )


# ---- Embedder -------------------------------------------------------------

class BgeEmbedder(EmbeddingFunction[Documents]):
    """sentence-transformers wrapper for ``BAAI/bge-small-en-v1.5``.

    Model is loaded lazily on first call so importing this module is free.
    Embeddings are normalised, so cosine similarity == dot product.
    """

    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or settings.embedder_model
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # heavy import
            logger.info("loading embedder %s", self._model_name)
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def __call__(self, input: Documents) -> Embeddings:
        model = self._load()
        return model.encode(list(input), normalize_embeddings=True).tolist()

    def name(self) -> str:
        return f"bge:{self._model_name}"

    def get_config(self) -> dict[str, Any]:
        return {"model_name": self._model_name}

    @classmethod
    def build_from_config(cls, config: dict[str, Any]) -> BgeEmbedder:
        return cls(model_name=config.get("model_name"))


class FakeEmbedder(EmbeddingFunction[Documents]):
    """Deterministic hash-based embedder for tests. 64-dim float vectors."""

    DIM = 64

    def __init__(self, dim: int = DIM) -> None:
        self._dim = dim

    def __call__(self, input: Documents) -> Embeddings:
        return [self._encode(s) for s in input]

    def _encode(self, s: str) -> list[float]:
        out: list[float] = []
        seed = s.encode("utf-8")
        for i in range(self._dim):
            h = hashlib.sha256(seed + i.to_bytes(2, "big")).digest()
            out.append((int.from_bytes(h[:4], "big") / 2**32) * 2 - 1)
        norm = sum(x * x for x in out) ** 0.5 or 1.0
        return [x / norm for x in out]

    def name(self) -> str:
        return "fake-sha256-64"

    def get_config(self) -> dict[str, Any]:
        return {"dim": self._dim}

    @classmethod
    def build_from_config(cls, config: dict[str, Any]) -> FakeEmbedder:
        return cls(dim=int(config.get("dim", cls.DIM)))


# Type alias for callers passing an embedder around.
Embedder = EmbeddingFunction[Documents]


# ---- Client + collection -------------------------------------------------

def get_client(persist_dir: Path | str | None = None) -> ClientAPI:
    """Return a Chroma persistent client rooted at ``persist_dir``."""
    p = Path(persist_dir) if persist_dir is not None else Path(settings.chroma_persist_dir)
    p.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(p),
        settings=ChromaSettings(anonymized_telemetry=False),
    )


def get_or_create_collection(
    client: ClientAPI,
    embedder: Embedder,
    name: str | None = None,
) -> Collection:
    """Get or create the seed-corpus collection bound to ``embedder``."""
    coll_name = name or settings.corpus_collection
    return client.get_or_create_collection(
        name=coll_name,
        embedding_function=embedder,  # type: ignore[arg-type]
        metadata={"hnsw:space": "cosine"},
    )


# ---- Load + index --------------------------------------------------------

def load_seed(seed_path: Path | str | None = None) -> list[CorpusEntry]:
    """Read seed JSON and validate every entry."""
    p = Path(seed_path) if seed_path is not None else Path(settings.corpus_seed_path)
    if not p.is_file():
        raise CorpusNotFoundError(f"corpus seed not found: {p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CorpusValidationError(f"corpus seed is not valid JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise CorpusValidationError("corpus seed root must be a list")
    return [CorpusEntry.from_dict(d) for d in raw]


def build_or_refresh_corpus(
    collection: Collection,
    seed_path: Path | str | None = None,
    *,
    force: bool = False,
) -> int:
    """Index the seed file into ``collection``. Returns rows written.

    Idempotent: skips when the seed's mtime matches the collection's
    stored ``seed_mtime`` and ``force`` is False.
    """
    p = Path(seed_path) if seed_path is not None else Path(settings.corpus_seed_path)
    if not p.is_file():
        raise CorpusNotFoundError(f"corpus seed not found: {p}")
    file_mtime = p.stat().st_mtime
    stored = (collection.metadata or {}).get("seed_mtime")
    if not force and stored is not None and float(stored) == file_mtime:
        logger.info("corpus up to date (seed_mtime=%s) — no reindex", stored)
        return 0

    entries = load_seed(p)
    _wipe_collection(collection)
    if entries:
        collection.add(
            ids=[e.id for e in entries],
            documents=[_document_text(e) for e in entries],
            metadatas=[e.to_metadata() for e in entries],
        )

    # Chroma forbids changing the distance function via modify(), so drop
    # any immutable config keys before persisting our own bookkeeping.
    new_meta = {
        k: v
        for k, v in (collection.metadata or {}).items()
        if not k.startswith("hnsw:")
    }
    new_meta["seed_mtime"] = file_mtime
    new_meta["seed_path"] = str(p)
    collection.modify(metadata=new_meta)
    logger.info("indexed %d corpus rows from %s", len(entries), p)
    return len(entries)


def _wipe_collection(collection: Collection) -> None:
    existing = collection.get(include=[])
    ids = existing.get("ids") or []
    if ids:
        collection.delete(ids=ids)


def _document_text(entry: CorpusEntry) -> str:
    """The string the embedder sees. Includes tags so retrieval by tag works."""
    return f"{', '.join(entry.tags)} :: {entry.snippet}"


# ---- CLI entry -----------------------------------------------------------

def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    embedder = BgeEmbedder()
    client = get_client()
    collection = get_or_create_collection(client, embedder)
    written = build_or_refresh_corpus(collection, force=True)
    print(f"indexed {written} rows into {settings.corpus_collection}")


if __name__ == "__main__":
    _main()
