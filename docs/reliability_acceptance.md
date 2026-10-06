# 复审整改限定验收

## 结论

**撤回此前任何“可靠性专项全部通过”的笼统结论。** 测试通过只能说明固定测试输入满足既有断言，不能证明真实招标文件解析完整、自然语言事实核验通用或企业生产流程可靠。

本轮只验证独立复审提出的特定写作核验和 Runtime 范围门禁反例，并加入确定有效的正例衡量误阻断。它不是通用事实核验、文件解析、模型或 OCR 认证，也不构成生产验收。

## 本轮范围

| 领域 | 正例 | 负例 | 关键断言 |
| --- | ---: | ---: | --- |
| 写作独立核验 | 6 | 12 | 认证标准、证据主体、主体标识、中文项目数量/金额归属、招标要求复述及良性章节 |
| Runtime 审查范围 | 2 | 7 | 跨项目、要求内容变化、requirement/scoring 同 ID 歧义、文件版本变化、范围扩张、伪造审批、无效写作范围，以及准确范围和安全子集 |

新增 Runtime 负例 `R-NEG-REQUIREMENT-SCORING-ID-COLLISION` 固定复现：review
requirements 含 `requirement_id=SAME`；`scoring_items` 含内容不同、`max_score=100`
的 `item_id=SAME`；ledger 仅有 `SAME` 且 `item_type=requirement` 的 matched 项；
review 与 writer 输入范围相同。该评分项未被单独核验，因此 oracle 要求 writer
调用数为 0，拒绝原因固定为 `requirement_scoring_id_collision`；该用例仍计为确定
负例，不得改标 `needs_review` 来移出负例分母。

新增 Runtime 负例 `R-NEG-INVALID-WRITING-SCOPE` 使用同项目、同版本、已匹配的 `R-A` 要求和 `S-A` 评分项，以及 `technical` / `commercial` 两个章节；review 与 writer 都只把 `writing_scope` 设为 `["does-not-match"]`。oracle 要求 review binding 为 `not_bound`、writer/model 调用均为 0，并要求拒绝原因包含 `writing_scope_unresolvable`。这不是跨项目或版本变化用例。

写作负例包括 ISO9001 证书号 `CN27001-2026` 冒充 ISO/IEC 27001、CMMI 3 证书正文/元数据被误认为可支持 CMMI 5（等级不匹配，不作为编号碰撞证据）、CMMI 5 标准与正文却凭证书号 `CN-CMMI-3-2026` 支持 CMMI 3（实际编号碰撞）、ISO 元数据与正文标准冲突、持证主体来源冲突、同名但统一社会信用代码不一致，以及无证据的“三十项大型政务项目”声明。新增两个主体归属负例：甲公司草稿声称“我司累计承接三十项大型政务项目”或“我司历史项目合同金额135万元”，唯一材料分别在正文明确归属乙公司；材料只有有效状态元数据，没有 `owner_name`。对应有效正例保留相同135万元声明、有效期和来源形状，仅材料标题与正文明确归属改为甲公司。正例还包括标准和主体标识一致的有效 ISO 证书、证书编号同样含 `CMMI-3` 但标准/正文/主体确为 CMMI 3 的有效正例、有证据支持的中文项目数量、正确复述招标要求，以及不含高风险企业事实的一般章节。

输入 fixture 与固定 oracle 分开存储。runner 先执行所有样本，再读取 oracle；oracle 不注册为文件，也不传入 Runtime、Skill 或模拟 LLM。模拟 LLM 仅返回每例预设的被测草稿，不能证明真实模型准确率。本轮不调用真实模型或 OCR。

## 指标解释

- `correct_pass_rate`：确定有效正例中被正确判为 `business_status=passed` 的比例。
- `false_block_rate`：确定有效正例中被阻断、判为 `needs_review`、`failed` 或 `not_checked` 的比例；这些情况保留在正例分母中。
- `false_release_rate` / `false_release_count`：负例中被错误判为通过的比例和数量。Runtime 只要实际调用写作 Skill，即计为负例误放行，不因最终运行状态为 `needs_review` 而豁免。
- 各率分母使用固定 oracle 中相应极性的全部样本；`not_run` 与 `inconclusive` 另外报告，同时不会从分母剔除。
- Runtime 记录模型调用数、写作 Skill 实际调用数及服务返回的 scope 拒绝原因。写作报告读取 `claim_verification.coverage`；字段缺失必须标为 `not_reported`，不得解释为覆盖完整。

本轮逐例结果及分母由 runner 生成；只有在测试实际运行后，才应把结果写入新的显式 `--output` 路径。不得覆盖既有验收报告。

## 本轮限定冻结结果

