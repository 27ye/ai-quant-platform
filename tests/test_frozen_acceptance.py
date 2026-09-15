import hashlib
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from backend.app.quant.config import QuantConfig
from scripts import frozen_acceptance as frozen


STOCK_CODE = "600519"


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _records(rows=403):
    start = date(2024, 1, 2)
    records = []
    calendar = []
    for index in range(rows):
        day = start + timedelta(days=index)
        close = 100.0 + index * 0.1
        calendar.append(day.isoformat())
        records.append(
            {
                "stock_code": STOCK_CODE,
                "trade_date": day.isoformat(),
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1000 + index,
                "amount": close * 1000,
                "turnover_rate": 0.01,
                "change_pct": 0.001,
            }
        )
    return records, calendar


def _write_package(tmp_path, mutate_meta=None, bad_hash=False):
    from backend.app.schemas.stock import DailyKlineSchema
    from backend.app.services.market_data_service import _round_daily

    records, calendar = _records()
    readback = [
        _round_daily(DailyKlineSchema(**record)).model_dump(mode="json")
        for record in records
    ]
    stock = {
        "stock_code": STOCK_CODE,
        "stock_name": "Frozen Stock",
        "industry": "Test Industry",
        "total_market_cap": 1.0,
        "float_market_cap": 1.0,
    }
    (tmp_path / "kline.json").write_text(json.dumps(records), encoding="utf-8")
    (tmp_path / "calendar.json").write_text(json.dumps(calendar), encoding="utf-8")
    (tmp_path / "stock.json").write_text(json.dumps(stock), encoding="utf-8")
    (tmp_path / "readback.json").write_text(json.dumps(readback), encoding="utf-8")
    meta = {
        "stock_code": STOCK_CODE,
        "actual_start_date": records[0]["trade_date"],
        "actual_end_date": records[-1]["trade_date"],
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "adjust": "qfq",
        "rows": 403,
        "kline": {"file": "kline.json", "sha256": _sha(tmp_path / "kline.json")},
        "calendar": {"file": "calendar.json", "sha256": _sha(tmp_path / "calendar.json")},
        "stock": {"file": "stock.json", "sha256": _sha(tmp_path / "stock.json")},
        "readback": {"file": "readback.json", "sha256": _sha(tmp_path / "readback.json")},
        "quant_config": QuantConfig().to_parameters(),
        "quant_expectations": {
            "score": 33,
            "order_count": 24,
            "equity_curve_points": 403,
            "total_return": -0.09165774117956027,
            "final_equity": 90834.22588204397,
        },
    }
    if bad_hash:
        meta["kline"]["sha256"] = "0" * 64
    if mutate_meta:
        mutate_meta(meta)
    (tmp_path / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


def test_load_package_accepts_complete_contract_without_news(tmp_path):
    _write_package(tmp_path)

    package = frozen.load_package(str(tmp_path))

    assert package.stock_code == STOCK_CODE
    assert len(package.bars) == 403
    assert package.news == []
    assert package.stock_info["stock_name"] == "Frozen Stock"


def test_hash_mismatch_blocks_before_package_use(tmp_path):
    _write_package(tmp_path, bad_hash=True)

    with pytest.raises(frozen.FrozenAcceptanceError, match="verification failed"):
        frozen.load_package(str(tmp_path))


def test_metadata_requires_timezone_and_403_rows(tmp_path):
    _write_package(
        tmp_path,
        lambda meta: meta.update({"captured_at": "2026-09-09T12:00:00", "rows": 402}),
    )

    with pytest.raises(frozen.FrozenAcceptanceError, match="timezone"):
        frozen.load_package(str(tmp_path))


def test_rejects_file_path_escape(tmp_path):
    outside = tmp_path.parent / "outside.json"
    outside.write_text("[]", encoding="utf-8")
    _write_package(tmp_path, lambda meta: meta["kline"].update({"file": "../outside.json"}))

    with pytest.raises(frozen.FrozenAcceptanceError, match="escapes"):
        frozen.load_package(str(tmp_path))


def test_frozen_provider_rejects_dates_outside_package(tmp_path):
    _write_package(tmp_path)
    package = frozen.load_package(str(tmp_path))
    provider = frozen.FrozenStockProvider(package)

    with pytest.raises(frozen.FrozenAcceptanceError, match="outside"):
        provider.get_daily_kline(STOCK_CODE, package.start_date - timedelta(days=1), package.end_date)


def test_compare_package_quant_accepts_matching_readback(tmp_path):
    _write_package(tmp_path)
    package = frozen.load_package(str(tmp_path))
    expected = package.metadata["quant_expectations"]

    def comparison(_bars, _readback):
        return {
            "data_equal": True,
            "analysis_equal": True,
            "direct": {
                "meta": {
                    "rows": 403,
                    "parameters": QuantConfig().to_parameters(),
                },
                "score": {"score": expected["score"]},
                "backtest": {
                    "order_count": expected["order_count"],
                    "equity_curve": [0] * expected["equity_curve_points"],
                    "total_return": expected["total_return"],
                    "final_equity": expected["final_equity"],
                },
            },
            "readback": {},
        }

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(frozen.verify_frozen_mysql, "compare_analyses", comparison)
    result = frozen.compare_package_quant(package)
    monkeypatch.undo()

    assert result["data_equal"] is True
    assert result["analysis_equal"] is True


def test_metadata_requires_default_quant_config_and_v1_expectations(tmp_path):
    _write_package(tmp_path, lambda meta: meta.update({"quant_config": {"strategy_name": "other"}}))

    with pytest.raises(frozen.FrozenAcceptanceError, match="quant_config"):
        frozen.load_package(str(tmp_path))

    _write_package(tmp_path, lambda meta: meta["quant_expectations"].update({"score": 34}))

    with pytest.raises(frozen.FrozenAcceptanceError, match="quant expectations"):
        frozen.load_package(str(tmp_path))


def test_mysql_frozen_refuses_imported_db_before_loading_package(monkeypatch, tmp_path):
    _write_package(tmp_path)
    monkeypatch.setitem(frozen.sys.modules, "backend.app.db.session", object())

    with pytest.raises(frozen.FrozenAcceptanceError, match="fresh process"):
        frozen.validate_mysql_frozen(STOCK_CODE, str(tmp_path), None, lambda: "never")


def test_api_kline_must_match_full_frozen_quant_result(monkeypatch, tmp_path):
    _write_package(tmp_path)
    package = frozen.load_package(str(tmp_path))
    records = [row.model_dump(mode="json") for row in package.readback]

    matching = {
        "data_equal": True,
        "analysis_equal": True,
        "direct": {},
        "readback": {},
    }
    monkeypatch.setattr(frozen.verify_frozen_mysql, "compare_analyses", lambda *_: matching)
    frozen._assert_kline_matches_package(records, package, "first query")

    monkeypatch.setattr(
        frozen.verify_frozen_mysql,
        "compare_analyses",
        lambda *_: {**matching, "analysis_equal": False},
    )
    with pytest.raises(frozen.FrozenAcceptanceError, match="full quant comparison"):
        frozen._assert_kline_matches_package(records, package, "cache hit")


def test_frozen_market_source_always_reports_frozen_provenance(tmp_path):
    _write_package(tmp_path)
    package = frozen.load_package(str(tmp_path))
    source = frozen.FrozenMarketDataSource(object(), package)

    assert source.get_query_provenance(STOCK_CODE) == {
        "source_mode": "frozen",
        "provider": "frozen-package",
    }
