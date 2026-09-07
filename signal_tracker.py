import csv
import logging
import os
import time
from dataclasses import dataclass
from typing import Iterable


logger = logging.getLogger(__name__)


DEFAULT_STATS_FILE = "signal_lifetime.csv"


@dataclass(slots=True)
class SignalState:

    key: tuple[str, str, str]

    asset: str

    buy_exchange: str
    sell_exchange: str

    buy_symbol: str
    sell_symbol: str

    started_at_ms: int
    started_at_ns: int

    last_seen_at_ms: int
    last_seen_at_ns: int

    samples: int

    start_net_profit_percent: float
    last_net_profit_percent: float

    max_net_profit_percent: float
    min_net_profit_percent: float

    start_raw_spread_percent: float
    last_raw_spread_percent: float

    max_raw_spread_percent: float
    min_raw_spread_percent: float

    max_execution_spread_percent: float
    min_execution_spread_percent: float

    max_buy_slippage_percent: float
    max_sell_slippage_percent: float

    position_notional: float

    last_buy_price: float
    last_sell_price: float

    last_buy_execution_price: float
    last_sell_execution_price: float

    last_timestamp_diff_ms: int | None

    last_buy_orderbook_age_ms: int | None
    last_sell_orderbook_age_ms: int | None


class SignalTracker:
    

    CSV_FIELDS = [
        "signal_id",

        "asset",

        "buy_exchange",
        "buy_symbol",

        "sell_exchange",
        "sell_symbol",

        "started_at_ms",
        "ended_at_ms",

        "lifetime_ms",

        "samples",

        "start_net_profit_percent",
        "end_net_profit_percent",

        "max_net_profit_percent",
        "min_net_profit_percent",

        "start_raw_spread_percent",
        "end_raw_spread_percent",

        "max_raw_spread_percent",
        "min_raw_spread_percent",

        "max_execution_spread_percent",
        "min_execution_spread_percent",

        "max_buy_slippage_percent",
        "max_sell_slippage_percent",

        "position_notional",

        "last_buy_price",
        "last_sell_price",

        "last_buy_execution_price",
        "last_sell_execution_price",

        "last_timestamp_diff_ms",

        "last_buy_orderbook_age_ms",
        "last_sell_orderbook_age_ms",

        "close_reason",
    ]

    def __init__(
        self,
        stats_file: str = DEFAULT_STATS_FILE,
    ) -> None:

        self.stats_file = stats_file

        self.active: dict[
            tuple[str, str, str],
            SignalState,
        ] = {}

        self._next_signal_id = 1

        self._ensure_csv()

    def _ensure_csv(self) -> None:

        directory = os.path.dirname(
            self.stats_file
        )

        if directory:
            os.makedirs(
                directory,
                exist_ok=True,
            )

        if os.path.exists(
            self.stats_file
        ):

            return

        try:

            with open(
                self.stats_file,
                "w",
                newline="",
                encoding="utf-8",
            ) as file:

                writer = csv.DictWriter(
                    file,
                    fieldnames=self.CSV_FIELDS,
                )

                writer.writeheader()

        except OSError:

            logger.exception(
                "Не удалось создать файл статистики: %s",
                self.stats_file,
            )

    def _write_closed_signal(
        self,
        state: SignalState,
        ended_at_ms: int,
        lifetime_ms: float,
        close_reason: str,
    ) -> None:
        

        row = {
            "signal_id": self._get_signal_id(state),

            "asset": state.asset,

            "buy_exchange": state.buy_exchange,
            "buy_symbol": state.buy_symbol,

            "sell_exchange": state.sell_exchange,
            "sell_symbol": state.sell_symbol,

            "started_at_ms": state.started_at_ms,
            "ended_at_ms": ended_at_ms,

            "lifetime_ms": round(
                lifetime_ms,
                3,
            ),

            "samples": state.samples,

            "start_net_profit_percent": (
                state.start_net_profit_percent
            ),

            "end_net_profit_percent": (
                state.last_net_profit_percent
            ),

            "max_net_profit_percent": (
                state.max_net_profit_percent
            ),

            "min_net_profit_percent": (
                state.min_net_profit_percent
            ),

            "start_raw_spread_percent": (
                state.start_raw_spread_percent
            ),

            "end_raw_spread_percent": (
                state.last_raw_spread_percent
            ),

            "max_raw_spread_percent": (
                state.max_raw_spread_percent
            ),

            "min_raw_spread_percent": (
                state.min_raw_spread_percent
            ),

            "max_execution_spread_percent": (
                state.max_execution_spread_percent
            ),

            "min_execution_spread_percent": (
                state.min_execution_spread_percent
            ),

            "max_buy_slippage_percent": (
                state.max_buy_slippage_percent
            ),

            "max_sell_slippage_percent": (
                state.max_sell_slippage_percent
            ),

            "position_notional": (
                state.position_notional
            ),

            "last_buy_price": (
                state.last_buy_price
            ),

            "last_sell_price": (
                state.last_sell_price
            ),

            "last_buy_execution_price": (
                state.last_buy_execution_price
            ),

            "last_sell_execution_price": (
                state.last_sell_execution_price
            ),

            "last_timestamp_diff_ms": (
                state.last_timestamp_diff_ms
            ),

            "last_buy_orderbook_age_ms": (
                state.last_buy_orderbook_age_ms
            ),

            "last_sell_orderbook_age_ms": (
                state.last_sell_orderbook_age_ms
            ),

            "close_reason": close_reason,
        }

        try:

            with open(
                self.stats_file,
                "a",
                newline="",
                encoding="utf-8",
            ) as file:

                writer = csv.DictWriter(
                    file,
                    fieldnames=self.CSV_FIELDS,
                )

                writer.writerow(row)

        except OSError:

            logger.exception(
                "Не удалось записать статистику сигнала: %s",
                self.stats_file,
            )

    def _get_signal_id(
        self,
        state: SignalState,
    ) -> int:

        return self._signal_ids.get(
            id(state),
            0,
        )

    _signal_ids: dict[int, int] = {}

    @staticmethod
    def make_key(
        opportunity: dict,
    ) -> tuple[str, str, str]:

        return (
            str(
                opportunity["asset"]
            ).upper(),

            str(
                opportunity["buy_exchange"]
            ).lower(),

            str(
                opportunity["sell_exchange"]
            ).lower(),
        )

    def _start_signal(
        self,
        opportunity: dict,
        now_ms: int,
        now_ns: int,
    ) -> SignalState:
        
        net_profit = float(
            opportunity[
                "net_profit_percent"
            ]
        )

        raw_spread = float(
            opportunity[
                "spread_percent"
            ]
        )

        execution_spread = float(
            opportunity[
                "execution_spread_percent"
            ]
        )

        buy_slippage = float(
            opportunity.get(
                "buy_slippage_percent",
                0.0,
            )
        )

        sell_slippage = float(
            opportunity.get(
                "sell_slippage_percent",
                0.0,
            )
        )

        state = SignalState(

            key=self.make_key(
                opportunity
            ),

            asset=str(
                opportunity["asset"]
            ).upper(),

            buy_exchange=str(
                opportunity["buy_exchange"]
            ).lower(),

            sell_exchange=str(
                opportunity["sell_exchange"]
            ).lower(),

            buy_symbol=str(
                opportunity["buy_symbol"]
            ),

            sell_symbol=str(
                opportunity["sell_symbol"]
            ),

            started_at_ms=now_ms,
            started_at_ns=now_ns,

            last_seen_at_ms=now_ms,
            last_seen_at_ns=now_ns,

            samples=1,

            start_net_profit_percent=net_profit,
            last_net_profit_percent=net_profit,

            max_net_profit_percent=net_profit,
            min_net_profit_percent=net_profit,

            start_raw_spread_percent=raw_spread,
            last_raw_spread_percent=raw_spread,

            max_raw_spread_percent=raw_spread,
            min_raw_spread_percent=raw_spread,

            max_execution_spread_percent=(
                execution_spread
            ),

            min_execution_spread_percent=(
                execution_spread
            ),

            max_buy_slippage_percent=(
                buy_slippage
            ),

            max_sell_slippage_percent=(
                sell_slippage
            ),

            position_notional=float(
                opportunity.get(
                    "position_notional",
                    0.0,
                )
            ),

            last_buy_price=float(
                opportunity.get(
                    "buy_price",
                    0.0,
                )
            ),

            last_sell_price=float(
                opportunity.get(
                    "sell_price",
                    0.0,
                )
            ),

            last_buy_execution_price=float(
                opportunity.get(
                    "buy_execution_price",
                    0.0,
                )
            ),

            last_sell_execution_price=float(
                opportunity.get(
                    "sell_execution_price",
                    0.0,
                )
            ),

            last_timestamp_diff_ms=(
                opportunity.get(
                    "timestamp_diff_ms"
                )
            ),

            last_buy_orderbook_age_ms=(
                opportunity.get(
                    "buy_orderbook_age_ms"
                )
            ),

            last_sell_orderbook_age_ms=(
                opportunity.get(
                    "sell_orderbook_age_ms"
                )
            ),
        )

        signal_id = (
            self._next_signal_id
        )

        self._next_signal_id += 1

        self._signal_ids[
            id(state)
        ] = signal_id

        self.active[
            state.key
        ] = state

        logger.info(
            "SIGNAL START | "
            "#%d | "
            "%s | "
            "%s -> %s | "
            "NET=%.4f%%",
            signal_id,
            state.asset,
            state.buy_exchange,
            state.sell_exchange,
            net_profit,
        )

        return state

    def _update_signal(
        self,
        state: SignalState,
        opportunity: dict,
        now_ms: int,
        now_ns: int,
    ) -> None:

        net_profit = float(
            opportunity[
                "net_profit_percent"
            ]
        )

        raw_spread = float(
            opportunity[
                "spread_percent"
            ]
        )

        execution_spread = float(
            opportunity[
                "execution_spread_percent"
            ]
        )

        buy_slippage = float(
            opportunity.get(
                "buy_slippage_percent",
                0.0,
            )
        )

        sell_slippage = float(
            opportunity.get(
                "sell_slippage_percent",
                0.0,
            )
        )

        state.last_seen_at_ms = now_ms
        state.last_seen_at_ns = now_ns

        state.samples += 1

        state.last_net_profit_percent = (
            net_profit
        )

        state.max_net_profit_percent = max(
            state.max_net_profit_percent,
            net_profit,
        )

        state.min_net_profit_percent = min(
            state.min_net_profit_percent,
            net_profit,
        )

        state.last_raw_spread_percent = (
            raw_spread
        )

        state.max_raw_spread_percent = max(
            state.max_raw_spread_percent,
            raw_spread,
        )

        state.min_raw_spread_percent = min(
            state.min_raw_spread_percent,
            raw_spread,
        )

        state.max_execution_spread_percent = max(
            state.max_execution_spread_percent,
            execution_spread,
        )

        state.min_execution_spread_percent = min(
            state.min_execution_spread_percent,
            execution_spread,
        )

        state.max_buy_slippage_percent = max(
            state.max_buy_slippage_percent,
            buy_slippage,
        )

        state.max_sell_slippage_percent = max(
            state.max_sell_slippage_percent,
            sell_slippage,
        )

        state.last_buy_price = float(
            opportunity.get(
                "buy_price",
                state.last_buy_price,
            )
        )

        state.last_sell_price = float(
            opportunity.get(
                "sell_price",
                state.last_sell_price,
            )
        )

        state.last_buy_execution_price = float(
            opportunity.get(
                "buy_execution_price",
                state.last_buy_execution_price,
            )
        )

        state.last_sell_execution_price = float(
            opportunity.get(
                "sell_execution_price",
                state.last_sell_execution_price,
            )
        )

        state.last_timestamp_diff_ms = (
            opportunity.get(
                "timestamp_diff_ms",
                state.last_timestamp_diff_ms,
            )
        )

        state.last_buy_orderbook_age_ms = (
            opportunity.get(
                "buy_orderbook_age_ms",
                state.last_buy_orderbook_age_ms,
            )
        )

        state.last_sell_orderbook_age_ms = (
            opportunity.get(
                "sell_orderbook_age_ms",
                state.last_sell_orderbook_age_ms,
            )
        )

    def update(
        self,
        opportunities: Iterable[dict],
    ) -> None:

        now_ms = int(
            time.time() * 1000
        )

        now_ns = time.monotonic_ns()

        current_keys: set[
            tuple[str, str, str]
        ] = set()

        for opportunity in opportunities:

            try:

                key = self.make_key(
                    opportunity
                )

                if key in current_keys:

                    continue

                current_keys.add(key)

                state = self.active.get(
                    key
                )

                if state is None:

                    self._start_signal(
                        opportunity,
                        now_ms,
                        now_ns,
                    )

                    continue

                self._update_signal(
                    state,
                    opportunity,
                    now_ms,
                    now_ns,
                )

            except Exception:

                logger.exception(
                    "Ошибка обработки signal tracker"
                )

        active_keys = set(
            self.active.keys()
        )

        disappeared_keys = (
            active_keys
            - current_keys
        )

        for key in disappeared_keys:

            self._close_signal(
                key=key,
                ended_at_ms=now_ms,
                ended_at_ns=now_ns,
                close_reason="DISAPPEARED",
            )


    def _close_signal(
        self,
        key: tuple[str, str, str],
        ended_at_ms: int,
        ended_at_ns: int,
        close_reason: str,
    ) -> None:
        
        state = self.active.pop(
            key,
            None,
        )

        if state is None:

            return

        lifetime_ms = (
            ended_at_ns
            - state.started_at_ns
        ) / 1_000_000

        if lifetime_ms < 0:

            lifetime_ms = 0.0

        signal_id = self._get_signal_id(
            state
        )

        self._write_closed_signal(
            state=state,
            ended_at_ms=ended_at_ms,
            lifetime_ms=lifetime_ms,
            close_reason=close_reason,
        )

        logger.info(
            "SIGNAL END | "
            "#%d | "
            "%s | "
            "%s -> %s | "
            "lifetime=%.3f ms | "
            "samples=%d | "
            "max_net=%.4f%% | "
            "end_net=%.4f%% | "
            "reason=%s",
            signal_id,
            state.asset,
            state.buy_exchange,
            state.sell_exchange,
            lifetime_ms,
            state.samples,
            state.max_net_profit_percent,
            state.last_net_profit_percent,
            close_reason,
        )

        self._signal_ids.pop(
            id(state),
            None,
        )

    def close_all(
        self,
        reason: str = "SHUTDOWN",
    ) -> None:

        if not self.active:

            return

        now_ms = int(
            time.time() * 1000
        )

        now_ns = time.monotonic_ns()

        keys = list(
            self.active.keys()
        )

        for key in keys:

            self._close_signal(
                key=key,
                ended_at_ms=now_ms,
                ended_at_ns=now_ns,
                close_reason=reason,
            )

    def active_count(self) -> int:

        return len(
            self.active
        )

    def get_active_signals(
        self,
    ) -> list[dict]:
        
        now_ns = time.monotonic_ns()

        result = []

        for state in self.active.values():

            lifetime_ms = (
                now_ns
                - state.started_at_ns
            ) / 1_000_000

            result.append(
                {
                    "signal_id": (
                        self._get_signal_id(
                            state
                        )
                    ),

                    "asset": state.asset,

                    "buy_exchange": (
                        state.buy_exchange
                    ),

                    "sell_exchange": (
                        state.sell_exchange
                    ),

                    "lifetime_ms": (
                        lifetime_ms
                    ),

                    "samples": (
                        state.samples
                    ),

                    "start_net_profit_percent": (
                        state.start_net_profit_percent
                    ),

                    "current_net_profit_percent": (
                        state.last_net_profit_percent
                    ),

                    "max_net_profit_percent": (
                        state.max_net_profit_percent
                    ),

                    "min_net_profit_percent": (
                        state.min_net_profit_percent
                    ),
                }
            )

        return result

