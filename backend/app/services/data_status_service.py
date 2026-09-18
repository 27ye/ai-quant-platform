"""Assemble ``GET /stocks/{stock_code}/data-status`` (V2 B2).

The endpoint answers "where did this stock's data come from and how old is it?"
without guessing:

* catalog state comes from the B1 sync bookkeeping;
* bar aggregates come from ``stock_daily`` itself;
* provenance (mode / source / last successful refresh) comes from
  ``stock_daily_sync`` - when that row is missing the mode is reported as
  ``unknown`` rather than invented;
* completeness is only claimed when the **trading calendar** can prove the
  expected bar count. A natural-day count is never substituted for it.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Callable, Optional

from backend.app.core.errors import DataProviderError
from backend.app.data.providers.base import InvalidStockCodeError
from backend.app.schemas.stock import (
    CatalogStatusSchema,
    KlineFreshnessSchema,
    KlineStatusSchema,
    StockDataStatusSchema,
)
from backend.app.services.market_data_service import (
    DEFAULT_MAX_STALE_DAYS,
    DailySyncState,
    DailyWindow,
    MarketDataRepository,
)
from backend.app.services.stock_catalog_service import StockCatalogRepository

STATUS_FRESH = "fresh"
STATUS_STALE = "stale"
STATUS_UNKNOWN = "unknown"
MODE_UNKNOWN = "unknown"


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Timestamps are stored as naive UTC; the API always states the zone."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class DataStatusService:
    def __init__(
        self,
        *,
        market_repository: MarketDataRepository,
        catalog_repository: StockCatalogRepository,
        trading_days: Optional[Callable[[date, date], Optional[int]]] = None,
        max_stale_days: int = DEFAULT_MAX_STALE_DAYS,
        today: Optional[Callable[[], date]] = None,
        now: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self._market = market_repository
        self._catalog = catalog_repository
        self._trading_days = trading_days
        self._max_stale_days = max_stale_days
        self._today = today or date.today
        self._now = now or (lambda: datetime.now(timezone.utc))

    def get_status(self, stock_code: str) -> StockDataStatusSchema:
        code = (stock_code or "").strip()
        if len(code) != 6 or not code.isdigit():
            raise InvalidStockCodeError(
                f"stock_code must be a 6-digit string, got {stock_code!r}"
            )
        window = self._market.daily_window(code)
        sync = self._market.get_daily_sync(code)
        return StockDataStatusSchema(
            stock_code=code,
            catalog=self._catalog_status(),
            kline=self._kline_status(window, sync),
            as_of=self._now(),
        )

    def _catalog_status(self) -> CatalogStatusSchema:
        state = self._catalog.get_state()
        if state is None:
            return CatalogStatusSchema(synced=False)
        return CatalogStatusSchema(
            synced=state.is_complete,
            row_count=state.row_count,
            last_success_at=_as_utc(state.last_success_at),
            last_attempt_at=_as_utc(state.last_attempt_at),
            source=state.source,
            last_error=state.last_error,
        )

    def _kline_status(
        self, window: DailyWindow, sync: Optional[DailySyncState]
    ) -> KlineStatusSchema:
        expected: Optional[int] = None
        coverage = STATUS_UNKNOWN
        if (
            window.first_trade_date is not None
            and window.last_trade_date is not None
            and self._trading_days is not None
        ):
            try:
                expected = self._trading_days(
                    window.first_trade_date, window.last_trade_date
                )
            except Exception as exc:  # noqa: BLE001 - provider errors stay 50001
                raise DataProviderError("trading calendar error") from exc
            coverage = "known" if expected is not None else STATUS_UNKNOWN

        return KlineStatusSchema(
            mode=sync.mode if sync is not None else MODE_UNKNOWN,
            source=sync.source if sync is not None else None,
            rows=window.row_count,
            first_trade_date=window.first_trade_date,
            last_trade_date=window.last_trade_date,
            last_refreshed_at=_as_utc(
                sync.last_success_at if sync is not None else window.last_updated_at
            ),
            coverage=coverage,
            expected_trading_days=expected,
            last_attempt_at=_as_utc(sync.last_attempt_at if sync is not None else None),
            last_error=sync.last_error if sync is not None else None,
            freshness=self._freshness(window),
        )

    def _freshness(self, window: DailyWindow) -> KlineFreshnessSchema:
        if window.row_count == 0 or window.last_trade_date is None:
            return KlineFreshnessSchema(
                status=STATUS_UNKNOWN, max_stale_days=self._max_stale_days
            )
        stale_days = (self._today() - window.last_trade_date).days
        status = STATUS_FRESH if stale_days <= self._max_stale_days else STATUS_STALE
        return KlineFreshnessSchema(
            status=status,
            stale_days=stale_days,
            max_stale_days=self._max_stale_days,
        )
