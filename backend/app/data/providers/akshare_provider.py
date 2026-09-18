import json
import math
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

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
    tencent_required_source_fields = ("日期", "开盘", "收盘", "最高", "最低", "成交量")
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
    #: Timeout for a fallback request (keeps total bounded).
    fallback_timeout_seconds = 3.0
    #: Same-source delayed-quote host used only as a fallback when the primary
    #: eastmoney hosts fail after retries (identical endpoints and field口径).
    delayed_base_url = "https://push2delay.eastmoney.com"
    tencent_kline_url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    tencent_retry_attempts = 2
    #: Cap on concurrently-running (possibly hung) background AKShare calls, so
    #: repeated timeouts cannot accumulate unbounded daemon threads.
    max_background_workers = 4
    _worker_lock = threading.Lock()
    _active_workers = 0

    #: Delayed-host catalog paging for the V2 stock-catalog sync. The clist
    #: endpoint hard-caps one page at 100 rows, so a full-market sync walks
    #: pages at low frequency; this was never viable for online search.
    catalog_page_size = 100
    catalog_max_pages = 80
    catalog_market_filter = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"
    #: Which host actually served the last :meth:`fetch_stock_catalog` call.
    last_catalog_source: Optional[str] = None
    #: Which host actually served the last successful :meth:`get_daily_kline`.
    last_kline_source: Optional[str] = None

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
            return self._daily_kline_from_tencent(stock_code, start_date, end_date, exc)
        except Exception as exc:
            raise StockDataProviderError(f"AKShare request failed for {stock_code}: {exc}") from exc

        self.last_kline_source = "akshare.stock_zh_a_hist"
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

    def fetch_stock_catalog(self) -> List[Dict[str, str]]:
        """Return the full A-share catalog as ``[{stock_code, stock_name}]``.

        Used by the V2 catalog sync (B1), never by online search. The primary
        source is the same full-market spot snapshot as :meth:`search_stocks`;
        when the realtime quote cluster is blocked, the same-source delayed host
        is paged through ``/api/qt/clist/get`` at low frequency. Either way a
        failure raises ``StockDataProviderError`` - an unreachable source must
        never be reported as "the market has no stocks".
        """
        reasons: List[str] = []

        try:
            items = self._catalog_from_primary()
            if items:
                self.last_catalog_source = "akshare.stock_zh_a_spot_em"
                return items
            reasons.append("primary returned no rows")
        except (*_TRANSIENT_ERRORS, StockDataProviderError) as exc:
            # ``_call_with_retry`` surfaces the raw transient error (TimeoutError
            # is OSError-derived), so both shapes must fall through to the
            # delayed host instead of escaping as an unhandled exception.
            reasons.append(f"primary: {type(exc).__name__}: {exc}")

        try:
            items = self._catalog_from_delay_host()
            if items:
                self.last_catalog_source = (
                    f"{self.delayed_base_url}/api/qt/clist/get"
                )
                return items
            reasons.append("delayed host returned no rows")
        except (*_TRANSIENT_ERRORS, StockDataProviderError) as exc:
            reasons.append(f"delayed host: {type(exc).__name__}: {exc}")

        raise StockDataProviderError(
            "stock catalog unavailable (" + "; ".join(reasons) + ")"
        )

    def _catalog_from_primary(self) -> List[Dict[str, str]]:
        import akshare as ak

        raw = self._call_with_retry(lambda: ak.stock_zh_a_spot_em())
        if raw is None or raw.empty:
            return []
        code_col = self._pick_column(raw, ("代码", "code", "股票代码"))
        name_col = self._pick_column(raw, ("名称", "name", "股票简称"))
        if code_col is None or name_col is None:
            raise StockDataSchemaError("AKShare spot response missing code/name columns")
        return self._normalize_catalog_rows(
            (row[code_col], row[name_col]) for _, row in raw.iterrows()
        )

    def _catalog_from_delay_host(self) -> List[Dict[str, str]]:
        import requests

        url = self.delayed_base_url + "/api/qt/clist/get"
        collected: Dict[str, str] = {}
        total: Optional[int] = None

        for page in range(1, self.catalog_max_pages + 1):
            try:
                response = requests.get(
                    url,
                    params={
                        "pn": str(page),
                        "pz": str(self.catalog_page_size),
                        "po": "1",
                        "np": "1",
                        "fltt": "2",
                        "invt": "2",
                        "fid": "f12",
                        "fs": self.catalog_market_filter,
                        "fields": "f12,f14",
                    },
                    timeout=self.fallback_timeout_seconds,
                )
                if response.status_code != 200:
                    raise StockDataProviderError(
                        f"delayed host catalog HTTP {response.status_code}"
                    )
                payload = response.json()
            except StockDataProviderError:
                raise
            except Exception as exc:
                raise StockDataProviderError(
                    f"delayed host catalog request failed: {exc}"
                ) from exc

            if not isinstance(payload, dict) or payload.get("rc", 0) != 0:
                raise StockDataProviderError("delayed host catalog returned a bad payload")
            data = payload.get("data")
            if not isinstance(data, dict):
                raise StockDataProviderError(
                    "delayed host catalog payload.data is not an object"
                )
            rows = data.get("diff")
            if not isinstance(rows, list):
                raise StockDataProviderError(
                    "delayed host catalog payload.diff is not a list"
                )
            if total is None and isinstance(data.get("total"), int):
                total = data["total"]

            rows = [row for row in rows if isinstance(row, dict)]
            for item in self._normalize_catalog_rows(
                (row.get("f12"), row.get("f14")) for row in rows
            ):
                collected[item["stock_code"]] = item["stock_name"]

            if not rows:
                break
            if total is not None and len(collected) >= total:
                break

        return [
            {"stock_code": code, "stock_name": name}
            for code, name in sorted(collected.items())
        ]

    @staticmethod
    def _normalize_catalog_rows(pairs: Iterable) -> List[Dict[str, str]]:
        """Normalize ``(code, name)`` pairs, dropping blank/invalid codes."""
        items: Dict[str, str] = {}
        for code_value, name_value in pairs:
            code = AKShareStockProvider._cell_text(code_value)
            name = AKShareStockProvider._cell_text(name_value)
            if not code or not name:
                continue
            code = str(code).strip().zfill(6)
            if len(code) != 6 or not code.isdigit():
                continue
            items[code] = str(name).strip()
        return [
            {"stock_code": code, "stock_name": name}
            for code, name in sorted(items.items())
        ]

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

    def _daily_kline_from_tencent(
        self,
        stock_code: str,
        start_date: date,
        end_date: date,
        cause: Exception,
    ) -> pd.DataFrame:
        """Fetch qfq bars only after the Eastmoney K-line request fails."""
        import requests

        def build_failure(reason: str) -> StockDataProviderError:
            return StockDataProviderError(
                f"AKShare request failed for {stock_code}: {cause} "
                f"(Tencent qfq fallback also failed: {reason})"
            )

        if stock_code.startswith("6"):
            symbol = f"sh{stock_code}"
        elif stock_code.startswith(("0", "3")):
            symbol = f"sz{stock_code}"
        elif stock_code.startswith(("4", "8")):
            symbol = f"bj{stock_code}"
        else:
            raise build_failure("unsupported stock market prefix")
        rows = []
        chunk_start = start_date
        while chunk_start <= end_date:
            # The endpoint silently truncates long requests (a five-year probe
            # returned only the latest ~640 bars). Two-year chunks stay below
            # that observed cap and preserve the entire requested window.
            chunk_end = min(end_date, chunk_start + timedelta(days=729))
            # Include the previous close so each chunk's first requested day
            # derives change_pct the same way as the frozen delivery batch.
            fetch_from = chunk_start - timedelta(days=15)
            url = (
                f"{self.tencent_kline_url}?param={symbol},day,"
                f"{fetch_from.isoformat()},{chunk_end.isoformat()},1000,qfq"
            )
            for attempt in range(self.tencent_retry_attempts):
                try:
                    response = requests.get(url, timeout=self.fallback_timeout_seconds)
                    if response.status_code != 200:
                        raise build_failure(f"HTTP {response.status_code}")
                    payload = response.json()
                    break
                except StockDataProviderError:
                    raise
                except Exception as exc:
                    if attempt + 1 < self.tencent_retry_attempts and isinstance(
                        exc, (OSError, requests.RequestException, json.JSONDecodeError)
                    ):
                        continue
                    raise build_failure(f"{type(exc).__name__}: {exc}") from exc

            if not isinstance(payload, dict):
                raise build_failure("payload is not an object")
            data = payload.get("data")
            if not isinstance(data, dict):
                raise build_failure("payload.data is not an object")
            node = data.get(symbol)
            if not isinstance(node, dict):
                raise build_failure(f"payload.data.{symbol} is not an object")
            # Never use the unadjusted `day` series in place of qfqday.
            klines = node.get("qfqday")
            if not isinstance(klines, list) or not klines:
                raise build_failure("upstream returned no qfqday rows")
            previous_close = None
            chunk_rows = []
            for parts in klines:
                if not isinstance(parts, list) or len(parts) < 6:
                    raise StockDataSchemaError(
                        f"Tencent qfq daily kline row is malformed for {stock_code}"
                    )
                try:
                    close = float(parts[2])
                    if not math.isfinite(close) or close <= 0:
                        raise ValueError("invalid close")
                except (TypeError, ValueError) as exc:
                    raise StockDataSchemaError(
                        f"Tencent qfq daily kline has invalid close for {stock_code}"
                    ) from exc
                change_pct = (
                    None if previous_close is None else (close - previous_close) / previous_close
                )
                previous_close = close
                if not (chunk_start.isoformat() <= str(parts[0]) <= chunk_end.isoformat()):
                    continue
                chunk_rows.append(
                    {
                        "日期": parts[0],
                        "开盘": parts[1],
                        "收盘": parts[2],
                        "最高": parts[3],
                        "最低": parts[4],
                        "成交量": parts[5],
                        # Normalization converts source percentages to ratios.
                        "涨跌幅": None if change_pct is None else change_pct * 100,
                    }
                )
            if not chunk_rows:
                raise build_failure("upstream returned no qfqday rows inside the requested window")
            rows.extend(chunk_rows)
            chunk_start = chunk_end + timedelta(days=1)
        normalized = self._normalize_daily_kline(
            pd.DataFrame(rows),
            stock_code,
            required_source_fields=self.tencent_required_source_fields,
            required_numeric_columns=("open", "high", "low", "close", "volume"),
        )
        self.last_kline_source = self.tencent_kline_url
        return normalized

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

    def _normalize_daily_kline(
        self,
        raw_data: pd.DataFrame,
        stock_code: str,
        *,
        required_source_fields: Optional[Iterable[str]] = None,
        required_numeric_columns: Optional[Iterable[str]] = None,
    ) -> pd.DataFrame:
        if raw_data is None or raw_data.empty:
            raise EmptyStockDataError(f"AKShare returned empty daily kline for {stock_code}")

        required_fields = required_source_fields or self.required_source_fields
        missing_fields = [field for field in required_fields if field not in raw_data.columns]
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

        for column in required_numeric_columns or self._numeric_required_columns():
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
