from __future__ import annotations

import asyncio
import json
import logging
import random
import time

import websockets
from websockets.exceptions import ConnectionClosed

from price_feeds.models_price import Price
import market_latency
import market_events

logger = logging.getLogger(__name__)

WS_URL = "wss://fstream.binance.com/stream"
STREAM_BATCH_SIZE = 10


def create_subscriptions(symbols: list[str]) -> list[str]:
    return [f"{symbol.lower()}@bookTicker" for symbol in symbols]


def _parse_book_ticker(message: str) -> tuple[str, float, float, float, float, int] | None:
    data = json.loads(message)
    payload = data.get("data")
    if not payload or payload.get("e") != "bookTicker":
        return None

    try:
        return (
            str(payload["s"]),
            float(payload["b"]),
            float(payload["a"]),
            float(payload["B"]),
            float(payload["A"]),
            int(payload["E"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


async def run_binance_connection(
    streams: list[str],
    price_cache: dict[str, dict[str, Price]],
    connection_id: int,
) -> None:
    if not streams:
        return

    url = f"{WS_URL}?streams={'/'.join(streams)}"
    reconnect_delay = 1.0

    while True:
        try:
            async with websockets.connect(
                url,
                open_timeout=15,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=None,
            ) as ws:
                reconnect_delay = 1.0

                async for message in ws:
                    received_at = int(time.time() * 1000)
                    received_at_ns = time.monotonic_ns()

                    try:
                        parsed = _parse_book_ticker(message)
                    except json.JSONDecodeError:
                        continue

                    if parsed is None:
                        continue

                    symbol, bid, ask, bid_qty, ask_qty, timestamp = parsed
                    if bid <= 0 or ask <= 0:
                        continue

                    asset = symbol[:-4] if symbol.endswith("USDT") else symbol

                    price_cache.setdefault(asset, {})["binance"] = Price(
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

                    market_latency.mark_ws_update(asset, "binance")
                    market_events.mark_asset_dirty(asset)

        except asyncio.CancelledError:
            raise
        except (ConnectionClosed, TimeoutError, OSError):
            pass
        except Exception:
            logger.exception("Binance WS[%d]: unexpected error", connection_id)

        await asyncio.sleep(reconnect_delay + random.uniform(0.0, 0.25))
        reconnect_delay = min(reconnect_delay * 2.0, 30.0)


async def run_binance_ws(
    symbols: list[str],
    price_cache: dict[str, dict[str, Price]],
) -> None:
    if not symbols:
        return

    streams = create_subscriptions(symbols)
    batches = [
        streams[i : i + STREAM_BATCH_SIZE]
        for i in range(0, len(streams), STREAM_BATCH_SIZE)
    ]

    tasks = [
        asyncio.create_task(
            run_binance_connection(batch, price_cache, connection_id)
        )
        for connection_id, batch in enumerate(batches, start=1)
    ]

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
