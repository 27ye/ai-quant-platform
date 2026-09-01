from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.ai.client import LLMClient
from backend.app.ai.errors import LLMOutputValidationError
from backend.app.ai.output_parser import parse_structured_output
from backend.app.ai.prompts import build_analysis_messages, build_repair_messages
from backend.app.core.errors import DatabaseOperationError
from backend.app.models.ai_analysis import AIAnalysis
from backend.app.schemas.ai import AIAnalysisData
from backend.app.services.analysis_context import AnalysisContextProvider


class AIAnalysisRepository(Protocol):
    def save(self, analysis: AIAnalysisData) -> None:
        """Persist a validated AI analysis result."""


class SQLAlchemyAIAnalysisRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def save(self, analysis: AIAnalysisData) -> None:
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
        )
        try:
            self._db.add(record)
            self._db.commit()
        except SQLAlchemyError as exc:
            self._db.rollback()
            raise DatabaseOperationError() from exc


class AIAnalysisService:
    def __init__(
        self,
        *,
        context_provider: AnalysisContextProvider,
        llm_client: LLMClient,
        repository: AIAnalysisRepository,
    ) -> None:
        self._context_provider = context_provider
        self._llm_client = llm_client
        self._repository = repository

    async def analyze(self, stock_code: str) -> AIAnalysisData:
        context = self._context_provider.get_context(stock_code)
        content = await self._llm_client.complete_json(
            build_analysis_messages(context)
        )
        try:
            structured_output = parse_structured_output(content)
        except LLMOutputValidationError:
            repaired_content = await self._llm_client.complete_json(
                build_repair_messages(context, content)
            )
            structured_output = parse_structured_output(repaired_content)

        quant_score = context.quant_score.score if context.quant_score else None
        result = AIAnalysisData(
            stock_code=context.stock.stock_code,
            quant_score=quant_score,
            model_name=self._llm_client.model_name,
            **structured_output.model_dump(),
        )
        self._repository.save(result)
        return result