主验收已对当前 27 个固定样本完成独立冻结重跑，报告为
`.qiaowenshu/acceptance/reliability-followup-final-2.json`。这只是列明反例与正例的
限定验收，不代表通用事实核验、解析完整性或生产可靠性认证。

| 领域（样本数） | 正例正确通过 | 正例误阻断 | 负例误放行 | `not_run` / `inconclusive` | 模型调用 / writer 调用 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 写作（18：6 正 / 12 负） | 6/6（100%） | 0/6（0%） | 0/12（0%） | 0 / 0 | 18 / 18 |
| Runtime（9：2 正 / 7 负） | 2/2（100%） | 0/2（0%） | 0/7（0%） | 0 / 0 | 2 / 2 |

Runtime 七个负例均未调用 writer 或模型；两个正例各调用 writer 和模型一次。
主验收全量测试为 `332 passed`，伴随 1 条既有 Starlette 弃用告警；Ruff 和
`git diff --check` 通过。全量测试包含
`tests/evals/test_raw_file_benchmark.py`，该测试调用 `run_raw_file_eval`。27 样本
followup 本身使用模拟模型，未调用真实模型或 OCR，也不处理 PDF。

主验收另行验证了主体与范围边界：同名企业但平铺登记码冲突、正文主体登记码不一致
会要求复核；登记码一致的正例通过。非法、混合未知项和非法类型的 scope 均在独立
模型调用前拒绝，合法默认范围和章节 ID 仍可通过。这些额外 probe 不计入上述 27 例
比率。

自然语言数量与金额声明扫描仅覆盖当前实现的有限模式和提取规则。扫描覆盖状态只说明
扫描器报告了什么，不能证明对同义改写、复杂表达或其他未识别表述已穷尽核验。

## 历史快照

`.qiaowenshu/acceptance/reliability-followup-final.json` 保留先前 23 个固定样本的
结果（写作 5 正/10 负、Runtime 2 正/6 负），不代表当前 27 例集合。先前该次全量
测试记录为 `294 passed` 和 1 条既有 Starlette 弃用告警。

`.qiaowenshu/acceptance/reliability-followup-expanded-before-fix.json` 保留新增案例
整改前的复现结果：两条跨主体写作负例及一条无效 scope Runtime 负例共 3 次误放行。
这份报告用于记录已复现缺陷，不是整改后的验收结果；上述历史报告均未覆盖或改写。

## 原始文件回归补测

主验收全量测试包含原文件评测测试；此外，原文件评测被单独运行并保存为
`.qiaowenshu/acceptance/raw-file-followup-acceptance.json`。报告状态为
`completed`，Poppler 可用，结果如下：

| 指标 | 结果 | 本轮处理 |
| --- | ---: | --- |
| 招标约束文本覆盖 | 4/10，遗漏 6 项 | 本轮独立原文件回归实测；6 项遗漏仍未修复、未验收通过 |
| 金额归一化 | 6/6 | 本轮独立原文件回归实测 |
| 评分上限 | 2/2 | 本轮独立原文件回归实测 |
| 关键负例误放行 | 0/7，`inconclusive=0` | 本轮独立原文件回归实测；主要反映保守阻断，不代表资格识别准确率 |

27 样本报告 `reliability-followup-final-2.json` 中的 `raw_file_baseline` 字段仍是
历史引用（`status=not_retested_in_this_followup`）：该 runner 不测 PDF，该字段不是
上述本轮原文件回归结果。原文约束的 4/10 只表示固定必要约束组的文本覆盖，不表示
要求已转为正确、完整的可执行规则；0/7 只表示这组负例未被门禁放行，不证明资格
识别准确率。

该原文件报告中的 OCR 为固定文本、置信度 `0.61` 的模拟 backend，调用 1 次，只测
告警和来源传递，不测真实 OCR 准确率；本轮未调用真实 OCR。6 项约束遗漏仍待修复
并验收。

## 运行

只运行本轮独立评测：

```powershell
.venv\Scripts\python.exe -m pytest tests\evals\test_reliability_followup.py -q --basetemp=.pytest-basetemp-reliability-followup
.venv\Scripts\python.exe scripts\run_reliability_followup_eval.py
```

runner 默认只向标准输出打印 JSON。仅显式提供一个尚不存在的 `--output` 路径才会写报告；若目标已存在则拒绝覆盖：

```powershell
.venv\Scripts\python.exe scripts\run_reliability_followup_eval.py `
  --output .qiaowenshu\acceptance\reliability-followup-NEW.json
```

本轮结果通过也只表示这些固定反例与正例达到断言，不认证通用事实真实性、原始文件解析完整性、生产并发、权限、安全、Word 交付或投标提交流程。
