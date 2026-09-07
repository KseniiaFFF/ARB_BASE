import requests
import os
import time
import hmac 
import hashlib

from config import BASE_URL_BINANCE
from models import Market
from dotenv import load_dotenv
from urllib.parse import urlencode


load_dotenv()

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
                asset=symbol[:-4],
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


def get_taker_fee(symbol: str) -> float:

    api_key = os.getenv("API_KEY_BINANCE")
    secret_key = os.getenv("SECRET_KEY_BINANCE")

    if not api_key or not secret_key:
        raise RuntimeError(
            "Binance API credentials are not configured"
        )

    timestamp = int(time.time() * 1000)

    params = {
        "symbol": symbol,
        "timestamp": timestamp,
        "recvWindow": 5000,
    }


    query_string = urlencode(
            params,
            safe=""
        )

    signature = hmac.new(
            secret_key.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    params["signature"] = signature

    response = requests.get(
        f"{BASE_URL_BINANCE}/fapi/v1/commissionRate",
        params=params,
        headers={
            "X-MBX-APIKEY": api_key,
        },
        timeout=5,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Binance commission error: "
            f"symbol={symbol}, "
            f"HTTP={response.status_code}, "
            f"response={response.text}"
        )


    data = response.json()

    taker_rate = data.get(
        "takerCommissionRate"
    )

    if taker_rate is None:
        raise RuntimeError(
            f"Binance taker commission is missing: "
            f"{data}"
        )

    return float(taker_rate) * 100
