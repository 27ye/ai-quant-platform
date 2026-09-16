# AI 智能量化投研平台 V1 数据库设计

> Database：MySQL 8  
> Database Name：`ai_quant`

## 1. 设计原则

V1 数据库只覆盖基础股票信息、历史行情、技术指标、股票新闻、回测结果和 AI 分析结果。不设计用户、账户、实盘订单、支付、权限或 Portfolio。

V1 暂不强制 MySQL Foreign Key，统一使用 `stock_code` 逻辑关联。

## 2. stock_basic

```sql
CREATE TABLE stock_basic (
    stock_code VARCHAR(10) PRIMARY KEY,
    stock_name VARCHAR(100) NOT NULL,
    industry VARCHAR(100),
    total_market_cap DECIMAL(20,2),
    float_market_cap DECIMAL(20,2),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP
);
```

股票代码必须使用字符串，不能使用整数。

## 3. stock_daily

```sql
CREATE TABLE stock_daily (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    stock_code VARCHAR(10) NOT NULL,
    trade_date DATE NOT NULL,
    open DECIMAL(12,4),
    high DECIMAL(12,4),
    low DECIMAL(12,4),
    close DECIMAL(12,4),
    volume BIGINT,
    amount DECIMAL(24,2),
    turnover_rate DECIMAL(12,6),
    change_pct DECIMAL(12,6),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_stock_trade_date (stock_code, trade_date),
    INDEX idx_stock_code (stock_code),
    INDEX idx_trade_date (trade_date)
);
```

## 4. stock_indicator

```sql
CREATE TABLE stock_indicator (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    stock_code VARCHAR(10) NOT NULL,
    trade_date DATE NOT NULL,
    ma5 DECIMAL(12,4),
    ma10 DECIMAL(12,4),
    ma20 DECIMAL(12,4),
    ma60 DECIMAL(12,4),
    macd DECIMAL(16,6),
    macd_signal DECIMAL(16,6),
    macd_hist DECIMAL(16,6),
    rsi14 DECIMAL(12,6),
    boll_upper DECIMAL(12,4),
    boll_middle DECIMAL(12,4),
    boll_lower DECIMAL(12,4),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_indicator_stock_date (stock_code, trade_date),
    INDEX idx_indicator_stock (stock_code)
);
```

## 5. stock_news

```sql
CREATE TABLE stock_news (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    stock_code VARCHAR(10) NOT NULL,
    title VARCHAR(500) NOT NULL,
    summary TEXT,
    source VARCHAR(200),
    publish_time DATETIME,
    url VARCHAR(1000),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_news_stock (stock_code),
    INDEX idx_news_publish_time (publish_time)
);
```

## 6. backtest_result

```sql
CREATE TABLE backtest_result (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    stock_code VARCHAR(10) NOT NULL,
    strategy_name VARCHAR(100) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    initial_cash DECIMAL(20,2),
    total_return DECIMAL(16,8),
    annual_return DECIMAL(16,8),
    max_drawdown DECIMAL(16,8),
    sharpe_ratio DECIMAL(16,8),
    win_rate DECIMAL(16,8),
    trade_count INT,
    benchmark_return DECIMAL(16,8),
    parameters JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- V2（迁移 v4）结果快照：历史读取只用这些列，不用当前行情重算
    semantics_version VARCHAR(20),      -- v1_legacy / v2_windowed
    strategy_version VARCHAR(20),
    final_equity DECIMAL(20,2),
    order_count INT,
    warmup_start_date DATE,             -- v2_windowed 的预热起点
    equity_curve JSON,
    benchmark_curve JSON,
    drawdown_curve JSON,
    orders JSON,
    effective_parameters JSON,          -- v1_legacy: 完整 V1 配置；v2_windowed: 仅白名单五字段
    data_meta JSON,                     -- 请求/实际区间、行数、frame_digest(B)、c_data_hash(C)、来源
    input_snapshot JSON,                -- V2（v6）送进 C 的逐行输入（最后 long 条预热 + 区间）
    c_result JSON,                      -- V2（v7）C 的完整结果，原样保存，历史详情自此读取
    INDEX idx_backtest_stock (stock_code),
    INDEX idx_backtest_strategy (strategy_name)
);
```

V1 只写了摘要指标，未保存曲线。**V2 起**同一次计算会把摘要 + 三条曲线 + 成交明细 + 生效参数 + 数据元信息**在一次事务内**写入（迁移 v4 对既有表做增量 `ALTER`；v6 补 `input_snapshot`，v7 补 `c_result`）。旧 V1 记录缺快照时，`GET /backtests/{id}` 返回 `snapshot_status="missing"`，**不补造**。

