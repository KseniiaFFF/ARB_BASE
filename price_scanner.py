# # import asyncio
# # import logging
# # import time

# # from config import (
# #     MIN_PERCENT,
# #     MIN_NET_PERCENT,
# #     PRICE_MAX_AGE_MS,
# #     MAX_TIMESTAMP_DIFF_MS,
# # )

# # from market_universe import build_universe
# # from price_feeds.models_price import Price
# # from price_feeds.orderbook_manager import OrderBookManager
# # from price_feeds.binance_ws import run_binance_ws
# # from price_feeds.bitget_ws import run_bitget_ws
# # from price_feeds.okx_ws import run_okx_ws

# # from profitability.fees import (
# #     get_fee,
# #     refresh_fees,
# #     is_fee_refresh_needed,
# # )

# # from contract_validator import get_valid_contracts

# # from profitability.position_size import (
# #     get_position_notional,
# #     calculate_pair_position,
# # )

# # from price_feeds.orderbook_cache import (
# #     get_orderbook,
# #     get_orderbook_age_ms,
# # )

# # from profitability.slippage import (
# #     Side,
# #     calculate_slippage_complete,
# #     SlippageError,
# # )

# # import signal_tracker
# # import market_latency
# # import market_events

# # logger = logging.getLogger(__name__)

# # ORDERBOOK_WS_MAX_DIFF_PERCENT = 0.2

# # ORDERBOOK_WS_MISMATCH_LOG_INTERVAL_MS = 5000
# # _MISMATCH_LOG_LAST: dict[tuple[str, str, str], int] = {}

# # price_cache: dict[str, dict[str, Price]] = {}


# # last_stats_log_ms = 0
# # orderbook_manager = OrderBookManager()


# # def log_scanner_stats(stats: dict) -> None:
# #     global last_stats_log_ms

# #     now_ms = int(time.time() * 1000)

# #     if now_ms - last_stats_log_ms < 1000:
# #         return

# #     last_stats_log_ms = now_ms

# #     max_raw_spread = stats["max_raw_spread"]

# #     if max_raw_spread is None:
# #         max_raw_spread_text = "None"
# #     else:
# #         max_raw_spread_text = f"{max_raw_spread:.6f}%"

# #     max_preliminary_net = stats["max_preliminary_net"]

# #     if max_preliminary_net is None:
# #         max_preliminary_net_text = "None"
# #     else:
# #         max_preliminary_net_text = (
# #             f"{max_preliminary_net:.6f}%"
# #         )


# # def get_exchange_symbols(
# #     universe: dict[str, list],
# # ) -> dict[str, list[str]]:

# #     symbols = {
# #         "binance": set(),
# #         "bitget": set(),
# #         "okx": set(),
# #     }

# #     for markets in universe.values():

# #         for market in markets:

# #             if not market.active:
# #                 # logger.info("if not market.active")
# #                 continue

# #             if market.exchange not in symbols:
# #                 # logger.info("market.exchange not in symbols")
# #                 continue

# #             symbols[market.exchange].add(
# #                 market.symbol
# #             )

# #     return {
# #         exchange: sorted(exchange_symbols)
# #         for exchange, exchange_symbols in symbols.items()
# #     }


# # def get_fee_symbols(universe):

# #     symbols = {}

# #     for markets in universe.values():

# #         for market in markets:

# #             if not market.active:
# #                 # logger.info("not market.active")
# #                 continue

# #             if market.exchange in symbols:
# #                 continue

# #             symbols[market.exchange] = market.symbol

# #     required_exchanges = {
# #         "binance",
# #         "bitget",
# #         "okx",
# #     }

# #     missing = (
# #         required_exchanges
# #         - symbols.keys()
# #     )

# #     if missing:
# #         raise RuntimeError(
# #             f"Не найдены символы для получения комиссии: "
# #             f"{sorted(missing)}"
# #         )

# #     return {
# #         exchange: symbols[exchange]
# #         for exchange in sorted(required_exchanges)
# #     }


# # def get_price_age_ms(
# #     price: Price,
# # ) -> int | None:

# #     if price.timestamp <= 0:
# #         return None

# #     now_ms = int(
# #         time.time() * 1000
# #     )

# #     age = (
# #         now_ms
# #         - price.received_at
# #     )

# #     if age < 0:
# #         return None

# #     return age


# # def is_price_fresh(
# #     price: Price,
# # ) -> bool:

# #     age = get_price_age_ms(price)

# #     if age is None:
# #         return False

# #     return age <= PRICE_MAX_AGE_MS


# # def get_timestamp_difference_ms(
# #     price_a: Price,
# #     price_b: Price,
# # ) -> int | None:

# #     if (
# #         price_a.timestamp <= 0
# #         or price_b.timestamp <= 0
# #     ):
# #         return None

# #     return abs(
# #         price_a.timestamp
# #         - price_b.timestamp
# #     )


# # def get_processing_age_ms(
# #     price: Price,
# # ) -> float | None:

# #     if price.received_at_ns <= 0:
# #         return None

# #     now_ns = time.monotonic_ns()

# #     age_ns = (
# #         now_ns
# #         - price.received_at_ns
# #     )

# #     if age_ns < 0:
# #         return None

# #     return age_ns / 1_000_000


# # def get_execution_price(
# #     exchange: str,
# #     symbol: str,
# #     side: Side,
# #     quantity: float,
# #     reference_price: float,
# # ) -> dict | None:

# #     orderbook = get_orderbook(
# #         exchange,
# #         symbol,
# #     )

# #     if orderbook is None:

# #         return None

# #     orderbook_age = (
# #         get_orderbook_age_ms(
# #             orderbook
# #         )
# #     )

# #     if orderbook_age is None:
# #         return None

# #     if orderbook_age > PRICE_MAX_AGE_MS:
# #         return None

# #     try:

# #         result = calculate_slippage_complete(
# #             orderbook=orderbook,
# #             side=side,
# #             quantity=quantity,
# #         )

# #     except SlippageError as e:

# #         logger.info(
# #             "Slippage skip %s %s %s: %s",
# #             exchange,
# #             symbol,
# #             side.value,
# #             e,
# #         )

# #         return None

# #     ob_price = result.best_price

# #     if reference_price <= 0 or ob_price <= 0:
# #         # logger.info(
# #         #     "Orderbook price validation skip %s %s %s: "
# #         #     "invalid price reference=%s ob=%s",
# #         #     exchange,
# #         #     symbol,
# #         #     side.value,
# #         #     reference_price,
# #         #     ob_price,
# #         # )
# #         return None

# #     price_diff_percent = abs(
# #         (ob_price / reference_price - 1) * 100
# #     )

# #     if price_diff_percent > ORDERBOOK_WS_MAX_DIFF_PERCENT:
# #         mismatch_key = (exchange, symbol, side.value)
# #         now_ms = int(time.monotonic() * 1000)
# #         last_log_ms = _MISMATCH_LOG_LAST.get(mismatch_key, 0)

# #         if now_ms - last_log_ms >= ORDERBOOK_WS_MISMATCH_LOG_INTERVAL_MS:
# #             _MISMATCH_LOG_LAST[mismatch_key] = now_ms
# #             # logger.info(
# #             #     "Orderbook/WS mismatch skip %s %s %s: "
# #             #     "WS=%.8f OB=%.8f diff=%.6f%% max=%.6f%%",
# #             #     exchange,
# #             #     symbol,
# #             #     side.value,
# #             #     reference_price,
# #             #     ob_price,
# #             #     price_diff_percent,
# #             #     ORDERBOOK_WS_MAX_DIFF_PERCENT,
# #             # )
# #         return None

# #     return {
# #         "best_price": result.best_price,
# #         "average_price": result.average_price,

# #         "slippage_abs": result.slippage_abs,
# #         "slippage_percent": result.slippage_percent,

# #         "requested_quantity": (
# #             result.requested_quantity
# #         ),
# #         "executed_quantity": (
# #             result.executed_quantity
# #         ),

# #         "requested_notional": (
# #             result.requested_notional
# #         ),
# #         "executed_notional": (
# #             result.executed_notional
# #         ),

# #         "levels_used": result.levels_used,

# #         "orderbook_age_ms": orderbook_age,
# #         "update_id": orderbook.update_id,
# #     }


# # def find_arbitrage_opportunities(
# #     universe: dict[str, list],
# #     contracts: dict[str, dict],
# #     assets: set[str] | None = None,
# # ) -> list[dict]:

# #     _scan_started_ns = market_latency.start()

# #     opportunities = []


# #     stats = {
# #         "assets": 0,
# #         "no_prices": 0,
# #         "less_than_2_exchanges": 0,

# #         "buy_contract_none": 0,
# #         "buy_price_stale": 0,

# #         "sell_contract_none": 0,
# #         "sell_price_stale": 0,

# #         "timestamp_none": 0,
# #         "timestamp_too_large": 0,

# #         "sell_invalid": 0,

# #         "preliminary_net": 0,

# #         "position": 0,

