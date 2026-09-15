# V1 阶段总结

> 文档版本：V1.0
> 更新日期：2026-09-04
> 总结范围：main 分支已合并的全部 PR，以及 `feature/V1-ai-context-integration` 分支上已完成待提交的 AI 上下文集成工作

## 1. V1 目标回顾

跑通一条真实、可演示、可继续迭代的 A 股投研链路：

```text
股票搜索 -> AKShare 真实行情 -> MySQL -> FastAPI -> K线
-> 技术指标 -> 量化评分 -> 简单回测 -> 新闻 -> AI综合分析 -> Vue 前端展示
```

原则：链路完整、数据真实、字段一致，不追求复杂策略收益。

## 2. 已完成模块

### 2.1 基础工程（初始提交）

- FastAPI 应用骨架，统一响应结构 `ApiResponse`（`code` / `message` / `data`）。
- `GET /api/v1/health` 健康检查。
- 配置从 `.env` 读取（MySQL、LLM）。
- SQLAlchemy 基础配置与六张核心表 ORM Model：
  `stock_basic`、`stock_daily`、`stock_indicator`、`stock_news`、`backtest_result`、`ai_analysis`。
- `StockDataProvider` 抽象 + `AKShareStockProvider`，完成 AKShare 中文字段到内部 `snake_case` 的转换。
- Vue 3 + TypeScript + Vite 前端骨架。

### 2.2 量化核心模块（PR #2 `feature/V1-ai-quant`）

位置：`backend/app/quant/`

| 文件 | 职责 |
|---|---|
| `indicators.py` | MA5/10/20/60、MACD、RSI14、BOLL 指标计算 |
| `scoring.py` | 0-100 量化评分（趋势 40 / 动量 25 / 成交量 20 / 风险 15） |
| `backtest.py` | 简单策略回测：T 日收盘出信号、T+1 开盘执行、禁止未来函数 |
| `pipeline.py` | 统一入口 `analyze_quant_dataframe`：校验→指标→评分→回测→严格 JSON 输出 |
| `validators.py` | DataFrame 契约校验（列、行数、空值） |
| `serialization.py` | JSON 安全序列化（拒绝 NaN/Infinity 等非标准浮点） |
| `config.py` / `metrics.py` / `strategy.py` | 参数配置、绩效指标、策略定义 |

边界约束：Quant 模块不访问 HTTP、AKShare 或 LLM，纯函数式金融计算。

### 2.3 K 线数据接口（PR #3 `feature/V1-ai-kline`）

- `GET /api/v1/stocks/{stock_code}/kline`：qfq 日 K，保证 ≥60 行。
- 按评审意见修正：40003 业务码、空数据自动扩窗、数据清洗校验、period 参数说明。

### 2.4 指标 / 评分 / 回测 API（PR #5，包装 C 量化模块）

- `GET /api/v1/stocks/{stock_code}/indicators`
- `GET /api/v1/stocks/{stock_code}/score`
- `POST /api/v1/backtests`

由 `QuantService` 包装 `quant.pipeline.analyze_quant_dataframe`，对外输出 `meta` / `latest` / `score` / `backtest` / `series` 结构。

### 2.5 股票搜索 / 信息接口（PR #6 `feature/V1-ai-stock-search`）

- `GET /api/v1/stocks/search?keyword=...`：普通文本匹配（regex=False，避免正则元字符误伤）。
- `GET /api/v1/stocks/{stock_code}`：个股基础信息。
- 补充 Provider 归一化测试。

### 2.6 AI 分析模块（PR #1，D 角色）

位置：`backend/app/ai/` + `backend/app/services/ai_analysis.py`

- `client.py`：OpenAI 兼容 LLM 客户端（api_key / base_url / model / timeout 均可配置）。
- `prompts.py`：分析 Prompt 与修复（repair）Prompt 构建。
- `output_parser.py`：Structured Output 解析与校验，失败自动触发一次修复重试。
- `AIAnalysisService`：编排"取上下文 → LLM → 解析 → 持久化"，结果写入 `ai_analysis` 表。
- 严格 Schema 契约（`backend/app/schemas/ai.py`）：
  - `StrictSchema` 基类：`extra="forbid"` + `allow_inf_nan=False`，杜绝多余字段与 NaN/Infinity 进入 Prompt；
  - `AnalysisContext`（股票/行情快照/技术指标/评分/回测/新闻）、`AIAnalysisStructuredOutput`（trend/summary/四段分析/优势/风险/结论）、`AIAnalysisData`。
- 依赖注入基于 Protocol，未直接导入 `backend.app.quant`，与量化模块解耦。

### 2.7 AI 上下文适配器（当前分支 `feature/V1-ai-context-integration`，已完成待提交）

