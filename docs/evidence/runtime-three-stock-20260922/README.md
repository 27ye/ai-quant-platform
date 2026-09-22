# 运行时三股实时 K 线门禁关闭证据（2026-09-22）

## 背景

2026-09-22 晨间探针中 300750 因腾讯兜底数据止于 2026-09-18、未覆盖最近已完成交易日
（2026-09-21），被 `fe8c0b4` 完整性契约按预期拒绝为 HTTP 502／`50001`。2026-09-22
10:18（Asia/Shanghai）复核：东财 `push2his` K 线端点恢复 HTTP 200，腾讯 `sz300750`
qfq 数据亦已补齐至 2026-09-21（257 行）。随后在当前候选上重跑三股门禁探针。

## 运行环境

- 代码 head：`851146e6a810a37f728a233a839ccd617aa4ee77`（生产代码仍为
  `bcbd559acb67d3435fe7a840f34ad73bbe35bbad`，本轮**无任何代码改动**）
- 隔离 MySQL 8.0.41（`127.0.0.1:3308`），验收库
  `ai_quant_v1_acceptance_20260922_102045_live3`，迁移 schema v0→v8
- 探针窗口：K 线 2025-09-01～2026-09-21；回测固定窗口 2025-07-04～2026-08-31，
  默认参数（`parameters: {}`）

## 复现步骤

```powershell
# 环境变量指向 3308 验收实例（.tmp/acceptance_browser.env，不入库）
$env:MYSQL_DATABASE = 'ai_quant_v1_acceptance_20260922_102045_live3'
$env:PYTHONPATH = '.'
.\.venv\Scripts\python.exe scripts\migrate_db.py
.\.venv\Scripts\python.exe docs\evidence\runtime-three-stock-20260922\probe.py
```

`probe.py` 与原始运行同源（`.tmp` 副本固化入库），仅输出路径为相对
`.tmp/live-three-stock-851146e.json`；结果文件已原样保存为本目录的
`live-three-stock-851146e.json`。

## 结果摘要

| 检查项 | 600519 | 000001 | 300750 |
|---|---|---|---|
| K 线 HTTP / code | 200 / 0 | 200 / 0 | 200 / 0 |
| 行数 | 257 | 257 | 257 |
| 覆盖区间 | 2025-09-01～2026-09-21 | 同左 | 同左 |
| 实际来源 | `akshare.stock_zh_a_hist` | 同左 | 同左 |
| coverage / freshness | known / fresh | 同左 | 同左 |
| 固定窗口默认回测 | 200 | 200 | 200 |

- 三股全部通过最近已完成交易日（2026-09-21）完整性门禁；主源（东财）恢复后
  未触发腾讯兜底，来源标记为东财，无混源。
- 股票目录（搜索）在全新隔离库上仍返回 HTTP 503／`50006`（stock catalog not
  synced）：东财目录端点 `push2.eastmoney.com` clist 直连仍 TLS 握手超时（12s），
  上游目录集群未恢复。该门禁保持开启，不以部分数据宣称通过。
- 上游直连复核（同日 10:18）：`push2his` kline HTTP 200；`push2delay` HTTP 200
  （9.97s）；`push2` clist 握手超时。

## 结论

「300750 完整实时数据」门禁**关闭**。V2 剩余门禁收敛为：上游目录恢复（搜索
50006）以及 A 对当前 V2 页面与用户最终流程的复验。PR #10 继续保持 Draft。
