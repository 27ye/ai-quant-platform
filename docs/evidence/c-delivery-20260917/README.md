# C 交付数据包 — 批次 `20260917`（关闭 600519 `2026-09-15` 差异）

- 生成时间：2026-09-17 08:55 (UTC+08) / `2026-09-17T00:55:26Z`
- 代码 SHA：**`b7cb06a39f56142e51cbf6c8054b03785a9881a4`**
- 请求窗口：`2024-12-01 ~ 2026-09-16`；实际 `2024-12-02 ~ 2026-09-16`（**437 行/只**）
- 最后完整交易日：`2026-09-16`
- 规范化精度：`4 / 2 / 6`（`price_ndigits` / `amount_ndigits` / `percent_ndigits`）
- 批次状态：**`ok`**（三只股票全部 `status=ok`、`rounding_problems` 为空、独立回读 `ok`）
- **数据来源：`tencent`**（不是 eastmoney —— 见下节，manifest 内 `market_data_source` / `source_note` 如实记录）
- 不覆盖旧证据：旧批次仍在 `docs/evidence/c-delivery/`

## 为什么这一批用 tencent 取数

东财的 **kline 端点对本机不可用**（不是全站封 IP，也不是参数问题）：

| 探测 | 结果 |
| --- | --- |
| `push2his.../kline/get`（含/不含 `ut`、1 周～2 年各种窗口、48 个编号主机） | 全部 `RemoteDisconnected` / 空 |
| `push2delay.../kline/get` | `HTTP 200` 但 `dktotal=0` / `klines=[]`（契约已记录的"限流后恒空"） |
| `push2delay.../stock/get`、`ulist.np`（**非 kline**） | `HTTP 200` 正常返回 → 说明本机没有被封 |

也就是说**仅 kline 这条端点不可用**，从 2026-09-16 17:16 起持续（其间 09-17 08:06 有一次数秒级恢复）。
连续尝试已累计 70+ 次取数全部失败，因此本批次改用**明确标注的备用来源**。

**应用运行时行为未做任何改动**：`StockService` 仍是单厂商（东财 + 同源 `push2delay` 回退），
Provider 失败仍如实抛 `50001`。该备用来源**只存在于导出脚本**（`--source tencent`），
并写入 manifest 的 `market_data_source` / `source_note`，不会被冒充成东财数据。

## 来源保真度（这是选 tencent 而不是其他厂商的原因）

tencent 的 qfq 复权口径与东财**一致**，OHLCV 与成交量逐值相同——包括旧包分歧那天：

| 日期 | 字段 | 旧包 raw（东财） | 本包 raw（tencent） |
| --- | --- | --- | --- |
| 2024-12-02 | open/high/low/close | 1422.54 / 1426.53 / 1411.64 / 1421.54 | 1422.537 / 1426.527 / 1411.637 / 1421.537 |
| 2026-09-15 | open/high/low/close/volume | 1281.0 / 1284.5 / 1271.28 / **1272.75** / 13762 | 1281.0 / 1284.5 / **1271.28** / **1272.75** / **13762** |

对比之下换用别的厂商会改变价格基准（例如新浪同期 2024-12-02 为 1415.45/1414.52，与东财差约 0.5%），
因此**没有**采用。

### 本包与东财的已知差异（如实列出，不掩盖）

| 字段 | 本包取值 | 说明 |
| --- | --- | --- |
| `open/high/low/close/volume` | 与东财一致 | tencent 成交量单位同为**手**，无需换算 |
| `amount` | **`null`** | tencent 该端点不发布成交额；C 侧 `validators.OPTIONAL_NUMERIC_COLUMNS` 将其列为**可选**，B 仅用于 `frame_digest` |
| `turnover_rate` | **`null`** | 同上，可选 |
| `change_pct` | **派生值**（非厂商直出） | 由相邻 qfq 收盘价计算 `(close_t − close_{t−1}) / close_{t−1}`；C 侧 `scoring.py` 需要它。已对旧包 435 行实测：最大偏差 **4.99e-05**，仅在接近零涨跌时有 3 次符号翻转（qfq 序列跨越除权日连续所致） |

为让首行也有 `change_pct`，取数时向前多取 15 天再裁剪，因此交付行本身都带真实派生涨跌幅。

## 600519 `2026-09-15` 旧差异已关闭

| | raw | normalized | 判定 |
| --- | --- | --- | --- |
| **旧包** `c-delivery` | close **1272.75**、volume 13762 | close **1278.66**、volume 2942 | **materially different（1 行）** |
| **本包** `c-delivery-20260917` | close **1272.75**、volume 13762 | close **1272.75**、volume 13762 | 一致 |