# #         "buy_orderbook": 0,
# #         "sell_orderbook": 0,

# #         "execution_price": 0,

# #         "final_net": 0,

# #         "opportunities": 0,

# #         "max_raw_spread": None,
# #         "max_preliminary_net": None,
# #     }


# #     if assets is None:
# #         asset_iter = universe.items()
# #     else:
# #         asset_iter = ((asset, universe[asset]) for asset in assets if asset in universe)

# #     for asset, markets in asset_iter:

# #         stats["assets"] += 1

# #         prices = price_cache.get(asset)

# #         if not prices:

# #             stats["no_prices"] += 1
# #             continue

# #         if len(prices) < 2:

# #             stats["less_than_2_exchanges"] += 1
# #             continue

# #         exchanges = list(
# #             prices.keys()
# #         )


# #         for buy_exchange in exchanges:

# #             buy_price = prices[
# #                 buy_exchange
# #             ]

# #             buy_contract = (
# #                 contracts
# #                 .get(buy_exchange, {})
# #                 .get(buy_price.symbol)
# #             )

# #             if buy_contract is None:

# #                 stats["buy_contract_none"] += 1

# #                 continue

# #             if not is_price_fresh(
# #                 buy_price
# #             ):

# #                 stats["buy_price_stale"] += 1

# #                 continue

# #             buy = buy_price.ask

# #             if buy <= 0:

# #                 # logger.info(
# #                 #     "buy <= 0"
# #                 # )

# #                 continue


# #             for sell_exchange in exchanges:

# #                 if (
# #                     buy_exchange
# #                     == sell_exchange
# #                 ):
# #                     continue

# #                 sell_price = prices[
# #                     sell_exchange
# #                 ]

# #                 sell_contract = (
# #                     contracts
# #                     .get(sell_exchange, {})
# #                     .get(sell_price.symbol)
# #                 )

# #                 if sell_contract is None:

# #                     stats[
# #                         "sell_contract_none"
# #                     ] += 1

# #                     continue

# #                 if not is_price_fresh(
# #                     sell_price
# #                 ):

# #                     stats[
# #                         "sell_price_stale"
# #                     ] += 1

# #                     continue


# #                 timestamp_diff = (
# #                     get_timestamp_difference_ms(
# #                         buy_price,
# #                         sell_price,
# #                     )
# #                 )

# #                 if timestamp_diff is None:

# #                     stats[
# #                         "timestamp_none"
# #                     ] += 1

# #                     continue

# #                 if (
# #                     timestamp_diff
# #                     > MAX_TIMESTAMP_DIFF_MS
# #                 ):

# #                     stats[
# #                         "timestamp_too_large"
# #                     ] += 1

# #                     continue

# #                 sell = sell_price.bid

# #                 if sell <= 0:

# #                     stats["sell_invalid"] += 1

# #                     # logger.info(
# #                     #     "sell <= 0"
# #                     # )

# #                     continue


# #                 spread_percent = (
# #                     (
# #                         sell / buy
# #                     ) - 1
# #                 ) * 100


# #                 if (
# #                     stats["max_raw_spread"]
# #                     is None
# #                     or spread_percent
# #                     > stats["max_raw_spread"]
# #                 ):

# #                     stats[
# #                         "max_raw_spread"
# #                     ] = spread_percent



# #                 buy_fee_percent = get_fee(
# #                     buy_exchange
# #                 )

# #                 sell_fee_percent = get_fee(
# #                     sell_exchange
# #                 )

# #                 total_fee_percent = (
# #                     buy_fee_percent * 2
# #                     + sell_fee_percent * 2
# #                 )


# #                 preliminary_net_profit = (
# #                     spread_percent
# #                     - total_fee_percent
# #                 )

# #                 if (
# #                     stats["max_preliminary_net"]
# #                     is None
# #                     or preliminary_net_profit
# #                     > stats["max_preliminary_net"]
# #                 ):

# #                     stats[
# #                         "max_preliminary_net"
# #                     ] = preliminary_net_profit

# #                 if (
# #                     preliminary_net_profit
# #                     < MIN_PERCENT
# #                 ):

# #                     stats[
# #                         "preliminary_net"
# #                     ] += 1

# #                     continue

# #                 orderbook_manager.ensure_pair(
# #                     buy_exchange=buy_exchange,
# #                     buy_symbol=buy_price.symbol,
# #                     sell_exchange=sell_exchange,
# #                     sell_symbol=sell_price.symbol,
# #                 )


# #                 stats["position"] += 1

# #                 position_notional = (
# #                     get_position_notional()
# #                     )

# #                 position = calculate_pair_position(
# #                     notional_usdt=position_notional,
# #                     buy_price=buy,
# #                     sell_price=sell,
# #                     buy_contract=buy_contract,
# #                     sell_contract=sell_contract,
# #                     )

# #                 if not position["possible"]:

# #                     # logger.info(
# #                     # "Position impossible: %s",
# #                     # position.get("reason", "unknown"),
# #                     # )

# #                     continue

# #                 buy_quantity = position["buy_quantity"]
# #                 sell_quantity = position["sell_quantity"]

# #                 buy_base_quantity = position[
# #                     "buy_base_quantity"
# #                     ]

# #                 sell_base_quantity = position[
# #                     "sell_base_quantity"
# #                     ]


# #                 buy_execution = (
# #                         get_execution_price(
# #                             exchange=buy_exchange,
# #                             symbol=buy_price.symbol,
# #                             side=Side.BUY,
# #                             quantity=buy_quantity,
# #                             reference_price=buy,
# #                         )
# #                     )   

# #                 if buy_execution is None:

# #                     stats[
# #                         "buy_orderbook"
# #                     ] += 1

# #                     continue


# #                 sell_execution = (
# #                         get_execution_price(
# #                             exchange=sell_exchange,
# #                             symbol=sell_price.symbol,
# #                             side=Side.SELL,
# #                             quantity=sell_quantity,
# #                             reference_price=sell,
# #                         )
# #                     )

# #                 if sell_execution is None:

# #                     stats[
# #                         "sell_orderbook"
# #                     ] += 1

# #                     continue


# #                 buy_execution_price = (
# #                     buy_execution[
# #                         "average_price"
# #                     ]
# #                 )

# #                 sell_execution_price = (
# #                     sell_execution[
# #                         "average_price"
# #                     ]
# #                 )

# #                 if (
# #                     buy_execution_price
# #                     <= 0
# #                 ):

# #                     stats[
# #                         "execution_price"
# #                     ] += 1

# #                     # logger.info(
# #                     #     "buy_execution_price <= 0"
# #                     # )

# #                     continue

# #                 if (
# #                     sell_execution_price
# #                     <= 0
# #                 ):

# #                     stats[
# #                         "execution_price"
# #                     ] += 1

# #                     # logger.info(
# #                     #     "sell_execution_price <= 0"
# #                     # )

# #                     continue


# #                 execution_spread_percent = (
# #                     (
# #                         sell_execution_price
# #                         / buy_execution_price
# #                     ) - 1
# #                 ) * 100



# #                 net_profit_percent = (
# #                     execution_spread_percent
# #                     - total_fee_percent
# #                 )


# #                 if (
# #                     net_profit_percent
# #                     < MIN_NET_PERCENT
# #                 ):

# #                     stats[
# #                         "final_net"
# #                     ] += 1

# #                     continue


# #                 opportunities.append(
# #                     {
# #                         "asset": asset,

# #                         "buy_exchange": buy_exchange,
# #                         "buy_symbol": buy_price.symbol,
# #                         "buy_price": buy,

# #                         "sell_exchange": sell_exchange,
# #                         "sell_symbol": sell_price.symbol,
# #                         "sell_price": sell,

# #                         "spread_percent": spread_percent,
# #                         "execution_spread_percent": execution_spread_percent,

# #                         "position_notional": position_notional,

# #                         "buy_quantity": buy_quantity,
# #                         "sell_quantity": sell_quantity,

# #                         "buy_base_quantity": buy_base_quantity,
# #                         "sell_base_quantity": sell_base_quantity,

# #                         "actual_base_quantity": (
# #                             position["actual_base_quantity"]
# #                         ),

# #                         "buy_actual_notional": (
# #                             position["buy_actual_notional"]
# #                         ),
# #                         "sell_actual_notional": (
# #                             position["sell_actual_notional"]
# #                         ),

# #                         "buy_fee_percent": buy_fee_percent,
# #                         "sell_fee_percent": sell_fee_percent,
# #                         "total_fee_percent": total_fee_percent,

# #                         "preliminary_net_profit": (
# #                             preliminary_net_profit
# #                         ),
# #                         "net_profit_percent": net_profit_percent,

# #                         "buy_qty": buy_price.ask_qty,
# #                         "sell_qty": sell_price.bid_qty,

# #                         "buy_timestamp": buy_price.timestamp,
# #                         "sell_timestamp": sell_price.timestamp,
# #                         "timestamp_diff_ms": timestamp_diff,

