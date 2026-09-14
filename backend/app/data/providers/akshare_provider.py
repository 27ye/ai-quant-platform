import json
import math
import threading
import time
from datetime import date, datetime
from typing import Any, Dict, Iterable, List

import pandas as pd

from backend.app.data.providers.base import (
    EmptyStockDataError,
    InvalidStockCodeError,
    StockDataProvider,
    StockDataProviderError,
    StockDataSchemaError,
)

#: Transient network/parse failures worth retrying: eastmoney connections are
#: intermittently dropped/reset on some networks. ``requests`` exceptions all
#: derive from ``OSError``; a 502 HTML body surfaces as ``JSONDecodeError``.
_TRANSIENT_ERRORS = (OSError, json.JSONDecodeError)


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

    #: Bounded retry for transient network/parse failures (same source, same fields).
    retry_attempts = 3
    retry_delay_seconds = 0.5
    #: Bound the wall-clock time of a single AKShare call and of the whole retry
    #: sequence, so a hung upstream returns 50001 quickly instead of hanging.
    call_timeout_seconds = 3.0
    retry_total_budget_seconds = 4.0
    #: Timeout for the same-source fallback request (keeps total bounded).
    fallback_timeout_seconds = 3.0
    #: Same-source delayed-quote host used only as a fallback when the primary
    #: eastmoney hosts fail after retries (identical endpoints and field口径).
    delayed_base_url = "https://push2delay.eastmoney.com"
    #: Cap on concurrently-running (possibly hung) background AKShare calls, so
    #: repeated timeouts cannot accumulate unbounded daemon threads.
    max_background_workers = 4
    _worker_lock = threading.Lock()
    _active_workers = 0

    def _call_with_timeout(self, call, timeout):
        """Run ``call`` in a bounded daemon thread, raising if it exceeds ``timeout``.

        A daemon thread cannot be cancelled, so the number of in-flight workers is
        capped: once the cap is reached new calls fail fast instead of piling up
        more hung threads.
        """
        cls = AKShareStockProvider
        with cls._worker_lock:
            if cls._active_workers >= self.max_background_workers:
                raise TimeoutError("too many in-flight AKShare calls")
            cls._active_workers += 1
        box = {}

        def worker():
            try:
                box["value"] = call()
            except BaseException as exc:  # noqa: BLE001 - re-raised in the caller
                box["error"] = exc
            finally:
                with cls._worker_lock:
                    cls._active_workers -= 1

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            raise TimeoutError(f"AKShare call exceeded {timeout:.1f}s")
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def _call_with_retry(self, call):
        """Bounded retries on transient errors within a total wall-clock budget."""
        deadline = time.monotonic() + self.retry_total_budget_seconds
        last_exc = None
        attempts = max(1, int(self.retry_attempts))
        for attempt in range(attempts):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                return self._call_with_timeout(
                    call, min(self.call_timeout_seconds, remaining)
                )
            except _TRANSIENT_ERRORS as exc:
                last_exc = exc
                if attempt < attempts - 1:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    time.sleep(min(self.retry_delay_seconds * (attempt + 1), remaining))
        if last_exc is None:
            last_exc = TimeoutError("AKShare call exceeded the retry budget")
        raise last_exc

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

            raw_data = self._call_with_retry(
                lambda: ak.stock_zh_a_hist(
                    symbol=stock_code,
                    period="daily",
                    start_date=start_date.strftime("%Y%m%d"),
                    end_date=end_date.strftime("%Y%m%d"),
                    adjust=adjust,
                )
            )
        except StockDataProviderError:
            raise
        except _TRANSIENT_ERRORS as exc:
            return self._daily_kline_from_delay_host(
                stock_code, start_date, end_date, adjust, exc
            )
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

            raw = self._call_with_retry(lambda: ak.stock_zh_a_spot_em())
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

            raw = self._call_with_retry(
                lambda: ak.stock_individual_info_em(symbol=stock_code)
            )
        except StockDataProviderError:
            raise
        except _TRANSIENT_ERRORS as exc:
            # Same-source delayed-quote host fallback (identical eastmoney fields).
            return self._stock_info_from_delay_host(stock_code, exc)
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

    def _stock_info_from_delay_host(
        self, stock_code: str, cause: Exception
    ) -> Dict[str, Any]:
        """Fallback stock info from the same-source delayed-quote host.

        Used only when the primary ``push2`` host fails after retries; the field
        mapping (``f57/f58/f116/f117/f127``) is identical to
        ``stock_individual_info_em``. HTTP status, response structure, business
        status (``rc``), field types and stock identity are all validated; any
        anomaly maps to 50001.
        """
        import requests

        def failure(reason: str) -> StockDataProviderError:
            """Report the primary failure *and* why the fallback gave up.

            Previously the raised message only repeated ``cause``, which hid the
            real fallback reason (e.g. an empty/throttled payload) and made
            operator diagnosis misleading.
            """
            return StockDataProviderError(
                f"AKShare info request failed for {stock_code}: {cause} "
                f"(delayed-host fallback also failed: {reason})"
            )

        market = "1" if stock_code.startswith("6") else "0"
        try:
            response = requests.get(
                self.delayed_base_url + "/api/qt/stock/get",
                params={
                    "fltt": "2",
                    "invt": "2",
                    "fields": "f57,f58,f116,f117,f127",
                    "secid": f"{market}.{stock_code}",
                },
                timeout=self.fallback_timeout_seconds,
            )
            if response.status_code != 200:
                raise failure(f"HTTP {response.status_code}")
            payload = response.json()
        except StockDataProviderError:
            raise
        except Exception as exc:
            raise failure(f"{type(exc).__name__}: {exc}") from exc

        if not isinstance(payload, dict) or payload.get("rc", 0) != 0:
            raise failure(f"rc={payload.get('rc') if isinstance(payload, dict) else 'n/a'}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise failure("payload.data is not an object")
        f57 = data.get("f57")
        f58 = data.get("f58")
        if isinstance(f57, bool) or not isinstance(f57, (str, int)):
            raise failure("f57 is not a scalar stock code")
        if not isinstance(f58, str) or not f58.strip():
            raise failure("f58 is not a non-empty stock name")
        code = str(f57).strip().zfill(6)
        if code != stock_code:
            # Never return a different stock's identity.
            raise failure(f"identity mismatch (requested {stock_code}, got {code})")
        return {
            "stock_code": code,
            "stock_name": f58.strip(),
            "industry": self._cell_text(data.get("f127")),
            "total_market_cap": self._cell_float(data.get("f116")),
            "float_market_cap": self._cell_float(data.get("f117")),
        }

    def _daily_kline_from_delay_host(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        adjust: str,
        cause: Exception,
    ) -> pd.DataFrame:
        """Fallback qfq daily kline from the same-source delayed-quote host."""
        import requests

        def build_failure(reason: str) -> StockDataProviderError:
            """Report the primary failure *and* why the fallback gave up."""
            return StockDataProviderError(
                f"AKShare request failed for {stock_code}: {cause} "
                f"(delayed-host fallback also failed: {reason})"
            )

        market = "1" if stock_code.startswith("6") else "0"
        try:
            response = requests.get(
                self.delayed_base_url + "/api/qt/stock/kline/get",
                params={
                    "secid": f"{market}.{stock_code}",
                    "klt": "101",  # daily
                    "fqt": "1" if adjust == "qfq" else "0",
                    "fields1": "f1,f2,f3,f4,f5,f6",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
                    "beg": start_date.strftime("%Y%m%d"),
                    "end": end_date.strftime("%Y%m%d"),
                },
                timeout=self.fallback_timeout_seconds,
            )
            if response.status_code != 200:
                raise build_failure(f"HTTP {response.status_code}")
            payload = response.json()
        except StockDataProviderError:
            raise
        except Exception as exc:
            raise build_failure(f"{type(exc).__name__}: {exc}") from exc

        if not isinstance(payload, dict) or payload.get("rc", 0) != 0:
            raise build_failure(
                f"rc={payload.get('rc') if isinstance(payload, dict) else 'n/a'}"
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            raise build_failure("payload.data is not an object")
        klines = data.get("klines")
        if not isinstance(klines, list) or not klines:
            # A data-source failure must surface as 50001, never be masked as
            # "empty history" (which StockService would turn into 40003).
            raise build_failure(
                "upstream returned no klines (empty or rate-limited payload)"
            )
        rows = []
        for line in klines:
            parts = str(line).split(",")
            if len(parts) < 11:
                # A truncated upstream row means a corrupt payload: fail loudly
                # (50001) rather than silently dropping bars.
                raise StockDataSchemaError(
                    f"delayed host daily kline row is malformed for {stock_code}"
                )
            rows.append(
                {
                    "日期": parts[0],
                    "开盘": parts[1],
                    "收盘": parts[2],
                    "最高": parts[3],
                    "最低": parts[4],
                    "成交量": parts[5],
                    "成交额": parts[6],
                    "涨跌幅": parts[8],
                    "换手率": parts[10],
                }
            )
        if not rows:
            raise StockDataSchemaError(
                f"delayed host daily kline rows are malformed for {stock_code}"
            )
        return self._normalize_daily_kline(pd.DataFrame(rows), stock_code)

    def get_stock_news(self, stock_code: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch recent East Money news for a stock and return normalized dicts.

        Returns a list of ``snake_case`` dicts with keys ``stock_code``, ``title``,
        ``summary``, ``source``, ``publish_time`` (``datetime`` or ``None``) and ``url``.
        """
        stock_code = self._normalize_stock_code(stock_code)
        try:
            import akshare as ak

            raw = self._call_with_retry(lambda: ak.stock_news_em(symbol=stock_code))
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
        if value is None or isinstance(value, (list, tuple, set, dict)):
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _cell_float(value: Any) -> Any:
        if value is None or isinstance(value, (list, tuple, set, dict)):
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
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
