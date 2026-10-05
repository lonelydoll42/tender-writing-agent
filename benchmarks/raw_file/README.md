# 原始文件可靠性评测

本评测检查原始招标/投标材料从文件注册、intake、分解、证据匹配、ledger到合规
门禁的流程，以及少量金额和评分解析边界。它用于暴露遗漏和误放行，不是解析器的
完整性认证。

## 输入与Oracle

`cases.json`列出最小文本fixture。PDF来自
`tests/标书Agent全流程模拟测试包_v1/`，以原始文件注册并走默认runtime；
`13_ground_truth_预期规则与结果.json`仅在运行流程后作为独立oracle读取，不注册、
不传入intake或解析backend。使用的PDF文件、fixture、抽取结果和错误样本均逐项
写入JSON报告。更正公告不自动覆盖原值，只保留双方来源并请求人工复核。

## 运行

```powershell
.venv\Scripts\python.exe scripts\run_raw_file_eval.py
.venv\Scripts\python.exe scripts\run_raw_file_eval.py `
  --output .qiaowenshu\acceptance\raw-file-run.json
.venv\Scripts\python.exe -m pytest `
  tests\test_local_parser_reliability.py `
  tests\test_ocr_ingestion.py `
  tests\evals\test_raw_file_benchmark.py -q `
  --basetemp=.pytest-basetemp-parser
```

默认只向标准输出打印报告；只有显式指定`--output`才写文件。请为每次运行指定新
路径，避免覆盖独立验收或历史报告。Poppler通过命令可用性检测，不以Windows
可执行文件扩展名作为唯一判断。缺少`pdftotext`或`pdfinfo`时，PDF场景为
`not_run`，对应要求遗漏数为`null`，不会把跳过当作零遗漏；缺少`pdftoppm`时，
OCR渲染模拟单独为`not_run`。

## 指标与当前结果

截至2026-10-05，主独立验收报告为
`.qiaowenshu/acceptance/raw-file-final.json`，该文件由验收方生成并保持原样。

| 指标 | 分母 | 结果 | 解释 |
| --- | ---: | ---: | --- |
| 原文约束文本覆盖 | 10条oracle要求 | 4条覆盖，6条遗漏 | 每条要求按必要约束组计分，组内同义项OR、组间AND |
| 金额归一化 | 6个已执行金额样本 | 6正确 | 包括4个原始PDF与2个文本样例，比较精确元值 |
| 评分上限 | 2个评分样例 | 2正确 | 含每份分值与明确总上限 |
| 关键负例误放行 | 7个负例 | 0误放行 | 仅表示这些流程未被门禁放行，不是资格判断准确率 |

约束文本覆盖衡量从源文中抽取必要约束组的文本覆盖，不衡量抽取结果是否已成为
可执行、完整的业务规则。`hard_false_release`按明确负例统计，无法判定的样本单列
为`inconclusive`，不计入已判定分母。ISO27001要求配ISO9001材料的完整runtime
反例中，具体标准不匹配、决策为`human_review`、业务状态为`needs_review`、
`extraction_complete=false`且门禁未通过。

10B保证金原始PDF的交易金额仍解析为`30000`元；第2页明确写明回单金额低于招标
文件要求的`40000`元，因此状态为`invalid`。要求金额不会覆盖或混入实际交易金额。
合同PDF中的135万元、90万元分别按`1350000`元、`900000`元记录。

低置信OCR使用固定文本和置信度`0.61`的模拟backend，仅用于检查来源、告警和复核
状态流转，绝不代表真实OCR识别准确率。复杂PDF的文本覆盖仍有明显遗漏；0/7负例
不抵消这些遗漏，也不证明一般场景资格判断可靠。未认证前不得用于多人生产或自动
通过资格审查。
