# Benchmarks

当前评测分为三层：

- `dev/`：开发样例，答案可见。
- `regression/`：冻结回归与 baseline 记录，每次修改都应通过。
- `challenge/`：Benchmark V3 holdout，开发调参阶段不读取答案。

## Benchmark V2

`tender_v2_corpus.json` 是可版本化的 JSON 语料入口。它把业务场景和 OCR
低置信度样例放在同一份 corpus 中，但不会把 Ground Truth 传给 Skill。

运行：

```powershell
python -m scripts.run_benchmark_v2
python -m scripts.run_benchmark_v2 --output benchmarks/reports/benchmark_v2.json
```

报告按场景和指标分别输出，不计算单一加权总分。当前指标包括：

- `hard_requirement_recall`
- `scoring_item_recall`
- `source_reference_accuracy`
- `evidence_precision`
- `evidence_recall`
- `conflict_recall`
- `critical_false_pass`
- `ocr_human_review_precision`

现有 tender V2 场景复用 `tests/fixtures/tender_v2`，后续可以在 corpus 中增加
新的 `kind: tender_v2` 目录或 `kind: evidence_matching` 内嵌样例。

## Benchmark V3

V3 使用独立的 challenge corpus 和答案文件：

```powershell
python -m scripts.run_benchmark_v3 --output benchmarks/reports/benchmark_v3.json
```

V3 不计算加权总分，重点报告组合规则状态、OCR review recall、hard-negative
false pass、版本冲突和 mutation / variant 通过率。
