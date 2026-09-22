"""Regression: the warm-up CLI must obey the same completed-day boundary as the request path.

``scripts/warm_market_data.py`` builds its own ``MarketDataService`` instead of going through
``api.v1.dependencies.get_market_data_source``.  Before the fix it passed only
``stock_service`` / ``repository`` / ``trading_days``, so the service had no
``completed_through`` callable and could fetch and persist an unfinished intraday bar
(observed on 2026-09-22: a 09-22 bar was written while the completed day was 09-21).

These tests assert the *wiring*: the warm entry injects the boundary exactly like the request
path does, and keeps its previous behaviour on a tree where the service has no such notion.
They deliberately do not re-test the service's own boundary logic (that lives in
``tests/test_market_data_repository.py``) and touch no database, provider or network.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_warm_module():
    path = PROJECT_ROOT / "scripts" / "warm_market_data.py"
    spec = importlib.util.spec_from_file_location("_warm_market_data_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Row:
    def __init__(self, trade_date: dt.date) -> None:
        self.trade_date = trade_date


class _FakeCalendar:
    """Stand-in for ``TradingCalendarProvider`` with a known completed day."""

    completed: dt.date | None = dt.date(2026, 9, 21)
    boundary_reads = 0

    def __init__(self, *args, **kwargs) -> None:
        pass

    def last_completed_trade_date(self, as_of: dt.datetime | None = None) -> dt.date | None:
        type(self).boundary_reads += 1
        return type(self).completed

    def count_between(self, start: dt.date, end: dt.date) -> int | None:
        return 3


class _FakeRepository:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def get_daily_sync(self, stock_code: str):
        return None


class _FakeSession:
    def close(self) -> None:
        pass


def _install_fakes(monkeypatch, module, service_cls, calendar_cls=None):
    """Replace everything ``main()`` touches except argument parsing and the wiring itself."""
    _FakeCalendar.boundary_reads = 0  # class-level counter: never leak state between tests
    monkeypatch.setattr(module, "apply_migrations", lambda engine: None)
    monkeypatch.setattr(module, "SessionLocal", _FakeSession)
    monkeypatch.setattr(module, "MarketDataRepository", _FakeRepository)
    monkeypatch.setattr(module, "StockService", lambda *a, **k: object())
    monkeypatch.setattr(
        module, "TradingCalendarProvider", calendar_cls or _FakeCalendar
    )
    monkeypatch.setattr(module, "MarketDataService", service_cls)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(sys, "argv", ["warm_market_data.py", "--stock-code", "600519", "--rounds", "1"])


#: Default for the recording service below: distinguishes "keyword not passed" from
#: "keyword passed as None", which are different statements about the boundary.
_NOT_PASSED = object()


def _make_service_cls(record: dict, *, with_boundary: bool):
    if with_boundary:

        class _Service:
            def __init__(
                self,
                *,
                stock_service=None,
                repository=None,
                trading_days=None,
                completed_through=_NOT_PASSED,
            ) -> None:
                record["boundary_passed"] = completed_through is not _NOT_PASSED
                record["completed_through"] = (
                    None if completed_through is _NOT_PASSED else completed_through
                )
                record["trading_days"] = trading_days

            def query_daily(self, stock_code, start_date, end_date, min_rows=None):
                return [_Row(dt.date(2026, 9, 18)), _Row(dt.date(2026, 9, 19))]

    else:

        class _Service:  # a tree whose MarketDataService has no boundary notion yet
            def __init__(self, *, stock_service=None, repository=None, trading_days=None) -> None:
                record["kwargs"] = {
                    "stock_service": stock_service,
                    "repository": repository,
                    "trading_days": trading_days,
                }

            def query_daily(self, stock_code, start_date, end_date, min_rows=None):
                return [_Row(dt.date(2026, 9, 18)), _Row(dt.date(2026, 9, 19))]

    return _Service


def test_warm_entry_injects_completed_day_boundary(monkeypatch):
    """The warm entry must hand the service the same boundary callable the request path uses."""
    module = _load_warm_module()
    record: dict = {}
    _FakeCalendar.boundary_reads = 0
    _install_fakes(monkeypatch, module, _make_service_cls(record, with_boundary=True))

    assert module.main() == 0

    assert record["boundary_passed"] is True, (
        "warm entry did not inject the completed-day boundary"
    )
    boundary = record["completed_through"]
    assert callable(boundary), "boundary must be the calendar callable, not a frozen date"
    assert boundary() == dt.date(2026, 9, 21)
    assert record["trading_days"] is not None


class _CalendarWithoutBoundary:
    """A calendar that cannot answer "which day is fully completed?"."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def count_between(self, start, end):
        return 3


def test_warm_entry_omits_boundary_when_the_calendar_cannot_provide_one(monkeypatch):
    """Behavioural counterpart of the removed source-text assertion.

    C (V2 review) noted that matching the script's *source text* breaks on any refactor
    while proving little. The property that must actually hold: when the calendar has no
    ``last_completed_trade_date``, the script must not pass the keyword **at all** - an
    explicit ``completed_through=None`` is a different statement from omitting it, and a
    script that cannot prove a boundary must not invent one.
    """
    module = _load_warm_module()
    record: dict = {}
    _install_fakes(
        monkeypatch,
        module,
        _make_service_cls(record, with_boundary=True),
        calendar_cls=_CalendarWithoutBoundary,
    )

    assert module.main() == 0

    assert record["completed_through"] is None
    assert record["boundary_passed"] is False


def test_warm_entry_keeps_old_behaviour_without_boundary_support(monkeypatch):
    """On a tree whose service has no ``completed_through``, the script must not guess."""
    module = _load_warm_module()
    record: dict = {}
    _install_fakes(monkeypatch, module, _make_service_cls(record, with_boundary=False))

    assert module.main() == 0

    assert "completed_through" not in record.get("kwargs", {}), (
        "boundary must not be passed to a service that does not accept it"
    )
    assert set(record["kwargs"]) == {"stock_service", "repository", "trading_days"}
    assert _FakeCalendar.boundary_reads == 0
