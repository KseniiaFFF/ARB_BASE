from dataclasses import dataclass

from price_feeds.orderbook_models import OrderBook
from profitability.slippage import (
    Side,
    SlippageResult,
    calculate_slippage,
)
from profitability.fees import get_fee


# ============================================================
# RESULT
# ============================================================

@dataclass(slots=True, frozen=True)
class ArbitrageProfitability:

    # --------------------------------------------------------
    # Basic
    # --------------------------------------------------------

    buy_exchange: str
    buy_symbol: str

    sell_exchange: str
    sell_symbol: str

    # --------------------------------------------------------
    # Quantities
    # --------------------------------------------------------

    buy_quantity: float
    sell_quantity: float

    # --------------------------------------------------------
    # Best prices
    # --------------------------------------------------------

    buy_best_price: float
    sell_best_price: float

    # --------------------------------------------------------
    # Actual execution prices
    # --------------------------------------------------------

    buy_entry_price: float
    sell_entry_price: float

    buy_exit_price: float
    sell_exit_price: float

    # --------------------------------------------------------
    # Top-of-book spread
    # --------------------------------------------------------

    spread_percent: float

    # --------------------------------------------------------
    # Execution spread
    # --------------------------------------------------------

    execution_spread_percent: float

    # --------------------------------------------------------
    # Slippage
    # --------------------------------------------------------

    buy_entry_slippage_percent: float
    sell_entry_slippage_percent: float

    buy_exit_slippage_percent: float
    sell_exit_slippage_percent: float

    total_slippage_percent: float

    # --------------------------------------------------------
    # Fees
    # --------------------------------------------------------

    buy_fee_percent: float
    sell_fee_percent: float

    total_fee_percent: float

    # --------------------------------------------------------
    # Final result
    # --------------------------------------------------------

    net_profit_percent: float

    # --------------------------------------------------------
    # Detailed slippage results
    # --------------------------------------------------------

    buy_entry: SlippageResult
    sell_entry: SlippageResult

    buy_exit: SlippageResult
    sell_exit: SlippageResult


# ============================================================
# MAIN CALCULATION
# ============================================================

def calculate_arbitrage_profitability(
    buy_orderbook: OrderBook,
    sell_orderbook: OrderBook,
    buy_quantity: float,
    sell_quantity: float,
) -> ArbitrageProfitability:
    """
    Расчёт прибыльности арбитражной сделки.

    BUY exchange:
        entry -> BUY
        exit  -> SELL

    SELL exchange:
        entry -> SELL
        exit  -> BUY

    Основной результат рассчитывается
    через реальные средние цены исполнения
    указанного объёма.

    Комиссии:
        2 операции на BUY exchange
        2 операции на SELL exchange

    Slippage:
        учитывается через фактические
        средние цены исполнения стакана.

    ВАЖНО:
        exit slippage рассчитывается по текущему
        стакану и является оценкой текущей
        стоимости закрытия, а не гарантированным
        будущим исполнением.
    """

    # ========================================================
    # VALIDATION
    # ========================================================

    if buy_quantity <= 0:

        raise ValueError(
            "buy_quantity должна быть > 0"
        )

    if sell_quantity <= 0:

        raise ValueError(
            "sell_quantity должна быть > 0"
        )

    # Для симметричного арбитража количества
    # должны совпадать.

    if abs(
        buy_quantity - sell_quantity
    ) > 1e-12:

        raise ValueError(
            "buy_quantity и sell_quantity "
            "должны совпадать"
        )

    # ========================================================
    # BEST PRICES
    # ========================================================

    buy_best_price = _get_best_ask(
        buy_orderbook
    )

    sell_best_price = _get_best_bid(
        sell_orderbook
    )

    # ========================================================
    # TOP-OF-BOOK SPREAD
    # ========================================================

    spread_percent = (
        sell_best_price
        / buy_best_price
        - 1
    ) * 100

    # ========================================================
    # ENTRY EXECUTION
    # ========================================================

    # --------------------------------------------------------
    # BUY exchange
    #
    # Покупаем BTC по ASK.
    # --------------------------------------------------------

    buy_entry = calculate_slippage(
        orderbook=buy_orderbook,
        side=Side.BUY,
        quantity=buy_quantity,
    )

    # --------------------------------------------------------
    # SELL exchange
    #
    # Продаём BTC по BID.
    # --------------------------------------------------------

    sell_entry = calculate_slippage(
        orderbook=sell_orderbook,
        side=Side.SELL,
        quantity=sell_quantity,
    )

    # ========================================================
    # EXIT EXECUTION
    # ========================================================

    # --------------------------------------------------------
    # BUY exchange
    #
    # Закрытие BUY -> SELL.
    # --------------------------------------------------------

    buy_exit = calculate_slippage(
        orderbook=buy_orderbook,
        side=Side.SELL,
        quantity=buy_quantity,
    )

    # --------------------------------------------------------
    # SELL exchange
    #
    # Закрытие SELL -> BUY.
    # --------------------------------------------------------

    sell_exit = calculate_slippage(
        orderbook=sell_orderbook,
        side=Side.BUY,
        quantity=sell_quantity,
    )

    # ========================================================
    # COMPLETE EXECUTION CHECK
    # ========================================================

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

    # ========================================================
    # ACTUAL EXECUTION PRICES
    # ========================================================

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

    # ========================================================
    # EXECUTION SPREAD
    # ========================================================

    # Реальный входной spread для указанного
    # объёма после прохождения стакана.

    execution_spread_percent = (
        sell_entry_price
        / buy_entry_price
        - 1
    ) * 100

    # ========================================================
    # SLIPPAGE
    # ========================================================

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

    # ========================================================
    # FEES
    # ========================================================

    buy_fee_percent = get_fee(
        buy_orderbook.exchange,
        buy_orderbook.symbol,
    )

    sell_fee_percent = get_fee(
        sell_orderbook.exchange,
        sell_orderbook.symbol,
    )

    # 2 операции на каждой бирже:
    #
    # BUY exchange:
    #     entry + exit
    #
    # SELL exchange:
    #     entry + exit

    total_fee_percent = (
        buy_fee_percent * 2
        + sell_fee_percent * 2
    )

    # ========================================================
    # EXIT EFFECT
    # ========================================================

    # --------------------------------------------------------
    # Вход:
    #
    # BUY exchange:
    #     покупка по buy_entry_price
    #
    # SELL exchange:
    #     продажа по sell_entry_price
    #
    # Закрытие:
    #
    # BUY exchange:
    #     продажа по buy_exit_price
    #
    # SELL exchange:
    #     покупка по sell_exit_price
    #
    # --------------------------------------------------------
    #
    # Для каждой ноги рассчитываем её относительный
    # результат.
    # --------------------------------------------------------

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

    # ========================================================
    # GROSS ARBITRAGE RESULT
    # ========================================================

    gross_profit_percent = (
        buy_leg_return
        + sell_leg_return
    )

    # ========================================================
    # NET PROFIT
    # ========================================================

    net_profit_percent = (
        gross_profit_percent
        - total_fee_percent
    )

    # ========================================================
    # RESULT
    # ========================================================

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


# ============================================================
# BEST ASK
# ============================================================

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


# ============================================================
# BEST BID
# ============================================================

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
