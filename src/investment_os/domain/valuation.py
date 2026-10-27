"""Versioned reference valuation; never an investment sizing or execution result."""

from dataclasses import dataclass
from decimal import Decimal, localcontext
from uuid import UUID

from investment_os.domain.values import exact_decimal

FORMULA_VERSION = "cny-reference-valuation-v1"


def nonnegative(value: Decimal | str | int) -> Decimal:
    number = exact_decimal(value)
    exponent = number.as_tuple().exponent
    assert isinstance(exponent, int)  # exact_decimal has rejected all non-finite values.
    if number < 0 or len(number.as_tuple().digits) > 38 or number.adjusted() > 37 or exponent < -18:
        raise ValueError("VALUATION_INPUT_INVALID")
    return number


@dataclass(frozen=True, slots=True)
class HoldingInput:
    instrument_id: UUID
    currency: str
    sector: str
    core_quantity: Decimal
    tactical_quantity: Decimal
    reference_price: Decimal | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "core_quantity", nonnegative(self.core_quantity))
        object.__setattr__(self, "tactical_quantity", nonnegative(self.tactical_quantity))
        if self.reference_price is not None:
            price = nonnegative(self.reference_price)
            if price <= 0:
                raise ValueError("REFERENCE_PRICE_INVALID")
            object.__setattr__(self, "reference_price", price)


@dataclass(frozen=True, slots=True)
class HoldingValue:
    instrument_id: UUID
    core_value: Decimal | None
    tactical_value: Decimal | None
    total_value: Decimal | None
    core_weight: Decimal | None
    tactical_weight: Decimal | None
    total_weight: Decimal | None


@dataclass(frozen=True, slots=True)
class PortfolioNumbers:
    status: str
    cash: Decimal
    nav: Decimal | None
    market_value: Decimal | None
    cash_weight: Decimal | None
    gross_exposure: Decimal | None
    net_exposure: Decimal | None
    sector_weights: tuple[tuple[str, Decimal], ...]
    holdings: tuple[HoldingValue, ...]


def value_portfolio(
    base_currency: str, cash: Decimal, holdings: tuple[HoldingInput, ...]
) -> PortfolioNumbers:
    """NAV=cash+sum((core+tactical)*price); ratios use fixed Decimal precision 80."""
    cash = nonnegative(cash)
    if len(holdings) > 1000 or len({h.instrument_id for h in holdings}) != len(holdings):
        raise ValueError("VALUATION_HOLDINGS_INVALID")
    holdings = tuple(sorted(holdings, key=lambda h: str(h.instrument_id)))
    with localcontext() as ctx:
        ctx.prec = 80
        fx = base_currency != "CNY" or any(
            h.currency != "CNY" and h.core_quantity + h.tactical_quantity > 0 for h in holdings
        )
        values: list[tuple[HoldingInput, Decimal | None, Decimal | None]] = []
        for h in holdings:
            if fx:
                core = tactical = None
            elif h.core_quantity + h.tactical_quantity == 0:
                core = tactical = Decimal(0)
            elif h.reference_price is None:
                core = tactical = None
            else:
                core = h.core_quantity * h.reference_price
                tactical = h.tactical_quantity * h.reference_price
            values.append((h, core, tactical))
        complete = not fx and all(c is not None and t is not None for _, c, t in values)
        market = (
            sum((c + t for _, c, t in values if c is not None and t is not None), Decimal(0))
            if complete
            else None
        )
        nav = cash + market if market is not None else None
        usable = nav is not None and nav > 0
        rows = tuple(
            HoldingValue(
                h.instrument_id,
                core,
                tactical,
                core + tactical if core is not None and tactical is not None else None,
                core / nav if usable and core is not None and nav is not None else None,
                tactical / nav if usable and tactical is not None and nav is not None else None,
                (core + tactical) / nav
                if usable and core is not None and tactical is not None and nav is not None
                else None,
            )
            for h, core, tactical in values
        )
        sectors: dict[str, Decimal] = {}
        if usable and nav is not None:
            for h, core, tactical in values:
                assert core is not None and tactical is not None
                key = h.sector.strip() or "UNCLASSIFIED"
                sectors[key] = sectors.get(key, Decimal(0)) + core + tactical
            sectors = {key: value / nav for key, value in sectors.items()}
        exposure = market / nav if usable and market is not None and nav is not None else None
        return PortfolioNumbers(
            "FX_REQUIRED"
            if fx
            else "MISSING_PRICES"
            if not complete
            else "ZERO_NAV"
            if not usable
            else "REFERENCE_ONLY",
            cash,
            nav,
            market,
            cash / nav if usable and nav is not None else None,
            exposure,
            exposure,
            tuple(sorted(sectors.items())),
            rows,
        )
