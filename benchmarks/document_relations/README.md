# 文档关系状态回归

## 当前专项状态（2026-10-10）

用户独立复查发现否定cue可使关系被错误标记为`confirmed`。本轮反例仅涉及前置“不需要”“不要求”及后置“无需”；专项核验关系语义，不评价业务材料是否被误放行。source reference通过原文坐标校验不代表关系semantics正确。

R4旧关闭判断因上述反例重新打开；本次由修改智能体统一检查、主审独立从Git导出复验。新canonical源码SHA-256为`76b23ab8d386616677b424f3f9e97f0b1b04ffae7b2809b0107fb406b2bde6c0`，65源码与11评测/测试blob匹配；全量`743 passed`、1条既有Starlette警告，Ruff通过。仅有限否定入口小修可关闭，Step 2整体、通用完整性及生产验收仍未通过。R4的`8/14`、旧源码SHA `c96529dc…`及`679 passed`属于历史，旧报告保持原字节。

新专项24负例（八种否定词乘前置/单行/后置入口）与6个肯定AND/OR正例均通过，`0 failed`、`0 not_run`、source_invalid`0/816`；未支持NOT保留带否定来源的candidate/unresolved，不推断成OR。相同评分器重放旧`7ed381c`导出源码时，负例10/24通过、14失败，正例6/6通过、未执行0，来源错误仍为0/1315。新14例关系复验仍为8/14，所有summary指标未变；来源有效不证明语义正确。这30例是公开人工回归，不是企业材料或盲测。

## 冻结资产

- `reserved/v1/`：历史`rejected-annotated-container`。输入含注释容器，不可作为有效运行输入。
- `reserved/v2/`：规范冻结bundle，含14份干净合成TXT、14份人工MD oracle、machine oracle与freeze manifest。
- `reports/initial-invalid-evaluator/`：首次无效grader输出及source proof，原字节保留，不代表产品评分。
- `reports/first-valid/`：首次有效产品评分与source proof，原字节保留。
- `reports/pre-operator-adapter-20261010/`：R3历史评分与source proof，保留operator布局适配前的`7/14`结果。
- `reports/final-20261010/`：R4最终canonical六份报告/proof。
- `reports/negation-followup-20261010/`：本次否定专项、旧源码专项重放、五份既有评测复验及source proof，共八份；不覆盖R4历史报告。
- `publication-record.json`：两版fingerprint、freeze/report SHA-256、发布与授权时间、首次读取时间状态（未知；先前自报已撤回）及grader契约勘误的独立索引。

v1 fingerprint为`a60343e423e1ba28c4cf7d43c8a5e771f978640234c8206ba54b9899b3ce518f`，freeze SHA-256为`294e0c028279a308cdf8571ef6f090501a31bfb0ab7d8f329199d926723a81e0`。

v2 fingerprint为`eb7322ccbdafba33db9ab17a6bc35c793fdce2ff9cb0bad82a38d5920e0d6864`，freeze SHA-256为`14072deebb73f993759272f19ca687649903c201b49f0d5ff78ede926a8dfcb2`。

冻结payload、报告与proof通过精确`.gitattributes`路径关闭EOL归一化。CRLF文件仅逐路径设置`whitespace=cr-at-eol`，保留原始CRLF并继续检查真实尾随空格；包含v1/v2冻结文件、历史与canonical source proof、R4 raw-file及reliability报告。不对`reserved/**`或reports目录全局关闭空白检查；LF评分JSON仍检查真实尾随空格。所有已发布原件均按SHA-256和字节长度核对，源文件不得重新格式化或覆盖。

## 评分边界

首次有效评分是在grader契约修正后，对源码树SHA-256 `93ad62e4729baedb9f149a781afa8b712987e9424818a4a5c82052af25d2b417`重新执行产品pipeline所得，不是对旧输出的离线精确重评；初始无效报告没有保留`actual_graph`或`source_context`。该历史结果为`0 passed / 14 failed / 0 not_run`，14例全部执行；`source_invalid`为`103/194`，产品locator与裁剪后的char bounds不一致，未放宽raw-coordinate校验。

**最终canonical R4：**源码树SHA-256为`c96529dc1fbf531aaac92e46f0e259ea24b2d64625f50fdd2d4fe981d41f485f`，source proof archive base tree为`35f5faafa934f5ffe7f014440c8a3c827ebfd499`，proof SHA-256为`819b8ebe322da3c814a26fd4e370437d504df2c2c933be8ed2fe4a80a03a8831`。proof验证65/65产品源码blob及9/9 grader/test blob。canonical导出源码真实导入测试为679 passed、1条既有Starlette警告，Ruff通过。grader `1.0.3`结果为`8/14 passed`、`6 failed`、`0 not_run`：通过case-01、02、04、05、06、08、10、14；待处理case-03、07、09、11、12、13。R3在同一产品源码SHA、grader `1.0.2`下为`7/14`；7到8是operator关系布局兼容修正，不是产品源码提升。R3 proof archive base为`76f06e2e98fe3cdfb4be5225848feaeddb1b116a`，proof SHA-256为`e44d68dc5ed4b890cc44703664fdf454dc0d723b352ce318975989d080394c8d`。

| 待处理case | 冻结语义主题 |
| --- | --- |
| 03 | 组内OR与跨组AND的嵌套结构 |
| 07 | 跨页明确延续的AND成员、scope与reference覆盖 |
| 09 | 文档回指及复印件属性scope，不据此捏造AND |
| 11 | 两组材料AND(OR, OR)嵌套未解析；1.9/1.10是材料编号 |
| 12 | 1.9至1.10明确限定两项材料，不扩为数值区间 |
| 13 | `contextual_scope_no_flat_operator`：财务说明与收入属性的上下文绑定未解析；1.10金额只是反例背景，额外非法原子为0 |

