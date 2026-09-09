# B 后端进度交接单

> 更新时间：本轮协作结束时
> 用途：让新会话 / 新成员无需依赖历史对话即可接续工作。

## 1. 仓库与分支

- 上游（主仓库）：`https://github.com/27ye/ai-quant-platform`，`main` 当前指向 `9fb1acf`
- 你的 fork：`https://github.com/Lawera2601/ai-quant-platform`
- 相关分支：
  - `feature/V1-ai-stock-search`：股票搜索/信息，**PR #6 已合并**（`e966bf1` 已入 upstream main）
  - `feature/V1-db-news`：MySQL 建表/迁移 + 行情 Upsert/查询 + 新闻服务 → **PR #7 开门**
- 本地 `main` 仍在 `2070c17`（未同步 upstream 的 PR #6 与后续，合并后需 `git fetch upstream` 再同步）。

## 2. 你（B 后端）已完成的接口

| 接口 | 实现 | PR | 状态 |
|---|---|---|---|
| `GET /api/v1/stocks/{code}/kline` | K线，≥60行 qfq（`StockService` 保证） | #3 | ✅ 已合 main |
| `GET /api/v1/stocks/{code}/indicators` | 指标序列（包装 C `calculate_indicators`） | #5 | ✅ 已合 main |
| `GET /api/v1/stocks/{code}/score` | 评分（包装 C `calculate_quant_score`） | #5 | ✅ 已合 main |
| `POST /api/v1/backtests` | 回测（包装 C `run_backtest`） | #5 | ✅ 已合 main |
| `GET /api/v1/stocks/search?keyword=` | 股票搜索（`regex=False` 子串匹配，≤50 条） | #6 | ✅ 已合 main |
| `GET /api/v1/stocks/{code}` | 股票基本信息 | #6 | ✅ 已合 main |
| `GET /api/v1/stocks/{code}/news` | 个股新闻（AKShare `stock_news_em` → 统一新闻结构） | #7 | 🕒 待 Review/合并 |

## 3. 关键架构 / 约定

- 分层：`Router -> Service -> Data/Provider -> DB`；B 只包装 C 的量化（`calculate_indicators`/`calculate_quant_score`/`run_backtest`），**不重算**。
- 数据层：`AKShareStockProvider` 唯一调 AKShare；`get_stock_news(stock_code, limit)` 返回统一 `snake_case` 新闻字段（`stock_code/title/summary/source/publish_time/url`）。
- **MySQL**：`backend/app/db/migrations.py`（幂等建 6 表 + `schema_version`）；`scripts/migrate_db.py` 建库迁移。
- **行情 Upsert/查询**：`backend/app/services/market_data_service.py` —— `MarketDataRepository` 按 `(stock_code, trade_date)` Upsert；`MarketDataService` 复用 `StockService` 的清洗 + 自动扩窗，`.query_daily(..., min_rows=60, max_stale_days=3, max_gap_days=15, trading_days=None)`。**完整性依据 = `trading_days`（`(start,end)->期望交易日数`，可用交易日历）**：仅当 `len(缓存) ≥ trading_days(start,end)` 才算完整命中；`trading_days` 为 `None` 时保守重拉（无法证明完整不命中）。`max_gap_days` 仅为辅助检查。其余命中条件：全部 bar 对 C 有效（有限且 >0 的 OHLC、OHLC 序、`volume` 非空且 ≥0）、覆盖起始、最新 bar 距 end ≤ `max_stale_days`。否则经 `StockService` 拉取补全；**统一精度（4/2/6 位）后、入库及返回前做有效性校验**，有效行数不足 `min_rows` 返回 `InsufficientStockDataError`（`40003`）。导出可注入的 `MarketDataSource` Protocol。
- **新闻服务**：`backend/app/services/news_service.py` —— `NewsService.get_news(stock_code, limit, max_age_seconds=None, refresh=False)` 返回**按 `publish_time` 倒序、`NULL` 最后**的统一 `NewsItemContext` 列表；带**缓存刷新策略**（缓存最新 `publish_time` 超过 `max_age_seconds`（默认 6h）或 `refresh=True` 时重新拉取并 Upsert）。`AKShareStockProvider.get_stock_news` 先对全部有效新闻按时间倒序再应用 `limit`。导出可注入的 `NewsSource` Protocol。
- **DB 异常**：两个 Repository 的 `SQLAlchemyError` 统一转为 `DatabaseOperationError`（`50002`）并 rollback，`/news` 在 DB 故障时返回 `ApiResponse{code:50002, message:"database error"}`
- 错误：统一业务码 + `ApiResponse`（`40001`/`40002`/`40003`/`50001`/`50002`/`50003`），见 `docs/API_SPEC.md`。
- 契约：`docs/API_SPEC.md`（新增 4.3 股票新闻）。
- 测试：`pytest tests -q` → **143 passed**（基线 95 + 新增 48）。
- **真实 trading_days 来源**：`backend/app/data/trading_calendar.py` 的 `TradingCalendarProvider`（用 AKShare `tool_trade_date_hist_sina` 取 A 股真实交易日历，进程内缓存，`refresh()` 可重载；构造时可用 `trade_dates`/`fetch` 注入以便离线测试）。**`count_between(start,end) -> Optional[int]`**：日历为空、或未覆盖完整窗口（最早/最晚交易日未包住 `[start,end]`）时返回 `None`（覆盖未知），调用方据此保守重拉，**不把未知当可信 0**。接入方式：**构造器注入** `MarketDataService(..., trading_days=provider.as_callable())`，或**每次调用** `query_daily(..., trading_days=...)`。当前环境到 sina/eastmoney 的 https 仍受 TLS/网络阻塞，真实抓取需可用网络/代理。

