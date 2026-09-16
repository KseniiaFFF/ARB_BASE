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

        # logger.info(
        #     "Binance: получено контрактов: %d",
        #     len(contracts)
        # )

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

            filters = {
                item["filterType"]: item
                for item in contract.get("filters", [])
            }

            lot_size = filters.get("LOT_SIZE")
            market_lot_size = filters.get("MARKET_LOT_SIZE")

            if market_lot_size:
                qty_filter = market_lot_size
            elif lot_size:
                qty_filter = lot_size
            else:
                logger.warning(
                    "Binance: нет quantity filter: %s",
                    symbol,
                )
                continue

            min_qty = float(
                qty_filter["minQty"]
            )

            max_qty = float(
                qty_filter["maxQty"]
            )

            qty_step = float(
                qty_filter["stepSize"]
            )

            valid_contracts[symbol] = Contract(
                exchange="binance",
                symbol=symbol,
                asset=symbol[:-4],
                quote="USDT",
                contract_type="perpetual",
                active=True,

                contract_size=1.0,

                contract_size_currency=contract.get(
                    "baseAsset",
                    symbol[:-4]
                ),

                min_qty=min_qty,
                max_qty=max_qty,
                qty_step=qty_step,
            )

        # logger.info(
        #     "Binance: действующих USDT perpetual контрактов: %d",
        #     len(valid_contracts)
        # )

        return valid_contracts

    except Exception:
        logger.exception(
            "Ошибка при получении/проверке контрактов Binance"
        )

        return {}


def get_valid_bitget_contracts() -> dict[str, Contract]:

    try:
        contracts = get_bitget_contracts()

        # logger.info(
        #     "Bitget: получено контрактов: %d",
        #     len(contracts)
        # )

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
                contract.get("sizeMultiplier", 1)
            )

            min_qty = float(
                contract.get("minTradeNum", 0)
            )

            max_qty = float(
                contract.get("maxOrderQty", 0)
            )

            qty_step = float(
                contract.get("sizeMultiplier", 1)
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

                min_qty=min_qty,
                max_qty=max_qty,
                qty_step=qty_step,
            )

        # logger.info(
        #     "Bitget: действующих USDT perpetual контрактов: %d",
        #     len(valid_contracts)
        # )

        return valid_contracts

    except Exception:
        logger.exception(
            "Ошибка при получении/проверке контрактов Bitget"
        )

        return {}


def get_valid_okx_contracts() -> dict[str, Contract]:

    try:
        contracts = get_okx_contracts()

        # logger.info(
        #     "OKX: получено контрактов: %d",
        #     len(contracts)
        # )

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

            min_qty = float(
                contract.get("minSz", 0)
            )

            qty_step = float(
                contract.get("lotSz", 1)
            )

            max_qty = float(
                contract.get("maxLmtSz", 0)
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

                min_qty=min_qty,
                max_qty=max_qty,
                qty_step=qty_step,
            )

        # logger.info(
        #     "OKX: действующих USDT perpetual контрактов: %d",
        #     len(valid_contracts)
        # )

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

        # logger.info(
        #     "%s: активных Market: %d из %d",
        #     exchange,
        #     active_count,
        #     len(markets)
        # )


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
                f" size={contract.contract_size}"
                f" min_qty={contract.min_qty}"
                f" max_qty={contract.max_qty}"
                f" qty_step={contract.qty_step}"
                f"  {contract.contract_size_currency}"
                )

        print()

    logger.info(
        "contract_validator.py завершил работу"
    )