---
name: analysis-report
description: 将投标可行性、证据、评分、台账和合规结果汇总为统一机器 JSON 与人类分析摘要。
---

# analysis-report

输入应来自上游 `bid-feasibility`、`scoring-strategy`、`requirement-ledger` 和
`compliance-review`。本 Skill 只做结构化汇总，不把缺失材料、主观评分或价格评分
推断为已满足或已获得。

输出包含：

- `machine_json`：版本固定的可评测协议对象；
- `human_report`：由机器对象渲染的简短报告。
