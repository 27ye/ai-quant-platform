# -*- coding: utf-8 -*-
"""Unit tests for the refactored ``scripts/export_c_delivery.py`` (C's §2 spec).

C approved the direction - one successful fetch, freeze the batch, render both
deliverables from it, then write, commit and read back independently - and asked
for offline coverage (pure functions, fixed fixtures, a temporary database) of a
specific list. Every item has a test below.

The live provider and the real MySQL are never touched: a counting fake provider
and a temporary SQLite database stand in for them.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.db.migrations import apply_migrations
from backend.app.schemas.stock import DailyKlineSchema

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_c_delivery.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("export_c_delivery", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # ``@dataclass`` resolves annotations through ``sys.modules[cls.__module__]``,
    # so the module must be registered before it is executed.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()

STOCK = "600519"
WINDOW_TOKEN = "20241201_20260915"
FETCHED_AT = "2026-09-16T00:05:41+00:00"


def _row(day: str, **overrides):
    row = {
        "stock_code": STOCK,
        "trade_date": day,
        "open": 10.123456,
        "high": 11.5,
        "low": 9.5,
        "close": 10.5,
        "volume": 1000,
        "amount": 12345.6789,
        "turnover_rate": 0.0123456789,
        "change_pct": -0.0040999999999999995,
    }
    row.update(overrides)
    return row


class _CountingProvider:
    """Counts calls; ``fail_from=N`` makes the Nth call raise."""

    def __init__(self, rows, *, fail_from=None) -> None:
        self._rows = rows
        self.fail_from = fail_from
        self.calls = 0

    def get_daily_kline(self, stock_code, start_date, end_date):
        self.calls += 1
        if self.fail_from is not None and self.calls >= self.fail_from:
            raise RuntimeError(f"provider called {self.calls} times")
        return [DailyKlineSchema(**row) for row in self._rows]


def _fetch(provider):
    """The only entry point that consumes a provider response."""
    return mod.fetch_stock_batch(
        provider,
        stock_code=STOCK,
        start_date=date(2024, 12, 1),
        end_date=date(2026, 9, 15),
        now=lambda: datetime(2026, 9, 16, 0, 5, 41, tzinfo=timezone.utc),
    )


def _batch(rows, window=("2024-12-01", "2026-09-15")):
    return mod.build_stock_batch(
        stock_code=STOCK,
        requested_window=window,
        rows=rows,
        fetched_at_utc=FETCHED_AT,
    )


def _session_factory():
    """A fresh SQLite database plus a factory that opens new sessions on it."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    apply_migrations(engine)
    return lambda: Session(bind=engine)


# -- C1: one response feeds both outputs -------------------------------------


def test_one_provider_response_feeds_both_outputs():
    provider = _CountingProvider([_row("2026-09-14"), _row("2026-09-15")])

    batch = _fetch(provider)

    assert provider.calls == 1
    assert len(batch.raw_rows) == 2
    assert len(batch.normalized_rows) == 2
    # `raw` keeps provider precision, `normalized` is the canonical rendering of
    # the very same row.
    assert batch.raw_rows[0]["open"] == 10.123456
    assert batch.normalized_rows[0]["open"] == 10.1235
    assert batch.rounding_problems == ()
    assert batch.ok is True
    assert batch.window == ("2026-09-14", "2026-09-15")


# -- C3: a second provider call would fail, so it must never happen ----------


def test_a_second_provider_call_would_fail_the_export():
    provider = _CountingProvider([_row("2026-09-14")], fail_from=2)

    batch = _fetch(provider)

    assert provider.calls == 1
    assert batch.ok is True


# -- C4: canonical rounding and optional nulls -------------------------------


def test_canonical_rounding_and_optional_nulls():
    normalized = _batch([_row("2026-09-14")]).normalized_rows[0]

    assert normalized["open"] == 10.1235            # OHLC -> 4 decimals
    assert normalized["amount"] == 12345.68         # amount -> 2
    assert normalized["turnover_rate"] == 0.012346  # percent -> 6
    assert normalized["change_pct"] == -0.0041      # float noise removed
    assert normalized["volume"] == 1000
    assert isinstance(normalized["volume"], int)

    nulls = _batch(
        [_row("2026-09-14", amount=None, turnover_rate=None, change_pct=None)]
    ).normalized_rows[0]

    assert nulls["amount"] is None
    assert nulls["turnover_rate"] is None
    assert nulls["change_pct"] is None


