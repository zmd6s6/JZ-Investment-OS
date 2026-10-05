"""Unit-test harness: configure write token and attach it to API write calls."""

from __future__ import annotations

import os

os.environ.setdefault("INVESTMENT_OS_API_WRITE_TOKEN", "unit-test-write-token")

import httpx

from investment_os.infrastructure.settings import get_settings

get_settings.cache_clear()

WRITE_TOKEN = "unit-test-write-token"
WRITE_HEADERS = {"Authorization": f"Bearer {WRITE_TOKEN}"}

_original_request = httpx.AsyncClient.request


async def _request_with_write_auth(self, method, url, **kwargs):  # type: ignore[no-untyped-def]
    method_upper = str(method).upper()
    if method_upper not in {"GET", "HEAD", "OPTIONS", "TRACE"} and "/api/v1/" in str(url):
        headers = dict(kwargs.get("headers") or {})
        headers.setdefault("Authorization", f"Bearer {WRITE_TOKEN}")
        kwargs["headers"] = headers
    return await _original_request(self, method, url, **kwargs)


httpx.AsyncClient.request = _request_with_write_auth  # type: ignore[method-assign]
