import asyncio
import json
import logging
import sys
import time

import websockets
from websockets.exceptions import ConnectionClosed

from price_feeds.orderbook_models import OrderBook
from price_feeds.orderbook_cache import update_orderbook


logger = logging.getLogger(__name__)


WS_URL = "wss://ws.okx.com:8443/ws/v5/public"

CHANNEL = "books"

PRINT_LEVELS = 10
PRINT_INTERVAL = 1.0

RECONNECT_DELAY = 2
MAX_RECONNECT_DELAY = 60


class OKXLocalOrderBook:

    def __init__(
        self,
        symbol: str,
    ) -> None:

        self.symbol = symbol

        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}

        self.seq_id: int | None = None

        self.events = 0

        self.synced = False

        self.last_timestamp = 0
        self.last_received_at = 0
        self.last_received_at_ns = 0

        self.last_print = 0.0


    def load_snapshot(
        self,
        data: dict,
    ) -> None:

        self.bids.clear()
        self.asks.clear()

        for level in data.get(
            "bids",
            [],
        ):

            if len(level) < 2:
                continue

            try:

                price = float(level[0])
                quantity = float(level[1])

            except (
                TypeError,
                ValueError,
            ):

                continue

            if quantity > 0:

                self.bids[price] = quantity

        for level in data.get(
            "asks",
            [],
        ):

            if len(level) < 2:
                continue

            try:

                price = float(level[0])
                quantity = float(level[1])

            except (
                TypeError,
                ValueError,
            ):

                continue

            if quantity > 0:

                self.asks[price] = quantity

        seq_id = data.get(
            "seqId"
        )

        if seq_id is None:

            raise RuntimeError(
                f"OKX OrderBook {self.symbol}: "
                "snapshot не содержит seqId"
            )

        self.seq_id = int(
            seq_id
        )

        timestamp = data.get(
            "ts"
        )

        if timestamp is not None:

            try:

                self.last_timestamp = int(
                    timestamp
                )

            except (
                TypeError,
                ValueError,
            ):

                self.last_timestamp = 0

        self.last_received_at_ns = (
            time.time_ns()
        )

        self.last_received_at = (
            self.last_received_at_ns // 1_000_000
        )

        self.events = 1
        self.synced = True

        logger.info(
            "OKX OrderBook %s: "
            "snapshot загружен: "
            "seqId=%d bids=%d asks=%d",
            self.symbol,
            self.seq_id,
            len(self.bids),
            len(self.asks),
        )


    def apply_update(
        self,
        data: dict,
    ) -> None:

        if not self.synced:

            raise RuntimeError(
                "Update получен до snapshot"
            )

        previous_seq_id = data.get(
            "prevSeqId"
        )

        new_seq_id = data.get(
            "seqId"
        )

        if (
            previous_seq_id is None
            or new_seq_id is None
        ):

            raise RuntimeError(
                f"OKX OrderBook {self.symbol}: "
                "update не содержит seqId/prevSeqId"
            )

        previous_seq_id = int(
            previous_seq_id
        )

        new_seq_id = int(
            new_seq_id
        )


        if previous_seq_id != self.seq_id:

            logger.error(
                "OKX OrderBook %s: "
                "sequence gap: "
                "local=%s prevSeqId=%s seqId=%s",
                self.symbol,
                self.seq_id,
                previous_seq_id,
                new_seq_id,
            )

            raise RuntimeError(
                "OKX OrderBook sequence gap"
            )


        if new_seq_id < self.seq_id:

            logger.error(
                "OKX OrderBook %s: "
                "sequence reset: "
                "local=%s prevSeqId=%s seqId=%s",
                self.symbol,
                self.seq_id,
                previous_seq_id,
                new_seq_id,
            )

            raise RuntimeError(
                "OKX OrderBook sequence reset"
            )


        apply_levels(
            self.bids,
            data.get(
                "bids",
                [],
            ),
        )


        apply_levels(
            self.asks,
            data.get(
                "asks",
                [],
            ),
        )


        self.seq_id = new_seq_id

        timestamp = data.get(
            "ts"
        )

        if timestamp is not None:

            try:

                self.last_timestamp = int(
                    timestamp
                )

            except (
                TypeError,
                ValueError,
            ):

                pass

        self.last_received_at_ns = (
            time.time_ns()
        )

        self.last_received_at = (
            self.last_received_at_ns // 1_000_000
        )

        self.events += 1


