import asyncio

from price_feeds.orderbook_cache import (
    get_orderbook,
    get_orderbook_age_ms,
    is_orderbook_fresh,
)

from price_feeds.binance_orderbook import (
    run_binance_orderbook,
)

from price_feeds.bitget_orderbook import (
    run_bitget_orderbook,
)

from price_feeds.okx_orderbook import (
    run_okx_orderbook,
)

from profitability.profitability import (
    calculate_arbitrage_profitability,
)


# ============================================================
# CONFIG
# ============================================================

BINANCE_SYMBOL = "BTCUSDT"
BITGET_SYMBOL = "BTCUSDT"
OKX_SYMBOL = "BTC-USDT-SWAP"

QUANTITY = 0.075

MAX_ORDERBOOK_AGE_MS = 1000

WAIT_TIMEOUT_SECONDS = 15


# ============================================================
# WAIT FOR ORDERBOOKS
# ============================================================

async def wait_for_orderbooks() -> bool:

    start = asyncio.get_running_loop().time()

    while True:

        binance = get_orderbook(
            "binance",
            BINANCE_SYMBOL,
        )

        bitget = get_orderbook(
            "bitget",
            BITGET_SYMBOL,
        )

        okx = get_orderbook(
            "okx",
            OKX_SYMBOL,
        )

        if (
            binance is not None
            and bitget is not None
            and okx is not None
        ):

            if (
                is_orderbook_fresh(
                    binance,
                    MAX_ORDERBOOK_AGE_MS,
                )
                and
                is_orderbook_fresh(
                    bitget,
                    MAX_ORDERBOOK_AGE_MS,
                )
                and
                is_orderbook_fresh(
                    okx,
                    MAX_ORDERBOOK_AGE_MS,
                )
            ):

                return True

        elapsed = (
            asyncio.get_running_loop().time()
            - start
        )

        if elapsed >= WAIT_TIMEOUT_SECONDS:

            return False

        await asyncio.sleep(0.1)


# ============================================================
# PRINT ORDERBOOK STATUS
# ============================================================

def print_orderbook_status() -> None:

    orderbooks = [
        (
            "BINANCE",
            "binance",
            BINANCE_SYMBOL,
        ),
        (
            "BITGET",
            "bitget",
            BITGET_SYMBOL,
        ),
        (
            "OKX",
            "okx",
            OKX_SYMBOL,
        ),
    ]

    for name, exchange, symbol in orderbooks:

        orderbook = get_orderbook(
            exchange,
            symbol,
        )

        if orderbook is None:

            print(
                f"{name:<8} NO ORDERBOOK"
            )

            continue

        age = get_orderbook_age_ms(
            orderbook
        )

        if age is None:

            print(
                f"{name:<8} INVALID AGE"
            )

            continue

        if age > MAX_ORDERBOOK_AGE_MS:

            print(
                f"{name:<8} STALE "
                f"({age} ms)"
            )

            continue

        print(
            f"{name:<8} OK "
            f"age={age} ms "
            f"bids={len(orderbook.bids)} "
            f"asks={len(orderbook.asks)}"
        )


# ============================================================
# CALCULATE
# ============================================================

def calculate(
    buy_exchange: str,
    buy_symbol: str,
    sell_exchange: str,
    sell_symbol: str,
):

    buy_orderbook = get_orderbook(
        buy_exchange,
        buy_symbol,
    )

    sell_orderbook = get_orderbook(
        sell_exchange,
        sell_symbol,
    )

    if buy_orderbook is None:
        return None

    if sell_orderbook is None:
        return None

    return calculate_arbitrage_profitability(

        buy_orderbook=buy_orderbook,

        sell_orderbook=sell_orderbook,

        buy_quantity=QUANTITY,

        sell_quantity=QUANTITY,
    )


# ============================================================
# PRINT RESULT
# ============================================================

def print_result(
    result,
) -> None:

    print(
        f"{result.buy_exchange.upper():<8} -> "
        f"{result.sell_exchange.upper():<8}: "
        f"{result.net_profit_percent:+.6f}%"
    )


