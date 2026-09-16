import asyncio
import json
import logging
import random
import sys
import time
import websockets

from websockets.exceptions import ConnectionClosed
from price_feeds.orderbook_models import OrderBook
from price_feeds.orderbook_cache import update_orderbook


logger = logging.getLogger(__name__)

WS_URL = "wss://ws.bitget.com/v2/ws/public"

CHANNEL = "books"
PRODUCT_TYPE = "USDT-FUTURES"

DISPLAY_LEVELS = 10

WS_TIMEOUT = 15
OPEN_TIMEOUT = 10

RECONNECT_DELAY = 5
MAX_RECONNECT_DELAY = 60
RECONNECT_JITTER = 1.0

PRINT_INTERVAL = 1.0



class BitgetLocalOrderBook:

    def __init__(
        self,
        symbol: str,
    ):
        self.symbol = symbol

        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}

        self.seq = 0

        self.update_id = 0

        self.exchange_timestamp = 0

        self.received_at = 0
        self.received_at_ns = 0

        self.events = 0

        self.synced = False


    def load_snapshot(
        self,
        bids: list,
        asks: list,
        timestamp: int,
        seq: int,
    ) -> None:

        if seq <= 0:
            raise RuntimeError(
                f"Bitget OrderBook {self.symbol}: "
                f"invalid snapshot seq={seq}"
            )

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

        self.seq = seq
        self.update_id = seq

        self.exchange_timestamp = timestamp

        self.received_at = int(
            time.time() * 1000
        )

        self.received_at_ns = time.time_ns()

        self.events = 0

        self.synced = True

        # logger.info(
        #     "Bitget OrderBook %s: "
        #     "WS snapshot загружен: "
        #     "seq=%s timestamp=%s "
        #     "bids=%d asks=%d",
        #     self.symbol,
        #     seq,
        #     timestamp,
        #     len(self.bids),
        #     len(self.asks),
        # )


    def apply_update(
        self,
        bids: list,
        asks: list,
        timestamp: int,
        seq: int,
        pseq: int,
    ) -> None:

        if not self.synced:
            raise RuntimeError(
                "Нельзя применить update "
                "до snapshot"
            )

        if seq <= 0:
            raise RuntimeError(
                f"Bitget OrderBook {self.symbol}: "
                f"invalid update seq={seq}"
            )

        if pseq <= 0:
            raise RuntimeError(
                f"Bitget OrderBook {self.symbol}: "
                f"invalid update pseq={pseq}"
            )


        if self.events == 0:

            if not (
                pseq
                <= self.seq
                <= seq
            ):

                raise RuntimeError(
                    f"Bitget OrderBook {self.symbol}: "
                    f"SEQUENCE GAP: "
                    f"snapshot_seq={self.seq} "
                    f"pseq={pseq} "
                    f"seq={seq}"
                )

        else:

            if pseq != self.seq:

                raise RuntimeError(
                    f"Bitget OrderBook {self.symbol}: "
                    f"SEQUENCE GAP: "
                    f"current_seq={self.seq} "
                    f"received_pseq={pseq} "
                    f"received_seq={seq}"
                )


        if seq < self.seq:

            raise RuntimeError(
                f"Bitget OrderBook {self.symbol}: "
                f"OUT-OF-ORDER: "
                f"current_seq={self.seq} "
                f"received_seq={seq}"
            )


        self._apply_levels(
            self.bids,
            bids,
        )

        self._apply_levels(
            self.asks,
            asks,
        )

        self.seq = seq
        self.update_id = seq

        self.exchange_timestamp = timestamp

        self.received_at = int(
            time.time() * 1000
        )

        self.received_at_ns = time.time_ns()

        self.events += 1


    @staticmethod
    def _apply_levels(
        book: dict[float, float],
        levels: list,
    ) -> None:

        for level in levels:

            if not isinstance(level, (list, tuple)):
                continue

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

            if price <= 0:
                continue

            if quantity < 0:
                continue

            if quantity == 0:

                book.pop(
                    price,
                    None,
                )

            else:

                book[price] = quantity


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


def publish_orderbook(
    orderbook: BitgetLocalOrderBook,
) -> None:

    common_orderbook = (
        orderbook.to_common_orderbook()
    )

    update_orderbook(
        common_orderbook
    )



def parse_int(
    value,
) -> int | None:

    if value is None:
        return None

    try:
        return int(value)

    except (
        TypeError,
        ValueError,
    ):
        return None



