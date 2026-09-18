from collections import UserDict
from dataclasses import FrozenInstanceError, asdict
from decimal import Decimal
import json

import pytest

from backend.app.quant.backtest_config import (
    PARAMETERS_UNSET,
    BacktestParameterError,
    BacktestParameters,
    BacktestRequestConfig,
    resolve_backtest_request,
)
from backend.app.quant.config import QuantConfig
from backend.app.quant.validators import QuantValidationError


def test_omitted_parameters_preserve_legacy_but_empty_object_selects_windowed():
    omitted = resolve_backtest_request()
    explicit_sentinel = resolve_backtest_request(PARAMETERS_UNSET)
    empty = resolve_backtest_request({})

    assert omitted == explicit_sentinel
    assert omitted.semantics_version == "v1_legacy"
    assert omitted.required_warmup_rows == 0
    assert empty.semantics_version == "v2_windowed"
    assert empty.required_warmup_rows == 20
    assert omitted.parameters == empty.parameters == BacktestParameters()


def test_cash_only_and_mapping_inputs_select_windowed_with_default_other_parameters():
    result = resolve_backtest_request(UserDict(initial_cash=250000))
    assert result.semantics_version == "v2_windowed"
    assert result.required_warmup_rows == 20
    assert result.parameters.to_parameters() == {
        "ma_short_period": 5,
        "ma_long_period": 20,
        "initial_cash": 250000.0,
        "transaction_cost": 0.001,
        "slippage": 0.0,
    }


def test_full_json_parameters_are_isolated_from_default_quant_config():
    before = asdict(QuantConfig())
    payload = json.loads(
        '{"ma_short_period":2,"ma_long_period":120,"initial_cash":50000,'
        '"transaction_cost":0,"slippage":0.01}'
    )
    request = resolve_backtest_request(payload)
    config = request.parameters.to_quant_config()
    expected = dict(before, **payload)

    assert request.required_warmup_rows == 120
    assert asdict(config) == expected
    assert asdict(QuantConfig()) == before
    assert config is not request.parameters.to_quant_config()
    # Mutating the input or exported mapping cannot mutate the resolved request.
    payload["ma_long_period"] = 30
    exported = request.parameters.to_parameters()
    exported["initial_cash"] = 1
    assert request.parameters.ma_long_period == 120
    assert request.parameters.initial_cash == 50000.0
    json.dumps(request.parameters.to_parameters(), allow_nan=False)


@pytest.mark.parametrize("short,long", [(2, 3), (119, 120)])
def test_period_boundaries_are_inclusive(short, long):
    parameters = BacktestParameters(ma_short_period=short, ma_long_period=long)
    assert parameters.ma_short_period == short
    assert parameters.ma_long_period == long


@pytest.mark.parametrize("short,long", [(1, 20), (2, 2), (20, 5), (5, 121), (0, 0)])
def test_invalid_period_order_or_bounds_are_rejected(short, long):
    with pytest.raises(BacktestParameterError, match="2 <="):
        resolve_backtest_request({"ma_short_period": short, "ma_long_period": long})


@pytest.mark.parametrize("field", ["ma_short_period", "ma_long_period"])
@pytest.mark.parametrize("value", [True, False, "5", 5.0, None])
def test_periods_reject_boolean_string_float_and_null(field, value):
    with pytest.raises(BacktestParameterError, match=field):
        resolve_backtest_request({field: value})


@pytest.mark.parametrize("field", ["initial_cash", "transaction_cost", "slippage"])
@pytest.mark.parametrize("value", [True, "0.01", None, Decimal("0.01")])
def test_financial_parameters_require_native_json_number_types(field, value):
    with pytest.raises(BacktestParameterError, match=field):
        resolve_backtest_request({field: value})


@pytest.mark.parametrize("field", ["initial_cash", "transaction_cost", "slippage"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), 10**400])
def test_nonfinite_or_float_overflow_numbers_are_parameter_errors(field, value):
    with pytest.raises(BacktestParameterError, match="finite"):
        resolve_backtest_request({field: value})


@pytest.mark.parametrize("cash", [0, -1, -0.0])
def test_initial_cash_must_be_positive(cash):
    with pytest.raises(BacktestParameterError, match="initial_cash"):
        resolve_backtest_request({"initial_cash": cash})


@pytest.mark.parametrize("field", ["transaction_cost", "slippage"])
@pytest.mark.parametrize("value", [-0.001, 1, 1.001])
def test_cost_and_slippage_upper_limit_is_exclusive(field, value):
    with pytest.raises(BacktestParameterError, match=r"\[0, 1\)"):
        resolve_backtest_request({field: value})


@pytest.mark.parametrize("value", [0, 0.9999999999999999])
def test_cost_and_slippage_allow_zero_and_values_below_one(value):
    result = resolve_backtest_request({"transaction_cost": value, "slippage": value})
    assert result.parameters.transaction_cost == value
    assert result.parameters.slippage == value


@pytest.mark.parametrize("value", [None, [], "{}", True, 1, BacktestParameters()])
def test_explicit_null_and_non_objects_are_rejected(value):
    with pytest.raises(BacktestParameterError, match="parameters must be an object"):
        resolve_backtest_request(value)


@pytest.mark.parametrize(
    "payload",
    [{"risk_free_rate": 0.0}, {"allow_fractional_shares": False}, {"strategy_name": "other"}],
)
def test_other_quant_fields_cannot_bypass_five_field_whitelist(payload):
    with pytest.raises(BacktestParameterError, match="unknown backtest parameters"):
        resolve_backtest_request(payload)


def test_non_string_keys_return_parameter_error_before_sorting_unknown_keys():
    with pytest.raises(BacktestParameterError, match="names must be strings"):
        resolve_backtest_request({1: 5, "unknown": 2})


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ma_short_period": True},
        {"ma_short_period": 20},
        {"initial_cash": "100000"},
        {"initial_cash": 10**400},
        {"transaction_cost": float("nan")},
        {"slippage": 1},
    ],
)
def test_direct_parameter_constructor_cannot_skip_validation(kwargs):
    with pytest.raises(BacktestParameterError):
        BacktestParameters(**kwargs)


@pytest.mark.parametrize("version", ["v3", "", None, True, []])
def test_direct_request_constructor_rejects_invalid_semantics(version):
    with pytest.raises(BacktestParameterError, match="semantics_version"):
        BacktestRequestConfig(version, BacktestParameters())


@pytest.mark.parametrize("parameters", [{}, None, QuantConfig()])
def test_direct_request_constructor_requires_validated_parameters(parameters):
    with pytest.raises(BacktestParameterError, match="must be BacktestParameters"):
        BacktestRequestConfig("v2_windowed", parameters)


def test_direct_legacy_request_cannot_introduce_custom_parameters():
    with pytest.raises(BacktestParameterError, match="v1_legacy requires default"):
        BacktestRequestConfig("v1_legacy", BacktestParameters(initial_cash=200000))


def test_parameter_errors_integrate_with_quant_validation_and_objects_are_frozen():
    assert issubclass(BacktestParameterError, QuantValidationError)
    result = resolve_backtest_request({})
    with pytest.raises(FrozenInstanceError):
        result.parameters.initial_cash = 1
    with pytest.raises(FrozenInstanceError):
        result.semantics_version = "v1_legacy"