def apply_levels(
    book: dict[float, float],
    levels: list,
) -> None:

    for level in levels:

        if len(level) < 2:
            continue

        try:

            price = float(level[0])
            quantity = float(level[1])

        except (
            TypeError,
            ValueError,
        ):

            continue

        if quantity == 0:

            book.pop(
                price,
                None,
            )

        else:

            book[price] = quantity


def build_common_orderbook(
    orderbook: OKXLocalOrderBook,
) -> OrderBook:

    if orderbook.seq_id is None:

        raise RuntimeError(
            "Cannot build common OrderBook "
            "without seq_id"
        )

    return OrderBook(
        exchange="okx",
        symbol=orderbook.symbol,

        bids=sorted(
            orderbook.bids.items(),
            reverse=True,
        ),

        asks=sorted(
            orderbook.asks.items()
        ),

        timestamp=orderbook.last_timestamp,

        received_at=orderbook.last_received_at,

        received_at_ns=orderbook.last_received_at_ns,

        update_id=orderbook.seq_id,
    )


def publish_orderbook(
    orderbook: OKXLocalOrderBook,
) -> None:

    common_orderbook = (
        build_common_orderbook(
            orderbook
        )
    )

    update_orderbook(
        common_orderbook
    )


def get_best_bid(
    orderbook: OKXLocalOrderBook,
) -> tuple[float, float] | None:

    if not orderbook.bids:
        return None

    price = max(
        orderbook.bids
    )

    return (
        price,
        orderbook.bids[price],
    )


def get_best_ask(
    orderbook: OKXLocalOrderBook,
) -> tuple[float, float] | None:

    if not orderbook.asks:
        return None

    price = min(
        orderbook.asks
    )

    return (
        price,
        orderbook.asks[price],
    )


def print_orderbook(
    orderbook: OKXLocalOrderBook,
) -> None:

    if not orderbook.synced:

        print(
            f"{orderbook.symbol}: "
            "NOT SYNCED"
        )

        return

    best_bid = get_best_bid(
        orderbook
    )

    best_ask = get_best_ask(
        orderbook
    )

    if not best_bid or not best_ask:

        print(
            f"{orderbook.symbol}: "
            "стакан пуст"
        )

        return


def should_print(
    orderbook: OKXLocalOrderBook,
) -> bool:

    now = time.monotonic()

    if (
        now - orderbook.last_print
        >= PRINT_INTERVAL
    ):

        orderbook.last_print = now

        return True

    return False


def parse_message(
    message: str,
) -> tuple[str, dict | None]:

    try:

        data = json.loads(
            message
        )

    except json.JSONDecodeError:

        logger.warning(
            "OKX OrderBook: "
            "некорректный JSON"
        )

        return (
            "invalid",
            None,
        )


    event = data.get(
        "event"
    )

    if event:

        return (
            event,
            data,
        )


    arg = data.get(
        "arg"
    )

    if not arg:

        return (
            "unknown",
            data,
        )

    channel = arg.get(
        "channel"
    )

    if channel != CHANNEL:

        return (
            "unknown",
            data,
        )


    action = data.get(
        "action"
    )

    if action not in (
        "snapshot",
        "update",
    ):

        return (
            "unknown",
            data,
        )

    payload = data.get(
        "data"
    )

    if not payload:

        return (
            action,
            None,
        )

    return (
        action,
        payload[0],
    )


async def subscribe(
    ws,
    symbol: str,
) -> None:

    request = {
        "op": "subscribe",
        "args": [
            {
                "channel": CHANNEL,
                "instId": symbol,
            }
        ],
    }

    await ws.send(
        json.dumps(
            request
        )
    )

    logger.info(
        "OKX OrderBook %s: "
        "отправлена подписка books",
        symbol,
    )


