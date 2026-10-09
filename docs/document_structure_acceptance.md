# 文档结构验收（Step 1）

## 验收范围

本步骤只评测解析结果中的物理文档块、编号与父子关系、原文位置引用、字符重建和不确定关系标记。它不评测条件树完整性、需求事实真实性、企业材料、业务判定或生产可用性。

Runner通过`ProjectFileRegistry`注册并解析原始fixture，再运行`build_default_registry`中的`TenderIntakeSkill`和`TenderDecompositionSkill`完整链路；oracle不注册、不注入请求。实际parse artifact和完整runtime输出均保存在报告内。当前执行未使用模型和真实OCR，business layer与condition-tree completeness均为`not_run`。

## 冻结记录

独立私有冻结目录为`.qiaowenshu/acceptance/private-document-structure-20261008`。冻结输入为合成抽取文本JSON，不是真实业务PDF。

- 输入与oracle文件：8个source、9个oracle，共17个；`freeze.json`另计。
- `created_at`：`2026-10-08T23:32:51.143+08:00`；manifest写盘时间约为`2026-10-08 23:33:30`（Asia/Shanghai）。
- fingerprint：`219ba05a264485f70a6698c0ca39d1d57dac1f3f119271a53e420675ca967204`。
- 冻结构造独立于产品输出；不声称早于所有集成代码编辑。A/B未获私有内容或答案；主审当时只列目录，未读取输入或oracle。
- 共享文件系统没有技术隔离，不能称认证blind。当前runner不加载私有集合；这些合成数据不外推为生产准确率。

## 公开回归集

公开输入沿用`benchmarks/raw_requirement_holdout`中的原始bytes，不复制或改写fixture。当前case索引和逐物理行oracle位于`benchmarks/document_structure`，分类为`public_regression_not_blind`。

| Case | 原始输入SHA-256 | 结构关注点 |
| --- | --- | --- |
| H01 | `69ac7a0260462b3e94c3641356d738d5d65536fac013f1037773b0de0e2b730a` | 跨页片段、编号列表、表格 |
| H05 | `d0f6663c9b47e7b4d516931f22da57d769c7160db7317672304daf971af79eb7` | 字母子项及编号父级 |
| H08 | `c62fb12061cd61ca5d47589b9dde7167aaa705fc68a175556061ec32a138f916` | 多级编号、跨章引用文本 |

`f894c05126e65e3d9504f6ac368fc6a5df814ec6e7a89fc338543eb4feb81ac1`是公开bundle的v1历史fingerprint。当前runner默认使用v3 freeze，fingerprint为`e03d75abad901766cbb7b70985bcea35c2cfa6d2a2299138d0008cd50dc6df4f`。Runner会校验case索引、oracle、上游raw freeze manifest和三份raw输入的SHA-256/字节数。H08中的跨章引用仅作为原文结构保存，本步骤不推断AND/OR关系。

## 字段与计数口径

- 每个页内物理block的`raw_text`不含line ending；`line_ending`单独保存。`source_span={page_number,start,end}`使用抽取页文本Unicode codepoint的零起点半开区间，只覆盖`raw_text`；这不是PDF原始字形坐标，也不保证真实OCR精度或Office原生树结构。
- `normalization_map`按归一化字符区间映射回抽取页文本的绝对codepoint区间，仅验收identity与whitespace runs。验收逐段确认归一化字符可由精确来源区间重建。
- 页间`\f`是synthetic序列化边界，不属于任一页正文；单独检查`page_boundary`数量，且不要求它有正文`source_span`或source reference。
- 非空页内块的source reference须与document、source version、页码、字符区间和原文quote精确对应；所有页内block及line ending必须逐页重建完整原文。
- parent/section关系内容只在oracle明确给出字段时比较；显式`null`表示期望无该关系，未声明字段不作内容断言。但全局完整性仍核验`block_id`唯一、所有非空parent/section ID均指向存在的block，并检查parent自引用及循环。`wrong_parent_or_merge`、`wrong_section`分开计数。
- `numbering.label`按原文literal prefix比较；公开oracle冻结保存各级literal-label路径，runner依据其末级token转换后与接口的token数组比较。`style`完整保留在实际输出中，但因尚无双方认可的style枚举，不作通过/失败判定。
- `missing_blocks`、kind、parent/merge、section、numbering、source gaps、normalization map、source references、needs_review、page boundary及`not_run`分别计数。所有原文块均纳入保留检查；显式filtered标注若产品未提供，会单独记为`not_reported_by_structure`。

这些结构保存指标不代表条件树完整、业务通过或生产验收。

## 初始调试结果

历史工作树报告为[initial-debug-worktree-v4.json](../benchmarks/document_structure/reports/initial-debug-worktree-v4.json)，`report_kind=initial_debug_worktree`，source tree SHA-256为`7b9e81c0d2bc2411255bbf50c2bc2a4ce117ca123d1469529abc4975d9d45640`。报告完整保留Registry parse artifact和技能链输出。早期initial-debug v1/v2/v3报告及冻结资产均保留：v1尚未从parse artifact顶层读取pages，且把未声明关系当作null；v2尚未把oracle label路径转换为接口token路径；早期v3调试报告尚未汇总kind、numbering和needs_review的分母/失败数。v4采用其运行时当时的评测口径，属于历史调试结果，不代表当前v3 oracle与grader口径。

