from __future__ import annotations

import logging
import time
from collections import defaultdict

logger = logging.getLogger(__name__)

_samples: dict[str, list[int]] = defaultdict(list)
_ws_updates: dict[tuple[str, str], int] = {}
_last_log_ns = time.monotonic_ns()

MAX_SAMPLES_PER_STAGE = 20_000


def start() -> int:
    return time.perf_counter_ns()


def record(stage: str, started_ns: int) -> None:
    elapsed = time.perf_counter_ns() - started_ns
    values = _samples[stage]
    values.append(elapsed)

    if len(values) > MAX_SAMPLES_PER_STAGE:
        del values[:len(values) - MAX_SAMPLES_PER_STAGE]


def mark_ws_update(asset: str, exchange: str) -> None:
    _ws_updates[(asset, exchange)] = time.monotonic_ns()


def consume_ws_to_scanner_latency(now_ns: int | None = None) -> None:
    global _last_log_ns

    if now_ns is None:
        now_ns = time.monotonic_ns()

    if _ws_updates:
        items = tuple(_ws_updates.items())
        _ws_updates.clear()

        for _, update_ns in items:
            if update_ns <= now_ns:
                # Direct append avoids using record(), because this is
                # a timestamp-to-timestamp measurement rather than a span.
                values = _samples["ws_to_scanner"]
                values.append(now_ns - update_ns)
                if len(values) > MAX_SAMPLES_PER_STAGE:
                    del values[:len(values) - MAX_SAMPLES_PER_STAGE]

    if now_ns - _last_log_ns < 1_000_000_000:
        return

    _last_log_ns = now_ns
    log_stats()


def log_stats() -> None:
    for stage, values in list(_samples.items()):
        if not values:
            continue

        ordered = sorted(values)

        def percentile(p: float) -> float:
            index = int((len(ordered) - 1) * p)
            return ordered[index] / 1_000_000.0

        avg = sum(ordered) / len(ordered) / 1_000_000.0

        # logger.info(
        #     "LATENCY | %-24s samples=%d avg=%.3f ms "
        #     "p50=%.3f p95=%.3f p99=%.3f max=%.3f ms",
        #     stage,
        #     len(ordered),
        #     avg,
        #     percentile(0.50),
        #     percentile(0.95),
        #     percentile(0.99),
        #     ordered[-1] / 1_000_000.0,
        # )
