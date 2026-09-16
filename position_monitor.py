from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Callable

from price_feeds.models_price import Price


@dataclass(slots=True)
class OpenPosition:
    asset: str
    buy_exchange: str
    buy_symbol: str
    buy_quantity: float
    buy_average_price: float
    sell_exchange: str
    sell_symbol: str
    sell_quantity: float
    sell_average_price: float
    buy_fee_percent: float
    sell_fee_percent: float
    opened_at_ms: int


@dataclass(slots=True)
class ExitSnapshot:
    buy_exit_price: float
    sell_exit_price: float
    gross_pnl_usdt: float
    entry_fee_usdt: float
    exit_fee_usdt: float
    net_pnl_usdt: float
    gross_pnl_percent: float
    net_pnl_percent: float
    timestamp_diff_ms: int | None
    buy_age_ms: int | None
    sell_age_ms: int | None


class PositionMonitor:
    POLL_INTERVAL_SEC = 0.02
    PRICE_MAX_AGE_MS = 500

    def __init__(self, price_cache: dict[str, dict[str, Price]]) -> None:
        self.price_cache = price_cache
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def reset(self) -> None:
        self._stop_event.clear()

    def get_snapshot(self, position: OpenPosition) -> ExitSnapshot | None:
        buy_price = self.price_cache.get(position.asset, {}).get(position.buy_exchange)
        sell_price = self.price_cache.get(position.asset, {}).get(position.sell_exchange)

        if buy_price is None or sell_price is None:
            return None

        now_ms = int(time.time() * 1000)
        buy_age_ms = now_ms - buy_price.received_at
        sell_age_ms = now_ms - sell_price.received_at

        if buy_age_ms < 0 or sell_age_ms < 0:
            return None

        if buy_age_ms > self.PRICE_MAX_AGE_MS or sell_age_ms > self.PRICE_MAX_AGE_MS:
            return None

        if buy_price.symbol != position.buy_symbol or sell_price.symbol != position.sell_symbol:
            return None

        if buy_price.bid <= 0 or sell_price.ask <= 0:
            return None

        # Close the long leg at BID and the short leg at ASK.
        buy_exit_price = buy_price.bid
        sell_exit_price = sell_price.ask

        # Binance / Bitget quantities are base-asset units.
        # OKX quantity is contracts. Use the non-OKX leg as the
        # common base quantity for the cross-exchange pair.
        if position.buy_exchange == "okx":
            buy_base_quantity = position.sell_quantity
        else:
            buy_base_quantity = position.buy_quantity

        if position.sell_exchange == "okx":
            sell_base_quantity = position.buy_quantity
        else:
            sell_base_quantity = position.sell_quantity

        long_pnl = (buy_exit_price - position.buy_average_price) * buy_base_quantity
        short_pnl = (position.sell_average_price - sell_exit_price) * sell_base_quantity
        gross_pnl_usdt = long_pnl + short_pnl

        entry_buy_notional = position.buy_average_price * buy_base_quantity
        entry_sell_notional = position.sell_average_price * sell_base_quantity
        exit_buy_notional = buy_exit_price * buy_base_quantity
        exit_sell_notional = sell_exit_price * sell_base_quantity

        entry_fee_usdt = (
            entry_buy_notional * position.buy_fee_percent / 100
            + entry_sell_notional * position.sell_fee_percent / 100
        )
        exit_fee_usdt = (
            exit_buy_notional * position.buy_fee_percent / 100
            + exit_sell_notional * position.sell_fee_percent / 100
        )

        net_pnl_usdt = gross_pnl_usdt - entry_fee_usdt - exit_fee_usdt
        position_notional = max(entry_buy_notional, entry_sell_notional)

        if position_notional > 0:
            gross_pnl_percent = gross_pnl_usdt / position_notional * 100
            net_pnl_percent = net_pnl_usdt / position_notional * 100
        else:
            gross_pnl_percent = 0.0
            net_pnl_percent = 0.0

        timestamp_diff_ms = None
        if buy_price.timestamp > 0 and sell_price.timestamp > 0:
            timestamp_diff_ms = abs(buy_price.timestamp - sell_price.timestamp)

        return ExitSnapshot(
            buy_exit_price=buy_exit_price,
            sell_exit_price=sell_exit_price,
            gross_pnl_usdt=gross_pnl_usdt,
            entry_fee_usdt=entry_fee_usdt,
            exit_fee_usdt=exit_fee_usdt,
            net_pnl_usdt=net_pnl_usdt,
            gross_pnl_percent=gross_pnl_percent,
            net_pnl_percent=net_pnl_percent,
            timestamp_diff_ms=timestamp_diff_ms,
            buy_age_ms=buy_age_ms,
            sell_age_ms=sell_age_ms,
        )

    def should_close(self, snapshot: ExitSnapshot) -> bool:
        # Close when the combined two-leg NET PnL reaches the configured
        # minimum profit. NET already includes both entry fees and the
        # current executable exit fees calculated in get_snapshot().
        TARGET_NET_PROFIT_PERCENT = 0.20
        return snapshot.net_pnl_percent >= TARGET_NET_PROFIT_PERCENT

    async def monitor(
        self,
        position: OpenPosition,
        should_close: Callable[[ExitSnapshot], bool] | None = None,
        on_update: Callable[[ExitSnapshot], None] | None = None,
    ) -> ExitSnapshot | None:
        self.reset()

        while not self._stop_event.is_set():
            snapshot = self.get_snapshot(position)

            if snapshot is not None:
                if on_update is not None:
                    on_update(snapshot)

                close_condition = (
                    should_close
                    if should_close is not None
                    else self.should_close
                )

                if close_condition(snapshot):
                    return snapshot

            await asyncio.sleep(self.POLL_INTERVAL_SEC)

        return None
