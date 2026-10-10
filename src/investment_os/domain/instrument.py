"""Pure instrument identity and catalog normalization for PRODUCT-05."""

from dataclasses import dataclass

from investment_os.domain.errors import DomainError, DomainErrorCode


def normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized:
        raise DomainError(DomainErrorCode.OUT_OF_RANGE, "symbol must not be empty")
    if len(normalized) > 64:
        raise DomainError(DomainErrorCode.OUT_OF_RANGE, "symbol must be at most 64 characters")
    return normalized


def normalize_market(market: str) -> str:
    normalized = market.strip().upper()
    if not normalized:
        raise DomainError(DomainErrorCode.OUT_OF_RANGE, "market must not be empty")
    if len(normalized) > 64:
        raise DomainError(DomainErrorCode.OUT_OF_RANGE, "market must be at most 64 characters")
    return normalized


def normalize_currency(currency: str) -> str:
    normalized = currency.strip().upper()
    if len(normalized) != 3:
        raise DomainError(DomainErrorCode.OUT_OF_RANGE, "currency must be a 3-letter code")
    return normalized


@dataclass(frozen=True, slots=True)
class InstrumentIdentity:
    """Canonical searchable identity for one listed instrument."""

    market: str
    symbol: str
    name: str
    asset_type: str
    currency: str
    sector: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "market", normalize_market(self.market))
        object.__setattr__(self, "symbol", normalize_symbol(self.symbol))
        name = self.name.strip()
        if not name:
            raise DomainError(DomainErrorCode.OUT_OF_RANGE, "name must not be empty")
        if len(name) > 255:
            raise DomainError(DomainErrorCode.OUT_OF_RANGE, "name must be at most 255 characters")
        object.__setattr__(self, "name", name)
        asset_type = self.asset_type.strip().upper()
        if not asset_type:
            raise DomainError(DomainErrorCode.OUT_OF_RANGE, "asset_type must not be empty")
        object.__setattr__(self, "asset_type", asset_type)
        object.__setattr__(self, "currency", normalize_currency(self.currency))
        sector = self.sector.strip()
        if len(sector) > 64:
            raise DomainError(DomainErrorCode.OUT_OF_RANGE, "sector must be at most 64 characters")
        object.__setattr__(self, "sector", sector)

    @property
    def natural_key(self) -> tuple[str, str]:
        return (self.market, self.symbol)
