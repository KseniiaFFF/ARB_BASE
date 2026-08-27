from dataclasses import dataclass


@dataclass
class Contract:
    exchange: str
    symbol: str
    asset: str
    quote: str
    contract_type: str
    active: bool

    contract_size: float

    contract_size_currency: str


@dataclass
class Market:
    asset: str
    base: str
    quote: str
    symbol: str
    exchange: str
    volume_24h: float
    active: bool
    contract_type: str