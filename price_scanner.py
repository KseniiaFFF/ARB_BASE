# import asyncio
# import logging
# import time

# from config import (
#     MIN_PERCENT,
#     PRICE_MAX_AGE_MS,
#     MAX_TIMESTAMP_DIFF_MS,
# )

# from market_universe import build_universe
# from price_feeds.models_price import Price

# from price_feeds.binance_ws import run_binance_ws
# from price_feeds.bitget_ws import run_bitget_ws
# from price_feeds.okx_ws import run_okx_ws

# from profitability.fees import (
#     get_fee,
#     refresh_fees,
#     is_fee_refresh_needed,
# )

# from contract_validator import get_valid_contracts

# from profitability.position_size import (
#     get_position_notional,
#     calculate_position,
# )

# from price_feeds.orderbook_cache import (
#     get_orderbook,
#     get_orderbook_age_ms,
# )

# from profitability.slippage import (
#     Side,
#     calculate_slippage_complete,
#     SlippageError,
# )


# logger = logging.getLogger(__name__)

# price_cache: dict[str, dict[str, Price]] = {}


# def get_exchange_symbols(
#     universe: dict[str, list],
# ) -> dict[str, list[str]]:

#     symbols = {
#         "binance": set(),
#         "bitget": set(),
#         "okx": set(),
#     }

#     for markets in universe.values():

#         for market in markets:

#             if not market.active:
#                 logger.info("if not market.active")
#                 continue

#             if market.exchange not in symbols:
#                 logger.info("market.exchange not in symbols")
#                 continue

#             symbols[market.exchange].add(
#                 market.symbol
#             )

#     return {
#         exchange: sorted(exchange_symbols)
#         for exchange, exchange_symbols in symbols.items()
#     }


# def get_fee_symbols(universe):
#     """
#     Выбирает по одному активному символу для каждой биржи.
#     Этого достаточно для получения account-level taker fee.
#     """

#     symbols = {}

#     for markets in universe.values():
#         for market in markets:
#             if not market.active:
#                 logger.info("not market.active")
#                 continue

#             if market.exchange in symbols:
#                 continue

#             symbols[market.exchange] = market.symbol

#     required_exchanges = {"binance", "bitget", "okx"}

#     missing = required_exchanges - symbols.keys()

#     if missing:
#         raise RuntimeError(
#             f"Не найдены символы для получения комиссии: {sorted(missing)}"
#         )

#     return {
#         exchange: symbols[exchange]
#         for exchange in sorted(required_exchanges)
#     }


# def get_price_age_ms(price: Price) -> int | None:

#     if price.timestamp <= 0:
#         return None

#     now_ms = int(time.time() * 1000)

#     age = now_ms - price.received_at

#     if age < 0:
#         return None

#     return age


# def is_price_fresh(price: Price) -> bool:

#     age = get_price_age_ms(price)

#     if age is None:
#         return False

#     return age <= PRICE_MAX_AGE_MS


# def get_timestamp_difference_ms(
#     price_a: Price,
#     price_b: Price,
# ) -> int | None:

#     if (
#         price_a.timestamp <= 0
#         or price_b.timestamp <= 0
#     ):
#         return None

#     return abs(
#         price_a.received_at
#         - price_b.received_at
#     )


# def get_processing_age_ms(
#     price: Price,
# ) -> float | None:

#     if price.received_at_ns <= 0:
#         return None

#     now_ns = time.monotonic_ns()

#     age_ns = (
#         now_ns
#         - price.received_at_ns
#     )

#     if age_ns < 0:
#         return None

#     return age_ns / 1_000_000


# def get_execution_price(
#     exchange: str,
#     symbol: str,
#     side: Side,
#     quantity: float,
# ) -> dict | None:

#     orderbook = get_orderbook(
#         exchange,
#         symbol,
#     )

#     if orderbook is None:
#         logger.debug(
#             "Orderbook skip %s %s: no orderbook",
#             exchange,
#             symbol,
#         )
#         return None

#     orderbook_age = get_orderbook_age_ms(
#         orderbook
#     )

#     if orderbook_age is None:
#         return None

#     if orderbook_age > PRICE_MAX_AGE_MS:
#         logger.debug(
#             "Orderbook skip %s %s: age=%d ms",
#             exchange,
#             symbol,
#             orderbook_age,
#         )
#         return None

#     try:

#         result = calculate_slippage_complete(
#             orderbook=orderbook,
#             side=side,
#             quantity=quantity,
#         )

#     except SlippageError as e:
#         logger.debug(
#             "Slippage skip %s %s %s: %s",
#             exchange,
#             symbol,
#             side.value,
#             e,
#         )
#         return None

#     return {
#         "best_price": result.best_price,
#         "average_price": result.average_price,

#         "slippage_abs": result.slippage_abs,
#         "slippage_percent": result.slippage_percent,

#         "requested_quantity": result.requested_quantity,
#         "executed_quantity": result.executed_quantity,

#         "requested_notional": result.requested_notional,
#         "executed_notional": result.executed_notional,

#         "levels_used": result.levels_used,

#         "orderbook_age_ms": orderbook_age,
#         "update_id": orderbook.update_id,
#     }


# def find_arbitrage_opportunities(
#     universe: dict[str, list],
#     contracts: dict[str, dict],
# ) -> list[dict]:

#     opportunities = []

#     for asset, markets in universe.items():

#         prices = price_cache.get(asset)

#         if not prices:
#             continue

#         if len(prices) < 2:
#             continue

#         exchanges = list(prices.keys())

#         for buy_exchange in exchanges:

#             buy_price = prices[buy_exchange]

