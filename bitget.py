import requests

from models import Market
from config import BASE_URL_BITGET


def get_futures_contracts() -> list[dict]:

    url = f"{BASE_URL_BITGET}/api/v2/mix/market/contracts"

    params = {
        "productType": "USDT-FUTURES",
    }

    response = requests.get(
        url,
        params=params,
        timeout=10,
    )
    response.raise_for_status()

    data = response.json()

    if data.get("code") != "00000":
        raise RuntimeError(
            f"Bitget API error: {data}"
        )

    return data["data"]


def get_futures_markets() -> list[Market]:

    url = f"{BASE_URL_BITGET}/api/v2/mix/market/tickers"

    params = {
        "productType": "USDT-FUTURES",
    }

    response = requests.get(
        url,
        params=params,
        timeout=10,
    )

    response.raise_for_status()

    data = response.json()

    if data.get("code") != "00000":
        raise RuntimeError(
            f"Bitget API error: {data}"
        )

    markets = []

    for ticker in data.get("data", []):

        symbol = ticker.get("symbol")

        if not symbol:
            continue

        if not symbol.endswith("USDT"):
            continue

        volume = ticker.get("usdtVolume")

        if volume is None:
            continue

        try:
            volume_24h = float(volume)
        except (TypeError, ValueError):
            continue

        markets.append(
            Market(
                base=symbol[:-4],
                quote="USDT",
                symbol=symbol,
                exchange="bitget",
                volume_24h=volume_24h,
                active=False,
                contract_type="perpetual",
            )
        )

    return markets