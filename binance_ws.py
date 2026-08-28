import asyncio
import json
import logging
import time
import websockets

from price_feeds.models_price import Price
from websockets.exceptions import ConnectionClosed


logger = logging.getLogger(__name__)


WS_URL = "wss://fstream.binance.com/stream"
STREAM_BATCH_SIZE = 10


def create_subscriptions(symbols: list[str]) -> list[str]:

    return [
        f"{symbol.lower()}@bookTicker"
        for symbol in symbols
    ]


async def run_binance_connection(
    streams: list[str],
    price_cache: dict[str, dict[str, Price]],
    connection_id: int,
) -> None:

    if not streams:
        return

    params = "/".join(streams)
    url = f"{WS_URL}?streams={params}"

    logger.info(
        "Binance WS[%d]: подключение, streams=%d",
        connection_id,
        len(streams),
    )

    reconnect_delay = 5

    while True:

        try:

            async with websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=None,
            ) as ws:

                logger.info(
                    "Binance WS[%d]: соединение установлено",
                    connection_id,
                )

                reconnect_delay = 5

                async for message in ws:

                    received_at = int(
                        time.time() * 1000
                    )

                    received_at_ns = (
                        time.monotonic_ns()
                    )

                    try:
                        data = json.loads(message)

                    except json.JSONDecodeError:

                        logger.warning(
                            "Binance WS[%d]: "
                            "некорректный JSON",
                            connection_id,
                        )

                        continue

                    payload = data.get("data")

                    if not payload:
                        continue

                    symbol = payload.get("s")

                    if not symbol:
                        continue

                    try:

                        bid = float(
                            payload["b"]
                        )

                        ask = float(
                            payload["a"]
                        )

                        bid_qty = float(
                            payload["B"]
                        )

                        ask_qty = float(
                            payload["A"]
                        )

                        timestamp = int(
                            payload["E"]
                        )

                    except (
                        KeyError,
                        TypeError,
                        ValueError,
                    ):

                        logger.exception(
                            "Binance WS[%d]: "
                            "ошибка обработки: %s",
                            connection_id,
                            payload,
                        )

                        continue

                    asset = symbol[:-4]

                    price_cache.setdefault(
                        asset,
                        {},
                    )["binance"] = Price(
                        asset=asset,
                        exchange="binance",
                        symbol=symbol,
                        bid=bid,
                        ask=ask,
                        bid_qty=bid_qty,
                        ask_qty=ask_qty,
                        timestamp=timestamp,
                        received_at=received_at,
                        received_at_ns=received_at_ns,
                    )

        except asyncio.CancelledError:

            logger.info(
                "Binance WS[%d]: остановлено",
                connection_id,
            )

            raise

        except ConnectionClosed as exc:

            logger.warning(
                "Binance WS[%d]: соединение закрыто: "
                "code=%s reason=%s",
                connection_id,
                exc.code,
                exc.reason,
            )

        await asyncio.sleep(
            reconnect_delay
        )

        reconnect_delay = min(
            reconnect_delay * 2,
            60,
        )


async def run_binance_ws(
    symbols: list[str],
    price_cache: dict[str, dict[str, Price]],
) -> None:

    if not symbols:
        logger.warning(
            "Binance WS: нет символов для подписки"
        )

        return

    streams = create_subscriptions(symbols)

    batches = [
        streams[i:i + STREAM_BATCH_SIZE]
        for i in range(
            0,
            len(streams),
            STREAM_BATCH_SIZE,
        )
    ]

    logger.info(
        "Binance WS: всего streams=%d, "
        "соединений=%d",
        len(streams),
        len(batches),
    )

    tasks = []

    for connection_id, batch in enumerate(
        batches,
        start=1,
    ):
        tasks.append(
            asyncio.create_task(
                run_binance_connection(
                    batch,
                    price_cache,
                    connection_id,
                )
            )
        )

    try:

        await asyncio.gather(
            *tasks
        )

    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()

        await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        raise
