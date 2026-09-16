# import asyncio
# import logging
# import time

# from price_feeds.binance_orderbook import run_binance_orderbook
# from price_feeds.bitget_orderbook import run_bitget_orderbook, run_bitget_orderbooks
# from price_feeds.okx_orderbook import run_okx_orderbook

# from price_feeds.orderbook_cache import remove_orderbook


# logger = logging.getLogger(__name__)


# # Hot-book mode: orderbooks are started once and kept alive.
# HOT_ORDERBOOKS = True
# ORDERBOOK_IDLE_TIMEOUT_MS = 5_000


# class OrderBookManager:
#     def __init__(self):

#         self.tasks: dict[tuple[str, str], asyncio.Task] = {}

#         self.last_needed_ms: dict[tuple[str, str], int] = {}

#     @staticmethod
#     def normalize_symbol(exchange: str, symbol: str) -> str:

#         exchange = exchange.lower()
#         symbol = symbol.upper()

#         if exchange == "okx":
#             if symbol.endswith("-USDT-SWAP"):
#                 return symbol

#             if symbol.endswith("USDT"):
#                 base = symbol[:-4]
#                 return f"{base}-USDT-SWAP"

#         return symbol

#     def ensure_orderbook(self, exchange: str, symbol: str):

#         exchange = exchange.lower()
#         symbol = self.normalize_symbol(exchange, symbol)

#         key = (exchange, symbol)

#         now_ms = int(time.time() * 1000)
#         self.last_needed_ms[key] = now_ms

#         task = self.tasks.get(key)

#         if task is not None and not task.done():
#             return

#         if task is not None and task.done():
#             self.tasks.pop(key, None)

#         if exchange == "binance":
#             coroutine = run_binance_orderbook(symbol)

#         elif exchange == "bitget":
#             coroutine = run_bitget_orderbook(symbol)

#         elif exchange == "okx":
#             coroutine = run_okx_orderbook(symbol)

#         else:
#             logger.warning(
#                 "Unknown exchange for orderbook: %s %s",
#                 exchange,
#                 symbol,
#             )
#             return

#         task = asyncio.create_task(coroutine)

#         self.tasks[key] = task

#         # logger.info(
#         #     "ORDERBOOK START: %s %s",
#         #     exchange,
#         #     symbol,
#         # )

#     def ensure_pair(
#         self,
#         buy_exchange: str,
#         buy_symbol: str,
#         sell_exchange: str,
#         sell_symbol: str,
#     ):
        
#         self.ensure_orderbook(
#             buy_exchange,
#             buy_symbol,
#         )

#         self.ensure_orderbook(
#             sell_exchange,
#             sell_symbol,
#         )

#     # Bitget is started in small batches to avoid a burst of simultaneous
#     # WebSocket connections when the whole universe is warmed up.
#     BITGET_START_BATCH_SIZE = 5
#     BITGET_START_BATCH_DELAY = 0.5

#     async def start_all(
#         self,
#         exchange_symbols: dict[str, list[str]],
#     ) -> None:
#         """
#         Start all orderbooks required by the current market universe.

#         Bitget uses one shared WebSocket for the whole universe.
#         Binance and OKX keep their existing per-symbol tasks.
#         """
#         total = 0

#         for exchange in ("binance", "okx"):
#             for symbol in exchange_symbols.get(exchange, []):
#                 self.ensure_orderbook(exchange, symbol)
#                 total += 1

#         bitget_symbols = exchange_symbols.get("bitget", [])

#         if bitget_symbols:
#             task = asyncio.create_task(
#                 run_bitget_orderbooks(
#                     bitget_symbols
#                 )
#             )

#             self.tasks[("bitget", "__ALL__")] = task
#             self.last_needed_ms[("bitget", "__ALL__")] = int(
#                 time.time() * 1000
#             )

#             total += len(bitget_symbols)

#             # logger.info(
#             #     "HOT ORDERBOOKS: Bitget shared WS started: %d books",
#             #     len(bitget_symbols),
#             # )

#         # logger.info(
#         #     "HOT ORDERBOOKS STARTED: %d books",
#         #     total,
#         # )

#     def cleanup(self):
#         if HOT_ORDERBOOKS:
#             return

#         now_ms = int(time.time() * 1000)

#         for key, task in list(self.tasks.items()):

#             if task.done():
#                 self.tasks.pop(key, None)
#                 self.last_needed_ms.pop(key, None)

