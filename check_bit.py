import asyncio

from trading.bitget import BitgetClient
from dotenv import load_dotenv

load_dotenv()


async def main() -> None:
    client = BitgetClient()

    try:
        data = await client._request(
            "GET",
            "/api/v2/mix/account/account",
            params={
                "symbol": "BTCUSDT",
                "productType": "USDT-FUTURES",
                "marginCoin": "USDT",
            },
        )

        row = data.get("data") or {}

        print("BITGET ACCOUNT MODE")
        print("-------------------")
        print("holdMode:", row.get("holdMode"))
        print("marginMode:", row.get("marginMode"))
        print("assetMode:", row.get("assetMode"))
        print()
        print("FULL ACCOUNT DATA:")
        print(row)

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
