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
from models import Contract, Market

setup_logging()

logger = logging.getLogger(__name__)


def get_valid_binance_contracts() -> dict[str, Contract]:

    try:
        contracts = get_binance_contracts()

        logger.info(
            "Binance: получено контрактов: %d",
            len(contracts)
        )

        valid_contracts = {}

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

            contract_size = 1.0

            valid_contracts[symbol] = Contract(
                exchange="binance",
                symbol=symbol,
                asset=symbol[:-4],
                quote="USDT",
                contract_type="perpetual",
                active=True,
                contract_size=contract_size,
                contract_size_currency=contract.get(
                    "baseAsset",
                    symbol[:-4]
                ),
            )

        logger.info(
            "Binance: действующих USDT perpetual контрактов: %d",
            len(valid_contracts)
        )

        return valid_contracts

    except Exception:
        logger.exception(
            "Ошибка при получении/проверке контрактов Binance"
        )

        return {}


def get_valid_bitget_contracts() -> dict[str, Contract]:

    try:
        contracts = get_bitget_contracts()

        logger.info(
            "Bitget: получено контрактов: %d",
            len(contracts)
        )

        valid_contracts = {}

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

            base = symbol[:-4]

            contract_size = float(
                contract.get("sizeMultiplayer", 1)
            )

            valid_contracts[symbol] = Contract(
                exchange="bitget",
                symbol=symbol,
                asset=base,
                quote="USDT",
                contract_type="perpetual",
                active=True,
                contract_size=contract_size,
                contract_size_currency=base,
            )

        logger.info(
            "Bitget: действующих USDT perpetual контрактов: %d",
            len(valid_contracts)
        )

        return valid_contracts

    except Exception:
        logger.exception(
            "Ошибка при получении/проверке контрактов Bitget"
        )

        return {}


def get_valid_okx_contracts() -> dict[str, Contract]:

    try:
        contracts = get_okx_contracts()

        logger.info(
            "OKX: получено контрактов: %d",
            len(contracts)
        )

        valid_contracts = {}

        for contract in contracts:

            if contract.get("settleCcy") != "USDT":
                continue

            symbol = contract.get("instId", "")

            if not symbol.endswith("-USDT-SWAP"):
                continue

            if contract.get("state") != "live":
                continue

            base = symbol.split("-")[0]

            ct_val = float(
                contract.get("ctVal", 0)
            )

            ct_val_ccy = contract.get(
                "ctValCcy",
                base
            )

            valid_contracts[symbol] = Contract(
                exchange="okx",
                symbol=symbol,
                asset=base,
                quote="USDT",
                contract_type="perpetual",
                active=True,
                contract_size=ct_val,
                contract_size_currency=ct_val_ccy,
            )

        logger.info(
            "OKX: действующих USDT perpetual контрактов: %d",
            len(valid_contracts)
        )

        return valid_contracts

    except Exception:
        logger.exception(
            "Ошибка при получении/проверке контрактов OKX"
        )

        return {}


def get_valid_contracts() -> dict[str, dict[str, Contract]]:

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
    valid_contracts: dict[str, dict[str, Contract]]
) -> None:

    for market in markets:

        exchange_contracts = valid_contracts.get(
            market.exchange,
            {}
        )

        contract = exchange_contracts.get(
            market.symbol
        )

        market.active = contract is not None

        logger.debug(
            "%s %s: active=%s",
            market.exchange,
            market.symbol,
            market.active
        )


def update_all_market_status(
    exchanges: dict[str, list[Market]],
    valid_contracts: dict[str, dict[str, Contract]]
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

    for exchange, exchange_contracts in contracts.items():

        print(
            f"{exchange}: "
            f"{len(exchange_contracts)} действующих контрактов"
        )

        for symbol, contract in sorted(
            exchange_contracts.items()
            ):
            print(
                f"  {symbol:20}"
                f"size={contract.contract_size}"
                f"  {contract.contract_size_currency}"
                )

        print()

    logger.info(
        "contract_validator.py завершил работу"
    )