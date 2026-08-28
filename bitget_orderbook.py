import asyncio
import json
import logging
import sys
import time

import requests
import websockets

from websockets.exceptions import ConnectionClosed

from config import BASE_URL_BITGET


logger = logging.getLogger(__name__)


# ============================================================
# CONFIG
# ============================================================

WS_URL = "wss://ws.bitget.com/v2/ws/public"

DEPTH_LIMIT = 50
DISPLAY_LEVELS = 10

SNAPSHOT_TIMEOUT = 10
WS_TIMEOUT = 30

RECONNECT_DELAY = 5


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


# ============================================================
# EXCEPTIONS
# ============================================================

class OrderBookSyncError(Exception):
    pass


# ============================================================
# ORDER BOOK
# ============================================================

class OrderBook:

    def __init__(self, symbol: str):

        self.symbol = symbol

        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}

        self.last_update_id = 0

        self.events_applied = 0

        self.synced = False

    # --------------------------------------------------------
    # Snapshot
    # --------------------------------------------------------

    def load_snapshot(
        self,
        bids: list[list[str]],
        asks: list[list[str]],
        update_id: int,
    ):

        logger.info(
            "Bitget OrderBook %s: загрузка snapshot",
            self.symbol,
        )

        self.bids.clear()
        self.asks.clear()

        for level in bids:

            if len(level) < 2:
                continue

            price = float(level[0])
            quantity = float(level[1])

            if quantity > 0:
                self.bids[price] = quantity

        for level in asks:

            if len(level) < 2:
                continue

            price = float(level[0])
            quantity = float(level[1])

            if quantity > 0:
                self.asks[price] = quantity

        self.last_update_id = update_id

        self.events_applied = 0

        logger.info(
            "Bitget OrderBook %s: snapshot загружен: "
            "update_id=%s bids=%d asks=%d",
            self.symbol,
            self.last_update_id,
            len(self.bids),
            len(self.asks),
        )

    # --------------------------------------------------------
    # Apply levels
    # --------------------------------------------------------

    def _apply_levels(
        self,
        levels: list[list[str]],
        book: dict[float, float],
    ):

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
                book.pop(price, None)

            else:
                book[price] = quantity

    # --------------------------------------------------------
    # Apply update
    # --------------------------------------------------------

    def apply_update(
        self,
        bids: list[list[str]],
        asks: list[list[str]],
        update_id: int,
    ):

        self._apply_levels(
            bids,
            self.bids,
        )

        self._apply_levels(
            asks,
            self.asks,
        )

        self.last_update_id = update_id

        self.events_applied += 1

    # --------------------------------------------------------
    # Best bid
    # --------------------------------------------------------

    @property
    def best_bid(self):

        if not self.bids:
            return None

        return max(self.bids)

    # --------------------------------------------------------
    # Best ask
    # --------------------------------------------------------

    @property
    def best_ask(self):

        if not self.asks:
            return None

        return min(self.asks)

    # --------------------------------------------------------
    # Spread
    # --------------------------------------------------------

    @property
    def spread(self):

        if (
            self.best_bid is None
            or self.best_ask is None
        ):
            return None

        return self.best_ask - self.best_bid

    # --------------------------------------------------------
    # Print
    # --------------------------------------------------------

    def print_book(self):

        best_bid = self.best_bid
        best_ask = self.best_ask

        if best_bid is None or best_ask is None:

            print(
                f"{self.symbol}: стакан пуст"
            )

            return

        spread = self.spread

        spread_percent = (
            spread / best_bid * 100
        )

        print()
        print("=" * 60)
        print(
            f"BITGET FUTURES ORDER BOOK: "
            f"{self.symbol}"
        )

        print(
            f"Update ID: {self.last_update_id}"
        )

        print(
            f"Events:    {self.events_applied}"
        )

        print(
            f"Spread:    "
            f"{spread:.8f} "
            f"({spread_percent:.6f}%)"
        )

        print("-" * 60)

        print("ASKS")

        asks = sorted(
            self.asks.items()
        )[:DISPLAY_LEVELS]

        for price, quantity in asks:

            print(
                f"{price:16.8f}"
                f" {quantity:18.8f}"
            )

        print("-" * 60)

        print("BIDS")

        bids = sorted(
            self.bids.items(),
            reverse=True,
        )[:DISPLAY_LEVELS]

        for price, quantity in bids:

            print(
                f"{price:16.8f}"
                f" {quantity:18.8f}"
            )

        print("=" * 60)


# ============================================================
# REST SNAPSHOT
# ============================================================

