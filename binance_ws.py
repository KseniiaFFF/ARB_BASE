import asyncio
import json
import logging
import time
import websockets

from price_feeds.models_price import Price


logger = logging.getLogger(__name__)


WS_URL = "wss://fstream.binance.com/stream"


def create_subscriptions(symbols: list[str]) -> list[str]:

    return [
        f"{symbol.lower()}@bookTicker"
        for symbol in symbols
    ]


async def run_binance_ws(
    symbols: list[str],
    price_cache: dict[str, dict[str, Price]],
) -> None:

    streams = create_subscriptions(symbols)

    if not streams:
        logger.warning(
            "Binance: нет символов для подписки"
        )
        return

    params = "/".join(streams)

    url = f"{WS_URL}?streams={params}"

    logger.info(
        "Binance WS: подключение, символов: %d",
        len(symbols)
    )

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
                    "Binance WS: соединение установлено"
                )

                async for message in ws:

                    received_at = int(time.time() * 1000)
                    received_at_ns = time.monotonic_ns()

                    data = json.loads(message)

                    payload = data.get("data")

                    if not payload:
                        continue

                    symbol = payload.get("s")

                    if not symbol:
                        continue

                    bid = float(payload["b"])
                    ask = float(payload["a"])

                    bid_qty = float(payload["B"])
                    ask_qty = float(payload["A"])

                    timestamp = payload.get(
                        "E"
                    )


                    price_cache.setdefault(
                        symbol[:-4],
                        {}
                    )["binance"] = Price(
                        asset=symbol[:-4],
                        exchange="binance",
                        symbol=symbol,
                        bid=bid,
                        ask=ask,
                        bid_qty=bid_qty,
                        ask_qty=ask_qty,
                        timestamp=timestamp,
                        received_at=received_at,
                        received_at_ns=received_at_ns
                    )

        except asyncio.CancelledError:
            logger.info(
                "Binance WS: остановлено"
            )
            raise

        except Exception:
            logger.exception(
                "Binance WS: ошибка соединения. "
                "Повтор через 5 секунд."
            )

            await asyncio.sleep(5)