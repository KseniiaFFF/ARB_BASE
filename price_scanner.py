import asyncio
import logging
import time

from config import MIN_PERCENT, PRICE_MAX_AGE_MS, MAX_TIMESTAMP_DIFF_MS

from market_universe import build_universe

from price_feeds.models_price import Price

from price_feeds.binance_ws import run_binance_ws
from price_feeds.bitget_ws import run_bitget_ws
from price_feeds.okx_ws import run_okx_ws
from profitability.fees import get_fee
from contract_validator import get_valid_contracts
from profitability.position_size import (
    get_position_notional,
    calculate_position,
)


logger = logging.getLogger(__name__)

price_cache: dict[str, dict[str, Price]] = {}


def get_exchange_symbols(
    universe: dict[str, list]
) -> dict[str, list[str]]:

    symbols = {
        "binance": set(),
        "bitget": set(),
        "okx": set(),
    }

    for markets in universe.values():

        for market in markets:

            if not market.active:
                continue

            if market.exchange not in symbols:
                continue

            symbols[market.exchange].add(
                market.symbol
            )

    return {
        exchange: sorted(exchange_symbols)
        for exchange, exchange_symbols
        in symbols.items()
    }


def get_price_age_ms(price: Price) -> int | None:

    if price.timestamp <= 0:
        return None

    now_ms = int(time.time() * 1000)

    # age = now_ms - price.timestamp
    age = now_ms - price.received_at

    if age < 0:
        return None

    return age


def is_price_fresh(price: Price) -> bool:

    age = get_price_age_ms(price)

    if age is None:
        return False

    return age <= PRICE_MAX_AGE_MS


def get_timestamp_difference_ms(price_a: Price, price_b: Price) -> int | None:

    if (price_a.timestamp <= 0 or price_b.timestamp <= 0):
        return None

    # return abs(price_a.timestamp - price_b.timestamp)
    return abs(price_a.received_at - price_b.received_at)


# def get_receive_delay_ms(price: Price, ) -> int | None:

#     if (price.timestamp <= 0 or price.received_at <= 0):
#         return None

#     delay = price.received_at - price.timestamp

#     if delay < 0:
#         logger.warning(
#             "%s: local clock is behind exchange timestamp by %dms",
#             price.exchange,
#             abs(delay),
#         )

#     return delay


def get_processing_age_ms(price: Price) -> float | None:

    if price.received_at_ns <= 0:
        return None

    now_ns = time.monotonic_ns()

    age_ns = now_ns - price.received_at_ns

    if age_ns < 0:
        return None

    return age_ns / 1_000_000


