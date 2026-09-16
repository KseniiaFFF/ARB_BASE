from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass

from .binance import BinanceClient
from .bitget import BitgetClient
from .common import OrderResult, TradingAPIError
from .okx import OKXClient


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PairExecutionResult:
    buy: OrderResult | None
    sell: OrderResult | None
    success: bool
    error: str | None = None
    buy_filled_quantity: float = 0.0
    sell_filled_quantity: float = 0.0
    buy_average_price: float = 0.0
    sell_average_price: float = 0.0


class PairExecutor:
    """
    Исполняет две ноги одной межбиржевой арбитражной сделки.

    Важные принципы:
    - leverage=1x;
    - Binance/Bitget: текущий режим аккаунта используется без переключения;
    - OKX: текущий long/short mode используется явно через posSide;
    - leverage=1x подготавливается один раз при старте;
    - затем обе market-заявки отправляются конкурентно;
    - если одна заявка не принята, результат возвращается явно;
      при частичном/неудачном входе исполненная нога аварийно закрывается.
    """

    LEVERAGE = 1

    def __init__(self) -> None:
        self.clients = {
            "binance": BinanceClient(),
            "bitget": BitgetClient(),
            "okx": OKXClient(),
        }

    async def start(self) -> None:
        await asyncio.gather(
            *(client.start() for client in self.clients.values())
        )

    async def prepare_leverage(
        self,
        exchange_symbols: dict[str, list[str]],
    ) -> None:
        """
        Set leverage=1x once at startup for all active instruments.

        BTC is deliberately excluded because the account may contain
        existing BTC positions with user-managed leverage.

        Requests are paced per exchange to avoid startup rate limits.
        429 responses are retried with exponential backoff.
        """
        intervals = {
            "binance": 0.25,
            "bitget": 0.25,
            "okx": 0.25,
        }
        max_retries = 5
        counts = {
            "binance": 0,
            "bitget": 0,
            "okx": 0,
        }

        async def set_one(exchange: str, symbol: str) -> None:
            client = self.clients[exchange]
            delay = intervals[exchange]

            for attempt in range(max_retries + 1):
                try:
                    await client.set_leverage(
                        symbol=symbol,
                        leverage=self.LEVERAGE,
                    )
                    return
                except Exception as exc:
                    message = str(exc)

                    if "429" not in message and "Too Many Requests" not in message:
                        raise

                    if attempt >= max_retries:
                        raise

                    backoff = max(delay, 0.5 * (2 ** attempt))
                    await asyncio.sleep(backoff)

        try:
            # Each exchange is prepared independently and sequentially.
            # This avoids bursting one exchange with dozens of requests.
            for exchange in ("binance", "bitget", "okx"):
                symbols = []

                for symbol in exchange_symbols.get(exchange, []):
                    normalized = symbol.replace("-", "").upper()

                    if normalized in {"BTCUSDT", "BTCUSDT-SWAP"}:
                        continue

                    symbols.append(symbol)

                for index, symbol in enumerate(symbols):
                    await set_one(exchange, symbol)
                    counts[exchange] += 1

                    if index + 1 < len(symbols):
                        await asyncio.sleep(intervals[exchange])

        except Exception as exc:
            logger.critical(
                "STARTUP LEVERAGE FAILED: %s",
                exc,
            )
            raise

        logger.info(
            "STARTUP LEVERAGE READY | Binance %d | Bitget %d | OKX %d | BTC SKIPPED",
            counts["binance"],
            counts["bitget"],
            counts["okx"],
        )

    async def close(self) -> None:
        await asyncio.gather(
            *(client.close() for client in self.clients.values()),
            return_exceptions=True,
        )

    async def execute(self, opportunity: dict) -> PairExecutionResult:
        execution_started_ns = time.perf_counter_ns()
        execution_started_ms = int(time.time() * 1000)

        buy_exchange = opportunity["buy_exchange"]
        sell_exchange = opportunity["sell_exchange"]

        if buy_exchange == sell_exchange:
            raise ValueError("BUY и SELL должны быть на разных биржах")

        buy_symbol = opportunity["buy_symbol"]
        sell_symbol = opportunity["sell_symbol"]

        buy_quantity = float(opportunity["buy_quantity"])
        sell_quantity = float(opportunity["sell_quantity"])

        buy_client = self.clients[buy_exchange]
        sell_client = self.clients[sell_exchange]

        execution_id = uuid.uuid4().hex[:12]

        detected_at_ms = int(opportunity.get("detected_at", 0) or 0)
        signal_age_ms = (
            execution_started_ms - detected_at_ms
            if detected_at_ms > 0
            else None
        )

        expected_exec_spread = float(
            opportunity.get("execution_spread_percent", 0.0)
        )
        expected_net = float(
            opportunity.get("net_profit_percent", 0.0)
        )
        signal_buy_price = float(opportunity.get("buy_price", 0.0))
        signal_sell_price = float(opportunity.get("sell_price", 0.0))
        signal_buy_execution_price = float(
            opportunity.get("buy_execution_price", 0.0)
        )
        signal_sell_execution_price = float(
            opportunity.get("sell_execution_price", 0.0)
        )

        logger.warning(
            "EXECUTION %s DIAG SIGNAL | age=%sms | "
            "BUY ask=%.12f | SELL bid=%.12f | "
            "BUY OB exec=%.12f | SELL OB exec=%.12f | "
            "expected_exec_spread=%.6f%% | expected_net=%.6f%%",
            execution_id,
            signal_age_ms if signal_age_ms is not None else "n/a",
            signal_buy_price,
            signal_sell_price,
            signal_buy_execution_price,
            signal_sell_execution_price,
            expected_exec_spread,
            expected_net,
        )

        logger.info(
            "[ENTRY] %s | BUY %s %s %.12f | SELL %s %s %.12f",
            execution_id,
            opportunity.get("buy_exchange"),
            opportunity.get("buy_symbol"),
            opportunity.get("buy_quantity", 0.0),
            opportunity.get("sell_exchange"),
            opportunity.get("sell_symbol"),
            opportunity.get("sell_quantity", 0.0),
        )

        logger.warning(
            "EXECUTION %s START | BUY %s %s qty=%s | SELL %s %s qty=%s",
            execution_id,
            buy_exchange,
            buy_symbol,
            buy_quantity,
            sell_exchange,
            sell_symbol,
            sell_quantity,
        )

        # ==========================================================
        # 1. ОБЕ MARKET ЗАЯВКИ — КОНКУРЕНТНО
        # ==========================================================
        # ==========================================================

        buy_client_id = f"arb{execution_id}b"
        sell_client_id = f"arb{execution_id}s"

        buy_side = "BUY" if buy_exchange == "binance" else "buy"
        buy_position_side = "LONG" if buy_exchange == "binance" else None
        buy_pos_side = "long" if buy_exchange == "okx" else None

        sell_side = "SELL" if sell_exchange == "binance" else "sell"
        sell_position_side = "SHORT" if sell_exchange == "binance" else None
        sell_pos_side = "short" if sell_exchange == "okx" else None

        order_started = time.perf_counter_ns()
        logger.info(
            "[ENTRY REQUEST] BUY %s %s side=%s%s | SELL %s %s side=%s%s",
            buy_exchange,
            buy_symbol,
            buy_side,
            f" positionSide={buy_position_side}" if buy_position_side else (
                f" posSide={buy_pos_side}" if buy_pos_side else ""
            ),
            sell_exchange,
            sell_symbol,
            sell_side,
            f" positionSide={sell_position_side}" if sell_position_side else (
                f" posSide={sell_pos_side}" if sell_pos_side else ""
            ),
        )

        buy_task = asyncio.create_task(
            buy_client.place_market_order(
                symbol=buy_symbol,
                side=buy_side,
                quantity=buy_quantity,
                client_order_id=buy_client_id,
                **({"position_side": buy_position_side} if buy_exchange == "binance" else {}),
                **({"pos_side": buy_pos_side} if buy_exchange == "okx" else {}),
            )
        )

        sell_task = asyncio.create_task(
            sell_client.place_market_order(
                symbol=sell_symbol,
                side=sell_side,
                quantity=sell_quantity,
                client_order_id=sell_client_id,
                **({"position_side": sell_position_side} if sell_exchange == "binance" else {}),
                **({"pos_side": sell_pos_side} if sell_exchange == "okx" else {}),
            )
        )

        buy_result, buy_error = await self._result_or_error(buy_task)
        buy_response_ns = time.perf_counter_ns()

        sell_result, sell_error = await self._result_or_error(sell_task)
        sell_response_ns = time.perf_counter_ns()

        order_ms = (
            time.perf_counter_ns() - order_started
        ) / 1_000_000

        logger.warning(
            "EXECUTION %s ORDERS DONE in %.3f ms | buy=%s | sell=%s",
            execution_id,
            order_ms,
            "OK" if buy_result else f"FAIL:{buy_error}",
            "OK" if sell_result else f"FAIL:{sell_error}",
        )

        logger.warning(
            "EXECUTION %s DIAG ORDER TIMING | "
            "buy_response=%.3fms | sell_response=%.3fms | "
            "first_leg_delta=%.3fms | total=%.3fms",
            execution_id,
            (buy_response_ns - order_started) / 1_000_000,
            (sell_response_ns - order_started) / 1_000_000,
            abs(buy_response_ns - sell_response_ns) / 1_000_000,
            (time.perf_counter_ns() - execution_started_ns) / 1_000_000,
        )

        # ==========================================================
        # 3. ПОКА НЕ ДЕЛАЕМ АВТОМАТИЧЕСКИЙ RECOVERY
        # ==========================================================
        #
        # Это принципиально: сначала отладим реальные ответы
        # бирж и фактические fill quantities.
        #
        # Если одна нога прошла, а вторая нет — явно возвращаем
        # success=False и не маскируем ситуацию.
        #

        if buy_result is None or sell_result is None:
            error = (
                f"buy={buy_error!s}; sell={sell_error!s}"
            )

            logger.critical(
                "EXECUTION %s PARTIAL/FAILED: %s",
                execution_id,
                error,
            )

            # If only one entry order was accepted, immediately close the
            # executed leg. Reconcile the accepted order first so that a
            # partial fill is closed only for the actually filled quantity.
            if buy_result is not None:
                await self._emergency_close_entry_leg(
                    execution_id=execution_id,
                    exchange=buy_exchange,
                    symbol=buy_symbol,
                    result=buy_result,
                    position_side=(
                        buy_position_side
                        if buy_exchange == "binance"
                        else buy_pos_side
                    ),
                )

            if sell_result is not None:
                await self._emergency_close_entry_leg(
                    execution_id=execution_id,
                    exchange=sell_exchange,
                    symbol=sell_symbol,
                    result=sell_result,
                    position_side=(
                        sell_position_side
                        if sell_exchange == "binance"
                        else sell_pos_side
                    ),
                )

            return PairExecutionResult(
                buy=buy_result,
                sell=sell_result,
                success=False,
                error=error,
            )

        # ----------------------------------------------------------
        # 3. RECONCILE ACTUAL FILLS
        # ----------------------------------------------------------
        # The two exchanges are independent, so reconciliation is
        # performed concurrently. This changes only the waiting time:
        # both fill queries still complete before the result is used.
        reconcile_started_ns = time.perf_counter_ns()

        buy_reconcile_task = asyncio.create_task(
            buy_client.get_order(
                symbol=buy_symbol,
                order_id=buy_result.order_id,
            )
        )

        sell_reconcile_task = asyncio.create_task(
            sell_client.get_order(
                symbol=sell_symbol,
                order_id=sell_result.order_id,
            )
        )

        buy_order, sell_order = await asyncio.gather(
            buy_reconcile_task,
            sell_reconcile_task,
        )

        reconcile_finished_ns = time.perf_counter_ns()

        buy_filled, buy_avg = self._fill_info(
            buy_exchange,
            buy_order,
        )
        sell_filled, sell_avg = self._fill_info(
            sell_exchange,
            sell_order,
        )

        reconcile_ms = (
            reconcile_finished_ns - reconcile_started_ns
        ) / 1_000_000

        actual_entry_spread = (
            ((sell_avg / buy_avg) - 1) * 100
            if buy_avg > 0 and sell_avg > 0
            else 0.0
        )

        logger.warning(
            "EXECUTION %s DIAG RECONCILE | "
            "BUY and SELL queried concurrently",
            execution_id,
        )

        buy_slippage_percent = (
            ((buy_avg / signal_buy_price) - 1.0) * 100.0
            if signal_buy_price > 0
            else 0.0
        )
        sell_slippage_percent = (
            (1.0 - (sell_avg / signal_sell_price)) * 100.0
            if signal_sell_price > 0
            else 0.0
        )
        buy_ob_slippage_percent = (
            ((buy_avg / signal_buy_execution_price) - 1.0) * 100.0
            if signal_buy_execution_price > 0
            else 0.0
        )
        sell_ob_slippage_percent = (
            (1.0 - (sell_avg / signal_sell_execution_price)) * 100.0
            if signal_sell_execution_price > 0
            else 0.0
        )
        spread_loss_bps = (
            expected_exec_spread - actual_entry_spread
        ) * 100.0

        logger.warning(
            "EXECUTION %s DIAG FILLS | "
            "BUY %.12f @ %.12f | SELL %.12f @ %.12f | "
            "actual_entry_spread=%.6f%% | spread_loss=%.3f bps | "
            "BUY slip=%.3f bps | SELL slip=%.3f bps | "
            "BUY vs OB=%.3f bps | SELL vs OB=%.3f bps | "
            "reconcile=%.3fms",
            execution_id,
            buy_filled,
            buy_avg,
            sell_filled,
            sell_avg,
            actual_entry_spread,
            spread_loss_bps,
            buy_slippage_percent * 100.0,
            sell_slippage_percent * 100.0,
            buy_ob_slippage_percent * 100.0,
            sell_ob_slippage_percent * 100.0,
            reconcile_ms,
        )

        actual_net = (
            actual_entry_spread
            - float(opportunity.get("buy_fee_percent", 0.0)) * 2.0
            - float(opportunity.get("sell_fee_percent", 0.0)) * 2.0
        )
        net_loss_bps = (expected_net - actual_net) * 100.0

        total_elapsed_ms = (
            time.perf_counter_ns() - execution_started_ns
        ) / 1_000_000

        logger.warning(
            "EXECUTION %s DIAG TOTAL | signal_age=%sms | "
            "expected_net=%.6f%% | actual_net=%.6f%% | "
            "actual_entry_spread=%.6f%% | net_loss=%.3f bps | "
            "elapsed=%.3fms",
            execution_id,
            signal_age_ms if signal_age_ms is not None else "n/a",
            expected_net,
            actual_net,
            actual_entry_spread,
            net_loss_bps,
            total_elapsed_ms,
        )

        if buy_filled <= 0 or sell_filled <= 0:
            error = (
                f"fill failed: "
                f"buy_filled={buy_filled}; "
                f"sell_filled={sell_filled}"
            )
            logger.critical(
                "EXECUTION %s FILL FAILED: %s",
                execution_id,
                error,
            )

            if buy_filled > 0:
                await self._emergency_close_entry_leg(
                    execution_id=execution_id,
                    exchange=buy_exchange,
                    symbol=buy_symbol,
                    result=buy_result,
                    position_side=(
                        buy_position_side
                        if buy_exchange == "binance"
                        else buy_pos_side
                    ),
                    filled_quantity=buy_filled,
                )

            if sell_filled > 0:
                await self._emergency_close_entry_leg(
                    execution_id=execution_id,
                    exchange=sell_exchange,
                    symbol=sell_symbol,
                    result=sell_result,
                    position_side=(
                        sell_position_side
                        if sell_exchange == "binance"
                        else sell_pos_side
                    ),
                    filled_quantity=sell_filled,
                )

            return PairExecutionResult(
                buy=buy_result,
                sell=sell_result,
                success=False,
                error=error,
                buy_filled_quantity=buy_filled,
                sell_filled_quantity=sell_filled,
                buy_average_price=buy_avg,
                sell_average_price=sell_avg,
            )

        logger.warning(
            "EXECUTION %s FILLED | "
            "BUY %.12f @ %.12f | SELL %.12f @ %.12f",
            execution_id,
            buy_filled,
            buy_avg,
            sell_filled,
            sell_avg,
        )

        return PairExecutionResult(
            buy=buy_result,
            sell=sell_result,
            success=True,
            buy_filled_quantity=buy_filled,
            sell_filled_quantity=sell_filled,
            buy_average_price=buy_avg,
            sell_average_price=sell_avg,
        )

    async def _emergency_close_entry_leg(
        self,
        execution_id: str,
        exchange: str,
        symbol: str,
        result: OrderResult,
        position_side: str | None = None,
        filled_quantity: float | None = None,
    ) -> bool:
        """Immediately close a leg that was executed without its pair."""
        client = self.clients[exchange]

        try:
            if filled_quantity is None:
                order = await client.get_order(
                    symbol=symbol,
                    order_id=result.order_id,
                )
                filled_quantity, _ = self._fill_info(
                    exchange,
                    order,
                )

            filled_quantity = float(filled_quantity or 0.0)

            if filled_quantity <= 0:
                logger.critical(
                    "EXECUTION %s EMERGENCY CLOSE | %s %s | no filled quantity",
                    execution_id,
                    exchange,
                    symbol,
                )
                return False

            close_side = (
                "SELL" if exchange == "binance" else "sell"
            ) if result.side.upper() == "BUY" else (
                "BUY" if exchange == "binance" else "buy"
            )

            close_position_side = position_side

            close_client_id = f"arb{execution_id}x"

            logger.critical(
                "EXECUTION %s EMERGENCY CLOSE START | %s %s side=%s qty=%.12f",
                execution_id,
                exchange,
                symbol,
                close_side,
                filled_quantity,
            )

            kwargs = {
                "symbol": symbol,
                "side": close_side,
                "quantity": filled_quantity,
                "client_order_id": close_client_id,
            }

            if exchange == "binance":
                kwargs["position_side"] = close_position_side
            elif exchange == "okx":
                kwargs["pos_side"] = close_position_side
            elif exchange == "bitget":
                kwargs["trade_side"] = "close"

            close_result = await client.place_market_order(**kwargs)

            close_order = await client.get_order(
                symbol=symbol,
                order_id=close_result.order_id,
            )
            close_filled, _ = self._fill_info(
                exchange,
                close_order,
            )

            if close_filled <= 0:
                raise RuntimeError(
                    f"emergency close returned zero fill: {exchange} {symbol}"
                )

            logger.critical(
                "EXECUTION %s EMERGENCY CLOSE DONE | %s %s qty=%.12f",
                execution_id,
                exchange,
                symbol,
                close_filled,
            )
            return True

        except Exception as exc:
            logger.critical(
                "EXECUTION %s EMERGENCY CLOSE FAILED | %s %s | %s",
                execution_id,
                exchange,
                symbol,
                exc,
                exc_info=True,
            )
            return False

    async def positions_are_flat(self, opportunity: dict) -> bool:
        """Return True only when both legs have no residual position."""
        buy_client = self.clients[opportunity["buy_exchange"]]
        sell_client = self.clients[opportunity["sell_exchange"]]

        buy_position, sell_position = await asyncio.gather(
            buy_client.get_position(opportunity["buy_symbol"]),
            sell_client.get_position(opportunity["sell_symbol"]),
        )

        return (
            abs(buy_position.quantity) <= 1e-12
            and abs(sell_position.quantity) <= 1e-12
        )

    async def close_position(self, position) -> PairExecutionResult:
        """Закрывает обе ноги уже открытой арбитражной позиции MARKET-ордерами."""

        buy_exchange = position.buy_exchange
        sell_exchange = position.sell_exchange
        buy_client = self.clients[buy_exchange]
        sell_client = self.clients[sell_exchange]

        execution_id = uuid.uuid4().hex[:12]

        logger.info(
            "[EXIT] START | %s | BUY-leg %s %s qty=%.12f | "
            "SELL-leg %s %s qty=%.12f",
            position.asset,
            position.buy_exchange,
            position.buy_symbol,
            position.buy_quantity,
            position.sell_exchange,
            position.sell_symbol,
            position.sell_quantity,
        )

        # Closing long -> SELL; closing short -> BUY.
        buy_side = "SELL" if buy_exchange == "binance" else "sell"
        buy_position_side = "LONG" if buy_exchange == "binance" else None
        buy_pos_side = "long" if buy_exchange == "okx" else None

        sell_side = "BUY" if sell_exchange == "binance" else "buy"
        sell_position_side = "SHORT" if sell_exchange == "binance" else None
        sell_pos_side = "short" if sell_exchange == "okx" else None

        logger.info(
            "[EXIT REQUEST] %s %s side=%s%s | %s %s side=%s%s",
            buy_exchange,
            position.buy_symbol,
            buy_side,
            f" positionSide={buy_position_side}" if buy_position_side else (
                f" posSide={buy_pos_side}" if buy_pos_side else (
                    " reduceOnly=YES" if buy_exchange == "bitget" else ""
                )
            ),
            sell_exchange,
            position.sell_symbol,
            sell_side,
            f" positionSide={sell_position_side}" if sell_position_side else (
                f" posSide={sell_pos_side}" if sell_pos_side else (
                    " reduceOnly=YES" if sell_exchange == "bitget" else ""
                )
            ),
        )

        # Both MARKET close requests are sent concurrently.
        buy_task = asyncio.create_task(
            buy_client.place_market_order(
                symbol=position.buy_symbol,
                side=buy_side,
                quantity=position.buy_quantity,
                client_order_id=f"arb{execution_id}cb",
                **(
                    {"position_side": buy_position_side}
                    if buy_exchange == "binance"
                    else {}
                ),
                **(
                    {"pos_side": buy_pos_side}
                    if buy_exchange == "okx"
                    else {}
                ),
                **(
                    {"trade_side": "close"}
                    if buy_exchange == "bitget"
                    else {}
                ),
            )
        )

        sell_task = asyncio.create_task(
            sell_client.place_market_order(
                symbol=position.sell_symbol,
                side=sell_side,
                quantity=position.sell_quantity,
                client_order_id=f"arb{execution_id}cs",
                **(
                    {"position_side": sell_position_side}
                    if sell_exchange == "binance"
                    else {}
                ),
                **(
                    {"pos_side": sell_pos_side}
                    if sell_exchange == "okx"
                    else {}
                ),
                **(
                    {"trade_side": "close"}
                    if sell_exchange == "bitget"
                    else {}
                ),
            )
        )

        buy_result, buy_error = await self._result_or_error(buy_task)
        sell_result, sell_error = await self._result_or_error(sell_task)

        # Reconcile accepted close orders concurrently.
        buy_order = None
        sell_order = None

        reconcile_tasks = []
        if buy_result is not None:
            reconcile_tasks.append(
                asyncio.create_task(
                    buy_client.get_order(
                        symbol=position.buy_symbol,
                        order_id=buy_result.order_id,
                    )
                )
            )
        else:
            reconcile_tasks.append(None)

        if sell_result is not None:
            reconcile_tasks.append(
                asyncio.create_task(
                    sell_client.get_order(
                        symbol=position.sell_symbol,
                        order_id=sell_result.order_id,
                    )
                )
            )
        else:
            reconcile_tasks.append(None)

        active_tasks = [task for task in reconcile_tasks if task is not None]
        if active_tasks:
            results = await asyncio.gather(*active_tasks, return_exceptions=True)

            result_index = 0
            if reconcile_tasks[0] is not None:
                result = results[result_index]
                result_index += 1
                if isinstance(result, Exception):
                    buy_error = buy_error or result
                else:
                    buy_order = result

            if reconcile_tasks[1] is not None:
                result = results[result_index]
                if isinstance(result, Exception):
                    sell_error = sell_error or result
                else:
                    sell_order = result

        buy_filled = (
            self._fill_info(buy_exchange, buy_order)[0]
            if buy_order is not None
            else 0.0
        )
        sell_filled = (
            self._fill_info(sell_exchange, sell_order)[0]
            if sell_order is not None
            else 0.0
        )

        buy_remaining = max(0.0, position.buy_quantity - buy_filled)
        sell_remaining = max(0.0, position.sell_quantity - sell_filled)

        # If a close request failed or was only partially filled,
        # immediately close the actual remaining position.
        recovery_tasks = []

        if buy_remaining > 1e-12:
            recovery_tasks.append(
                asyncio.create_task(
                    self._market_close_remaining(
                        execution_id=execution_id,
                        exchange=buy_exchange,
                        symbol=position.buy_symbol,
                        side=buy_side,
                        quantity=buy_remaining,
                        position_side=buy_position_side,
                        pos_side=buy_pos_side,
                    )
                )
            )

        if sell_remaining > 1e-12:
            recovery_tasks.append(
                asyncio.create_task(
                    self._market_close_remaining(
                        execution_id=execution_id,
                        exchange=sell_exchange,
                        symbol=position.sell_symbol,
                        side=sell_side,
                        quantity=sell_remaining,
                        position_side=sell_position_side,
                        pos_side=sell_pos_side,
                    )
                )
            )

        recovery_results = []
        if recovery_tasks:
            recovery_results = await asyncio.gather(
                *recovery_tasks,
                return_exceptions=True,
            )

        # Final authoritative position check.
        buy_position, sell_position = await asyncio.gather(
            buy_client.get_position(position.buy_symbol),
            sell_client.get_position(position.sell_symbol),
        )

        flat = (
            abs(buy_position.quantity) <= 1e-12
            and abs(sell_position.quantity) <= 1e-12
        )

        if not flat:
            return PairExecutionResult(
                buy=buy_result,
                sell=sell_result,
                success=False,
                error=(
                    f"close verification failed: "
                    f"buy_position={buy_position.quantity}; "
                    f"sell_position={sell_position.quantity}; "
                    f"buy_error={buy_error!s}; "
                    f"sell_error={sell_error!s}; "
                    f"recovery={recovery_results}"
                ),
                buy_filled_quantity=buy_filled,
                sell_filled_quantity=sell_filled,
            )

        return PairExecutionResult(
            buy=buy_result,
            sell=sell_result,
            success=True,
            buy_filled_quantity=buy_filled,
            sell_filled_quantity=sell_filled,
        )

    @staticmethod
    def _fill_info(
        exchange: str,
        order: dict,
    ) -> tuple[float, float]:
        if exchange == "binance":
            return (
                float(order.get("executedQty", 0) or 0),
                float(order.get("avgPrice", 0) or 0),
            )

        if exchange == "okx":
            return (
                float(order.get("accFillSz", 0) or 0),
                float(order.get("avgPx", 0) or 0),
            )

        if exchange == "bitget":
            return (
                float(
                    order.get("baseVolume", 0)
                    or order.get("filledQty", 0)
                    or order.get("fillSz", 0)
                    or 0
                ),
                float(
                    order.get("priceAvg", 0)
                    or order.get("avgPx", 0)
                    or 0
                ),
            )

        raise ValueError(f"Неизвестная биржа: {exchange}")

    @staticmethod
    async def _result_or_error(task: asyncio.Task):
        try:
            return await task, None
        except Exception as exc:
            return None, exc
