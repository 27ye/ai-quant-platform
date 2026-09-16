# C V2 交付与验收入口（2026-09-16）

本说明用于把 C 已有实现交给 B/D，并接续三股票验收。包内完整 Git SHA、文件哈希、实际测试结果和未验证项以交付包根目录的 manifest.json 为准。较早的协调记录保留当时状态，不用它们推断当前实现已推送或整个 V2 已验收。

## 当前公开交付入口（2026-09-16 更新）

按 [COLLABORATION.md 第 6 节](COLLABORATION.md#6-git-分支与协作流程统一规则) 的 `feature/<模块>-<功能>` 规则，以及 [V2_DEVELOPMENT_PLAN.md](V2_DEVELOPMENT_PLAN.md) 第 7 节明确列出的 C 名称，正式交付分支统一为 **`feature/v2-c-backtest-params`**。旧 `codex/v2-c-backtest-params` 已重命名，不再用作交付入口。

- 仓库及分支：[pop17589822299-coder/ai-quant-platform](https://github.com/pop17589822299-coder/ai-quant-platform/tree/feature/v2-c-backtest-params)。
- C 实现提交：`92df017404126e9af920e1ad82e4a136d813f8d1`；算法核心保持此版本。
- 组合复核证据提交：`f114a3816105727630ea3b1b5acb52a63ebf3f8b`，仅增加 7 份文档/JSON。
- 最新状态：[C 项目进度看板](C_PROGRESS.md)；最新搜索复验：[C_V2_B25C_REVIEW_20260916.md](C_V2_B25C_REVIEW_20260916.md)；前轮 MySQL / A 状态复验：[C_V2_FOLLOWUP_REVIEW_20260916.md](C_V2_FOLLOWUP_REVIEW_20260916.md)。B9a1 原两项、A0108410 状态/标签、B25c 搜索边界均已在对应版本通过，A 消息映射与 D 新组合验收仍待完成。
- [C_V2_COMBINED_15315_REVIEW_20260916.md](C_V2_COMBINED_15315_REVIEW_20260916.md) 保留旧组合的历史发现，不再作为最新分支未修清单。后续 C 进展按看板中的约定同轮同步 GitHub。

```bash
git fetch https://github.com/pop17589822299-coder/ai-quant-platform.git feature/v2-c-backtest-params
git rev-parse FETCH_HEAD
git show FETCH_HEAD:backend/app/quant/windowed_backtest.py
```

下文有关本地打包/早期接线的内容保留为历史交付过程，当前是否已发布及验收状态以上述公开入口与最新复核报告为准。

## 1. 交付边界

交付包括 C 的量化核心变更、C 测试、离线校验脚本、字段契约与 JSON 样例。没有修改 A 前端、B 的 HTTP/数据库/行情代码或 D 的 AI 代码。测试中的合成数据始终单列，不冒充 B 的三股真实样本。

原 C 工作目录使用的 Git 对象库引用旧目录，读对象时出现索引警告。本次使用独立克隆的同一基底 8062599b3d85c421f00714de9d27a9fbe11ad083 整理交付提交，逐文件比对 C 源码；原工作目录保持不变。最终可复现提交在交付包 Git bundle 中，是否已推送远端另行记录。

包中的 patch 供逐文件评审，Git bundle 供接收方获取准确提交。两者都不自动推送、合并或修改接收方工作目录。补丁应用检查只证明补丁能应用，不证明 B/C/D 接口已经兼容。

## 2. B 接入入口

```python
from backend.app.quant import (
    PARAMETERS_UNSET,
    resolve_backtest_request,
    validate_backtest_window,
    run_backtest_request,
)

# raw_parameters 必须保留缺省与显式 {} 的差别；只允许五个请求字段。
request = resolve_backtest_request(raw_parameters)
if request.semantics_version == "v2_windowed":
    start, end = validate_backtest_window(start, end)
    required_warmup_rows = request.required_warmup_rows

# B 在校验后取得包含预热的规范化 DataFrame；由 C 统一选窗。
result = run_backtest_request(
    normalized_dataframe, start_date=start, end_date=end,
    parameters=raw_parameters,
)
```

这是接线说明，不是新增 HTTP 路由。五个字段为 ma_short_period、ma_long_period、initial_cash、transaction_cost、slippage；不能传整个 QuantConfig。显式 V2 缺少 C 入口时明确失败，不回退旧算法并标成 V2。

保留 C 返回的完整 effective_parameters、semantics_version、algorithm_version、warmup、initial_equity、execution_assumptions、input_snapshot 和 data_hash，不覆盖基准口径。B 原样保存完整结果快照，历史 GET 读取保存结果；摘要列不替代完整快照。

完整约定见 [C_V2_BACKTEST_CONTRACT.md](C_V2_BACKTEST_CONTRACT.md) 和 [C_V2_FRONTEND_CONTRACT.md](C_V2_FRONTEND_CONTRACT.md)。当前 C 入口不返回技术指标逐日序列，默认指标、评分和 AI 仍为独立分析链路。

## 3. 三股固定区间验收

可信文件哈希来自 [B 的 2026-09-16 交付评论](https://github.com/27ye/ai-quant-platform/pull/10#issuecomment-5689910575)，保存在 [C_V2_B_DELIVERY_HASHES_20260916.json](examples/C_V2_B_DELIVERY_HASHES_20260916.json)。该文件记录 B 公布的哈希，不表示 C 已收到数据。

请 B 提供实际可读取的数据包。不要用重新抓取或本地其他股票样本代替声明交付的这六份文件。脚本自动核对三份 normalized 的已知哈希；raw 与 metadata/MANIFEST/mysql_readback 的完整交付及来源核验另行记录。

在包含本次 C 实现的项目根运行（使用项目已有 Python 环境）：

```powershell
python scripts/validate_v2_c_acceptance.py --delivery-dir "B数据包解压目录" --expected-hashes docs/examples/C_V2_B_DELIVERY_HASHES_20260916.json --output-dir "../c-three-stock-evidence-20260916" --start-date 2025-07-04 --end-date 2026-08-31 --data-mode input_json
```

输出目录必须不存在。缺文件、哈希不符、错股票、日期乱序/重复或有效预热不足时失败，不补取或生成替代数据。开始日前至少 120 条是交付数据集覆盖要求；每次 C 计算只使用该请求 long 条预热。

三只股票为 600519、000001、300750；固定窗口均为 2025-07-04 至 2026-08-31：

| case | parameters |
|---|---|
| default | `{}` |
| ma10-30 | `{"ma_short_period":10,"ma_long_period":30}` |
| ma20-60-cost | `{"ma_short_period":20,"ma_long_period":60,"initial_cash":200000,"transaction_cost":0.002,"slippage":0.001}` |

九组请求另见 [C_V2_ACCEPTANCE_REQUESTS.json](examples/C_V2_ACCEPTANCE_REQUESTS.json)。每组导出 `{code}-{case}.request.json` 和 `.result.json`，并在 report.json 记录实际区间、预热、订单/往返数、曲线点数及输入哈希。完整保存后读取并复算，必须逐字段一致。

`data_mode=input_json` 仅说明此次离线输入方式，不是 provider 来源。与正式 API 的 C 输入比较时，必须使用 B 实际传入的同一属性及相同规范化列；不能为了让哈希一致而篡改真实来源。包内元信息缺失时应说明，不猜测。

## 4. 通过范围与真实联调

离线脚本通过，只能证明文件匹配、C 固定窗口计算及 JSON 回读复算。接下来还必须：

1. B 使用同一输入、日期、参数和 C 版本调用正式 API，保存真实 backtest_id。
2. C 比较直接结果、POST 和历史详情的完整字段，特别是快照、精度、实际配置、三条曲线和成交记录。
3. 在真实 MySQL 保存/重启后回读，证明历史 GET 不取数、不重算；D 的 AI 历史 GET 不重新调用 LLM。
4. A 的请求指向约定服务，运行版本与组合 SHA 对应，再做三股浏览器流程。

当前 B 接线的已知问题与证据见 [C_V2_AB_COORDINATION_20260916.md](C_V2_AB_COORDINATION_20260916.md)。交付包附加的 HTTP 冒烟证据使用合成数据和临时 SQLite，与真实 MySQL 验收分开。

验收结论仍需 D 指定最终组合 SHA。旧冻结 R2 的 33 分、24 条订单、12 次往返、403 点用于 V1 回归，不强制 V2 新窗口也产生这些数量。
