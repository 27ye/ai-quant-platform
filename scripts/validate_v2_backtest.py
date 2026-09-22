"""Write reproducible offline C backtest evidence; never use providers or services.

The output directory must not already exist. By default the input is explicitly
synthetic. A normalized, single-stock JSON row array can instead be supplied with
--input-json. JSON replay proves only local serialization/recalculation equality;
it does not prove API, MySQL, live-market or LLM integration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.quant.backtest import run_backtest  # noqa: E402
from backend.app.quant.pipeline import analyze_quant_dataframe  # noqa: E402
from backend.app.quant.serialization import dataframe_records  # noqa: E402
from backend.app.quant.validators import validate_stock_dataframe  # noqa: E402
from backend.app.quant.windowed_backtest import run_backtest_request  # noqa: E402
from scripts.validate_quant_core import build_synthetic_daily_data  # noqa: E402


PARAMETER_FIELDS = (
    "ma_short_period", "ma_long_period", "initial_cash", "transaction_cost", "slippage"
)
SOURCE_PATHS = (
    "backend/app/quant", "scripts/validate_v2_backtest.py", "scripts/validate_quant_core.py"
)


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number is not allowed: " + value)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=_reject_constant)


def _assert_exact(actual: Any, expected: Any, path: str = "$") -> None:
    """Compare every JSON value, including its type, without tolerances/rounding."""

    if type(actual) is not type(expected):
        raise AssertionError("JSON type mismatch at " + path)
    if isinstance(actual, dict):
        if actual.keys() != expected.keys():
            raise AssertionError("JSON object keys differ at " + path)
        for key in actual:
            _assert_exact(actual[key], expected[key], path + "." + key)
    elif isinstance(actual, list):
        if len(actual) != len(expected):
            raise AssertionError("JSON array length differs at " + path)
        for index, (left, right) in enumerate(zip(actual, expected)):
            _assert_exact(left, right, "%s[%d]" % (path, index))
    elif actual != expected:
        raise AssertionError("JSON value differs at " + path)


def _git(*arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(PROJECT_ROOT), *arguments],
        text=True, encoding="utf-8", stderr=subprocess.PIPE,
    ).strip()


def _source_provenance() -> Dict[str, Any]:
    paths = _git("ls-files", "--cached", "--others", "--exclude-standard", "--", *SOURCE_PATHS)
    sources = {}
    for relative in sorted(set(paths.splitlines())):
        if relative.endswith(".py"):
            sources[relative] = _sha256((PROJECT_ROOT / relative).read_bytes())
    diff = _git("diff", "--no-ext-diff", "--binary", "HEAD", "--", *SOURCE_PATHS)
    return {
        "git_head": _git("rev-parse", "HEAD"),
        "git_status": _git("status", "--short", "--untracked-files=all"),
        "source_fingerprint_scope": list(SOURCE_PATHS),
        "source_files_sha256": sources,
        "source_fingerprint_sha256": _sha256(_json_bytes(sources)),
        "tracked_source_diff": diff,
        "tracked_source_diff_sha256": _sha256(diff.encode("utf-8")),
    }


def _save_json(directory: Path, name: str, value: Any, manifest: Dict[str, Any]) -> Any:
    content = _json_bytes(value)
    path = directory / name
    with path.open("xb") as stream:
        stream.write(content)
    manifest["files"][name] = {"sha256": _sha256(content), "bytes": len(content)}
    restored = _load_json(path)
    _assert_exact(restored, value)
    return restored


def _frame_from_snapshot(snapshot: Dict[str, Any]) -> pd.DataFrame:
    """Rebuild only from saved rows; do not fetch missing data or recompute history."""

    data = pd.DataFrame(snapshot["rows"], columns=snapshot["columns"])
    data.attrs["data_mode"] = snapshot["data_mode"]
    return data


def replay_backtest_result(saved: Dict[str, Any]) -> Dict[str, Any]:
    data = _frame_from_snapshot(saved["input_snapshot"])
    arguments = {
        "start_date": saved["requested_start_date"],
        "end_date": saved["requested_end_date"],
    }
    if saved["semantics_version"] == "v2_windowed":
        arguments["parameters"] = {
            field: saved["effective_parameters"][field] for field in PARAMETER_FIELDS
        }
    elif saved["semantics_version"] != "v1_legacy":
        raise ValueError("unknown saved semantics_version")
    replayed = run_backtest_request(data, **arguments)
    _assert_exact(replayed, saved)
    return replayed


def _save_backtest(
    directory: Path, name: str, result: Dict[str, Any], manifest: Dict[str, Any]
) -> None:
    restored = _save_json(directory, name, result, manifest)
    replay_backtest_result(restored)
    manifest["checks"].append({"name": name + ": full JSON snapshot replay", "status": "passed"})
    manifest["files"][name].update({
        "semantics_version": result["semantics_version"],
        "algorithm_version": result["algorithm_version"],
        "effective_parameters": result["effective_parameters"],
        "requested_start_date": result["requested_start_date"],
        "requested_end_date": result["requested_end_date"],
        "input_snapshot_sha256": result["input_snapshot"]["sha256"],
        "warmup": result["warmup"],
        "order_count": result["order_count"],
        "round_trip_count": result["trade_count"],
        "equity_curve_points": len(result["equity_curve"]),
        "total_return": result["total_return"],
        "final_equity": result["final_equity"],
        "full_json_replay_equal": True,
    })


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--input-json", type=Path, help="normalized JSON row array; no network fallback")
    parser.add_argument("--data-mode", default="input_json", help="input JSON provenance label (default: input_json)")
    parser.add_argument("--source-note", help="optional human-supplied provenance note; not an external-source verification")
    parser.add_argument("--expected-v1-json", type=Path, help="complete analyze_quant_dataframe baseline; exact comparison")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    output = args.output_dir.resolve()
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        print("C offline validation failed: output directory must be new (%s)" % type(exc).__name__, file=sys.stderr)
        return 1

    manifest = {
        "schema_version": "c_v2_offline_evidence_v1",
        "status": "failed",
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "evidence_scope": "offline_quant_only",
        "replay_scope": "local JSON readback and quant recalculation; not MySQL/API readback",
        "data_mode_scope": "preserved computation metadata; it does not imply live retrieval",
        "source_note": args.source_note,
        "not_verified": ["API integration", "MySQL persistence/readback", "live market data", "LLM integration"],
        "environment": {"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__},
        "files": {},
        "checks": [],
    }
    try:
        provenance = _source_provenance()
        diff = provenance.pop("tracked_source_diff")
        manifest["source"] = provenance
        diff_bytes = diff.encode("utf-8")
        with (output / "source-diff.patch").open("xb") as stream:
            stream.write(diff_bytes)
        manifest["files"]["source-diff.patch"] = {"sha256": _sha256(diff_bytes), "bytes": len(diff_bytes)}

        if args.input_json is None:
            data = build_synthetic_daily_data("600519", date(2024, 1, 1), date(2026, 8, 31))
            manifest["source_mode"] = "synthetic"
        else:
            input_bytes = args.input_json.read_bytes()
            rows = json.loads(input_bytes.decode("utf-8-sig"), parse_constant=_reject_constant)
            if not isinstance(rows, list) or not rows or not all(isinstance(row, dict) for row in rows):
                raise ValueError("--input-json must contain a non-empty array of normalized daily row objects")
            data = pd.DataFrame(rows)
            data.attrs["data_mode"] = args.data_mode
            manifest["source_mode"] = "input_json"
            manifest["input_file"] = {
                "path": str(args.input_json.resolve()), "sha256": _sha256(input_bytes)
            }
        data = validate_stock_dataframe(data)
        if len(data) < 122:
            raise ValueError("offline examples require at least 122 valid rows: 120 warmup rows and 2 window rows; received %d" % len(data))
        manifest.update({"data_mode": data.attrs["data_mode"], "input_rows": len(data)})
        stored_rows = _save_json(output, "input.json", dataframe_records(data), manifest)
        replay_data = pd.DataFrame(stored_rows)
        replay_data.attrs["data_mode"] = data.attrs["data_mode"]

        quant = analyze_quant_dataframe(data)
        restored_quant = _save_json(output, "v1-quant.json", quant, manifest)
        _assert_exact(analyze_quant_dataframe(replay_data), restored_quant)
        manifest["checks"].append({"name": "complete V1 quant JSON replay", "status": "passed"})
        manifest["files"]["v1-quant.json"].update({
            "score": quant["score"]["score"],
            "effective_parameters": quant["meta"]["parameters"],
            "order_count": quant["backtest"]["order_count"],
            "round_trip_count": quant["backtest"]["trade_count"],
            "equity_curve_points": len(quant["backtest"]["equity_curve"]),
            "total_return": quant["backtest"]["total_return"],
            "final_equity": quant["backtest"]["final_equity"],
            "full_json_replay_equal": True,
        })
        if args.expected_v1_json is not None:
            baseline_bytes = args.expected_v1_json.read_bytes()
            _assert_exact(quant, json.loads(baseline_bytes.decode("utf-8-sig"), parse_constant=_reject_constant))
            manifest["checks"].append({"name": "complete external V1 baseline", "status": "passed"})
            manifest["expected_v1_baseline"] = {
                "path": str(args.expected_v1_json.resolve()),
                "sha256": _sha256(baseline_bytes), "full_json_equal": True,
            }
        else:
            manifest["checks"].append({"name": "external V1 baseline", "status": "not_provided"})

        legacy = run_backtest_request(data)
        original_backtest = run_backtest(data)
        _assert_exact({key: legacy[key] for key in original_backtest}, original_backtest)
        _assert_exact(original_backtest, quant["backtest"])
        manifest["checks"].append({"name": "all legacy run_backtest fields preserved", "status": "passed"})
        _save_backtest(output, "v1-legacy.json", legacy, manifest)

        start = data.iloc[120]["trade_date"].strftime("%Y-%m-%d")
        end = data.iloc[-1]["trade_date"].strftime("%Y-%m-%d")
        manifest["shared_v2_window"] = {"start_date": start, "end_date": end, "available_prior_rows": 120}
        examples = (
            ("v2-default.json", {}),
            ("v2-ma10-30.json", {"ma_short_period": 10, "ma_long_period": 30}),
            ("v2-ma20-60-cost.json", {
                "ma_short_period": 20, "ma_long_period": 60, "initial_cash": 200000,
                "transaction_cost": 0.002, "slippage": 0.001,
            }),
        )
        for name, parameters in examples:
            result = run_backtest_request(data, start_date=start, end_date=end, parameters=parameters)
            _save_backtest(output, name, result, manifest)
            manifest["files"][name]["requested_parameters"] = parameters

        boundary_parameters = {"ma_short_period": 20, "ma_long_period": 120}
        boundary = run_backtest_request(data, start_date=start, end_date=start, parameters=boundary_parameters)
        _save_backtest(output, "v2-long120-one-day.json", boundary, manifest)
        manifest["files"]["v2-long120-one-day.json"]["requested_parameters"] = boundary_parameters

        final_provenance = _source_provenance()
        for field in ("git_head", "source_fingerprint_sha256", "tracked_source_diff_sha256"):
            _assert_exact(final_provenance[field], provenance[field], "$.source." + field)
        manifest["checks"].append({"name": "quant sources unchanged during validation", "status": "passed"})
        manifest["status"] = "passed"
    except Exception as exc:
        manifest["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        print("C offline validation failed (%s): %s" % (type(exc).__name__, exc), file=sys.stderr)
    finally:
        manifest["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        content = _json_bytes(manifest)
        with (output / "manifest.json").open("xb") as stream:
            stream.write(content)
        with (output / "manifest.sha256").open("x", encoding="ascii") as stream:
            stream.write(_sha256(content) + "  manifest.json\n")
    if manifest["status"] != "passed":
        return 1
    print(json.dumps({
        "status": "passed", "evidence_scope": manifest["evidence_scope"],
        "source_mode": manifest["source_mode"], "input_rows": manifest["input_rows"],
        "manifest": str(output / "manifest.json"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
