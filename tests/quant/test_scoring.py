import pytest

from backend.app.quant.scoring import calculate_quant_score
from backend.app.quant.validators import InsufficientDataError


def test_score_total_equals_components(synthetic_daily_data):
    result = calculate_quant_score(synthetic_daily_data)
    assert result["score"] == sum(
        result[field]
        for field in ("trend_score", "momentum_score", "volume_score", "risk_score")
    )


def test_score_components_respect_formal_caps(synthetic_daily_data):
    result = calculate_quant_score(synthetic_daily_data)
    assert 0 <= result["trend_score"] <= 40
    assert 0 <= result["momentum_score"] <= 25
    assert 0 <= result["volume_score"] <= 20
    assert 0 <= result["risk_score"] <= 15
    assert 0 <= result["score"] <= 100


def test_score_returns_rule_reasons_and_provisional_status(synthetic_daily_data):
    result = calculate_quant_score(synthetic_daily_data)
    assert result["contract_status"] == "provisional"
    assert result["reasons"]
    assert all(isinstance(reason, str) for reason in result["reasons"])


def test_score_rejects_insufficient_warmup(frame_factory):
    with pytest.raises(InsufficientDataError, match="at least 60 rows"):
        calculate_quant_score(frame_factory([100.0] * 59))
