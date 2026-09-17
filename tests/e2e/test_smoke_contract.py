import pytest

from investment_os.api.smoke_contract import validate_health_payload


def test_smoke_contract_accepts_safe_live_payload() -> None:
    validate_health_payload(
        {
            "schema_version": "1.0",
            "service": "investment-api",
            "status": "alive",
            "mode": "DEVELOPMENT",
            "live_trading": False,
        },
        expected_status="alive",
    )


def test_smoke_contract_rejects_live_trading_enabled() -> None:
    with pytest.raises(ValueError, match="live_trading"):
        validate_health_payload(
            {
                "schema_version": "1.0",
                "service": "investment-api",
                "status": "alive",
                "mode": "DEVELOPMENT",
                "live_trading": True,
            },
            expected_status="alive",
        )