### 可注入接口（给 D）

```python
# 行情（backend.app.services.market_data_service.MarketDataSource / .MarketDataService）
service = MarketDataService(repository=MarketDataRepository(db))  # DB 缺省时用 StockService(Provider)
rows = service.query_daily(
    "600519", start_date=None, end_date=None,
    min_rows=60, max_stale_days=3,
)  # -> List[DailyKlineSchema]，≥min_rows 且最新 bar 距 end ≤ max_stale_days，否则自动补
rows = service.sync_daily("600519", start_date, end_date, min_rows=60)  # 强制拉取+清洗+扩窗+Upsert

# 新闻（backend.app.services.news_service.NewsSource / .NewsService）
service = NewsService(repository=NewsRepository(db), max_age_seconds=21600)
items = service.get_news(
    "600519", limit=10, max_age_seconds=None, refresh=False,
)  # -> Sequence[NewsItemContext]；缓存过期或 refresh=True 时重新拉取
```

- 两个服务都支持无 DB 构造（`NewsSource` / `MarketDataSource` 只依赖可用注入源），便于 D 在 AI Context 中注入。
- `NewsService` 满足 `NewsAnalysisService` 协议（`get_news(stock_code, limit) -> Sequence[NewsItemContext]`）。

## 4. 下一步（B）

1. **PR #7**（`feature/V1-db-news`）待 Review，由 27ye 合并。该分支已基于含 PR #6 的最新 main，为干净增量。
2. 合并后同步：`git fetch upstream` → `git checkout main` → `git merge upstream/main`（本地 `main` 落后至 `2070c17`）。
3. 进入 Demo 1.0 全链路联调：A 前端 `VITE_USE_MOCK=false` → 逐接口联调 → 删 mock。D 接入 `NewsService` 到 AI Context（`AnalysisContextProvider` 已用 `NewsItemContext` 契约）。

## 5. 安全约定

- GitHub 推送使用一次性 **PAT 令牌**（`repo` 权限），用完即撤销；**不要把令牌写入 commit、写进 config、或放进 URL（会留在 shell 历史/进程列表中）**。令牌只在生成时显示一次。
- 密钥（如 MySQL 口令、LLM Key）只从环境/本地 gitignored `.env` 读取，仓库仅提交 `.env.example`。
- 数据库连接信息仅在本地 `.env`（gitignored），勿提交。

## 6. 补充说明

- `docs/COLLABORATION.md`：四人协作规范（分工/文件所有权/冲突处理）。
- 曾因脚本改 `docs/API_SPEC.md` 出现编码乱码，已用 `git checkout` 恢复并改为安全方式编辑；现无乱码。
