import requests

from config import BASE_URL_BINANCE
from models import Market

def get_futures_contracts() -> list[dict]:

    url = f"{BASE_URL_BINANCE}/fapi/v1/exchangeInfo"

    response = requests.get(
        url,
        timeout=10,
    )
    response.raise_for_status()

    data = response.json()

    return data["symbols"]


def get_futures_markets() -> list[Market]:

    url = f"{BASE_URL_BINANCE}/fapi/v1/ticker/24hr"

    response = requests.get(
        url,
        timeout=10,
    )
    response.raise_for_status()

    tickers = response.json()

    markets = []

    for ticker in tickers:
        symbol = ticker["symbol"]

        if not symbol.endswith("USDT"):
            continue

        if "_" in symbol:
            continue

        markets.append(
            Market(
                base=symbol[:-4],
                quote="USDT",
                symbol=symbol,
                exchange="binance",
                volume_24h=float(ticker["quoteVolume"]),
                active=False,
                contract_type="perpetual",
            )
        )

    return markets