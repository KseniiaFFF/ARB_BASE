from dataclasses import dataclass


@dataclass(slots=True)
class Price:
    asset: str
    exchange: str
    symbol: str

    bid: float
    ask: float

    bid_qty: float
    ask_qty: float

    timestamp: int

    received_at: int
    received_at_ns: int