"""Assemble the V1 frozen acceptance package (metadata + manifest).

The output ``metadata.json`` is compatible with D's
``scripts/frozen_acceptance.py::load_package`` contract:

* required top-level ``stock_code / actual_start_date / actual_end_date /
  captured_at / rows / kline / calendar / stock / readback / quant_config /
  quant_expectations``;
* ``captured_at`` is the *original* fetch time (timezone-aware), never the
  packaging time;
* ``stock`` (not ``stock_basic``) carries file + sha256 + real capture provenance;
* ``quant_expectations`` is exactly the five agreed keys;
* the original kline/calendar SHA-256 values are verified against the source
  metadata and preserved (provenance is not recomputed-and-replaced).

No network is used. Paths are under ``frozen/`` (git-ignored).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FROZEN = ROOT / "frozen"

#: Exact five-key expectations required by D's load_package.
QUANT_EXPECTATIONS = {
    "score": 33,
    "order_count": 24,
    "equity_curve_points": 403,
    "total_return": -0.09165774117956027,
    "final_equity": 90834.22588204397,
}

REQUIRED_TOP_LEVEL = (
    "stock_code",
    "actual_start_date",
    "actual_end_date",
    "captured_at",
    "rows",
    "kline",
    "calendar",
    "stock",
    "readback",
    "quant_config",
    "quant_expectations",
)

STOCK_SNAPSHOT_FILE = "stock_basic_600519.json"
STOCK_PROVENANCE_FILE = "stock_basic_600519.provenance.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def resolve_source_metadata(frozen_dir: Path, explicit: str = None) -> Path:
    """Locate the C-provided source metadata (explicit path wins)."""
    if explicit:
        return Path(explicit)
    default = Path(frozen_dir) / "metadata(1).json"
    if default.exists():
        return default
    candidates = sorted(
        p
        for p in Path(frozen_dir).glob("metadata*.json")
        if p.is_file() and p.name != "metadata.json"
    )
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise SystemExit("[build] multiple source metadata files; use --source-metadata")
    raise FileNotFoundError(f"no source metadata found in {frozen_dir}")


def assert_source_hashes(source_meta: dict, frozen_dir: Path) -> None:
    """Verify the declared original SHA-256 of kline/calendar before packaging."""
    for key in ("kline", "calendar"):
        spec = source_meta[key]
        path = Path(frozen_dir) / spec["file"]
        actual = sha256(path)
        if actual.lower() != str(spec["sha256"]).lower():
            raise SystemExit(
                f"[build] {key} sha256 mismatch: {actual} != {spec['sha256']}"
            )


def stock_snapshot_from_raw(raw: dict) -> dict:
    data = raw["data"]
    return {
        "stock_code": str(data["f57"]),
        "stock_name": data["f58"],
        "industry": data.get("f127"),
        "total_market_cap": data.get("f116"),
        "float_market_cap": data.get("f117"),
    }


def build_metadata(
    source_meta: dict,
    *,
    stock_entry: dict,
    readback_entry: dict,
    quant_config: dict,
) -> dict:
    """Pure builder for the D-compatible metadata dict."""
    kline = dict(source_meta["kline"])
    calendar = dict(source_meta["calendar"])
    return {
        "stock_code": str(kline["stock_code"]),
        "actual_start_date": kline["actual_start_date"],
        "actual_end_date": kline["actual_end_date"],
        "captured_at": kline["fetch_finished_at_utc"],
        "rows": int(kline["rows"]),
        "adjust": kline.get("adjust", "qfq"),
        "frequency": kline.get("period", "daily"),
        "precision": {
            "price_ndigits": 4,
            "amount_ndigits": 2,
            "percent_ndigits": 6,
            "volume": "integer",
        },
        "kline": kline,
        "calendar": calendar,
        "stock": stock_entry,
        "readback": readback_entry,
        "quant_config": quant_config,
        "quant_expectations": dict(QUANT_EXPECTATIONS),
        "news": None,
        "news_status": "absent (no real news snapshot in this package)",
    }


def main() -> int:
    from backend.app.quant.config import QuantConfig

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen-dir", default=str(FROZEN))
    parser.add_argument("--source-metadata", default=None)
    parser.add_argument("--output-metadata", default=None)
    args = parser.parse_args()

    frozen = Path(args.frozen_dir)
    source_path = resolve_source_metadata(frozen, args.source_metadata)
    source_meta = json.loads(source_path.read_text(encoding="utf-8"))

    # Verify the original declared hashes BEFORE packaging (keep their values).
    assert_source_hashes(source_meta, frozen)

    provenance = json.loads((frozen / STOCK_PROVENANCE_FILE).read_text(encoding="utf-8"))
    raw = json.loads((frozen / provenance["raw_file"]).read_text(encoding="utf-8"))
    snapshot = stock_snapshot_from_raw(raw)
    stock_path = frozen / STOCK_SNAPSHOT_FILE
    stock_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")

    stock_entry = {
        "file": stock_path.name,
        "sha256": sha256(stock_path),
        "source": provenance["endpoint"],
        "wrapped_by": provenance["wrapped_by"],
        "captured_at": provenance["captured_at"],
        "raw_file": provenance["raw_file"],
        "note": provenance["note"],
    }

    readback_path = frozen / "mysql_readback_600519.json"
    readback_entry = {
        "file": readback_path.name,
        "sha256": sha256(readback_path),
        "rows": int(source_meta["kline"]["rows"]),
        "mysql_version": "8.0.44",
        "target_db": "ai_quant_test",
    }

    metadata = build_metadata(
        source_meta,
        stock_entry=stock_entry,
        readback_entry=readback_entry,
        quant_config=QuantConfig().to_parameters(),
    )
    output_path = Path(args.output_metadata) if args.output_metadata else frozen / "metadata.json"
    output_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    package_files = [
        source_meta["kline"]["file"],
        source_meta["calendar"]["file"],
        STOCK_SNAPSHOT_FILE,
        provenance["raw_file"],
        readback_path.name,
        output_path.name,
    ]
    manifest = {
        "files": {name: sha256(frozen / name) for name in package_files},
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (frozen / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