#             buy_contract = (
#                 contracts
#                 .get(buy_exchange, {})
#                 .get(buy_price.symbol)
#             )

#             if buy_contract is None:
#                 logger.info("buy_contract is None")
#                 continue

#             if not is_price_fresh(buy_price):
#                 continue

#             buy = buy_price.ask

#             if buy <= 0:
#                 logger.info("buy <= 0")
#                 continue

#             for sell_exchange in exchanges:

#                 if buy_exchange == sell_exchange:
#                     continue

#                 sell_price = prices[sell_exchange]

#                 sell_contract = (
#                     contracts
#                     .get(sell_exchange, {})
#                     .get(sell_price.symbol)
#                 )

#                 if sell_contract is None:
#                     logger.info("sell_contract is None")
#                     continue

#                 if not is_price_fresh(sell_price):
#                     continue

#                 timestamp_diff = (
#                     get_timestamp_difference_ms(
#                         buy_price,
#                         sell_price,
#                     )
#                 )

#                 if timestamp_diff is None:
#                     logger.info("timestamp_diff is None")
#                     continue

#                 if timestamp_diff > MAX_TIMESTAMP_DIFF_MS:
#                     continue

#                 sell = sell_price.bid

#                 if sell <= 0:
#                     logger.info("sell <= 0")
#                     continue

#                 # ==========================================================
#                 # 1. RAW SPREAD
#                 # ==========================================================

#                 spread_percent = (
#                     (sell / buy) - 1
#                 ) * 100
#                 if spread_percent >= 1.0:
#                     print("spread_percent: ", spread_percent)

#                 # ==========================================================
#                 # 2. FEES
#                 # ==========================================================

#                 buy_fee_percent = get_fee(
#                     buy_exchange
#                 )

#                 sell_fee_percent = get_fee(
#                     sell_exchange
#                 )

#                 total_fee_percent = (
#                     buy_fee_percent * 2
#                     + sell_fee_percent * 2
#                 )

#                 # ==========================================================
#                 # 3. PRELIMINARY NET
#                 #
#                 # Здесь стакан ещё НЕ используется.
#                 # Если обычного спреда недостаточно даже после комиссий,
#                 # рассчитывать slippage бессмысленно.
#                 # ==========================================================

#                 preliminary_net_profit = (
#                     spread_percent
#                     - total_fee_percent
#                 )

                

#                 if preliminary_net_profit < MIN_PERCENT:
#                     continue
                

#                 # ==========================================================
#                 # 4. POSITION SIZE
#                 # ==========================================================

#                 position_notional = (
#                     get_position_notional()
#                 )
                

#                 buy_position = calculate_position(
#                     notional_usdt=position_notional,
#                     price=buy,
#                     contract=buy_contract,
#                 )

#                 sell_position = calculate_position(
#                     notional_usdt=position_notional,
#                     price=sell,
#                     contract=sell_contract,
#                 )

                

#                 if not buy_position["possible"]:
#                     logger.info("not buy_position -possible-")
#                     continue

#                 if not sell_position["possible"]:
#                     logger.info("not sell_position -possible-")
#                     continue

#                 # ==========================================================
#                 # 5. REAL BUY EXECUTION THROUGH ORDER BOOK
#                 # ==========================================================

#                 buy_execution = get_execution_price(
#                     exchange=buy_exchange,
#                     symbol=buy_price.symbol,
#                     side=Side.BUY,
#                     quantity=buy_position["quantity"],
#                 )

#                 if buy_execution is None:
#                     continue

#                 # ==========================================================
#                 # 6. REAL SELL EXECUTION THROUGH ORDER BOOK
#                 # ==========================================================

#                 sell_execution = get_execution_price(
#                     exchange=sell_exchange,
#                     symbol=sell_price.symbol,
#                     side=Side.SELL,
#                     quantity=sell_position["quantity"],
#                 )

#                 if sell_execution is None:
#                     continue

#                 # ==========================================================
#                 # 7. EXECUTION PRICES
#                 # ==========================================================

#                 buy_execution_price = (
#                     buy_execution["average_price"]
#                 )

#                 sell_execution_price = (
#                     sell_execution["average_price"]
#                 )

#                 if buy_execution_price <= 0:
#                     logger.info("buy_execution_price <= 0")
#                     continue

#                 if sell_execution_price <= 0:
#                     logger.info("sell_execution_price <= 0")
#                     continue

#                 # ==========================================================
#                 # 8. REAL SPREAD AFTER SLIPPAGE
#                 # ==========================================================

#                 execution_spread_percent = (
#                     (
#                         sell_execution_price
#                         / buy_execution_price
#                     ) - 1
#                 ) * 100

#                 logger.info("execution_spread_percent-OK")

#                 if execution_spread_percent >= 0.5:
#                     print(f"execution_spread_percent: {execution_spread_percent}")

#                 # ==========================================================
#                 # 9. FINAL NET PROFIT
#                 # ==========================================================

#                 net_profit_percent = (
#                     execution_spread_percent
#                     - total_fee_percent
#                 )

#                 # Final filter.
#                 # Теперь учитывается уже реальная цена исполнения.
#                 if net_profit_percent < MIN_PERCENT:
#                     logger.info("net_profit_percent < MIN_PERCENT")
#                     continue

#                 # ==========================================================
#                 # 10. SAVE OPPORTUNITY
#                 # ==========================================================

#                 opportunities.append(
#                     {
#                         "asset": asset,

#                         "buy_exchange": buy_exchange,
#                         "buy_symbol": buy_price.symbol,
#                         "buy_price": buy,

#                         "sell_exchange": sell_exchange,
#                         "sell_symbol": sell_price.symbol,
#                         "sell_price": sell,

