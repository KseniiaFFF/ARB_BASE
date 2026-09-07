import asyncio
import json
import logging
import sys
import time
from collections import deque
from dataclasses import dataclass, field

import requests
import websockets


from price_feeds.orderbook_models import OrderBook
from price_feeds.orderbook_cache import update_orderbook


logger = logging.getLogger(__name__)


WS_URL = "wss://fstream.binance.com/ws"
REST_URL = "https://fapi.binance.com/fapi/v1/depth"

DEPTH_LIMIT = 1000

SNAPSHOT_TIMEOUT = 5
RECONNECT_DELAY = 2

MAX_LOCAL_LEVELS = 1000
PRINT_INTERVAL = 1.0


@dataclass(slots=True)
class DepthEvent:

    event_time: int
    transaction_time: int

    first_update_id: int
    final_update_id: int
    previous_final_update_id: int

    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]



@dataclass
class BinanceOrderBook:

    symbol: str

    bids: dict[float, float] = field(
        default_factory=dict
    )

    asks: dict[float, float] = field(
        default_factory=dict
    )

    last_update_id: int = 0

    synced: bool = False

    event_count: int = 0

    last_event_time: int = 0

    last_received_at: int = 0

    last_received_at_ns: int = 0


def parse_depth_event(
    message: str,
) -> DepthEvent | None:

    data = json.loads(message)

    if data.get("e") != "depthUpdate":
        return None

    try:

        event_time = int(data["E"])
        transaction_time = int(data["T"])

        first_update_id = int(data["U"])
        final_update_id = int(data["u"])
        previous_final_update_id = int(data["pu"])

        bids = [
            (
                float(price),
                float(quantity),
            )
            for price, quantity in data.get("b", [])
        ]

        asks = [
            (
                float(price),
                float(quantity),
            )
            for price, quantity in data.get("a", [])
        ]

    except (
        KeyError,
        TypeError,
        ValueError,
    ):

        logger.exception(
            "Binance OrderBook: "
            "ошибка разбора depth event"
        )

        return None

    return DepthEvent(

        event_time=event_time,

        transaction_time=transaction_time,

        first_update_id=first_update_id,

        final_update_id=final_update_id,

        previous_final_update_id=(
            previous_final_update_id
        ),

        bids=bids,

        asks=asks,
    )


def apply_levels(
    levels: dict[float, float],
    updates: list[tuple[float, float]],
) -> None:

    for price, quantity in updates:

        if quantity == 0:

            levels.pop(
                price,
                None,
            )

        else:

            levels[price] = quantity


def apply_update(
    orderbook: BinanceOrderBook,
    event: DepthEvent,
) -> None:

    apply_levels(
        orderbook.bids,
        event.bids,
    )

    apply_levels(
        orderbook.asks,
        event.asks,
    )

    orderbook.last_update_id = (
        event.final_update_id
    )

    orderbook.last_event_time = (
        event.event_time
    )

    orderbook.last_received_at = (
        int(time.time() * 1000)
    )

    orderbook.last_received_at_ns = (
        time.time_ns()
    )

    orderbook.event_count += 1


def trim_orderbook(
    orderbook: BinanceOrderBook,
) -> None:

    if len(orderbook.bids) > MAX_LOCAL_LEVELS:

        best_bids = sorted(
            orderbook.bids,
            reverse=True,
        )[:MAX_LOCAL_LEVELS]

        orderbook.bids = {
            price: orderbook.bids[price]
            for price in best_bids
        }

    if len(orderbook.asks) > MAX_LOCAL_LEVELS:

        best_asks = sorted(
            orderbook.asks
        )[:MAX_LOCAL_LEVELS]

        orderbook.asks = {
            price: orderbook.asks[price]
            for price in best_asks
        }


def apply_live_event(
    orderbook: BinanceOrderBook,
    event: DepthEvent,
) -> None:

    if not orderbook.synced:

        raise RuntimeError(
            "Cannot apply live event: "
            "order book is not synchronized"
        )

    local_id = (
        orderbook.last_update_id
    )

    if (
        event.previous_final_update_id
        != local_id
    ):

        raise RuntimeError(
            "Binance order book sequence gap: "
            f"local={local_id}, "
            f"pu={event.previous_final_update_id}, "
            f"U={event.first_update_id}, "
            f"u={event.final_update_id}"
        )

    apply_update(
        orderbook,
        event,
    )

    trim_orderbook(
        orderbook
    )


