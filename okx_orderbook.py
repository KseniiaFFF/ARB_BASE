import asyncio
import json
import logging
import sys
import time

import websockets
from websockets.exceptions import ConnectionClosed


logger = logging.getLogger(__name__)


WS_URL = "wss://ws.okx.com:8443/ws/v5/public"

CHANNEL = "books"

PRINT_LEVELS = 10

PRINT_INTERVAL = 1.0


# ============================================================
# ORDER BOOK
# ============================================================

class OKXOrderBook:

    def __init__(self, symbol: str):

        self.symbol = symbol

        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}

        self.seq_id: int | None = None

        self.events = 0

        self.snapshot_received = False

        self.last_print = 0.0

    # ========================================================
    # SNAPSHOT
    # ========================================================

    def load_snapshot(
        self,
        data: dict,
    ) -> None:

        print("load_snapshot")

        self.bids.clear()
        self.asks.clear()

        for level in data.get("bids", []):

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

        for level in data.get("asks", []):

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

        seq_id = data.get("seqId")

        if seq_id is None:

            raise RuntimeError(
                f"OKX OrderBook {self.symbol}: "
                "snapshot не содержит seqId"
            )

        self.seq_id = int(seq_id)

        self.snapshot_received = True

        self.events = 1

        logger.info(
            "OKX OrderBook %s: "
            "snapshot загружен: "
            "seqId=%d bids=%d asks=%d",
            self.symbol,
            self.seq_id,
            len(self.bids),
            len(self.asks),
        )

    # ========================================================
    # UPDATE
    # ========================================================

    def apply_update(
        self,
        data: dict,
    ) -> None:

        print("apply_update")

        if not self.snapshot_received:

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

        # ====================================================
        # SEQUENCE CHECK
        # ====================================================

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

        # ====================================================
        # APPLY BIDS
        # ====================================================

        self.apply_levels(
            self.bids,
            data.get("bids", []),
        )

        # ====================================================
        # APPLY ASKS
        # ====================================================

        self.apply_levels(
            self.asks,
            data.get("asks", []),
        )

        self.seq_id = new_seq_id

        self.events += 1

    # ========================================================
    # APPLY LEVELS
    # ========================================================

    @staticmethod
    def apply_levels(
        book: dict[float, float],
        levels: list,
    ) -> None:

        print("apply_levels")

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

    # ========================================================
    # BEST BID
    # ========================================================

    def best_bid(self) -> float | None:

        if not self.bids:
            return None

        return max(
            self.bids
        )

    # ========================================================
    # BEST ASK
    # ========================================================

    def best_ask(self) -> float | None:

        if not self.asks:
            return None

        return min(
            self.asks
        )

    # ========================================================
    # PRINT ORDER BOOK
    # ========================================================

    def print_book(self) -> None:

        print(
            "\n"
            + "=" * 60
        )

        print(
            f"OKX FUTURES ORDER BOOK: "
            f"{self.symbol}"
        )

        print(
            f"Sequence ID:       "
            f"{self.seq_id}"
        )

        print(
            f"Events:            "
            f"{self.events}"
        )

        best_bid = self.best_bid()
        best_ask = self.best_ask()

        if (
            best_bid is not None
            and best_ask is not None
        ):

            spread = (
                best_ask - best_bid
            )

            mid = (
                best_ask + best_bid
            ) / 2

            spread_percent = (
                spread / mid * 100
                if mid
                else 0
            )

            print(
                f"Spread:            "
                f"{spread:.8f} "
                f"({spread_percent:.6f}%)"
            )

        print(
            "-" * 60
        )

        # ====================================================
        # ASKS
        # ====================================================

        print("ASKS")

        asks = sorted(
            self.asks.items()
        )[:PRINT_LEVELS]

        for price, quantity in asks:

            print(
                f"  {price:14.8f}"
                f"  {quantity:18.8f}"
            )

        print(
            "-" * 60
        )

        # ====================================================
        # BIDS
        # ====================================================

        print("BIDS")

        bids = sorted(
            self.bids.items(),
            reverse=True,
        )[:PRINT_LEVELS]

        for price, quantity in bids:

            print(
                f"  {price:14.8f}"
                f"  {quantity:18.8f}"
            )

        print(
            "=" * 60
        )

    # ========================================================
    # PRINT TIMER
    # ========================================================

    def should_print(self) -> bool:

        now = time.monotonic()

        if (
            now - self.last_print
            >= PRINT_INTERVAL
        ):

            self.last_print = now

            return True

        return False


# ============================================================
# PARSE MESSAGE
# ============================================================

def parse_message(
    message: str,
) -> tuple[str, dict | None]:

    print("parse_message")

    try:

        data = json.loads(
            message
        )

    except json.JSONDecodeError:

        logger.warning(
            "OKX OrderBook: "
            "некорректный JSON: %s",
            message,
        )

        return (
            "invalid",
            None,
        )

    # ========================================================
    # WS EVENT
    # ========================================================

    event = data.get(
        "event"
    )

    if event:

        return (
            event,
            data,
        )

    # ========================================================
    # CHANNEL
    # ========================================================

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

    # ========================================================
    # ACTION
    # ========================================================

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
                "channel": CHANNEL,
                "instId": symbol,
            }
        ],
    }

    await ws.send(
        json.dumps(request)
    )

    logger.info(
        "OKX OrderBook %s: "
        "отправлена подписка books",
        symbol,
    )


# ============================================================
# MAIN CONNECTION
# ============================================================

async def run_okx_orderbook(
    symbol: str,
) -> None:

    logger.info(
        "OKX OrderBook %s: запуск",
        symbol,
    )

    reconnect_delay = 5

    while True:

        book = OKXOrderBook(
            symbol
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

                reconnect_delay = 5

                await subscribe(
                    ws,
                    symbol,
                )

                # =================================================
                # MESSAGE LOOP
                # =================================================

                async for message in ws:

                    action, payload = (
                        parse_message(
                            message
                        )
                    )

                    # =============================================
                    # SUBSCRIBE CONFIRMATION
                    # =============================================

                    if action == "subscribe":

                        logger.info(
                            "OKX OrderBook %s: "
                            "подписка подтверждена: %s",
                            symbol,
                            payload,
                        )

                        continue

                    # =============================================
                    # ERROR
                    # =============================================

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

                    # =============================================
                    # SNAPSHOT
                    # =============================================

                    if action == "snapshot":

                        logger.info(
                            "OKX OrderBook %s: "
                            "получен WS snapshot",
                            symbol,
                        )

                        book.load_snapshot(
                            payload
                        )

                        logger.info(
                            "OKX OrderBook %s: "
                            "локальный стакан готов",
                            symbol,
                        )

                        book.print_book()

                        continue

                    # =============================================
                    # UPDATE
                    # =============================================

                    if action == "update":

                        book.apply_update(
                            payload
                        )

                        if book.should_print():

                            book.print_book()

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
            60,
        )


# ============================================================
# ENTRY POINT
# ============================================================

async def main():

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

    input_symbol = (
        sys.argv[1]
        .upper()
    )

    # ========================================================
    # BTCUSDT -> BTC-USDT-SWAP
    # ========================================================

    if input_symbol.endswith(
        "USDT"
    ):

        asset = input_symbol[:-4]

        symbol = (
            f"{asset}-USDT-SWAP"
        )

    elif input_symbol.endswith(
        "-USDT-SWAP"
    ):

        symbol = input_symbol

    else:

        raise ValueError(
            f"Неподдерживаемый символ: "
            f"{input_symbol}"
        )

    await run_okx_orderbook(
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
            "\nOKX OrderBook: "
            "остановлено пользователем"
        )