#                         "spread_percent": spread_percent,

#                         "position_notional": position_notional,

#                         "buy_quantity": buy_position["quantity"],
#                         "buy_actual_notional": (
#                             buy_position["actual_notional"]
#                         ),

#                         "sell_quantity": sell_position["quantity"],
#                         "sell_actual_notional": (
#                             sell_position["actual_notional"]
#                         ),

#                         "buy_contract_size": (
#                             buy_contract.contract_size
#                         ),
#                         "buy_contract_size_currency": (
#                             buy_contract.contract_size_currency
#                         ),

#                         "sell_contract_size": (
#                             sell_contract.contract_size
#                         ),
#                         "sell_contract_size_currency": (
#                             sell_contract.contract_size_currency
#                         ),

#                         "buy_fee_percent": buy_fee_percent,
#                         "sell_fee_percent": sell_fee_percent,

#                         "total_fee_percent": total_fee_percent,

#                         "preliminary_net_profit": (
#                             preliminary_net_profit
#                         ),

#                         "net_profit_percent": (
#                             net_profit_percent
#                         ),

#                         "buy_qty": buy_price.ask_qty,
#                         "sell_qty": sell_price.bid_qty,

#                         "buy_timestamp": buy_price.timestamp,
#                         "sell_timestamp": sell_price.timestamp,

#                         "timestamp_diff_ms": timestamp_diff,

#                         "buy_age_ms": (
#                             get_price_age_ms(buy_price)
#                         ),
#                         "sell_age_ms": (
#                             get_price_age_ms(sell_price)
#                         ),

#                         "buy_processing_age_ms": (
#                             get_processing_age_ms(buy_price)
#                         ),
#                         "sell_processing_age_ms": (
#                             get_processing_age_ms(sell_price)
#                         ),

#                         # BUY order book
#                         "buy_best_price": (
#                             buy_execution["best_price"]
#                         ),
#                         "buy_execution_price": (
#                             buy_execution["average_price"]
#                         ),
#                         "buy_slippage_abs": (
#                             buy_execution["slippage_abs"]
#                         ),
#                         "buy_slippage_percent": (
#                             buy_execution["slippage_percent"]
#                         ),
#                         "buy_levels_used": (
#                             buy_execution["levels_used"]
#                         ),
#                         "buy_orderbook_age_ms": (
#                             buy_execution["orderbook_age_ms"]
#                         ),
#                         "buy_orderbook_update_id": (
#                             buy_execution["update_id"]
#                         ),

#                         # SELL order book
#                         "sell_best_price": (
#                             sell_execution["best_price"]
#                         ),
#                         "sell_execution_price": (
#                             sell_execution["average_price"]
#                         ),
#                         "sell_slippage_abs": (
#                             sell_execution["slippage_abs"]
#                         ),
#                         "sell_slippage_percent": (
#                             sell_execution["slippage_percent"]
#                         ),
#                         "sell_levels_used": (
#                             sell_execution["levels_used"]
#                         ),
#                         "sell_orderbook_age_ms": (
#                             sell_execution["orderbook_age_ms"]
#                         ),
#                         "sell_orderbook_update_id": (
#                             sell_execution["update_id"]
#                         ),

#                         "execution_spread_percent": (
#                             execution_spread_percent
#                         ),

#                         "detected_at": int(
#                             time.time() * 1000
#                         ),
#                     }
#                 )

#     return opportunities


# def print_opportunity(
#     opportunity: dict,
# ) -> None:

#     print(
#         "\n"
#         "========================================\n"
#         "ARBITRAGE SIGNAL\n"
#         "========================================"
#     )

#     print(
#         f"{opportunity['asset']} | "
#         f"BUY {opportunity['buy_exchange']} "
#         f"{opportunity['buy_price']:.8f} | "
#         f"SELL {opportunity['sell_exchange']} "
#         f"{opportunity['sell_price']:.8f}"
#     )

#     print(
#         f"Raw spread:          "
#         f"{opportunity['spread_percent']:.4f}%"
#     )

#     print(
#         f"BUY slippage:        "
#         f"{opportunity['buy_slippage_percent']:.6f}%"
#     )

#     print(
#         f"SELL slippage:       "
#         f"{opportunity['sell_slippage_percent']:.6f}%"
#     )

#     print(
#         f"Execution spread:    "
#         f"{opportunity['execution_spread_percent']:.4f}%"
#     )

#     print(
#         f"Total fees:          "
#         f"{opportunity['total_fee_percent']:.4f}%"
#     )

#     print(
#         f"NET PROFIT:          "
#         f"{opportunity['net_profit_percent']:.4f}%"
#     )

#     print(
#         f"Position:            "
#         f"{opportunity['position_notional']:.2f} USDT"
#     )

#     print(
#         f"BUY quantity:        "
#         f"{opportunity['buy_quantity']:.12f}"
#     )

#     print(
#         f"SELL quantity:       "
#         f"{opportunity['sell_quantity']:.12f}"
#     )

#     print(
#         f"Timestamp diff:      "
#         f"{opportunity['timestamp_diff_ms']} ms"
#     )

#     print(
#         f"BUY OB age:          "
#         f"{opportunity['buy_orderbook_age_ms']} ms"
#     )

#     print(
#         f"SELL OB age:         "
#         f"{opportunity['sell_orderbook_age_ms']} ms"
#     )

#     print(
#         "========================================\n"
#     )


# async def monitor(
#     universe: dict[str, list],
#     contracts: dict[str, dict],
#     fee_symbols: dict[str, str],
# ) -> None:

