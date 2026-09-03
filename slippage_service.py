from dataclasses import dataclass

from price_feeds.orderbook_cache import (
    get_orderbook,
    get_orderbook_age_ms,
    is_orderbook_fresh,
)
from price_feeds.orderbook_models import OrderBook

from profitability.slippage import (
    Side,
    SlippageResult,
    calculate_slippage,
)


# ============================================================
# EXCEPTIONS
# ============================================================


class SlippageServiceError(Exception):
    """Base exception for slippage service."""


class OrderBookNotFoundError(
    SlippageServiceError
):
    """Order book does not exist in cache."""


class StaleOrderBookError(
    SlippageServiceError
):
    """Order book exists but is too old."""


# ============================================================
# RESULT
# ============================================================


@dataclass(slots=True)
class SlippageCheckResult:

    slippage: SlippageResult

    orderbook_age_ms: int

    max_age_ms: int


# ============================================================
# GET ORDER BOOK
# ============================================================


def get_fresh_orderbook(
    exchange: str,
    symbol: str,
    max_age_ms: int,
) -> OrderBook:

    if max_age_ms < 0:

        raise ValueError(
            "max_age_ms должен быть >= 0"
        )

    orderbook = get_orderbook(
        exchange=exchange,
        symbol=symbol,
    )

    if orderbook is None:

        raise OrderBookNotFoundError(
            f"OrderBook не найден в cache: "
            f"{exchange} {symbol}"
        )

    age_ms = get_orderbook_age_ms(
        orderbook
    )

    if age_ms is None:

        raise StaleOrderBookError(
            f"OrderBook {exchange} {symbol}: "
            "невозможно определить возраст"
        )

    if not is_orderbook_fresh(
        orderbook,
        max_age_ms,
    ):

        raise StaleOrderBookError(
            f"OrderBook {exchange} {symbol} "
            f"устарел: "
            f"age={age_ms}ms, "
            f"max_age={max_age_ms}ms"
        )

    return orderbook


# ============================================================
# CALCULATE FROM CACHE
# ============================================================


def calculate_cached_slippage(
    exchange: str,
    symbol: str,
    side: Side,
    quantity: float,
    max_age_ms: int,
) -> SlippageCheckResult:

    orderbook = get_fresh_orderbook(
        exchange=exchange,
        symbol=symbol,
        max_age_ms=max_age_ms,
    )

    result = calculate_slippage(
        orderbook=orderbook,
        side=side,
        quantity=quantity,
    )

    age_ms = get_orderbook_age_ms(
        orderbook
    )

    if age_ms is None:

        raise StaleOrderBookError(
            f"OrderBook {exchange} {symbol}: "
            "возраст стакана неизвестен"
        )

    return SlippageCheckResult(
        slippage=result,
        orderbook_age_ms=age_ms,
        max_age_ms=max_age_ms,
    )


# ============================================================
# BUY
# ============================================================


def calculate_cached_buy_slippage(
    exchange: str,
    symbol: str,
    quantity: float,
    max_age_ms: int,
) -> SlippageCheckResult:

    return calculate_cached_slippage(
        exchange=exchange,
        symbol=symbol,
        side=Side.BUY,
        quantity=quantity,
        max_age_ms=max_age_ms,
    )


# ============================================================
# SELL
# ============================================================


def calculate_cached_sell_slippage(
    exchange: str,
    symbol: str,
    quantity: float,
    max_age_ms: int,
) -> SlippageCheckResult:

    return calculate_cached_slippage(
        exchange=exchange,
        symbol=symbol,
        side=Side.SELL,
        quantity=quantity,
        max_age_ms=max_age_ms,
    )