# #                         "buy_age_ms": get_price_age_ms(
# #                             buy_price
# #                         ),
# #                         "sell_age_ms": get_price_age_ms(
# #                             sell_price
# #                         ),

# #                         "buy_processing_age_ms": (
# #                             get_processing_age_ms(
# #                                 buy_price
# #                             )
# #                         ),
# #                         "sell_processing_age_ms": (
# #                             get_processing_age_ms(
# #                                 sell_price
# #                             )
# #                         ),

# #                         "buy_best_price": (
# #                             buy_execution["best_price"]
# #                         ),
# #                         "buy_ob_ws_diff_percent": abs(
# #                             (
# #                                 buy_execution["best_price"]
# #                                 / buy
# #                                 - 1
# #                             ) * 100
# #                         ),
# #                         "buy_execution_price": (
# #                             buy_execution["average_price"]
# #                         ),
# #                         "buy_slippage_abs": (
# #                             buy_execution["slippage_abs"]
# #                         ),
# #                         "buy_slippage_percent": (
# #                             buy_execution["slippage_percent"]
# #                         ),
# #                         "buy_levels_used": (
# #                             buy_execution["levels_used"]
# #                         ),
# #                         "buy_orderbook_age_ms": (
# #                             buy_execution["orderbook_age_ms"]
# #                         ),
# #                         "buy_orderbook_update_id": (
# #                             buy_execution["update_id"]
# #                         ),

# #                         "sell_best_price": (
# #                             sell_execution["best_price"]
# #                         ),
# #                         "sell_ob_ws_diff_percent": abs(
# #                             (
# #                                 sell_execution["best_price"]
# #                                 / sell
# #                                 - 1
# #                             ) * 100
# #                         ),
# #                         "sell_execution_price": (
# #                             sell_execution["average_price"]
# #                         ),
# #                         "sell_slippage_abs": (
# #                             sell_execution["slippage_abs"]
# #                         ),
# #                         "sell_slippage_percent": (
# #                             sell_execution["slippage_percent"]
# #                         ),
# #                         "sell_levels_used": (
# #                             sell_execution["levels_used"]
# #                         ),
# #                         "sell_orderbook_age_ms": (
# #                             sell_execution["orderbook_age_ms"]
# #                         ),
# #                         "sell_orderbook_update_id": (
# #                             sell_execution["update_id"]
# #                         ),

# #                         "detected_at": int(
# #                             time.time() * 1000
# #                         ),
# #                     }
# #                 )

# #                 stats["opportunities"] += 1



# #     log_scanner_stats(stats)

# #     market_latency.record(
# #         "scanner_find_arbitrage",
# #         _scan_started_ns,
# #     )

# #     return opportunities


# # def print_opportunity(
# #     opportunity: dict,
# # ) -> None:

# #     print(
# #         "\n"
# #         "========================================\n"
# #         "ARBITRAGE SIGNAL\n"
# #         "========================================"
# #     )

# #     print(
# #         f"{opportunity['asset']} | "
# #         f"BUY {opportunity['buy_exchange']} "
# #         f"{opportunity['buy_price']:.8f} | "
# #         f"SELL {opportunity['sell_exchange']} "
# #         f"{opportunity['sell_price']:.8f}"
# #     )

# #     print(
# #         f"Raw spread:          "
# #         f"{opportunity['spread_percent']:.4f}%"
# #     )

# #     print(
# #         f"BUY slippage:        "
# #         f"{opportunity['buy_slippage_percent']:.6f}%"
# #     )

# #     print(
# #         f"SELL slippage:       "
# #         f"{opportunity['sell_slippage_percent']:.6f}%"
# #     )

# #     print(
# #         f"Execution spread:    "
# #         f"{opportunity['execution_spread_percent']:.4f}%"
# #     )

# #     print(
# #         f"Total fees:          "
# #         f"{opportunity['total_fee_percent']:.4f}%"
# #     )

# #     print(
# #         f"NET PROFIT:          "
# #         f"{opportunity['net_profit_percent']:.4f}%"
# #     )

# #     print(
# #         f"Position:            "
# #         f"{opportunity['position_notional']:.2f} USDT"
# #     )

# #     print(
# #         f"BUY quantity:        "
# #         f"{opportunity['buy_quantity']:.12f}"
# #     )

# #     print(
# #         f"SELL quantity:       "
# #         f"{opportunity['sell_quantity']:.12f}"
# #     )

# #     print(
# #         f"Timestamp diff:      "
# #         f"{opportunity['timestamp_diff_ms']} ms"
# #     )

# #     print(
# #         f"BUY OB age:          "
# #         f"{opportunity['buy_orderbook_age_ms']} ms"
# #     )

# #     print(
# #         f"SELL OB age:         "
# #         f"{opportunity['sell_orderbook_age_ms']} ms"
# #     )

# #     print(f"BUY WS price:       {opportunity['buy_price']:.8f}")
# #     print(f"BUY OB best:        {opportunity['buy_best_price']:.8f}")
# #     print(f"BUY OB execution:   {opportunity['buy_execution_price']:.8f}")
# #     print(
# #         f"BUY OB/WS diff:     "
# #         f"{opportunity['buy_ob_ws_diff_percent']:.6f}%"
# #     )

# #     print(f"SELL WS price:      {opportunity['sell_price']:.8f}")
# #     print(f"SELL OB best:       {opportunity['sell_best_price']:.8f}")
# #     print(f"SELL OB execution:  {opportunity['sell_execution_price']:.8f}")
# #     print(
# #         f"SELL OB/WS diff:    "
# #         f"{opportunity['sell_ob_ws_diff_percent']:.6f}%"
# #     )

# #     print(
# #         "========================================\n"
# #     )


# # async def monitor(
# #     universe: dict[str, list],
# #     contracts: dict[str, dict],
# #     fee_symbols: dict[str, str],
# # ) -> None:

# #     # logger.info(
# #     #     "Запуск мониторинга цен"
# #     # )

# #     last_signal_time: dict[
# #         tuple[str, str, str],
# #         int,
# #     ] = {}

# #     SIGNAL_COOLDOWN_MS = 20_000

# #     while True:

# #         try:

# #             market_latency.consume_ws_to_scanner_latency()

# #             if is_fee_refresh_needed():

# #                 await asyncio.to_thread(
# #                     refresh_fees,
# #                     fee_symbols,
# #                 )

# #             opportunities = (
# #                 find_arbitrage_opportunities(
# #                     universe,
# #                     contracts,
# #                 )
# #             )

# #             signal_tracker.update_signal_tracker(
# #                 opportunities
# #             )

# #             for opportunity in opportunities:

# #                 key = (
# #                     opportunity["asset"],
# #                     opportunity[
# #                         "buy_exchange"
# #                     ],
# #                     opportunity[
# #                         "sell_exchange"
# #                     ],
# #                 )

# #                 now_ms = int(
# #                     time.time() * 1000
# #                 )

# #                 last_time = (
# #                     last_signal_time.get(key)
# #                 )

# #                 if (
# #                     last_time is not None
# #                     and now_ms - last_time
# #                     < SIGNAL_COOLDOWN_MS
# #                 ):

# #                     continue

# #                 print_opportunity(
# #                     opportunity
# #                 )

# #                 last_signal_time[key] = (
# #                     now_ms
# #                 )

# #             orderbook_manager.cleanup()

# #             _event_wait_started_ns = market_latency.start()

# #             await market_events.wait_for_updates()

# #             market_latency.record(
# #                 "event_wait",
# #                 _event_wait_started_ns,
# #             )

# #             dirty_assets = market_events.take_dirty_assets()

# #             if not dirty_assets:
# #                 continue

# #             _dirty_scan_started_ns = market_latency.start()

# #             opportunities = find_arbitrage_opportunities(
# #                 universe,
# #                 contracts,
# #                 dirty_assets,
# #             )

# #             market_latency.record(
# #                 "dirty_scan_total",
# #                 _dirty_scan_started_ns,
# #             )

# #         except asyncio.CancelledError:

# #             raise

# #         except Exception:

# #             logger.exception(
# #                 "Ошибка основного цикла мониторинга"
# #             )

# #             await asyncio.sleep(1)


# # async def main() -> None:

# #     # logger.info(
# #     #     "Запуск price_scanner.py"
# #     # )

# #     universe = build_universe()

# #     # logger.info(
# #     #     "Universe сформирован: %d монет",
# #     #     len(universe),
# #     # )

# #     fee_symbols = get_fee_symbols(
# #         universe
# #     )

# #     # logger.info(
# #     #     "Получение taker fee: %s",
# #     #     fee_symbols,
# #     # )

# #     refresh_fees(
# #         fee_symbols
# #     )

# #     contracts = get_valid_contracts()

# #     exchange_symbols = (
# #         get_exchange_symbols(
# #             universe
# #         )
# #     )