def test_verify_pair_flags_a_genuine_second_snapshot():
    raw = [_row("2026-09-15", close=1272.75)]
    normalized = [dict(mod.canonical_row(raw[0]), close=1278.66)]

    problems = mod.verify_pair(raw, normalized)

    assert problems
    assert "close" in problems[0]


# -- C6: a failed round never promotes an older file -------------------------


def test_empty_batch_never_promotes_an_older_file(tmp_path):
    stale = tmp_path / f"{STOCK}_qfq_raw_{WINDOW_TOKEN}.json"
    stale.write_text(json.dumps([_row("2026-09-14")]), encoding="utf-8")

    files = mod.write_stock_batch(_batch([]), tmp_path, WINDOW_TOKEN)

    assert files == {"raw": None, "normalized": None}
    # The old file survives untouched, but is not claimed as this batch's output.
    assert json.loads(stale.read_text(encoding="utf-8"))
    assert len(json.loads(stale.read_text(encoding="utf-8"))) == 1


# -- C7: saved bytes match the manifest --------------------------------------


def test_written_bytes_match_the_recorded_sha256(tmp_path):
    files = mod.write_stock_batch(
        _batch([_row("2026-09-14"), _row("2026-09-15")]), tmp_path, WINDOW_TOKEN
    )

    for key in ("raw", "normalized"):
        path = Path(files[key]["path"])
        assert path.exists()
        assert files[key]["sha256"] == mod.sha256_file(path)
        assert files[key]["rows"] == 2
        assert files[key]["actual_window"] == ["2026-09-14", "2026-09-15"]

    # The two renderings must not be byte-identical: raw keeps provider precision.
    assert files["raw"]["sha256"] != files["normalized"]["sha256"]


# -- write -> commit -> independent read-back --------------------------------


def test_readback_uses_a_new_session_and_matches_the_file():
    sessions = _session_factory()
    batch = _fetch(_CountingProvider([_row("2026-09-14"), _row("2026-09-15")]))

    with sessions() as session:
        assert mod.persist_normalized(session, batch) == 2

    readback = mod.readback_and_verify(batch, session_factory=sessions)

    assert readback["ok"] is True
    assert readback["rows"] == 2
    assert readback["window"] == ["2026-09-14", "2026-09-15"]
    assert readback["problems"] == []


# -- C2: a pre-seeded cache never leaks into the batch -----------------------


def test_pre_seeded_cache_does_not_leak_into_the_batch():
    sessions = _session_factory()
    with sessions() as session:
        # An older, different snapshot already sits in the repository.
        mod.MarketDataRepository(session).upsert_daily(
            [DailyKlineSchema(**_row("2026-09-14", close=777.0))]
        )
        session.commit()

    batch = _fetch(_CountingProvider([_row("2026-09-14")]))

    # The batch carries the freshly fetched values, never the cached ones.
    assert batch.normalized_rows[0]["close"] == 10.5

    with sessions() as session:
        assert mod.persist_normalized(session, batch) == 1

    readback = mod.readback_and_verify(batch, session_factory=sessions)
    assert readback["ok"] is True
    assert readback["rows"] == 1


# -- C5: a failed write/read-back is never reported as success ---------------


def test_readback_mismatch_is_not_reported_as_success():
    sessions = _session_factory()
    with sessions() as session:
        # A stale row, and this time the batch's own write never lands.
        mod.MarketDataRepository(session).upsert_daily(
            [DailyKlineSchema(**_row("2026-09-14", close=777.0))]
        )
        session.commit()

    batch = _batch([_row("2026-09-14")], window=("2026-09-14", "2026-09-14"))

    readback = mod.readback_and_verify(batch, session_factory=sessions)

    assert readback["ok"] is False
    assert any("close" in problem for problem in readback["problems"])


def test_readback_exception_is_not_reported_as_success():
    batch = _batch([_row("2026-09-14")], window=("2026-09-14", "2026-09-14"))

    def broken_factory():
        raise RuntimeError("mysql is down")

    readback = mod.readback_and_verify(batch, session_factory=broken_factory)

    assert readback["ok"] is False
    assert "read-back failed" in readback["problems"][0]


def test_empty_batch_reports_a_failed_readback():
    readback = mod.readback_and_verify(_batch([]), session_factory=_session_factory())

    assert readback["ok"] is False
    assert readback["rows"] == 0


# -- delivery gates: an existing directory is never overwritten ---------------


