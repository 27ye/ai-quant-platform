# B → C：三股票回测数据包（`docs/evidence/c-delivery/`）

> 交付人：**B**　分支：`feature/v2-b-market-data`
> 窗口：请求 `2024-12-01 ~ 2026-09-15`，实际 `2024-12-02 ~ 2026-09-15`（436 行/只）
> 来源：`AKShareStockProvider / stock_zh_a_hist (eastmoney)`，**前复权 `qfq`**，日线

## 为什么放在仓库里

C 在 PR #10 评审中指出：此前的交付目录 `frozen/c-delivery/` 是本机 Git 忽略目录
（`.gitignore` 的 `/frozen/` 规则），**提交里没有这些文件，C 无法独立校验**；重新运行导出
脚本也不等于取得本批相同文件。

因此本批交付物直接提交进仓库，路径 `docs/evidence/c-delivery/`，C 拉分支即可核对。

## 文件清单（12 个）

下表哈希对应**仓库中实际存放的字节**（CRLF 行尾，见下一节）：

| 股票 | 文件 | 行数 | SHA-256 |
|---|---|---|---|
| 600519 | `600519_qfq_raw_20241201_20260915.json` | 436 | `f645ea1dedf76f18d1676412319e35052d203e7ba36b61f9bf16bb5e83a1ed82` |
| 600519 | `600519_qfq_normalized_20241201_20260915.json` | 436 | `75caedb816cd49d6b31f76dc3a398f86be0ac9b639ec43c72b0529c14e57ad7e` |
| 000001 | `000001_qfq_raw_20241201_20260915.json` | 436 | `cf50922b1914cee945357c2cfb118715cc211e49d244a424f7c7b63e2581440e` |
| 000001 | `000001_qfq_normalized_20241201_20260915.json` | 436 | `78189dfa5b8d877b579599803e7d62d2bde42a6cc3185643e67950e71d3cc99a` |
| 300750 | `300750_qfq_raw_20241201_20260915.json` | 436 | `ceb7b86724f1bcfe23b638776b4355b8c961697914898fe88203ebe1a2ac9030` |
| 300750 | `300750_qfq_normalized_20241201_20260915.json` | 436 | `a8c03c0a31c7e635d4902c1ab0bbaad66d945307c23f38613480630780c44b21` |
| — | `600519_metadata.json` | — | `b6a1d9a9dbb67908e0e78e31abd9d49c5a9a1eb8a66191d805b7fa119b9b2c07` |
| — | `000001_metadata.json` | — | `fdb099969492b3dbd71dbf3813ececfb1b67b85714dac8ba16e3029c23a59d7f` |
| — | `300750_metadata.json` | — | `77366fbfa6751573ecdf9a2a35e79ba03da2e7f003017ba1b2785f14b507bc58` |
| — | `MANIFEST.json` | — | `a75efb5a6336268b9766e6062d9911ab5441de66f9017011a96fd5e56b7a721d` |
| — | `mysql_readback.json` | — | `536a27e313378636bb019efdf2930c318016ba0f340edf40a5c0ad505b7c2c09` |

### 两种表示形式（用途不同，请勿混用）

- **`*_raw_*.json`** = provider **原精度**（未做 4/2/6 舍入），用于**来源核验与留档**。
- **`*_normalized_*.json`** = 规范化 **4/2/6** 输入，**就是正式送入 C 的那份行**，
  用于直接计算、API 与 MySQL 一致性验收。

每只文件字段：`stock_code`（六位字符串）、`trade_date`（升序、不重复）、
`open/high/low/close/volume`，另附 `amount/turnover_rate/change_pct`。

## 行尾与字节哈希（已修正）

C 复核时发现：**已公布的 SHA-256 对应 CRLF 字节，而 Git 提交里的 blob 是 LF**，
所以从仓库直接取文件验不上哈希。原因与处理：

| 项 | 说明 |
|---|---|
| 现象 | 本机 `core.autocrlf=true`，提交时把工作区的 CRLF 归一化成 LF 存进 blob |
| 证据 | 工作区文件（CRLF）哈希 = 公布值；CRLF→LF 后 600519 normalized = `4142a2483daf6b4e51ff14a1d604f3d55cdcdb4787418e1b0abb5d4c1634d5d2`，正是 C 报的 LF 值 |
| **修正** | 新增本目录的 `.gitattributes`：`*.json -text`，**禁止 git 归一化这些文件的字节**；并把已提交的 JSON 重新入库，使 blob 保存的就是 CRLF 原始字节 |
| 结果 | 现在**新克隆仓库得到的文件就是公布哈希对应的字节**，无需再做 LF↔CRLF 转换 |