# #     # logger.info(
# #     #     "Символов для WebSocket: "
# #     #     "Binance=%d, Bitget=%d, OKX=%d",
# #     #     len(
# #     #         exchange_symbols[
# #     #             "binance"
# #     #         ]
# #     #     ),
# #     #     len(
# #     #         exchange_symbols[
# #     #             "bitget"
# #     #         ]
# #     #     ),
# #     #     len(
# #     #         exchange_symbols[
# #     #             "okx"
# #     #         ]
# #     #     ),
# #     # )

# #     # HOT ORDERBOOK MODE:
# #     # Start every required orderbook before the monitor begins.
# #     # The scanner no longer has to create a cold orderbook connection
# #     # after an arbitrage signal appears.
# #     await orderbook_manager.start_all(
# #         exchange_symbols
# #     )

# #     websocket_tasks = [

# #         asyncio.create_task(
# #             run_binance_ws(
# #                 exchange_symbols[
# #                     "binance"
# #                 ],
# #                 price_cache,
# #             )
# #         ),

# #         asyncio.create_task(
# #             run_bitget_ws(
# #                 exchange_symbols[
# #                     "bitget"
# #                 ],
# #                 price_cache,
# #             )
# #         ),

# #         asyncio.create_task(
# #             run_okx_ws(
# #                 exchange_symbols[
# #                     "okx"
# #                 ],
# #                 price_cache,
# #             )
# #         ),
# #     ]

# #     monitor_task = asyncio.create_task(
# #         monitor(
# #             universe,
# #             contracts,
# #             fee_symbols,
# #         )
# #     )

# #     try:

# #         await asyncio.gather(
# #             *websocket_tasks,
# #             monitor_task,
# #         )

# #     except asyncio.CancelledError:

# #         logger.info(
# #             "Остановка price_scanner.py"
# #         )

# #         for task in websocket_tasks:
# #             task.cancel()

# #         monitor_task.cancel()

# #         raise

# #     finally:

# #         signal_tracker.close_signal_tracker()

# #         await orderbook_manager.shutdown()

# #         logger.info(
# #             "price_scanner.py остановлен"
# #         )


# # if __name__ == "__main__":

# #     try:

# #         asyncio.run(main())

# #     except KeyboardInterrupt:

# #         logger.info(
# #             "price_scanner.py остановлен пользователем"
# #         )

# import asyncio
# import logging
# import time

# from config import (
#     MIN_PERCENT,
#     MIN_NET_PERCENT,
#     PRICE_MAX_AGE_MS,
#     MAX_TIMESTAMP_DIFF_MS,
# )

# from market_universe import build_universe
# from price_feeds.models_price import Price
# from price_feeds.orderbook_manager import OrderBookManager
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
#     calculate_pair_position,
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

# from trading.executor import PairExecutor

# import signal_tracker
# import market_latency
# import market_events

# logger = logging.getLogger(__name__)

# ORDERBOOK_WS_MAX_DIFF_PERCENT = 0.2

# ORDERBOOK_WS_MISMATCH_LOG_INTERVAL_MS = 5000
# _MISMATCH_LOG_LAST: dict[tuple[str, str, str], int] = {}

# price_cache: dict[str, dict[str, Price]] = {}


# last_stats_log_ms = 0
# orderbook_manager = OrderBookManager()
# pair_executor = PairExecutor()

# active_pairs: set[tuple[str, str, str]] = set()
# active_assets: set[str] = set()
# active_monitor_tasks: set[asyncio.Task] = set()
# entry_in_progress = False


# def log_scanner_stats(stats: dict) -> None:
#     global last_stats_log_ms

#     now_ms = int(time.time() * 1000)

#     if now_ms - last_stats_log_ms < 1000:
#         return

#     last_stats_log_ms = now_ms

#     max_raw_spread = stats["max_raw_spread"]

#     if max_raw_spread is None:
#         max_raw_spread_text = "None"
#     else:
#         max_raw_spread_text = f"{max_raw_spread:.6f}%"

#     max_preliminary_net = stats["max_preliminary_net"]

#     if max_preliminary_net is None:
#         max_preliminary_net_text = "None"
#     else:
#         max_preliminary_net_text = (
#             f"{max_preliminary_net:.6f}%"
#         )


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
#                 # logger.info("if not market.active")
#                 continue

#             if market.exchange not in symbols:
#                 # logger.info("market.exchange not in symbols")
#                 continue

#             symbols[market.exchange].add(
#                 market.symbol
#             )

#     return {
#         exchange: sorted(exchange_symbols)
#         for exchange, exchange_symbols in symbols.items()
#     }


# def get_fee_symbols(universe):

#     symbols = {}

#     for markets in universe.values():

#         for market in markets:

#             if not market.active:
#                 # logger.info("not market.active")
#                 continue

#             if market.exchange in symbols:
#                 continue

#             symbols[market.exchange] = market.symbol

#     required_exchanges = {
#         "binance",
#         "bitget",
#         "okx",
#     }

#     missing = (
#         required_exchanges
#         - symbols.keys()
#     )

#     if missing:
#         raise RuntimeError(
#             f"Не найдены символы для получения комиссии: "
#             f"{sorted(missing)}"
#         )

#     return {
#         exchange: symbols[exchange]
#         for exchange in sorted(required_exchanges)
#     }


# def get_price_age_ms(
#     price: Price,
# ) -> int | None:

#     if price.timestamp <= 0:
#         return None

#     now_ms = int(
#         time.time() * 1000
#     )

#     age = (
#         now_ms
#         - price.received_at
#     )

#     if age < 0:
#         return None

#     return age


# def is_price_fresh(
#     price: Price,
# ) -> bool:

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
#         price_a.timestamp
#         - price_b.timestamp
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
#     reference_price: float,
# ) -> dict | None:

#     orderbook = get_orderbook(
#         exchange,
#         symbol,
#     )

#     if orderbook is None:

#         return None

#     orderbook_age = (
#         get_orderbook_age_ms(
#             orderbook
#         )
#     )

#     if orderbook_age is None:
#         return None

#     if orderbook_age > PRICE_MAX_AGE_MS:
#         return None

#     try:

#         result = calculate_slippage_complete(
#             orderbook=orderbook,
#             side=side,
#             quantity=quantity,
#         )

#     except SlippageError as e:

#         logger.info(
#             "Slippage skip %s %s %s: %s",
#             exchange,
#             symbol,
#             side.value,
#             e,
#         )

#         return None

#     ob_price = result.best_price

#     if reference_price <= 0 or ob_price <= 0:
#         # logger.info(
#         #     "Orderbook price validation skip %s %s %s: "
#         #     "invalid price reference=%s ob=%s",
#         #     exchange,
#         #     symbol,
#         #     side.value,
#         #     reference_price,
#         #     ob_price,
#         # )
#         return None

#     price_diff_percent = abs(
#         (ob_price / reference_price - 1) * 100
#     )

#     if price_diff_percent > ORDERBOOK_WS_MAX_DIFF_PERCENT:
#         mismatch_key = (exchange, symbol, side.value)
#         now_ms = int(time.monotonic() * 1000)
#         last_log_ms = _MISMATCH_LOG_LAST.get(mismatch_key, 0)

#         if now_ms - last_log_ms >= ORDERBOOK_WS_MISMATCH_LOG_INTERVAL_MS:
#             _MISMATCH_LOG_LAST[mismatch_key] = now_ms
#             # logger.info(
#             #     "Orderbook/WS mismatch skip %s %s %s: "
#             #     "WS=%.8f OB=%.8f diff=%.6f%% max=%.6f%%",
#             #     exchange,
#             #     symbol,
#             #     side.value,
#             #     reference_price,
#             #     ob_price,
#             #     price_diff_percent,
#             #     ORDERBOOK_WS_MAX_DIFF_PERCENT,
#             # )
#         return None

#     return {
#         "best_price": result.best_price,
#         "average_price": result.average_price,

#         "slippage_abs": result.slippage_abs,
#         "slippage_percent": result.slippage_percent,

#         "requested_quantity": (
#             result.requested_quantity
#         ),
#         "executed_quantity": (
#             result.executed_quantity
#         ),

#         "requested_notional": (
#             result.requested_notional
#         ),
#         "executed_notional": (
#             result.executed_notional
#         ),

#         "levels_used": result.levels_used,

#         "orderbook_age_ms": orderbook_age,
#         "update_id": orderbook.update_id,
#     }


# def find_arbitrage_opportunities(
#     universe: dict[str, list],
#     contracts: dict[str, dict],
#     assets: set[str] | None = None,
# ) -> list[dict]:

#     _scan_started_ns = market_latency.start()

#     opportunities = []


#     stats = {
#         "assets": 0,
#         "no_prices": 0,
#         "less_than_2_exchanges": 0,

#         "buy_contract_none": 0,
#         "buy_price_stale": 0,

#         "sell_contract_none": 0,
#         "sell_price_stale": 0,

#         "timestamp_none": 0,
#         "timestamp_too_large": 0,

#         "sell_invalid": 0,

#         "preliminary_net": 0,

#         "position": 0,

#         "buy_orderbook": 0,
#         "sell_orderbook": 0,

