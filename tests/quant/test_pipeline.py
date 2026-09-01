import ast
import json
from pathlib import Path

from backend.app.quant.pipeline import analyze_quant_dataframe


def test_pipeline_output_is_strict_json_safe(synthetic_daily_data):
    result = analyze_quant_dataframe(synthetic_daily_data)
    encoded = json.dumps(result, allow_nan=False)
    assert encoded


def test_pipeline_contract_and_series_shape(synthetic_daily_data):
    result = analyze_quant_dataframe(synthetic_daily_data)
    assert result["meta"]["stock_code"] == "600519"
    assert result["meta"]["adjust"] == "qfq"
    assert result["meta"]["contract_status"] == "provisional"
    assert result["meta"]["data_mode"] == "synthetic_test_fixture"
    assert len(result["series"]["indicators"]) == len(synthetic_daily_data)
    assert result["latest"]["trade_date"] == synthetic_daily_data.iloc[-1][
        "trade_date"
    ].strftime("%Y-%m-%d")


def test_pipeline_exposes_stable_ai_adapter_fields(synthetic_daily_data):
    result = analyze_quant_dataframe(synthetic_daily_data)

    assert {
        "trade_date",
        "ma5",
        "ma10",
        "ma20",
        "ma60",
        "macd",
        "macd_signal",
        "macd_hist",
        "rsi14",
        "boll_upper",
        "boll_middle",
        "boll_lower",
    } <= result["latest"].keys()
    assert {"score", "level", "reasons"} <= result["score"].keys()
    assert {
        "strategy_name",
        "start_date",
        "end_date",
        "total_return",
        "annual_return",
        "max_drawdown",
        "sharpe_ratio",
        "win_rate",
        "trade_count",
        "benchmark_return",
    } <= result["backtest"].keys()


def test_indicator_warmups_become_json_null(synthetic_daily_data):
    result = analyze_quant_dataframe(synthetic_daily_data)
    assert result["series"]["indicators"][0]["ma60"] is None
    assert result["series"]["indicators"][58]["ma60"] is None
    assert result["series"]["indicators"][59]["ma60"] is not None


def test_quant_module_has_no_external_io_dependencies():
    quant_dir = Path(__file__).resolve().parents[2] / "backend" / "app" / "quant"
    forbidden_roots = {
        "akshare",
        "requests",
        "httpx",
        "fastapi",
        "sqlalchemy",
        "pymysql",
        "openai",
    }
    for path in quant_dir.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                assert module.split(".")[0] not in forbidden_roots
                assert not module.startswith("backend.app.data")
        lowered = source.lower()
        assert "http://" not in lowered
        assert "https://" not in lowered
        assert "langchain" not in lowered
