import pytest

from backend.app.ai.errors import LLMOutputValidationError
from backend.app.ai.output_parser import parse_structured_output


VALID_OUTPUT = """{
  "trend": "neutral",
  "summary": "趋势信号混合。",
  "technical_analysis": "技术指标暂未形成一致方向。",
  "quant_analysis": "量化结果需结合风险理解。",
  "news_analysis": "新闻信息未形成一致催化。",
  "advantages": ["品牌优势"],
  "risks": ["市场波动"],
  "conclusion": "保持审慎并持续跟踪。"
}"""


def test_output_parser_accepts_json_and_optional_fence():
    assert parse_structured_output(VALID_OUTPUT).trend == "neutral"
    assert parse_structured_output(f"```json\n{VALID_OUTPUT}\n```").trend == "neutral"


@pytest.mark.parametrize(
    "invalid_output",
    [
        "not json",
        '{"trend":"neutral"}',
        VALID_OUTPUT.replace('"neutral"', '"uncertain"'),
        VALID_OUTPUT[:-1] + ',"unexpected":true}',
    ],
)
def test_output_parser_rejects_invalid_output(invalid_output):
    with pytest.raises(LLMOutputValidationError):
        parse_structured_output(invalid_output)
