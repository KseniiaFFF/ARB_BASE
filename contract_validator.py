import logging

from exchanges.binance import (
    get_futures_contracts as get_binance_contracts
)
from exchanges.bitget import (
    get_futures_contracts as get_bitget_contracts
)
from exchanges.okx import (
    get_futures_contracts as get_okx_contracts
)

from log_settings import setup_logging
from models import Market

setup_logging()

logger = logging.getLogger(__name__)


def get_valid_binance_contracts() -> set[str]:

    try:
        contracts = get_binance_contracts()

        logger.info(
            "Binance: получено контрактов: %d",
            len(contracts)
        )

        valid_contracts = set()

        for contract in contracts:

            if contract.get("quoteAsset") != "USDT":
                continue

            if contract.get("contractType") != "PERPETUAL":
                continue

            if contract.get("status") != "TRADING":
                continue

            symbol = contract.get("symbol")

            if not symbol:
                logger.warning(
                    "Binance: найден контракт без symbol: %s",
                    contract
                )
                continue

            valid_contracts.add(symbol)

        logger.info(
            "Binance: действующих USDT perpetual контрактов: %d",
            len(valid_contracts)
        )

        return valid_contracts

    except Exception:
        logger.exception(
            "Ошибка при получении/проверке контрактов Binance"
        )

        return set()


def get_valid_bitget_contracts() -> set[str]:

    try:
        contracts = get_bitget_contracts()

        logger.info(
            "Bitget: получено контрактов: %d",
            len(contracts)
        )

        valid_contracts = set()

        for contract in contracts:

            if contract.get("quoteCoin") != "USDT":
                continue

            if contract.get("symbolStatus") != "normal":
                continue

            symbol = contract.get("symbol")

            if not symbol:
                logger.warning(
                    "Bitget: найден контракт без symbol: %s",
                    contract
                )
                continue

            valid_contracts.add(symbol)

        logger.info(
            "Bitget: действующих USDT perpetual контрактов: %d",
            len(valid_contracts)
        )

        return valid_contracts

    except Exception:
        logger.exception(
            "Ошибка при получении/проверке контрактов Bitget"
        )

        return set()


def get_valid_okx_contracts() -> set[str]:

    try:
        contracts = get_okx_contracts()

        logger.info(
            "OKX: получено контрактов: %d",
            len(contracts)
        )

        valid_contracts = set()

        for contract in contracts:

            if contract.get("settleCcy") != "USDT":
                continue

            symbol = contract.get("instId", "")

            if not symbol.endswith("-USDT-SWAP"):
                continue

            if contract.get("state") != "live":
                continue

            valid_contracts.add(symbol)

        logger.info(
            "OKX: действующих USDT perpetual контрактов: %d",
            len(valid_contracts)
        )

        return valid_contracts

    except Exception:
        logger.exception(
            "Ошибка при получении/проверке контрактов OKX"
        )

        return set()


def get_valid_contracts() -> dict[str, set[str]]:

    logger.info(
        "Начало проверки действующих контрактов"
    )

    contracts = {
        "binance": get_valid_binance_contracts(),
        "bitget": get_valid_bitget_contracts(),
        "okx": get_valid_okx_contracts(),
    }

    logger.info(
        "Проверка действующих контрактов завершена"
    )

    return contracts


def update_market_status(
    markets: list[Market],
    valid_contracts: dict[str, set[str]]
) -> None:

    for market in markets:

        exchange_contracts = valid_contracts.get(
            market.exchange,
            set()
        )

        market.active = market.symbol in exchange_contracts

        logger.debug(
            "%s %s: active=%s",
            market.exchange,
            market.symbol,
            market.active
        )


def update_all_market_status(
    exchanges: dict[str, list[Market]],
    valid_contracts: dict[str, set[str]]
) -> None:

    for exchange, markets in exchanges.items():

        update_market_status(
            markets,
            valid_contracts
        )

        active_count = sum(
            market.active
            for market in markets
        )

        logger.info(
            "%s: активных Market: %d из %d",
            exchange,
            active_count,
            len(markets)
        )


if __name__ == "__main__":

    logger.info(
        "Запуск contract_validator.py"
    )

    contracts = get_valid_contracts()

    for exchange, symbols in contracts.items():

        print(
            f"{exchange}: "
            f"{len(symbols)} действующих контрактов"
        )

        for symbol in sorted(symbols):
            print(f"  {symbol}")

        print()

    logger.info(
        "contract_validator.py завершил работу"
    )