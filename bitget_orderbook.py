import asyncio
import json
import logging
import sys
import time

import requests
import websockets

from websockets.exceptions import ConnectionClosed

from config import BASE_URL_BITGET
from price_feeds.orderbook_models import OrderBook
from price_feeds.orderbook_cache import update_orderbook


logger = logging.getLogger(__name__)


# ============================================================
# CONFIG
# ============================================================

WS_URL = "wss://ws.bitget.com/v2/ws/public"

REST_URL = (
    f"{BASE_URL_BITGET}"
    "/api/v2/mix/market/merge-depth"
)

CHANNEL = "books"

PRODUCT_TYPE = "USDT-FUTURES"

DEPTH_LIMIT = 50

DISPLAY_LEVELS = 10

SNAPSHOT_TIMEOUT = 10

WS_TIMEOUT = 30

RECONNECT_DELAY = 5

PRINT_INTERVAL = 1.0


# ============================================================
# INTERNAL ORDER BOOK
# ============================================================

class BitgetLocalOrderBook:

    def __init__(
        self,
        symbol: str,
    ):

        self.symbol = symbol

        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}

        self.update_id = 0

        self.exchange_timestamp = 0

        self.received_at = 0

        self.received_at_ns = 0

        self.events = 0

        self.synced = False

    # ========================================================
    # LOAD SNAPSHOT
    # ========================================================

    def load_snapshot(
        self,
        bids: list,
        asks: list,
        timestamp: int,
    ) -> None:

        self.bids.clear()
        self.asks.clear()

        self._apply_levels(
            self.bids,
            bids,
        )

        self._apply_levels(
            self.asks,
            asks,
        )

        self.update_id = timestamp

        self.exchange_timestamp = timestamp

        self.received_at = int(
            time.time() * 1000
        )

        self.received_at_ns = time.time_ns()

        self.events = 0

        self.synced = True

        logger.info(
            "Bitget OrderBook %s: "
            "snapshot загружен: "
            "timestamp=%s bids=%d asks=%d",
            self.symbol,
            timestamp,
            len(self.bids),
            len(self.asks),
        )

    # ========================================================
    # APPLY UPDATE
    # ========================================================

    def apply_update(
        self,
        bids: list,
        asks: list,
        timestamp: int,
    ) -> None:

        if not self.synced:

            raise RuntimeError(
                "Нельзя применить update "
                "до snapshot"
            )

        self._apply_levels(
            self.bids,
            bids,
        )

        self._apply_levels(
            self.asks,
            asks,
        )

        self.update_id = timestamp

        self.exchange_timestamp = timestamp

        self.received_at = int(
            time.time() * 1000
        )

        self.received_at_ns = time.time_ns()

        self.events += 1

    # ========================================================
    # APPLY LEVELS
    # ========================================================

    @staticmethod
    def _apply_levels(
        book: dict[float, float],
        levels: list,
    ) -> None:

        for level in levels:

            if len(level) < 2:
                continue

            try:

                price = float(
                    level[0]
                )

                quantity = float(
                    level[1]
                )

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

    # ========================================================
    # BEST BID
    # ========================================================

    @property
    def best_bid(
        self,
    ) -> tuple[float, float] | None:

        if not self.bids:
            return None

        price = max(
            self.bids
        )

        return (
            price,
            self.bids[price],
        )

    # ========================================================
    # BEST ASK
    # ========================================================

    @property
    def best_ask(
        self,
    ) -> tuple[float, float] | None:

        if not self.asks:
            return None

        price = min(
            self.asks
        )

        return (
            price,
            self.asks[price],
        )

    # ========================================================
    # BUILD COMMON ORDERBOOK
    # ========================================================

    def to_common_orderbook(
        self,
    ) -> OrderBook:

        bids = sorted(
            self.bids.items(),
            reverse=True,
        )

        asks = sorted(
            self.asks.items()
        )

        return OrderBook(
            exchange="bitget",
            symbol=self.symbol,

            bids=bids,
            asks=asks,

            timestamp=self.exchange_timestamp,

            received_at=self.received_at,

            received_at_ns=self.received_at_ns,

            update_id=self.update_id,
        )

    # ========================================================
    # PRINT
    # ========================================================

    def print_book(
        self,
    ) -> None:

        best_bid = self.best_bid
        best_ask = self.best_ask

        if (
            best_bid is None
            or best_ask is None
        ):

            print(
                f"{self.symbol}: стакан пуст"
            )

            return

        # bid_price, _ = best_bid
        # ask_price, _ = best_ask

        # spread = (
        #     ask_price - bid_price
        # )

        # spread_percent = (
        #     spread / bid_price * 100
        #     if bid_price
        #     else 0
        # )

        # print()
        # print("=" * 50)

        # print(
        #     f"BITGET FUTURES ORDER BOOK: "
        #     f"{self.symbol}"
        # )

        # print(
        #     f"Update ID: {self.update_id}"
        # )

        # print(
        #     f"Events:    {self.events}"
        # )

        # print(
        #     f"Spread:    "
        #     f"{spread:.8f} "
        #     f"({spread_percent:.6f}%)"
        # )

        # print("-" * 50)

        # print("ASKS")

        # asks = sorted(
        #     self.asks.items()
        # )[:DISPLAY_LEVELS]

        # for price, quantity in reversed(
        #     asks
        # ):

        #     print(
        #         f"{price:>18.8f} "
        #         f"{quantity:>18.8f}"
        #     )

        # print("-" * 50)

        # print("BIDS")

        # bids = sorted(
        #     self.bids.items(),
        #     reverse=True,
        # )[:DISPLAY_LEVELS]

        # for price, quantity in bids:

        #     print(
        #         f"{price:>18.8f} "
        #         f"{quantity:>18.8f}"
        #     )

        # print("=" * 50)


