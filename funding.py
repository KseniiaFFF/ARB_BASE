import requests


BASE_URL = "https://fapi.binance.com"
TOP_N = 5


def get_top_funding(limit: int = TOP_N):

    url = f"{BASE_URL}/fapi/v1/premiumIndex"

    response = requests.get(url, timeout=10)
    response.raise_for_status()

    data = response.json()

    funding_data = []

    for item in data:
        symbol = item.get("symbol", "")
        funding_rate = item.get("lastFundingRate")

        if not symbol.endswith("USDT"):
            continue

        if funding_rate is None:
            continue

        funding_rate = float(funding_rate)

        funding_data.append({
            "symbol": symbol,
            "funding_rate": funding_rate,
            "funding_percent": funding_rate * 100,
            "abs_funding": abs(funding_rate),
        })

    funding_data.sort(
        key=lambda x: x["abs_funding"],
        reverse=True
    )

    return funding_data[:limit]


def print_top_funding(limit: int = TOP_N):
    top = get_top_funding(limit)

    print("\nBINANCE FUTURES — TOP 5 ABSOLUTE FUNDING")
    print("-" * 65)

    for i, item in enumerate(top, start=1):
        symbol = item["symbol"]
        funding_percent = item["funding_percent"]

        if funding_percent > 0:
            direction = "LONG pays SHORT"
        elif funding_percent < 0:
            direction = "SHORT pays LONG"
        else:
            direction = "-"

        print(
            f"{i}. {symbol:<15} "
            f"{funding_percent:+.5f}%   "
            f"{direction}"
        )

    print("-" * 65)


if __name__ == "__main__":
    print_top_funding()