#         "execution_price": 0,

#         "final_net": 0,

#         "opportunities": 0,

#         "max_raw_spread": None,
#         "max_preliminary_net": None,
#     }


#     if assets is None:
#         asset_iter = universe.items()
#     else:
#         asset_iter = ((asset, universe[asset]) for asset in assets if asset in universe)

#     for asset, markets in asset_iter:

#         stats["assets"] += 1

#         prices = price_cache.get(asset)

#         if not prices:

#             stats["no_prices"] += 1
#             continue

#         if len(prices) < 2:

#             stats["less_than_2_exchanges"] += 1
#             continue

#         exchanges = list(
#             prices.keys()
#         )


#         for buy_exchange in exchanges:

#             buy_price = prices[
#                 buy_exchange
#             ]

#             buy_contract = (
#                 contracts
#                 .get(buy_exchange, {})
#                 .get(buy_price.symbol)
#             )

#             if buy_contract is None:

#                 stats["buy_contract_none"] += 1

#                 continue

#             if not is_price_fresh(
#                 buy_price
#             ):

#                 stats["buy_price_stale"] += 1

#                 continue

#             buy = buy_price.ask

#             if buy <= 0:

#                 # logger.info(
#                 #     "buy <= 0"
#                 # )

#                 continue


#             for sell_exchange in exchanges:

#                 if (
#                     buy_exchange
#                     == sell_exchange
#                 ):
#                     continue

#                 sell_price = prices[
#                     sell_exchange
#                 ]

#                 sell_contract = (
#                     contracts
#                     .get(sell_exchange, {})
#                     .get(sell_price.symbol)
#                 )

#                 if sell_contract is None:

#                     stats[
#                         "sell_contract_none"
#                     ] += 1

#                     continue

#                 if not is_price_fresh(
#                     sell_price
#                 ):

#                     stats[
#                         "sell_price_stale"
#                     ] += 1

#                     continue


#                 timestamp_diff = (
#                     get_timestamp_difference_ms(
#                         buy_price,
#                         sell_price,
#                     )
#                 )

#                 if timestamp_diff is None:

#                     stats[
#                         "timestamp_none"
#                     ] += 1

#                     continue

#                 if (
#                     timestamp_diff
#                     > MAX_TIMESTAMP_DIFF_MS
#                 ):

#                     stats[
#                         "timestamp_too_large"
#                     ] += 1

#                     continue

#                 sell = sell_price.bid

#                 if sell <= 0:

#                     stats["sell_invalid"] += 1

#                     # logger.info(
#                     #     "sell <= 0"
#                     # )

#                     continue


#                 spread_percent = (
#                     (
#                         sell / buy
#                     ) - 1
#                 ) * 100


#                 if (
#                     stats["max_raw_spread"]
#                     is None
#                     or spread_percent
#                     > stats["max_raw_spread"]
#                 ):

#                     stats[
#                         "max_raw_spread"
#                     ] = spread_percent



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


#                 preliminary_net_profit = (
#                     spread_percent
#                     - total_fee_percent
#                 )

#                 if (
#                     stats["max_preliminary_net"]
#                     is None
#                     or preliminary_net_profit
#                     > stats["max_preliminary_net"]
#                 ):

#                     stats[
#                         "max_preliminary_net"
#                     ] = preliminary_net_profit

#                 if (
#                     preliminary_net_profit
#                     < MIN_PERCENT
#                 ):

#                     stats[
#                         "preliminary_net"
#                     ] += 1

#                     continue

#                 orderbook_manager.ensure_pair(
#                     buy_exchange=buy_exchange,
#                     buy_symbol=buy_price.symbol,
#                     sell_exchange=sell_exchange,
#                     sell_symbol=sell_price.symbol,
#                 )


#                 stats["position"] += 1

#                 position_notional = (
#                     get_position_notional()
#                     )

#                 position = calculate_pair_position(
#                     notional_usdt=position_notional,
#                     buy_price=buy,
#                     sell_price=sell,
#                     buy_contract=buy_contract,
#                     sell_contract=sell_contract,
#                     )

#                 if not position["possible"]:

#                     # logger.info(
#                     # "Position impossible: %s",
#                     # position.get("reason", "unknown"),
#                     # )

#                     continue

#                 buy_quantity = position["buy_quantity"]
#                 sell_quantity = position["sell_quantity"]

#                 buy_base_quantity = position[
#                     "buy_base_quantity"
#                     ]

#                 sell_base_quantity = position[
#                     "sell_base_quantity"
#                     ]


#                 buy_execution = (
#                         get_execution_price(
#                             exchange=buy_exchange,
#                             symbol=buy_price.symbol,
#                             side=Side.BUY,
#                             quantity=buy_quantity,
#                             reference_price=buy,
#                         )
#                     )   

#                 if buy_execution is None:

#                     stats[
#                         "buy_orderbook"
#                     ] += 1

#                     continue


#                 sell_execution = (
#                         get_execution_price(
#                             exchange=sell_exchange,
#                             symbol=sell_price.symbol,
#                             side=Side.SELL,
#                             quantity=sell_quantity,
#                             reference_price=sell,
#                         )
#                     )

#                 if sell_execution is None:

#                     stats[
#                         "sell_orderbook"
#                     ] += 1

#                     continue


#                 buy_execution_price = (
#                     buy_execution[
#                         "average_price"
#                     ]
#                 )

#                 sell_execution_price = (
#                     sell_execution[
#                         "average_price"
#                     ]
#                 )

#                 if (
#                     buy_execution_price
#                     <= 0
#                 ):

#                     stats[
#                         "execution_price"
#                     ] += 1

#                     # logger.info(
#                     #     "buy_execution_price <= 0"
#                     # )

#                     continue

#                 if (
#                     sell_execution_price
#                     <= 0
#                 ):

#                     stats[
#                         "execution_price"
#                     ] += 1

#                     # logger.info(
#                     #     "sell_execution_price <= 0"
#                     # )

#                     continue


#                 execution_spread_percent = (
#                     (
#                         sell_execution_price
#                         / buy_execution_price
#                     ) - 1
#                 ) * 100



#                 net_profit_percent = (
#                     execution_spread_percent
#                     - total_fee_percent
#                 )


#                 if (
#                     net_profit_percent
#                     < MIN_NET_PERCENT
#                 ):

#                     stats[
#                         "final_net"
#                     ] += 1

#                     continue


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
#                         "execution_spread_percent": execution_spread_percent,

#                         "position_notional": position_notional,

#                         "buy_quantity": buy_quantity,
#                         "sell_quantity": sell_quantity,

#                         "buy_base_quantity": buy_base_quantity,
#                         "sell_base_quantity": sell_base_quantity,

#                         "actual_base_quantity": (
#                             position["actual_base_quantity"]
#                         ),

#                         "buy_actual_notional": (
#                             position["buy_actual_notional"]
#                         ),
#                         "sell_actual_notional": (
#                             position["sell_actual_notional"]
#                         ),

#                         "buy_fee_percent": buy_fee_percent,
#                         "sell_fee_percent": sell_fee_percent,
#                         "total_fee_percent": total_fee_percent,

#                         "preliminary_net_profit": (
#                             preliminary_net_profit
#                         ),
#                         "net_profit_percent": net_profit_percent,

#                         "buy_qty": buy_price.ask_qty,
#                         "sell_qty": sell_price.bid_qty,

#                         "buy_timestamp": buy_price.timestamp,
#                         "sell_timestamp": sell_price.timestamp,
#                         "timestamp_diff_ms": timestamp_diff,

#                         "buy_age_ms": get_price_age_ms(
#                             buy_price
#                         ),
#                         "sell_age_ms": get_price_age_ms(
#                             sell_price
#                         ),

#                         "buy_processing_age_ms": (
#                             get_processing_age_ms(
#                                 buy_price
#                             )
#                         ),
#                         "sell_processing_age_ms": (
#                             get_processing_age_ms(
#                                 sell_price
#                             )
#                         ),

#                         "buy_best_price": (
#                             buy_execution["best_price"]
#                         ),
#                         "buy_ob_ws_diff_percent": abs(
#                             (
#                                 buy_execution["best_price"]
#                                 / buy
#                                 - 1
#                             ) * 100
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

#                         "sell_best_price": (
#                             sell_execution["best_price"]
#                         ),
#                         "sell_ob_ws_diff_percent": abs(
#                             (
#                                 sell_execution["best_price"]
#                                 / sell
#                                 - 1
#                             ) * 100
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

#                         "detected_at": int(
#                             time.time() * 1000
#                         ),
#                     }
#                 )

#                 stats["opportunities"] += 1



#     log_scanner_stats(stats)

#     market_latency.record(
#         "scanner_find_arbitrage",
#         _scan_started_ns,
#     )

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

#     print(f"BUY WS price:       {opportunity['buy_price']:.8f}")
#     print(f"BUY OB best:        {opportunity['buy_best_price']:.8f}")
#     print(f"BUY OB execution:   {opportunity['buy_execution_price']:.8f}")
#     print(
#         f"BUY OB/WS diff:     "
#         f"{opportunity['buy_ob_ws_diff_percent']:.6f}%"
#     )