#     logger.info(
#         "Запуск мониторинга цен"
#     )

#     last_signal_time: dict[
#         tuple[str, str, str],
#         int,
#     ] = {}

#     SIGNAL_COOLDOWN_MS = 20_000

#     while True:

#         try:

#             if is_fee_refresh_needed():
#                 await asyncio.to_thread(
#                     refresh_fees,
#                     fee_symbols,
#                 )

#             opportunities = (
#                 find_arbitrage_opportunities(
#                     universe,
#                     contracts,
#                 )
#             )

#             for opportunity in opportunities:

#                 key = (
#                     opportunity["asset"],
#                     opportunity["buy_exchange"],
#                     opportunity["sell_exchange"],
#                 )

#                 now_ms = int(
#                     time.time() * 1000
#                 )

#                 last_time = (
#                     last_signal_time.get(key)
#                 )

#                 if (
#                     last_time is not None
#                     and now_ms - last_time
#                     < SIGNAL_COOLDOWN_MS
#                 ):
#                     logger.info("last_time is not None  and now_ms - last_time < SIGNAL_COOLDOWN_MS")
#                     continue

#                 print_opportunity(
#                     opportunity
#                 )

#                 last_signal_time[key] = now_ms

#             await asyncio.sleep(0.02)

#         except asyncio.CancelledError:
#             raise

#         except Exception:

#             logger.exception(
#                 "Ошибка основного цикла мониторинга"
#             )

#             await asyncio.sleep(1)


# async def main() -> None:

#     logger.info(
#         "Запуск price_scanner.py"
#     )

#     universe = build_universe()

#     logger.info(
#         "Universe сформирован: %d монет",
#         len(universe),
#     )

#     fee_symbols = get_fee_symbols(universe)

#     logger.info(
#         "Получение taker fee: %s",
#         fee_symbols,
#     )

#     refresh_fees(fee_symbols)

#     contracts = get_valid_contracts()

#     exchange_symbols = (
#         get_exchange_symbols(universe)
#     )

#     logger.info(
#         "Символов для WebSocket: "
#         "Binance=%d, Bitget=%d, OKX=%d",
#         len(exchange_symbols["binance"]),
#         len(exchange_symbols["bitget"]),
#         len(exchange_symbols["okx"]),
#     )

#     websocket_tasks = [

#         asyncio.create_task(
#             run_binance_ws(
#                 exchange_symbols["binance"],
#                 price_cache,
#             )
#         ),

#         asyncio.create_task(
#             run_bitget_ws(
#                 exchange_symbols["bitget"],
#                 price_cache,
#             )
#         ),

#         asyncio.create_task(
#             run_okx_ws(
#                 exchange_symbols["okx"],
#                 price_cache,
#             )
#         ),
#     ]

#     monitor_task = asyncio.create_task(
#         monitor(
#             universe,
#             contracts,
#             fee_symbols,
#         )
#     )

#     try:

#         await asyncio.gather(
#             *websocket_tasks,
#             monitor_task,
#         )

#     except asyncio.CancelledError:

#         logger.info(
#             "price_scanner.py остановлен"
#         )

#         for task in websocket_tasks:
#             task.cancel()

#         monitor_task.cancel()

#         raise


# if __name__ == "__main__":

#     try:
#         asyncio.run(main())

#     except KeyboardInterrupt:

#         logger.info(
#             "price_scanner.py остановлен пользователем"
#         )


import asyncio
import logging
import time

from config import (
    MIN_PERCENT,
    PRICE_MAX_AGE_MS,
    MAX_TIMESTAMP_DIFF_MS,
)

from market_universe import build_universe
from price_feeds.models_price import Price
from price_feeds.orderbook_manager import OrderBookManager
from price_feeds.binance_ws import run_binance_ws
from price_feeds.bitget_ws import run_bitget_ws
from price_feeds.okx_ws import run_okx_ws

from profitability.fees import (
    get_fee,
    refresh_fees,
    is_fee_refresh_needed,
)

from contract_validator import get_valid_contracts

from profitability.position_size import (
    get_position_notional,
    calculate_position,
)

from price_feeds.orderbook_cache import (
    get_orderbook,
    get_orderbook_age_ms,
)

from profitability.slippage import (
    Side,
    calculate_slippage_complete,
    SlippageError,
)


logger = logging.getLogger(__name__)

price_cache: dict[str, dict[str, Price]] = {}

# ==========================================================
# DIAGNOSTIC
# Статистика выводится не чаще одного раза в секунду.
# ==========================================================

last_stats_log_ms = 0
orderbook_manager = OrderBookManager()


def log_scanner_stats(stats: dict) -> None:
    global last_stats_log_ms

    now_ms = int(time.time() * 1000)

    if now_ms - last_stats_log_ms < 1000:
        return

    last_stats_log_ms = now_ms

    max_raw_spread = stats["max_raw_spread"]

    if max_raw_spread is None:
        max_raw_spread_text = "None"
    else:
        max_raw_spread_text = f"{max_raw_spread:.6f}%"

    max_preliminary_net = stats["max_preliminary_net"]

    if max_preliminary_net is None:
        max_preliminary_net_text = "None"
    else:
        max_preliminary_net_text = (
            f"{max_preliminary_net:.6f}%"
        )

    # logger.info(
    #     "SCANNER STATS | "
    #     "assets=%d | "
    #     "no_prices=%d | "
    #     "<2_exchanges=%d | "
    #     "buy_contract_none=%d | "
    #     "buy_stale=%d | "
    #     "sell_contract_none=%d | "
    #     "sell_stale=%d | "
    #     "timestamp_none=%d | "
    #     "timestamp_too_large=%d | "
    #     "sell_invalid=%d | "
    #     "preliminary_net=%d | "
    #     "position=%d | "
    #     "buy_OB=%d | "
    #     "sell_OB=%d | "
    #     "execution_price=%d | "
    #     "final_net=%d | "
    #     "opportunities=%d | "
    #     "max_raw_spread=%s | "
    #     "max_preliminary_net=%s",
    #     stats["assets"],
    #     stats["no_prices"],
    #     stats["less_than_2_exchanges"],
    #     stats["buy_contract_none"],
    #     stats["buy_price_stale"],
    #     stats["sell_contract_none"],
    #     stats["sell_price_stale"],
    #     stats["timestamp_none"],
    #     stats["timestamp_too_large"],
    #     stats["sell_invalid"],
    #     stats["preliminary_net"],
    #     stats["position"],
    #     stats["buy_orderbook"],
    #     stats["sell_orderbook"],
    #     stats["execution_price"],
    #     stats["final_net"],
    #     stats["opportunities"],
    #     max_raw_spread_text,
    #     max_preliminary_net_text,
    # )


