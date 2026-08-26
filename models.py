from dataclasses import dataclass


@dataclass
class Market:
    base: str
    quote: str
    symbol: str
    exchange: str
    volume_24h: float
    active: bool
    contract_type: str