def find_arbitrage_opportunities(
    universe: dict[str, list],
    contracts: dict[str, dict],
) -> list[dict]:

    opportunities = []

    for asset, markets in universe.items():

        prices = price_cache.get(asset)

        if not prices:
            continue

        if len(prices) < 2:
            continue

        exchanges = list(prices.keys())

        for buy_exchange in exchanges:

            buy_price = prices[buy_exchange]

            buy_contract = contracts.get(
                buy_exchange,
                {},
            ).get(
                buy_price.symbol
            )

            if buy_contract is None:
                continue

            if not is_price_fresh(buy_price):
                continue

            buy = buy_price.ask

            if buy <= 0:
                continue

            for sell_exchange in exchanges:

                if buy_exchange == sell_exchange:
                    continue

                sell_price = prices[sell_exchange]

                sell_contract = contracts.get(
                    sell_exchange,
                    {},
                ).get(
                    sell_price.symbol
                )

                if sell_contract is None:
                    continue

                if not is_price_fresh(sell_price):
                    continue

                timestamp_diff = get_timestamp_difference_ms(buy_price, sell_price)

                if timestamp_diff is None:
                    continue

                if timestamp_diff > MAX_TIMESTAMP_DIFF_MS:
                    # logger.info(f"Symbol skip: {timestamp_diff}")
                    continue


                sell = sell_price.bid

                if sell <= 0:
                    continue

                position_notional = get_position_notional()

                buy_position = calculate_position(
                    notional_usdt=position_notional,
                    price=buy,
                    contract=buy_contract,
                )

                sell_position = calculate_position(
                    notional_usdt=position_notional,
                    price=sell,
                    contract=sell_contract,
                )

                if not buy_position["possible"]:
                    continue

                if not sell_position["possible"]:
                    continue

                spread_percent = (
                    (sell / buy) - 1
                ) * 100

                buy_fee_percent = get_fee(
                    buy_exchange,
                    buy_price.symbol,
                )

                sell_fee_percent = get_fee(
                    sell_exchange,
                    sell_price.symbol,
                )

                total_fee_percent = (
                    buy_fee_percent * 2 + sell_fee_percent * 2
                )


                net_profit_percent = (
                    spread_percent - total_fee_percent
                )

                if net_profit_percent < MIN_PERCENT:
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

                        "position_notional": position_notional,

                        "buy_quantity": buy_position["quantity"],
                        "buy_actual_notional": buy_position["actual_notional"],

                        "sell_quantity": sell_position["quantity"],
                        "sell_actual_notional": sell_position["actual_notional"],

                        "buy_contract_size": buy_contract.contract_size,
                        "buy_contract_size_currency": buy_contract.contract_size_currency,

                        "sell_contract_size": sell_contract.contract_size,
                        "sell_contract_size_currency": sell_contract.contract_size_currency,

                        "buy_fee_percent": buy_fee_percent,
                        "sell_fee_percent": sell_fee_percent,

                        "total_fee_percent": total_fee_percent,

                        "net_profit_percent": net_profit_percent,

                        "buy_qty": buy_price.ask_qty,
                        "sell_qty": sell_price.bid_qty,

                        "buy_timestamp": buy_price.timestamp,
                        "sell_timestamp": sell_price.timestamp,

                        "timestamp_diff_ms": timestamp_diff,

                        "buy_age_ms": get_price_age_ms(buy_price),
                        "sell_age_ms": get_price_age_ms(sell_price),

                        # "buy_latency_ms": get_receive_delay_ms(buy_price),
                        # "sell_latency_ms": get_receive_delay_ms(sell_price),

                        "buy_processing_age_ms": get_processing_age_ms(buy_price),
                        "sell_processing_age_ms": get_processing_age_ms(sell_price),

                        "detected_at": int(
                            time.time() * 1000
                        ),
                    }
                )

    return opportunities


def print_opportunity(
    opportunity: dict
) -> None:

    print(
        "\n"
        "========================================\n"
        "ARBITRAGE SIGNAL\n"
        "========================================"
    )

    print(
        f"Монета: {opportunity['asset']}"
    )

    print(
        f"BUY : "
        f"{opportunity['buy_exchange']:8} "
        f"{opportunity['buy_symbol']:20} "
        f"{opportunity['buy_price']}"
    )

    print(
        f"SELL: "
        f"{opportunity['sell_exchange']:8} "
        f"{opportunity['sell_symbol']:20} "
        f"{opportunity['sell_price']}"
    )

    print(
    f"Net profit:           "
    f"{opportunity['net_profit_percent']:.4f}%"
    )

    print(
    f"Position notional:  "
    f"{opportunity['position_notional']:.8f} USDT"
)

    print(
        f"Buy quantity:       "
        f"{opportunity['buy_quantity']:.12f}"
    )

    print(
        f"Buy actual notional:"
        f" {opportunity['buy_actual_notional']:.8f} USDT"
    )

    print(
        f"Sell quantity:      "
        f"{opportunity['sell_quantity']:.12f}"
    )

    print(
        f"Sell actual notional:"
        f" {opportunity['sell_actual_notional']:.8f} USDT"
    )

    print(
        f"Ask quantity:        "
        f"{opportunity['buy_qty']}"
    )

    print(
        f"Bid quantity:        "
        f"{opportunity['sell_qty']}"
    )

    print(
        f"Buy timestamp:       "
        f"{opportunity['buy_timestamp']}"
    )

    print(
        f"Sell timestamp:      "
        f"{opportunity['sell_timestamp']}"
    )

    print(
        f"Timestamp diff:      "
        f"{opportunity['timestamp_diff_ms']} ms"
    )

    print(
        f"Buy age:             "
        f"{opportunity['buy_age_ms']} ms"
    )

    print(
        f"Sell age:            "
        f"{opportunity['sell_age_ms']} ms"
    )

    print(
            f"Buy_processing_age_ms:             "
            f"{opportunity["buy_processing_age_ms"]} ms"
        )
    
    print(
        f"Sell_processing_age_ms:            "
        f"{opportunity["sell_processing_age_ms"]} ms"
    )

    print(
        f"Detected at:         "
        f"{opportunity['detected_at']}"
    )

    print(
        "========================================\n"
    )



