"""Offline C/D compatibility evidence on a checkout containing PR #10 and C V2.

Uses synthetic bars, a fake LLM, and a temporary SQLite database only. This is
not HTTP, MySQL, migration, live-market, real-LLM, or final-combination acceptance.
Run from any directory; --output-dir must name a directory that does not exist.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import importlib
import json
import math
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXED_TIME = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)
NOT_VERIFIED = [
    "HTTP routes and HTTP error codes",
    "Real MySQL storage precision, migrations, or server restart",
    "Real LLM, live providers, or three-stock real-data acceptance",
    "A frontend or B parameterized-backtest API/persistence integration",
    "Final B+D+C combined Git SHA or overall V2 acceptance",
]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                               allow_nan=False) + "\n", encoding="utf-8")


def capabilities():
    """Fail explicitly on the original C/PR9 baseline; never silently skip."""
    required = {
        "backend.app.services.ai_analysis": (
            "normalize_analysis_context", "serialize_analysis_context",
            "SQLAlchemyAIAnalysisRepository", "AIAnalysisService",
        ),
        "backend.app.schemas.ai": ("AIReportDetail", "AIReportMetadata"),
        "backend.app.services.ai_context_adapter": ("StockQuantAnalysisAdapter",),
        "backend.app.quant.windowed_backtest": ("run_backtest_request",),
    }
    modules = {}
    try:
        for name, symbols in required.items():
            module = importlib.import_module(name)
            missing = [symbol for symbol in symbols if not hasattr(module, symbol)]
            if missing:
                raise RuntimeError(name + " missing " + ", ".join(missing))
            modules[name] = module
        schema = modules["backend.app.schemas.ai"]
        check("context_snapshot" in schema.AIReportDetail.model_fields,
              "AIReportDetail lacks context_snapshot")
        repository = modules["backend.app.services.ai_analysis"].SQLAlchemyAIAnalysisRepository
        check(all(hasattr(repository, name) for name in ("get_report", "list_reports")),
              "AI history repository methods are absent")
        adapter = modules["backend.app.services.ai_context_adapter"].StockQuantAnalysisAdapter
        check(hasattr(adapter, "get_market_provenance"), "adapter provenance is absent")
    except (ImportError, AttributeError, RuntimeError, AssertionError) as exc:
        raise RuntimeError("Requires PR10 AI history capabilities plus C V2 in this checkout: "
                           + str(exc)) from exc
    return modules


def synthetic_frame(pd):
    rows = []
    previous = None
    for index, stamp in enumerate(pd.bdate_range("2025-01-02", periods=220)):
        close = 80 + index * 0.015 + math.sin(index / 7.0) * 7 + 0.123456789123456
        opening = close * (1 + math.cos(index / 4.0) * 0.003)
        rows.append({
            "stock_code": "600519", "trade_date": stamp.date(),
            "open": opening, "high": max(opening, close) + 0.5,
            "low": min(opening, close) - 0.5, "close": close,
            "volume": float(10000 + index * 17), "amount": close * (10000 + index * 17),
            "turnover_rate": 0.01234567891234567,
            "change_pct": -0.0 if previous is None else close / previous - 1,
        })
        previous = close
    frame = pd.DataFrame(rows)
    frame.attrs["data_mode"] = "synthetic_c_ai_compatibility"
    return frame


def run_validation(output, report, event_loop):
    modules = capabilities()
    import pandas as pd
    from sqlalchemy import BIGINT, create_engine
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.orm import Session
    from backend.app.core.errors import DatabaseOperationError
    from backend.app.models.ai_analysis import AIAnalysis
    from backend.app.services import analysis_context as context_module
    from backend.app.quant import pipeline as pipeline_module
    from backend.app.quant.serialization import to_json_safe

    # SQLite-only, process-local compilation; no D models or MySQL DDL change.
    @compiles(BIGINT, "sqlite")
    def compile_bigint_sqlite(type_, compiler, **kw):
        return "INTEGER"

    service_module = modules["backend.app.services.ai_analysis"]
    adapter_module = modules["backend.app.services.ai_context_adapter"]
    window_module = modules["backend.app.quant.windowed_backtest"]
    schema = modules["backend.app.schemas.ai"]
    normalize = service_module.normalize_analysis_context
    serialize = service_module.serialize_analysis_context
    real_pipeline = pipeline_module.analyze_quant_dataframe
    frame = synthetic_frame(pd)
    records = frame.to_dict(orient="records")
    original_frame = frame.copy(deep=True)
    events = {"market": 0, "quant": 0, "llm": 0, "context": 0}
    forbidden_calls = []
    checks = report["checks"]

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return FIXED_TIME.replace(tzinfo=None) if tz is None else FIXED_TIME.astimezone(tz)

    class Source:
        def query_daily(self, stock_code, **kwargs):
            check(stock_code == "600519", "unexpected stock code")
            check(kwargs == {"min_rows": 60, "max_stale_days": 3, "max_gap_days": 15},
                  "AI default data requirements changed")
            events["market"] += 1
            return [SimpleNamespace(model_dump=lambda row=row: copy.deepcopy(row))
                    for row in records]

        def get_query_provenance(self, stock_code):
            # D schema has no synthetic enum. Both provider and report identify
            # this frozen in-memory fixture explicitly as synthetic, never live.
            return {"source_mode": "frozen", "provider": "synthetic_c_ai_fixture"}

    class Stock:
        def get_stock_info(self, stock_code):
            return SimpleNamespace(stock_code=stock_code,
                                   stock_name="合成测试股票（非真实行情）", industry=None)

    class News:
        def get_news(self, stock_code, limit):
            return []

    def tracked_pipeline(data):
        events["quant"] += 1
        return real_pipeline(data)

    def build_context():
        events["context"] += 1
        adapter = adapter_module.StockQuantAnalysisAdapter(
            market_data_source=Source(), stock_service=Stock(), quant_pipeline=tracked_pipeline,
        )
        provider = context_module.ServiceAnalysisContextProvider(
            stock_service=adapter, quant_service=adapter,
            backtest_service=adapter, news_service=News(),
        )
        before = dict(events)
        with patch.object(context_module, "datetime", FixedDateTime):
            result = provider.get_context("600519")
        check(events["market"] == before["market"] + 1, "context fetched more than once")
        check(events["quant"] == before["quant"] + 1, "context calculated more than once")
        return result

    default = real_pipeline(frame)
    default_bytes = canonical(default)
    context_before = build_context()
    raw_context_bytes = canonical(context_before.model_dump(mode="json"))
    expected = context_before.model_copy(deep=True)
    expected.technical_indicators = schema.TechnicalIndicatorContext(**{
        key: default["latest"][key] for key in schema.TechnicalIndicatorContext.model_fields
    })
    expected.quant_score = schema.QuantScoreContext(**{
        key: default["score"][key] for key in schema.QuantScoreContext.model_fields
    })
    expected.backtest_metrics = schema.BacktestMetricsContext(**{
        key: default["backtest"][key] for key in schema.BacktestMetricsContext.model_fields
    })
    check(normalize(context_before) == normalize(expected), "D context differs from default C")
    custom = window_module.run_backtest_request(
        frame, start_date=records[130]["trade_date"], end_date=records[210]["trade_date"],
        parameters={"ma_short_period": 10, "ma_long_period": 30,
                    "initial_cash": 12345.25, "transaction_cost": 0.002, "slippage": 0.001},
    )
    custom_bytes = canonical(custom)
    context_after = build_context()  # Fresh adapter avoids cache hiding mutation.
    check(context_before == context_after, "custom V2 affected default AI context")
    check(canonical(real_pipeline(frame)) == default_bytes, "custom V2 affected default C")
    check(frame.equals(original_frame) and frame.attrs == original_frame.attrs,
          "input frame changed")
    checks.append("default_C_projection_and_fresh_AI_context_unchanged_after_custom_V2")
    checks.append("AI_default_pipeline_and_market_called_once_per_context")

    normalized = normalize(context_before)
    normalized_bytes = canonical(normalized.model_dump(mode="json"))
    check(normalized_bytes != raw_context_bytes, "fixture did not exercise 15-digit normalization")
    check(canonical(context_before.model_dump(mode="json")) == raw_context_bytes,
          "D normalization mutated its input context")
    check(canonical(default) == default_bytes and canonical(custom) == custom_bytes,
          "AI normalization changed C output")
    snapshot = custom["input_snapshot"]
    check(custom["data_hash"] == snapshot["sha256"] == digest({
        key: value for key, value in snapshot.items() if key != "sha256"
    }), "C input hash changed")
    before_snapshot, before_hash = serialize(context_before)
    check(serialize(context_after) == (before_snapshot, before_hash), "AI hash changed")
    zero_context = context_before.model_copy(deep=True)
    zero_context.market_snapshot.change_pct = -0.0
    positive_context = zero_context.model_copy(deep=True)
    positive_context.market_snapshot.change_pct = 0.0
    check(serialize(zero_context) == serialize(positive_context), "AI negative-zero hash differs")
    checks.append("D_15_digit_and_negative_zero_normalization_only_changes_AI_copy")
    checks.append("C_input_snapshot_hash_preserved_and_AI_context_hash_reproducible")

    class LiveContext:
        def get_context(self, stock_code):
            return build_context()

    class FakeLLM:
        model_name = "synthetic_fake_llm_no_network"

        async def complete_json(self, messages):
            events["llm"] += 1
            prompt_context = json.loads(messages[-1]["content"].split("analysis_context=", 1)[1])
            check(prompt_context == before_snapshot, "prompt differs from saved context")
            return json.dumps({
                "trend": "neutral", "summary": "仅供离线兼容测试的合成报告。",
                "technical_analysis": "使用默认 C 指标的测试投影。",
                "quant_analysis": "评分由默认 C 流水线提供。",
                "news_analysis": "新闻数据暂不可用。", "advantages": ["测试数据可复现"],
                "risks": ["合成行情不能证明真实策略收益"], "conclusion": "仅验证模块兼容。",
            }, ensure_ascii=False)

    def forbidden(name):
        def fail(*args, **kwargs):
            forbidden_calls.append(name)
            raise AssertionError("Forbidden during history read: " + name)
        return fail

    with tempfile.TemporaryDirectory(prefix="c-ai-history-") as temporary:
        db_url = "sqlite:///" + (Path(temporary) / "history.sqlite").as_posix()
        engine = create_engine(db_url)
        AIAnalysis.__table__.create(engine)
        try:
            with Session(engine) as first_session:
                service = service_module.AIAnalysisService(
                    context_provider=LiveContext(), llm_client=FakeLLM(),
                    repository=service_module.SQLAlchemyAIAnalysisRepository(first_session),
                )
                saved = event_loop.run_until_complete(service.analyze("600519"))
                check(saved.context_snapshot.model_dump(mode="json") == before_snapshot,
                      "saved context differs from prompt")
                check(saved.context_hash == before_hash, "saved AI hash differs")
                legacy = AIAnalysis(
                    stock_code="600519", quant_score=50, trend="neutral", summary="合成旧记录",
                    technical_analysis="旧技术说明", quant_analysis="旧量化说明",
                    news_analysis="无新闻", advantages=["测试"], risks=["测试"], conclusion="测试",
                    model_name="synthetic_legacy", created_at=datetime(2025, 1, 1),
                )
                first_session.add(legacy)
                first_session.commit()
                legacy_id = legacy.id
            # Close the connection pool too, then create a fresh engine/session.
            engine.dispose()
            engine = create_engine(db_url)
            event_counts_before_history = dict(events)
            with ExitStack() as guards:
                for module_name, attribute in (
                    ("backend.app.quant.pipeline", "analyze_quant_dataframe"),
                    ("backend.app.quant.backtest", "run_backtest"),
                    ("backend.app.quant.windowed_backtest", "run_backtest_request"),
                    ("backend.app.quant", "run_backtest_request"),
                    ("backend.app.services.ai_context_adapter", "analyze_quant_dataframe"),
                ):
                    module = importlib.import_module(module_name)
                    guards.enter_context(patch.object(module, attribute, forbidden(attribute)))
                guards.enter_context(patch.object(adapter_module.StockQuantAnalysisAdapter,
                                                   "_load_quant_result", forbidden("adapter")))
                guards.enter_context(patch.object(LiveContext, "get_context", forbidden("context")))
                guards.enter_context(patch.object(Source, "query_daily", forbidden("market")))
                guards.enter_context(patch.object(FakeLLM, "complete_json", forbidden("llm")))
                with Session(engine) as fresh_session:
                    service = service_module.AIAnalysisService(
                        context_provider=LiveContext(), llm_client=FakeLLM(),
                        repository=service_module.SQLAlchemyAIAnalysisRepository(fresh_session),
                    )
                    restored = service.get_report(saved.report_id)
                    check(restored.model_dump(mode="json") == saved.model_dump(mode="json"),
                          "fresh-session history changed saved report")
                    page = service.list_reports("600519", page=1, page_size=1)
                    check(page.total == 2 and page.items[0].report_id == saved.report_id,
                          "history pagination/sorting changed")
                    check("context_snapshot" not in page.items[0].model_dump(),
                          "history summary contains full context")
                    old = service.get_report(legacy_id)
                    check(old.snapshot_status == "legacy_missing" and old.source_mode == "unknown"
                          and old.context_snapshot is None and old.context_hash is None,
                          "legacy history was not preserved as missing")
                    check(service.get_report(999999) is None, "missing history was fabricated")
                    checks.append("SQLite_new_engine_and_session_history_matches_without_external_calls")
                    checks.append("legacy_missing_and_unknown_ID_do_not_recompute")
                    record = fresh_session.get(AIAnalysis, saved.report_id)
                    tampered = copy.deepcopy(record.context_snapshot)
                    tampered["market_snapshot"]["close"] += 1.0
                    record.context_snapshot = tampered
                    fresh_session.commit()
                    try:
                        service.get_report(saved.report_id)
                    except DatabaseOperationError:
                        pass
                    else:
                        raise AssertionError("tampered AI context hash was accepted")
                    checks.append("tampered_AI_context_hash_rejected_without_recompute")
            check(events == event_counts_before_history and not forbidden_calls,
                  "history performed a forbidden calculation or I/O")
        finally:
            engine.dispose()

    write_json(output / "synthetic-input.json", to_json_safe(records))
    write_json(output / "default-c-result.json", default)
    write_json(output / "custom-v2-result.json", custom)
    write_json(output / "ai-context-raw.json", context_before.model_dump(mode="json"))
    write_json(output / "ai-context-normalized.json", before_snapshot)
    write_json(output / "saved-ai-report.json", saved.model_dump(mode="json"))
    report.update({
        "status": "passed", "synthetic_rows": len(records),
        "source_mode": "frozen", "provider": "synthetic_c_ai_fixture",
        "default_score": default["score"]["score"], "events": events,
        "history_forbidden_calls": forbidden_calls,
        "data_hash": custom["data_hash"], "context_hash": before_hash,
        "default_c_result_sha256": digest(default), "custom_c_result_sha256": digest(custom),
        "sqlite": "temporary file removed; engine and session recreated before readback",
    })


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        parser.error("--output-dir must not already exist: " + str(output))
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "failed", "scope": "offline PR10+C compatibility only",
              "data": "synthetic; no real stock-price observations",
              "database": "temporary SQLite, NOT MySQL", "llm": "fake, NOT real LLM",
              "checks": [], "not_verified": NOT_VERIFIED, "checkout": str(ROOT)}
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
                         capture_output=True, check=False)
    report["checkout_head"] = git.stdout.strip() if git.returncode == 0 else None
    report["checkout_head_note"] = "HEAD alone does not identify uncommitted C overlay files"
    source_files = [ROOT / "backend/app/quant/windowed_backtest.py",
                    ROOT / "backend/app/quant/backtest.py",
                    ROOT / "backend/app/services/ai_context_adapter.py",
                    ROOT / "backend/app/services/ai_analysis.py", Path(__file__).resolve()]
    report["source_file_sha256"] = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_files if path.is_file()
    }
    # Windows ProactorEventLoop initializes an OS-local socketpair. Create it
    # before the network guard; all validation and fake-LLM execution stay guarded.
    event_loop = asyncio.new_event_loop()
    try:
        # A whole-run guard makes accidental networking fail, even before history.
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), \
                patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")):
            run_validation(output, report, event_loop)
    except Exception as exc:
        report["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        write_json(output / "report.json", report)
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 1
    finally:
        event_loop.close()
    write_json(output / "report.json", report)
    print("PASS: offline C/PR10 AI history compatibility; SQLite + fake LLM + synthetic bars.")
    print("Evidence: " + str(output / "report.json"))
    print("Not final B+D+C, HTTP, MySQL, live-data, or real-LLM acceptance.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
