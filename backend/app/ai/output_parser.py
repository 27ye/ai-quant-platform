import json

from pydantic import ValidationError

from backend.app.ai.errors import LLMOutputValidationError
from backend.app.schemas.ai import AIAnalysisStructuredOutput


def parse_structured_output(content: str) -> AIAnalysisStructuredOutput:
    normalized = _strip_optional_json_fence(content)
    try:
        payload = json.loads(normalized)
        return AIAnalysisStructuredOutput.model_validate(payload)
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise LLMOutputValidationError(
            "LLM output does not match the analysis schema"
        ) from exc


def _strip_optional_json_fence(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```json") and stripped.endswith("```"):
        return stripped[7:-3].strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        return stripped[3:-3].strip()
    return stripped