def get_exchange_symbols(
    universe: dict[str, list],
) -> dict[str, list[str]]:

    symbols = {
        "binance": set(),
        "bitget": set(),
        "okx": set(),
    }

    for markets in universe.values():

        for market in markets:

            if not market.active:
                logger.info("if not market.active")
                continue

            if market.exchange not in symbols:
                logger.info("market.exchange not in symbols")
                continue

            symbols[market.exchange].add(
                market.symbol
            )

    return {
        exchange: sorted(exchange_symbols)
        for exchange, exchange_symbols in symbols.items()
    }


def get_fee_symbols(universe):
    """
    Выбирает по одному активному символу для каждой биржи.
    Этого достаточно для получения account-level taker fee.
    """

    symbols = {}

    for markets in universe.values():

        for market in markets:

            if not market.active:
                logger.info("not market.active")
                continue

            if market.exchange in symbols:
                continue

            symbols[market.exchange] = market.symbol

    required_exchanges = {
        "binance",
        "bitget",
        "okx",
    }

    missing = (
        required_exchanges
        - symbols.keys()
    )

    if missing:
        raise RuntimeError(
            f"Не найдены символы для получения комиссии: "
            f"{sorted(missing)}"
        )

    return {
        exchange: symbols[exchange]
        for exchange in sorted(required_exchanges)
    }


def get_price_age_ms(
    price: Price,
) -> int | None:

    if price.timestamp <= 0:
        return None

    now_ms = int(
        time.time() * 1000
    )

    age = (
        now_ms
        - price.received_at
    )

    if age < 0:
        return None

    return age


def is_price_fresh(
    price: Price,
) -> bool:

    age = get_price_age_ms(price)

    if age is None:
        return False

    return age <= PRICE_MAX_AGE_MS


def get_timestamp_difference_ms(
    price_a: Price,
    price_b: Price,
) -> int | None:

    if (
        price_a.timestamp <= 0
        or price_b.timestamp <= 0
    ):
        return None

    return abs(
        price_a.received_at
        - price_b.received_at
    )


def get_processing_age_ms(
    price: Price,
) -> float | None:

    if price.received_at_ns <= 0:
        return None

    now_ns = time.monotonic_ns()

    age_ns = (
        now_ns
        - price.received_at_ns
    )

    if age_ns < 0:
        return None

    return age_ns / 1_000_000


def get_execution_price(
    exchange: str,
    symbol: str,
    side: Side,
    quantity: float,
) -> dict | None:

    orderbook = get_orderbook(
        exchange,
        symbol,
    )

    if orderbook is None:

        return None

    orderbook_age = (
        get_orderbook_age_ms(
            orderbook
        )
    )

    if orderbook_age is None:

        return None

    if orderbook_age > PRICE_MAX_AGE_MS:

        logger.info(
            "Orderbook skip %s %s: age=%d ms > max=%d ms",
            exchange,
            symbol,
            orderbook_age,
            PRICE_MAX_AGE_MS,
        )

        return None

    try:

        result = calculate_slippage_complete(
            orderbook=orderbook,
            side=side,
            quantity=quantity,
        )

    except SlippageError as e:

        logger.info(
            "Slippage skip %s %s %s: %s",
            exchange,
            symbol,
            side.value,
            e,
        )

        return None

    return {
        "best_price": result.best_price,
        "average_price": result.average_price,

        "slippage_abs": result.slippage_abs,
        "slippage_percent": result.slippage_percent,

        "requested_quantity": (
            result.requested_quantity
        ),
        "executed_quantity": (
            result.executed_quantity
        ),

        "requested_notional": (
            result.requested_notional
        ),
        "executed_notional": (
            result.executed_notional
        ),

        "levels_used": result.levels_used,

        "orderbook_age_ms": orderbook_age,
        "update_id": orderbook.update_id,
    }


