import math

from config import DEPOSIT, RISK_PERC
from models import Contract


def get_position_notional() -> float:

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

    base_quantity = (
        notional_usdt / price
    )

    if contract.exchange == "okx":

        quantity = (
            base_quantity
            / contract.contract_size
        )

    else:

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


def quantity_to_base(
    quantity: float,
    contract: Contract,
) -> float:

    if contract.exchange == "okx":
        return quantity * contract.contract_size

    return quantity


def base_to_quantity(
    base_quantity: float,
    contract: Contract,
) -> float:
    

    if contract.contract_size <= 0:
        raise ValueError(
            f"Invalid contract size: "
            f"{contract.exchange} "
            f"{contract.symbol}"
        )

    if contract.exchange == "okx":
        quantity = (
            base_quantity
            / contract.contract_size
        )
    else:
        quantity = base_quantity

    return quantity


def get_actual_notional(
    quantity: float,
    price: float,
    contract: Contract,
) -> float:
    

    base_quantity = quantity_to_base(
        quantity=quantity,
        contract=contract,
    )

    return base_quantity * price


def calculate_pair_position(
    notional_usdt: float,
    buy_price: float,
    sell_price: float,
    buy_contract: Contract,
    sell_contract: Contract,
) -> dict:
    

    if notional_usdt <= 0:
        raise ValueError(
            "notional_usdt must be > 0"
        )

    if buy_price <= 0:
        raise ValueError(
            "buy_price must be > 0"
        )

    if sell_price <= 0:
        raise ValueError(
            "sell_price must be > 0"
        )

    for contract in (
        buy_contract,
        sell_contract,
    ):
        if contract.contract_size <= 0:
            raise ValueError(
                f"Invalid contract size: "
                f"{contract.exchange} "
                f"{contract.symbol}"
            )

        if contract.qty_step <= 0:
            raise ValueError(
                f"Invalid quantity step: "
                f"{contract.exchange} "
                f"{contract.symbol}: "
                f"{contract.qty_step}"
            )


    desired_base_quantity = (
        notional_usdt / buy_price
    )


    buy_min_base = quantity_to_base(
        quantity=buy_contract.min_qty,
        contract=buy_contract,
    )

    sell_min_base = quantity_to_base(
        quantity=sell_contract.min_qty,
        contract=sell_contract,
    )

    min_base_quantity = max(
        buy_min_base,
        sell_min_base,
    )


    max_base_quantities = []

    if buy_contract.max_qty > 0:
        max_base_quantities.append(
            quantity_to_base(
                quantity=buy_contract.max_qty,
                contract=buy_contract,
            )
        )

    if sell_contract.max_qty > 0:
        max_base_quantities.append(
            quantity_to_base(
                quantity=sell_contract.max_qty,
                contract=sell_contract,
            )
        )

    if max_base_quantities:
        max_base_quantity = min(
            max_base_quantities
        )
    else:
        max_base_quantity = None


    base_quantity = desired_base_quantity

    if max_base_quantity is not None:
        base_quantity = min(
            base_quantity,
            max_base_quantity,
        )


    buy_quantity = base_to_quantity(
        base_quantity=base_quantity,
        contract=buy_contract,
    )

    sell_quantity = base_to_quantity(
        base_quantity=base_quantity,
        contract=sell_contract,
    )

    buy_quantity = round_down(
        buy_quantity,
        buy_contract.qty_step,
    )

    sell_quantity = round_down(
        sell_quantity,
        sell_contract.qty_step,
    )


    buy_base_quantity = quantity_to_base(
        quantity=buy_quantity,
        contract=buy_contract,
    )

    sell_base_quantity = quantity_to_base(
        quantity=sell_quantity,
        contract=sell_contract,
    )

    base_quantity = min(
        buy_base_quantity,
        sell_base_quantity,
    )


    buy_quantity = round_down(
        base_to_quantity(
            base_quantity,
            buy_contract,
        ),
        buy_contract.qty_step,
    )

    sell_quantity = round_down(
        base_to_quantity(
            base_quantity,
            sell_contract,
        ),
        sell_contract.qty_step,
    )


    buy_base_quantity = quantity_to_base(
        buy_quantity,
        buy_contract,
    )

    sell_base_quantity = quantity_to_base(
        sell_quantity,
        sell_contract,
    )


    if buy_quantity < buy_contract.min_qty:
        return {
            "possible": False,
            "reason": "buy quantity below minimum",
        }

    if sell_quantity < sell_contract.min_qty:
        return {
            "possible": False,
            "reason": "sell quantity below minimum",
        }


    actual_base_quantity = min(
        buy_base_quantity,
        sell_base_quantity,
    )

    buy_actual_notional = (
        actual_base_quantity * buy_price
    )

    sell_actual_notional = (
        actual_base_quantity * sell_price
    )

    hedge_difference_base = abs(
        buy_base_quantity
        - sell_base_quantity
    )

    hedge_difference_percent = 0.0

    if actual_base_quantity > 0:
        hedge_difference_percent = (
            hedge_difference_base
            / actual_base_quantity
            * 100
        )

    return {
        "possible": True,

        "buy_quantity": buy_quantity,
        "sell_quantity": sell_quantity,

        "buy_base_quantity": buy_base_quantity,
        "sell_base_quantity": sell_base_quantity,

        "desired_base_quantity": desired_base_quantity,

        "actual_base_quantity": actual_base_quantity,

        "buy_actual_notional": buy_actual_notional,
        "sell_actual_notional": sell_actual_notional,

        "hedge_difference_base": hedge_difference_base,
        "hedge_difference_percent": hedge_difference_percent,
    }


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
