from sqlalchemy import CHAR, UniqueConstraint

from backend.app import models  # noqa: F401
from backend.app.db.base import Base


def test_all_v1_tables_are_registered():
    assert set(Base.metadata.tables) == {
        "stock_basic",
        "stock_daily",
        "stock_indicator",
        "stock_news",
        "backtest_result",
        "ai_analysis",
    }


def test_stock_daily_unique_constraint_matches_design():
    constraints = Base.metadata.tables["stock_daily"].constraints
    unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("stock_code", "trade_date") in unique_columns


def test_ai_analysis_contains_v2_snapshot_columns_and_existing_indexes():
    table = Base.metadata.tables["ai_analysis"]
    assert {
        "context_snapshot", "context_hash", "source_mode", "data_as_of",
        "prompt_version", "context_schema_version", "output_schema_version",
    } <= set(table.columns.keys())
    assert {index.name for index in table.indexes} == {
        "idx_ai_stock",
        "idx_ai_created_at",
    }
    assert isinstance(table.columns["context_hash"].type, CHAR)