_tracker: SignalTracker | None = None


def get_signal_tracker(
    stats_file: str = DEFAULT_STATS_FILE,
) -> SignalTracker:

    global _tracker

    if _tracker is None:

        _tracker = SignalTracker(
            stats_file=stats_file
        )

    return _tracker


def update_signal_tracker(
    opportunities: Iterable[dict],
) -> None:

    tracker = get_signal_tracker()

    tracker.update(
        opportunities
    )


def close_signal_tracker(
    reason: str = "SHUTDOWN",
) -> None:
    
    tracker = get_signal_tracker()

    tracker.close_all(
        reason=reason
    )


if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s | "
            "%(levelname)s | "
            "%(message)s"
        ),
    )

    tracker = SignalTracker(
        stats_file="signal_lifetime_test.csv"
    )

    test_opportunity = {
        "asset": "BTC",

        "buy_exchange": "okx",
        "buy_symbol": "BTC-USDT-SWAP",
        "buy_price": 100000.0,

        "sell_exchange": "binance",
        "sell_symbol": "BTCUSDT",
        "sell_price": 100500.0,

        "spread_percent": 0.5,

        "execution_spread_percent": 0.4,

        "net_profit_percent": 0.2,

        "buy_slippage_percent": 0.03,
        "sell_slippage_percent": 0.02,

        "position_notional": 1000.0,

        "buy_execution_price": 100030.0,
        "sell_execution_price": 100430.0,

        "timestamp_diff_ms": 10,

        "buy_orderbook_age_ms": 20,
        "sell_orderbook_age_ms": 15,
    }

    tracker.update(
        [test_opportunity]
    )

    time.sleep(0.1)

    test_opportunity[
        "net_profit_percent"
    ] = 0.35

    tracker.update(
        [test_opportunity]
    )

    time.sleep(0.1)

    tracker.update([])

    print(
        "Тест завершён."
    )