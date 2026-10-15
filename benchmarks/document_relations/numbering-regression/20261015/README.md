# Case-12 有限材料编号语义

`contract.md`、`cases.json` 的20例与 `scope-freeze.json` 在实施前冻结。其后另存6例公开审查探针及1例普通清单保留对照；全部是共享环境公开回归，不是未见文件。原有861件受控文件中，856件受保护历史文件不可改动。

本批只在完整肯定原句明确给出范围、逐字一致的两个不同标签、明确列举和“共两项材料均须提交”时确认两个材料项。数字分段标签按字符串保存；非相邻也不补中间项，金额小数不生成材料条件。含糊、冲突及未支持形式保留原文和复核原因。

`check-acceptance.py` 使用真实 Registry → Runtime，独立检查两个原始叶子、直接 AND、明确有向父级及操作符/成员/终止证据。`--product-root` 可指向固定导出，避免工作区并发修改影响归属。语义变异保留有效引用，来源损坏另行统计；该检查器不是冻结的总体评分器。

在导出根目录使用项目依赖，并为输出选择新路径：

```powershell
python benchmarks/document_relations/numbering-regression/20261015/check-acceptance.py `
  --case-file benchmarks/document_relations/numbering-regression/20261015/cases.json `
  --case-file benchmarks/document_relations/numbering-regression/20261015/reviewer-public-probes.json `
  --case-file benchmarks/document_relations/numbering-regression/20261015/reviewer-boundary-probes.json `
  --output NEW-public-checks.json

python -m pytest -q -p no:cacheprovider --junitxml=NEW-tests.xml
python scripts/run_document_relations_eval.py `
  --bundle benchmarks/document_relations/reserved/v2 `
  --output NEW-product-capture.json --main-reviewer-authorized
```

主审基线来自 `c08edec`：861/861导出文件匹配原始Git blob，源码SHA为 `8141956da6314058e73a3c1f64b0f8c058d4fdb5a3c0a1b7068aa1e9e7be45d4`。冻结1.0.3、1.0.4均未映射case-12的两个明确材料项；原图只有一个候选元数据节点。26例全部实际执行，17例符合本批合同、9例未满足，首次输出另存，不把未执行变异记作通过。

最终报告位于 `reports/numbering-followup-20261015/`。`verify-snapshot.py` 检查最终代码的Git字节及历史资产；代码tree不包含随后补充的报告、文档和发布元数据。十四例新采集使用原冻结三版评分API；适配器只比较源码元数据，需另以Git proof证明。脚本退出1可能表示评分仍有失败，需分别查看执行与评分状态。

执行过程中用户新增模型政策：后续修改智能体显式固定 `gpt-6.1-sol / high`，旧实例停止并交接，其既有基线红测原样保留。当前已运行主会话的实际模型不由本报告推定。未见验收 `not_run`；case-07、企业材料判定、通用完整性与生产验收不在本批关闭范围。固定样例分数不能替代生产完整性；`uv.lock` 独立处理。
