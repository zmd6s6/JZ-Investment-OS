"""Local single-user write API authentication (ADR-0017 aligned)."""

from __future__ import annotations

import asyncio
import secrets
import sqlite3
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from investment_os.infrastructure.local_access import LocalAccessStore, cookie_name

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def _extract_bearer(header_value: str | None) -> str | None:
    if not header_value:
        return None
    scheme, _, token = header_value.partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = token.strip()
    return token or None


class WriteApiAuthMiddleware(BaseHTTPMiddleware):
    """Require Bearer write token on non-safe /api/v1 methods.

    Fail closed: when no token is configured, all write API calls are rejected.
    Health and read endpoints stay available.
    """

    def __init__(
        self,
        app: ASGIApp,
        token: str | None,
        local_store: LocalAccessStore | None = None,
        origin: str | None = None,
    ) -> None:
        super().__init__(app)
        self._token = token.strip() if token and token.strip() else None
        self._local_store = local_store
        self._origin = origin

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if self._local_store is not None and self._origin is not None:
            return await self._local_dispatch(request, call_next)
        if request.method in SAFE_METHODS or not request.url.path.startswith("/api/v1/"):
            return await call_next(request)

        if self._token is None:
            return JSONResponse(
                status_code=503,
                content={"detail": "write_api_token_not_configured"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        presented = _extract_bearer(request.headers.get("authorization"))
        if presented is None or not secrets.compare_digest(presented, self._token):
            return JSONResponse(
                status_code=401,
                content={"detail": "write_api_unauthorized"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)

    async def _local_dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        assert self._local_store is not None and self._origin is not None
        if request.url.path in {"/health/live", "/health/ready"}:
            return await call_next(request)
        # Use the actual Host, not attacker-controlled forwarded headers.
        expected_host = self._origin.removeprefix("http://")
        if request.headers.get("host", "").lower() != expected_host:
            return JSONResponse(status_code=403, content={"detail": "local_origin_mismatch"})
        if not request.url.path.startswith("/api/v1/"):
            return await call_next(request)
        origin = request.headers.get("origin")
        if origin is not None and origin != self._origin:
            return JSONResponse(status_code=403, content={"detail": "local_origin_mismatch"})
        unsafe = request.method not in SAFE_METHODS
        presented = _extract_bearer(request.headers.get("authorization"))
        bearer_ok = (
            self._token is not None
            and presented is not None
            and secrets.compare_digest(presented, self._token)
        )
        if (
            unsafe
            and not bearer_ok
            and (origin != self._origin or request.headers.get("x-investment-os") != "local-ui")
        ):
            return JSONResponse(status_code=403, content={"detail": "local_origin_required"})
        public = (request.url.path == "/api/v1/auth/session" and request.method == "GET") or (
            request.url.path == "/api/v1/auth/pair" and request.method == "POST"
        )
        try:
            token = request.cookies.get(cookie_name(self._origin), "")
            expiry = await asyncio.to_thread(self._local_store.session_expiry, token, self._origin)
            if not public and not bearer_ok and expiry is None:
                return JSONResponse(status_code=401, content={"detail": "local_access_required"})
            response = await call_next(request)
        except (sqlite3.Error, OSError):
            return JSONResponse(status_code=503, content={"detail": "local_access_unavailable"})
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response
