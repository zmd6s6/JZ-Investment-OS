"""Named regression tests for read-time evidence freshness derivation (R3)."""

from datetime import UTC, datetime, timedelta

import pytest

from investment_os.application.evidence import FreshnessStatus, derive_display_freshness

BASE = datetime(2026, 10, 9, 12, 0, 0, tzinfo=UTC)


def test_freshness_before_equal_after_available_at() -> None:
    available = BASE
    before = derive_display_freshness(
        as_of=available - timedelta(seconds=1),
        available_at=available,
        expires_at=BASE + timedelta(hours=1),
    )
    at = derive_display_freshness(
        as_of=available,
        available_at=available,
        expires_at=BASE + timedelta(hours=1),
    )
    after = derive_display_freshness(
        as_of=available + timedelta(seconds=1),
        available_at=available,
        expires_at=BASE + timedelta(hours=1),
    )
    assert before is FreshnessStatus.NOT_YET_AVAILABLE
    assert at is FreshnessStatus.FRESH
    assert after is FreshnessStatus.FRESH


def test_freshness_not_yet_available_then_becomes_fresh_without_rewrite() -> None:
    available = BASE + timedelta(seconds=4)
    expires = BASE + timedelta(hours=1)
    stored_ingest_status = FreshnessStatus.NOT_YET_AVAILABLE
    early = derive_display_freshness(
        as_of=BASE,
        available_at=available,
        expires_at=expires,
        ingested_status=stored_ingest_status,
    )
    late = derive_display_freshness(
        as_of=available + timedelta(milliseconds=1),
        available_at=available,
        expires_at=expires,
        ingested_status=stored_ingest_status,
    )
    assert early is FreshnessStatus.NOT_YET_AVAILABLE
    # Stored ingest status must not freeze the display after available_at.
    assert late is FreshnessStatus.FRESH


def test_freshness_before_equal_after_expires_at() -> None:
    expires = BASE + timedelta(hours=1)
    before = derive_display_freshness(
        as_of=expires - timedelta(seconds=1),
        available_at=BASE,
        expires_at=expires,
    )
    at = derive_display_freshness(as_of=expires, available_at=BASE, expires_at=expires)
    after = derive_display_freshness(
        as_of=expires + timedelta(seconds=1),
        available_at=BASE,
        expires_at=expires,
    )
    assert before is FreshnessStatus.FRESH
    assert at is FreshnessStatus.EXPIRED
    assert after is FreshnessStatus.EXPIRED


def test_freshness_ingested_fresh_but_expired_at_read() -> None:
    status = derive_display_freshness(
        as_of=BASE + timedelta(hours=2),
        available_at=BASE,
        expires_at=BASE + timedelta(hours=1),
        ingested_status=FreshnessStatus.FRESH,
    )
    assert status is FreshnessStatus.EXPIRED


def test_freshness_observed_past_available_future() -> None:
    # observed_at is in the past but available_at is still in the future.
    status = derive_display_freshness(
        as_of=BASE,
        available_at=BASE + timedelta(minutes=30),
        expires_at=BASE + timedelta(hours=2),
    )
    assert status is FreshnessStatus.NOT_YET_AVAILABLE


def test_freshness_stored_stale_stays_stale_when_available() -> None:
    status = derive_display_freshness(
        as_of=BASE + timedelta(minutes=5),
        available_at=BASE,
        expires_at=BASE + timedelta(hours=1),
        ingested_status=FreshnessStatus.STALE,
    )
    assert status is FreshnessStatus.STALE


def test_freshness_naive_timestamps_fail_closed() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        derive_display_freshness(
            as_of=BASE.replace(tzinfo=None),
            available_at=BASE,
            expires_at=None,
        )
