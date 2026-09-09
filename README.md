# AI 智能量化投研平台 V1

这是一个面向 A 股投研链路的 V1 工程。当前已完成基础骨架、AKShare 日 K Provider、量化分析，以及 AI 接口、真实数据上下文、OpenAI 兼容 Client、Prompt 和 Structured Output 校验。

V1 最终链路是：股票搜索 -> AKShare 真实行情 -> MySQL -> FastAPI -> K 线 -> 技术指标 -> 量化评分 -> 简单回测 -> 新闻 -> AI 综合分析 -> Vue 前端展示。

## 技术栈

- 前端：Vue 3、TypeScript、Vite、Element Plus、ECharts、Axios、Vue Router
- 后端：Python 3.9、FastAPI、Pydantic、SQLAlchemy、Uvicorn
- 数据：AKShare、Pandas、NumPy
- 数据库：MySQL 8
- AI：LLM API、Structured Output

## 项目目录

```text
ai-quant-platform/
├── backend/              # FastAPI 后端
│   └── app/
│       ├── api/v1/
│       ├── core/
│       ├── data/providers/
│       ├── db/
│       ├── models/
│       ├── schemas/
│       ├── services/
│       ├── quant/
│       ├── ai/
│       └── main.py
├── frontend/             # Vue 3 前端
│   └── src/
├── tests/                # 后端测试
├── scripts/              # 本地验证脚本
├── docs/                 # 项目规范文档
├── .env.example
├── .gitignore
└── README.md
```

## Python 环境准备

后端统一使用 Python 3.9。建议在项目根目录创建虚拟环境：

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r backend/requirements-dev.txt
```

## Node 环境准备

建议使用 Node.js 18+。

```bash
cd frontend
npm install
```

## MySQL 配置

需要本地或远程 MySQL 8，并创建数据库：

```sql
CREATE DATABASE ai_quant DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

已提供 B 的幂等建表迁移脚本 `python scripts/migrate_db.py`，使用当前配置的目标库。
执行前请确认库名与权限。D 联合验收使用下文的 `--mysql` 隔离模式，不直接对现有业务库运行迁移或写入验证数据。

## .env 配置

复制 `.env.example` 为 `.env`，按本机环境填写：

```env
APP_NAME=AI Quant Research Platform
APP_ENV=development
APP_DEBUG=false
CORS_ORIGINS=http://localhost:5173

MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=
MYSQL_DATABASE=ai_quant

LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=
LLM_TIMEOUT_SECONDS=30
```

前端如需覆盖 API 地址，可复制 `frontend/.env.example` 为 `frontend/.env`。

## 后端启动

```bash
uvicorn backend.app.main:app --reload
```

健康检查：

```bash
curl http://localhost:8000/api/v1/health
```

期望返回：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "status": "ok"
  }
}
```

## 前端启动

```bash
cd frontend
npm run dev
```

默认访问 `http://localhost:5173`。

构建检查：

```bash
npm run build
```

## AI 综合分析

AI 接口只接收 6 位字符串股票代码：

```bash
curl -X POST http://localhost:8000/api/v1/ai/analyze \
  -H "Content-Type: application/json" \
  -d '{"stock_code":"600519"}'
```

接口通过请求级依赖注入消费 B 的 `MarketDataService`、`NewsService`，行情只查询一次并复用 C 的量化流水线结果；股票名称和行业沿用 `StockService`。行情、新闻与 AI 报告仓库共用请求级 MySQL 会话。

LLM 输出经 Pydantic 校验，首次不合法只修复一次，报告保存成功后才返回成功。新闻确实为空时明确说明缺失，缓存新闻按实际发布时间解释。正式接口强制要求 MySQL，不提供 SQLite 或内存降级。

行情精度和完整性由 B 负责。当前 D 不注入未经验证的交易日历，无法证明覆盖完整时由 B 保守重新拉取；不是仅凭行数、首尾日期或 15 天间隔认定缓存完整。

不写入 MySQL 的真实 AKShare + LLM 联调命令：

```bash
python scripts/validate_ai_analysis.py --stock-code 600519
```

使用真实服务图和正式 AI 路由，在本机新建唯一命名的独立 MySQL 库验收：

```bash
python scripts/validate_ai_analysis.py --mysql --stock-code 600519
```

该命令只创建 `ai_quant_v1_acceptance_<时间戳>` 新库，拒绝非本机地址或重用同名库。
仅切换自身进程的数据库配置，不修改 `.env`，不覆盖 `ai_quant`，成功或失败后均保留验收库。
需当前 MySQL 账号具备创建测试库及建表、读写权限；1045 表示认证被拒绝。

仅排查 LLM 连接时可用 `python scripts/validate_ai_analysis.py --llm-only`。
这不是股票数据、报告内容或 MySQL 落库验收。详细结果及待办见 [D 集成验收记录](docs/D_INTEGRATION_ACCEPTANCE.md)。

## AKShare 真实数据验证

```bash
python scripts/validate_akshare.py --stock-code 600519
```

该脚本会通过 `AKShareStockProvider` 获取贵州茅台 qfq 日 K 数据。网络不可用、AKShare 不可用或字段变化时，脚本会返回失败原因。

## 当前已完成

- 项目基础目录
- FastAPI 应用入口
- `GET /api/v1/health`
- 统一配置管理，从 `.env` 读取 MySQL 和 LLM 配置
- SQLAlchemy Base、Engine、Session
- `DATABASE_DESIGN.md` 对应的六个 ORM Model
- 基础 Pydantic Schema
- `StockDataProvider` 抽象与 `AKShareStockProvider`
- AKShare 中文字段到内部 `snake_case` 字段转换
- OpenAI 兼容 LLM Client、Prompt 和 Structured Output 校验骨架
- `POST /api/v1/ai/analyze` 契约、AI 结果持久化和统一错误响应
- 股票搜索、K 线、技术指标、量化评分与回测 API
- Vue 3 health 状态、股票搜索、详情图表、回测与 AI 结构化报告展示

## 当前未完成

- B/C 新版本的数据质量边界与独立补充用例联合确认
- 冻结真实样本的独立 MySQL 一致性验证及正式 AI 报告落库验收
- 实时 AKShare、MySQL、新闻和 LLM 的完整端到端验证，以及 A 的真实页面联调
