from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from investment_os.application.universe_snapshots import (
    UniverseConfirm,
    UniverseError,
    UniverseImport,
    UniverseRun,
    UniverseSource,
    parse_members,
)

NOW = datetime(2026, 10, 29, tzinfo=UTC)


def source(total=1):
    return UniverseSource(
        source_name="合成来源",
        source_version="v1",
        source_locator="synthetic://scope.csv",
        market="SSE",
        coverage_definition="只声明此合成集合, 不是全市场",
        observed_at=NOW - timedelta(days=2),
        effective_at=NOW - timedelta(days=1),
        available_at=NOW - timedelta(hours=1),
        declared_total=total,
        completeness="UNKNOWN",
    )


@pytest.mark.parametrize(
    "csv_text,code,row",
    [
        ("symbol,market\nSYN,SSE", "UNIVERSE_CSV_HEADER", 1),
        ("market,symbol\nSSE,SYN\nSSE,SYN", "UNIVERSE_DUPLICATE", 3),
        ("market,symbol\nSZSE,SYN", "UNIVERSE_MARKET_MISMATCH", 2),
        ("market,symbol\nSSE,syn", "UNIVERSE_CSV_ROW", 2),
        ("market,symbol\nSSE,SYN,extra", "UNIVERSE_CSV_ROW", 2),
        ("market,symbol\n\nSSE,SYN", "UNIVERSE_CSV_ROW", 2),
        ("market,symbol\n", "UNIVERSE_COUNT_MISMATCH", None),
    ],
)
def test_csv_never_silently_drops_or_guesses_members(csv_text, code, row):
    with pytest.raises(UniverseError) as error:
        parse_members(UniverseImport(source=source(), csv_text=csv_text))
    assert error.value.code == code and error.value.row == row


def test_utf8_bom_and_symbol_leading_zero_are_preserved():
    command = UniverseImport(source=source(), csv_text="\ufeffmarket,symbol\r\nSSE,000001\r\n")
    assert parse_members(command) == ("000001",)
    assert command.csv_text.startswith("\ufeff")


@pytest.mark.parametrize("value", [False, 1, "true", None])
def test_legal_use_requires_exact_explicit_true(value):
    with pytest.raises(ValidationError):
        UniverseConfirm(
            source=source(),
            csv_text="market,symbol\nSSE,SYN",
            request_id=uuid4(),
            preview_hash="a" * 64,
            legal_use_acknowledgement=value,
            declaration_acknowledgement=True,
        )


def test_missing_dates_unknown_fields_and_subsets_are_not_accepted():
    fields = source().model_dump()
    del fields["available_at"]
    with pytest.raises(ValidationError):
        UniverseSource.model_validate(fields)
    with pytest.raises(ValidationError):
        UniverseSource.model_validate({**source().model_dump(), "independently_verified": True})
    with pytest.raises(ValidationError):
        UniverseRun.model_validate(
            {
                "request_id": str(uuid4()),
                "snapshot_hash": "a" * 64,
                "quote_source_name": "synthetic",
                "fact_source_name": "synthetic",
                "candidate_limit": 1,
                "min_profit_margin": "0.1",
                "min_revenue_growth": "0.1",
                "max_pe": "60",
                "min_price_change": "0",
                "instrument_ids": [str(uuid4())],
            }
        )