def find_arbitrage_opportunities(
    universe: dict[str, list],
    contracts: dict[str, dict],
) -> list[dict]:

    opportunities = []

    # ==========================================================
    # DIAGNOSTIC COUNTERS
    # ==========================================================

    stats = {
        "assets": 0,
        "no_prices": 0,
        "less_than_2_exchanges": 0,

        "buy_contract_none": 0,
        "buy_price_stale": 0,

        "sell_contract_none": 0,
        "sell_price_stale": 0,

        "timestamp_none": 0,
        "timestamp_too_large": 0,

        "sell_invalid": 0,

        "preliminary_net": 0,

        "position": 0,

        "buy_orderbook": 0,
        "sell_orderbook": 0,

        "execution_price": 0,

        "final_net": 0,

        "opportunities": 0,

        "max_raw_spread": None,
        "max_preliminary_net": None,
    }

    # ==========================================================
    # ASSETS
    # ==========================================================

    for asset, markets in universe.items():

        stats["assets"] += 1

        prices = price_cache.get(asset)

        if not prices:

            stats["no_prices"] += 1
            continue

        if len(prices) < 2:

            stats["less_than_2_exchanges"] += 1
            continue

        exchanges = list(
            prices.keys()
        )

        # ======================================================
        # BUY EXCHANGE
        # ======================================================

        for buy_exchange in exchanges:

            buy_price = prices[
                buy_exchange
            ]

            buy_contract = (
                contracts
                .get(buy_exchange, {})
                .get(buy_price.symbol)
            )

            if buy_contract is None:

                stats["buy_contract_none"] += 1

                continue

            if not is_price_fresh(
                buy_price
            ):

                stats["buy_price_stale"] += 1

                continue

            buy = buy_price.ask

            if buy <= 0:

                logger.info(
                    "buy <= 0"
                )

                continue

            # ==================================================
            # SELL EXCHANGE
            # ==================================================

            for sell_exchange in exchanges:

                if (
                    buy_exchange
                    == sell_exchange
                ):
                    continue

                sell_price = prices[
                    sell_exchange
                ]

                sell_contract = (
                    contracts
                    .get(sell_exchange, {})
                    .get(sell_price.symbol)
                )

                if sell_contract is None:

                    stats[
                        "sell_contract_none"
                    ] += 1

                    continue

                if not is_price_fresh(
                    sell_price
                ):

                    stats[
                        "sell_price_stale"
                    ] += 1

                    continue

                # ==============================================
                # TIMESTAMP DIFFERENCE
                # ==============================================

                timestamp_diff = (
                    get_timestamp_difference_ms(
                        buy_price,
                        sell_price,
                    )
                )

                if timestamp_diff is None:

                    stats[
                        "timestamp_none"
                    ] += 1

                    continue

                if (
                    timestamp_diff
                    > MAX_TIMESTAMP_DIFF_MS
                ):

                    stats[
                        "timestamp_too_large"
                    ] += 1

                    continue

                sell = sell_price.bid

                if sell <= 0:

                    stats["sell_invalid"] += 1

                    logger.info(
                        "sell <= 0"
                    )

                    continue

                # ==================================================
                # 1. RAW SPREAD
                # ==================================================

                spread_percent = (
                    (
                        sell / buy
                    ) - 1
                ) * 100

                # Сохраняем максимальный raw spread
                # для диагностики.

                if (
                    stats["max_raw_spread"]
                    is None
                    or spread_percent
                    > stats["max_raw_spread"]
                ):

                    stats[
                        "max_raw_spread"
                    ] = spread_percent

                # Старый debug оставляем.

                if spread_percent >= 1.0:

                    print(
                        "spread_percent: ",
                        spread_percent,
                    )

                # ==================================================
                # 2. FEES
                # ==================================================

                buy_fee_percent = get_fee(
                    buy_exchange
                )

                sell_fee_percent = get_fee(
                    sell_exchange
                )

                total_fee_percent = (
                    buy_fee_percent * 2
                    + sell_fee_percent * 2
                )

                # ==================================================
                # 3. PRELIMINARY NET
                # ==================================================

                preliminary_net_profit = (
                    spread_percent
                    - total_fee_percent
                )

                if (
                    stats["max_preliminary_net"]
                    is None
                    or preliminary_net_profit
                    > stats["max_preliminary_net"]
                ):

                    stats[
                        "max_preliminary_net"
                    ] = preliminary_net_profit

                if (
                    preliminary_net_profit
                    < MIN_PERCENT
                ):

                    stats[
                        "preliminary_net"
                    ] += 1

                    continue

                orderbook_manager.ensure_pair(
                    buy_exchange=buy_exchange,
                    buy_symbol=buy_price.symbol,
                    sell_exchange=sell_exchange,
                    sell_symbol=sell_price.symbol,
                )

                # ==================================================
                # 4. POSITION SIZE
                # ==================================================

                stats["position"] += 1

                position_notional = (
                    get_position_notional()
                )

                buy_position = (
                    calculate_position(
                        notional_usdt=(
                            position_notional
                        ),
                        price=buy,
                        contract=buy_contract,
                    )
                )

                sell_position = (
                    calculate_position(
                        notional_usdt=(
                            position_notional
                        ),
                        price=sell,
                        contract=sell_contract,
                    )
                )

                if not buy_position[
                    "possible"
                ]:

                    logger.info(
                        "not buy_position -possible-"
                    )

                    continue

                if not sell_position[
                    "possible"
                ]:

                    logger.info(
                        "not sell_position -possible-"
                    )

                    continue

                # ==================================================
                # 5. REAL BUY EXECUTION
                # ==================================================

                buy_execution = (
                    get_execution_price(
                        exchange=buy_exchange,
                        symbol=buy_price.symbol,
                        side=Side.BUY,
                        quantity=(
                            buy_position[
                                "quantity"
                            ]
                        ),
                    )
                )

                if buy_execution is None:

                    stats[
                        "buy_orderbook"
                    ] += 1

                    continue

                # ==================================================
                # 6. REAL SELL EXECUTION
                # ==================================================

                sell_execution = (
                    get_execution_price(
                        exchange=sell_exchange,
                        symbol=sell_price.symbol,
                        side=Side.SELL,
                        quantity=(
                            sell_position[
                                "quantity"
                            ]
                        ),
                    )
                )

                if sell_execution is None:

                    stats[
                        "sell_orderbook"
                    ] += 1

                    continue

                # ==================================================
                # 7. EXECUTION PRICES
                # ==================================================

                buy_execution_price = (
                    buy_execution[
                        "average_price"
                    ]
                )

                sell_execution_price = (
                    sell_execution[
                        "average_price"
                    ]
                )

                if (
                    buy_execution_price
                    <= 0
                ):

                    stats[
                        "execution_price"
                    ] += 1

                    logger.info(
                        "buy_execution_price <= 0"
                    )

                    continue

                if (
                    sell_execution_price
                    <= 0
                ):

                    stats[
                        "execution_price"
                    ] += 1

                    logger.info(
                        "sell_execution_price <= 0"
                    )

                    continue

                # ==================================================
                # 8. REAL SPREAD AFTER SLIPPAGE
                # ==================================================

                execution_spread_percent = (
                    (
                        sell_execution_price
                        / buy_execution_price
                    ) - 1
                ) * 100

                if (
                    execution_spread_percent
                    >= 0.5
                ):

                    print(
                        "execution_spread_percent: "
                        f"{execution_spread_percent}"
                    )

                # ==================================================
                # 9. FINAL NET PROFIT
                # ==================================================

                net_profit_percent = (
                    execution_spread_percent
                    - total_fee_percent
                )

                # print(f"net_profit_percent: , {net_profit_percent}, buy_symbol: , {buy_price.symbol}, buy_exchange: {buy_exchange}")

                if (
                    net_profit_percent
                    < MIN_PERCENT
                ):

                    stats[
                        "final_net"
                    ] += 1

                    continue

                # ==================================================
                # 10. SAVE OPPORTUNITY
                # ==================================================

                opportunities.append(
                    {
                        "asset": asset,

                        "buy_exchange": (
                            buy_exchange
                        ),
                        "buy_symbol": (
                            buy_price.symbol
                        ),
                        "buy_price": buy,

                        "sell_exchange": (
                            sell_exchange
                        ),
                        "sell_symbol": (
                            sell_price.symbol
                        ),
                        "sell_price": sell,

                        "spread_percent": (
                            spread_percent
                        ),

                        "position_notional": (
                            position_notional
                        ),

                        "buy_quantity": (
                            buy_position[
                                "quantity"
                            ]
                        ),
                        "buy_actual_notional": (
                            buy_position[
                                "actual_notional"
                            ]
                        ),

                        "sell_quantity": (
                            sell_position[
                                "quantity"
                            ]
                        ),
                        "sell_actual_notional": (
                            sell_position[
                                "actual_notional"
                            ]
                        ),

                        "buy_contract_size": (
                            buy_contract.contract_size
                        ),
                        "buy_contract_size_currency": (
                            buy_contract
                            .contract_size_currency
                        ),

                        "sell_contract_size": (
                            sell_contract.contract_size
                        ),
                        "sell_contract_size_currency": (
                            sell_contract
                            .contract_size_currency
                        ),

                        "buy_fee_percent": (
                            buy_fee_percent
                        ),
                        "sell_fee_percent": (
                            sell_fee_percent
                        ),

                        "total_fee_percent": (
                            total_fee_percent
                        ),

                        "preliminary_net_profit": (
                            preliminary_net_profit
                        ),

                        "net_profit_percent": (
                            net_profit_percent
                        ),

                        "buy_qty": (
                            buy_price.ask_qty
                        ),
                        "sell_qty": (
                            sell_price.bid_qty
                        ),

                        "buy_timestamp": (
                            buy_price.timestamp
                        ),
                        "sell_timestamp": (
                            sell_price.timestamp
                        ),

                        "timestamp_diff_ms": (
                            timestamp_diff
                        ),

                        "buy_age_ms": (
                            get_price_age_ms(
                                buy_price
                            )
                        ),
                        "sell_age_ms": (
                            get_price_age_ms(
                                sell_price
                            )
                        ),

                        "buy_processing_age_ms": (
                            get_processing_age_ms(
                                buy_price
                            )
                        ),
                        "sell_processing_age_ms": (
                            get_processing_age_ms(
                                sell_price
                            )
                        ),

                        # BUY order book

                        "buy_best_price": (
                            buy_execution[
                                "best_price"
                            ]
                        ),
                        "buy_execution_price": (
                            buy_execution[
                                "average_price"
                            ]
                        ),
                        "buy_slippage_abs": (
                            buy_execution[
                                "slippage_abs"
                            ]
                        ),
                        "buy_slippage_percent": (
                            buy_execution[
                                "slippage_percent"
                            ]
                        ),
                        "buy_levels_used": (
                            buy_execution[
                                "levels_used"
                            ]
                        ),
                        "buy_orderbook_age_ms": (
                            buy_execution[
                                "orderbook_age_ms"
                            ]
                        ),
                        "buy_orderbook_update_id": (
                            buy_execution[
                                "update_id"
                            ]
                        ),

                        # SELL order book

                        "sell_best_price": (
                            sell_execution[
                                "best_price"
                            ]
                        ),
                        "sell_execution_price": (
                            sell_execution[
                                "average_price"
                            ]
                        ),
                        "sell_slippage_abs": (
                            sell_execution[
                                "slippage_abs"
                            ]
                        ),
                        "sell_slippage_percent": (
                            sell_execution[
                                "slippage_percent"
                            ]
                        ),
                        "sell_levels_used": (
                            sell_execution[
                                "levels_used"
                            ]
                        ),
                        "sell_orderbook_age_ms": (
                            sell_execution[
                                "orderbook_age_ms"
                            ]
                        ),
                        "sell_orderbook_update_id": (
                            sell_execution[
                                "update_id"
                            ]
                        ),

                        "execution_spread_percent": (
                            execution_spread_percent
                        ),

                        "detected_at": int(
                            time.time()
                            * 1000
                        ),
                    }
                )

                stats[
                    "opportunities"
                ] += 1

    # ==========================================================
    # DIAGNOSTIC OUTPUT
    # ==========================================================

    log_scanner_stats(stats)

    return opportunities


