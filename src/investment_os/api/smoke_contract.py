"""Strict validation for the PR-00 operator smoke test."""

from typing import Any


def validate_health_payload(payload: dict[str, Any], *, expected_status: str) -> None:
    """Fail closed when a health payload weakens the bootstrap safety contract."""

    expected = {
        "schema_version": "1.0",
        "service": "investment-api",
        "status": expected_status,
        "mode": "DEVELOPMENT",
        "live_trading": False,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f"unexpected {key}: {payload.get(key)!r}")