本包两侧都等于**已结算收盘值 1272.75**，与旧包的 *raw* 相同；旧包的 *normalized* 是库内 09:46 的
盘中快照——这与 B 此前的根因判断（双源快照：raw 直连、normalized 走库内缓存）**完全吻合**，
并由新包独立佐证。根因修复（一次取数、两处输出）在本批次生效。

## 校验结果

```
$ python scripts/verify_c_delivery_consistency.py --dir docs/evidence/c-delivery-20260917
OK: all 3 raw/normalized pair(s) agree after canonical rounding        (exit 0)

旧批次对照：
$ python scripts/verify_c_delivery_consistency.py --dir docs/evidence/c-delivery
FAIL: 1 of 3 pair(s) did not agree                                     (exit 1)
     └ 600519：435 行仅舍入差异 + 1 行 materially different（2026-09-15）
```

逐只：`rounding_only_rows = 437`、`materially_different_rows = []`、`structural_problems = []`。

## 独立 MySQL 回读

每只股票在**新会话**中从仓储独立读回（不经过 provider）：

```
600519: ok=true rows=437 window=['2024-12-02','2026-09-16'] problems=[]
000001: ok=true rows=437
300750: ok=true rows=437
```

`persist_normalized` 已把这批规范化行写入目标库（manifest 内 `database` 记录库名）。

## 文件与 SHA-256

| 文件 | 行数 | SHA-256 |
| --- | --- | --- |
| `600519_qfq_raw_20241201_20260916.json` | 437 | `07f9f3af59b564f36ae40d0eef340414b4716712ef1205d1a937186b18709416` |
| `600519_qfq_normalized_20241201_20260916.json` | 437 | `280eed0f779440425bf79c5c368eebc07e1abc906dba7b2ad44afdd41f95cd27` |
| `000001_qfq_raw_20241201_20260916.json` | 437 | `993fa95241c78962583f97aa06c54e5a7636196ecb222547a5ee43c8cefc207c` |
| `000001_qfq_normalized_20241201_20260916.json` | 437 | `d4fc99555e4a5283ab36408ef6063873e2a05e55e5a350826c3c56a3ac95aa73` |
| `300750_qfq_raw_20241201_20260916.json` | 437 | `780f51e0fadd7644aef83d5881917efe9f225d28baffbcde277c74ebf57d80d8` |
| `300750_qfq_normalized_20241201_20260916.json` | 437 | `b25d6e31442cdaeb37243d818b6171d69f2aad248e3f073e9500ebfcc1daf0df` |

哈希口径同旧批次：**工作区字节**。本目录 JSON 为 **CRLF**（导出脚本在 Windows 用文本模式写出），
因此同目录放置了 `.gitattributes` 声明 `*.json -text`，让 git **永不规范化**这些字节——否则
`core.autocrlf=true` 会把提交的 blob 存成 LF，新克隆出来的文件哈希与上表不符（C 在首次交付时
正是抓到这一点：提交 blob `4142a248...` vs 公布的 `75caedb8...`）。该文件另含
`*.json whitespace=cr-at-eol`，使 `git diff --check` 不被 CRLF 噪声淹没；两者都不改变任何字节。

## 复现

```powershell
# 备用来源（本批次实际使用）
python scripts/export_c_delivery.py --batch 20260917 --source tencent \
    --start-date 2024-12-01 --end-date 2026-09-16 --last-complete-trading-day 2026-09-16

# 默认来源（东财恢复后应优先用它，产物应与本包 OHLCV 一致）
python scripts/export_c_delivery.py --batch <new> \
    --start-date 2024-12-01 --end-date 2026-09-16 --last-complete-trading-day 2026-09-16

python scripts/verify_c_delivery_consistency.py --dir docs/evidence/c-delivery-20260917
```

## 已知限制（如实标注）

- 本包**不是**东财来源；`amount` / `turnover_rate` 为 `null`，`change_pct` 为派生值（偏差上限已实测）。
  若 D/C 要求必须为东财口径，请等东财 kline 恢复后用默认来源重出，本包保留为独立备选证据。
- 窗口比旧包多一天（到 `2026-09-16`，437 行 vs 436 行），因此两者不是逐行等长对照；
  旧包分歧日 `2026-09-15` 在两包中都存在，可逐行比较。
- 本证据只覆盖数据包本身；不替代 C 的 9 组 API 复验、D 的浏览器端到端或 V1→v8 迁移证据
  （后者见 `docs/evidence/v1-migration-chain-20260917/`）。
- 未在真实浏览器/真实 LLM 下验证；与本包无关。