def print_opportunity(
    opportunity: dict,
) -> None:

    print(
        "\n"
        "========================================\n"
        "ARBITRAGE SIGNAL\n"
        "========================================"
    )

    print(
        f"{opportunity['asset']} | "
        f"BUY {opportunity['buy_exchange']} "
        f"{opportunity['buy_price']:.8f} | "
        f"SELL {opportunity['sell_exchange']} "
        f"{opportunity['sell_price']:.8f}"
    )

    print(
        f"Raw spread:          "
        f"{opportunity['spread_percent']:.4f}%"
    )

    print(
        f"BUY slippage:        "
        f"{opportunity['buy_slippage_percent']:.6f}%"
    )

    print(
        f"SELL slippage:       "
        f"{opportunity['sell_slippage_percent']:.6f}%"
    )

    print(
        f"Execution spread:    "
        f"{opportunity['execution_spread_percent']:.4f}%"
    )

    print(
        f"Total fees:          "
        f"{opportunity['total_fee_percent']:.4f}%"
    )

    print(
        f"NET PROFIT:          "
        f"{opportunity['net_profit_percent']:.4f}%"
    )

    print(
        f"Position:            "
        f"{opportunity['position_notional']:.2f} USDT"
    )

    print(
        f"BUY quantity:        "
        f"{opportunity['buy_quantity']:.12f}"
    )

    print(
        f"SELL quantity:       "
        f"{opportunity['sell_quantity']:.12f}"
    )

    print(
        f"Timestamp diff:      "
        f"{opportunity['timestamp_diff_ms']} ms"
    )

    print(
        f"BUY OB age:          "
        f"{opportunity['buy_orderbook_age_ms']} ms"
    )

    print(
        f"SELL OB age:         "
        f"{opportunity['sell_orderbook_age_ms']} ms"
    )

    print(
        "========================================\n"
    )


