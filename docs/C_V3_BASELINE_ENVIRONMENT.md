# C V3 旧结果基线：环境与验收方法

## 决定

采用 D 提出的方案 (a)：保留原基线，在独立验收环境复现捕获条件。
不重捕获哈希，不放宽容差，不跳过测试，不修改量化算法。
本次测试文件只补注释，函数语义、输入、断言和基线常量均不变。

原捕获记录：`docs/evidence/c-v3-macd-20260922/manifest.json`。

| 项目 | 原捕获环境/基线 |
|---|---|
| 平台 | Windows x64 |
| Python | 3.12.10 |
| pandas | 2.3.3 |
| NumPy | 2.5.3 |
| 冻结代码 | 26f422a6ebd64295a632cee5a92492ed3aacb62c |
| C量化生产代码 | 6a84901c82256b7d48dfab3ebee3208633e5058c |
| 固定输入 | docs/evidence/c-delivery-20260917，三股 normalized |
| 覆盖 | 三股各default pipeline、legacy、三组windowed MA，共15组完整结果 |
| canonical SHA-256 | 7f2cb64ed9d82527978a6f8b088b6249a82d3afa25c4a83adf0132ba99f96095 |

## D 如何运行

在待验收的明确 checkout 根目录操作。使用单独 venv，不覆盖现有 B/D 数据库或运行环境，也不修改公共 requirements。以下 `C:\path\to\Python31210\python.exe` 必须替换为已安装的 **3.12.10** 解释器路径。临时环境放在仓库外一个新的目录中。

```powershell
$capturePython = 'C:\path\to\Python31210\python.exe'
& $capturePython -c "import sys; print(sys.version); assert sys.version_info[:3] == (3, 12, 10)"
if ($LASTEXITCODE -ne 0) { throw '请先选择原捕获版本的解释器' }
$auditEnv = Join-Path $env:TEMP ('c-v3-baseline-' + [guid]::NewGuid().ToString('N'))
& $capturePython -m venv $auditEnv
$auditPython = Join-Path $auditEnv 'Scripts\python.exe'
& $auditPython -m pip install -r backend/requirements-dev.txt 'pandas==2.3.3' 'numpy==2.5.3'
if ($LASTEXITCODE -ne 0) { throw '验收依赖安装失败，不能继续标记通过' }
& $auditPython -c "import sys,platform,pandas,numpy; print(sys.version); print(platform.platform(),platform.machine()); print(pandas.__version__,numpy.__version__); assert pandas.__version__ == '2.3.3' and numpy.__version__ == '2.5.3'"
if ($LASTEXITCODE -ne 0) { throw '验收环境不匹配' }
git rev-parse HEAD
git status --short
& $auditPython -m pytest tests/quant/test_v3_macd.py::test_all_pre_v3_results_equal_captured_main_baseline -q
if ($LASTEXITCODE -ne 0) { throw '保留失败日志和完整输出，不替换哈希' }
```

单例成功后，D用同一解释器对包含C18的组合运行 `-m pytest tests -q`，并记录退出码、结果、40位SHA、工作树状态与依赖版本。其他DB/LLM测试遵循项目的独立测试环境规则，不指向生产库。
安装命令仅锁定本次已协调的数值环境，不宣称完整依赖树的可复现性；验收记录应另外保存 `pip freeze`。

若相同版本仍不匹配，保留双方完整canonical JSON，逐字段检查数值、类型和运行平台/可选数值加速依赖；不自动改基线或容差。

## 同环境对照证据与边界

- C在原捕获环境对26f422a与C head导出15组完整结果：均为2458986字节，均为7f2cb64e完整哈希，原守卫通过。
- C在Python3.12.10/pandas2.2.3/NumPy1.26.4的隔离环境下，两版也均为7f2cb64e；这只作为诊断，不替换指定捕获环境。
- [D的同环境对照](https://github.com/27ye/ai-quant-platform/pull/18#issuecomment-5779155847)：Python3.12.7/pandas2.2.2/NumPy1.26.4，两版字节一致，均为bc6783a244076997163273664a88e4631ed34e008344e6c891bd37507c2b3a02，D报告长度2458502字符。此结果证明D环境中的失败也发生于旧版，不是C接线带来的旧结果回归；未以字符数冒充UTF-8字节数。
- [B的独立对照](https://github.com/27ye/ai-quant-platform/pull/18#issuecomment-5779133744)：Python3.14.2/pandas2.3.3/NumPy2.5.2，两树15/15组一致且总哈希为7f2cb64e，守卫通过。属于B的证据，不冒称C本轮执行。

这些结果支持环境相关的字节差异；尚未通过跨环境JSON叶子比较把原因限定为某一具体库/序列化函数。
代码回归疑点已由同环境对照排除，D指定环境中的组合全量结果仍需实际执行。
#22转Ready/合并由D负责，A页面/B真实DB/最终C4验收仍需绑定各自实际被测版本。

## 本次落地验证（2026-09-22）

起点为C分支e7badfc5f70943514d159b47b3040dcc70badfb8，只增加本次注释与文档：

- Windows/Python3.12.10/pandas2.3.3/NumPy2.5.3，原基线单例 **1 passed in 2.25s**。
- 以Python `ast.dump(ast.parse(...))` 比较修改前后的完整测试文件，结果完全一致：注释没有改变测试执行逻辑。
- `git diff --exit-code 6a84901 -- backend/app/quant` 为0：量化生产代码无变化。
- 未重跑未变化的全量套件，未修改公共依赖文件，未声称D端指定环境或最终组合已经通过。
