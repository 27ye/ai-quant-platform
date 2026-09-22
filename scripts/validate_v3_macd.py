"""Export reproducible offline C V3 evidence; never contacts providers/DB/LLM.

Usage: python scripts/validate_v3_macd.py --output-dir <new-directory>
       python scripts/validate_v3_macd.py --verify <existing-directory>
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PureWindowsPath
import platform
import socket
import subprocess
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.app.quant import run_backtest_request, resolve_backtest_request

SETS = {
    "default": {},
    "fast6_slow13_signal5": {"macd_fast_period": 6, "macd_slow_period": 13, "macd_signal_period": 5},
    "fast20_slow40_signal12_cost": {"macd_fast_period": 20, "macd_slow_period": 40,
        "macd_signal_period": 12, "initial_cash": 200000, "transaction_cost": 0.002, "slippage": 0.001},
}
NOT_VERIFIED = ["HTTP MACD wiring", "MySQL persistence/restart GET", "live provider",
                "real LLM/custom context integration", "browser", "final combined V3 SHA"]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def write_json(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def replay(result):
    snapshot = dict(result["input_snapshot"])
    recorded_hash = snapshot.pop("sha256")
    require(digest(canonical(snapshot).encode()) == recorded_hash == result["data_hash"], "input hash mismatch")
    frame = pd.DataFrame(snapshot["rows"])
    frame.attrs["data_mode"] = snapshot["data_mode"]
    strategy = "macd" if result["strategy_name"] == "macd_dif_above_dea_long_only" else "ma_cross"
    fields = resolve_backtest_request({}, strategy=strategy).parameters.to_parameters()
    parameters = {key: result["effective_parameters"][key] for key in fields}
    actual = run_backtest_request(frame, strategy=strategy, parameters=parameters,
        start_date=result["requested_start_date"], end_date=result["requested_end_date"])
    require(canonical(actual) == canonical(result), "full replay result mismatch (including types)")


def numeric_example(result):
    """A review fixture for C3; not the D AI context schema or a saved report."""
    fields = ("stock_code", "strategy_name", "algorithm_version", "semantics_version", "effective_parameters",
        "requested_start_date", "requested_end_date", "start_date", "end_date", "warmup", "initial_equity",
        "initial_cash", "final_equity", "total_return", "annual_return", "max_drawdown", "sharpe_ratio",
        "win_rate", "trade_count", "order_count", "benchmark_return", "current_position", "execution_assumptions", "data_hash")
    return {"fixture_only_not_saved_report": True, "quant_score": None,
        "source_record_fields": "record_id/source/saved_at must come from B, absent in this C-only fixture",
        "values_from_same_result": {key: result[key] for key in fields},
        "curve_summary": {
            "points": len(result["equity_curve"]), "first": result["equity_curve"][0],
            "last": result["equity_curve"][-1],
            "normalized_last_return": result["equity_curve"][-1]["equity"] / result["initial_cash"] - 1,
            "minimum_drawdown": min(row["drawdown"] for row in result["drawdown_curve"]),
        }}


def verify(output):
    manifest = read_json(output / "manifest.json")
    require(manifest["status"] == "passed", "evidence status is not passed")
    for name, sha in manifest["files_sha256"].items():
        path = (output / name).resolve()
        require(path.parent == output.resolve(), "non-local evidence path")
        require(digest(path.read_bytes()) == sha, "file hash mismatch: " + name)
    for name in manifest["result_files"]:
        replay(read_json(output / name))
    require(len(manifest["matrix"]) == 9, "expected 3 stocks x 3 configurations")
    print("PASS: file hashes and complete snapshot replay; 9 MACD + 1 MA results")


def export(output):
    output.mkdir(parents=True, exist_ok=False)
    source_paths = sorted(list((ROOT / "backend/app/quant").glob("*.py")) +
                          list((ROOT / "tests/quant").glob("*.py")) + [Path(__file__).resolve()])
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    status = subprocess.check_output(["git", "status", "--porcelain", "--", "backend/app/quant", "tests/quant", "scripts/validate_v3_macd.py"], cwd=ROOT, text=True)
    require(not status.strip(), "commit C source/tests before producing SHA-bound evidence")
    manifest = {"status": "running", "scope": "offline C quant only", "code_sha": head,
        "environment": {"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__},
        "source_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): digest(p.read_bytes()) for p in source_paths},
        "data_batch": "20260917", "data_source": "tencent qfq delivery-only normalized 4/2/6; not live eastmoney",
        "window": ["2025-07-04", "2026-08-31"], "not_verified": NOT_VERIFIED,
        "matrix": [], "result_files": [], "files_sha256": {}, "input_files_sha256": {}}
    write_json(output / "manifest.json", manifest)
    package = ROOT / "docs/evidence/c-delivery-20260917"
    package_manifest = read_json(package / "MANIFEST.json")
    manifest["package_manifest_sha256"] = digest((package / "MANIFEST.json").read_bytes())
    for stock in package_manifest["stocks"]:
        for representation in ("raw", "normalized"):
            info = stock[representation]
            filename = PureWindowsPath(info["path"]).name
            actual_hash = digest((package / filename).read_bytes())
            require(actual_hash == info["sha256"], "package hash mismatch: " + filename)
            manifest["input_files_sha256"][filename] = actual_hash
        code = stock["stock_code"]
        rows = read_json(package / PureWindowsPath(stock["normalized"]["path"]).name)
        require(len(rows) == 437, "unexpected stock row count")
        frame = pd.DataFrame(rows)
        frame.attrs["data_mode"] = "c_delivery_20260917_normalized"
        for label, parameters in SETS.items():
            result = run_backtest_request(frame, strategy="macd", parameters=parameters,
                start_date=manifest["window"][0], end_date=manifest["window"][1])
            replay(result)
            if label == "default":
                omitted = run_backtest_request(frame, strategy="macd", start_date=manifest["window"][0], end_date=manifest["window"][1])
                require(canonical(omitted) == canonical(result), "MACD omitted/empty mismatch")
            require(len(result["equity_curve"]) == len(result["benchmark_curve"]) == len(result["drawdown_curve"]) == 283, "curve count mismatch")
            require(result["order_count"] == len(result["trades"]), "order count mismatch")
            require(result["trade_count"] == sum(t["side"] == "sell" for t in result["trades"]), "round-trip count mismatch")
            name = code + "_" + label + ".json"
            write_json(output / name, result)
            manifest["result_files"].append(name)
            manifest["matrix"].append({"stock_code": code, "parameter_set": label,
                **{key: result[key] for key in ("order_count", "trade_count", "final_equity", "total_return", "data_hash")},
                "warmup_rows": result["warmup"]["used_rows"], "curve_points": 283, "full_replay_equal": True})
            if code == "600519" and label == "default":
                write_json(output / "macd_numeric_example.json", numeric_example(result))
        if code == "600519":
            ma = run_backtest_request(frame, parameters={}, start_date=manifest["window"][0], end_date=manifest["window"][1])
            replay(ma)
            write_json(output / "ma_default.json", ma)
            manifest["result_files"].append("ma_default.json")
            write_json(output / "ma_numeric_example.json", numeric_example(ma))
    manifest["files_sha256"] = {p.name: digest(p.read_bytes()) for p in sorted(output.glob("*.json")) if p.name != "manifest.json"}
    manifest["status"] = "passed"
    write_json(output / "manifest.json", manifest)
    verify(output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output-dir", type=Path)
    action.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    try:
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), \
             patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")):
            if args.verify:
                verify(args.verify)
            else:
                export(args.output_dir)
    except Exception as exc:
        print(type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
