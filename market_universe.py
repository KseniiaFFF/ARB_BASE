from config import MIN_VOLUME_BINANCE
from models import Market

from exchanges.binance import get_futures_markets as get_binance_markets
from exchanges.bitget import get_futures_markets as get_bitget_markets
from exchanges.okx import get_futures_markets as get_okx_markets
from contract_validator import get_valid_contracts, update_market_status


def build_universe() -> dict[str, list[Market]]:

    exchanges = {
        "binance": get_binance_markets(),
        "bitget": get_bitget_markets(),
        "okx": get_okx_markets(),
    }

    valid_contracts = get_valid_contracts()

    markets_by_coin: dict[str, list[Market]] = {}


    for exchange_markets in exchanges.values():

        update_market_status(
            exchange_markets,
            valid_contracts
        )


    for market in exchanges["binance"]:

        if not market.active:
            continue

        if market.volume_24h < MIN_VOLUME_BINANCE:
            continue

        markets_by_coin[market.base] = [market]


    for exchange_name in ("bitget", "okx"):

        for market in exchanges[exchange_name]:

            if not market.active:
                continue

            if market.base not in markets_by_coin:
                continue

            markets_by_coin[market.base].append(market)


    return {
        coin: markets
        for coin, markets in markets_by_coin.items()
        if len(markets) >= 2
    }


if __name__ == "__main__":
    universe = build_universe()

    print(f"Найдено монет: {len(universe)}")
    print()

    for coin, markets in universe.items():

        print(coin)

        for market in markets:
            print(
                f"  {market.exchange:10} "
                f"{market.symbol:20} "
                f"${market.volume_24h:,.0f}"
            )

        print()