#                 exchange, symbol = key
#                 remove_orderbook(exchange, symbol)

#                 continue

#             last_needed = self.last_needed_ms.get(key)

#             if last_needed is None:
#                 continue

#             if now_ms - last_needed < ORDERBOOK_IDLE_TIMEOUT_MS:
#                 continue

#             exchange, symbol = key

#             logger.info(
#                 "ORDERBOOK STOP: %s %s",
#                 exchange,
#                 symbol,
#             )

#             task.cancel()

#             self.tasks.pop(key, None)
#             self.last_needed_ms.pop(key, None)

#             remove_orderbook(exchange, symbol)

#     async def shutdown(self):

#         tasks = list(self.tasks.values())

#         if not tasks:
#             return

#         logger.info(
#             "Stopping %d orderbook tasks",
#             len(tasks),
#         )

#         for task in tasks:
#             if not task.done():
#                 task.cancel()

#         await asyncio.gather(
#             *tasks,
#             return_exceptions=True,
#         )

#         self.tasks.clear()
#         self.last_needed_ms.clear()

#         logger.info("All orderbook tasks stopped")

#     def get_active_count(self) -> int:

#         return sum(
#             1
#             for task in self.tasks.values()
#             if not task.done()
#         )

import asyncio
import logging
import time

from price_feeds.binance_orderbook import run_binance_orderbook
from price_feeds.bitget_orderbook import run_bitget_orderbook, run_bitget_orderbooks
from price_feeds.okx_orderbook import run_okx_orderbook

from price_feeds.orderbook_cache import (
    get_exchange_orderbooks,
    remove_orderbook,
)


logger = logging.getLogger(__name__)


# Hot-book mode: orderbooks are started once and kept alive.
HOT_ORDERBOOKS = True
ORDERBOOK_IDLE_TIMEOUT_MS = 5_000


