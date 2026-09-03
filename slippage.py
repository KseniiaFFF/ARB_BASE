from dataclasses import dataclass
from enum import Enum

from price_feeds.orderbook_models import OrderBook


# ============================================================
# SIDE
# ============================================================

class Side(str, Enum):

    BUY = "buy"
    SELL = "sell"


# ============================================================
# EXCEPTION
# ============================================================

class SlippageError(Exception):
    pass


# ============================================================
# RESULT
# ============================================================

@dataclass(slots=True)
class SlippageResult:

    exchange: str
    symbol: str

    side: Side

    requested_quantity: float
    executed_quantity: float

    requested_notional: float
    executed_notional: float

    best_price: float
    average_price: float

    slippage_abs: float
    slippage_percent: float

    levels_used: int

    complete: bool


# ============================================================
# CALCULATE SLIPPAGE
# ============================================================

def calculate_slippage(
    orderbook: OrderBook,
    side: Side,
    quantity: float,
) -> SlippageResult:

    if quantity <= 0:

        raise ValueError(
            "quantity должна быть > 0"
        )

    # --------------------------------------------------------
    # Выбираем сторону стакана.
    #
    # BUY  -> asks, начиная с самого дешёвого ASK
    # SELL -> bids, начиная с самого дорогого BID
    # --------------------------------------------------------

    if side == Side.BUY:

        levels = orderbook.asks

    elif side == Side.SELL:

        levels = orderbook.bids

    else:

        raise ValueError(
            f"Неизвестная сторона: {side}"
        )

    if not levels:

        raise SlippageError(
            f"Стакан {orderbook.exchange} "
            f"{orderbook.symbol} пуст"
        )

    # --------------------------------------------------------
    # Первый уровень = best price.
    # --------------------------------------------------------

    best_price = levels[0][0]

    if best_price <= 0:

        raise SlippageError(
            f"Некорректная best price: "
            f"{best_price}"
        )

    remaining_quantity = quantity

    executed_quantity = 0.0
    executed_notional = 0.0

    levels_used = 0

    # --------------------------------------------------------
    # Симулируем рыночное исполнение.
    # --------------------------------------------------------

    for price, available_quantity in levels:

        if remaining_quantity <= 0:
            break

        if price <= 0:
            continue

        if available_quantity <= 0:
            continue

        execution_quantity = min(
            remaining_quantity,
            available_quantity,
        )

        executed_quantity += (
            execution_quantity
        )

        executed_notional += (
            price * execution_quantity
        )

        remaining_quantity -= (
            execution_quantity
        )

        levels_used += 1

    # --------------------------------------------------------
    # Ничего не исполнилось.
    # --------------------------------------------------------

    if executed_quantity <= 0:

        raise SlippageError(
            f"Не удалось исполнить заявку "
            f"{orderbook.exchange} "
            f"{orderbook.symbol}"
        )

    # --------------------------------------------------------
    # Средняя цена фактического исполнения.
    # --------------------------------------------------------

    average_price = (
        executed_notional
        / executed_quantity
    )

    # --------------------------------------------------------
    # Slippage.
    #
    # BUY:
    # средняя цена > best ask
    #
    # SELL:
    # средняя цена < best bid
    # --------------------------------------------------------

    if side == Side.BUY:

        slippage_abs = (
            average_price
            - best_price
        )

    else:

        slippage_abs = (
            best_price
            - average_price
        )

    slippage_percent = (
        slippage_abs
        / best_price
        * 100
    )

    # --------------------------------------------------------
    # Полное исполнение.
    #
    # Небольшой epsilon нужен из-за float.
    # --------------------------------------------------------

    complete = (
        executed_quantity
        >= quantity * (1 - 1e-12)
    )

    # --------------------------------------------------------
    # Notional заявки.
    #
    # Это номинал по best price.
    # --------------------------------------------------------

    requested_notional = (
        quantity * best_price
    )

    return SlippageResult(

        exchange=orderbook.exchange,
        symbol=orderbook.symbol,

        side=side,

        requested_quantity=quantity,
        executed_quantity=executed_quantity,

        requested_notional=requested_notional,
        executed_notional=executed_notional,

        best_price=best_price,
        average_price=average_price,

        slippage_abs=slippage_abs,
        slippage_percent=slippage_percent,

        levels_used=levels_used,

        complete=complete,
    )


# ============================================================
# BUY
# ============================================================

def calculate_buy_slippage(
    orderbook: OrderBook,
    quantity: float,
) -> SlippageResult:

    return calculate_slippage(
        orderbook=orderbook,
        side=Side.BUY,
        quantity=quantity,
    )


# ============================================================
# SELL
# ============================================================

def calculate_sell_slippage(
    orderbook: OrderBook,
    quantity: float,
) -> SlippageResult:

    return calculate_slippage(
        orderbook=orderbook,
        side=Side.SELL,
        quantity=quantity,
    )


# ============================================================
# REQUIRE COMPLETE EXECUTION
# ============================================================

def calculate_slippage_complete(
    orderbook: OrderBook,
    side: Side,
    quantity: float,
) -> SlippageResult:

    result = calculate_slippage(
        orderbook=orderbook,
        side=side,
        quantity=quantity,
    )

    if not result.complete:

        raise SlippageError(
            f"Недостаточно ликвидности: "
            f"{orderbook.exchange} "
            f"{orderbook.symbol} "
            f"side={side.value} "
            f"requested={quantity} "
            f"executed={result.executed_quantity}"
        )

    return result