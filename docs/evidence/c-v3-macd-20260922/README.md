# C V3 MACD 模块验收（2026-09-22）

**结论：C1/C2 已实现并通过模块验收；C3 数值契约及 MA/MACD 示例已交付；C4 离线三股三参数通过，最终接口/持久化/AI/页面联调待集成 SHA。**

被测代码提交：`6a84901c82256b7d48dfab3ebee3208633e5058c`。基线 main：`26f422a6ebd64295a632cee5a92492ed3aacb62c`。之后仅添加本文、进度及生成的证据，不能把文档提交当作新代码验收。
执行环境 Windows / Python3.12.10 / pandas2.3.3 / numpy2.5.3；Python3.9仅检查语法，未在3.9解释器上执行。未增加依赖。

## 实际检查

| 命令 / 检查 | 实际结果 |
|---|---|
| `python -m pytest tests -q` | **677 passed**，31.96秒；2项依赖弃用警告，无失败 |
| `python -m compileall -q backend scripts` | exit 0 |
| `python scripts/validate_quant_core.py` | exit 0；默认合成样本，不是真实行情 |
| `python scripts/validate_c_ai_history_compatibility.py --output-dir <新目录>` | exit 0，7项检查通过；SQLite / 模拟LLM / 合成行情，仅旧默认AI兼容 |
| `npm --prefix frontend run typecheck` | exit 0 |
| `npm --prefix frontend run build` | exit 0；已有大于500kB打包提示；不等同页面验收 |
| Python3.9 AST语法检查 | C模块、新测试及导出器共15文件通过 |
| `git diff upstream/main...HEAD --check` | exit 0；upstream 为项目官方27ye仓库 |
| `git diff origin/main...HEAD --check` | exit 2，个人fork旧main比较包含基线已有的两个B测试EOF空行，见下方说明 |
| `python scripts/validate_v3_macd.py --output-dir docs/evidence/c-v3-macd-20260922` | exit 0；6份输入文件哈希一致，9份MACD+1份MA完整重放一致 |

`origin/main` 指向个人 fork 的旧基线。对未修改的官方基线执行 `git diff origin/main...26f422a6ebd64295a632cee5a92492ed3aacb62c --check` 也得到完全相同两条：`tests/test_akshare_provider_news.py:102` 与 `tests/test_provider_retry.py:535` 的 new blank line at EOF。C 未改这两个B文件，也未擅自更新fork main。C PR实际新增差异对官方 main 无空白问题。

新增117项测试覆盖：策略与省略/null矩阵、严格周期/资金参数、窗口前验证、默认及最大239条预热、独立Fraction递推、手算交易费用、首日预热信号、末日不提前执行/不强平、相等/无交易、未来数据隔离、快照哈希与重放、并发请求隔离、旧MA/评分完整指纹，以及证据篡改拒绝与不覆盖历史证据。没有删除旧测试。

## 固定包验收结果

输入使用 `docs/evidence/c-delivery-20260917/` 三股各437行 normalized，原包raw/normalized共6份的SHA-256均先验证。来源是腾讯qfq交付备用批次，4/2/6精度，不是实时东财；成交额和换手率为空，change_pct为派生值。
回测窗口：2025-07-04—2026-08-31。每组权益/基准/回撤曲线各283点；每份完整结果包含实际使用预热+窗口的输入快照及哈希。

| 股票 | fast/slow/signal | 预热 | 订单 | 往返 | 区间收益率 |
|---|---|---:|---:|---:|---:|
| 600519 | 12/26/9 | 34 | 28 | 14 | −17.0739% |
| 600519 | 6/13/5 | 17 | 45 | 22 | −10.1035% |
| 600519 | 20/40/12 | 51 | 16 | 8 | −7.3554% |
| 000001 | 12/26/9 | 34 | 25 | 12 | −0.3160% |
| 000001 | 6/13/5 | 17 | 37 | 18 | 7.8384% |
| 000001 | 20/40/12 | 51 | 21 | 10 | −3.1862% |
| 300750 | 12/26/9 | 34 | 26 | 13 | 23.1759% |
| 300750 | 6/13/5 | 17 | 46 | 23 | −10.6307% |
| 300750 | 20/40/12 | 51 | 12 | 6 | 32.3298% |

前两组初资100000、成本0.001、滑点0；第三组初资200000、成本0.002、滑点0.001。显示收益率在此四舍五入，机器JSON保留完整精度；没有挑选最好结果或优化收益。本次验证确定性、单位、时序和记账，不证明真实交易盈利或策略优于基准。

旧版本兼容：改动前在官方main捕获三股 **3份默认pipeline + 3份legacy + 9份MA窗口回测** 的完整JSON，改动后逐字段/类型保持一致；合并canonical指纹 `7f2cb64ed9d82527978a6f8b088b6249a82d3afa25c4a83adf0132ba99f96095` 已固定在回归测试。

## 复核入口

- `manifest.json`：代码SHA、运行环境、输入和结果文件SHA、每组计数、未验证项。
- `*_default.json`、两组自定义命名JSON：9份完整MACD结果，包含订单、三曲线、实际输入。
- `ma_default.json`：供F3/F4对接参考的MA原结果。
- `macd_numeric_example.json` / `ma_numeric_example.json`：仅供口径复核的字段投影，不是已保存报告或D的最终AI上下文；无伪造数据库ID/来源时间，quant_score为null。

```powershell
python scripts/validate_v3_macd.py --verify docs/evidence/c-v3-macd-20260922
# 新执行必须用新目录，不覆盖本批：
python scripts/validate_v3_macd.py --output-dir .tmp/c-v3-new-run
```

导出与重放全程禁止网络连接；不读取.env，不访问数据库或LLM。生产来源/输入哈希与C结果哈希含义分开，MA和MACD初值不可混用。

## 等待联调的明确事项

- B：按C契约透传strategy、省略与null，取足预热；提供接口/保存实现SHA，C再比对直接结果→POST→新连接MySQL GET；历史零重算。
- D：给出F4上下文/归一化实现SHA及字段契约，C复核同一保存快照的数字、null、输入hash与context_hash边界；真实LLM和调用隔离仍由D证据支持。
- A：对照与MACD表单接入B字段，正确显示缺失、比例、订单/往返、参数及窗口差异；页面验收由A/D执行。
- 最终组合发生生产代码变化后需按最终SHA复验，当前不能签为V3整站完成。C没有合并任何PR或改其他成员生产代码。
