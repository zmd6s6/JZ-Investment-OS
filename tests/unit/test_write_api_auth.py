"""Write API authentication middleware tests."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from investment_os.api.write_auth import WriteApiAuthMiddleware


def _app(token: str | None) -> FastAPI:
    app = FastAPI()
    app.add_middleware(WriteApiAuthMiddleware, token=token)

    @app.get("/api/v1/items")
    async def read() -> dict[str, str]:
        return {"ok": "read"}

    @app.post("/api/v1/items")
    async def write() -> dict[str, str]:
        return {"ok": "write"}

    @app.post("/health/live")
    async def health_write() -> dict[str, str]:
        return {"ok": "health"}

    return app


def test_reads_stay_open_and_writes_fail_closed_without_token() -> None:
    client = TestClient(_app(None))
    assert client.get("/api/v1/items").status_code == 200
    response = client.post("/api/v1/items")
    assert response.status_code == 503
    assert response.json()["detail"] == "write_api_token_not_configured"


def test_write_requires_matching_bearer_token() -> None:
    client = TestClient(_app("secret-token"))
    assert client.post("/api/v1/items").status_code == 401
    assert (
        client.post(
            "/api/v1/items", headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )
    ok = client.post("/api/v1/items", headers={"Authorization": "Bearer secret-token"})
    assert ok.status_code == 200


def test_non_api_write_paths_are_not_gated_by_write_token() -> None:
    client = TestClient(_app(None))
    assert client.post("/health/live").status_code == 200
