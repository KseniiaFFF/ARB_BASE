from dataclasses import dataclass

from price_feeds.orderbook_models import OrderBook
from profitability.slippage import (
    Side,
    SlippageResult,
    calculate_slippage,
)
from profitability.fees import get_fee


@dataclass(slots=True, frozen=True)
class ArbitrageProfitability:


    buy_exchange: str
    buy_symbol: str

    sell_exchange: str
    sell_symbol: str


    buy_quantity: float
    sell_quantity: float


    buy_best_price: float
    sell_best_price: float


    buy_entry_price: float
    sell_entry_price: float

    buy_exit_price: float
    sell_exit_price: float

    spread_percent: float
    execution_spread_percent: float

    buy_entry_slippage_percent: float
    sell_entry_slippage_percent: float

    buy_exit_slippage_percent: float
    sell_exit_slippage_percent: float

    total_slippage_percent: float

    buy_fee_percent: float
    sell_fee_percent: float

    total_fee_percent: float

    net_profit_percent: float

    buy_entry: SlippageResult
    sell_entry: SlippageResult

    buy_exit: SlippageResult
    sell_exit: SlippageResult

def calculate_arbitrage_profitability(
    buy_orderbook: OrderBook,
    sell_orderbook: OrderBook,
    buy_quantity: float,
    sell_quantity: float,
) -> ArbitrageProfitability:
    
    if buy_quantity <= 0:

        raise ValueError(
            "buy_quantity должна быть > 0"
        )

    if sell_quantity <= 0:

        raise ValueError(
            "sell_quantity должна быть > 0"
        )

    if abs(
        buy_quantity - sell_quantity
    ) > 1e-12:

        raise ValueError(
            "buy_quantity и sell_quantity "
            "должны совпадать"
        )

    buy_best_price = _get_best_ask(
        buy_orderbook
    )

    sell_best_price = _get_best_bid(
        sell_orderbook
    )

    spread_percent = (
        sell_best_price
        / buy_best_price
        - 1
    ) * 100

    buy_entry = calculate_slippage(
        orderbook=buy_orderbook,
        side=Side.BUY,
        quantity=buy_quantity,
    )

    sell_entry = calculate_slippage(
        orderbook=sell_orderbook,
        side=Side.SELL,
        quantity=sell_quantity,
    )

    buy_exit = calculate_slippage(
        orderbook=buy_orderbook,
        side=Side.SELL,
        quantity=buy_quantity,
    )

    sell_exit = calculate_slippage(
        orderbook=sell_orderbook,
        side=Side.BUY,
        quantity=sell_quantity,
    )

    if not buy_entry.complete:

        raise ValueError(
            f"Недостаточно ликвидности "
            f"для BUY entry: "
            f"{buy_orderbook.exchange} "
            f"{buy_orderbook.symbol} "
            f"requested={buy_quantity} "
            f"executed={buy_entry.executed_quantity}"
        )

    if not sell_entry.complete:

        raise ValueError(
            f"Недостаточно ликвидности "
            f"для SELL entry: "
            f"{sell_orderbook.exchange} "
            f"{sell_orderbook.symbol} "
            f"requested={sell_quantity} "
            f"executed={sell_entry.executed_quantity}"
        )

    if not buy_exit.complete:

        raise ValueError(
            f"Недостаточно ликвидности "
            f"для BUY exchange exit: "
            f"{buy_orderbook.exchange} "
            f"{buy_orderbook.symbol} "
            f"requested={buy_quantity} "
            f"executed={buy_exit.executed_quantity}"
        )

    if not sell_exit.complete:

        raise ValueError(
            f"Недостаточно ликвидности "
            f"для SELL exchange exit: "
            f"{sell_orderbook.exchange} "
            f"{sell_orderbook.symbol} "
            f"requested={sell_quantity} "
            f"executed={sell_exit.executed_quantity}"
        )

    buy_entry_price = (
        buy_entry.average_price
    )

    sell_entry_price = (
        sell_entry.average_price
    )

    buy_exit_price = (
        buy_exit.average_price
    )

    sell_exit_price = (
        sell_exit.average_price
    )

    execution_spread_percent = (
        sell_entry_price
        / buy_entry_price
        - 1
    ) * 100

    buy_entry_slippage_percent = (
        buy_entry.slippage_percent
    )

    sell_entry_slippage_percent = (
        sell_entry.slippage_percent
    )

    buy_exit_slippage_percent = (
        buy_exit.slippage_percent
    )

    sell_exit_slippage_percent = (
        sell_exit.slippage_percent
    )

    total_slippage_percent = (

        buy_entry_slippage_percent
        + sell_entry_slippage_percent
        + buy_exit_slippage_percent
        + sell_exit_slippage_percent
    )

    buy_fee_percent = get_fee(
        buy_orderbook.exchange,
        buy_orderbook.symbol,
    )

    sell_fee_percent = get_fee(
        sell_orderbook.exchange,
        sell_orderbook.symbol,
    )

    total_fee_percent = (
        buy_fee_percent * 2
        + sell_fee_percent * 2
    )

    buy_leg_return = (
        buy_exit_price
        / buy_entry_price
        - 1
    ) * 100

    sell_leg_return = (
        sell_entry_price
        / sell_exit_price
        - 1
    ) * 100

    gross_profit_percent = (
        buy_leg_return
        + sell_leg_return
    )

    net_profit_percent = (
        gross_profit_percent
        - total_fee_percent
    )

    return ArbitrageProfitability(

        buy_exchange=(
            buy_orderbook.exchange
        ),

        buy_symbol=(
            buy_orderbook.symbol
        ),

        sell_exchange=(
            sell_orderbook.exchange
        ),

        sell_symbol=(
            sell_orderbook.symbol
        ),

        buy_quantity=buy_quantity,

        sell_quantity=sell_quantity,

        buy_best_price=(
            buy_best_price
        ),

        sell_best_price=(
            sell_best_price
        ),

        buy_entry_price=(
            buy_entry_price
        ),

        sell_entry_price=(
            sell_entry_price
        ),

        buy_exit_price=(
            buy_exit_price
        ),

        sell_exit_price=(
            sell_exit_price
        ),

        spread_percent=(
            spread_percent
        ),

        execution_spread_percent=(
            execution_spread_percent
        ),

        buy_entry_slippage_percent=(
            buy_entry_slippage_percent
        ),

        sell_entry_slippage_percent=(
            sell_entry_slippage_percent
        ),

        buy_exit_slippage_percent=(
            buy_exit_slippage_percent
        ),

        sell_exit_slippage_percent=(
            sell_exit_slippage_percent
        ),

        total_slippage_percent=(
            total_slippage_percent
        ),

        buy_fee_percent=(
            buy_fee_percent
        ),

        sell_fee_percent=(
            sell_fee_percent
        ),

        total_fee_percent=(
            total_fee_percent
        ),

        net_profit_percent=(
            net_profit_percent
        ),

        buy_entry=buy_entry,

        sell_entry=sell_entry,

        buy_exit=buy_exit,

        sell_exit=sell_exit,
    )

def _get_best_ask(
    orderbook: OrderBook,
) -> float:

    if not orderbook.asks:

        raise ValueError(
            f"ASK стакан пуст: "
            f"{orderbook.exchange} "
            f"{orderbook.symbol}"
        )

    prices = [
        price
        for price, quantity
        in orderbook.asks
        if quantity > 0
    ]

    if not prices:

        raise ValueError(
            f"ASK стакан не содержит "
            f"положительных объёмов: "
            f"{orderbook.exchange} "
            f"{orderbook.symbol}"
        )

    return min(prices)

def _get_best_bid(
    orderbook: OrderBook,
) -> float:

    if not orderbook.bids:

        raise ValueError(
            f"BID стакан пуст: "
            f"{orderbook.exchange} "
            f"{orderbook.symbol}"
        )

    prices = [
        price
        for price, quantity
        in orderbook.bids
        if quantity > 0
    ]

    if not prices:

        raise ValueError(
            f"BID стакан не содержит "
            f"положительных объёмов: "
            f"{orderbook.exchange} "
            f"{orderbook.symbol}"
        )

    return max(prices)