def test_existing_batch_directory_is_refused(tmp_path):
    target = tmp_path / "c-delivery-20260916"

    mod.ensure_publishable_dir(target)  # missing is fine
    target.mkdir()
    mod.ensure_publishable_dir(target)  # empty is fine

    (target / "MANIFEST.json").write_text("{}", encoding="utf-8")
    with pytest.raises(mod.BatchError) as excinfo:
        mod.ensure_publishable_dir(target)

    assert "already exists" in str(excinfo.value)


# -- delivery gate: nothing past the last complete trading day ---------------


def _export(rows, settled_day, tmp_path, sessions):
    session = sessions()
    try:
        return mod.export_stock(
            code=STOCK,
            provider=_CountingProvider(rows),
            session=session,
            session_factory=sessions,
            out_dir=tmp_path,
            window_token=WINDOW_TOKEN,
            start_date=date(2024, 12, 1),
            end_date=date(2026, 9, 15),
            now=lambda: datetime(2026, 9, 16, 0, 5, 41, tzinfo=timezone.utc),
            database="probe",
            settled_day=settled_day,
        )
    finally:
        session.close()


def test_rows_after_the_settled_day_are_refused_before_any_side_effect(tmp_path):
    sessions = _session_factory()

    entry = _export([_row("2026-09-15"), _row("2026-09-16")], "2026-09-15", tmp_path, sessions)

    assert entry["status"] == "beyond_settled_day"
    assert entry["rows_beyond_settled_day"] == ["2026-09-16"]
    assert entry["raw"] is None and entry["normalized"] is None
    assert list(tmp_path.iterdir()) == []  # no file written
    with sessions() as session:
        stored = mod.MarketDataRepository(session).list_daily(
            STOCK, date(2024, 12, 1), date(2026, 12, 31)
        )
        assert stored == []  # and nothing written to the database


def test_rows_up_to_the_settled_day_are_accepted(tmp_path):
    sessions = _session_factory()

    entry = _export([_row("2026-09-14"), _row("2026-09-15")], "2026-09-15", tmp_path, sessions)

    assert entry["status"] == "ok"
    assert entry["rows_beyond_settled_day"] == []
    assert (tmp_path / f"{STOCK}_qfq_raw_{WINDOW_TOKEN}.json").exists()
    assert (tmp_path / f"{STOCK}_qfq_normalized_{WINDOW_TOKEN}.json").exists()


def test_absent_settled_day_is_refused_before_any_side_effect(tmp_path):
    """C: the last complete trading day is mandatory, not just recorded."""
    sessions = _session_factory()

    entry = _export([_row("2026-09-15")], None, tmp_path, sessions)

    assert entry["status"] == "missing_settled_day"
    assert entry["status"] != "ok"
    assert list(tmp_path.iterdir()) == []
    with sessions() as session:
        assert mod.MarketDataRepository(session).list_daily(
            STOCK, date(2024, 12, 1), date(2026, 12, 31)
        ) == []


def test_require_settled_day_rejects_a_missing_value():
    with pytest.raises(mod.BatchError) as excinfo:
        mod.require_settled_day(None)

    assert "required" in str(excinfo.value)
    assert mod.require_settled_day("2026-09-15") == "2026-09-15"


def test_cli_refuses_when_the_settled_day_is_omitted(tmp_path, monkeypatch, capsys):
    """The gate must fire before any provider call, write or database access."""
    batch_dir = tmp_path / "c-delivery-20260916"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "export_c_delivery.py",
            "--batch",
            "20260916",
            "--output-dir",
            str(batch_dir),
        ],
    )

    exit_code = mod.main()

    assert exit_code == 2
    assert not batch_dir.exists()
    assert "required" in capsys.readouterr().err


def test_export_failure_is_recorded_as_a_failure_not_a_success(tmp_path, monkeypatch):
    sessions = _session_factory()

    def _boom(*args, **kwargs):
        raise RuntimeError("read-back exploded")

    monkeypatch.setattr(mod, "readback_and_verify", _boom)

    entry = _export([_row("2026-09-15")], "2026-09-15", tmp_path, sessions)

    assert entry["status"] == "export_failed"
    assert entry["status"] != "ok"
    assert "read-back exploded" in entry["error"]


def test_persist_failure_is_recorded_as_a_failure_not_a_success(tmp_path, monkeypatch):
    sessions = _session_factory()

    def _boom(*args, **kwargs):
        raise RuntimeError("mysql is down")

    monkeypatch.setattr(mod, "persist_normalized", _boom)

    entry = _export([_row("2026-09-15")], "2026-09-15", tmp_path, sessions)

    assert entry["status"] == "export_failed"
    assert "mysql is down" in entry["error"]
    assert (entry["readback"] or {}).get("ok") is False