位置：`backend/app/services/ai_context_adapter.py`

- `StockQuantAnalysisAdapter`：把 C 量化管线输出（`latest` / `score` / `backtest`）逐字段提取并映射为 D 的 Context Schema，不整字典透传，符合 `extra="forbid"` 严格模式。
- 单请求内按股票代码缓存 K 线与量化结果，多次投影只拉取一次数据、跑一次管线。
- `EmptyNewsAnalysisService`：新闻模块（B 角色）未接入前的空实现边界，返回空列表。
- `dependencies.py` 完成依赖注入编排：Adapter → ContextProvider → AIAnalysisService。
- 配套离线验证脚本 `scripts/validate_ai_analysis.py` 与适配器测试 `tests/test_ai_context_adapter.py`。

### 2.8 前端（PR #4 `feature/V1-frontend-ui`）

技术栈：Vue 3 + TypeScript + Vite + Element Plus + ECharts + Axios + Vue Router。

- 路由：`/`（首页）、`/stock/:code`（个股详情，路由复用时重新拉数据）、未匹配回首页。
- 视图：`HomeView`（搜索入口）、`StockDetailView`（个股详情）。
- 组件：`KlineChart`（K 线）、`ScoreCard`（评分）、`BacktestPanel`（回测）、`AIReportCard`（AI 报告）、`HealthStatus`（健康状态）。
- API 层（`src/api/`）：`http` 统一封装（非 2xx 优先展示 `body.message` 业务文案）、`stocks` / `ai` / `health` 接口封装、`mockSwitch` mock 开关。
- Mock 数据层（`src/mocks/`）：AI 与股票数据 mock，便于前端独立开发。
- 已按 C 契约回归审核意见修正六项问题（含 `BacktestData` 与回测曲线字段对齐）。

## 3. API 一览

| 方法 | 路径 | 说明 | 状态 |
|---|---|---|---|
| GET | `/api/v1/health` | 健康检查 | ✅ 已合并 |
| GET | `/api/v1/stocks/search` | 股票搜索 | ✅ 已合并 |
| GET | `/api/v1/stocks/{code}` | 个股信息 | ✅ 已合并 |
| GET | `/api/v1/stocks/{code}/kline` | qfq 日 K（≥60 行） | ✅ 已合并 |
| GET | `/api/v1/stocks/{code}/indicators` | 技术指标 | ✅ 已合并 |
| GET | `/api/v1/stocks/{code}/score` | 量化评分 | ✅ 已合并 |
| POST | `/api/v1/backtests` | 简单回测 | ✅ 已合并 |
| POST | `/api/v1/ai/analyze` | AI 综合分析 | ✅ 已合并（适配器接线在当前分支） |

## 4. 测试现状

- 全量测试：**105 passed**（`python -m pytest tests`，约 4s）。
- 覆盖面：量化模块（指标/评分/回测/管线/校验）、AKShare Provider（含搜索归一化）、Stock/Quant Service、AI 全链路（Schema/客户端/Prompt/输出解析/持久化/API/上下文适配器）。
- 此前 C+D 联合评审基线为 69 passed，随各 PR 合并已增长至 105。

## 5. 协作与评审流程回顾

- 多人协作按 `docs/COLLABORATION.md` 执行，PR 流程 + 智能体交叉审查。
- 累计合并 6 个 PR（#1~#6），每次合并前均通过跨角色兼容性审查（如 C 对 D 的审查清单：测试通过 / 应用导入 / health 200 / Schema 适配 / 严格 JSON 序列化）。
- C 对 D 提出的合并前建议（`StrictSchema` 增加 `allow_inf_nan=False`）已落实。

## 6. 已知边界与待办

| 项 | 说明 | 责任 |
|---|---|---|
| 新闻模块未接入 | `EmptyNewsAnalysisService` 返回空列表，`news_analysis` 暂无真实数据 | B 角色 |
| 上下文适配器未提交 | 当前分支 `feature/V1-ai-context-integration` 改动已完成并通过测试，待提交、审查、合并 | 待办 |
| 真实 LLM 联调 | 离线验证脚本已就绪，需配置 `.env` 中 LLM 参数后做一次真实调用验证 | 待办 |
| V1 明确不做 | AI Agent、RAG、预测、用户系统、实盘交易、美股/港股等 | 见 `PROJECT_SPEC_V1.md` |

## 7. 快速启动

```powershell
# 后端
cd backend
uvicorn app.main:app --reload   # http://localhost:8000/api/v1/health

# 前端
cd frontend
npm install
npm run dev
```

```powershell
# 测试
python -m pytest tests

# AI 离线验证
python scripts/validate_ai_analysis.py
```