#     print(f"SELL WS price:      {opportunity['sell_price']:.8f}")
#     print(f"SELL OB best:       {opportunity['sell_best_price']:.8f}")
#     print(f"SELL OB execution:  {opportunity['sell_execution_price']:.8f}")
#     print(
#         f"SELL OB/WS diff:    "
#         f"{opportunity['sell_ob_ws_diff_percent']:.6f}%"
#     )

#     print(
#         "========================================\n"
#     )



# async def process_opportunities(
#     opportunities: list[dict],
#     last_signal_time: dict[tuple[str, str, str], int],
# ) -> None:

#     SIGNAL_COOLDOWN_MS = 20_000

#     for opportunity in opportunities:

#         key = (
#             opportunity["asset"],
#             opportunity["buy_exchange"],
#             opportunity["sell_exchange"],
#         )

#         if key in active_pairs:
#             continue

#         now_ms = int(time.time() * 1000)

#         last_time = last_signal_time.get(key)

#         if (
#             last_time is not None
#             and now_ms - last_time < SIGNAL_COOLDOWN_MS
#         ):
#             continue

#         print_opportunity(opportunity)

#         last_signal_time[key] = now_ms

#         result = await pair_executor.execute(opportunity)

#         if result.success:
#             active_pairs.add(key)

#             print(
#                 f"POSITION OPENED | "
#                 f"{opportunity['asset']} | "
#                 f"BUY {opportunity['buy_exchange']} "
#                 f"{result.buy_filled_quantity:.12f} "
#                 f"@ {result.buy_average_price:.12f} | "
#                 f"SELL {opportunity['sell_exchange']} "
#                 f"{result.sell_filled_quantity:.12f} "
#                 f"@ {result.sell_average_price:.12f}"
#             )

#         else:
#             logger.error(
#                 "Execution failed for %s: %s",
#                 key,
#                 result.error,
#             )


# async def monitor(
#     universe: dict[str, list],
#     contracts: dict[str, dict],
#     fee_symbols: dict[str, str],
# ) -> None:

#     # logger.info(
#     #     "Запуск мониторинга цен"
#     # )

#     last_signal_time: dict[
#         tuple[str, str, str],
#         int,
#     ] = {}

#     while True:

#         try:

#             market_latency.consume_ws_to_scanner_latency()

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

#             signal_tracker.update_signal_tracker(
#                 opportunities
#             )

#             await process_opportunities(
#                 opportunities,
#                 last_signal_time,
#             )

#             orderbook_manager.cleanup()

#             _event_wait_started_ns = market_latency.start()

#             await market_events.wait_for_updates()

#             market_latency.record(
#                 "event_wait",
#                 _event_wait_started_ns,
#             )

#             dirty_assets = market_events.take_dirty_assets()

#             if not dirty_assets:
#                 continue

#             _dirty_scan_started_ns = market_latency.start()

#             opportunities = find_arbitrage_opportunities(
#                 universe,
#                 contracts,
#                 dirty_assets,
#             )

#             await process_opportunities(
#                 opportunities,
#                 last_signal_time,
#             )

#             market_latency.record(
#                 "dirty_scan_total",
#                 _dirty_scan_started_ns,
#             )

#         except asyncio.CancelledError:

#             raise

#         except Exception:

#             logger.exception(
#                 "Ошибка основного цикла мониторинга"
#             )

#             await asyncio.sleep(1)


# async def main() -> None:

#     # logger.info(
#     #     "Запуск price_scanner.py"
#     # )

#     universe = build_universe()

#     # logger.info(
#     #     "Universe сформирован: %d монет",
#     #     len(universe),
#     # )

#     fee_symbols = get_fee_symbols(
#         universe
#     )

#     # logger.info(
#     #     "Получение taker fee: %s",
#     #     fee_symbols,
#     # )

#     refresh_fees(
#         fee_symbols
#     )

#     contracts = get_valid_contracts()

#     exchange_symbols = (
#         get_exchange_symbols(
#             universe
#         )
#     )

#     # logger.info(
#     #     "Символов для WebSocket: "
#     #     "Binance=%d, Bitget=%d, OKX=%d",
#     #     len(
#     #         exchange_symbols[
#     #             "binance"
#     #         ]
#     #     ),
#     #     len(
#     #         exchange_symbols[
#     #             "bitget"
#     #         ]
#     #     ),
#     #     len(
#     #         exchange_symbols[
#     #             "okx"
#     #         ]
#     #     ),
#     # )

#     # HOT ORDERBOOK MODE:
#     # Start every required orderbook before the monitor begins.
#     # The scanner no longer has to create a cold orderbook connection
#     # after an arbitrage signal appears.
#     await orderbook_manager.start_all(
#         exchange_symbols
#     )

#     websocket_tasks = [

#         asyncio.create_task(
#             run_binance_ws(
#                 exchange_symbols[
#                     "binance"
#                 ],
#                 price_cache,
#             )
#         ),

#         asyncio.create_task(
#             run_bitget_ws(
#                 exchange_symbols[
#                     "bitget"
#                 ],
#                 price_cache,
#             )
#         ),

#         asyncio.create_task(
#             run_okx_ws(
#                 exchange_symbols[
#                     "okx"
#                 ],
#                 price_cache,
#             )
#         ),
#     ]

#     await pair_executor.start()

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
#             "Остановка price_scanner.py"
#         )

#         for task in websocket_tasks:
#             task.cancel()

#         monitor_task.cancel()

#         raise

#     finally:

#         signal_tracker.close_signal_tracker()

#         await orderbook_manager.shutdown()

#         await pair_executor.close()

#         logger.info(
#             "price_scanner.py остановлен"
#         )


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
    MIN_NET_PERCENT,
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
    calculate_pair_position,
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

from trading.executor import PairExecutor
from position_monitor import OpenPosition, PositionMonitor

import signal_tracker
import market_latency
import market_events

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

ORDERBOOK_WS_MAX_DIFF_PERCENT = 0.2

ORDERBOOK_WS_MISMATCH_LOG_INTERVAL_MS = 5000
_MISMATCH_LOG_LAST: dict[tuple[str, str, str], int] = {}

price_cache: dict[str, dict[str, Price]] = {}


last_stats_log_ms = 0
orderbook_manager = OrderBookManager()
pair_executor = PairExecutor()
position_monitor = PositionMonitor(price_cache)

active_pairs: set[tuple[str, str, str]] = set()
active_assets: set[str] = set()
active_monitor_tasks: set[asyncio.Task] = set()
entry_in_progress = False

BLACKLIST: set[str] = {
     "SOPH",
     "BTC",
}


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
                # logger.info("if not market.active")
                continue

            if market.exchange not in symbols:
                # logger.info("market.exchange not in symbols")
                continue

            symbols[market.exchange].add(
                market.symbol
            )

    return {
        exchange: sorted(exchange_symbols)
        for exchange, exchange_symbols in symbols.items()
    }


