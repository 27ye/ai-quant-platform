from datetime import date, datetime
from typing import Any, Dict, Iterable, List

import math

import pandas as pd

from backend.app.data.providers.base import (
    EmptyStockDataError,
    InvalidStockCodeError,
    StockDataProvider,
    StockDataProviderError,
    StockDataSchemaError,
)


class AKShareStockProvider(StockDataProvider):
    field_mapping: Dict[str, str] = {
        "日期": "trade_date",
        "股票代码": "stock_code",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
        "换手率": "turnover_rate",
        "涨跌幅": "change_pct",
    }
    required_source_fields = ("日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额")
    output_columns = (
        "stock_code",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "turnover_rate",
        "change_pct",
    )
    news_field_mapping = {
        "新闻标题": "title",
        "新闻内容": "summary",
        "发布时间": "publish_time",
        "文章来源": "source",
        "新闻链接": "url",
    }
    required_news_source_fields = ("新闻标题", "新闻内容", "文章来源", "新闻链接")
    news_output_columns = ("stock_code", "title", "summary", "source", "publish_time", "url")

    def get_daily_kline(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        stock_code = self._normalize_stock_code(stock_code)
        self._validate_dates(start_date, end_date)
        if adjust != "qfq":
            raise ValueError("V1 daily kline only supports qfq adjust")

        try:
            import akshare as ak

            raw_data = ak.stock_zh_a_hist(
                symbol=stock_code,
                period="daily",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                adjust=adjust,
            )
        except StockDataProviderError:
            raise
        except Exception as exc:
            raise StockDataProviderError(f"AKShare request failed for {stock_code}: {exc}") from exc

        return self._normalize_daily_kline(raw_data, stock_code)

    def search_stocks(self, keyword: str) -> List[Dict[str, str]]:
        """Search A-share stocks by code or name substring (via AKShare spot)."""
        keyword = keyword.strip()
        if not keyword:
            raise StockDataProviderError("search keyword must not be empty")
        try:
            import akshare as ak

            raw = ak.stock_zh_a_spot_em()
        except StockDataProviderError:
            raise
        except Exception as exc:
            raise StockDataProviderError(f"AKShare spot request failed: {exc}") from exc

        code_col = self._pick_column(raw, ("代码", "code", "股票代码"))
        name_col = self._pick_column(raw, ("名称", "name", "股票简称"))
        if code_col is None or name_col is None:
            raise StockDataSchemaError("AKShare spot response missing code/name columns")

        mask = raw[code_col].astype(str).str.contains(
            keyword, case=False, na=False, regex=False
        ) | raw[name_col].astype(str).str.contains(
            keyword, case=False, na=False, regex=False
        )
        subset = raw.loc[mask, [code_col, name_col]].head(50)

        result: List[Dict[str, str]] = []
        for _, row in subset.iterrows():
            code = str(row[code_col]).strip().zfill(6)
            if len(code) != 6 or not code.isdigit():
                continue
            result.append({"stock_code": code, "stock_name": str(row[name_col]).strip()})
        return result

    def get_stock_info(self, stock_code: str) -> Dict[str, Any]:
        """Return basic stock info (name, industry, market caps) via AKShare."""
        stock_code = self._normalize_stock_code(stock_code)
        try:
            import akshare as ak

            raw = ak.stock_individual_info_em(symbol=stock_code)
        except StockDataProviderError:
            raise
        except Exception as exc:
            raise StockDataProviderError(
                f"AKShare info request failed for {stock_code}: {exc}"
            ) from exc

        if raw is None or raw.empty:
            raise EmptyStockDataError(f"AKShare returned no info for {stock_code}")
        item_col = self._pick_column(raw, ("item", "项目"))
        value_col = self._pick_column(raw, ("value", "值"))
        if item_col is None or value_col is None:
            raise StockDataSchemaError("AKShare info response missing item/value columns")

        kv: Dict[str, Any] = {}
        for _, row in raw.iterrows():
            kv[str(row[item_col]).strip()] = row[value_col]

        return {
            "stock_code": stock_code,
            "stock_name": self._cell_text(kv.get("股票简称")) or stock_code,
            "industry": self._cell_text(kv.get("行业")),
            "total_market_cap": self._cell_float(kv.get("总市值")),
            "float_market_cap": self._cell_float(kv.get("流通市值")),
        }

    def get_stock_news(self, stock_code: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch recent East Money news for a stock and return normalized dicts.

        Returns a list of ``snake_case`` dicts with keys ``stock_code``, ``title``,
        ``summary``, ``source``, ``publish_time`` (``datetime`` or ``None``) and ``url``.
        """
        stock_code = self._normalize_stock_code(stock_code)
        try:
            import akshare as ak

            raw = ak.stock_news_em(symbol=stock_code)
        except StockDataProviderError:
            raise
        except Exception as exc:
            raise StockDataProviderError(
                f"AKShare news request failed for {stock_code}: {exc}"
            ) from exc

        if raw is None or raw.empty:
            return []

        missing_fields = [
            field
            for field in self.required_news_source_fields
            if field not in raw.columns
        ]
        if missing_fields:
            raise StockDataSchemaError(
                f"AKShare news response missing fields: {missing_fields}"
            )

        data = raw.rename(columns=self.news_field_mapping).copy()
        data["stock_code"] = stock_code
        if "publish_time" in data.columns:
            data["publish_time"] = pd.to_datetime(data["publish_time"], errors="coerce")
        data = data.where(pd.notnull(data), None)

        items: List[Dict[str, Any]] = []
        for _, row in data.iterrows():
            title = self._cell_text(row.get("title"))
            if not title:
                continue
            items.append(
                {
                    "stock_code": stock_code,
                    "title": title,
                    "summary": self._cell_text(row.get("summary")),
                    "source": self._cell_text(row.get("source")),
                    "publish_time": self._cell_datetime(row.get("publish_time")),
                    "url": self._cell_text(row.get("url")),
                }
            )
        # Sort ALL valid news newest-first (NULL last) BEFORE applying ``limit``,
        # so the newest item is never dropped by the source's non-time-sorted
        # order (e.g. the newest item appearing at the tail of the raw frame).
        return self._sort_news(items)[:limit]

    @staticmethod
    def _sort_news(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Return items sorted by ``publish_time`` descending, ``None`` last."""
        return sorted(
            items,
            key=lambda item: item.get("publish_time") or datetime.min,
            reverse=True,
        )

    @staticmethod
    def _pick_column(frame: pd.DataFrame, candidates: tuple) -> Any:
        for candidate in candidates:
            if candidate in frame.columns:
                return candidate
        return None

    @staticmethod
    def _cell_text(value: Any) -> Any:
        if value is None or pd.isna(value):
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _cell_float(value: Any) -> Any:
        if value is None or pd.isna(value):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _cell_datetime(value: Any) -> Any:
        if value is None or pd.isna(value):
            return None
        if isinstance(value, pd.Timestamp):
            return value.to_pydatetime()
        try:
            parsed = pd.to_datetime(value)
        except (TypeError, ValueError):
            return None
        return parsed.to_pydatetime() if not pd.isna(parsed) else None

    def _normalize_daily_kline(self, raw_data: pd.DataFrame, stock_code: str) -> pd.DataFrame:
        if raw_data is None or raw_data.empty:
            raise EmptyStockDataError(f"AKShare returned empty daily kline for {stock_code}")

        missing_fields = [field for field in self.required_source_fields if field not in raw_data.columns]
        if missing_fields:
            raise StockDataSchemaError(f"AKShare daily kline missing fields: {missing_fields}")

        data = raw_data.rename(columns=self.field_mapping).copy()
        if "stock_code" not in data.columns:
            data["stock_code"] = stock_code
        data["stock_code"] = data["stock_code"].astype(str).str.zfill(6)
        data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce").dt.date

        for column in ("open", "high", "low", "close", "volume", "amount", "turnover_rate", "change_pct"):
            if column in data.columns:
                data[column] = pd.to_numeric(data[column], errors="coerce")

        for percent_column in ("turnover_rate", "change_pct"):
            if percent_column in data.columns:
                data[percent_column] = data[percent_column] / 100

        data = data.where(pd.notnull(data), None)
        if data["trade_date"].isna().any():
            raise StockDataSchemaError("AKShare daily kline contains invalid trade_date values")

        for column in self._numeric_required_columns():
            if column in data.columns and data[column].isna().any():
                raise StockDataSchemaError(f"AKShare daily kline contains invalid numeric values in {column}")

        for column in self.output_columns:
            if column not in data.columns:
                data[column] = None
        return data.loc[:, self.output_columns].sort_values("trade_date").reset_index(drop=True)

    @staticmethod
    def _normalize_stock_code(stock_code: str) -> str:
        if not isinstance(stock_code, str):
            raise InvalidStockCodeError("stock_code must be a string")
        normalized = stock_code.strip()
        if not (normalized.isdigit() and len(normalized) == 6):
            raise InvalidStockCodeError("stock_code must be a 6-digit string")
        return normalized

    @staticmethod
    def _validate_dates(start_date: date, end_date: date) -> None:
        if not isinstance(start_date, date) or not isinstance(end_date, date):
            raise ValueError("start_date and end_date must be date instances")
        if start_date > end_date:
            raise ValueError("start_date must be earlier than or equal to end_date")

    @staticmethod
    def _numeric_required_columns() -> Iterable[str]:
        return ("open", "high", "low", "close", "volume", "amount")
