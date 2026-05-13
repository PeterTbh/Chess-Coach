"""Phase 1 smoke tests."""

from fastapi.testclient import TestClient

from src.api.main import app
from src.shared import schemas
from src.shared.chess_utils import STARTING_FEN, validate_fen

client = TestClient(app)


def test_schemas_importable() -> None:
    assert hasattr(schemas, "AdviseResponse")
    assert hasattr(schemas, "DeviationReport")
    assert hasattr(schemas, "EvalResponse")
    assert hasattr(schemas, "GameMetadata")


def test_health_endpoint() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"


def test_validate_starting_fen() -> None:
    assert validate_fen(STARTING_FEN) is True


def test_validate_garbage_fen() -> None:
    assert validate_fen("not a fen") is False


def test_youtube_stub_is_deferred() -> None:
    resp = client.get("/youtube_search")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deferred"
