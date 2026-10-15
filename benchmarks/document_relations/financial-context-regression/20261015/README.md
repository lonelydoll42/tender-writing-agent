# Case-13 有限财务上下文回归

本批开发与主审共享环境，新增文件全部为公开回归，不宣称未见。合同、十五例与修改范围在开发前冻结；随后新增六例公开探针及一个远距离同名指标边界例。22例含5个确认正例、17个人工复核例。`contract.md` 是本批语义合同，`scope-freeze.json` 记录基线824件受控文件及其中819件不可改动资产。

`check-acceptance.py` 调用真实 Registry → Runtime，独立检查三个原子、原有 AND、非逻辑 scope 的直接成员、A3 → A2 的有向归属、唯一ID、双端来源和复核状态。23个语义变异以实际正例输出为基础，保留有效引用；两个来源变异另行统计。它不是被冻结的总体评分器。`verify-snapshot.py` 复用原样字节核验器，另核对本批96个代码文件及819件历史资产。

主审最终源码tree为 `4e330214cea8ff81195b347125d1d361239c70ae`，已导出832个Git文件。全部代码在最终提交继续保持相同blob，后补报告/文档/元数据不属于该代码tree。可导出该tree后，在导出根目录使用项目依赖执行以下命令，输出必须使用新路径：

```powershell
python benchmarks/document_relations/financial-context-regression/20261015/check-acceptance.py `
  --case-file benchmarks/document_relations/financial-context-regression/20261015/cases.json `
  --case-file benchmarks/document_relations/financial-context-regression/20261015/reviewer-public-probes.json `
  --case-file benchmarks/document_relations/financial-context-regression/20261015/reviewer-boundary-probes.json `
  --output NEW-public-checks.json

python -m pytest -q -p no:cacheprovider --junitxml=NEW-tests.xml
python scripts/run_document_relations_eval.py `
  --bundle benchmarks/document_relations/reserved/v2 `
  --output NEW-product-capture.json --main-reviewer-authorized
```

十四例采集退出1表示仍有评分失败，不能据此认定未执行。三版重评使用原 `scripts/run_document_relations_snapshot_rescore.py`：先独立核对capture的源码SHA与Git proof，再传入capture文件SHA、已证明的源码SHA和新输出路径；适配器本身只验证元数据，不证明Git归属。`--mapping-report` 可对已保存捕获核对case-13原子映射。

最终主审报告在 `reports/financial-context-followup-20261015/reviewer/`：`canonical-actual-public-22.json`、`canonical-existing-public-33.json`、`product-v2-capture-1.0.3.json`、`canonical-three-view-scores.json`、`pytest-canonical-final.xml`、`final-code-proof.json`。`baseline-*` 保留修复前结果；`working-iteration*` 仅是工作区诊断，没有固定源码归属证明。两次采集的文档ID不同，原文输入不变；跨版本评分比较见 `baseline-to-product-comparison.json`，身份说明见 `comparison-identity-note.json`。

有限句式不覆盖通用财务、跨页/跨段上下文、主体/时间推断或企业材料满足判断。未见验收 `not_run`，旧公开原始文件0/8、企业材料未运行、通用完整性与生产验收未通过的边界继续保留。`uv.lock` 未在本批发布。
