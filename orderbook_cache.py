import time

from price_feeds.orderbook_models import OrderBook


orderbook_cache: dict[str, dict[str, OrderBook]] = {}


def update_orderbook(
    orderbook: OrderBook,
) -> None:

    exchange = orderbook.exchange
    symbol = orderbook.symbol

    if exchange not in orderbook_cache:
        orderbook_cache[exchange] = {}

    orderbook_cache[exchange][symbol] = orderbook


def get_orderbook(
    exchange: str,
    symbol: str,
) -> OrderBook | None:

    return (
        orderbook_cache
        .get(exchange, {})
        .get(symbol)
    )


def get_orderbook_age_ms(
    orderbook: OrderBook,
) -> int | None:

    if orderbook.received_at <= 0:
        return None

    now_ms = int(
        time.time() * 1000
    )

    age = now_ms - orderbook.received_at

    if age < 0:
        return None

    return age


def is_orderbook_fresh(
    orderbook: OrderBook,
    max_age_ms: int,
) -> bool:

    age = get_orderbook_age_ms(
        orderbook
    )

    if age is None:
        return False

    return age <= max_age_ms


def remove_orderbook(
    exchange: str,
    symbol: str,
) -> None:

    exchange_cache = orderbook_cache.get(
        exchange
    )

    if not exchange_cache:
        return

    exchange_cache.pop(
        symbol,
        None
    )


def clear_orderbook_cache() -> None:
    orderbook_cache.clear()