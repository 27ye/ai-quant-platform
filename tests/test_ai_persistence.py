from datetime import date, datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.errors import DatabaseOperationError
from backend.app.db.base import Base
from backend.app.models.ai_analysis import AIAnalysis
from backend.app.schemas.ai import (
    AIAnalysisData,
    AIReportMetadata,
    AnalysisContext,
    DataProvenance,
    MarketSnapshotContext,
    StockAnalysisContext,
)
from backend.app.services.ai_analysis import (
    SQLAlchemyAIAnalysisRepository,
    serialize_analysis_context,
)


def _context(close=1450.5):
    timestamp = datetime(2026, 8, 31, 15, 0, tzinfo=timezone.utc)
    return AnalysisContext(
        stock=StockAnalysisContext(stock_code="600519", stock_name="贵州茅台"),
        market_snapshot=MarketSnapshotContext(
            trade_date=date(2026, 8, 31),
            close=close,
        ),
        data_as_of=timestamp,
        provenance=DataProvenance(
            source_mode="live",
            provider="test-provider",
            market_start_date=date(2026, 1, 1),
            market_end_date=date(2026, 8, 31),
            market_rows=120,
            news_status="empty",
            news_count=0,
            retrieved_at=timestamp,
        ),
    )


def _analysis(stock_code="600519", summary="趋势偏强。"):
    return AIAnalysisData(
        stock_code=stock_code,
        quant_score=82,
        trend="bullish",
        summary=summary,
        technical_analysis="技术指标整体偏强。",
        quant_analysis="量化评分较高。",
        news_analysis="新闻数据暂不可用。",
        advantages=["品牌优势"],
        risks=["市场波动"],
        conclusion="结合风险承受能力审慎判断。",
        model_name="test-model",
    )


def _metadata(context):
    _, context_hash = serialize_analysis_context(context)
    return AIReportMetadata(
        data_as_of=context.data_as_of,
        source_mode=context.provenance.source_mode,
        prompt_version="v2.0",
        context_schema_version="v2.0",
        output_schema_version="v2.0",
        context_hash=context_hash,
    )


@pytest.fixture
def repository():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield SQLAlchemyAIAnalysisRepository(db), db
    engine.dispose()


def test_repository_saves_complete_snapshot_and_returns_database_identity(repository):
    repo, db = repository
    context = _context()

    result = repo.save(_analysis(), context, _metadata(context))

    assert result.report_id > 0
    assert result.created_at.tzinfo == timezone.utc
    assert result.context_snapshot == context
    assert result.context_hash == serialize_analysis_context(context)[1]
    record = db.get(AIAnalysis, result.report_id)
    assert record.context_snapshot == context.model_dump(mode="json")
    assert record.prompt_version == "v2.0"
    assert record.source_mode == "live"


def test_context_hash_is_stable_and_changes_with_any_context_field():
    first_snapshot, first_hash = serialize_analysis_context(_context())
    repeated_snapshot, repeated_hash = serialize_analysis_context(_context())
    changed_snapshot, changed_hash = serialize_analysis_context(_context(close=1451.0))

    assert first_snapshot == repeated_snapshot
    assert first_hash == repeated_hash
    assert len(first_hash) == 64
    assert changed_snapshot != first_snapshot
    assert changed_hash != first_hash


def test_context_hash_normalizes_negative_zero_for_mysql_json_readback():
    negative = _context(close=-0.0)
    positive = _context(close=0.0)

    negative_snapshot, negative_hash = serialize_analysis_context(negative)
    positive_snapshot, positive_hash = serialize_analysis_context(positive)

    assert negative_snapshot["market_snapshot"]["close"] == 0.0
    assert negative_hash == positive_hash


def test_repository_rolls_back_database_failure():
    class FailingSession(Session):
        rolled_back = False

        def commit(self):
            raise SQLAlchemyError("commit failed")

        def rollback(self):
            self.rolled_back = True
            return super().rollback()

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=FailingSession)
    context = _context()
    with factory() as db:
        with pytest.raises(DatabaseOperationError):
            SQLAlchemyAIAnalysisRepository(db).save(
                _analysis(), context, _metadata(context)
            )
        assert db.rolled_back is True
        assert db.query(AIAnalysis).count() == 0
    engine.dispose()


def test_repository_lists_stably_filters_and_omits_context(repository):
    repo, _ = repository
    first_context = _context()
    first = repo.save(_analysis(summary="第一份"), first_context, _metadata(first_context))
    second_context = _context(close=1451.0)
    second = repo.save(
        _analysis(summary="第二份"),
        second_context,
        _metadata(second_context),
    )

    page = repo.list_reports("600519", page=1, page_size=1)
    empty = repo.list_reports("000001", page=1, page_size=20)

    assert page.total == 2
    assert [item.report_id for item in page.items] == [second.report_id]
    assert page.items[0].report_id != first.report_id
    assert "context_snapshot" not in page.items[0].model_dump()
    assert empty.items == []
    assert empty.total == 0


def test_repository_reads_legacy_row_without_reconstructing_snapshot(repository):
    repo, db = repository
    legacy = AIAnalysis(
        stock_code="600519",
        quant_score=50,
        trend="neutral",
        summary="旧报告",
        technical_analysis="旧技术分析",
        quant_analysis="旧量化分析",
        news_analysis="旧新闻分析",
        advantages=["旧优势"],
        risks=["旧风险"],
        conclusion="旧结论",
        model_name="legacy-model",
        created_at=datetime(2025, 1, 1),
    )
    db.add(legacy)
    db.commit()

    result = repo.get_report(legacy.id)

    assert result is not None
    assert result.snapshot_status == "legacy_missing"
    assert result.source_mode == "unknown"
    assert result.context_snapshot is None
    assert result.context_hash is None
    assert result.prompt_version is None


def test_repository_rejects_corrupted_new_snapshot(repository):
    repo, db = repository
    corrupt = AIAnalysis(
        stock_code="600519",
        quant_score=50,
        trend="neutral",
        summary="损坏报告",
        technical_analysis="技术分析",
        quant_analysis="量化分析",
        news_analysis="新闻分析",
        advantages=["优势"],
        risks=["风险"],
        conclusion="结论",
        model_name="test-model",
        context_snapshot={"unexpected": "data"},
        context_hash="0" * 64,
        source_mode="live",
        data_as_of=datetime(2026, 8, 31),
        prompt_version="v2.0",
        context_schema_version="v2.0",
        output_schema_version="v2.0",
        created_at=datetime(2026, 8, 31),
    )
    db.add(corrupt)
    db.commit()

    with pytest.raises(DatabaseOperationError):
        repo.get_report(corrupt.id)


def test_repository_does_not_treat_partial_v2_metadata_as_legacy(repository):
    repo, db = repository
    partial = AIAnalysis(
        stock_code="600519",
        quant_score=50,
        trend="neutral",
        summary="不完整报告",
        technical_analysis="技术分析",
        quant_analysis="量化分析",
        news_analysis="新闻分析",
        advantages=["优势"],
        risks=["风险"],
        conclusion="结论",
        model_name="test-model",
        context_hash="0" * 64,
        created_at=datetime(2026, 8, 31),
    )
    db.add(partial)
    db.commit()

    with pytest.raises(DatabaseOperationError):
        repo.get_report(partial.id)
