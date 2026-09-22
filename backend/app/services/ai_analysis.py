from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Protocol

from pydantic import ValidationError
from sqlalchemy import func
from sqlalchemy.engine import Row
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.ai.client import LLMClient
from backend.app.ai.errors import LLMOutputValidationError
from backend.app.ai.output_parser import parse_structured_output
from backend.app.ai.prompts import build_analysis_messages, build_repair_messages
from backend.app.core.errors import DatabaseOperationError
from backend.app.models.ai_analysis import AIAnalysis
from backend.app.schemas.ai import (
    BACKTEST_CONTEXT_VERSION,
    BACKTEST_NEWS_DISCLOSURE,
    BacktestInterpretationContext,
    ReportContext,
    CONTEXT_SCHEMA_VERSION,
    OUTPUT_SCHEMA_VERSION,
    PROMPT_VERSION,
    AIAnalysisData,
    AIReportDetail,
    AIReportMetadata,
    AIReportSummary,
    AnalysisContext,
    PaginatedAIReports,
)
from backend.app.services.analysis_context import AnalysisContextProvider


logger = logging.getLogger(__name__)


def serialize_analysis_context(context: ReportContext) -> tuple[dict, str]:
    snapshot = _normalize_json_numbers(context.model_dump(mode="json"))
    canonical = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return snapshot, hashlib.sha256(canonical).hexdigest()


def normalize_analysis_context(context: ReportContext) -> ReportContext:
    """Normalize JSON numbers before the context reaches Prompt or storage.

    MySQL JSON canonicalizes IEEE ``-0.0`` and fractional digits beyond its
    stable double-precision representation. Doing the same once at the service
    boundary keeps the prompt, stored snapshot and readback hash identical.
    """
    payload = _normalize_json_numbers(context.model_dump(mode="python"))
    return type(context).model_validate(payload)


class AIAnalysisRepository(Protocol):
    def save(
        self,
        analysis: AIAnalysisData,
        context: ReportContext,
        metadata: AIReportMetadata,
    ) -> AIReportDetail:
        """Persist one validated report and its exact input snapshot."""

    def list_reports(
        self,
        stock_code: Optional[str],
        page: int,
        page_size: int,
    ) -> PaginatedAIReports:
        """Return a stable, newest-first summary page."""

    def get_report(self, report_id: int) -> Optional[AIReportDetail]:
        """Read one stored report without invoking external services."""


class SQLAlchemyAIAnalysisRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def save(
        self,
        analysis: AIAnalysisData,
        context: ReportContext,
        metadata: AIReportMetadata,
    ) -> AIReportDetail:
        snapshot, actual_hash = serialize_analysis_context(context)
        if actual_hash != metadata.context_hash:
            raise DatabaseOperationError()
        record = AIAnalysis(
            stock_code=analysis.stock_code,
            quant_score=analysis.quant_score,
            trend=analysis.trend,
            summary=analysis.summary,
            technical_analysis=analysis.technical_analysis,
            quant_analysis=analysis.quant_analysis,
            news_analysis=analysis.news_analysis,
            advantages=analysis.advantages,
            risks=analysis.risks,
            conclusion=analysis.conclusion,
            model_name=analysis.model_name,
            analysis_mode=metadata.analysis_mode,
            backtest_id=metadata.backtest_id,
            context_snapshot=snapshot,
            context_hash=metadata.context_hash,
            source_mode=metadata.source_mode,
            data_as_of=_as_naive_utc(metadata.data_as_of),
            prompt_version=metadata.prompt_version,
            context_schema_version=metadata.context_schema_version,
            output_schema_version=metadata.output_schema_version,
            created_at=_utc_now_naive(),
        )
        try:
            self._db.add(record)
            self._db.flush()
            detail = self._to_detail(record)
            self._db.commit()
            return detail
        except (SQLAlchemyError, ValidationError, ValueError, TypeError) as exc:
            self._db.rollback()
            raise DatabaseOperationError() from exc

    def list_reports(
        self,
        stock_code: Optional[str],
        page: int,
        page_size: int,
    ) -> PaginatedAIReports:
        try:
            count_query = self._db.query(func.count(AIAnalysis.id))
            has_complete_snapshot = (
                AIAnalysis.context_snapshot.is_not(None)
                & AIAnalysis.context_hash.is_not(None)
                & AIAnalysis.source_mode.is_not(None)
                & AIAnalysis.data_as_of.is_not(None)
                & AIAnalysis.prompt_version.is_not(None)
                & AIAnalysis.context_schema_version.is_not(None)
                & AIAnalysis.output_schema_version.is_not(None)
            ).label("has_complete_snapshot")
            is_legacy_report = (
                AIAnalysis.context_snapshot.is_(None)
                & AIAnalysis.context_hash.is_(None)
                & AIAnalysis.source_mode.is_(None)
                & AIAnalysis.data_as_of.is_(None)
                & AIAnalysis.prompt_version.is_(None)
                & AIAnalysis.context_schema_version.is_(None)
                & AIAnalysis.output_schema_version.is_(None)
            ).label("is_legacy_report")
            page_query = self._db.query(
                AIAnalysis.id,
                AIAnalysis.stock_code,
                AIAnalysis.quant_score,
                AIAnalysis.trend,
                AIAnalysis.summary,
                AIAnalysis.model_name,
                AIAnalysis.data_as_of,
                AIAnalysis.created_at,
                AIAnalysis.source_mode,
                AIAnalysis.analysis_mode,
                AIAnalysis.backtest_id,
                AIAnalysis.prompt_version,
                AIAnalysis.context_schema_version,
                AIAnalysis.output_schema_version,
                has_complete_snapshot,
                is_legacy_report,
            )
            if stock_code is not None:
                count_query = count_query.filter(AIAnalysis.stock_code == stock_code)
                page_query = page_query.filter(AIAnalysis.stock_code == stock_code)
            total = int(count_query.scalar() or 0)
            records = (
                page_query.order_by(AIAnalysis.created_at.desc(), AIAnalysis.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return PaginatedAIReports(
                items=[self._to_summary(record) for record in records],
                total=total,
                page=page,
                page_size=page_size,
            )
        except (SQLAlchemyError, ValidationError, ValueError, TypeError) as exc:
            self._db.rollback()
            raise DatabaseOperationError() from exc

    def get_report(self, report_id: int) -> Optional[AIReportDetail]:
        try:
            record = self._db.get(AIAnalysis, report_id)
            if record is None:
                return None
            return self._to_detail(record)
        except (SQLAlchemyError, ValidationError, ValueError, TypeError) as exc:
            self._db.rollback()
            logger.error("stored AI report validation failed", extra={"report_id": report_id})
            raise DatabaseOperationError() from exc

    @staticmethod
    def _to_summary(record: Row) -> AIReportSummary:
        # ``list_reports`` selects individual columns plus the labeled
        # snapshot-state expressions, so this receives a Row, not an ORM object.
        if not record.has_complete_snapshot and not record.is_legacy_report:
            raise ValueError("stored report snapshot metadata is incomplete")
        complete = bool(record.has_complete_snapshot)
        mode = _report_mode(record, legacy=not complete)
        return AIReportSummary(
            analysis_mode=mode,
            backtest_id=record.backtest_id,
            report_id=record.id,
            stock_code=record.stock_code,
            quant_score=record.quant_score,
            trend=record.trend,
            summary=record.summary,
            model_name=record.model_name,
            data_as_of=_as_utc(record.data_as_of),
            created_at=_as_utc(record.created_at),
            source_mode=record.source_mode if complete else "unknown",
            snapshot_status="complete" if complete else "legacy_missing",
        )

    @staticmethod
    def _to_detail(record: AIAnalysis) -> AIReportDetail:
        legacy = record.context_snapshot is None
        context = None
        mode = _report_mode(record, legacy=legacy)
        if legacy and any(
            value is not None
            for value in (
                record.context_hash,
                record.source_mode,
                record.data_as_of,
                record.prompt_version,
                record.context_schema_version,
                record.output_schema_version,
            )
        ):
            raise ValueError("stored report snapshot is incomplete")
        if not legacy:
            required_metadata = (
                record.context_hash,
                record.source_mode,
                record.data_as_of,
                record.prompt_version,
                record.context_schema_version,
                record.output_schema_version,
            )
            if any(value is None for value in required_metadata):
                raise ValueError("stored report metadata is incomplete")
            context_type = BacktestInterpretationContext if mode == "custom_backtest" else AnalysisContext
            context = context_type.model_validate(record.context_snapshot)
            context_stock = context.stock_code if mode == "custom_backtest" else context.stock.stock_code
            if context_stock != record.stock_code:
                raise ValueError("stored report stock mismatch")
            if mode == "custom_backtest" and (context.backtest_id != record.backtest_id or record.news_analysis != BACKTEST_NEWS_DISCLOSURE):
                raise ValueError("stored custom report metadata mismatch")
            _, actual_hash = serialize_analysis_context(context)
            if not record.context_hash or actual_hash != record.context_hash:
                raise ValueError("stored context hash mismatch")
            if _as_utc(record.data_as_of) != _as_utc(context.data_as_of):
                raise ValueError("stored report data timestamp mismatch")
            if (record.source_mode or "unknown") != context.provenance.source_mode:
                raise ValueError("stored report source mode mismatch")
        return AIReportDetail(
            analysis_mode=mode,
            backtest_id=record.backtest_id,
            report_id=record.id,
            stock_code=record.stock_code,
            quant_score=record.quant_score,
            trend=record.trend,
            summary=record.summary,
            technical_analysis=record.technical_analysis,
            quant_analysis=record.quant_analysis,
            news_analysis=record.news_analysis,
            advantages=record.advantages,
            risks=record.risks,
            conclusion=record.conclusion,
            model_name=record.model_name,
            created_at=_as_utc(record.created_at),
            data_as_of=_as_utc(record.data_as_of),
            source_mode="unknown" if legacy else record.source_mode,
            prompt_version=None if legacy else record.prompt_version,
            context_schema_version=None if legacy else record.context_schema_version,
            output_schema_version=None if legacy else record.output_schema_version,
            context_hash=None if legacy else record.context_hash,
            snapshot_status="legacy_missing" if legacy else "complete",
            context_snapshot=context,
        )


class AIAnalysisService:
    def __init__(
        self,
        *,
        context_provider: Optional[AnalysisContextProvider],
        llm_client: LLMClient,
        repository: AIAnalysisRepository,
        backtest_context_provider=None,
    ) -> None:
        self._backtest_context_provider = backtest_context_provider
        self._context_provider = context_provider
        self._llm_client = llm_client
        self._repository = repository

    async def analyze(self, stock_code: str, backtest_id: Optional[int] = None) -> AIReportDetail:
        custom = backtest_id is not None
        if custom:
            if self._backtest_context_provider is None:
                raise RuntimeError("backtest context provider is not configured")
            raw_context = self._backtest_context_provider.get_context(stock_code, backtest_id)
        else:
            if self._context_provider is None:
                raise RuntimeError("standard context provider is not configured")
            raw_context = self._context_provider.get_context(stock_code)
        context = normalize_analysis_context(raw_context)
        _, context_hash = serialize_analysis_context(context)
        content = await self._llm_client.complete_json(build_analysis_messages(context))
        try:
            structured_output = parse_structured_output(content)
        except LLMOutputValidationError:
            repaired_content = await self._llm_client.complete_json(
                build_repair_messages(context, content)
            )
            structured_output = parse_structured_output(repaired_content)

        if custom:
            structured_output = structured_output.model_copy(update={
                "trend": "neutral", "news_analysis": BACKTEST_NEWS_DISCLOSURE,
            })
        quant_score = None if custom else (context.quant_score.score if context.quant_score else None)
        result = AIAnalysisData(
            stock_code=context.stock_code if custom else context.stock.stock_code,
            quant_score=quant_score,
            model_name=self._llm_client.model_name,
            **structured_output.model_dump(),
        )
        metadata = AIReportMetadata(
            analysis_mode="custom_backtest" if custom else "standard",
            backtest_id=backtest_id,
            data_as_of=context.data_as_of,
            source_mode=context.provenance.source_mode,
            prompt_version=BACKTEST_CONTEXT_VERSION if custom else PROMPT_VERSION,
            context_schema_version=BACKTEST_CONTEXT_VERSION if custom else CONTEXT_SCHEMA_VERSION,
            output_schema_version=OUTPUT_SCHEMA_VERSION,
            context_hash=context_hash,
        )
        return self._repository.save(result, context, metadata)

    def list_reports(
        self,
        stock_code: Optional[str],
        page: int,
        page_size: int,
    ) -> PaginatedAIReports:
        return self._repository.list_reports(stock_code, page, page_size)

    def get_report(self, report_id: int) -> Optional[AIReportDetail]:
        return self._repository.get_report(report_id)


class AIReportHistoryService:
    """Read saved reports without constructing generation dependencies."""

    def __init__(self, repository: AIAnalysisRepository) -> None:
        self._repository = repository

    def list_reports(
        self,
        stock_code: Optional[str],
        page: int,
        page_size: int,
    ) -> PaginatedAIReports:
        return self._repository.list_reports(stock_code, page, page_size)

    def get_report(self, report_id: int) -> Optional[AIReportDetail]:
        return self._repository.get_report(report_id)


def _report_mode(record, *, legacy: bool) -> str:
    if legacy and record.analysis_mode is not None:
        raise ValueError("new report mode requires a complete snapshot")
    mode = "standard" if record.analysis_mode is None else record.analysis_mode
    if mode not in ("standard", "custom_backtest"):
        raise ValueError("unknown stored analysis mode")
    if mode == "standard":
        if record.backtest_id is not None:
            raise ValueError("standard report must not reference a backtest")
        expected = (PROMPT_VERSION, CONTEXT_SCHEMA_VERSION, OUTPUT_SCHEMA_VERSION)
    else:
        if legacy or type(record.backtest_id) is not int or record.backtest_id <= 0 or record.quant_score is not None or record.trend != "neutral":
            raise ValueError("inconsistent custom report metadata")
        expected = (BACKTEST_CONTEXT_VERSION, BACKTEST_CONTEXT_VERSION, OUTPUT_SCHEMA_VERSION)
    if not legacy and (record.prompt_version, record.context_schema_version, record.output_schema_version) != expected:
        raise ValueError("unsupported stored report schema version")
    return mode


def _utc_now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def _as_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_json_numbers(value):
    if isinstance(value, float):
        # MySQL JSON stores fractional numbers as IEEE doubles and may change
        # the 16th+ significant decimal digit on readback. Fifteen significant
        # digits are the portable precision boundary for a stable JSON snapshot.
        return 0.0 if value == 0.0 else float(format(value, ".15g"))
    if isinstance(value, dict):
        return {key: _normalize_json_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_json_numbers(item) for item in value]
    return value
