from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from investment_os.api.app import create_app
from investment_os.infrastructure.local_access import (
    PAIR_TTL,
    SESSION_TTL,
    LocalAccessStore,
    cookie_name,
    local_origin,
)

ORIGIN = "http://127.0.0.1:18104"
HEADERS = {"Origin": ORIGIN, "X-Investment-OS": "local-ui"}


def test_local_pairing_is_single_use_and_stores_only_hashes(tmp_path: Path) -> None:
    store = LocalAccessStore(tmp_path / "access.sqlite3")
    code = store.issue_pairing(ORIGIN, now=100)
    token, expiry = store.exchange(code, ORIGIN, now=101)
    assert expiry == 101 + SESSION_TTL
    assert store.session_expiry(token, ORIGIN, now=102) == expiry
    assert code.encode() not in store.path.read_bytes()
    assert token.encode() not in store.path.read_bytes()
    with pytest.raises(ValueError):
        store.exchange(code, ORIGIN, now=102)


def test_pairing_expiry_boundary_and_origin_are_enforced(tmp_path: Path) -> None:
    store = LocalAccessStore(tmp_path / "access.sqlite3")
    code = store.issue_pairing(ORIGIN, now=100)
    with pytest.raises(ValueError):
        store.exchange(code, "http://127.0.0.1:9999", now=101)
    with pytest.raises(ValueError):
        store.exchange(code, ORIGIN, now=100 + PAIR_TTL)
    code = store.issue_pairing(ORIGIN, now=200)
    token, expiry = store.exchange(code, ORIGIN, now=201)
    assert store.session_expiry(token, ORIGIN, now=expiry - 1) == expiry
    assert store.session_expiry(token, ORIGIN, now=expiry) is None
    assert store.session_expiry(token, "http://127.0.0.1:9999", now=202) is None


def test_sessions_survive_restart_but_revocation_persists(tmp_path: Path) -> None:
    path = tmp_path / "access.sqlite3"
    store = LocalAccessStore(path)
    token, expiry = store.exchange(store.issue_pairing(ORIGIN), ORIGIN)
    assert LocalAccessStore(path).session_expiry(token, ORIGIN) == expiry
    LocalAccessStore(path).revoke(token)
    assert LocalAccessStore(path).session_expiry(token, ORIGIN) is None


def test_concurrent_pairing_redeems_exactly_once(tmp_path: Path) -> None:
    store = LocalAccessStore(tmp_path / "access.sqlite3")
    code = store.issue_pairing(ORIGIN)

    def redeem(_: int) -> bool:
        try:
            store.exchange(code, ORIGIN)
        except ValueError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(redeem, [1, 2])) == [False, True]


@pytest.mark.parametrize(
    "value",
    [
        "https://remote.example",
        "http://0.0.0.0:8100",
        "http://127.0.0.1.evil.test",
        "http://user@127.0.0.1",
        "http://127.0.0.1/x",
        "http://127.0.0.1#secret",
    ],
)
def test_local_mode_refuses_remote_or_ambiguous_origin(value: str) -> None:
    with pytest.raises(ValueError):
        local_origin(value)


def test_browser_pair_cookie_and_business_reads_need_authorization(tmp_path: Path) -> None:
    store = LocalAccessStore(tmp_path / "access.sqlite3")
    app = create_app(local_access_store=store, local_access_origin=ORIGIN)
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/api/v1/product-capabilities").status_code == 401
        assert client.get("/api/v1/auth/session").json()["authenticated"] is False
        code = store.issue_pairing(ORIGIN)
        paired = client.post("/api/v1/auth/pair", headers=HEADERS, json={"code": code})
        assert paired.status_code == 200
        assert code not in paired.text
        assert "HttpOnly" in paired.headers["set-cookie"]
        assert "SameSite=strict" in paired.headers["set-cookie"]
        assert "Max-Age=2592000" in paired.headers["set-cookie"]
        assert client.get("/api/v1/auth/session").json()["authenticated"] is True
        assert client.get("/api/v1/product-capabilities").status_code == 200
        assert client.post("/api/v1/auth/check", headers=HEADERS).status_code == 200
        assert client.post("/api/v1/auth/check").status_code == 403
        assert (
            client.post("/api/v1/auth/pair", headers=HEADERS, json={"code": code}).status_code
            == 401
        )


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example", "X-Investment-OS": "local-ui"},
        {"Origin": "null", "X-Investment-OS": "local-ui"},
        {"Origin": ORIGIN},
        {"X-Investment-OS": "local-ui"},
        {},
    ],
)
def test_cross_origin_and_missing_csrf_cannot_pair(tmp_path: Path, headers: dict[str, str]) -> None:
    store = LocalAccessStore(tmp_path / "access.sqlite3")
    with TestClient(
        create_app(local_access_store=store, local_access_origin=ORIGIN), base_url=ORIGIN
    ) as client:
        code = store.issue_pairing(ORIGIN)
        response = client.post("/api/v1/auth/pair", headers=headers, json={"code": code})
        assert response.status_code == 403
        assert code not in response.text
        assert (
            client.post("/api/v1/auth/pair", headers=HEADERS, json={"code": code}).status_code
            == 200
        )


def test_wrong_host_cannot_read_or_pair_even_with_forwarded_headers(tmp_path: Path) -> None:
    store = LocalAccessStore(tmp_path / "access.sqlite3")
    with TestClient(
        create_app(local_access_store=store, local_access_origin=ORIGIN), base_url=ORIGIN
    ) as client:
        response = client.get(
            "/api/v1/auth/session",
            headers={"Host": "evil.example", "X-Forwarded-Host": "127.0.0.1:18104"},
        )
        assert response.status_code == 403


def test_logout_revokes_copied_cookie_and_cli_bearer_still_works(tmp_path: Path) -> None:
    store = LocalAccessStore(tmp_path / "access.sqlite3")
    app = create_app(
        write_api_token="synthetic-cli-access", local_access_store=store, local_access_origin=ORIGIN
    )
    with TestClient(app, base_url=ORIGIN) as client:
        client.post(
            "/api/v1/auth/pair", headers=HEADERS, json={"code": store.issue_pairing(ORIGIN)}
        )
        copied = client.cookies.get(cookie_name(ORIGIN))
        assert copied is not None
        assert client.post("/api/v1/auth/logout", headers=HEADERS).status_code == 204
        client.cookies.set(cookie_name(ORIGIN), copied)
        assert client.get("/api/v1/product-capabilities").status_code == 401
        assert (
            client.post(
                "/api/v1/auth/check", headers={"Authorization": "Bearer synthetic-cli-access"}
            ).status_code
            == 200
        )


@pytest.mark.parametrize(
    "body",
    [
        {"code": "synthetic-private-input"},
        {"code": {"private": "synthetic-private-input"}},
        {"other": "synthetic-private-input"},
    ],
)
def test_invalid_pairing_never_echoes_inputs(tmp_path: Path, body: dict[str, object]) -> None:
    store = LocalAccessStore(tmp_path / "access.sqlite3")
    with TestClient(
        create_app(local_access_store=store, local_access_origin=ORIGIN), base_url=ORIGIN
    ) as client:
        response = client.post("/api/v1/auth/pair", headers=HEADERS, json=body)
        assert response.status_code == 401
        assert "synthetic-private-input" not in response.text