def get_snapshot(
    symbol: str,
) -> dict:

    logger.info(
        "Bitget OrderBook %s: "
        "запрос REST snapshot...",
        symbol,
    )

    url = (
        f"{BASE_URL_BITGET}"
        "/api/v2/mix/market/merge-depth"
    )

    params = {
        "symbol": symbol,
        "productType": "USDT-FUTURES",
        "limit": DEPTH_LIMIT,
    }

    response = requests.get(
        url,
        params=params,
        timeout=SNAPSHOT_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    if data.get("code") != "00000":

        raise RuntimeError(
            f"Bitget snapshot error: {data}"
        )

    snapshot = data.get("data")

    if not snapshot:

        raise RuntimeError(
            "Bitget snapshot is empty"
        )

    return snapshot


# ============================================================
# PARSE SNAPSHOT
# ============================================================

def parse_snapshot(
    symbol: str,
) -> OrderBook:

    snapshot = get_snapshot(
        symbol
    )

    bids = snapshot.get(
        "bids",
        [],
    )

    asks = snapshot.get(
        "asks",
        [],
    )

    # Bitget uses ts as timestamp.
    # Some API versions can also provide
    # version/update information.
    update_id_raw = (
        snapshot.get("version")
        or snapshot.get("u")
        or snapshot.get("seq")
        or snapshot.get("ts")
    )

    if update_id_raw is None:

        raise RuntimeError(
            f"Bitget snapshot does not contain "
            f"update identifier: {snapshot}"
        )

    update_id = int(update_id_raw)

    orderbook = OrderBook(
        symbol
    )

    orderbook.load_snapshot(
        bids=bids,
        asks=asks,
        update_id=update_id,
    )

    return orderbook


# ============================================================
# PARSE WS EVENT
# ============================================================

def parse_depth_event(
    message: str,
):

    try:

        data = json.loads(
            message
        )

    except json.JSONDecodeError:

        logger.warning(
            "Bitget OrderBook: "
            "некорректный JSON: %s",
            message,
        )

        return None

    if data.get("event") == "subscribe":

        logger.info(
            "Bitget OrderBook: "
            "подписка подтверждена: %s",
            data,
        )

        return None

    if data.get("event") == "error":

        raise RuntimeError(
            f"Bitget WS error: {data}"
        )

    if data.get("arg", {}).get("channel") != "books":

        return None

    data_list = data.get(
        "data"
    )

    if not data_list:

        return None

    payload = data_list[0]

    bids = payload.get(
        "bids",
        [],
    )

    asks = payload.get(
        "asks",
        [],
    )

    timestamp_raw = payload.get(
        "ts"
    )

    if timestamp_raw is None:

        return None

    timestamp = int(
        timestamp_raw
    )

    return {
        "bids": bids,
        "asks": asks,
        "update_id": timestamp,
    }


# ============================================================
# WEBSOCKET
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
        "Bitget OrderBook %s: WS подключен",
        symbol,
    )

    subscribe_message = {
        "op": "subscribe",
        "args": [
            {
                "instType": "USDT-FUTURES",
                "channel": "books",
                "instId": symbol,
            }
        ],
    }

    await ws.send(
        json.dumps(
            subscribe_message
        )
    )

    logger.info(
        "Bitget OrderBook %s: "
        "отправлена подписка books",
        symbol,
    )

    return ws


# ============================================================
# EVENT BUFFER
# ============================================================

async def collect_events(
    ws,
    symbol: str,
    first_event: dict | None = None,
):

    events = []

    if first_event is not None:

        events.append(
            first_event
        )

    while True:

        try:

            message = await asyncio.wait_for(
                ws.recv(),
                timeout=WS_TIMEOUT,
            )

        except asyncio.TimeoutError:

            logger.warning(
                "Bitget OrderBook %s: "
                "WS timeout",
                symbol,
            )

            break

        event = parse_depth_event(
            message
        )

        if event is None:
            continue

        events.append(
            event
        )

        return events


# ============================================================
# SYNC
# ============================================================

