import logging
import time

from exchanges.binance import get_taker_fee as get_binance_fee
from exchanges.bitget import get_taker_fee as get_bitget_fee
from exchanges.okx import get_taker_fee as get_okx_fee

logger = logging.getLogger(__name__)

FEE_REFRESH_INTERVAL_SECONDS = 24 * 60 * 60

fee_cache: dict[str, float] = {}
fee_updated_at: float = 0.0


def refresh_fees(symbols_by_exchange: dict[str, str]) -> None:
    """
    Получает текущую taker-комиссию один раз для каждой биржи.

    symbols_by_exchange:
        {
            "binance": "BTCUSDT",
            "bitget": "BTCUSDT",
            "okx": "BTC-USDT-SWAP",
        }

    После успешного обновления значения хранятся в fee_cache.
    """

    global fee_updated_at

    new_fees: dict[str, float] = {}

    for exchange, symbol in symbols_by_exchange.items():
        try:
            if exchange == "binance":
                fee = get_binance_fee(symbol)
            elif exchange == "bitget":
                fee = get_bitget_fee(symbol)
            elif exchange == "okx":
                fee = get_okx_fee(symbol)
            else:
                raise ValueError(f"Unknown exchange: {exchange}")

            new_fees[exchange] = fee

            logger.info(
                "Fee updated: %s = %.4f%%",
                exchange,
                fee,
            )

        except Exception:
            logger.exception(
                "Не удалось получить taker fee: %s %s",
                exchange,
                symbol,
            )
            raise

    # Обновляем cache только если ВСЕ три комиссии успешно получены.
    # Это важно: нельзя оставить часть старых и часть новых значений.
    fee_cache.clear()
    fee_cache.update(new_fees)

    fee_updated_at = time.time()

    logger.info(
        "Комиссии обновлены. Следующее обновление через 24 часа."
    )


def get_fee(exchange: str) -> float:
    """
    Возвращает уже загруженную taker-комиссию.

    HTTP-запросов здесь нет.
    """

    try:
        return fee_cache[exchange]
    except KeyError:
        raise RuntimeError(
            f"Комиссия для биржи {exchange} ещё не загружена"
        )


def is_fee_refresh_needed() -> bool:
    if not fee_cache:
        return True

    return time.time() - fee_updated_at >= FEE_REFRESH_INTERVAL_SECONDS


def get_fee_age_hours() -> float | None:
    if not fee_updated_at:
        return None

    return (time.time() - fee_updated_at) / 3600
