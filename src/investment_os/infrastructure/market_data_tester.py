"""Composite data-provider connection tester dispatching by profile type."""

from __future__ import annotations

from investment_os.application.provider_settings import (
    DataProviderConnectionTester,
    DataProviderProfile,
    ProviderTestResult,
)

_PROVIDER_TYPE = "TUSHARE_MARKET"


class CompositeDataProviderConnectionTester:
    """Route connection tests to the adapter that owns the profile type."""

    def __init__(
        self,
        *,
        bocha_tester: DataProviderConnectionTester,
        tushare_tester: object,
    ) -> None:
        self._bocha = bocha_tester
        self._tushare = tushare_tester

    async def close(self) -> None:
        close = getattr(self._tushare, "close", None)
        if close is not None:
            await close()

    async def test_connection(
        self, *, profile: DataProviderProfile, credential: str
    ) -> ProviderTestResult:
        if profile.provider_type == _PROVIDER_TYPE:
            ok, detail, latency = await self._tushare_test(credential)
            return ProviderTestResult(
                status="CONNECTION_SUCCEEDED" if ok else "CONNECTION_FAILED",
                detail=detail,
                latency_ms=latency,
            )
        return await self._bocha.test_connection(profile=profile, credential=credential)

    async def _tushare_test(self, credential: str) -> tuple[bool, str, int | None]:
        result = await self._tushare.test(credential=credential)  # type: ignore[attr-defined]
        return (
            bool(result[0]),
            str(result[1]),
            int(result[2]) if result[2] is not None else None,
        )
