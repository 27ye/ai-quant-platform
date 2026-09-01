"""Strict JSON-safe conversion for NumPy, Pandas, dates, and non-finite values."""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Dict

import numpy as np
import pandas as pd


def to_json_safe(value: Any) -> Any:
    """Recursively convert a quant result for json.dumps(..., allow_nan=False)."""

    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, pd.DataFrame):
        return [to_json_safe(record) for record in value.to_dict(orient="records")]
    if isinstance(value, pd.Series):
        return [to_json_safe(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {str(key): to_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, np.datetime64):
        if np.isnat(value):
            return None
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    if isinstance(value, np.generic):
        return to_json_safe(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (str, int, bool)):
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def dataframe_records(data: pd.DataFrame) -> Any:
    """Convert DataFrame records through the same strict scalar rules."""

    return to_json_safe(data.to_dict(orient="records"))
