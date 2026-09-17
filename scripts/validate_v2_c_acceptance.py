"""Run the fixed-window, three-stock C acceptance matrix entirely offline.

Supply --expected-hashes from an independently confirmed filename-to-SHA256 JSON
mapping. The delivery's own MANIFEST.json is never used as a trust anchor. This
tool checks file integrity, daily-row validity, and local JSON replay, not the
truth of a claimed market-data source or HTTP/MySQL/live integration.

Example (all paths are local):
    python scripts/validate_v2_c_acceptance.py --delivery-dir DELIVERY \
        --expected-hashes CONFIRMED_HASHES.json --output-dir NEW_EVIDENCE
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.quant.validators import (  # noqa: E402
    OPTIONAL_NUMERIC_COLUMNS,
    REQUIRED_COLUMNS,
    REQUIRED_NUMERIC_COLUMNS,
    validate_stock_dataframe,
)
from backend.app.quant.windowed_backtest import (  # noqa: E402
    run_backtest_request,
    validate_backtest_window,
)
from scripts.validate_v2_backtest import replay_backtest_result  # noqa: E402


STOCK_CODES = ("600519", "000001", "300750")
FILENAME_TEMPLATE = "{code}_qfq_normalized_20241201_20260915.json"
DELIVERY_WARMUP_ROWS = 120
MATRIX_CASES = (
    ("default", {}),
    ("ma10-30", {"ma_short_period": 10, "ma_long_period": 30}),
    ("ma20-60-cost", {
        "ma_short_period": 20,
        "ma_long_period": 60,
        "initial_cash": 200000,
        "transaction_cost": 0.002,
        "slippage": 0.001,
    }),
)
SOURCE_PATHS = (
    "backend/app/quant",
    "scripts/validate_v2_c_acceptance.py",
    "scripts/validate_v2_backtest.py",
    "scripts/validate_quant_core.py",
    "tests/quant/test_c_acceptance_matrix.py",
)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number is not allowed: " + value)


def _unique_object(pairs: Any) -> Dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key: " + key)
        result[key] = value
    return result


def _decode_json(content: bytes) -> Any:
    return json.loads(
        content.decode("utf-8-sig"), parse_constant=_reject_constant,
        object_pairs_hook=_unique_object,
    )


def _git(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(PROJECT_ROOT), *arguments],
        text=True, encoding="utf-8", stderr=subprocess.PIPE,
    ).strip()


def _source_provenance() -> Dict[str, Any]:
    listed = _git("ls-files", "--cached", "--others", "--exclude-standard", "--", *SOURCE_PATHS)
    sources = {
        relative: _sha256((PROJECT_ROOT / relative).read_bytes())
        for relative in sorted(set(listed.splitlines())) if relative.endswith(".py")
    }
    if "scripts/validate_v2_c_acceptance.py" not in sources:
        raise ValueError("acceptance script is missing from the source provenance scope")
    scope_status = _git("status", "--porcelain=v1", "--untracked-files=all", "--", *SOURCE_PATHS)
    worktree_status = _git("status", "--porcelain=v1", "--untracked-files=all")
    return {
        "git_base_head": _git("rev-parse", "HEAD"),
        "git_worktree_dirty": bool(worktree_status),
        "git_worktree_status": worktree_status,
        "affected_source_dirty": bool(scope_status),
        "affected_source_status": scope_status,
        "source_fingerprint_scope": list(SOURCE_PATHS),
        "source_files_sha256": sources,
        "source_fingerprint_sha256": _sha256(_json_bytes(sources)),
        "interpretation": "git_base_head alone does not identify uncommitted source; use hashes and dirty state",
    }


def _load_expected_hashes(path: Path, filename_template: str = FILENAME_TEMPLATE) -> Tuple[Dict[str, str], bytes]:
    content = path.read_bytes()
    hashes = _decode_json(content)
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("--expected-hashes must be a non-empty filename-to-SHA256 JSON object")
    for name, digest in hashes.items():
        if not name or "/" in name or "\\" in name:
            raise ValueError("expected hash keys must be plain filenames")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            raise ValueError("expected SHA256 must have 64 hexadecimal characters: " + name)
    required = [filename_template.format(code=code) for code in STOCK_CODES]
    missing = [name for name in required if name not in hashes]
    if missing:
        raise ValueError("expected hashes missing required normalized files: " + ", ".join(missing))
    return {name: digest.lower() for name, digest in hashes.items()}, content


def _strict_rows(rows: Any, code: str) -> None:
    if not isinstance(rows, list) or not rows:
        raise ValueError(code + ": expected a non-empty JSON array of normalized daily rows")
    previous = None
    for index, row in enumerate(rows):
        prefix = "%s row %d: " % (code, index + 1)
        if not isinstance(row, dict):
            raise ValueError(prefix + "daily row must be an object")
        if any(column not in row for column in REQUIRED_COLUMNS):
            raise ValueError(prefix + "missing required daily columns")
        if type(row["stock_code"]) is not str or row["stock_code"] != code:
            raise ValueError(prefix + "stock_code must be exactly the expected six-digit string")
        raw_date = row["trade_date"]
        if not isinstance(raw_date, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw_date):
            raise ValueError(prefix + "trade_date must be YYYY-MM-DD")
        try:
            current = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise ValueError(prefix + "trade_date is not a valid calendar date") from exc
        if previous is not None and current <= previous:
            raise ValueError(prefix + "trade_date must be strictly increasing and unique")
        previous = current
        for column in REQUIRED_NUMERIC_COLUMNS + OPTIONAL_NUMERIC_COLUMNS:
            if column not in row or (column in OPTIONAL_NUMERIC_COLUMNS and row[column] is None):
                continue
            value = row[column]
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(prefix + column + " must be a finite JSON number (not bool/string)")


def _load_delivery(
    directory: Path, hashes: Dict[str, str], start: date, end: date, data_mode: str,
    filename_template: str = FILENAME_TEMPLATE,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, Any], Dict[str, bytes]]:
    frames = {}
    metadata = {}
    originals = {}
    # Validate all three files before doing any backtest. Never fetch or fill gaps.
    for code in STOCK_CODES:
        filename = filename_template.format(code=code)
        source_path = directory / filename
        if not source_path.is_file():
            raise ValueError("missing required normalized file: " + filename)
        content = source_path.read_bytes()
        digest = _sha256(content)
        if digest != hashes[filename]:
            raise ValueError("SHA256 mismatch: " + filename)
        rows = _decode_json(content)
        _strict_rows(rows, code)
        data = pd.DataFrame(rows)
        data.attrs["data_mode"] = data_mode
        data = validate_stock_dataframe(data)
        dates = data["trade_date"].dt.date
        prior_count = int((dates < start).sum())
        window_dates = data.loc[(dates >= start) & (dates <= end), "trade_date"]
        if prior_count < DELIVERY_WARMUP_ROWS:
            raise ValueError(
                "%s: delivery requires at least 120 valid rows before start_date; received %d"
                % (code, prior_count)
            )
        if window_dates.empty:
            raise ValueError(code + ": no valid daily rows inside the fixed requested window")
        frames[code] = data
        originals[filename] = content
        metadata[code] = {
            "source_path": str(source_path.resolve()),
            "source_filename": filename,
            "source_file_sha256": digest,
            "expected_file_sha256": hashes[filename],
            "source_bytes": len(content),
            "input_rows": len(data),
            "input_start_date": data.iloc[0]["trade_date"].strftime("%Y-%m-%d"),
            "input_end_date": data.iloc[-1]["trade_date"].strftime("%Y-%m-%d"),
            "available_prior_rows": prior_count,
            "delivery_required_prior_rows": DELIVERY_WARMUP_ROWS,
            "window_rows": len(window_dates),
            "actual_window_start_date": window_dates.iloc[0].strftime("%Y-%m-%d"),
            "actual_window_end_date": window_dates.iloc[-1].strftime("%Y-%m-%d"),
            "window_trade_dates": window_dates.dt.strftime("%Y-%m-%d").tolist(),
            "data_mode": data_mode,
        }
    return frames, metadata, originals


def _save_bytes(output: Path, name: str, content: bytes, report: Dict[str, Any]) -> None:
    with (output / name).open("xb") as stream:
        stream.write(content)
    if (output / name).read_bytes() != content:
        raise AssertionError("saved file byte readback differs: " + name)
    report["files"][name] = {"sha256": _sha256(content), "bytes": len(content)}


def _save_json(output: Path, name: str, value: Any, report: Dict[str, Any]) -> Any:
    _save_bytes(output, name, _json_bytes(value), report)
    return _decode_json((output / name).read_bytes())


def _assert_window_result(result: Dict[str, Any], source: Dict[str, Any]) -> None:
    expected_dates = source["window_trade_dates"]
    for key in ("equity_curve", "benchmark_curve", "drawdown_curve"):
        if [point["trade_date"] for point in result[key]] != expected_dates:
            raise AssertionError(key + " must contain exactly the requested window's observed dates")
    if result["order_count"] != len(result["trades"]):
        raise AssertionError("order_count does not match trades")
    if result["trade_count"] != sum(order["side"] == "sell" for order in result["trades"]):
        raise AssertionError("trade_count does not match completed long-only round trips")
    if any(order["execution_date"] not in expected_dates for order in result["trades"]):
        raise AssertionError("an order execution lies outside the observed window")
    required = result["effective_parameters"]["ma_long_period"]
    if result["warmup"]["required_rows"] != required or result["warmup"]["used_rows"] != required:
        raise AssertionError("per-case warmup must match its long MA, not the 120-row delivery minimum")
    if len(result["input_snapshot"]["rows"]) != required + len(expected_dates):
        raise AssertionError("input snapshot must contain only selected warmup and window rows")
    if result["data_hash"] != result["input_snapshot"]["sha256"]:
        raise AssertionError("C data_hash must identify the saved C input snapshot")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True, help="new directory; existing paths are never overwritten")
    parser.add_argument("--expected-hashes", type=Path, required=True, help="independently confirmed filename-to-SHA256 JSON mapping")
    parser.add_argument("--start-date", default="2025-07-04")
    parser.add_argument("--end-date", default="2026-08-31")
    parser.add_argument("--data-mode", default="input_json", help="C input metadata only, not verified provider provenance; use synthetic_fixture for synthetic tests")
    parser.add_argument("--filename-template", default=FILENAME_TEMPLATE,
                        help="explicit normalized batch filename, e.g. {code}_qfq_normalized_20241201_20260916.json; no auto-selection")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    output = args.output_dir.resolve()
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        print("C matrix failed: output directory must be new (%s)" % type(exc).__name__, file=sys.stderr)
        return 1
    report = {
        "schema_version": "c_v2_fixed_window_matrix_v1",
        "status": "failed",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "evidence_scope": "offline_quant_fixed_window_matrix_only",
        "data_mode": args.data_mode,
        "filename_template": args.filename_template,
        "data_mode_scope": "caller-supplied C input metadata; not proof of provider identity or real/live data",
        "hash_trust_scope": "explicit caller-supplied expected hashes; trust in their independent origin must be established outside this tool",
        "replay_scope": "saved JSON readback and exact full-result recalculation from its C snapshot",
        "not_verified": [
            "HTTP/API integration", "MySQL persistence/readback", "live market retrieval",
            "provider provenance or trading-calendar completeness", "AI/LLM integration",
        ],
        "environment": {"python": platform.python_version(), "pandas": pd.__version__},
        "requested_window": {"start_date": args.start_date, "end_date": args.end_date},
        "files": {},
        "matrix": [],
    }
    try:
        start, end = validate_backtest_window(args.start_date, args.end_date)
        if not args.data_mode.strip():
            raise ValueError("--data-mode must not be empty")
        if not re.fullmatch(r"\{code\}_qfq_normalized_[0-9]{8}_[0-9]{8}\.json", args.filename_template):
            raise ValueError("--filename-template must be a plain normalized filename with exactly one {code} placeholder and two YYYYMMDD dates")
        source = _source_provenance()
        report["source"] = source
        hashes, hash_bytes = _load_expected_hashes(args.expected_hashes, args.filename_template)
        report["expected_hashes"] = {
            "path": str(args.expected_hashes.resolve()),
            "file_sha256": _sha256(hash_bytes),
            "mapping": hashes,
        }
        frames, inputs, originals = _load_delivery(
            args.delivery_dir.resolve(), hashes, start, end, args.data_mode, args.filename_template,
        )
        report["inputs"] = inputs
        _save_bytes(output, "expected-hashes.json", hash_bytes, report)
        for name, content in originals.items():
            _save_bytes(output, name, content, report)
        for code in STOCK_CODES:
            for case_name, parameters in MATRIX_CASES:
                request = {
                    "stock_code": code, "start_date": start.isoformat(),
                    "end_date": end.isoformat(), "parameters": dict(parameters),
                }
                result = run_backtest_request(
                    frames[code], start_date=start, end_date=end, parameters=dict(parameters),
                )
                _assert_window_result(result, inputs[code])
                stem = code + "-" + case_name
                request_name, result_name = stem + ".request.json", stem + ".result.json"
                _save_json(output, request_name, request, report)
                restored = _save_json(output, result_name, result, report)
                replay_backtest_result(restored)
                report["matrix"].append({
                    "case": case_name, "stock_code": code,
                    "request": request, "request_file": request_name, "result_file": result_name,
                    "source_file_sha256": inputs[code]["source_file_sha256"],
                    "c_data_hash": result["data_hash"],
                    "semantics_version": result["semantics_version"],
                    "algorithm_version": result["algorithm_version"],
                    "effective_parameters": result["effective_parameters"],
                    "actual_start_date": result["start_date"], "actual_end_date": result["end_date"],
                    "warmup": result["warmup"], "order_count": result["order_count"],
                    "round_trip_count": result["trade_count"],
                    "curve_points": {key: len(result[key]) for key in ("equity_curve", "benchmark_curve", "drawdown_curve")},
                    "total_return": result["total_return"], "final_equity": result["final_equity"],
                    "full_saved_json_replay_equal": True,
                })
        final_source = _source_provenance()
        for field in ("git_base_head", "source_fingerprint_sha256", "affected_source_status"):
            if source[field] != final_source[field]:
                raise AssertionError("quant source changed during validation: " + field)
        report["source_unchanged_during_run"] = True
        report["completed_cases"] = len(report["matrix"])
        if report["completed_cases"] != 9:
            raise AssertionError("matrix must contain exactly three stocks by three configurations")
        report["status"] = "passed"
    except Exception as exc:
        report["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        print("C matrix failed (%s): %s" % (type(exc).__name__, exc), file=sys.stderr)
    finally:
        report["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        content = _json_bytes(report)
        with (output / "report.json").open("xb") as stream:
            stream.write(content)
        with (output / "report.sha256").open("x", encoding="ascii") as stream:
            stream.write(_sha256(content) + "  report.json\n")
    if report["status"] != "passed":
        return 1
    print(json.dumps({"status": "passed", "completed_cases": 9, "evidence_scope": report["evidence_scope"], "report": str(output / "report.json")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
