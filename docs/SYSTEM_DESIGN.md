# AI 智能量化投研平台 V1 系统设计

> 文档版本：V1.2  
> 架构：模块化单体  
> 后端运行时：Python 3.9

## 1. 总体架构

```text
Vue 3 Frontend
  -> HTTP JSON
FastAPI Router
  -> Service
  -> Data Provider / DB / Quant / AI
  -> AKShare / MySQL 8 / LLM API
```

依赖只能向下。Router 不直接访问 AKShare、执行金融计算、调用 LLM 或编写大量 SQL。

## 2. 后端目录

```text
backend/app/
├── api/v1/          # /api/v1 路由
├── core/            # 配置、错误、日志等基础能力
├── data/providers/  # 数据源抽象与 AKShare 实现
├── db/              # SQLAlchemy Base、Engine、Session
├── models/          # 六张表的 ORM Model
├── schemas/         # API 请求、响应和领域 Schema
├── services/        # 业务编排
├── quant/           # 指标、评分、策略、回测，后续实现
├── ai/              # LLM 与 Structured Output，后续实现
└── main.py          # FastAPI 应用入口
```

当前初始化只实现启动、health、配置、数据库基础、ORM、基础 Schema 和日 K Provider。

## 3. 前端目录

```text
frontend/src/
├── api/         # Axios 实例和接口调用
├── components/  # 可复用展示组件
├── views/       # 路由页面
├── router/      # Vue Router
├── stores/      # 确有全局状态时使用
├── types/       # API TypeScript 类型
└── utils/       # 无业务状态的通用工具
```

前端不直接访问 AKShare、MySQL 或 LLM，也不计算技术指标或回测结果。

## 4. API 层

- Base URL 固定为 `/api/v1`。
- 所有响应遵守 `docs/API_SPEC.md`。
- JSON 字段使用 `snake_case`。
- 成功响应统一为 `{ "code": 0, "message": "success", "data": ... }`。

## 5. Service 层

Service 负责组合 Provider、数据库、Quant 和 AI。后续股票行情读取建议流程：

```text
查询 MySQL -> 数据缺失时调用 Provider -> 标准化与校验 -> Upsert MySQL -> 返回
```

当前阶段可以直接通过脚本验证 Provider，但业务 API 后续必须通过 Service 编排。

## 6. Data Provider

统一抽象为 `StockDataProvider`。AKShare 调用只能出现在 `backend/app/data/providers/`。

日 K 输入：

- `stock_code`：6 位字符串
- `start_date` / `end_date`：内部使用 `date`
- `period`：V1 固定 `daily`
- `adjust`：V1 固定 `qfq`

Provider 输出字段：

```text
stock_code
trade_date
open
high
low
close
volume
amount
turnover_rate
change_pct
```

AKShare 原始中文字段必须在 Provider 内转换。若 AKShare 返回的涨跌幅、换手率是百分数值，Provider 必须转换为内部小数。

Provider 必须区分并向上抛出清晰错误：无效股票代码、数据源异常、空数据、缺少字段、字段值异常。不得吞异常或返回伪造数据。

## 7. 数据库

- 使用 SQLAlchemy 连接 MySQL 8。
- 连接信息来自 `.env`，不得硬编码密码。
- ORM 严格对应 `docs/DATABASE_DESIGN.md` 的六张表。
- V1 不强制数据库外键，统一使用 `stock_code` 逻辑关联。
- NaN、空字符串和 `"nan"` 写库前转换为 `NULL`。
- `stock_daily` 按 `(stock_code, trade_date)` 去重或 Upsert。

## 8. Quant 与 AI 边界

- Quant 只做确定性金融计算，统一使用 qfq 行情，禁止未来函数。
- AI 只消费 Stock、Quant、Backtest 和 News Service 的真实结构化输出，负责解释、总结和风险提示。
- LLM 返回必须通过 Pydantic 或 JSON Schema 校验。

## 9. 配置

`.env` 至少提供：

```text
APP_NAME
APP_ENV
MYSQL_HOST
MYSQL_PORT
MYSQL_USER
MYSQL_PASSWORD
MYSQL_DATABASE
LLM_API_KEY
LLM_BASE_URL
LLM_MODEL
LLM_TIMEOUT_SECONDS
```

仓库只提交 `.env.example`。

## 10. 初始化验证边界

本阶段至少验证：

- Python 3.9 兼容的后端应用可导入。
- FastAPI 可启动，`GET /api/v1/health` 返回契约内容。
- 六个 ORM Model 可加载且关键约束存在。
- Provider 能把 AKShare 中文列规范化为内部字段。
- 网络可用时真实获取 `600519` qfq 日 K；失败时报告真实失败原因。
- Vue 前端依赖可安装且 Vite build 通过。