> **口径分离**：`data_meta.frame_digest` 是 B 交给 C 的那份数据帧的摘要，`c_result.data_hash`（平铺为 `c_data_hash`）是 C 自身结果的哈希，两者分别记录、互不替代。

## 7. ai_analysis

```sql
CREATE TABLE ai_analysis (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    stock_code VARCHAR(10) NOT NULL,
    quant_score INT,
    trend VARCHAR(50),
    summary TEXT,
    technical_analysis TEXT,
    quant_analysis TEXT,
    news_analysis TEXT,
    advantages JSON,
    risks JSON,
    conclusion TEXT,
    model_name VARCHAR(100),
    context_snapshot JSON NULL,
    context_hash CHAR(64) NULL,
    source_mode VARCHAR(16) NULL,
    data_as_of DATETIME NULL,
    prompt_version VARCHAR(32) NULL,
    context_schema_version VARCHAR(32) NULL,
    output_schema_version VARCHAR(32) NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_ai_stock (stock_code),
    INDEX idx_ai_created_at (created_at)
);
```

V2 新增字段全部允许 `NULL`，以兼容 V1 历史记录。`context_snapshot` 与报告正文在同一事务写入；V1 旧记录读取时返回 `snapshot_status=legacy_missing`。V2 保留 `idx_ai_stock` 和 `idx_ai_created_at`，首版不增加复合索引。

## 8. ORM 与 Schema

- ORM Model 放在 `backend/app/models/`，建议每张表一个文件。
- Pydantic Schema 放在 `backend/app/schemas/`。
- 禁止直接把 SQLAlchemy Model 当作 API Response 返回。

## 9. 数据规则

- 百分比统一存小数，`0.21` 表示 21%。
- API 日期使用 `YYYY-MM-DD`，数据库使用 `DATE` / `DATETIME`。
- NaN、None、`-`、空字符串和 `"nan"` 写库前统一转为 `NULL`。
- `stock_daily` 必须支持按 `(stock_code, trade_date)` Upsert。

## 10. 初始化顺序

```text
1. stock_basic
2. stock_daily
3. stock_indicator
4. stock_news
5. backtest_result
6. ai_analysis
7. stock_catalog_sync   -- V2
8. stock_daily_sync     -- V2
```

## 11. V2 新增表

### 11.1 stock_catalog_sync（迁移 v2）

单行（`id=1`）记录本地股票目录的同步状态。搜索改为查 `stock_basic`，因此必须能区分"目录完整"与"同步失败"。

```sql
CREATE TABLE stock_catalog_sync (
    id INT NOT NULL PRIMARY KEY,        -- 固定 1
    status VARCHAR(20) NOT NULL,        -- success / failed
    last_success_at DATETIME NULL,      -- 仅成功时更新
    last_attempt_at DATETIME NOT NULL,  -- 每次尝试都更新
    row_count INT NOT NULL DEFAULT 0,
    source VARCHAR(200) NULL,
    last_error VARCHAR(500) NULL
);
```

### 11.2 stock_daily_sync（迁移 v3）

按股票记录**行情来源**（`stock_daily` 本身无法说明数据来自实时抓取、冻结包还是旧库）。

```sql
CREATE TABLE stock_daily_sync (
    stock_code VARCHAR(10) NOT NULL PRIMARY KEY,
    mode VARCHAR(20) NOT NULL,          -- live / frozen / unknown
    source VARCHAR(200) NULL,           -- 实际主机/端点
    row_count INT NOT NULL DEFAULT 0,
    first_trade_date DATE NULL,
    last_trade_date DATE NULL,
    last_success_at DATETIME NULL,
    last_attempt_at DATETIME NOT NULL,
    last_error VARCHAR(500) NULL
);
```

## 12. 迁移与版本（schema_version）

迁移改为**分步执行**：每步独立事务，**成功后才写入 `schema_version`**；失败不记录版本号，重跑从失败步恢复。`create_all` 只用于建新表，**不能替代 ALTER**，因此对既有表的列变更走显式 `ALTER`（按列是否存在判断，可重复执行）。

| 版本 | 内容 |
|---|---|
| v1 | 六张 V1 基础表 |
| v2 | `stock_catalog_sync` |
| v3 | `stock_daily_sync` |
| v4 | `backtest_result` 增加 V2 快照列（见 §6） |

任何数据库结构调整必须先修改本文档，并同步 ORM、Schema 和测试。
