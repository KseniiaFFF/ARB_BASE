import asyncio
import functools
import logging
import threading
import time
from collections import defaultdict, deque

logger = logging.getLogger(__name__)
_MAX_SAMPLES = 5000
_stats = defaultdict(lambda: {"calls": 0, "total_ns": 0, "max_ns": 0, "samples": deque(maxlen=_MAX_SAMPLES)})
_lock = threading.Lock()
_last_report_ns = time.monotonic_ns()

def record(name: str, elapsed_ns: int) -> None:
    with _lock:
        s = _stats[name]
        s["calls"] += 1
        s["total_ns"] += elapsed_ns
        s["max_ns"] = max(s["max_ns"], elapsed_ns)
        s["samples"].append(elapsed_ns)

def _percentile(samples, q):
    if not samples:
        return 0
    values = sorted(samples)
    return values[int((len(values) - 1) * q)]

def log_report(force: bool = False) -> None:
    global _last_report_ns
    now = time.monotonic_ns()
    if not force and now - _last_report_ns < 1_000_000_000:
        return
    with _lock:
        snapshot = {name: {"calls": s["calls"], "total_ns": s["total_ns"], "max_ns": s["max_ns"], "samples": list(s["samples"])} for name, s in _stats.items()}
    _last_report_ns = now
    if not snapshot:
        return
    lines = ["========== SCANNER PERFORMANCE =========="]
    for name, s in sorted(snapshot.items(), key=lambda item: item[1]["total_ns"], reverse=True):
        calls = s["calls"]
        total_ms = s["total_ns"] / 1_000_000
        avg_ms = total_ms / calls if calls else 0
        p50_ms = _percentile(s["samples"], .50) / 1_000_000
        p95_ms = _percentile(s["samples"], .95) / 1_000_000
        p99_ms = _percentile(s["samples"], .99) / 1_000_000
        max_ms = s["max_ns"] / 1_000_000
        lines.append(f"PERF {name:<35} calls={calls:>7} total={total_ms:>10.3f} ms avg={avg_ms:>8.4f} ms p50={p50_ms:>8.4f} ms p95={p95_ms:>8.4f} ms p99={p99_ms:>8.4f} ms max={max_ms:>8.4f} ms")
    lines.append("=========================================")
    logger.info("\n".join(lines))

def profiled(func):
    if asyncio.iscoroutinefunction(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            started = time.perf_counter_ns()
            try:
                return await func(*args, **kwargs)
            finally:
                record(func.__name__, time.perf_counter_ns() - started)
                log_report()
        return async_wrapper
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        started = time.perf_counter_ns()
        try:
            return func(*args, **kwargs)
        finally:
            record(func.__name__, time.perf_counter_ns() - started)
            log_report()
    return wrapper

class profile_block:
    def __init__(self, name: str):
        self.name = name
    def __enter__(self):
        self.started = time.perf_counter_ns()
        return self
    def __exit__(self, exc_type, exc, tb):
        record(self.name, time.perf_counter_ns() - self.started)
        log_report()
        return False
