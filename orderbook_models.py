from dataclasses import dataclass


@dataclass(slots=True)
class OrderBook:
    exchange: str
    symbol: str

    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]

    timestamp: int
    received_at: int
    received_at_ns: int