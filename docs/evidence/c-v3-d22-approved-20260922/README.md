# C 对 D22 修复与 rebase 组合的通过结论

日期2026-09-22。**C对PR22的两轮修改请求均已闭环，可批准C审阅范围；最终V3/C4尚未签字。**

## 版本与独立验证

- PR22当前头：`fedeb09d05b9073e30af50b202b94f40ec30d789`。
- 对应生产代码：`6c9ca524eaea8ef0a261c95a6fdc9ce8eda42c6c`。fedeb09仅文档，与该生产提交的backend/tests/scripts/frontend无差异。
- D已rebase到真实main `10283b079f686cb8310bf18125d7992b60979293`，包含B19/B21；db/migrations.py与该main逐字节一致，确认使用B唯一v9来源。
- 隔离目录仅叠加C quant `6a84901c82256b7d48dfab3ebee3208633e5058c`及其测试/脚本/样本，不改D/B生产文件。
- 全量 **746 passed, 1 skipped**，2条依赖弃用warning。skip为C已存在后不运行的缺实现分支，专项探针另强制关闭支持位验证50004。
- 本次虽D只请求复验零资金，但rebase同时引入B19/B21，故对新组合执行全量回归及MA/MACD两类专项，未把旧版本成绩当成新组合成绩。

## 通过项

1. 三股×三组MA：精确保存C结果、原始context数值/类型、15位归一化后的Prompt/POST/保存快照/新SQLite连接GET一致；context_hash独立计算通过，C输入哈希未混用。
2. 四类损坏记录（总收益、回撤、往返数矛盾，以及initial_cash=0.0）：全部HTTP500 / JSON code50002，LLM0、新报告0，上下文服务均抛DatabaseOperationError。零资金已不再抛未捕获除零异常。
3. 完整C MACD保存结果送F4仍422/40007、LLM0，符合首版MA-only范围，不要求扩大功能。
4. 三股×三组MACD：直接C/HTTP POST/重建SQLite连接GET完整结果一致，六参数值/类型一致，历史参数再次POST成功且结果相同。
5. 日期缺失/null与非法参数正确拒绝且取数/落库0；MA默认窗口保持；缺C实现50004正确。

数据为既有腾讯qfq normalized三股样本；各组区间2025-07-04至2026-08-31，283点。`ai-result.json`及`backtest-result.json`分别记录两套矩阵。无实时Provider、真实MySQL、真实LLM或浏览器；使用临时SQLite及固定LLM假件。不能将此记录写成生产库/付费模型/页面全链路验收。

复现：在上述D头叠加C的隔离checkout内执行：

```powershell
python <probe_ai.py绝对路径> <新AI结果json> --with-c-overlay
python <probe_backtest.py绝对路径> <新回测结果json>
```

AI探针本版对四项损坏响应也硬断言，任一不符合50002/LLM0/报告0即失败。

## B最新两条回复处理

- B Issue20 comment5777648317：收到候选组合`7fdaa6c...`及其真实MySQL自测报告。其D输入仍是bf7cd54，故仅作为B所述迁移/历史读取预验，不据此关闭后续D修复或替代最终集成。本次C独立验证的是fedeb09新组合，未声称独立重做B的MySQL检查。
- B PR21 comment5777648565：已从B fork分支获取完整`27f83479d56f965901c1eb86e335a5f213b1d72b`。与已批准0360b699相比确实只改tests/test_f3_detail_contract.py（+29），生产代码无差异。在原B+C隔离目录替换该测试文件，定向 **3 passed**。无需重跑完整生产矩阵，原C批准保持。
- PR21合并时头是0360b699，GitHub已合PR的head仍固定此值；B fork后续27f83479不会因旧PR已合并而自动进入main。若需保留这条测试，B应通过后续PR或交D显式集成，不重新开发。

## 其他成员与剩余范围

- D：原三项数值矛盾、零资金保护、v9去重/rebase均在本轮核对通过；可将验收文档的C审阅待办标为本SHA已通过。A/B独立门禁仍由本人确认。
- A23尚无新修复（仍6daa211），请求/实际区间映射与F3字段清单确认仍待A，不能由C替代。
- C18仍待D审阅/集成，C算法未变。当前批准D22不意味着C18或D22已合并，也不是最终C4签字。
- 本轮PR19/21合并提醒和PR13关闭属于已知事件；没有新增其他C算法开发要求。
