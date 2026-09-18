# B 数据源实时失败诊断（给 D）

> 结论：`stock_individual_info_em` 与 `stock_zh_a_hist` 的实时失败是**上游/网络问题**，不是 B 代码问题；
> B 已按契约把两者都映射为 `50001`（未伪装成空数据）。以下为可复现诊断与不含凭据的配置说明。

## 1. 现象（与 D 报告一致）

| 数据源 | 接口 | 结果 |
|---|---|---|
| 股票基础信息 | `ak.stock_individual_info_em` → `push2.eastmoney.com/api/qt/stock/get` | `StockDataProviderError` ← `JSONDecodeError: Expecting value: line 1 column 1 (char 0)` |
| 日线行情 | `ak.stock_zh_a_hist` → `push2his.eastmoney.com` | `StockDataProviderError` ← `SSLError`（偶发 `ProxyError`） |
| 新闻 | `ak.stock_news_em` → `search-api-web.eastmoney.com` | 正常 |
| 交易日历 | `ak.tool_trade_date_hist_sina` → `finance.sina.com.cn` | 正常（网络好时） |

## 2. 复现命令

```powershell
$env:PYTHONIOENCODING='utf-8'
./.venv/Scripts/python.exe -c "from datetime import date,timedelta; from backend.app.data.providers.akshare_provider import AKShareStockProvider as P; p=P(); print(p.get_stock_info('600519'))"
./.venv/Scripts/python.exe -c "from datetime import date,timedelta; from backend.app.data.providers.akshare_provider import AKShareStockProvider as P; p=P(); print(p.get_daily_kline('600519', date.today()-timedelta(days=15), date.today()))"
```

## 3. 根因证据

1. **股票信息 = 上游返回 HTTP 502（HTML）**，akshare 直接 `r.json()` 失败：
   ```
   GET https://push2.eastmoney.com/api/qt/stock/get  ->  HTTP 502
   body: '<html><head><title>502 Bad Gateway</title></head>...'
   ```
   偶发成功窗口返回真实 JSON：`{"f57":"600519","f58":"贵州茅台","f116":1606517367893.1301,"f117":1606517367893.1301,"f127":"白酒Ⅱ"}`。
2. **日线 = `push2his.eastmoney.com` TLS 握手间歇失败**（直连与走代理均复现）：
   ```
   SSLError: HTTPSConnectionPool(host='push2his.eastmoney.com', port=443): Max retries exceeded
   偶发: ProxyError
   ```
3. **代理因素**：本机 WinINET 启用了系统代理 `127.0.0.1:7892`（Clash），`requests` 默认 `trust_env=True` 会对所有主机使用该代理；该代理对 `push2*.eastmoney.com` 不稳定（SSL/Proxy/502），而 `search-api-web` 稳定。
   验证：`requests.utils.get_environ_proxies('<host>')` 返回 `{'https': 'http://127.0.0.1:7892'}`。

## 3.1 重要线索：延迟行情主机可用

实测 `push2.eastmoney.com` 连续 20 次 HTTP 502 时，同族**延迟行情主机 `push2delay.eastmoney.com` 返回 HTTP 200**，同一接口给出 600519 真实数据（贵州茅台 / 白酒Ⅱ / 总市值·流通市值）。
→ 股票基础信息的实时获取可考虑切到 `push2delay` 主机（或在其恢复前用它做只读快照采集，本次冻结包的股票快照即由此采集，证据见包内 `stock_basic_600519.raw.json` 与 provenance）。

## 3.2 已实施的同源容错

