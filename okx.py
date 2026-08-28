import requests
import logging
import os
import time
import hmac
import hashlib
import base64

from models import Market
from config import BASE_URL_OKX
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def sign(
    timestamp: str,
    method: str,
    request_path: str,
    body: str,
    secret_key: str,
) -> str:

    message = (
        timestamp
        + method.upper()
        + request_path
        + body
    )

    digest = hmac.new(
        secret_key.encode(),
        message.encode(),
        hashlib.sha256,
    ).digest()

    return base64.b64encode(digest).decode()


def get_taker_fee(symbol: str) -> float:

    api_key = os.getenv("API_KEY_OKX")
    secret_key = os.getenv("SECRET_KEY_OKX")
    passphrase = os.getenv("PASSPHRASE_OKX")

    if not api_key or not secret_key or not passphrase:
        raise RuntimeError(
            "OKX API credentials are not configured"
        )


    if symbol.endswith("-SWAP"):
        inst_family = symbol[:-5]

    elif "-" in symbol:
        inst_family = symbol

    elif symbol.endswith("USDT"):
        inst_family = f"{symbol[:-4]}-USDT"

    else:
        raise ValueError(
            f"Unsupported OKX symbol format: {symbol}"
        )

    timestamp = (
        time.strftime(
            "%Y-%m-%dT%H:%M:%S.000Z",
            time.gmtime(),
        )
    )

    method = "GET"

    request_path = (
        "/api/v5/account/trade-fee"
    )

    params = {
        "instType": "SWAP",
        "instFamily": inst_family,
    }

    query = "&".join(
        f"{key}={value}"
        for key, value in params.items()
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
        "OK-ACCESS-KEY": api_key,
        "OK-ACCESS-SIGN": signature,
        "OK-ACCESS-TIMESTAMP": timestamp,
        "OK-ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json",
    }

    response = requests.get(
        f"{BASE_URL_OKX}{signed_path}",
        headers=headers,
        timeout=5,
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"OKX HTTP {response.status_code}: "
            f"{response.text}"
        )

    data = response.json()

    if data.get("code") != "0":
        raise RuntimeError(
            f"OKX API error: {data}"
        )

    fee_data = data.get("data")

    if not fee_data:
        raise RuntimeError(
            f"OKX fee data is empty: {data}"
        )

    fee_group = fee_data[0].get("feeGroup")

    if not fee_group:
        raise RuntimeError(
            f"OKX feeGroup is missing: {data}"
        )

    taker = fee_group[0].get("taker")

    if taker is None:
        raise RuntimeError(
            f"OKX taker fee is missing: {data}"
        )


    return abs(float(taker)) * 100


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

        last = ticker.get("last")

        if not last:
            continue

        try:

            last_price = float(last)

        except (TypeError, ValueError):
            logger.warning(
                "OKX: некорректный last price: %r | ticker=%s",
                last,
                ticker,
            )
            continue

        volume_base = float(ticker["volCcy24h"])

        volume_usdt = volume_base * last_price

        markets.append(
            Market(
                asset=base,
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