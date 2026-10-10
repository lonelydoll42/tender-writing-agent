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

## 文档关系状态回归

冻结输入及oracle位于[`document_relations/README.md`](document_relations/README.md)。
v2是规范输入，v1作为`rejected-annotated-container`历史保留。两版冻结件与评分报告均按原始字节发布；14例现为public regression，不是unseen holdout，也不是certified blind。所有输入均为合成TXT，非真实业务PDF。

首次有效产品评分为`0/14 passed`、`14 failed`、`0 not_run`；业务材料`not_run/14`。来源locator与裁剪char bounds不一致按实际产品错误保留，未放宽校验。产品结果和source proof见`document_relations/reports/first-valid/`，初始无效grader报告另存于`document_relations/reports/initial-invalid-evaluator/`。完整范围、typed-parent grader契约勘误和复现入口见[`docs/document_relations_acceptance.md`](../docs/document_relations_acceptance.md)。

主审R4最终canonical在源码树SHA-256 `c96529dc1fbf531aaac92e46f0e259ea24b2d64625f50fdd2d4fe981d41f485f`上由grader `1.0.3`评分：`8/14 passed`、`6 failed`、`0 not_run`；R3同一产品源码在operator布局契约修正前为`7/14`。7到8的差异来自grader契约兼容修正，不是产品提升。最终报告、source proof与所有SHA见[`document_relations/reports/final-20261010/`](document_relations/reports/final-20261010/)及publication record。source proof验证65/65产品源码blob、9/9评测器/测试blob；canonical测试为679 passed、1条既有Starlette警告，Ruff通过。

本批基础关系状态与有限显式AND/OR可按限定范围关闭，不关闭Step 2整体、通用/生产完整性或企业业务验收；企业材料`not_run/14`。6个失败例为case-03、07、09、11、12、13，待处理主题和指标见完整验收文档。其余已发布的结构、旧公开原始文件、raw-file及reliability结果均为各自固定评测范围，不外推为生产准确率。

## Benchmark V3

V3 使用独立的 challenge corpus 和答案文件：

```powershell
python -m scripts.run_benchmark_v3 --output benchmarks/reports/benchmark_v3.json
```

V3 不计算加权总分，重点报告组合规则状态、OCR review recall、hard-negative
false pass、版本冲突和 mutation / variant 通过率。
