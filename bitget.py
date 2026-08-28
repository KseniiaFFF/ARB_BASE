import requests
import os
import hmac
import hashlib 
import base64
import time

from models import Market
from config import BASE_URL_BITGET
from dotenv import load_dotenv

load_dotenv()


def sign(
        timestamp: str,
        method: str,
        request_path: str,
        body: str,
        secret_key: str,
) -> str:

    message = (
        timestamp + method.upper() + request_path + body
    )

    digest = hmac.new(
        secret_key.encode(),
        message.encode(),
        hashlib.sha256,
    ).digest()

    return base64.b64encode(digest).decode()


def get_taker_fee(symbol: str) -> float:

    api_key = os.getenv("API_KEY_BIT")
    secret_key = os.getenv("SECRET_KEY_BIT")
    passphrase = os.getenv("PASSPHRASE_BIT")

    if not api_key or not secret_key or not passphrase:
        raise RuntimeError(
            "Bitget API credentials are not configured"
        )

    timestamp = str(
        int(time.time() * 1000)
    )

    method = "GET"

    request_path = (
        "/api/v2/common/trade-rate"
    )

    params = {
        "symbol": symbol,
        "businessType": "mix",
    }

    query = "&".join(
        f"{key}={value}"
        for key, value in sorted(params.items())
    )

    signed_path = (
        f"{request_path}?{query}"
    )

    signature = sign(
        timestamp=timestamp,
        method=method,
        request_path=signed_path,
        body="",
        secret_key=secret_key,
    )

    headers = {
        "ACCESS-KEY": api_key,
        "ACCESS-SIGN": signature,
        "ACCESS-TIMESTAMP": timestamp,
        "ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json",
        "locale": "en-US",
    }

    response = requests.get(
        f"{BASE_URL_BITGET}{signed_path}",
        headers=headers,
        timeout=5,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Bitget HTTP {response.status_code}: "
            f"{response.text}"
        )

    data = response.json()

    if data.get("code") != "00000":
        raise RuntimeError(
            f"Bitget API error: {data}"
        )

    fee_data = data.get("data")

    if not fee_data:
        raise RuntimeError(
            f"Bitget fee data is empty: {data}"
        )

    taker_fee_rate = fee_data.get(
        "takerFeeRate"
    )

    if taker_fee_rate is None:
        raise RuntimeError(
            f"Bitget takerFeeRate is missing: {data}"
        )

    return float(taker_fee_rate) * 100


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
                asset=symbol[:-4],
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