# ============================================================
# MAIN
# ============================================================

async def main():

    print()
    print("=" * 70)
    print("ARBITRAGE PROFITABILITY")
    print("=" * 70)

    print(
        f"Quantity: {QUANTITY} BTC"
    )

    print(
        f"Max orderbook age: "
        f"{MAX_ORDERBOOK_AGE_MS} ms"
    )

    # ========================================================
    # START ORDERBOOKS
    # ========================================================

    tasks = [

        asyncio.create_task(
            run_binance_orderbook(
                BINANCE_SYMBOL
            )
        ),

        asyncio.create_task(
            run_bitget_orderbook(
                BITGET_SYMBOL
            )
        ),

        asyncio.create_task(
            run_okx_orderbook(
                OKX_SYMBOL
            )
        ),
    ]

    try:

        # ====================================================
        # WAIT
        # ====================================================

        ready = await wait_for_orderbooks()

        print()

        print_orderbook_status()

        print()

        if not ready:

            print(
                "Недостаточно актуальных стаканов "
                "для расчёта."
            )

            return

        # ====================================================
        # CHECK AGE ONE MORE TIME
        # ====================================================

        binance = get_orderbook(
            "binance",
            BINANCE_SYMBOL,
        )

        bitget = get_orderbook(
            "bitget",
            BITGET_SYMBOL,
        )

        okx = get_orderbook(
            "okx",
            OKX_SYMBOL,
        )

        if (
            binance is None
            or bitget is None
            or okx is None
        ):

            print(
                "Один из стаканов исчез из cache."
            )

            return

        if not is_orderbook_fresh(
            binance,
            MAX_ORDERBOOK_AGE_MS,
        ):

            print(
                "Binance стакан устарел."
            )

            return

        if not is_orderbook_fresh(
            bitget,
            MAX_ORDERBOOK_AGE_MS,
        ):

            print(
                "Bitget стакан устарел."
            )

            return

        if not is_orderbook_fresh(
            okx,
            MAX_ORDERBOOK_AGE_MS,
        ):

            print(
                "OKX стакан устарел."
            )

            return

        # ====================================================
        # AGE
        # ====================================================

        binance_age = get_orderbook_age_ms(
            binance
        )

        bitget_age = get_orderbook_age_ms(
            bitget
        )

        okx_age = get_orderbook_age_ms(
            okx
        )

        print(
            f"Binance age: {binance_age} ms"
        )

        print(
            f"Bitget age:  {bitget_age} ms"
        )

        print(
            f"OKX age:     {okx_age} ms"
        )

        # ====================================================
        # CALCULATIONS
        # ====================================================

        print()
        print("-" * 70)

        # Binance -> Bitget

        result = calculate(
            "binance",
            BINANCE_SYMBOL,
            "bitget",
            BITGET_SYMBOL,
        )

        if result is not None:
            print_result(result)

        # Bitget -> Binance

        result = calculate(
            "bitget",
            BITGET_SYMBOL,
            "binance",
            BINANCE_SYMBOL,
        )

        if result is not None:
            print_result(result)

        # Binance -> OKX

        result = calculate(
            "binance",
            BINANCE_SYMBOL,
            "okx",
            OKX_SYMBOL,
        )

        if result is not None:
            print_result(result)

        # OKX -> Binance

        result = calculate(
            "okx",
            OKX_SYMBOL,
            "binance",
            BINANCE_SYMBOL,
        )

        if result is not None:
            print_result(result)

        # Bitget -> OKX

        result = calculate(
            "bitget",
            BITGET_SYMBOL,
            "okx",
            OKX_SYMBOL,
        )

        if result is not None:
            print_result(result)

        # OKX -> Bitget

        result = calculate(
            "okx",
            OKX_SYMBOL,
            "bitget",
            BITGET_SYMBOL,
        )

        if result is not None:
            print_result(result)

        print("=" * 70)

    finally:

        # ====================================================
        # STOP ORDERBOOK TASKS
        # ====================================================

        for task in tasks:

            task.cancel()

        await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "\nТест остановлен пользователем."
        )