async def monitor(
    universe: dict[str, list],
    contracts: dict[str, dict]
) -> None:

    logger.info(
        "Запуск мониторинга цен"
    )

    # last_signals: dict[
    #     tuple[str, str, str],
    #     # float
    #     int
    # ] = {}
    last_signal_time: dict[
            tuple[str, str, str],
            # float
            int
        ] = {}

    SIGNAL_COOLDOWN_MS = 20_000

    while True:

        try:

            opportunities = (
                find_arbitrage_opportunities(
                    universe,
                    contracts,
                )
            )

            for opportunity in opportunities:

                key = (
                    opportunity["asset"],
                    opportunity["buy_exchange"],
                    opportunity["sell_exchange"],
                )

                now_ms = int(
                    time.time() * 1000
                )

                last_time = last_signal_time.get(key)

                if (
                    last_time is not None
                    and now_ms - last_time < SIGNAL_COOLDOWN_MS
                ):
                    continue

                # spread = (
                #     opportunity["spread_percent"]
                # )

                # previous = last_signals.get(key)

                # if (
                #     previous is None
                #     or abs(spread - previous) >= 0.01
                # ):

                print_opportunity(
                    opportunity
                )

                logger.info(
                    "Arbitrage: %s | "
                    "BUY %s %.8f | "
                    "SELL %s %.8f | "
                    "spread=%.4f%% | "
                    "timestamp_diff=%dms | "
                    "buy_age=%dms | "
                    "sell_age=%dms | "
                    # "buy_latency=%dms | "
                    # "sell_latency=%dms",
                    "buy_processing_age=%sms | "
                    "sell_processing_age=%sms",
                    
                    opportunity["asset"],

                    opportunity["buy_exchange"],
                    opportunity["buy_price"],

                    opportunity["sell_exchange"],
                    opportunity["sell_price"],

                    opportunity["spread_percent"],

                    opportunity["timestamp_diff_ms"],

                    opportunity["buy_age_ms"],
                    opportunity["sell_age_ms"],

                    # opportunity["buy_latency_ms"],
                    # opportunity["sell_latency_ms"],
                    opportunity["buy_processing_age_ms"],
                    opportunity["sell_processing_age_ms"],
                )

                last_signal_time[key] = now_ms

                # last_signals[key] = spread

            await asyncio.sleep(0.02)

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

    print(
        "Формирование market universe..."
    )

    universe = build_universe()

    logger.info(
        "Universe сформирован: %d монет",
        len(universe)
    )

    contracts = get_valid_contracts()

    print(
        f"Universe: {len(universe)} монет"
    )

    exchange_symbols = (
        get_exchange_symbols(universe)
    )

    print(
        f"Binance: "
        f"{len(exchange_symbols['binance'])}"
    )

    print(
        f"Bitget:  "
        f"{len(exchange_symbols['bitget'])}"
    )

    print(
        f"OKX:     "
        f"{len(exchange_symbols['okx'])}"
    )

    logger.info(
        "Символов для WebSocket: "
        "Binance=%d, Bitget=%d, OKX=%d",
        len(exchange_symbols["binance"]),
        len(exchange_symbols["bitget"]),
        len(exchange_symbols["okx"]),
    )


    websocket_tasks = [

        asyncio.create_task(
            run_binance_ws(
                exchange_symbols["binance"],
                price_cache,
            )
        ),

        asyncio.create_task(
            run_bitget_ws(
                exchange_symbols["bitget"],
                price_cache,
            )
        ),

        asyncio.create_task(
            run_okx_ws(
                exchange_symbols["okx"],
                price_cache,
            )
        ),
    ]


    monitor_task = asyncio.create_task(
        monitor(universe, contracts,)
    )

    try:

        await asyncio.gather(
            *websocket_tasks,
            monitor_task,
        )

    except asyncio.CancelledError:

        logger.info(
            "price_scanner.py остановлен"
        )

        for task in websocket_tasks:
            task.cancel()

        monitor_task.cancel()

        raise


if __name__ == "__main__":

    try:
        asyncio.run(main())

    except KeyboardInterrupt:

        logger.info(
            "price_scanner.py остановлен пользователем"
        )