若你手上已经有基于 `ce06ed3` 的 LF 副本、想直接核对旧 blob，转换关系是
“LF 版本 = 把文件所有 CRLF 换成 LF”，对应的 LF 哈希见
`docs/examples/C_V2_B_DELIVERY_HASHES_20260916.json`（该文件由 C 发布，值的来源即上述 LF blob）。

## raw 与 normalized 的一致性（`2026-09-15` 差异，已定位）

对每只股票逐行比对 `raw` 与 `normalized`（容差 `1e-6`，即只容忍浮点噪声）：

| 股票 | 总行数 | 只差舍入 | **实质不一致** |
|---|---|---|---|
| 000001 | 436 | 436 | **0** |
| 300750 | 436 | 436 | **0** |
| 600519 | 436 | 435 | **1**（`2026-09-15`） |

600519 该行的差异（C 已列出，此处复现一致）：

| 字段 | raw | normalized |
|---|---:|---:|
| `low` | 1271.28 | 1273.0 |
| `close` | 1272.75 | 1278.66 |
| `volume` | 13762 | 2942 |
| `amount` | 1756915149.0 | 376338636.0 |
| `turnover_rate` | 0.0011 | 0.0002 |
| `change_pct` | -0.0041 | 0.0005 |

### 根因（代码级）

`scripts/export_c_delivery.py` 对每只股票做的是**两次独立取数**，不是同一批数据出两份：

```python
raw_source = StockService()                     # 直连 provider 取原精度
raw_rows = raw_source.get_daily_kline(code, start, end)

normalized_source = MarketDataService(...)      # 走数据库侧，落库后再读回
normalized_rows = normalized_source.query_daily(code, start, end, ...)
```

- `2026-09-15` 正是**抓取当天、当时尚未收盘**的交易日；
- `000001` / `300750` 两条路径当天恰好取到同一快照，所以只差舍入；
- `600519` 两条路径取到了**同一交易日的不同盘中快照**（raw 的成交量更大，是更晚的一次），
  因此不是舍入差异。

**这是导出脚本的取数口径缺陷，不是代码计算问题。** 对已收盘的历史交易日，两条路径都一致。

### 影响范围

- `2026-09-15` **不在**本次任何验收计算区间内（三股票九组回测区间是
  `2025-07-04 ~ 2026-08-31`，窗口内数据完全一致）；C 也已只放行这九组计算与 HTTP/SQLite 验证。
- 「完整 436 行整包 raw/normalized 一致性」**本批仍未通过**，如实标注，不掩盖。

### 复现方式

```bash
python scripts/verify_c_delivery_consistency.py
# 600519 / 000001 / 300750 逐行比对；发现超出舍入的差异时退出码为 1
```

### 下一步（尚未执行）

把导出脚本改成**一次取数、两处输出**（同一批 provider 行 → raw 原样 + normalized 走 B 的
4/2/6 规范化），从根上消除双源快照差异；然后重新生成整包并公布新哈希。
未在本轮直接改导出管线，是因为它依赖实时 provider 与真实 MySQL，本轮无法完整验证——
不改没验证过的交付管线。

## 校验方式

```bash
# 逐文件核对 SHA-256（本目录已是公布字节，直接比即可）
python - <<'PY'
import hashlib, json, pathlib
base = pathlib.Path("docs/evidence/c-delivery")
manifest = json.loads((base / "MANIFEST.json").read_text(encoding="utf-8"))
for stock in manifest["stocks"]:
    for kind in ("raw", "normalized"):
        name = pathlib.Path(stock[kind]["path"]).name
        got = hashlib.sha256((base / name).read_bytes()).hexdigest()
        print(stock["stock_code"], kind, "OK" if got == stock[kind]["sha256"] else "MISMATCH")
PY

# raw / normalized 逐行一致性
python scripts/verify_c_delivery_consistency.py

# 交付文件 vs MySQL 回读（需要本机 MySQL）
python scripts/verify_c_delivery_mysql.py
```

> `MANIFEST.json` 是抓取当时生成的原始证据，**内容未做修改**，因此其中
> `raw.path` / `normalized.path` / `metadata_file.path` 仍写着抓取时的本机路径
> `frozen\c-delivery\...`。本次只是把同一批文件**原样搬到仓库内**。

## 版本口径

- 文件 SHA-256（本目录）、C 的 `data_hash`、D 的 `context_hash` **分别记录、不混用**；
- 行情进入 C 前由 B 统一精度（4/2/6），**C 返回的结果保存时不再二次舍入**；
- 三方验收必须使用**同一份规范化输入、同一参数与版本**。

## 过程说明（如实）

300750 的扩展窗口此前连续多次撞在上游不可用窗口上（主站 `RemoteDisconnected`、
同源延迟主机返回空），最终由低频重试命中窗口后一次性取齐三只。导出脚本已改为
**以磁盘产物为准**：后续失败轮次不会抹掉早先抓到的文件，`MANIFEST` 只描述真实存在的产物。
