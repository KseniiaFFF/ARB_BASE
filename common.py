
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class TradingAPIError(RuntimeError):
    """Exchange rejected or failed a trading API request."""


@dataclass(slots=True)
class OrderResult:
    exchange: str
    symbol: str
    side: str
    quantity: float
    order_id: str
    client_order_id: str | None
    status: str | None
    raw: dict[str, Any]


@dataclass(slots=True)
class PositionResult:
    exchange: str
    symbol: str
    quantity: float
    entry_price: float
    raw: dict[str, Any]


def require_env(*names: str) -> tuple[str, ...]:
    import os

    values = tuple(os.getenv(name, "").strip() for name in names)
    missing = [name for name, value in zip(names, values) if not value]
    if missing:
        raise RuntimeError(
            "Не заданы переменные окружения: " + ", ".join(missing)
        )
    return values
