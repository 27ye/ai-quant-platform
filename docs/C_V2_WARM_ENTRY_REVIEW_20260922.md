# C：预热脚本完成日边界定向复验

日期：2026-09-22。PR #10 集成头 `b506618e904b8b0edb09b5a06d0110c9392f493a`；B 修复 `a89c2ea5c67eb8a1b64f1ac195e2ef80d4390a1a`。

## 结论

B 新发现有效：当前 D 的 `scripts/warm_market_data.py` 未给服务注入完成日回调，直接运行该入口可能写入当天未收盘日线。C 独立复现；B 的脚本在 D 当前服务实现上通过三个定向场景。修复尚未纳入所核对的 D 集成头，建议 D 收入 B 原提交并公布组合 SHA，再核对实际交付脚本与依赖。C 不代改 B/D 生产代码、不代合并。

这是一项新增的 CLI 入口缺陷，不撤销原固定数据九组/API 路径及两处已修复运行时缺陷的验收。原签字不应被扩写成“所有运维入口均已验证”。收尾清单应增加这一脚本集成项。

## 独立实测

直接执行 Git 中对应版本脚本的 `main()`，保留真实 `StockService`、`MarketDataService`、repository 和迁移；只替换命令行参数、数据库连接（全新 SQLite 内存库）、合成 Provider、合成交易日历和等待。100 个合成工作日截至 2026-09-22，完成日固定为 2026-09-21。合成日历不代表真实交易所日历。

| 场景 | 观察 | 判定 |
|---|---|---|
| D 原脚本，空库 | 写入100行，含09-22未完成日 | 缺陷复现 |
| B 脚本 + D 服务，空库 | 取数上限09-21，落库99行，来源正确 | 通过 |
| B 脚本 + D 服务，完成日未知 | 返回退出码1；Provider调用0、落库0 | 通过 |
| B 脚本 + D 服务，旧库缺09-21但含09-22尾行 | 补齐09-21，整段替换为99行，09-22不再落库，来源更新 | 通过 |

执行源代码基线是 `bcbd559acb67d3435fe7a840f34ad73bbe35bbad`。Git tree 核对证明 b506618 的 backend/frontend/scripts/tests/固定批次与其完全一致，差异仅为 D 验收文档和文档目录内的证据探针。B 脚本从 a89c2ea 原文载入内存，未改写被测生产文件。这是“B 脚本 + D 核心”的本地诊断组合，不能冒称 D 已集成的新 SHA。

本轮未连接真实行情、真实 LLM 或 MySQL，没有修改现有数据库；未重跑未变化的557项及固定九组。B 自报369项与本轮三个通过场景分别记录。兼容检测在尚无完成日能力的旧 B 树上仍保留旧行为，因此“脚本单独存在”不等于旧树也具备完成日保护。

[机器结果及树审计](evidence/c-warm-entry-20260922/result.json) · [可复现探针](evidence/c-warm-entry-20260922/warm_entry_probe.py)

复现：先获取上述 D/B 完整提交，提供生产树为 bcbd559 或 b506618 的干净 D checkout；在安装项目依赖的 Python 下运行：

```text
python warm_entry_probe.py --source <D_CHECKOUT> --git-repo <REPO_WITH_D_AND_B_COMMITS> --output result.json
```

## D 新证据的范围

- [D 三股实时记录](https://github.com/27ye/ai-quant-platform/issues/15#issuecomment-5770339262)：独立 MySQL 8.0.41，三股各257行截至09-21，K线及默认参数回测HTTP200。
- [D 目录记录](https://github.com/27ye/ai-quant-platform/issues/15#issuecomment-5770411682)：显式CLI同步5918条，push2delay兜底；Vite代理搜索三项HTTP200。D 已关闭对应门禁。
- D 文档另记录关 Mock 的冻结浏览器和真实 LLM 流程。这些是 D 的执行证据，C 本轮只读核对，不写成 C 独立实测，也不替代 A 当前页面及用户最终验收。
- [B 原回复](https://github.com/27ye/ai-quant-platform/issues/15#issuecomment-5770400406) 的440行实时库与冻结交付包每股437行用途不同；冻结批次不应随上游恢复而覆盖。

下一步：D 纳入预热入口修复、同步最终契约/PR清单并给出组合SHA；C 按实际差异完成该入口确认。A 页面和用户最终验收继续推进，PR #10 的合并由 D 安排。