def get_fee_symbols(universe):

    symbols = {}

    for markets in universe.values():

        for market in markets:

            if not market.active:
                # logger.info("not market.active")
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
        price_a.timestamp
        - price_b.timestamp
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
    reference_price: float,
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

    ob_price = result.best_price

    if reference_price <= 0 or ob_price <= 0:
        # logger.info(
        #     "Orderbook price validation skip %s %s %s: "
        #     "invalid price reference=%s ob=%s",
        #     exchange,
        #     symbol,
        #     side.value,
        #     reference_price,
        #     ob_price,
        # )
        return None

    price_diff_percent = abs(
        (ob_price / reference_price - 1) * 100
    )

    if price_diff_percent > ORDERBOOK_WS_MAX_DIFF_PERCENT:
        mismatch_key = (exchange, symbol, side.value)
        now_ms = int(time.monotonic() * 1000)
        last_log_ms = _MISMATCH_LOG_LAST.get(mismatch_key, 0)

        if now_ms - last_log_ms >= ORDERBOOK_WS_MISMATCH_LOG_INTERVAL_MS:
            _MISMATCH_LOG_LAST[mismatch_key] = now_ms
            # logger.info(
            #     "Orderbook/WS mismatch skip %s %s %s: "
            #     "WS=%.8f OB=%.8f diff=%.6f%% max=%.6f%%",
            #     exchange,
            #     symbol,
            #     side.value,
            #     reference_price,
            #     ob_price,
            #     price_diff_percent,
            #     ORDERBOOK_WS_MAX_DIFF_PERCENT,
            # )
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
    assets: set[str] | None = None,
) -> list[dict]:

    _scan_started_ns = market_latency.start()

    opportunities = []


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


    if assets is None:
        asset_iter = universe.items()
    else:
        asset_iter = ((asset, universe[asset]) for asset in assets if asset in universe)

    for asset, markets in asset_iter:

        if asset in BLACKLIST:
            continue

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

                # logger.info(
                #     "buy <= 0"
                # )

                continue


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

                    # logger.info(
                    #     "sell <= 0"
                    # )

                    continue


                spread_percent = (
                    (
                        sell / buy
                    ) - 1
                ) * 100


                if (
                    stats["max_raw_spread"]
                    is None
                    or spread_percent
                    > stats["max_raw_spread"]
                ):

                    stats[
                        "max_raw_spread"
                    ] = spread_percent



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

                    # logger.info(f"preliminary_net_profit: {preliminary_net_profit}, buy_Symbol: {buy_price.symbol}, sell_Symbol: {sell_price.symbol}")

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


                stats["position"] += 1

                position_notional = (
                    get_position_notional()
                    )

                position = calculate_pair_position(
                    notional_usdt=position_notional,
                    buy_price=buy,
                    sell_price=sell,
                    buy_contract=buy_contract,
                    sell_contract=sell_contract,
                    )

                if not position["possible"]:

                    # logger.info(
                    # "Position impossible: %s",
                    # position.get("reason", "unknown"),
                    # )

                    continue

                buy_quantity = position["buy_quantity"]
                sell_quantity = position["sell_quantity"]

                buy_base_quantity = position[
                    "buy_base_quantity"
                    ]

                sell_base_quantity = position[
                    "sell_base_quantity"
                    ]


                buy_execution = (
                        get_execution_price(
                            exchange=buy_exchange,
                            symbol=buy_price.symbol,
                            side=Side.BUY,
                            quantity=buy_quantity,
                            reference_price=buy,
                        )
                    )   

                if buy_execution is None:

                    stats[
                        "buy_orderbook"
                    ] += 1

                    continue


                sell_execution = (
                        get_execution_price(
                            exchange=sell_exchange,
                            symbol=sell_price.symbol,
                            side=Side.SELL,
                            quantity=sell_quantity,
                            reference_price=sell,
                        )
                    )

                if sell_execution is None:

                    stats[
                        "sell_orderbook"
                    ] += 1

                    continue


                buy_execution_price = max(
                    buy_execution[
                        "average_price"
                    ],
                    buy,
                )

                sell_execution_price = min(
                    sell_execution[
                        "average_price"
                    ],
                    sell,
                )

                if (
                    buy_execution_price
                    <= 0
                ):

                    stats[
                        "execution_price"
                    ] += 1

                    # logger.info(
                    #     "buy_execution_price <= 0"
                    # )

                    continue

                if (
                    sell_execution_price
                    <= 0
                ):

                    stats[
                        "execution_price"
                    ] += 1

                    # logger.info(
                    #     "sell_execution_price <= 0"
                    # )

                    continue


                execution_spread_percent = (
                    (
                        sell_execution_price
                        / buy_execution_price
                    ) - 1
                ) * 100



                net_profit_percent = (
                    execution_spread_percent
                    - total_fee_percent
                )


                if (
                    net_profit_percent
                    < MIN_NET_PERCENT
                ):

                    stats[
                        "final_net"
                    ] += 1

                    continue


                opportunities.append(
                    {
                        "asset": asset,

                        "buy_exchange": buy_exchange,
                        "buy_symbol": buy_price.symbol,
                        "buy_price": buy,

                        "sell_exchange": sell_exchange,
                        "sell_symbol": sell_price.symbol,
                        "sell_price": sell,

                        "spread_percent": spread_percent,
                        "execution_spread_percent": execution_spread_percent,

                        "position_notional": position_notional,

                        "buy_quantity": buy_quantity,
                        "sell_quantity": sell_quantity,

                        "buy_base_quantity": buy_base_quantity,
                        "sell_base_quantity": sell_base_quantity,

                        "actual_base_quantity": (
                            position["actual_base_quantity"]
                        ),

                        "buy_actual_notional": (
                            position["buy_actual_notional"]
                        ),
                        "sell_actual_notional": (
                            position["sell_actual_notional"]
                        ),

                        "buy_fee_percent": buy_fee_percent,
                        "sell_fee_percent": sell_fee_percent,
                        "total_fee_percent": total_fee_percent,

                        "preliminary_net_profit": (
                            preliminary_net_profit
                        ),
                        "net_profit_percent": net_profit_percent,

                        "buy_qty": buy_price.ask_qty,
                        "sell_qty": sell_price.bid_qty,

                        "buy_timestamp": buy_price.timestamp,
                        "sell_timestamp": sell_price.timestamp,
                        "timestamp_diff_ms": timestamp_diff,

                        "buy_age_ms": get_price_age_ms(
                            buy_price
                        ),
                        "sell_age_ms": get_price_age_ms(
                            sell_price
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

                        "buy_best_price": (
                            buy_execution["best_price"]
                        ),
                        "buy_ob_ws_diff_percent": abs(
                            (
                                buy_execution["best_price"]
                                / buy
                                - 1
                            ) * 100
                        ),
                        "buy_execution_price": (
                            buy_execution["average_price"]
                        ),
                        "buy_slippage_abs": (
                            buy_execution["slippage_abs"]
                        ),
                        "buy_slippage_percent": (
                            buy_execution["slippage_percent"]
                        ),
                        "buy_levels_used": (
                            buy_execution["levels_used"]
                        ),
                        "buy_orderbook_age_ms": (
                            buy_execution["orderbook_age_ms"]
                        ),
                        "buy_orderbook_update_id": (
                            buy_execution["update_id"]
                        ),

                        "sell_best_price": (
                            sell_execution["best_price"]
                        ),
                        "sell_ob_ws_diff_percent": abs(
                            (
                                sell_execution["best_price"]
                                / sell
                                - 1
                            ) * 100
                        ),
                        "sell_execution_price": (
                            sell_execution["average_price"]
                        ),
                        "sell_slippage_abs": (
                            sell_execution["slippage_abs"]
                        ),
                        "sell_slippage_percent": (
                            sell_execution["slippage_percent"]
                        ),
                        "sell_levels_used": (
                            sell_execution["levels_used"]
                        ),
                        "sell_orderbook_age_ms": (
                            sell_execution["orderbook_age_ms"]
                        ),
                        "sell_orderbook_update_id": (
                            sell_execution["update_id"]
                        ),

                        "detected_at": int(
                            time.time() * 1000
                        ),
                    }
                )

                stats["opportunities"] += 1



    log_scanner_stats(stats)

    market_latency.record(
        "scanner_find_arbitrage",
        _scan_started_ns,
    )

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

    print(f"BUY WS price:       {opportunity['buy_price']:.8f}")
    print(f"BUY OB best:        {opportunity['buy_best_price']:.8f}")
    print(f"BUY OB execution:   {opportunity['buy_execution_price']:.8f}")
    print(
        f"BUY OB/WS diff:     "
        f"{opportunity['buy_ob_ws_diff_percent']:.6f}%"
    )

    print(f"SELL WS price:      {opportunity['sell_price']:.8f}")
    print(f"SELL OB best:       {opportunity['sell_best_price']:.8f}")
    print(f"SELL OB execution:  {opportunity['sell_execution_price']:.8f}")
    print(
        f"SELL OB/WS diff:    "
        f"{opportunity['sell_ob_ws_diff_percent']:.6f}%"
    )

    print(
        "========================================\n"
    )



async def process_opportunities(
    opportunities: list[dict],
    last_signal_time: dict[tuple[str, str, str], int],
) -> None:

    global entry_in_progress

    SIGNAL_COOLDOWN_MS = 20_000

    if entry_in_progress:
        return

    for opportunity in opportunities:

        key = (
            opportunity["asset"],
            opportunity["buy_exchange"],
            opportunity["sell_exchange"],
        )

        if opportunity["asset"] in active_assets:
            continue

        now_ms = int(time.time() * 1000)

        last_time = last_signal_time.get(key)

        if (
            last_time is not None
            and now_ms - last_time < SIGNAL_COOLDOWN_MS
        ):
            continue

        print_opportunity(opportunity)

        last_signal_time[key] = now_ms

        # Reserve the single global arbitrage slot BEFORE sending either leg.
        # This prevents a second entry while the first entry is still being
        # accepted/reconciled by the exchanges.
        entry_in_progress = True

        result = await pair_executor.execute(opportunity)

        if result.success:
            async def _run_position_monitor():
                active_pairs.add(key)
                active_assets.add(opportunity["asset"])
                entry_in_progress = False

                print(
                    f"POSITION OPENED | "
                    f"{opportunity['asset']} | "
                    f"BUY {opportunity['buy_exchange']} "
                    f"{result.buy_filled_quantity:.12f} "
                    f"@ {result.buy_average_price:.12f} | "
                    f"SELL {opportunity['sell_exchange']} "
                    f"{result.sell_filled_quantity:.12f} "
                    f"@ {result.sell_average_price:.12f}"
                )

                position = OpenPosition(
                    asset=opportunity["asset"],
                    buy_exchange=opportunity["buy_exchange"],
                    buy_symbol=opportunity["buy_symbol"],
                    buy_quantity=result.buy_filled_quantity,
                    buy_average_price=result.buy_average_price,
                    sell_exchange=opportunity["sell_exchange"],
                    sell_symbol=opportunity["sell_symbol"],
                    sell_quantity=result.sell_filled_quantity,
                    sell_average_price=result.sell_average_price,
                    buy_fee_percent=opportunity["buy_fee_percent"],
                    sell_fee_percent=opportunity["sell_fee_percent"],
                    opened_at_ms=int(time.time() * 1000),
                )

                logger.info("[MONITOR] START | scanner continues")

                last_monitor_log_ms = 0
                first_monitor_snapshot_logged = False
                monitor_wait_started_ms = int(time.time() * 1000)
                monitor_wait_last_log_ms = monitor_wait_started_ms

                def _log_monitor_snapshot(snapshot):
                    nonlocal last_monitor_log_ms
                    nonlocal first_monitor_snapshot_logged
                    now_ms = int(time.time() * 1000)

                    if not first_monitor_snapshot_logged:
                        first_monitor_snapshot_logged = True
                        logger.warning(
                            "[DIAG] FIRST MONITOR | %s | "
                            "since_open=%sms | "
                            "entry BUY %.12f | entry SELL %.12f | "
                            "exit BUY %.12f | exit SELL %.12f | "
                            "NET %.6f%% | %.6f USDT | "
                            "ages %sms/%sms",
                            position.asset,
                            now_ms - position.opened_at_ms,
                            position.buy_average_price,
                            position.sell_average_price,
                            snapshot.buy_exit_price,
                            snapshot.sell_exit_price,
                            snapshot.net_pnl_percent,
                            snapshot.net_pnl_usdt,
                            snapshot.buy_age_ms,
                            snapshot.sell_age_ms,
                        )

                    # Не спамим лог 50 раз в секунду.
                    if now_ms - last_monitor_log_ms < 250:
                        return

                    last_monitor_log_ms = now_ms

                    logger.info(
                        "[MONITOR] %s | BUY exit %.8f | SELL exit %.8f | "
                        "NET %.6f%% | %.6f USDT | ages %sms/%sms",
                        position.asset,
                        snapshot.buy_exit_price,
                        snapshot.sell_exit_price,
                        snapshot.net_pnl_percent,
                        snapshot.net_pnl_usdt,
                        snapshot.buy_age_ms,
                        snapshot.sell_age_ms,
                    )

                async def _monitor_with_wait_diagnostic():
                    nonlocal monitor_wait_last_log_ms

                    while True:
                        now_ms = int(time.time() * 1000)

                        buy_price = (
                            price_cache
                            .get(position.asset, {})
                            .get(position.buy_exchange)
                        )
                        sell_price = (
                            price_cache
                            .get(position.asset, {})
                            .get(position.sell_exchange)
                        )

                        buy_age = (
                            get_price_age_ms(buy_price)
                            if buy_price is not None
                            else None
                        )
                        sell_age = (
                            get_price_age_ms(sell_price)
                            if sell_price is not None
                            else None
                        )

                        buy_ok = (
                            buy_price is not None
                            and buy_age is not None
                            and buy_age <= PRICE_MAX_AGE_MS
                            and buy_price.bid > 0
                            and buy_price.ask > 0
                        )
                        sell_ok = (
                            sell_price is not None
                            and sell_age is not None
                            and sell_age <= PRICE_MAX_AGE_MS
                            and sell_price.bid > 0
                            and sell_price.ask > 0
                        )

                        if buy_ok and sell_ok:
                            return await position_monitor.monitor(
                                position,
                                on_update=_log_monitor_snapshot,
                            )

                        if now_ms - monitor_wait_last_log_ms >= 250:
                            monitor_wait_last_log_ms = now_ms

                            if buy_price is None:
                                buy_state = "missing"
                            elif buy_age is None:
                                buy_state = "invalid_age"
                            elif buy_age > PRICE_MAX_AGE_MS:
                                buy_state = f"stale_{buy_age}ms"
                            elif buy_price.bid <= 0 or buy_price.ask <= 0:
                                buy_state = "invalid_bbo"
                            else:
                                buy_state = f"ok_{buy_age}ms"

                            if sell_price is None:
                                sell_state = "missing"
                            elif sell_age is None:
                                sell_state = "invalid_age"
                            elif sell_age > PRICE_MAX_AGE_MS:
                                sell_state = f"stale_{sell_age}ms"
                            elif sell_price.bid <= 0 or sell_price.ask <= 0:
                                sell_state = "invalid_bbo"
                            else:
                                sell_state = f"ok_{sell_age}ms"

                            logger.warning(
                                "[DIAG] MONITOR WAIT | %s | "
                                "since_open=%sms | BUY %s | SELL %s",
                                position.asset,
                                now_ms - monitor_wait_started_ms,
                                buy_state,
                                sell_state,
                            )

                        await asyncio.sleep(0.02)

                exit_snapshot = await _monitor_with_wait_diagnostic()

                if exit_snapshot is None:
                    return

                print(
                    f"[EXIT] CONDITION | "
                    f"NET PnL {exit_snapshot.net_pnl_percent:.6f}% | "
                    f"{exit_snapshot.net_pnl_usdt:.6f} USDT"
                )

                close_result = await pair_executor.close_position(
                    position,
                )

                if close_result.success:
                    active_pairs.discard(key)
                    active_assets.discard(position.asset)
                    logger.info("[EXIT] POSITION CLOSED | SCANNER CONTINUES")
                else:
                    logger.critical(
                        "Position close failed for %s: %s",
                        key,
                        close_result.error,
                    )
                    # Keep the global entry lock. A new trade must not be opened
                    # until the unresolved position is confirmed flat.

            monitor_task = asyncio.create_task(_run_position_monitor())
            active_monitor_tasks.add(monitor_task)
            monitor_task.add_done_callback(active_monitor_tasks.discard)
        else:
            logger.error(
                "Execution failed for %s: %s",
                key,
                result.error,
            )

            # Never allow a new entry until both exchanges confirm that the
            # failed attempt left no residual position.
            try:
                if await pair_executor.positions_are_flat(opportunity):
                    entry_in_progress = False
            except Exception:
                logger.exception(
                    "Failed to verify flat state after execution failure for %s",
                    key,
                )


async def monitor(
    universe: dict[str, list],
    contracts: dict[str, dict],
    fee_symbols: dict[str, str],
) -> None:

    # logger.info(
    #     "Запуск мониторинга цен"
    # )

    last_signal_time: dict[
        tuple[str, str, str],
        int,
    ] = {}

    while True:

        try:

            market_latency.consume_ws_to_scanner_latency()

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

            signal_tracker.update_signal_tracker(
                opportunities
            )

            await process_opportunities(
                opportunities,
                last_signal_time,
            )

            orderbook_manager.cleanup()

            _event_wait_started_ns = market_latency.start()

            await market_events.wait_for_updates()

            market_latency.record(
                "event_wait",
                _event_wait_started_ns,
            )

            dirty_assets = market_events.take_dirty_assets()

            if not dirty_assets:
                continue

            _dirty_scan_started_ns = market_latency.start()

            opportunities = find_arbitrage_opportunities(
                universe,
                contracts,
                dirty_assets,
            )

            await process_opportunities(
                opportunities,
                last_signal_time,
            )

            market_latency.record(
                "dirty_scan_total",
                _dirty_scan_started_ns,
            )

        except asyncio.CancelledError:

            raise

        except Exception:

            logger.exception(
                "Ошибка основного цикла мониторинга"
            )

            await asyncio.sleep(1)


async def main() -> None:

    # logger.info(
    #     "Запуск price_scanner.py"
    # )

    universe = build_universe()

    # logger.info(
    #     "Universe сформирован: %d монет",
    #     len(universe),
    # )

    fee_symbols = get_fee_symbols(
        universe
    )

    # logger.info(
    #     "Получение taker fee: %s",
    #     fee_symbols,
    # )

    refresh_fees(
        fee_symbols
    )

    contracts = get_valid_contracts()

    exchange_symbols = (
        get_exchange_symbols(
            universe
        )
    )

    # logger.info(
    #     "Символов для WebSocket: "
    #     "Binance=%d, Bitget=%d, OKX=%d",
    #     len(
    #         exchange_symbols[
    #             "binance"
    #         ]
    #     ),
    #     len(
    #         exchange_symbols[
    #             "bitget"
    #         ]
    #     ),
    #     len(
    #         exchange_symbols[
    #             "okx"
    #         ]
    #     ),
    # )

    # HOT ORDERBOOK MODE:
    # Start every required orderbook before the monitor begins.
    # The scanner no longer has to create a cold orderbook connection
    # after an arbitrage signal appears.
    await orderbook_manager.start_all(
        exchange_symbols
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

    await pair_executor.start()

    await pair_executor.prepare_leverage(
        exchange_symbols
    )

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

        signal_tracker.close_signal_tracker()

        await orderbook_manager.shutdown()

        await pair_executor.close()

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
