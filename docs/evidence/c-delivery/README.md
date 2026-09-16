# B → C：三股票回测数据包（`docs/evidence/c-delivery/`）

> 交付人：**B**　分支：`feature/v2-b-market-data`
> 窗口：请求 `2024-12-01 ~ 2026-09-15`，实际 `2024-12-02 ~ 2026-09-15`（436 行/只）
> 来源：`AKShareStockProvider / stock_zh_a_hist (eastmoney)`，后复权 `qfq`，日线

## 为什么放在仓库里

C 在 PR #10 评审中指出：此前的交付目录 `frozen/c-delivery/` 是本机 Git 忽略目录
（`.gitignore` 的 `/frozen/` 规则），**提交里没有这些文件，C 无法独立校验**；重新运行导出
脚本也不等于取得本批相同文件。

因此本批交付物直接提交进仓库，路径 `docs/evidence/c-delivery/`，C 拉分支即可核对。

## 文件清单（11 个）

| 股票 | 文件 | 行数 | SHA-256 |
|---|---|---|---|
| 600519 | `600519_qfq_raw_20241201_20260915.json` | 436 | `f645ea1dedf76f18d1676412319e35052d203e7ba36b61f9bf16bb5e83a1ed82` |
| 600519 | `600519_qfq_normalized_20241201_20260915.json` | 436 | `75caedb816cd49d6b31f76dc3a398f86be0ac9b639ec43c72b0529c14e57ad7e` |
| 000001 | `000001_qfq_raw_20241201_20260915.json` | 436 | `cf50922b1914cee945357c2cfb118715cc211e49d244a424f7c7b63e2581440e` |
| 000001 | `000001_qfq_normalized_20241201_20260915.json` | 436 | `78189dfa5b8d877b579599803e7d62d2bde42a6cc3185643e67950e71d3cc99a` |
| 300750 | `300750_qfq_raw_20241201_20260915.json` | 436 | `ceb7b86724f1bcfe23b638776b4355b8c961697914898fe88203ebe1a2ac9030` |
| 300750 | `300750_qfq_normalized_20241201_20260915.json` | 436 | `a8c03c0a31c7e635d4902c1ab0bbaad66d945307c23f38613480630780c44b21` |
| — | `600519_metadata.json` / `000001_metadata.json` / `300750_metadata.json` | — | 见 `MANIFEST.json` |
| — | `MANIFEST.json` | — | 逐文件 `sha256` + 抓取时间 |
| — | `mysql_readback.json` | — | 交付文件 vs MySQL 回读比对结果 |

### 两种表示形式（用途不同，请勿混用）

- **`*_raw_*.json`** = provider **原精度**（未做 4/2/6 舍入），用于**来源核验与留档**。
- **`*_normalized_*.json`** = 规范化 **4/2/6** 输入，**就是正式送入 C 的那份行**，
  用于直接计算、API 与 MySQL 一致性验收。

每只文件字段：`stock_code`（六位字符串）、`trade_date`（升序、不重复）、
`open/high/low/close/volume`，另附 `amount/turnover_rate/change_pct`。

## 校验方式

`MANIFEST.json` 是抓取当时生成的原始证据，**未做任何修改**，因此其中每只股票的
`raw.path` / `normalized.path` / `metadata_file.path` 仍写着抓取时的本机路径
`frozen\c-delivery\...`。本次只是把同一批文件**原样搬到仓库内**：文件内容未变，
所以 `sha256` 全部继续有效（已逐文件复核，9/9 一致，行数 436 全部匹配）。

```bash
# 逐文件核对 SHA-256（把 MANIFEST 里的 hash 与实际文件比对）
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

# 交付文件 vs MySQL 回读（需要本机 MySQL）
python scripts/verify_c_delivery_mysql.py
```

## 版本口径

- 文件 SHA-256（本目录）、C 的 `data_hash`、D 的 `context_hash` **分别记录、不混用**；
- 行情进入 C 前由 B 统一精度（4/2/6），**C 返回的结果保存时不再二次舍入**；
- 三方验收必须使用**同一份规范化输入、同一参数与版本**。

## 过程说明（如实）

300750 的扩展窗口此前连续多次撞在上游不可用窗口上（主站 `RemoteDisconnected`、
同源延迟主机返回空），最终由低频重试命中窗口后一次性取齐三只。导出脚本已改为
**以磁盘产物为准**：后续失败轮次不会抹掉早先抓到的文件，`MANIFEST` 只描述真实存在的产物。