async def sync_orderbook(
    symbol: str,
    ws,
    first_event: dict,
):

    logger.info(
        "Bitget OrderBook %s: "
        "первое WS событие получено: "
        "update_id=%s. "
        "Запускаем snapshot.",
        symbol,
        first_event["update_id"],
    )

    buffer = [
        first_event
    ]

    # --------------------------------------------------------
    # Пока REST snapshot загружается,
    # продолжаем получать WS events.
    # --------------------------------------------------------

    snapshot_task = asyncio.create_task(
        asyncio.to_thread(
            get_snapshot,
            symbol,
        )
    )

    try:

        while not snapshot_task.done():

            try:

                message = await asyncio.wait_for(
                    ws.recv(),
                    timeout=1,
                )

            except asyncio.TimeoutError:

                continue

            event = parse_depth_event(
                message
            )

            if event is not None:

                buffer.append(
                    event
                )

    finally:

        snapshot = await snapshot_task

    bids = snapshot.get(
        "bids",
        [],
    )

    asks = snapshot.get(
        "asks",
        [],
    )

    update_id_raw = (
        snapshot.get("version")
        or snapshot.get("u")
        or snapshot.get("seq")
        or snapshot.get("ts")
    )

    if update_id_raw is None:

        raise OrderBookSyncError(
            "Bitget snapshot has no update ID"
        )

    snapshot_update_id = int(
        update_id_raw
    )

    logger.info(
        "Bitget OrderBook %s: "
        "snapshot получен: update_id=%s "
        "bids=%d asks=%d",
        symbol,
        snapshot_update_id,
        len(bids),
        len(asks),
    )

    orderbook = OrderBook(
        symbol
    )

    orderbook.load_snapshot(
        bids=bids,
        asks=asks,
        update_id=snapshot_update_id,
    )

    logger.info(
        "Bitget OrderBook %s: "
        "начинаем синхронизацию: "
        "snapshot=%s buffer=%d",
        symbol,
        snapshot_update_id,
        len(buffer),
    )

    # --------------------------------------------------------
    # Bitget books channel is snapshot/delta based.
    # Find first event newer than snapshot.
    # --------------------------------------------------------

    applicable_events = [
        event
        for event in buffer
        if event["update_id"] > snapshot_update_id
    ]

    if not applicable_events:

        logger.info(
            "Bitget OrderBook %s: "
            "в buffer пока нет событий после snapshot",
            symbol,
        )

    else:

        for event in applicable_events:

            orderbook.apply_update(
                bids=event["bids"],
                asks=event["asks"],
                update_id=event["update_id"],
            )

    orderbook.synced = True

    logger.info(
        "Bitget OrderBook %s: "
        "SYNC SUCCESS: update_id=%s "
        "bids=%d asks=%d",
        symbol,
        orderbook.last_update_id,
        len(orderbook.bids),
        len(orderbook.asks),
    )

    return orderbook


# ============================================================
# MAIN LOOP
# ============================================================

async def run_bitget_orderbook(
    symbol: str,
):

    symbol = symbol.upper()

    reconnect_delay = RECONNECT_DELAY

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

            # ------------------------------------------------
            # First event
            # ------------------------------------------------

            first_event = None

            while first_event is None:

                message = await asyncio.wait_for(
                    ws.recv(),
                    timeout=WS_TIMEOUT,
                )

                first_event = parse_depth_event(
                    message
                )

            # ------------------------------------------------
            # Sync
            # ------------------------------------------------

            orderbook = await sync_orderbook(
                symbol= symbol,
                ws=ws,
                first_event=first_event,
            )

            logger.info(
                "Bitget OrderBook %s: "
                "локальный стакан готов",
                symbol,
            )

            reconnect_delay = RECONNECT_DELAY

            # ------------------------------------------------
            # Live updates
            # ------------------------------------------------

            last_print = time.monotonic()

            while True:

                message = await asyncio.wait_for(
                    ws.recv(),
                    timeout=WS_TIMEOUT,
                )

                event = parse_depth_event(
                    message
                )

                if event is None:
                    continue

                update_id = event[
                    "update_id"
                ]

                # ------------------------------------------------
                # Ignore old events
                # ------------------------------------------------

                if update_id <= orderbook.last_update_id:

                    logger.debug(
                        "Bitget OrderBook %s: "
                        "старое событие: "
                        "update_id=%s local=%s",
                        symbol,
                        update_id,
                        orderbook.last_update_id,
                    )

                    continue

                # ------------------------------------------------
                # Apply update
                # ------------------------------------------------

                orderbook.apply_update(
                    bids=event["bids"],
                    asks=event["asks"],
                    update_id=update_id,
                )

                # ------------------------------------------------
                # Print every ~1 second
                # ------------------------------------------------

                now = time.monotonic()

                if now - last_print >= 1:

                    orderbook.print_book()

                    last_print = now

        except asyncio.CancelledError:

            logger.info(
                "Bitget OrderBook %s: остановлено",
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
# CLI
# ============================================================

async def main():

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

    symbol = sys.argv[1].upper()

    await run_bitget_orderbook(
        symbol
    )


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