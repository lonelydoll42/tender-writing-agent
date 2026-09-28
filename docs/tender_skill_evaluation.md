# 标书流程 Skill 验收测试

## 测试边界

当前版本验收的能力是前五个节点加上受证据约束的投标草案生成：

1. `tender-intake`
2. `tender-decomposition`
3. `bid-feasibility`
4. `scoring-strategy`
5. `evidence-matching`
6. `document-writing`

项目文件登记、企业材料收集、统一 Requirement Ledger、跨文档一致性、报价校验和
合规审核已经注册为 Skill。`document-writing` 当前输出带人工复核标记的 Markdown
草案，不等同于最终可提交文件。

## 六层测试

- 触发测试：验证招标文件分析、资格拆解、评分策略和废标风险进入最小能力
  Skill；普通知识问答不进入标书流程。
- 流程测试：验证 `tender-decomposition` 的结构化结果可以通过 `$state`
  传给 `bid-feasibility` 和 `evidence-matching`。
- 节点测试：分别检查资格、废标、评分项、证据缺口和缺证不通过。
- 质量测试：固定检查硬性条件召回、来源字段、证据状态和可解释原因。
- 异常测试：覆盖缺资质、缺材料、无效/过期材料和明确失败规则。
- 回归测试：固定保留 `TC01` 到 `TC10`。`TC08` 的跨文档冲突和 `TC09` 的报价
  算术校验已经支持；`TC10` 仍需要目录、封装、签章和提交前完整性检查，不能仅
  凭正文草案判定完整标书通过。

## 固定指标

质量评分按 100 分记录：

| 指标 | 权重 |
| --- | ---: |
| 废标项识别完整率 | 20 |
| 资格条件完整率 | 15 |
| 评分项完整率 | 20 |
| 技术需求完整率 | 15 |
| 无虚构信息 | 10 |
| 前后一致性 | 10 |
| 输出结构可用性 | 5 |
| 标书内容质量 | 5 |

当前自动化测试可以直接计算结构化召回、证据安全性、跨文档冲突检测、报价失败
检测和输出结构；扫描件 OCR、排版和完整标书内容质量仍需要真实招标文件基准集。

## 执行命令

```powershell
python -m pytest -q tests/evals -s
python -m scripts.run_tender_eval
python -m scripts.run_benchmark_v2 --output benchmarks/reports/benchmark_v2.json
```

不要只看最终文本。每次改动后应同时记录测试总数、硬性条件召回率、评分项
召回率、缺证误通过数、跨文档冲突数、报价失败数和未支持案例数。

## Benchmark V2 指标

`benchmarks/tender_v2_corpus.json` 使用 JSON 记录隔离场景和期望标签，
`scripts/run_benchmark_v2.py` 只把业务输入交给分析链，报告阶段才读取语料标签。
报告按 case 和指标分别给出分子、分母及 value，不合并成单一总分：

- `hard_requirement_recall`：硬性要求 ID 的召回率。
- `scoring_item_recall`：评分项 ID 的召回率。
- `source_reference_accuracy`：输出来源引用是否来自输入来源集合。
- `evidence_precision` / `evidence_recall`：有效证据覆盖的精确率和召回率。
- `conflict_recall`：标注冲突要求被识别为 `conflict` 的召回率。
- `critical_false_pass`：关键要求被错误判定为 `pass` 的数量。
- `ocr_human_review_precision`：低置信度 OCR 进入 `human_review` 的精确率。

当前 corpus 同时包含 A/B/C/D tender 场景和一个内嵌 OCR 低置信度样例；真实
扫描件、表格版面和更大规模标注集可以继续按相同格式追加。
