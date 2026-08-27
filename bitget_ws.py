import asyncio
import json
import logging
import time
import websockets

from price_feeds.models import Price


logger = logging.getLogger(__name__)


WS_URL = "wss://ws.bitget.com/v2/ws/public"

SUBSCRIPTION_BATCH_SIZE = 50


def create_subscriptions(
    symbols: list[str],
) -> list[dict]:

    return [
        {
            "instType": "USDT-FUTURES",
            "channel": "books1",
            "instId": symbol,
        }
        for symbol in symbols
    ]


async def send_ping(ws) -> None:

    try:

        while True:

            await asyncio.sleep(25)

            await ws.send("ping")

    except asyncio.CancelledError:

        raise

    except Exception:

        logger.exception(
            "Bitget WS: ошибка heartbeat"
        )


async def run_bitget_ws(
    symbols: list[str],
    price_cache: dict[str, dict[str, Price]],
) -> None:

    if not symbols:

        logger.warning(
            "Bitget WS: нет символов для подписки"
        )

        return

    args = create_subscriptions(symbols)

    logger.info(
        "Bitget WS: подключение, символов: %d",
        len(symbols),
    )

    while True:

        ping_task = None

        try:

            async with websockets.connect(
                WS_URL,
                ping_interval=None,
                max_size=None,
            ) as ws:

                logger.info(
                    "Bitget WS: соединение установлено"
                )

                ping_task = asyncio.create_task(
                    send_ping(ws)
                )

                for i in range(
                    0,
                    len(args),
                    SUBSCRIPTION_BATCH_SIZE,
                ):

                    batch = args[
                        i:i + SUBSCRIPTION_BATCH_SIZE
                    ]

                    request = {
                        "op": "subscribe",
                        "args": batch,
                    }

                    await ws.send(
                        json.dumps(request)
                    )

                    logger.info(
                        "Bitget WS: отправлена "
                        "подписка %d-%d",
                        i + 1,
                        min(
                            i + SUBSCRIPTION_BATCH_SIZE,
                            len(args),
                        ),
                    )

                    await asyncio.sleep(0.1)

                async for message in ws:

                    if message == "pong":
                        continue

                    received_at = int(time.time() * 1000)
                    received_at_ns = time.monotonic_ns()

                    try:

                        data = json.loads(message)

                    except json.JSONDecodeError:

                        logger.warning(
                            "Bitget WS: некорректный JSON: %s",
                            message,
                        )

                        continue

                    if data.get("event") == "error":

                        logger.error(
                            "Bitget WS error: %s",
                            data,
                        )

                        continue

                    if data.get("event") == "subscribe":

                        logger.debug(
                            "Bitget WS: подписка подтверждена: %s",
                            data,
                        )

                        continue

                    rows = data.get("data")

                    if not rows:
                        continue

                    for book in rows:

                        symbol = (
                            data.get("arg", {})
                            .get("instId")
                        )

                        if not symbol:
                            continue

                        asks = book.get("asks")
                        bids = book.get("bids")

                        if not asks or not bids:
                            continue

                        try:

                            ask_price = float(
                                asks[0][0]
                            )

                            ask_qty = float(
                                asks[0][1]
                            )

                            bid_price = float(
                                bids[0][0]
                            )

                            bid_qty = float(
                                bids[0][1]
                            )

                            timestamp = int(
                                book.get(
                                    "ts",
                                    0,
                                )
                            )


                        except (
                            IndexError,
                            KeyError,
                            TypeError,
                            ValueError,
                        ):

                            logger.exception(
                                "Bitget WS: ошибка "
                                "обработки books1: %s",
                                book,
                            )

                            continue

                        asset = symbol[:-4]

                        price_cache.setdefault(
                            asset,
                            {},
                        )["bitget"] = Price(
                            asset=asset,
                            exchange="bitget",
                            symbol=symbol,
                            bid=bid_price,
                            ask=ask_price,
                            bid_qty=bid_qty,
                            ask_qty=ask_qty,
                            timestamp=timestamp,
                            received_at=received_at,
                            received_at_ns=received_at_ns
                        )

        except asyncio.CancelledError:

            logger.info(
                "Bitget WS: остановлено"
            )

            if ping_task:

                ping_task.cancel()

                try:
                    await ping_task
                except asyncio.CancelledError:
                    pass

            raise

        except Exception:

            logger.exception(
                "Bitget WS: ошибка соединения. "
                "Повтор через 5 секунд."
            )

        finally:

            if ping_task:

                ping_task.cancel()

                try:
                    await ping_task
                except asyncio.CancelledError:
                    pass

        await asyncio.sleep(5)