- **有限重试 + 退避**：对**瞬时网络/解析错误**（`OSError` 派生：`ConnectionError`/`SSLError`/`ProxyError`/`Timeout`；以及 502 HTML 触发的 `JSONDecodeError`）自动重试（默认 3 次）。
- **超时与总预算（保证快速失败）**：单次 AKShare 调用超时 `call_timeout_seconds=3s`，整段重试总预算 `retry_total_budget_seconds=4s`，回退请求超时 `fallback_timeout_seconds=3s`；超预算立即放弃并返回 `50001`，避免 `search` 这类全市场分页抓取把请求挂到 15s+（前端 10s 超时只会误报「网络错误」）。
  - 诚实说明：`thread.join` 超时**不会中止**已发出的上游请求（守护线程会继续跑完），且 `requests` 的 `timeout` 只是连接/读取单步超时、**不是完整响应时限**。因此只能保证**调用方响应**被预算约束，不能宣称上游请求端到端一定 ≤ ~7s。
  - 已加**后台工作数上限** `max_background_workers=4`：达到上限即快速失败，避免反复超时导致线程无限累积。
- **同源延迟主机回退**：主站失败后回退到 `push2delay.eastmoney.com`（同为 eastmoney、同接口同字段口径）：
  - 股票信息 `/api/qt/stock/get`（实测可用：`GET /stocks/{code}` 由 50001 恢复为 200）；
  - 日线 `/api/qt/stock/kline/get`；**空响应时抛 `StockDataProviderError`（50001）**，不伪装成「无数据/40003」；**上游报文畸形行（列数不足）抛 `StockDataSchemaError`（50001）**，不静默跳过。
  - 回退响应统一校验：**HTTP 状态须为 200**、载荷须为 dict、`rc==0`、`data` 须为 dict、股票信息要求 `f57` 为标量且 **`f57` 必须等于请求的股票代码**、`f58` 为非空字符串；任何异常一律 `50001`——不返回裸 500、不返回 `code=0` 的半成品、不返回其它股票。
  - 搜索**不加回退**：延迟主机 clist 单页上限 100，无法覆盖全表，回退会给出误导性的空结果；故搜索在主站故障时**如实返回 `50001`**。
- **实测限制（重要）**：延迟主机对**长历史区间**有限制（长区间 kline 常返回空）；且**高频访问后被 eastmoney 限流**（随后各主机均可能返回空或断连）。故实时链路仍可能 `50001`，**建议低频、少量重试**，不要持续密集探测。
- 未改数据源字段口径与错误码；数据源错误一律 `50001`、不伪装为空数据；冻结链路完全不受影响。

## 3.3 主机可达性实测（本机直连、无代理）

同一时段对各家主机各发一次请求（间隔 1.5s，低频）的结果：

| 主机 / 端点 | 结果 | 说明 |
|---|---|---|
| `push2his.eastmoney.com` `/api/qt/stock/kline/get` | ❌ 0.5s `RemoteDisconnected` | 实时行情主站被**网络层重置**（不是 502、也不是超时） |
| `push2.eastmoney.com` `/api/qt/clist/get` | ❌ 0.5s `RemoteDisconnected` | 同上 |
| `82.push2.eastmoney.com` `/api/qt/clist/get` | ❌ 0.5s `RemoteDisconnected` | 同上 |
| `push2delay.eastmoney.com` `/api/qt/stock/get` | ✅ HTTP 200 | 股票信息回退**有效**（`GET /stocks/{code}` 由 50001 恢复为 200） |
| `push2delay.eastmoney.com` `/api/qt/clist/get` | ✅ HTTP 200，`total=5913` | 但 `pz` 被硬限制为 **100 行/页**（`pz=6000` 仍只返回 100） |
| `push2delay.eastmoney.com` `/api/qt/stock/kline/get` | ⚠️ HTTP 200 但 `rc=0`、`dktotal=0`、`klines=[]` | **同一组请求参数早些时候曾返回 23 行**，之后一律返回空 → 限流特征 |
| `datacenter-web.eastmoney.com` | ✅ HTTP 200 | — |
| `search-api-web.eastmoney.com`（新闻） | ✅ HTTP 200 | 新闻链路正常（0.4s，5 条） |

结论：

