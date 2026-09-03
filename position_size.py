import math

from config import DEPOSIT, RISK_PERC
from models import Contract


def get_position_notional() -> float:
    """
    USDT-номинал одной условной арбитражной позиции.
    """

    return DEPOSIT * RISK_PERC / 100


def round_down(
    value: float,
    step: float,
) -> float:

    if step <= 0:
        raise ValueError(
            f"Invalid quantity step: {step}"
        )

    return math.floor(
        value / step
    ) * step


def calculate_position_quantity(
    notional_usdt: float,
    price: float,
    contract: Contract,
) -> float:

    if notional_usdt <= 0:
        raise ValueError(
            "notional_usdt must be > 0"
        )

    if price <= 0:
        raise ValueError(
            "price must be > 0"
        )

    if contract.contract_size <= 0:
        raise ValueError(
            f"Invalid contract size: "
            f"{contract.exchange} "
            f"{contract.symbol}"
        )

    # Сколько базовой валюты хотим купить/продать.
    base_quantity = (
        notional_usdt / price
    )

    if contract.exchange == "okx":

        # OKX quantity = количество контрактов.
        quantity = (
            base_quantity
            / contract.contract_size
        )

    else:

        # Binance / Bitget quantity =
        # количество базового актива.
        quantity = base_quantity

    quantity = round_down(
        quantity,
        contract.qty_step,
    )

    if quantity < contract.min_qty:
        return 0.0

    if (
        contract.max_qty > 0
        and quantity > contract.max_qty
    ):
        quantity = round_down(
            contract.max_qty,
            contract.qty_step,
        )

    return quantity


def get_actual_notional(
    quantity: float,
    price: float,
    contract: Contract,
) -> float:

    if contract.exchange == "okx":

        base_quantity = (
            quantity
            * contract.contract_size
        )

    else:

        base_quantity = quantity

    return base_quantity * price


def calculate_position(
    notional_usdt: float,
    price: float,
    contract: Contract,
) -> dict:

    quantity = calculate_position_quantity(
        notional_usdt=notional_usdt,
        price=price,
        contract=contract,
    )

    if quantity <= 0:
        return {
            "possible": False,
            "quantity": 0.0,
            "actual_notional": 0.0,
        }

    actual_notional = get_actual_notional(
        quantity=quantity,
        price=price,
        contract=contract,
    )

    return {
        "possible": True,
        "quantity": quantity,
        "actual_notional": actual_notional,
    }