async def run_okx_orderbook(
    symbol: str,
) -> None:

    symbol = symbol.upper()

    logger.info(
        "OKX OrderBook %s: запуск",
        symbol,
    )

    reconnect_delay = RECONNECT_DELAY

    while True:

        orderbook = (
            OKXLocalOrderBook(
                symbol
            )
        )

        try:

            logger.info(
                "OKX OrderBook %s: "
                "подключение WS: %s",
                symbol,
                WS_URL,
            )

            async with websockets.connect(
                WS_URL,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=None,
            ) as ws:

                logger.info(
                    "OKX OrderBook %s: "
                    "WS подключен",
                    symbol,
                )

                reconnect_delay = (
                    RECONNECT_DELAY
                )

                await subscribe(
                    ws,
                    symbol,
                )


                async for message in ws:

                    action, payload = (
                        parse_message(
                            message
                        )
                    )


                    if action == "subscribe":

                        logger.info(
                            "OKX OrderBook %s: "
                            "подписка подтверждена",
                            symbol,
                        )

                        continue


                    if action == "error":

                        logger.error(
                            "OKX OrderBook %s: "
                            "WS error: %s",
                            symbol,
                            payload,
                        )

                        raise RuntimeError(
                            f"OKX WS error: {payload}"
                        )

                    if payload is None:
                        continue


                    if action == "snapshot":

                        logger.info(
                            "OKX OrderBook %s: "
                            "получен WS snapshot",
                            symbol,
                        )

                        orderbook.load_snapshot(
                            payload
                        )

                        publish_orderbook(
                            orderbook
                        )

                        logger.info(
                            "OKX OrderBook %s: "
                            "локальный стакан готов: "
                            "update_id=%d bids=%d asks=%d",
                            symbol,
                            orderbook.seq_id,
                            len(orderbook.bids),
                            len(orderbook.asks),
                        )

                        print_orderbook(
                            orderbook
                        )

                        continue


                    if action == "update":

                        orderbook.apply_update(
                            payload
                        )

                        publish_orderbook(
                            orderbook
                        )

                        if should_print(
                            orderbook
                        ):

                            print_orderbook(
                                orderbook
                            )

        except asyncio.CancelledError:

            logger.info(
                "OKX OrderBook %s: "
                "остановлено",
                symbol,
            )

            raise

        except ConnectionClosed as exc:

            logger.warning(
                "OKX OrderBook %s: "
                "соединение закрыто: "
                "code=%s reason=%s",
                symbol,
                exc.code,
                exc.reason,
            )

        except Exception:

            logger.exception(
                "OKX OrderBook %s: "
                "ошибка, выполняется reconnect",
                symbol,
            )

        logger.info(
            "OKX OrderBook %s: "
            "reconnect через %d сек.",
            symbol,
            reconnect_delay,
        )

        await asyncio.sleep(
            reconnect_delay
        )

        reconnect_delay = min(
            reconnect_delay * 2,
            MAX_RECONNECT_DELAY,
        )


def convert_symbol(
    input_symbol: str,
) -> str:

    input_symbol = (
        input_symbol.upper()
    )

    if input_symbol.endswith(
        "-USDT-SWAP"
    ):

        return input_symbol

    if input_symbol.endswith(
        "USDT"
    ):

        asset = input_symbol[:-4]

        return (
            f"{asset}-USDT-SWAP"
        )

    raise ValueError(
        f"Неподдерживаемый символ: "
        f"{input_symbol}"
    )


async def main() -> None:

    if len(sys.argv) < 2:

        print(
            "Использование:"
        )

        print(
            "python -m "
            "price_feeds.okx_orderbook "
            "BTCUSDT"
        )

        return

    input_symbol = sys.argv[1]

    symbol = convert_symbol(
        input_symbol
    )

    await run_okx_orderbook(
        symbol
    )


if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s - "
            "%(levelname)s - "
            "%(message)s"
        ),
    )

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "\nOKX OrderBook: "
            "остановлено пользователем"
        )