1. 被阻断的**只有实时行情集群**（`push2` / `push2his` / `82.push2`），表现是握手后立即 `RemoteDisconnected`；与代理无关（实测 `HTTP_PROXY`/`HTTPS_PROXY` 均为空）。
2. 因此当前：`get_stock_info` **可用**（走延迟主机）；`get_daily_kline` 走延迟主机被限流返回空 → 按契约抛 `50001`（**不会**伪装成 40003 空数据）。
3. 搜索仍如实 `50001`：延迟主机单页 100 行、全表 5913 行需 60 页，不适合做在线搜索回退（会拖垮响应时间或给出误导性结果）。
4. 判定方法：`ut` 令牌、`beg/end` 区间形式、`lmt` 参数均已逐一排除——**带与不带 `ut` 结果相同**，故不是参数问题，是上游对该来源的限流/阻断。

### 错误信息可诊断性（本次修正）

回退失败时，异常消息现在**同时**给出主站原因与回退放弃原因，例如：

```
AKShare request failed for 600519: ('Connection aborted.', RemoteDisconnected(...))
  (delayed-host fallback also failed: upstream returned no klines (empty or rate-limited payload))
```

此前只重复主站原因，会把「**回退被限流返回空**」误判为「主站网络故障」，导致排查方向错误（本次即被此掩盖过一次）。

## 4. 不含凭据的配置建议

- **优先**：确认本地代理（曾用 Clash `127.0.0.1:7892`）是否运行，且其规则/节点到 `*.eastmoney.com`、`*.sina.com.cn` 稳定；`push2*` 与 `search-api-web` 需分别可用。
  - 注意：代理关闭时本机 `HTTP_PROXY`/`HTTPS_PROXY` 为空，此时 `push2*` 仍被 `RemoteDisconnected` 阻断（见 3.3），故**不要**把问题归因于代理。
- 若存在**直连可用**的通路，可对这两个域**绕过代理**（`NO_PROXY=eastmoney.com,sina.com.cn`）；本环境实测直连同样失败，需按实际网络确认。
- **重试**：这两类失败为间歇性；Provider 现已内置有限重试 + 同源延迟主机回退（见 3.2）。
- **不要**把数据源错误降级为空数据；B 保持 `50001`。

## 5. 契约

- 两个接口失败均抛 `StockDataProviderError` → HTTP `50001`（`data provider error`），`ai_analysis` 不落库。
- 未修改 C 量化算法、A 前端源码。

## 6. 冻结链路不受影响

实时端点不可用时，**冻结样本链路**（本地文件 → `ai_quant_test` → 量化）完全离线可跑，B/C 已完成一致性验证；
实时 AKShare 冒烟待上述网络/代理问题解决后单独记录。

## 7. 2026-09-16/17 长时段 kline 不可用 + 替代来源评估（新增）

> 本节记录一次**持续约 16 小时**的行情中断的完整排查，以及为交付包引入的备用来源。
> 结论先行：**被阻断的只有 kline 这一个端点**；应用运行时 Provider **未改动**；交付包改用
> 明确标注的备用来源。

### 7.1 现象与时长

自 **2026-09-16 17:16** 起至 **2026-09-17 09:20**，三只验收股票（600519 / 000001 / 300750）的日线取数**持续失败**，
期间仅 09-17 08:06 出现**一次数秒级**可用窗口。累计 **70+ 次取数全部失败**（含 20 轮导出重试）。

### 7.2 逐项排除（都可复现）

| 假设 | 实测 | 结论 |
|---|---|---|
| 全站封 IP | `push2delay.eastmoney.com/api/qt/stock/get` 与 `ulist.np` 均 **HTTP 200 正常** | ❌ 本机未被封 |
| 某台主机故障 | 扫 **48 个主机**（`push2his`/`push2delay`/`push2` × 编号 1–99 抽样）：32 个 `ConnectionError`、16 个 200 但 `dktotal=0` | ❌ 不是单主机问题 |
| 缺 `ut` 令牌 | `ut` 取 `fa5fd1943c7b386f172d6893dbfba10b` / `7eea3edcaed734bea9cbfc24409ed989` / `bd1d9ddb04089700cf9c27f6f7426281` 与不带 `ut` 结果**完全相同** | ❌ 不是参数 |
| 窗口太长 | 1 周 / 1 月 / 6 月 / 1 年 / 全量 各 3 次 | ❌ 全部失败，与窗口长度无关 |
| 本地代理 | `HTTP_PROXY`/`HTTPS_PROXY`/`ALL_PROXY` 均为空；`lmclientCore` 占用的 `127.0.0.1:7892` 走 HTTP/SOCKS5 均 **TLS 握手失败** | ❌ 与代理无关，且该端口**不能**当代理用 |

