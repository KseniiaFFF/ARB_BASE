from exchanges.binance import get_taker_fee as get_binance_fee
from exchanges.bitget import get_taker_fee as get_bitget_fee
from exchanges.okx import get_taker_fee as get_okx_fee


fee_cache: dict[tuple[str, str], float] = {}


def get_fee(
    exchange: str,
    symbol: str,
) -> float:

    key = (exchange, symbol)

    if key in fee_cache:
        return fee_cache[key]

    if exchange == "binance":
        fee = get_binance_fee(symbol)

    elif exchange == "bitget":
        fee = get_bitget_fee(symbol)

    elif exchange == "okx":
        fee = get_okx_fee(symbol)

    else:
        raise ValueError(
            f"Unknown exchange: {exchange}"
        )

    fee_cache[key] = fee

    return fee


if __name__ == "__main__":
    fee = get_binance_fee("龙虾USDT")

    print(
        f"binance taker fee: {fee:.4f}%"
    )