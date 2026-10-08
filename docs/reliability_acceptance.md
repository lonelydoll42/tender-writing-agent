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
该次 final-2 验收全量测试为 `332 passed`，伴随 1 条既有 Starlette 弃用告警；Ruff 和
`git diff --check` 通过。全量测试包含
`tests/evals/test_raw_file_benchmark.py`，该测试调用 `run_raw_file_eval`。27 样本
followup 本身使用模拟模型，未调用真实模型或 OCR，也不处理 PDF。
final-2 报告位于本地 ignored 输出，可由主审复验；不将它描述为已入库报告。

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

2026-10-06 主验收对当前原始文件评测重新实测，报告保存为
`.qiaowenshu/acceptance/raw-requirement-final-noise-fixed-20261006.json`，
未覆盖旧报告：

| 指标 | 结果 | 口径 |
| --- | ---: | --- |
| legacy 要求覆盖 | 8/10 | 完全保留 legacy oracle；Q5 同年简写、T4“不得绑定”词形仍是 legacy matcher 限制 |
| strict 六类文本覆盖 | 6/6 | strict 独立 matcher 已覆盖实际 T4 原句 |
| strict 有限条件特征 | 6/6 | 仅核对冻结的有限结构和语义映射 |
| strict 来源引用 | 6/6 | 核对 Registry 文件、版本、页码、原始行 quote 和 locator |
| strict 自动核验支持 | 0/6 | 六类均为 `partial` / `manual_review`，不宣称自动执行 |
| 金额归一化 | 6/6 | 原始文件回归实测 |
| 评分上限 | 2/2 | 原始文件回归实测 |
| 关键负例误放行 | 0/7，`inconclusive=0` | 保守阻断结果，不证明资格识别准确率 |
| 精度回归 | 2 个负例、3 个正例 | 噪声修复后的限定回归，不外推为原始文件整体准确率 |

`3ed3057` 的历史 baseline 为 `4/10`，此前“六项遗漏”只属于该历史口径，
不能描述为当前 raw 结果。当前 legacy `8/10` 仍保留旧 matcher 限制：Q5 的同年
区间简写和 T4 的“不得绑定单一公有云”词形未纳入 legacy matcher。strict 结果已
覆盖这些实际原句，因此两套分数不可混为一个准确率，也不能称为所有原始文件准确率。

strict 保留 `coverage_status=partial` 与 `manual_review` 能力边界；有限条件特征
存在不代表生产可执行或通用语义认证。原始文件评测中的 OCR 仍为模拟 backend，
不测真实 OCR 准确率。

主审本轮另行完成 canonical `raw_file_eval`；对应输出仅在本地 ignored 区域，
可由主审复验，不作为已入库报告。结果为：legacy `8/10`；strict 六类文本 `6/6`
（报告另保留 `ambiguous_count=1`）；树结构/有限语义 `6/6`；来源 `6/6`；
自动核验支持 `0/6`；金额归一化 `6/6`；score `2/2`；关键负例误放行 `0/7`，
`inconclusive=0`。核心 counted OR 为
`(营业执照 OR 法人证明) AND 审计独立 mandatory`；`unknowncount`、缺号或重复号按
保守策略处理，不擅自并入分组。这些有限结果不证明通用资格识别或生产可靠性。

### 固定公开回归集

8 份构造 TXT 与 frozen oracle 已预冻结 fingerprint，raw 源文件字节保持不变；它们不是真实
未见业务 PDF。基线 `9ac022b` 的历史 v2 报告为
[`raw-requirement-holdout-acceptance-v2-final-20261006-rerun.json`](../benchmarks/raw_requirement_holdout/reports/raw-requirement-holdout-acceptance-v2-final-20261006-rerun.json)，
复跑入口为
[`scripts/run_raw_requirement_holdout_eval.py`](../scripts/run_raw_requirement_holdout_eval.py)。
该固定集今后作为公开回归使用，不再称为 blind holdout。历史报告中的 status 是静态人工
注记，不是当前机器评测结果。
8/8 均实际执行 decomposition，分别产生 `2、2、2、1、1、1、4、3` 条结果；
冻结的 8 份 raw 与 oracle hash 未变化。