v4实测：3/3 case执行，`not_run=0/3`；physical blocks为85/85，missing blocks `0/85`，kind错误`13/85`，wrong parent/merge `13/85`，wrong section `11/85`，numbering错误`0/85`，H01不确定续页候选`needs_review`失败`1/1`。5/5 Registry页文本与原始页一致；source gaps `0/5`页、normalization map失败`0/85`、source reference失败`0/85`、page boundary错误为0。全体物理块均被保留，但结构仍为`not_passed`。

报告`generated_at`按执行主机的UTC+08系统时钟记录为`2026-10-09T00:34:38.28141+08:00`。这是v4历史报告自身的时间戳；截至`2026-10-09`不再称为未来时标，也不用于证明冻结与运行的先后。冻结时序以私有`freeze.json`记录和上列manifest写盘时间为准。

v4是工作树initial/debug历史快照，不替代canonical结果。既有可靠性记录中的有限raw结论`0/8`、企业材料`not_run/8`及生产未通过保持原样；下列canonical结果是新增记录，不覆盖这些历史结论。

## Canonical最终实测（2026-10-09）

正式结构报告为[structure-step1-final-20261009.json](../benchmarks/document_structure/reports/structure-step1-final-20261009.json)，`report_kind=archive_snapshot`，`repository_context=archive/no_local_git_root`，`git_revision_at_run=null`。报告记录的`source_tree_sha256`为`5a179382bd01796b9c2dcb7ae033667d80b2948d3d9fd372e31a389e5dd116eb`，v3 freeze有效，fingerprint为`e03d75abad901766cbb7b70985bcea35c2cfa6d2a2299138d0008cd50dc6df4f`。

主审核对staged archive tree `0d6fa8f9a4a5ac41252472b8694f9f5e8b42fab6`：64/64个`src` Git blobs及5/5个evaluator/test Git blobs一致，0处不匹配。该canonical批次全量测试为`512 passed`、1条既有Starlette warning；全归档Ruff通过。`git diff --check`仍由主审在最终提交前执行，本文不预填其结果。

[主审快照核验报告](../benchmarks/document_structure/reports/snapshot-verification-step1-final-20261009.json)记录了上述64/64、5/5 blob核验及0 mismatches；报告确认archive base staged tree和source hash与canonical结构报告一致。

| 检查 | Canonical结果 |
| --- | --- |
| 公开结构case | H01/H05/H08共3/3执行，failed=0，not_run=0 |
| 物理块与页 | 85/85块；5页；缺块、kind、parent/merge、关系图、section、numbering错误均为0 |
| 原文与映射 | 5/5页精确重建；source gaps、normalization map、source reference错误均为0 |
| 表格 | 11/11行分组、37/37 cells跨度核验，错误均为0 |
| 候选链路审计 | 85/85原块映射及53/53候选最终结果均无错误 |
| 不确定续页 | H01候选1/1按oracle要求复核，无错误 |

以上是选定公开样本上的结构保存结果，不代表条件树完整、业务层通过或生产验收；`condition_tree_completeness=not_run`、`business_layer=not_run`，生产验收仍为`not_passed`。

同批次的[raw requirement有限回归](../benchmarks/document_structure/reports/raw-requirement-regression-step1-final-20261009.json)为`0/8`通过、8 failed、not_run=0，精确来源引用`18/18`；business evidence为`not_run/8`。该结果保留既有有限检查未通过及企业材料未运行的边界。

[Reliability follow-up报告](../benchmarks/document_structure/reports/reliability-followup-step1-final-20261009.json)记录写作正例正确通过`6/6`、误阻`0/6`、负例误放`0/12`；Runtime正例正确通过`2/2`、误阻`0/2`、负例误放`0/7`。七个Runtime负例writer/model调用均为0；该报告使用模拟模型输出，不代表真实模型表现。

[Raw-file回归报告](../benchmarks/document_structure/reports/raw-file-regression-step1-final-20261009.json)记录旧10项覆盖`8/10`，六类text/tree/source检查各`6/6`，自动核验支持`0/6`。这些有限指标不代表通用文件完整性。

独立私有集合仍未运行：8个合成样本为`not_run/8`，不是8份真实PDF；共享文件系统不构成认证blind，也不据此外推生产准确率。保留集17个source/oracle文件及`freeze.json`共18个文件原字节不变，17/17校验通过，fingerprint仍为`219ba05a264485f70a6698c0ca39d1d57dac1f3f119271a53e420675ca967204`。v1/v2/v3冻结资产和6份debug报告均保留；debug报告不是canonical结果依据。

最终commit可新增报告与文档；提交后仍须由主审复核`src`及evaluator/test字节未变。此处不预填未来commit SHA。

## 复跑

```powershell
.venv\Scripts\python.exe -m pytest tests\evals\test_document_structure_eval.py -q --basetemp=.pytest-basetemp-document-structure-NEW
.venv\Scripts\python.exe scripts\run_document_structure_eval.py
```

Runner默认输出JSON到stdout。显式提供`--output`时只接受尚不存在的路径；现有文件会被拒绝覆盖。公开oracle和raw SHA固定，任何调试暴露的私有样本不得再称未见holdout。
