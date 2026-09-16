import time

from price_feeds.orderbook_models import OrderBook


class LazySortedLevels:
    """List-like view over a price->quantity dict.

    Sorting is deferred until the scanner actually needs to iterate/index
    the levels. The sorted result is cached until invalidate() is called.
    """

    __slots__ = ("_levels", "_reverse", "_cache")

    def __init__(self, levels: dict[float, float], reverse: bool = False):
        self._levels = levels
        self._reverse = reverse
        self._cache = None

    def invalidate(self) -> None:
        self._cache = None

    def _sorted(self):
        cached = self._cache
        if cached is None:
            cached = sorted(
                self._levels.items(),
                reverse=self._reverse,
            )
            self._cache = cached
        return cached

    def __iter__(self):
        return iter(self._sorted())

    def __len__(self):
        return len(self._levels)

    def __getitem__(self, item):
        return self._sorted()[item]

    def __bool__(self):
        return bool(self._levels)


orderbook_cache: dict[str, dict[str, OrderBook]] = {}


def update_orderbook(orderbook: OrderBook) -> None:
    exchange_cache = orderbook_cache.setdefault(orderbook.exchange, {})
    exchange_cache[orderbook.symbol] = orderbook


def get_orderbook(exchange: str, symbol: str) -> OrderBook | None:
    return orderbook_cache.get(exchange, {}).get(symbol)


def get_orderbook_age_ms(orderbook: OrderBook) -> int | None:
    if orderbook.received_at <= 0:
        return None

    now_ms = int(time.time() * 1000)
    age = now_ms - orderbook.received_at

    if age < 0:
        return None

    return age


def is_orderbook_fresh(orderbook: OrderBook, max_age_ms: int) -> bool:
    age = get_orderbook_age_ms(orderbook)
    if age is None:
        return False
    return age <= max_age_ms


def get_orderbook_count() -> int:
    return sum(len(exchange_cache) for exchange_cache in orderbook_cache.values())


def get_exchange_orderbooks(exchange: str) -> dict[str, OrderBook]:
    return orderbook_cache.get(exchange, {})


def remove_orderbook(exchange: str, symbol: str) -> None:
    exchange_cache = orderbook_cache.get(exchange)
    if not exchange_cache:
        return

    exchange_cache.pop(symbol, None)

    if not exchange_cache:
        orderbook_cache.pop(exchange, None)


def clear_orderbook_cache() -> None:
    orderbook_cache.clear()