| 指标 | 结果 | 边界 |
| --- | ---: | --- |
| decomposition 执行 | 8/8 | 证明执行发生，不证明要求完整 |
| 来源定位核验 | 16/16 | 文件、页码、版本 token、精确 quote、物理行号均真实 |
| 必要约束/跨段关系完整 | 0/8 | 8/8 均为 `partial`，不构成独立集完整性通过 |
| business evidence 注册 | `not_run/8` | 独立 bidder material 未注册，不能计算正确通过率或误阻断率 |

瓶颈已定位为跨段结构关系而非继续增加关键词：H01/H02 丢失跨编号 OR 分支；
H03/H04 的同人和连续月份关联不足；H05 丢失身份协议与禁替换 AND；H06
方案替换事实不全；H07 保留文本但 TLS 与数据库跨条 AND 不完整；H08 遗漏
PostgreSQL 14+ 与三项 AND。首版因 validator 错误判定为 `not_run`，已保留但标记
`invalid`，不计入通过或失败；不能引用不存在的 knowledge-retrieval 失败。

因此，本轮只说明固定原 PDF 六类专项的 strict 漏洞已修复并达到 `6/6`；通用、
跨段、多级编号原始文件完整性验收不通过，不扩大使用范围，不构成生产可用结论。
不能以继续增加关键词替代关系分组、多级编号和独立语料验收。

`353 passed`、1 条既有 Starlette warning 是 `9ac022b` 历史全量测试记录，已由下方
更新的冻结摘要取代；不可表述为本轮结果。

## 当前验收摘要

本轮 canonical 冻结全量测试为 `436 passed`，另有 1 条既有 Starlette warning、无其他
warning；全仓 Ruff `--no-respect-gitignore` 通过，三个专项测试文件共 `79 passed`。
此前 `406 passed` 是上一轮冻结副本的历史记录，已被本轮结果取代，不是当前验收值。
固定专项不代表通用解析或生产验收；`uv.lock` 留待后续处理，本轮未改。
本轮 P2 边界为：“以下两项任选一项”只将前两项分组，第 3 项审计为独立 mandatory；
整体为 `(营业执照 OR 法人证明) AND 审计`。缺号、重复号或不支持的数量表达保持人工复核，
不自动分组。

标题 P2 修复经主审独立矩阵 `32/32` 通过，纯标题负例仍被过滤。既有 27-case 限定复测中，
写作正例正确通过 `6/6`、负例误放行 `0/12`；Runtime 正例正确通过 `2/2`、负例 writer
及模型调用均为 `0/7`。以上限定复测均未调用真实 LLM。

历史公开回归报告路径为
[`public-regression-final-20261007.json`](../benchmarks/raw_requirement_holdout/reports/public-regression-final-20261007.json)。报告元数据的 `generated_at` 为 `2026-10-07T03:05:30.763776+08:00`；
`source_tree_sha256` 为
`b3a1b85a5a24d90a49c9f19f349fb4bb1b7d838b966543b5265dbc15be32b042`；
运行时 Git revision 为 `9ac022b4e969231fdf0e8a16c3217b43fec32bbc`，运行时工作区为
dirty。Git revision 是运行时元数据，不能据此声称 `9ac022b` 原源码就是本次被测修复；
被测源码快照由报告中的 source tree hash 标识。

旧报告的 `b3a1b85a5a24d90a49c9f19f349fb4bb1b7d838b966543b5265dbc15be32b042`
是该次 Windows 工作树 `src/**/*.py` 文件的原始字节快照，与旧报告保持一致；
它不是 Git blob 的规范源码哈希。当前 `core.autocrlf=true` 环境中有 59 个
源码文件的工作树换行与 Git blob 不同。不得归一化或改写旧报告来替换这个历史值。

该公开集 8/8 个 case 均实际执行；有限 machine checks 为 `0/8 passed`、
`8 failed`、`not_run=0`。输出引用 `18/18` 的文档 ID、source version token、页码、
locator 和物理行 quote 均精确核验；business evidence 为 `not_run/8`。