# ============================================================
# PUBLISH TO COMMON CACHE
# ============================================================

def publish_orderbook(
    orderbook: BitgetLocalOrderBook,
) -> None:

    common_orderbook = (
        orderbook.to_common_orderbook()
    )

    update_orderbook(
        common_orderbook
    )


# ============================================================
# REST SNAPSHOT
# ============================================================

def get_snapshot_sync(
    symbol: str,
) -> dict:

    logger.info(
        "Bitget OrderBook %s: "
        "запрос REST snapshot...",
        symbol,
    )

    response = requests.get(
        REST_URL,
        params={
            "symbol": symbol,
            "productType": PRODUCT_TYPE,
            "limit": DEPTH_LIMIT,
        },
        timeout=SNAPSHOT_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    if data.get("code") != "00000":

        raise RuntimeError(
            f"Bitget snapshot error: "
            f"{data}"
        )

    snapshot = data.get(
        "data"
    )

    if not snapshot:

        raise RuntimeError(
            "Bitget snapshot is empty"
        )

    # merge-depth обычно возвращает
    # один объект.
    if isinstance(
        snapshot,
        list,
    ):

        snapshot = snapshot[0]

    return snapshot


async def get_snapshot(
    symbol: str,
) -> dict:

    return await asyncio.to_thread(
        get_snapshot_sync,
        symbol,
    )


# ============================================================
# PARSE TIMESTAMP
# ============================================================

def get_timestamp(
    payload: dict,
) -> int | None:

    timestamp = (
        payload.get("ts")
        or payload.get("timestamp")
    )

    if timestamp is None:
        return None

    try:

        return int(
            timestamp
        )

    except (
        TypeError,
        ValueError,
    ):

        return None


# ============================================================
# PARSE MESSAGE
# ============================================================

def parse_message(
    message: str,
) -> tuple[str, dict | None]:

    try:

        data = json.loads(
            message
        )

    except json.JSONDecodeError:

        logger.warning(
            "Bitget OrderBook: "
            "некорректный JSON"
        )

        return (
            "invalid",
            None,
        )

    # --------------------------------------------------------
    # SUBSCRIBE
    # --------------------------------------------------------

    event = data.get(
        "event"
    )

    if event == "subscribe":

        return (
            "subscribe",
            data,
        )

    # --------------------------------------------------------
    # ERROR
    # --------------------------------------------------------

    if event == "error":

        return (
            "error",
            data,
        )

    # --------------------------------------------------------
    # CHANNEL
    # --------------------------------------------------------

    arg = data.get(
        "arg"
    )

    if not isinstance(
        arg,
        dict,
    ):

        return (
            "unknown",
            None,
        )

    if arg.get(
        "channel"
    ) != CHANNEL:

        return (
            "unknown",
            None,
        )

    # --------------------------------------------------------
    # DATA
    # --------------------------------------------------------

    data_list = data.get(
        "data"
    )

    if not data_list:

        return (
            "unknown",
            None,
        )

    payload = data_list[0]

    if not isinstance(
        payload,
        dict,
    ):

        return (
            "unknown",
            None,
        )

    bids = payload.get(
        "bids",
        [],
    )

    asks = payload.get(
        "asks",
        [],
    )

    timestamp = get_timestamp(
        payload
    )

    if timestamp is None:

        logger.warning(
            "Bitget OrderBook: "
            "event без timestamp"
        )

        return (
            "unknown",
            None,
        )

    result = {
        "bids": bids,
        "asks": asks,
        "timestamp": timestamp,
    }

    # Bitget books:
    #
    # action=snapshot
    # action=update
    #
    # поэтому передаём action дальше.

    action = data.get(
        "action"
    )

    if action == "snapshot":

        return (
            "snapshot",
            result,
        )

    if action == "update":

        return (
            "update",
            result,
        )

    return (
        "unknown",
        result,
    )


# ============================================================
# SUBSCRIBE
# ============================================================

async def subscribe(
    ws,
    symbol: str,
) -> None:

    request = {
        "op": "subscribe",
        "args": [
            {
                "instType": PRODUCT_TYPE,
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
        "Bitget OrderBook %s: "
        "отправлена подписка books",
        symbol,
    )


# ============================================================
# CONNECT
# ============================================================

async def connect_ws(
    symbol: str,
):

    logger.info(
        "Bitget OrderBook %s: "
        "подключение WS: %s",
        symbol,
        WS_URL,
    )

    ws = await websockets.connect(
        WS_URL,
        ping_interval=None,
        ping_timeout=None,
        close_timeout=5,
        max_size=None,
    )

    logger.info(
        "Bitget OrderBook %s: "
        "WS подключен",
        symbol,
    )

    await subscribe(
        ws,
        symbol,
    )

    return ws


# ============================================================
# SNAPSHOT + BUFFER SYNC
# ============================================================

async def synchronize_orderbook(
    symbol: str,
    ws,
    first_event: dict,
) -> BitgetLocalOrderBook:

    logger.info(
        "Bitget OrderBook %s: "
        "первое WS событие получено: "
        "timestamp=%s. "
        "Запускаем snapshot.",
        symbol,
        first_event["timestamp"],
    )

    buffer = [
        first_event
    ]

    # --------------------------------------------------------
    # Запускаем REST snapshot параллельно.
    # --------------------------------------------------------

    snapshot_task = asyncio.create_task(
        get_snapshot(
            symbol
        )
    )

    # --------------------------------------------------------
    # Пока REST работает, продолжаем
    # получать WS events.
    # --------------------------------------------------------

    while not snapshot_task.done():

        try:

            message = await asyncio.wait_for(
                ws.recv(),
                timeout=1,
            )

        except asyncio.TimeoutError:

            continue

        action, payload = parse_message(
            message
        )

        if action in (
            "snapshot",
            "update",
        ) and payload is not None:

            buffer.append(
                payload
            )

    snapshot = await snapshot_task

    bids = snapshot.get(
        "bids",
        [],
    )

    asks = snapshot.get(
        "asks",
        [],
    )

    snapshot_timestamp = get_timestamp(
        snapshot
    )

    if snapshot_timestamp is None:

        raise RuntimeError(
            "Bitget snapshot "
            "не содержит timestamp"
        )

    logger.info(
        "Bitget OrderBook %s: "
        "snapshot получен: "
        "timestamp=%s bids=%d asks=%d",
        symbol,
        snapshot_timestamp,
        len(bids),
        len(asks),
    )

    orderbook = BitgetLocalOrderBook(
        symbol
    )

    orderbook.load_snapshot(
        bids=bids,
        asks=asks,
        timestamp=snapshot_timestamp,
    )

    # --------------------------------------------------------
    # Применяем только WS-события,
    # которые новее snapshot.
    #
    # В отличие от Binance здесь нет
    # полноценной sequence-связи.
    # --------------------------------------------------------

    applicable_events = [
        event
        for event in buffer
        if event["timestamp"]
        > snapshot_timestamp
    ]

    for event in applicable_events:

        orderbook.apply_update(
            bids=event["bids"],
            asks=event["asks"],
            timestamp=event["timestamp"],
        )

    orderbook.synced = True

    logger.info(
        "Bitget OrderBook %s: "
        "SYNC SUCCESS: timestamp=%s "
        "events=%d bids=%d asks=%d",
        symbol,
        orderbook.update_id,
        orderbook.events,
        len(orderbook.bids),
        len(orderbook.asks),
    )

    return orderbook


# ============================================================
# MAIN LOOP
# ============================================================

async def run_bitget_orderbook(
    symbol: str,
) -> None:

    symbol = symbol.upper()

    reconnect_delay = (
        RECONNECT_DELAY
    )

    while True:

        ws = None

        try:

            logger.info(
                "Bitget OrderBook %s: запуск",
                symbol,
            )

            ws = await connect_ws(
                symbol
            )

            # =================================================
            # WAIT FIRST EVENT
            # =================================================

            first_event = None

            while first_event is None:

                message = await asyncio.wait_for(
                    ws.recv(),
                    timeout=WS_TIMEOUT,
                )

                action, payload = parse_message(
                    message
                )

                if action == "error":

                    raise RuntimeError(
                        f"Bitget WS error: "
                        f"{payload}"
                    )

                if (
                    action == "snapshot"
                    and payload is not None
                ):

                    first_event = payload

                elif (
                    action == "update"
                    and payload is not None
                ):

                    first_event = payload

            # =================================================
            # SYNCHRONIZATION
            # =================================================

            orderbook = (
                await synchronize_orderbook(
                    symbol=symbol,
                    ws=ws,
                    first_event=first_event,
                )
            )

            logger.info(
                "Bitget OrderBook %s: "
                "локальный стакан готов",
                symbol,
            )

            # -------------------------------------------------
            # Первый publish
            # -------------------------------------------------

            publish_orderbook(
                orderbook
            )

            orderbook.print_book()

            reconnect_delay = (
                RECONNECT_DELAY
            )

            last_print = time.monotonic()

            # =================================================
            # LIVE LOOP
            # =================================================

            while True:

                message = await asyncio.wait_for(
                    ws.recv(),
                    timeout=WS_TIMEOUT,
                )

                action, payload = parse_message(
                    message
                )

                # ------------------------------------------------
                # Subscribe confirmation
                # ------------------------------------------------

                if action == "subscribe":

                    logger.info(
                        "Bitget OrderBook %s: "
                        "подписка подтверждена",
                        symbol,
                    )

                    continue

                # ------------------------------------------------
                # Error
                # ------------------------------------------------

                if action == "error":

                    raise RuntimeError(
                        f"Bitget WS error: "
                        f"{payload}"
                    )

                # ------------------------------------------------
                # Ignore irrelevant messages
                # ------------------------------------------------

                if (
                    action != "update"
                    or payload is None
                ):

                    continue

                timestamp = payload[
                    "timestamp"
                ]

                # ------------------------------------------------
                # Bitget does not provide the same
                # sequence semantics as Binance.
                #
                # Поэтому здесь не делаем
                # sequence-gap validation.
                #
                # Старое событие всё равно
                # не применяем.
                # ------------------------------------------------

                if (
                    timestamp
                    < orderbook.update_id
                ):

                    logger.debug(
                        "Bitget OrderBook %s: "
                        "старое событие: "
                        "timestamp=%s local=%s",
                        symbol,
                        timestamp,
                        orderbook.update_id,
                    )

                    continue

                orderbook.apply_update(
                    bids=payload["bids"],
                    asks=payload["asks"],
                    timestamp=timestamp,
                )

                # ------------------------------------------------
                # Publish to common cache
                # ------------------------------------------------

                publish_orderbook(
                    orderbook
                )

                # ------------------------------------------------
                # Console output
                # ------------------------------------------------

                now = time.monotonic()

                if (
                    now - last_print
                    >= PRINT_INTERVAL
                ):

                    orderbook.print_book()

                    last_print = now

        except asyncio.CancelledError:

            logger.info(
                "Bitget OrderBook %s: "
                "остановлено",
                symbol,
            )

            if ws is not None:

                await ws.close()

            raise

        except ConnectionClosed as exc:

            logger.warning(
                "Bitget OrderBook %s: "
                "WS закрыт: code=%s reason=%s",
                symbol,
                exc.code,
                exc.reason,
            )

        except Exception:

            logger.exception(
                "Bitget OrderBook %s: "
                "ошибка, выполняется resync",
                symbol,
            )

        finally:

            if ws is not None:

                try:

                    await ws.close()

                except Exception:

                    pass

        logger.info(
            "Bitget OrderBook %s: "
            "reconnect через %s сек.",
            symbol,
            reconnect_delay,
        )

        await asyncio.sleep(
            reconnect_delay
        )

        reconnect_delay = min(
            reconnect_delay * 2,
            60,
        )


# ============================================================
# MAIN
# ============================================================

async def main() -> None:

    if len(sys.argv) < 2:

        print(
            "Использование:"
        )

        print(
            "python -m "
            "price_feeds.bitget_orderbook "
            "BTCUSDT"
        )

        return

    symbol = (
        sys.argv[1]
        .upper()
    )

    # ========================================================
    # Нормализуем символ.
    #
    # BTCUSDT -> BTCUSDT
    #
    # BTC-USDT-SWAP -> BTCUSDT
    # ========================================================

    if symbol.endswith(
        "-USDT-SWAP"
    ):

        symbol = symbol.replace(
            "-USDT-SWAP",
            "USDT",
        )

    elif not symbol.endswith(
        "USDT"
    ):

        raise ValueError(
            f"Неподдерживаемый символ: "
            f"{symbol}"
        )

    await run_bitget_orderbook(
        symbol
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print(
            "\nBitget OrderBook: "
            "остановлено пользователем"
        )