**特征**：`push2his…/api/qt/stock/kline/get` 握手后立即 `RemoteDisconnected`；
`push2delay…/kline/get` 返回 `HTTP 200` + `{"rc":0,…,"dktotal":0,"klines":[]}`（契约已记录的"限流后恒空"）。
按 §3.2 的契约，空响应抛 `50001`，**不伪装成 40003 空数据**。

### 7.3 替代来源评估（口径验证优先）

| 来源 | 可达 | 字段 | 与东财的一致性 |
|---|---|---|---|
| **腾讯** `web.ifzq.gtimg.cn/appstock/app/fqkline/get`（qfq） | ✅ | `[date, open, close, high, low, volume]`（**非** OHLC 顺序），volume 单位同为**手** | 共同 436 日中 **OHLC 有 378/209/327 行不同**（600519/000001/300750），最大 \|差\| ~0.004 元；**成交量完全一致**；**仅 2 位舍入后一致**；无 `amount`/`turnover_rate` |
| 新浪 `ak.stock_zh_a_daily(adjust="qfq")` | ✅ | 含 `amount`/`outstanding_share`/`turnover`（`turnover` 已是小数，与 B 的存储口径一致） | **复权口径不同**：2024-12-02 为 1415.45/1414.52，与东财 1422.54/1421.54 **差约 0.5%** |

**结论**：`amount` 是**厂商无关**的成交额原始值（新浪与东财实测**完全相同**：`4086609952`），
但**价格复权口径因厂商而异**。因此选**腾讯**（价格与东财最接近，量级差 0.004 元）而**非**新浪（差 0.5%）；
并在交付物中如实标注差异，**不声称逐值相同**。

### 7.4 采取的处置（不改变运行时行为）

- **应用运行时 Provider 零改动**：`StockService` 仍是单厂商（东财 + 同源 `push2delay` 回退），
  失败仍如实抛 `50001`。§3.2 的契约与 C 的复验**未被推翻**。
- 备用来源**只存在于导出脚本**：`scripts/export_c_delivery.py --source tencent`（默认 `eastmoney`），
  来源写入 manifest 的 `market_data_source` / `source_note` 与**逐股** `source`，不会被冒充成东财数据。
- 交付包 `docs/evidence/c-delivery-20260917/` 即由此产出：三股×437 行，`raw`/`normalized` 三对全部一致，
  独立 MySQL 回读 `ok`。溯源（含导出时工作区为 dirty 的说明）、精度差异与已知限制见包内 README。
- **是否需要**长期引入跨厂商兜底（会改变 `50001` 语义与契约）属**产品决策**，需 D/C 认可；
  本环境只做了交付脚本层面的备用来源。

### 7.5 复现命令

```powershell
# 端点 / 主机可达性
curl.exe -sS -o NUL -w "code=%{http_code}`n" --max-time 15 `
  "https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.600519&klt=101&fqt=1&beg=20260908&end=20260916&fields1=f1&fields2=f51"
curl.exe -sS --max-time 15 `
  "https://push2delay.eastmoney.com/api/qt/stock/kline/get?secid=1.600519&klt=101&fqt=1&beg=20260908&end=20260916&fields1=f1&fields2=f51"
# 非 kline 端点仍可用（用于区分"被封 IP"与"仅该端点受限"）
curl.exe -sS --max-time 15 "https://push2delay.eastmoney.com/api/qt/stock/get?secid=1.600519&fields=f43,f57,f58"

# 应用侧（应如实抛 50001，且延迟主机回退也失败）
.\.venv\Scripts\python.exe -c "from datetime import date; from backend.app.services.stock_service import StockService as S; print(S().get_daily_kline('600519', date(2024,12,1), date(2026,9,16)))"
```