def get_snapshot_sync(
    symbol: str,
) -> dict:

    response = requests.get(
        REST_URL,

        params={
            "symbol": symbol,
            "limit": DEPTH_LIMIT,
        },

        timeout=SNAPSHOT_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    if "lastUpdateId" not in data:

        raise RuntimeError(
            "Binance snapshot "
            "не содержит lastUpdateId"
        )

    return data


async def get_snapshot(
    symbol: str,
) -> dict:

    logger.info(
        "Binance OrderBook %s: "
        "запрос REST snapshot...",
        symbol,
    )

    snapshot = await asyncio.to_thread(
        get_snapshot_sync,
        symbol,
    )

    logger.info(
        "Binance OrderBook %s: "
        "snapshot получен: "
        "lastUpdateId=%s, bids=%d, asks=%d",

        symbol,

        snapshot["lastUpdateId"],

        len(
            snapshot.get(
                "bids",
                [],
            )
        ),

        len(
            snapshot.get(
                "asks",
                [],
            )
        ),
    )

    return snapshot


def apply_snapshot(
    orderbook: BinanceOrderBook,
    snapshot: dict,
) -> None:

    orderbook.bids.clear()
    orderbook.asks.clear()

    for price, quantity in snapshot.get(
        "bids",
        [],
    ):

        price = float(price)
        quantity = float(quantity)

        if quantity > 0:

            orderbook.bids[price] = quantity

    for price, quantity in snapshot.get(
        "asks",
        [],
    ):

        price = float(price)
        quantity = float(quantity)

        if quantity > 0:

            orderbook.asks[price] = quantity

    orderbook.last_update_id = int(
        snapshot["lastUpdateId"]
    )

    orderbook.synced = False

    orderbook.event_count = 0

    orderbook.last_event_time = 0

    orderbook.last_received_at = 0

    orderbook.last_received_at_ns = 0

    trim_orderbook(
        orderbook
    )


def synchronize_from_buffer(
    orderbook: BinanceOrderBook,
    snapshot: dict,
    event_buffer: deque[DepthEvent],
) -> None:

    snapshot_id = int(
        snapshot["lastUpdateId"]
    )

    logger.info(
        "Binance OrderBook %s: "
        "начинаем синхронизацию: "
        "snapshot=%d, buffer=%d",

        orderbook.symbol,

        snapshot_id,

        len(event_buffer),
    )

    apply_snapshot(
        orderbook,
        snapshot,
    )


    while event_buffer:

        event = event_buffer[0]

        if event.final_update_id <= snapshot_id:

            event_buffer.popleft()

        else:

            break

    if not event_buffer:

        raise RuntimeError(
            "Buffer пуст после snapshot"
        )


    first_event_index = None

    for index, event in enumerate(
        event_buffer
    ):

        if (
            event.first_update_id
            <= snapshot_id + 1
            <= event.final_update_id
        ):

            first_event_index = index

            break

    if first_event_index is None:

        first = event_buffer[0]

        raise RuntimeError(
            "Не найдено событие "
            "для стыковки snapshot: "

            f"snapshot={snapshot_id}, "

            f"first_buffer_U="
            f"{first.first_update_id}, "

            f"first_buffer_u="
            f"{first.final_update_id}"
        )


    for _ in range(
        first_event_index
    ):

        event_buffer.popleft()

    first_event = event_buffer.popleft()

    logger.info(
        "Binance OrderBook %s: "
        "найдено первое событие для sync: "
        "U=%d u=%d pu=%d",

        orderbook.symbol,

        first_event.first_update_id,

        first_event.final_update_id,

        first_event.previous_final_update_id,
    )


    if not (
        first_event.first_update_id
        <= snapshot_id + 1
        <= first_event.final_update_id
    ):

        raise RuntimeError(
            "Первое событие "
            "не покрывает snapshot + 1"
        )

    apply_update(
        orderbook,
        first_event,
    )

    for event in event_buffer:

        if (
            event.previous_final_update_id
            != orderbook.last_update_id
        ):

            raise RuntimeError(
                "Gap во время snapshot sync: "

                f"local="
                f"{orderbook.last_update_id}, "

                f"pu="
                f"{event.previous_final_update_id}, "

                f"U="
                f"{event.first_update_id}, "

                f"u="
                f"{event.final_update_id}"
            )

        apply_update(
            orderbook,
            event,
        )

    event_buffer.clear()

    orderbook.synced = True

    trim_orderbook(
        orderbook
    )

    logger.info(
        "Binance OrderBook %s: "
        "SYNC SUCCESS: "
        "lastUpdateId=%d "
        "bids=%d "
        "asks=%d",

        orderbook.symbol,

        orderbook.last_update_id,

        len(orderbook.bids),

        len(orderbook.asks),
    )


def get_best_bid(
    orderbook: BinanceOrderBook,
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
    orderbook: BinanceOrderBook,
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


def build_common_orderbook(
    orderbook: BinanceOrderBook,
) -> OrderBook:

    bids = sorted(
        orderbook.bids.items(),
        key=lambda x: x[0],
        reverse=True,
    )[:MAX_LOCAL_LEVELS]

    asks = sorted(
        orderbook.asks.items(),
        key=lambda x: x[0],
    )[:MAX_LOCAL_LEVELS]

    return OrderBook(

        exchange="binance",

        symbol=orderbook.symbol,

        bids=bids,

        asks=asks,

        timestamp=orderbook.last_event_time,

        received_at=orderbook.last_received_at,

        received_at_ns=(
            orderbook.last_received_at_ns
        ),

        # ВАЖНО:
        # это поле есть в общей модели OrderBook.
        update_id=orderbook.last_update_id,
    )


def publish_orderbook(
    orderbook: BinanceOrderBook,
) -> None:

    common_orderbook = (
        build_common_orderbook(
            orderbook
        )
    )

    update_orderbook(
        common_orderbook
    )


def print_orderbook(
    orderbook: BinanceOrderBook,
    levels: int = 10,
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


async def run_binance_orderbook(
    symbol: str,
) -> None:

    symbol = symbol.upper()

    logger.info(
        "Binance OrderBook %s: запуск",
        symbol,
    )

    while True:

        orderbook = BinanceOrderBook(
            symbol=symbol
        )

        event_buffer: deque[
            DepthEvent
        ] = deque()

        try:

            ws_url = (
                f"{WS_URL}/"
                f"{symbol.lower()}@depth@100ms"
            )

            logger.info(
                "Binance OrderBook %s: "
                "подключение WS: %s",

                symbol,

                ws_url,
            )

            async with websockets.connect(
                ws_url,

                ping_interval=20,

                ping_timeout=20,

                close_timeout=5,

                max_size=None,
            ) as ws:

                logger.info(
                    "Binance OrderBook %s: "
                    "WS подключен",
                    symbol,
                )

                snapshot_task = None

                synced = False

                last_print_time = 0.0

                async for message in ws:

                    try:

                        event = parse_depth_event(
                            message
                        )

                    except json.JSONDecodeError:

                        logger.warning(
                            "Binance OrderBook %s: "
                            "некорректный JSON",
                            symbol,
                        )

                        continue

                    if event is None:
                        continue


                    if not synced:

                        event_buffer.append(
                            event
                        )

                        if snapshot_task is None:

                            logger.info(
                                "Binance OrderBook %s: "
                                "первое WS событие получено: "
                                "U=%d u=%d pu=%d. "
                                "Запускаем snapshot.",

                                symbol,

                                event.first_update_id,

                                event.final_update_id,

                                event.previous_final_update_id,
                            )

                            snapshot_task = (
                                asyncio.create_task(
                                    get_snapshot(
                                        symbol
                                    )
                                )
                            )

                        if (
                            snapshot_task.done()
                        ):

                            snapshot = (
                                snapshot_task.result()
                            )

                            synchronize_from_buffer(
                                orderbook,

                                snapshot,

                                event_buffer,
                            )

                            synced = True

                            logger.info(
                                "Binance OrderBook %s: "
                                "локальный стакан готов",
                                symbol,
                            )

                            publish_orderbook(
                                orderbook
                            )

                            print_orderbook(
                                orderbook,
                                levels=10,
                            )

                            last_print_time = (
                                time.monotonic()
                            )

                            continue


                    else:

                        apply_live_event(
                            orderbook,
                            event,
                        )


                        publish_orderbook(
                            orderbook
                        )

                        now = time.monotonic()

                        if (
                            now - last_print_time
                            >= PRINT_INTERVAL
                        ):

                            print_orderbook(
                                orderbook,
                                levels=10,
                            )

                            last_print_time = now

        except asyncio.CancelledError:

            logger.info(
                "Binance OrderBook %s: "
                "остановлено",
                symbol,
            )

            raise

        except Exception:

            logger.exception(
                "Binance OrderBook %s: "
                "ошибка, выполняется "
                "полный resync",
                symbol,
            )

        await asyncio.sleep(
            RECONNECT_DELAY
        )

        logger.info(
            "Binance OrderBook %s: "
            "повторное подключение",
            symbol,
        )


async def main() -> None:

    if len(sys.argv) < 2:

        print(
            "Использование:"
        )

        print(
            "python -m "
            "price_feeds.binance_orderbook BTCUSDT"
        )

        return

    symbol = sys.argv[1]

    await run_binance_orderbook(
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
            "\nBinance OrderBook: "
            "остановлено пользователем"
        )
