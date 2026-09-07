from dataclasses import dataclass
from enum import Enum

from price_feeds.orderbook_models import OrderBook


class Side(str, Enum):

    BUY = "buy"
    SELL = "sell"


class SlippageError(Exception):
    pass



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



def _calculate_level_notional(
    price: float,
    quantity: float,
    contract_size: float,
) -> float:
    
    if price <= 0:
        raise ValueError(
            f"price должен быть > 0: {price}"
        )

    if quantity <= 0:
        raise ValueError(
            f"quantity должен быть > 0: {quantity}"
        )

    if contract_size <= 0:
        raise ValueError(
            f"contract_size должен быть > 0: "
            f"{contract_size}"
        )

    return (
        price
        * quantity
        * contract_size
    )


def calculate_slippage(
    orderbook: OrderBook,
    side: Side,
    quantity: float,
    contract_size: float = 1.0,
) -> SlippageResult:
    
    if quantity <= 0:

        raise ValueError(
            "quantity должна быть > 0"
        )

    if contract_size <= 0:

        raise ValueError(
            "contract_size должна быть > 0"
        )

    if not isinstance(side, Side):

        raise ValueError(
            f"Неизвестная сторона: {side}"
        )

    if side == Side.BUY:

        levels = orderbook.asks

    else:

        levels = orderbook.bids

    if not levels:

        raise SlippageError(
            f"Стакан {orderbook.exchange} "
            f"{orderbook.symbol} пуст"
        )

    try:

        best_price = float(
            levels[0][0]
        )

    except (
        TypeError,
        ValueError,
        IndexError,
    ) as exc:

        raise SlippageError(
            f"Некорректный первый уровень стакана "
            f"{orderbook.exchange} "
            f"{orderbook.symbol}"
        ) from exc

    if best_price <= 0:

        raise SlippageError(
            f"Некорректная best price: "
            f"{best_price}"
        )
    
    remaining_quantity = float(
        quantity
    )

    executed_quantity = 0.0

    executed_notional = 0.0

    levels_used = 0

    for level in levels:

        if remaining_quantity <= 0:
            break


        if len(level) < 2:
            continue

        try:

            price = float(
                level[0]
            )

            available_quantity = float(
                level[1]
            )

        except (
            TypeError,
            ValueError,
        ):

            continue


        if price <= 0:
            continue

        if available_quantity <= 0:
            continue


        execution_quantity = min(
            remaining_quantity,
            available_quantity,
        )

        if execution_quantity <= 0:
            continue


        executed_quantity += (
            execution_quantity
        )


        executed_notional += (
            _calculate_level_notional(
                price=price,
                quantity=execution_quantity,
                contract_size=contract_size,
            )
        )

        remaining_quantity -= (
            execution_quantity
        )

        levels_used += 1


    if executed_quantity <= 0:

        raise SlippageError(
            f"Не удалось исполнить заявку "
            f"{orderbook.exchange} "
            f"{orderbook.symbol} "
            f"side={side.value} "
            f"quantity={quantity}"
        )


    executed_base_quantity = (
        executed_quantity
        * contract_size
    )

    if executed_base_quantity <= 0:

        raise SlippageError(
            f"Некорректный executed base quantity: "
            f"{executed_base_quantity}"
        )

    average_price = (
        executed_notional
        / executed_base_quantity
    )


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


    if slippage_abs < 0 and abs(slippage_abs) < 1e-12:

        slippage_abs = 0.0

    slippage_percent = (
        slippage_abs
        / best_price
        * 100.0
    )


    complete = (
        executed_quantity
        >= quantity * (1.0 - 1e-12)
    )


    requested_notional = (
        _calculate_level_notional(
            price=best_price,
            quantity=quantity,
            contract_size=contract_size,
        )
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


def calculate_buy_slippage(
    orderbook: OrderBook,
    quantity: float,
    contract_size: float = 1.0,
) -> SlippageResult:

    return calculate_slippage(
        orderbook=orderbook,
        side=Side.BUY,
        quantity=quantity,
        contract_size=contract_size,
    )



def calculate_sell_slippage(
    orderbook: OrderBook,
    quantity: float,
    contract_size: float = 1.0,
) -> SlippageResult:

    return calculate_slippage(
        orderbook=orderbook,
        side=Side.SELL,
        quantity=quantity,
        contract_size=contract_size,
    )



def calculate_slippage_complete(
    orderbook: OrderBook,
    side: Side,
    quantity: float,
    contract_size: float = 1.0,
) -> SlippageResult:
    
    result = calculate_slippage(
        orderbook=orderbook,
        side=side,
        quantity=quantity,
        contract_size=contract_size,
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