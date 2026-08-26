import requests

from models import Market
from config import BASE_URL_OKX


def get_futures_contracts() -> list[dict]:

    url = f"{BASE_URL_OKX}/api/v5/public/instruments"

    params = {
        "instType": "SWAP",
    }

    response = requests.get(
        url,
        params=params,
        timeout=10,
    )
    response.raise_for_status()

    data = response.json()

    if data.get("code") != "0":
        raise RuntimeError(
            f"OKX API error: {data}"
        )

    return data["data"]


def get_futures_markets() -> list[Market]:

    url = f"{BASE_URL_OKX}/api/v5/market/tickers"

    params = {
        "instType": "SWAP",
    }

    response = requests.get(
        url,
        params=params,
        timeout=10,
    )
    response.raise_for_status()

    data = response.json()

    if data.get("code") != "0":
        raise RuntimeError(
            f"OKX API error: {data}"
        )

    markets = []

    for ticker in data["data"]:
        symbol = ticker["instId"]

        if not symbol.endswith("-USDT-SWAP"):
            continue

        base = symbol.split("-")[0]

        last_price = float(ticker["last"])

        volume_base = float(ticker["volCcy24h"])

        volume_usdt = volume_base * last_price

        markets.append(
            Market(
                base=base,
                quote="USDT",
                symbol=symbol,
                exchange="okx",
                volume_24h=volume_usdt,
                active=False,
                contract_type="perpetual",
            )
        )

    return markets