async def monitor(
    universe: dict[str, list],
    contracts: dict[str, dict],
    fee_symbols: dict[str, str],
) -> None:

    logger.info(
        "Запуск мониторинга цен"
    )

    last_signal_time: dict[
        tuple[str, str, str],
        int,
    ] = {}

    SIGNAL_COOLDOWN_MS = 20_000

    while True:

        try:

            if is_fee_refresh_needed():

                await asyncio.to_thread(
                    refresh_fees,
                    fee_symbols,
                )

            opportunities = (
                find_arbitrage_opportunities(
                    universe,
                    contracts,
                )
            )

            for opportunity in opportunities:

                key = (
                    opportunity["asset"],
                    opportunity[
                        "buy_exchange"
                    ],
                    opportunity[
                        "sell_exchange"
                    ],
                )

                now_ms = int(
                    time.time() * 1000
                )

                last_time = (
                    last_signal_time.get(key)
                )

                if (
                    last_time is not None
                    and now_ms - last_time
                    < SIGNAL_COOLDOWN_MS
                ):

                    continue

                print_opportunity(
                    opportunity
                )

                last_signal_time[key] = (
                    now_ms
                )

            orderbook_manager.cleanup()

            await asyncio.sleep(
                0.02
            )

        except asyncio.CancelledError:

            raise

        except Exception:

            logger.exception(
                "Ошибка основного цикла мониторинга"
            )

            await asyncio.sleep(1)


async def main() -> None:

    logger.info(
        "Запуск price_scanner.py"
    )

    universe = build_universe()

    logger.info(
        "Universe сформирован: %d монет",
        len(universe),
    )

    fee_symbols = get_fee_symbols(
        universe
    )

    logger.info(
        "Получение taker fee: %s",
        fee_symbols,
    )

    refresh_fees(
        fee_symbols
    )

    contracts = get_valid_contracts()

    exchange_symbols = (
        get_exchange_symbols(
            universe
        )
    )

    logger.info(
        "Символов для WebSocket: "
        "Binance=%d, Bitget=%d, OKX=%d",
        len(
            exchange_symbols[
                "binance"
            ]
        ),
        len(
            exchange_symbols[
                "bitget"
            ]
        ),
        len(
            exchange_symbols[
                "okx"
            ]
        ),
    )

    websocket_tasks = [

        asyncio.create_task(
            run_binance_ws(
                exchange_symbols[
                    "binance"
                ],
                price_cache,
            )
        ),

        asyncio.create_task(
            run_bitget_ws(
                exchange_symbols[
                    "bitget"
                ],
                price_cache,
            )
        ),

        asyncio.create_task(
            run_okx_ws(
                exchange_symbols[
                    "okx"
                ],
                price_cache,
            )
        ),
    ]

    monitor_task = asyncio.create_task(
        monitor(
            universe,
            contracts,
            fee_symbols,
        )
    )

    try:

        await asyncio.gather(
            *websocket_tasks,
            monitor_task,
        )

    except asyncio.CancelledError:

        logger.info(
            "Остановка price_scanner.py"
        )

        for task in websocket_tasks:
            task.cancel()

        monitor_task.cancel()

        raise

    finally:

        await orderbook_manager.shutdown()

        logger.info(
            "price_scanner.py остановлен"
        )


if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        logger.info(
            "price_scanner.py остановлен пользователем"
        )
