from investment_os.infrastructure.settings import Settings


def test_bootstrap_settings_do_not_expose_live_trading_switch() -> None:
    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert not hasattr(settings, "auto_trade")
    assert not hasattr(settings, "live_trading")
