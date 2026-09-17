# C 对 D 冷启动修复的候选复核

2026-09-17，被测 D SHA：`4a7402a35ec1a42a3a6964d9f351395d19315188`。

**既有525项测试、编译与C/AI兼容检查通过；补充日历检查5通过、1失败。发现静态注入日历的refresh回归，已交D处理。当前仍不作最终集成签字。**

## 改动与实际验证

用户给出的846c1cc→4a7402a比较只包含交易日历共享缓存/锁及验收说明更新。相比C上次核对的b480014，本轮还包括846c1cc的逐股票同步锁、持锁复检及数据库快照刷新。C在独立目录下载精确D归档，258份原文件均未修改；未向D源树叠加C或B代码。

| 检查 | C 本轮实际结果 |
|---|---|
| D完整pytest | 525 passed，0 failure/error/skipped |
| compileall backend/scripts | exit 0 |
| C/AI兼容 | 7项通过：SQLite、合成行情、假LLM；包含默认AI与自定义参数隔离、重建连接历史读取、禁止重算 |
| C核心 | 12份Python文件与92df017404126e9af920e1ad82e4a136d813f8d1的Git blob逐字节一致 |
| 默认日历8实例并发加载 | 模拟加载源仅调用1次，全部取得相同日期 |
| 缓存/刷新边界 | 返回副本不污染共享缓存、默认refresh、注入fetch隔离/刷新、首次失败后重试均通过 |
| 静态trade_dates注入后refresh | **失败**；前版846c1cc在同一模拟源下通过 |
| GitHub远程检查 | 0 check-runs、0 commit statuses，综合状态pending；未看到CI通过证据，不解释为已有运行中的任务 |

D报告的真实目录5916行、三股各244行并发K线、真实LLM和MySQL属于D的环境证据，C本轮没有独立重跑这些流程；也没有独立重放846c1cc的真实MySQL并发插入场景。本轮不能替代最终三股九组direct/POST/重建连接MySQL GET。

## 可复现问题：静态注入日历刷新

位置：`backend/app/data/trading_calendar.py:58–60`。当构造时仅传`trade_dates`时，`_fetch`是None，`refresh()`却走到`self._fetch()`，报`TypeError: 'NoneType' object is not callable`。

```python
provider = TradingCalendarProvider(trade_dates=[date(2025, 1, 2)])
provider.refresh()
```

C用同一模拟AKShare加载函数分别执行846c1cc和4a7402a：前版返回重新加载日期且调用加载器1次；新版TypeError且加载器0次。共享缓存的默认实时路径在上述定向检查中通过，暂未发现线上路由会刷新静态注入实例；因此不将此问题描述为实时全流程必然失败。

建议D恢复`fetch is None`时的合法刷新路径并加回归用例，保留本次默认共享缓存/锁。C不修改B/D生产文件。可复现探针见[calendar_probe.py](evidence/c-d4a7402-20260917/calendar_probe.py)，参数`--source`指向未修改的D4a7402a源目录，`--before`指向846c1cc的原始trading_calendar.py，`--output`指定输出JSON。探针用确定性模拟源，**不调用真实AKShare**；当前预期退出1，以显式记录该回归。

## 仍需D集成的交付

- B最新`540a00f604044bd046cd3935f4df9d018063b44b`已修正跨字段校验与完整frame传递说明，关闭此前这两处文字澄清；相对共同祖先e4ef000，D仍缺 **8个B提交**：b7cb06a、dedad609、5404c25、74c74fb、d63aaa0、821f322、a7cfa91、540a00f。建议完整合入B540a00f并保留来源历史。
- D当前树仍缺新腾讯包、真实V1迁移证据/脚本；导出脚本仍没有TencentQfqSource。新包已交付并完成C候选复核，**PR正文/验收文档的“等待B出包”已过期**，应改为D合入并验包，不要求B重复导出相同文件。
- D仍无C工具b2c372ebca1176194880e2eb88ab8b447b218fd8的`--filename-template`，应合入或明确绑定外部验证工具SHA。
- A PR13仍为d7ba01c，前轮“C输入快照哈希”标签协调保持原范围；D合入时保留正确语义。
- D收尾修复/集成及页面/CI后给最终40位SHA与固定批次，C再执行三股三参数完整对象、类型、哈希、订单、曲线及历史零重算/AI隔离复验。本次4a7402a只作候选复核。

[进度看板](C_PROGRESS.md) · [本轮证据](evidence/c-d4a7402-20260917/summary.json) · [日历探针结果](evidence/c-d4a7402-20260917/calendar-probe.json)
