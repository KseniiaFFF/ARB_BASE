from dataclasses import dataclass


@dataclass(slots=True)
class OrderBook:

    exchange: str
    symbol: str

    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]

    update_id: int

    timestamp: int
    received_at: int
    received_at_ns: int

    @property
    def best_bid(self) -> tuple[float, float] | None:

        if not self.bids:
            return None

        return self.bids[0]

    @property
    def best_ask(self) -> tuple[float, float] | None:

        if not self.asks:
            return None

        return self.asks[0]

    @property
    def bid_price(self) -> float | None:

        if not self.bids:
            return None

        return self.bids[0][0]

    @property
    def ask_price(self) -> float | None:

        if not self.asks:
            return None

        return self.asks[0][0]

    @property
    def spread(self) -> float | None:

        if not self.bids or not self.asks:
            return None

        return self.asks[0][0] - self.bids[0][0]

    @property
    def spread_percent(self) -> float | None:
        
        if not self.bids or not self.asks:
            return None

        bid = self.bids[0][0]

        if bid <= 0:
            return None

        ask = self.asks[0][0]

        return (ask - bid) / bid * 100