这套有限 machine oracle 与历史 v2 报告中的静态人工注记采用不同口径，不可混读。
`failed` 表示 parser 已执行后有限结构检查未满足，不等于 parser 未执行。可通过
[`scripts/run_raw_requirement_holdout_eval.py`](../scripts/run_raw_requirement_holdout_eval.py)
复跑：

```powershell
.venv\Scripts\python.exe -X utf8 scripts\run_raw_requirement_holdout_eval.py
```

CLI 退出码取决于有限 checks；`8 failed` 时退出码为 1，这不表示脚本或 parser
未运行。公开有限回归未通过，不代表第三步完整验收或生产可用。

### 2026-10-08 快照复现

主验收在 2026-10-08 独立核对基线 commit
`9d9cbe02bebf7b9a85315f7a74cae2c00ff596a9` 的规范 Git blob 快照：使用
`git -c core.autocrlf=false archive 9d9cbe02bebf7b9a85315f7a74cae2c00ff596a9`
导出并逐文件与 `git show 9d9cbe02bebf7b9a85315f7a74cae2c00ff596a9:<path>`
比较，63/63 个 `src/**/*.py` 文件字节完全一致，source tree hash 为
`207b0de46cdd303e1b9c723a5b6651e9707cb73dd3461dfbfc498fb76c39428c`。此值仅标识
该固定基线，不随之后的 `HEAD` 移动，也不预设最终 staged-tree 报告的哈希。
普通 `git archive` 在本次 Windows 环境下会转换源码换行；正式复现必须显式使用
`-c core.autocrlf=false`。Windows 解包使用 ZIP 与 PowerShell
`Expand-Archive -LiteralPath`；本环境的系统 `C:\Windows\system32\tar.exe` 可能破坏中文路径，
不据此泛化其他平台或 tar 实现。精确 staged-tree 命令见
[`raw requirement holdout README`](../benchmarks/raw_requirement_holdout/README.md)。

最终公开回归报告为
[`public-regression-final-20261008.json`](../benchmarks/raw_requirement_holdout/reports/public-regression-final-20261008.json)，
`generated_at=2026-10-08T11:53:10.381492+08:00`。主审记录的 staged tree 为
`1989ef5e66e271dcf1da3962191e8b6cba5677fd`；63/63 个 `src/**/*.py` 文件逐个与该
tree 的 Git blobs 字节完全一致，报告 `source_tree_sha256` 为
`c7b6040cd13b1e2bc5245073356c5a5d14c22ed6ac156a1e426f1f1ed0b22ce4`。
`repository_context=archive/no_local_git_root`、`git_revision_at_run=null` 是归档执行的
预期值；不得借用父仓库 revision。报告中的 `evaluation_baseline_revision=9ac022b`
是评测基线标签，不是运行时 Git revision。raw、oracle、machine-freeze 校验有效且
冻结内容未变；8/8 个 decomposition 实际成功，有限检查 `0/8 passed`、`8 failed`、
`not_run=0`，来源引用 `18/18` 精确。

这仍是公开语料有限回归，生产完整性未通过；business evidence 为 `not_run/8`，未使用
真实模型或 OCR，也不是盲测。主审后续 commit 后会复验相同 source hash；本文不预填
未来 commit 标识。两份旧 public report 的 SHA 与开始时保存值一致、原字节未变；
本轮唯一新增的公开 8-raw 报告为上述 2026-10-08 文件。

支持范围仅包括明确前置 frame、同一 scope 内相邻编号条款的同级 AND/OR 分组、
inline license OR 再 AND audit，以及明确的同人日期关系；分组仍为
`manual_review` / `partial`，自动核验不受支持（unsupported）。跨编号引用、字母分支、递归嵌套列表和
通用完整性不受支持。原 PDF 六类、标题 P2 矩阵、资产复现与安全测试各自通过，
不代表第三步完整通过或产品可用于生产；公开有限回归为 `0/8 passed`。

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
