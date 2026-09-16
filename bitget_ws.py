import asyncio
import json
import logging
import time

import websockets

import market_latency
import market_events
from price_feeds.models_price import Price


logger = logging.getLogger(__name__)


WS_URL = "wss://ws.bitget.com/v2/ws/public"

SUBSCRIPTION_BATCH_SIZE = 50

# Параметры переподключения
INITIAL_RECONNECT_DELAY = 5
MAX_RECONNECT_DELAY = 60


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

    except Exception as exc:

        logger.warning(
            "Bitget WS: heartbeat остановлен: %s",
            exc,
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

    # logger.info(
    #     "Bitget WS: подключение, символов: %d",
    #     len(symbols),
    # )

    reconnect_delay = INITIAL_RECONNECT_DELAY

    while True:

        ping_task = None

        try:

            # logger.info(
            #     "Bitget WS: попытка подключения"
            # )

            async with websockets.connect(
                WS_URL,
                ping_interval=None,
                max_size=None,
                open_timeout=30,
                close_timeout=5,
            ) as ws:

                # logger.info(
                #     "Bitget WS: соединение установлено"
                # )

                # После успешного подключения
                # начинаем backoff заново.
                reconnect_delay = INITIAL_RECONNECT_DELAY

                ping_task = asyncio.create_task(
                    send_ping(ws)
                )

                # -------------------------------------------------
                # Подписка на все символы
                # -------------------------------------------------

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

                    # logger.info(
                    #     "Bitget WS: отправлена "
                    #     "подписка %d-%d",
                    #     i + 1,
                    #     min(
                    #         i + SUBSCRIPTION_BATCH_SIZE,
                    #         len(args),
                    #     ),
                    # )

                    await asyncio.sleep(0.1)

                # -------------------------------------------------
                # Получение данных
                # -------------------------------------------------

                async for message in ws:

                    # Bitget heartbeat response
                    if message == "pong":
                        continue

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
                            "Bitget WS: некорректный JSON: %s",
                            message,
                        )

                        continue

                    # -------------------------------------------------
                    # Ошибка Bitget API
                    # -------------------------------------------------

                    if data.get("event") == "error":

                        logger.error(
                            "Bitget WS error: %s",
                            data,
                        )

                        continue

                    # -------------------------------------------------
                    # Подтверждение подписки
                    # -------------------------------------------------

                    if data.get("event") == "subscribe":

                        logger.debug(
                            "Bitget WS: подписка подтверждена: %s",
                            data,
                        )

                        continue

                    # -------------------------------------------------
                    # Данные стакана
                    # -------------------------------------------------

                    rows = data.get("data")

                    if not rows:
                        continue

                    symbol = (
                        data.get("arg", {})
                        .get("instId")
                    )

                    if not symbol:
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

                        # BTCUSDT -> BTC
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
                            received_at_ns=received_at_ns,
                        )

                        market_latency.mark_ws_update(
                            asset,
                            "bitget",
                        )
                        market_events.mark_asset_dirty(asset)

        # ---------------------------------------------------------
        # Остановка по CancelledError
        # ---------------------------------------------------------

        except asyncio.CancelledError:

            logger.info(
                "Bitget WS: остановлено"
            )

            raise

        # ---------------------------------------------------------
        # WebSocket закрылся
        # ---------------------------------------------------------

        except websockets.exceptions.ConnectionClosed as exc:

            logger.warning(
                "Bitget WS: соединение закрыто: "
                "code=%s reason=%s",
                exc.code,
                exc.reason,
            )

        # ---------------------------------------------------------
        # Таймаут подключения
        # ---------------------------------------------------------

        except TimeoutError:

            logger.warning(
                "Bitget WS: таймаут подключения"
            )

        # ---------------------------------------------------------
        # Любая сетевая / системная ошибка
        #
        # Сюда попадёт в том числе:
        # socket.gaierror [Errno 11001]
        # ConnectionResetError
        # ConnectionRefusedError
        # OSError
        # ---------------------------------------------------------

        except OSError as exc:

            logger.warning(
                "Bitget WS: сетевая ошибка: %s. "
                "Переподключение через %d секунд.",
                exc,
                reconnect_delay,
            )

        # ---------------------------------------------------------
        # Остальные неожиданные ошибки
        # ---------------------------------------------------------

        except Exception:

            logger.exception(
                "Bitget WS: неожиданная ошибка. "
                "Переподключение через %d секунд.",
                reconnect_delay,
            )

        # ---------------------------------------------------------
        # Останавливаем heartbeat после любого выхода
        # из соединения
        # ---------------------------------------------------------

        finally:

            if ping_task is not None:

                ping_task.cancel()

                try:

                    await ping_task

                except asyncio.CancelledError:

                    pass

        # ---------------------------------------------------------
        # Пауза перед переподключением
        # ---------------------------------------------------------

        # logger.info(
        #     "Bitget WS: переподключение через %d секунд",
        #     reconnect_delay,
        # )

        await asyncio.sleep(
            reconnect_delay
        )

        # Экспоненциальный backoff:
        #
        # 5 -> 10 -> 20 -> 40 -> 60 -> 60...
        #

        reconnect_delay = min(
            reconnect_delay * 2,
            MAX_RECONNECT_DELAY,
        )
