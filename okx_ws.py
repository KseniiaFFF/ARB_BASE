import asyncio
import json
import logging
import time
import websockets

from price_feeds.models import Price


logger = logging.getLogger(__name__)


WS_URL = "wss://ws.okx.com:8443/ws/v5/public"


def create_subscriptions(
    symbols: list[str]
) -> list[dict]:

    return [
        {
            "channel": "bbo-tbt",
            "instId": symbol,
        }
        for symbol in symbols
    ]


async def run_okx_ws(
    symbols: list[str],
    price_cache: dict[str, dict[str, Price]],
) -> None:

    if not symbols:

        logger.warning(
            "OKX WS: нет символов для подписки"
        )

        return

    args = create_subscriptions(symbols)

    logger.info(
        "OKX WS: подключение, символов: %d",
        len(symbols)
    )

    while True:

        try:

            async with websockets.connect(
                WS_URL,
                ping_interval=None,
                max_size=None,
            ) as ws:

                logger.info(
                    "OKX WS: соединение установлено"
                )


                for i in range(0, len(args), 50):

                    batch = args[i:i + 50]

                    request = {
                        "op": "subscribe",
                        "args": batch,
                    }

                    await ws.send(
                        json.dumps(request)
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
                        logger.warning("OKX WS: некорректный JSON: %s",
                            message,
                            )
                        continue

                    if data.get("event") == "error":

                        logger.error(
                            "OKX WS error: %s",
                            data
                        )

                        continue

                    if data.get("event") == "subscribe":
                        continue

                    rows = data.get("data")

                    if not rows:
                        continue

                    for book in rows:

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
                                book.get("ts", 0)
                            )

                        except (
                            IndexError,
                            KeyError,
                            TypeError,
                            ValueError,
                        ):
                            logger.exception(
                                "OKX WS: ошибка "
                                "обработки bbo-tbt: %s",
                                book,
                            )

                            continue

                        symbol = (
                            data.get("arg", {})
                            .get("instId")
                        )

                        if not symbol:
                            continue

                        asset = symbol.split("-")[0]

                        price_cache.setdefault(
                            asset,
                            {}
                        )["okx"] = Price(
                            asset=asset,
                            exchange="okx",
                            symbol=symbol,
                            bid=bid_price,
                            ask=ask_price,
                            bid_qty=bid_qty,
                            ask_qty=ask_qty,
                            timestamp=timestamp,
                            received_at = received_at,
                            received_at_ns=received_at_ns
                        )

        except asyncio.CancelledError:

            logger.info(
                "OKX WS: остановлено"
            )

            raise

        except Exception:

            logger.exception(
                "OKX WS: ошибка соединения. "
                "Повтор через 5 секунд."
            )

            await asyncio.sleep(5)