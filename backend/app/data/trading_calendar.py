"""A-share trading-day calendar helper.

This is the *real* completeness basis for :class:`MarketDataService.query_daily` —
a ``(start, end) -> expected trading-day count`` callable derived from the actual
A-share trade-date calendar (via AKShare), so the cache-completeness judgment is
not a fixed test value.

Coverage safety: an empty/expired/partial calendar must NOT be treated as a
trustworthy count of 0. ``count_between`` returns ``None`` whenever the calendar
cannot *prove* it covers the full window (no data, or the earliest/latest known
trade date does not bracket ``[start, end]``). Callers treat ``None`` as
"coverage unknown" and must conservatively refetch rather than serving a cache.

The calendar list is cached in-process and can be reloaded with :meth:`refresh`.
For offline tests, a deterministic ``trade_dates`` list (or a ``fetch`` callable)
can be injected instead of hitting AKShare.
"""

from __future__ import annotations

from datetime import date
from typing import Callable, List, Optional

import pandas as pd


class TradingCalendarProvider:
    """Provide the A-share trading-day list and count days in a window."""

    def __init__(
        self,
        trade_dates: Optional[List[date]] = None,
        fetch: Optional[Callable[[], List[date]]] = None,
    ) -> None:
        self._trade_dates = trade_dates
        self._fetch = fetch

    def get_trade_dates(self, refresh: bool = False) -> List[date]:
        if refresh or self._trade_dates is None:
            self._trade_dates = (
                self._fetch() if self._fetch is not None else self._load_from_akshare()
            )
        return self._trade_dates

    def refresh(self) -> List[date]:
        """Drop the cached calendar and reload it from the source."""
        return self.get_trade_dates(refresh=True)

    def count_between(self, start: date, end: date) -> Optional[int]:
        """Number of trading days in ``[start, end]``, or ``None`` when the
        calendar cannot prove it covers the whole window (empty/partial/expired).
        """
        dates = self.get_trade_dates()
        if not dates:
            return None  # empty calendar -> coverage unknown
        if dates[0] > start or dates[-1] < end:
            return None  # calendar does not bracket the window -> coverage unknown
        return sum(1 for day in dates if start <= day <= end)

    def as_callable(self) -> Callable[[date, date], Optional[int]]:
        """Return ``(start, end) -> Optional[int]`` for injection as ``trading_days``."""
        return self.count_between

    @staticmethod
    def _load_from_akshare() -> List[date]:
        import akshare as ak

        raw = ak.tool_trade_date_hist_sina()
        column = "trade_date" if "trade_date" in raw.columns else raw.columns[0]
        return sorted(pd.to_datetime(raw[column]).dt.date.tolist())
