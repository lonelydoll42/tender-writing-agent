# Benchmark V3 Challenge

这是 holdout challenge set。`tender_v3_cases.json` 只包含业务输入，
`tender_v3_answers.json` 是独立答案文件。开发阶段只运行不带答案的输入 smoke test：

```powershell
python -m scripts.run_benchmark_v3 --blind
```

版本节点才使用答案文件进行正式评测。

运行正式评测：

```powershell
python -m scripts.run_benchmark_v3 --output benchmarks/reports/benchmark_v3.json
```

重点覆盖：

- ISO27001 / ISO9001 hard negative 与过期证书
- 日期、金额、项目类别、数量、合同和验收的组合条件
- OCR human-review precision、recall 与 critical false pass
- 补遗导致的金额、日期变化
- 无明确版本优先级的证据冲突
- 原始输入与 mutation 的结论差分