class OrderBookManager:
    def __init__(self):

        self.tasks: dict[tuple[str, str], asyncio.Task] = {}

        self.last_needed_ms: dict[tuple[str, str], int] = {}

        self.expected_symbols: dict[str, set[str]] = {
            "binance": set(),
            "bitget": set(),
            "okx": set(),
        }

    @staticmethod
    def normalize_symbol(exchange: str, symbol: str) -> str:

        exchange = exchange.lower()
        symbol = symbol.upper()

        if exchange == "okx":
            if symbol.endswith("-USDT-SWAP"):
                return symbol

            if symbol.endswith("USDT"):
                base = symbol[:-4]
                return f"{base}-USDT-SWAP"

        return symbol

    def ensure_orderbook(self, exchange: str, symbol: str):

        exchange = exchange.lower()
        symbol = self.normalize_symbol(exchange, symbol)

        key = (exchange, symbol)

        now_ms = int(time.time() * 1000)
        self.last_needed_ms[key] = now_ms

        task = self.tasks.get(key)

        if task is not None and not task.done():
            return

        if task is not None and task.done():
            self.tasks.pop(key, None)

        if exchange == "binance":
            coroutine = run_binance_orderbook(symbol)

        elif exchange == "bitget":
            coroutine = run_bitget_orderbook(symbol)

        elif exchange == "okx":
            coroutine = run_okx_orderbook(symbol)

        else:
            logger.warning(
                "Unknown exchange for orderbook: %s %s",
                exchange,
                symbol,
            )
            return

        task = asyncio.create_task(coroutine)

        self.tasks[key] = task

        # logger.info(
        #     "ORDERBOOK START: %s %s",
        #     exchange,
        #     symbol,
        # )

    def ensure_pair(
        self,
        buy_exchange: str,
        buy_symbol: str,
        sell_exchange: str,
        sell_symbol: str,
    ):
        
        self.ensure_orderbook(
            buy_exchange,
            buy_symbol,
        )

        self.ensure_orderbook(
            sell_exchange,
            sell_symbol,
        )

    # Bitget is started in small batches to avoid a burst of simultaneous
    # WebSocket connections when the whole universe is warmed up.
    BITGET_START_BATCH_SIZE = 5
    BITGET_START_BATCH_DELAY = 0.5

    async def start_all(
        self,
        exchange_symbols: dict[str, list[str]],
    ) -> None:
        """
        Start all orderbooks required by the current market universe.

        Bitget uses one shared WebSocket for the whole universe.
        Binance and OKX keep their existing per-symbol tasks.
        """
        total = 0

        self.expected_symbols = {
            "binance": {
                self.normalize_symbol("binance", symbol)
                for symbol in exchange_symbols.get("binance", [])
            },
            "bitget": {
                self.normalize_symbol("bitget", symbol)
                for symbol in exchange_symbols.get("bitget", [])
            },
            "okx": {
                self.normalize_symbol("okx", symbol)
                for symbol in exchange_symbols.get("okx", [])
            },
        }

        for exchange in ("binance", "okx"):
            for symbol in self.expected_symbols[exchange]:
                self.ensure_orderbook(exchange, symbol)
                total += 1

        bitget_symbols = list(self.expected_symbols["bitget"])

        if bitget_symbols:
            task = asyncio.create_task(
                run_bitget_orderbooks(
                    bitget_symbols
                )
            )

            self.tasks[("bitget", "__ALL__")] = task
            self.last_needed_ms[("bitget", "__ALL__")] = int(
                time.time() * 1000
            )

            total += len(bitget_symbols)

            # logger.info(
            #     "HOT ORDERBOOKS: Bitget shared WS started: %d books",
            #     len(bitget_symbols),
            # )

        # logger.info(
        #     "HOT ORDERBOOKS STARTED: %d books",
        #     total,
        # )

        await self.wait_until_all_ready()

    async def wait_until_all_ready(self) -> None:
        """
        Wait until every required orderbook has published a live local book.

        A book is considered ready only after it exists in the common cache
        with non-empty bids and asks. This means the exchange-specific
        snapshot/synchronization has completed.
        """
        if not any(self.expected_symbols.values()):
            return

        logged_progress = {
            "binance": False,
            "bitget": False,
            "okx": False,
        }

        while True:
            ready_counts: dict[str, int] = {}
            all_ready = True

            for exchange, symbols in self.expected_symbols.items():
                books = get_exchange_orderbooks(exchange)
                ready = sum(
                    1
                    for symbol in symbols
                    if (
                        (book := books.get(symbol)) is not None
                        and bool(book.bids)
                        and bool(book.asks)
                    )
                )
                ready_counts[exchange] = ready

                if ready < len(symbols):
                    all_ready = False

            if all_ready:
                logger.info(
                    "ORDERBOOKS READY | Binance %d/%d | Bitget %d/%d | OKX %d/%d",
                    ready_counts["binance"],
                    len(self.expected_symbols["binance"]),
                    ready_counts["bitget"],
                    len(self.expected_symbols["bitget"]),
                    ready_counts["okx"],
                    len(self.expected_symbols["okx"]),
                )
                return

            for exchange in ("binance", "bitget", "okx"):
                expected = len(self.expected_symbols[exchange])
                ready = ready_counts[exchange]

                if expected and ready == expected and not logged_progress[exchange]:
                    logger.info(
                        "ORDERBOOKS %s READY | %d/%d",
                        exchange.capitalize(),
                        ready,
                        expected,
                    )
                    logged_progress[exchange] = True

            await asyncio.sleep(0.05)

    def cleanup(self):
        if HOT_ORDERBOOKS:
            return

        now_ms = int(time.time() * 1000)

        for key, task in list(self.tasks.items()):

            if task.done():
                self.tasks.pop(key, None)
                self.last_needed_ms.pop(key, None)

                exchange, symbol = key
                remove_orderbook(exchange, symbol)

                continue

            last_needed = self.last_needed_ms.get(key)

            if last_needed is None:
                continue

            if now_ms - last_needed < ORDERBOOK_IDLE_TIMEOUT_MS:
                continue

            exchange, symbol = key

            logger.info(
                "ORDERBOOK STOP: %s %s",
                exchange,
                symbol,
            )

            task.cancel()

            self.tasks.pop(key, None)
            self.last_needed_ms.pop(key, None)

            remove_orderbook(exchange, symbol)

    async def shutdown(self):

        tasks = list(self.tasks.values())

        if not tasks:
            return

        logger.info(
            "Stopping %d orderbook tasks",
            len(tasks),
        )

        for task in tasks:
            if not task.done():
                task.cancel()

        await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        self.tasks.clear()
        self.last_needed_ms.clear()

        logger.info("All orderbook tasks stopped")

    def get_active_count(self) -> int:

        return sum(
            1
            for task in self.tasks.values()
            if not task.done()
        )