R4指标：source_invalid `0/724`、review-handling errors `0/19`、condition omission `6/37`、wrong merge `0/34`、wrong split `0/37`、scope membership errors `21/50`、operator structure errors `6/14`。`forbidden`为`1/16`，原因是显式跨页成员未完整识别，不是业务误放行率。存在有限confirmed scope；K-of-N scope仍为candidate，operator与semantic parent为unresolved。

R4同批其它范围：结构`3/3`通过；既有公开原始文件完整性评测`0/8`即8例实际执行且全失败、`0 not_run`，业务材料`not_run/8`；raw-file必要原文约束覆盖`8/10`、hard false release `0/7`；27个固定reliability mocks为writing正例`6/6`、负例`12/12`，runtime正例`2/2`、负例`7/7`，误阻断和误放行均为0。mock及有限固定样例不外推为生产准确率。企业材料在本批`not_run/14`。R4当时关于有限关系范围可关闭的判断仅属历史；本次否定专项结论见上文，Step 2整体及通用/生产验收仍未关闭。

主审曾在同一源码树SHA上无mock复验当时列出的四类有限探针及candidate helper，未发现错误confirmed；这是仅覆盖那些实际探针的历史观察，不覆盖用户本轮提出的前置“不需要”“不要求”及后置“无需”三类反例，也不能据此推断这些cue处理正确或当前专项通过。新反例已表明旧D结果不能外推。详情及历史报告SHA见[验收文档](../../docs/document_relations_acceptance.md)与[publication record](publication-record.json)。

这些是合成TXT，不是真实业务PDF。共享文件系统只提供策略隔离，不是技术隔离，也不是certified blind。发布后全部14例都是public regression，不得称为unseen holdout。R4当时仅对本批基础关系状态与有限显式AND/OR范围作出历史判断；该判断不关闭Step 2整体、通用或生产验收，也不代表当前专项结论。

来源状态不可混用：`source_reference_status=verified`仅证明原文坐标自洽；`source_identity_status=registry_verified`证明对应真实Registry文件/版本；`caller_asserted`只是调用方声明。它们都不代表企业条件满足或授予写作授权。D在R4同一源码树SHA上的复验仅覆盖当时实际运行的有限探针；用户本轮三类反例表明其“未发现错误confirmed”不能外推至这些否定cue，也不能当作当前验收通过证据。

case04/05的confirmed parent是显式清单中的结构归属，不要求逻辑scope或AND。grader要求actual关系有明确layer和basis、所有成员均有confirmed有向边、共同target存在且target自身来源包含显式清单cue。semantic parent需要明确语义layer/basis、方向及来源覆盖；编号物理parent仅凭status改为confirmed不能通过。case09/13的属性或上下文scope由非AND scope关系承载。typed adapter变更不改冻结oracle和first-valid报告。

## 主审复现

grader现冻结为version `1.0.3`，报告schema仍为`document-relations-acceptance-eval-v1`。脚本SHA-256为`26330942263746e6794deb7def70e17f4848bb64f2fe7ebb4011f5784ca57483`，公开自测SHA-256为`7fb5e3694d8614e962c6061e50d2de8b15c29a2bc6d02e808048f161ac371228`；公开自测`72 passed`，当前Python环境有1条`asyncio_mode`未知配置警告，Ruff通过。1.0.2的原脚本/测试哈希及64项结果、以及1.0.0/1.0.1沿革均保留于publication record；历史报告未改写。

1.0.1执行分类勘误：decomposition步骤成功/部分成功，但`relation_analysis`标记`not_run`且`unprocessed_structures.reason=builder_failed`时，归类为`failed`，不能隐去已尝试但抛错的构建；明确`no_document_structures`仍为`not_run`。新增公开mock自测覆盖两种分支。该勘误不改冻结oracle、历史报告或既有产品结果；评分器维护智能体在1.0.1该勘误阶段未运行产品评分，此说明不表示项目整体未评分。

1.0.2 candidate原子映射勘误：只对冻结oracle的`certainty=candidate`启用source-literal后备匹配，且actual text必须包含精确冻结source quote；同页/行实际source quote也须包含该引文，并通过原始char坐标校验。实际status仍单独检查。错误引文、错行、坏offset、错text不匹配；不降低全局相似度阈值，不改变一对一分配或confirmed原子的错并/错拆计分。公开fixture均为合成自测；评分器维护智能体在1.0.2该勘误阶段未读取产品图或运行产品评分，此说明不表示项目整体未评分，历史评分不改写。

1.0.3 operator review布局勘误：从condition-node、node-scope、block-scope及显式block operator关系四种通道收集`operator_relation`，并只使用关系自身status和source references。包装层scope status或裸`operator_status`不能证明操作符；包装`operator_status`与内层status冲突时拒绝该证据。合成自测验证各布局、candidate/unresolved状态区分、无来源状态、错来源及包装矛盾。该grader契约修正不改产品源码、冻结oracle或历史报告；评分器维护智能体在此维护阶段未运行产品评分，主审随后以此版本完成R4 canonical。

经主审授权后，指定一个从未存在过的新输出路径：

```powershell
python scripts/run_document_relations_eval.py `
  --bundle benchmarks/document_relations/reserved/v2 `
  --output benchmarks/document_relations/reports/follow-up-NEW.json `
  --main-reviewer-authorized
```

R4 canonical已由主审执行；上述命令仅示范从公开v2 bundle进行后续public-regression复现。runner拒绝覆盖已有报告；运行结果不构成盲测或生产认证。