def get_timestamp(
    payload: dict,
) -> int | None:

    timestamp = (
        payload.get("ts")
        or payload.get("timestamp")
    )

    return parse_int(
        timestamp
    )


def get_sequence(
    payload: dict,
) -> tuple[int | None, int | None]:

    seq = parse_int(
        payload.get("seq")
    )

    pseq = parse_int(
        payload.get("pseq")
    )

    return seq, pseq


def parse_message(
    message: str,
) -> tuple[str, dict | None]:


    if message == "ping":

        return (
            "ping",
            None,
        )

    if message == "pong":

        return (
            "pong",
            None,
        )


    try:

        data = json.loads(
            message
        )

    except (
        json.JSONDecodeError,
        TypeError,
    ):

        logger.warning(
            "Bitget OrderBook: "
            "некорректный JSON: %r",
            message,
        )

        return (
            "invalid",
            None,
        )

    if not isinstance(
        data,
        dict,
    ):

        return (
            "unknown",
            None,
        )


    event = data.get(
        "event"
    )

    if event == "subscribe":

        return (
            "subscribe",
            data,
        )


    if event == "error":

        return (
            "error",
            data,
        )


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


    data_list = data.get(
        "data"
    )

    if not isinstance(
        data_list,
        list,
    ):

        return (
            "unknown",
            None,
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

    if not isinstance(
        bids,
        list,
    ):

        bids = []

    if not isinstance(
        asks,
        list,
    ):

        asks = []


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


    seq, pseq = get_sequence(
        payload
    )

    if seq is None:

        logger.warning(
            "Bitget OrderBook %s: "
            "event без seq",
            arg.get("instId"),
        )

        return (
            "unknown",
            None,
        )


    result = {
        "bids": bids,
        "asks": asks,

        "timestamp": timestamp,

        "seq": seq,
        "pseq": pseq,
    }


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

    # logger.info(
    #     "Bitget OrderBook %s: "
    #     "отправлена подписка books",
    #     symbol,
    # )


async def connect_ws(
    symbol: str,
):

    # logger.info(
    #     "Bitget OrderBook %s: "
    #     "подключение WS: %s",
    #     symbol,
    #     WS_URL,
    # )

    ws = await websockets.connect(
        WS_URL,

        ping_interval=None,
        ping_timeout=None,

        close_timeout=5,
        open_timeout=OPEN_TIMEOUT,

        max_size=None,
    )

    # logger.info(
    #     "Bitget OrderBook %s: "
    #     "WS подключен",
    #     symbol,
    # )

    await subscribe(
        ws,
        symbol,
    )

    return ws


async def wait_for_snapshot(
    symbol: str,
    ws,
) -> dict:

    while True:

        message = await asyncio.wait_for(
            ws.recv(),
            timeout=WS_TIMEOUT,
        )

        if message == "ping":

            await ws.send(
                "pong"
            )

            continue

        action, payload = parse_message(
            message
        )


        if action == "subscribe":

            # logger.info(
            #     "Bitget OrderBook %s: "
            #     "подписка подтверждена",
            #     symbol,
            # )

            continue


        if action == "error":

            raise RuntimeError(
                f"Bitget WS error: "
                f"{payload}"
            )


        if (
            action == "snapshot"
            and payload is not None
        ):

            return payload


def create_orderbook_from_snapshot(
    symbol: str,
    snapshot: dict,
) -> BitgetLocalOrderBook:

    orderbook = BitgetLocalOrderBook(
        symbol
    )

    seq = snapshot.get(
        "seq"
    )

    timestamp = snapshot.get(
        "timestamp"
    )

    if seq is None:
        raise RuntimeError(
            f"Bitget OrderBook {symbol}: "
            "snapshot без seq"
        )

    if timestamp is None:
        raise RuntimeError(
            f"Bitget OrderBook {symbol}: "
            "snapshot без timestamp"
        )

    orderbook.load_snapshot(
        bids=snapshot.get(
            "bids",
            [],
        ),
        asks=snapshot.get(
            "asks",
            [],
        ),
        timestamp=timestamp,
        seq=seq,
    )

    return orderbook


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

            # logger.info(
            #     "Bitget OrderBook %s: запуск",
            #     symbol,
            # )


            ws = await connect_ws(
                symbol
            )


            snapshot = (
                await wait_for_snapshot(
                    symbol,
                    ws,
                )
            )


            orderbook = (
                create_orderbook_from_snapshot(
                    symbol,
                    snapshot,
                )
            )

            # logger.info(
            #     "Bitget OrderBook %s: "
            #     "локальный стакан готов: "
            #     "seq=%s",
            #     symbol,
            #     orderbook.seq,
            # )

            publish_orderbook(
                orderbook
            )


            reconnect_delay = (
                RECONNECT_DELAY
            )

            last_print = time.monotonic()


            while True:

                try:

                    message = await asyncio.wait_for(
                        ws.recv(),
                        timeout=WS_TIMEOUT,
                    )

                except asyncio.TimeoutError:

                    try:

                        await ws.send(
                            "ping"
                        )

                    except Exception as exc:

                        raise RuntimeError(
                            "Bitget heartbeat failed"
                        ) from exc

                    continue

                if message == "ping":

                    await ws.send(
                        "pong"
                    )

                    continue

                if message == "pong":

                    continue

                action, payload = parse_message(
                    message
                )

                if action == "subscribe":

                    # logger.info(
                    #     "Bitget OrderBook %s: "
                    #     "подписка подтверждена",
                    #     symbol,
                    # )

                    continue


                if action == "error":

                    raise RuntimeError(
                        f"Bitget WS error: "
                        f"{payload}"
                    )


                if (
                    action != "update"
                    or payload is None
                ):

                    continue


                timestamp = payload.get(
                    "timestamp"
                )

                seq = payload.get(
                    "seq"
                )

                pseq = payload.get(
                    "pseq"
                )

                if timestamp is None:
                    raise RuntimeError(
                        f"Bitget OrderBook {symbol}: "
                        "update без timestamp"
                    )

                if seq is None:
                    raise RuntimeError(
                        f"Bitget OrderBook {symbol}: "
                        "update без seq"
                    )

                if pseq is None:
                    raise RuntimeError(
                        f"Bitget OrderBook {symbol}: "
                        "update без pseq"
                    )

                if orderbook.events == 0:

                    if not (
                        pseq
                        <= orderbook.seq
                        <= seq
                    ):

                        raise RuntimeError(
                            f"Bitget OrderBook {symbol}: "
                            f"SEQUENCE GAP: "
                            f"snapshot_seq={orderbook.seq} "
                            f"pseq={pseq} "
                            f"seq={seq}"
                        )

                else:

                    if pseq != orderbook.seq:

                        raise RuntimeError(
                            f"Bitget OrderBook {symbol}: "
                            f"SEQUENCE GAP: "
                            f"local_seq={orderbook.seq} "
                            f"pseq={pseq} "
                            f"seq={seq}"
                        )


                if seq < orderbook.seq:

                    raise RuntimeError(
                        f"Bitget OrderBook {symbol}: "
                        f"OUT-OF-ORDER: "
                        f"local_seq={orderbook.seq} "
                        f"seq={seq}"
                    )

                orderbook.apply_update(
                    bids=payload.get(
                        "bids",
                        [],
                    ),
                    asks=payload.get(
                        "asks",
                        [],
                    ),
                    timestamp=timestamp,
                    seq=seq,
                    pseq=pseq,
                )


                publish_orderbook(
                    orderbook
                )

                now = time.monotonic()

                if (
                    now - last_print
                    >= PRINT_INTERVAL
                ):


                    last_print = now


        except asyncio.CancelledError:

            logger.info(
                "Bitget OrderBook %s: "
                "остановлено",
                symbol,
            )

            if ws is not None:

                try:
                    await ws.close()

                except Exception:
                    pass

            raise


        except ConnectionClosed:

            pass


        except (TimeoutError, OSError):

            pass


        except RuntimeError as exc:

            message = str(exc)

            if not (

                "SEQUENCE GAP" in message

                or "OUT-OF-ORDER" in message

                or "snapshot" in message.lower()

                or "heartbeat" in message.lower()

            ):

                logger.exception(

                    "Bitget OrderBook %s: unexpected error",

                    symbol,

                )


        except Exception:

            logger.exception(

                "Bitget OrderBook %s: unexpected error",

                symbol,

            )


        delay = reconnect_delay + random.uniform(0, RECONNECT_JITTER)

        await asyncio.sleep(delay)


        reconnect_delay = min(

            reconnect_delay * 2,

            MAX_RECONNECT_DELAY,

        )

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


async def run_bitget_orderbooks(
    symbols: list[str],
) -> None:
    tasks = [
        asyncio.create_task(
            run_bitget_orderbook(symbol)
        )
        for symbol in symbols
    ]

    await asyncio.gather(*tasks)


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

