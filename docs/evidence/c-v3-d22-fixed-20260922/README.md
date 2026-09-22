# C 复验 D22 数值校验修复

日期2026-09-22。**原三项反例已闭环；新增除法使零初始资金损坏记录的错误响应回归，待D补齐。**

## 被测版本

- D PR22：`7530d0180c32377fc763951e4ece828fc59b63c0`。
- C quant：`6a84901c82256b7d48dfab3ebee3208633e5058c`，在隔离checkout叠加C quant、两份测试、脚本和样本，未改D生产文件。
- 上版对照：D `bf7cd54a7694728e48937ce9d8f54a5ae4a12714` + 同一C quant，用同一探针独立执行。
- 样本：既有三股腾讯qfq normalized，三组MA参数，区间2025-07-04至2026-08-31；细节及源文件SHA-256见result.json。
- 真实HTTP、Repository、文件SQLite、新engine/session，固定LLM假件。无实时Provider、真实MySQL、真实LLM、浏览器；不包含B19/B21/A23，不是最终集成SHA。

## 已通过

- D新版本+C全量 **716 passed**，2条依赖弃用warning。
- 三股九组原始数值/类型、归一化Prompt/POST/数据库快照/新连接历史GET一致；独立context_hash通过，C输入哈希不混用，精确文本未改写。
- 原始三项结果损坏反例：total_return=0.99、max_drawdown=-0.5、trade_count=999（其余对应曲线/订单不变），全部返回 **HTTP500 / code50002 / LLM0 / 新报告0**。旧版同探针仍为200/LLM1/新报告1，证明修复有效。
- C MACD保存记录继续422/40007、LLM0，符合F4首版仅支持MA。

## 新回归：除法前未验证初始资金

仅把合法保存结果的`c_result_text.initial_cash`从200000改为0.0，保留其他字段及输入哈希：

| 版本 | HTTP | 响应 | 上下文服务异常 | LLM / 新报告 |
|---|---|---|---|---|
| 旧bf7cd54 | 500 | JSON code50002 | DatabaseOperationError | 0 / 0 |
| 新7530d01 | 500 | 纯文本 Internal Server Error，无业务code | ZeroDivisionError | 0 / 0 |

新代码`expected_return = final_equity / initial_cash - 1`发生在已有Schema资金检查前，且异常捕获未覆盖ZeroDivisionError。测试是保存记录损坏，不是允许用户提交零资金；正常接口仍应拒绝零资金。

请D在该除法前验证分母为非bool的有限正数（可先复用结构校验），非法值转既定DatabaseOperationError；至少补零资金回归断言，确保HTTP500/JSON50002/LLM0/报告0。无需改C算法、扩大请求允许范围或调用回测。

## 复现与结果判定

从被测D+C checkout运行：

```powershell
python <本目录probe.py绝对路径> <新结果json路径> --with-c-overlay
```

探针读取当前HEAD作为被测D SHA。`result.json`是新版本，`before-result.json`是同探针旧版对照。正常链路有硬断言，损坏案例记录实际值供诊断；**exit0不代表所有错误码正确**，需检查corruption_probes。

## 全部新消息及协同状态

- **D Issue20 comment5776767594**：已确认v9唯一来源PR19、D22撤销重复迁移/重复测试、保留B21策略文档段、40007随D22落地由B核查。C接受这项决定；实现落地与组合验收仍需D/B执行。当前7530d01只含数值修复，不能说迁移去重已完成。
- **D PR22 7530d01**：C本轮已复验，原三项通过，剩上述新回归。
- **B21 0360b699**：未变，C先前703通过/1跳过和APPROVE保持，不要求B重复修复。
- **A23 6daa211**：未变，请求/实际区间映射修复和F3字段确认仍待A执行。
- **A旧PR13关闭**：前轮已知的前端分支整理，无新增C任务。
- 本轮通知中的其他旧V2/计划/评审提醒没有发现新执行请求，不重复开发或发催促；C4仍待最终组合SHA。
