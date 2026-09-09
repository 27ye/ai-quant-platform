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
- **行情 Upsert/查询**：`backend/app/services/market_data_service.py` —— `MarketDataRepository` 按 `(stock_code, trade_date)` Upsert；`MarketDataService` 复用 `StockService` 的清洗 + 自动扩窗，`.query_daily(..., min_rows=60)` 仅当缓存行数 ≥ `min_rows` 才算完整命中，否则经 `StockService` 拉取补全；最大扩窗后仍不足抛出 `InsufficientStockDataError`（`40003`）。
- **新闻服务**：`backend/app/services/news_service.py` —— `NewsService.get_news(stock_code, limit)` 返回**按 `publish_time` 倒序、`NULL` 最后**的统一 `NewsItemContext` 列表；`AKShareStockProvider.get_stock_news` 已先对全部有效新闻按时间倒序再应用 `limit`（最新不会被源顺序丢弃）。实现 D 的 `NewsAnalysisService` Protocol。
- **DB 异常**：两个 Repository 的 `SQLAlchemyError` 统一转为 `DatabaseOperationError`（`50002`）并 rollback，`/news` 在 DB 故障时返回 `ApiResponse{code:50002, message:"database error"}`
- 错误：统一业务码 + `ApiResponse`（`40001`/`40002`/`40003`/`50001`/`50002`/`50003`），见 `docs/API_SPEC.md`。
- 契约：`docs/API_SPEC.md`（新增 4.3 股票新闻）。
- 测试：`pytest tests -q` → **121 passed**（基线 95 + 新增 26）。

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
