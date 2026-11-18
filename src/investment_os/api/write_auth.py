"""Local single-user mutation and weekly task audit authentication."""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

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
    """Authenticate API mutations and the new weekly opportunity task audit reads.

    An absent token fails closed for these operations. Other existing safe reads
    and OPTIONS retain their previous middleware behavior.
    """

    def __init__(self, app: ASGIApp, token: str | None) -> None:
        super().__init__(app)
        self._token = token.strip() if token and token.strip() else None

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        protected_history = request.method in {"GET", "HEAD"} and any(
            request.url.path == prefix or request.url.path.startswith(prefix + "/")
            for prefix in (
                "/api/v1/opportunities/weekly/tasks",
                "/api/v1/opportunities/complete-weekly/tasks",
            )
        )
        if (
            request.method in SAFE_METHODS and not protected_history
        ) or not request.url.path.startswith("/api/v1/"):
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
