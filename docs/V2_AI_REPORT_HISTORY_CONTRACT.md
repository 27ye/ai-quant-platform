# V2 AI 报告历史接口契约

## 版本与分析口径

- API 前缀保持 `/api/v1`。
- `PROMPT_VERSION`、`CONTEXT_SCHEMA_VERSION`、`OUTPUT_SCHEMA_VERSION` 均为 `v2.0`。
- AI 只解释 C 提供的默认评分与默认回测结果，用户参数化回测不进入报告上下文。
- 新报告保存完整上下文；旧报告不使用当前行情补写。
- Prompt 与数据库快照使用同一个上下文对象；浮点数统一为 15 位有效数字，并把 `-0.0` 规范为 `0.0`，保证 MySQL JSON 回读后哈希稳定。

## 生成报告

```http
POST /api/v1/ai/analyze
Content-Type: application/json

{"stock_code":"600519"}
```

响应中的 `data` 保留 V1 报告正文，并增加：

```json
{
  "report_id": 101,
  "created_at": "2026-09-15T08:30:00Z",
  "data_as_of": "2026-09-15T08:29:40Z",
  "source_mode": "live",
  "prompt_version": "v2.0",
  "context_schema_version": "v2.0",
  "output_schema_version": "v2.0",
  "context_hash": "9af45d325e7cced7fc420da9f502e3abcf72ede1b7ad95070b264f8b0c4052f4",
  "snapshot_status": "complete",
  "context_snapshot": {
    "stock": {"stock_code": "600519", "stock_name": "贵州茅台", "industry": "白酒"},
    "market_snapshot": {"trade_date": "2026-09-14", "close": 1450.5, "change_pct": 0.012, "turnover_rate": 0.002},
    "technical_indicators": null,
    "quant_score": {"score": 82, "level": "strong", "reasons": ["趋势得分较高"]},
    "backtest_metrics": null,
    "news": [],
    "data_as_of": "2026-09-15T08:29:40Z",
    "provenance": {
      "source_mode": "live",
      "provider": "akshare",
      "market_start_date": "2025-09-14",
      "market_end_date": "2026-09-14",
      "market_rows": 243,
      "news_status": "empty",
      "news_count": 0,
      "retrieved_at": "2026-09-15T08:29:40Z"
    }
  }
}
```

## 历史列表

```http
GET /api/v1/ai/reports?stock_code=600519&page=1&page_size=20
```

`stock_code` 可选。列表按 `created_at DESC, id DESC` 排序；默认 `page=1`、`page_size=20`，最大 100。列表项只含摘要与快照状态，不返回完整上下文。

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [{
      "report_id": 101,
      "stock_code": "600519",
      "quant_score": 82,
      "trend": "bullish",
      "summary": "...",
      "model_name": "...",
      "data_as_of": "2026-09-15T08:29:40Z",
      "created_at": "2026-09-15T08:30:00Z",
      "source_mode": "live",
      "snapshot_status": "complete"
    }],
    "total": 1,
    "page": 1,
    "page_size": 20
  }
}
```

## 历史详情与旧数据

```http
GET /api/v1/ai/reports/101
```

详情结构与生成接口一致，直接读取保存时的数据。GET 历史接口不调用 Provider、Quant 或 LLM。

V1 记录返回：

```json
{
  "snapshot_status": "legacy_missing",
  "context_snapshot": null,
  "context_hash": null,
  "source_mode": "unknown",
  "prompt_version": null,
  "context_schema_version": null,
  "output_schema_version": null
}
```

不存在的报告返回 HTTP 404：

```json
{"code":40006,"message":"report not found","data":null}
```

## 数据库增量字段

| 字段 | MySQL 类型 | 可空 | 索引 |
| --- | --- | --- | --- |
| `context_snapshot` | `JSON` | 是 | 无 |
| `context_hash` | `CHAR(64)` | 是 | 无 |
| `source_mode` | `VARCHAR(16)` | 是 | 无 |
| `data_as_of` | `DATETIME` | 是 | 无 |
| `prompt_version` | `VARCHAR(32)` | 是 | 无 |
| `context_schema_version` | `VARCHAR(32)` | 是 | 无 |
| `output_schema_version` | `VARCHAR(32)` | 是 | 无 |

已有索引 `idx_ai_stock(stock_code)`、`idx_ai_created_at(created_at)` 保持不变。
