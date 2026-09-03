import asyncio
import logging
import time

from price_feeds.binance_orderbook import run_binance_orderbook
from price_feeds.bitget_orderbook import run_bitget_orderbook
from price_feeds.okx_orderbook import run_okx_orderbook

from price_feeds.orderbook_cache import remove_orderbook


logger = logging.getLogger(__name__)


# Сколько времени держать стакан после того,
# как связка перестала проходить MIN_PERCENT.
#
# Это нужно, чтобы стаканы не запускались/останавливались
# постоянно при колебании спреда около MIN_PERCENT.
ORDERBOOK_IDLE_TIMEOUT_MS = 5_000


class OrderBookManager:
    def __init__(self):
        # (exchange, symbol) -> asyncio.Task
        self.tasks: dict[tuple[str, str], asyncio.Task] = {}

        # Последнее время, когда этот стакан был нужен
        self.last_needed_ms: dict[tuple[str, str], int] = {}

    @staticmethod
    def normalize_symbol(exchange: str, symbol: str) -> str:
        """
        Приводит символ к формату, который ожидает конкретная биржа.
        """

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
        """
        Запускает стакан, если он ещё не запущен.

        Если стакан уже работает — ничего не делает,
        только обновляет время его последнего использования.
        """

        exchange = exchange.lower()
        symbol = self.normalize_symbol(exchange, symbol)

        key = (exchange, symbol)

        now_ms = int(time.time() * 1000)
        self.last_needed_ms[key] = now_ms

        task = self.tasks.get(key)

        # Уже запущен
        if task is not None and not task.done():
            return

        # Если старый task завершился — удаляем его
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

        logger.info(
            "ORDERBOOK START: %s %s",
            exchange,
            symbol,
        )

    def ensure_pair(
        self,
        buy_exchange: str,
        buy_symbol: str,
        sell_exchange: str,
        sell_symbol: str,
    ):
        """
        Запускает оба стакана, необходимые для арбитражной связки.

        Например:

        Binance BTCUSDT -> OKX BTCUSDT

        запустит:

        Binance BTCUSDT
        OKX BTC-USDT-SWAP

        Если они уже работают — повторно ничего не запускается.
        """

        self.ensure_orderbook(
            buy_exchange,
            buy_symbol,
        )

        self.ensure_orderbook(
            sell_exchange,
            sell_symbol,
        )

    def cleanup(self):
        """
        Останавливает стаканы, которые давно не использовались.
        """

        now_ms = int(time.time() * 1000)

        for key, task in list(self.tasks.items()):

            # Уже завершившийся task
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
        """
        Корректно останавливает все стаканы при завершении программы.
        """

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
        """
        Количество работающих стаканов.
        """

        return sum(
            1
            for task in self.tasks.values()
            if not task.done()
        )