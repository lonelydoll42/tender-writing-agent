# 文档关系状态回归

## 当前 case-12 有限材料编号语义（2026-10-15）

修改智能体实现，主审从固定 Git 副本独立验收。先冻结材料编号、区间和金额职责合同及20例，再另存7例公开探针。原输出两个明确材料项在冻结1.0.3、1.0.4下均为0/2，属于产品缺失；评分器、oracle、旧测试及历史报告未改。

仅在完整肯定原句明确给出区间、两个不同且与端点逐字一致的标签、逐项列举及“两／二／2项均须提交”时确认。标签按字符串保留，只展开原文列出的两项，不按小数或算术补项。含糊、否定、条件、数量冲突、金额单位或跨块表达保留原文并复核；普通金额及明确普通清单保留原行为。

实际公开专项 **27/27**（6确认、16复核、5对照），**292/292**引用有效；实际图语义变异 **21/21**、来源变异 **2/2**拒绝。既有专项 **22/22、33/33**及其全部变异保持。主审初版职责检查器的21/27误拒结果、检查器快照与修正记录另存，未改冻结评分器。最终全量 **1087 passed、1条既有警告**，Ruff、差异检查通过。

十四例全部重新执行，三版同一捕获重评为 **12/14、12/14、13/14**；旧 **11/14、11/14、12/14**保留。只有case-12的状态及指标改善，其余十三例不变；1130/1130引用有效。前后采集因新文档身份不宣称原始图字节相同，原始输入及页文本一致。1.0.5合同视图剩余case-07。

**99个代码文件、65个产品源码、870个导出文件**与固定tree匹配，源码SHA为 `27af318f62035782d4db08e1d029dfc0a57248c4069afe40b33bb37094f0a7cc`，**856件历史文件**不变。原发布记录24个字段值保留。

- [numbering-regression/20261015](numbering-regression/20261015/README.md)：开发前冻结合同、公开用例、主审检查与复验入口。
- `reports/numbering-followup-20261015/`：原始失败、实际输出、三版评分、逐例对照、测试与Git证明。
- [numbering-publication-record.json](numbering-publication-record.json)：本批资产hash、模型政策审计及限定结论。

执行中模型政策改为只允许 `gpt-6.1-sol / high`，全局主/子默认值和规则已核对，替代修改智能体显式配置；已运行主会话的实际模型不由配置修改推定。

**case-12有限公开回归通过，第2步整体仍不关闭。** 未见验收 `not_run`，旧公开 **0/8**未重跑、企业材料未运行、通用完整性和生产验收未通过；case-07及`uv.lock`单独处理。完整限定范围见[验收文档](../../docs/document_relations_acceptance.md)。

## 历史 case-13 有限财务上下文关联（2026-10-15）

修改智能体实现，主审从固定 Git 副本独立验收。先核对原子映射：冻结1.0.3、1.0.4 原本均为3/3，失败来自关系和证据。产品保留 `AND(A1,A2)` 及独立门槛 A3，新增非逻辑财务 scope、有向 A3 → A2 字段归属和双端原文证据，冻结评分器、oracle 不改。

仅确认同页相邻、完整肯定的指定编号财务说明与人民币收入下限句式，结构中恰有两处收入提及。额外同名指标、主体切换、条件、选择、分页、章节或其他实质段落进入复核，不扩展到通用财务或企业满足判断。

新实际公开专项 **22/22**（5确认、17复核），**1315/1315** 引用有效；实际图语义变异 **23/23**、来源变异 **2/2** 拒绝。既有专项 **33/33**、720/720 引用有效，既有变异保持。最终全量 **1053 passed、1 条既有警告**，Ruff、差异检查通过。

十四例全部重新实际执行，三版同一捕获重评 **11/14、11/14、12/14**；基线另存 **10/14、10/14、11/14**。只有 case-13 状态及语义指标改善，其余十三例全部指标不变，当前1107/1107引用有效。重复采集产生新文档ID，前后原始图不宣称字节相同；输入字节不变，同一捕获内三版指纹一致。

**96个代码文件、65个产品源码、832个导出文件**与固定tree匹配，源码SHA为 `8141956da6314058e73a3c1f64b0f8c058d4fdb5a3c0a1b7068aa1e9e7be45d4`，**819件历史资产**不变。

- [financial-context-regression/20261015](financial-context-regression/20261015/README.md)：冻结合同、公开正反例、主审职责检查及复验入口。
- `reports/financial-context-followup-20261015/`：基线、红/绿测试、实际输出、三版评分、对照与Git字节证明。
- [financial-context-publication-record.json](financial-context-publication-record.json)：本批资产hash与限定结论。

**本项有限公开回归通过，第2步整体仍不关闭。** 未见验收 `not_run`，旧公开 **0/8** 未重跑、企业材料未运行、通用完整性和生产验收未通过；case-07、12另立项，`uv.lock` 单独处理。完整规则见[验收文档](../../docs/document_relations_acceptance.md)。

## 历史备选先行对象边界补修（2026-10-14）

修改智能体实施，主审独立验收。先从 `1b50e96` Git 副本保存两个原反例的真实失败：均错误确认、44/44 引用有效。改为整句匹配有限肯定单对象形式后，两例 scope/属性父级均为 `candidate`，保留原文、30/30 引用有效并继续复核。固定五类对象之外及未支持前后缀也进入复核；不以词频和缺少连接词证明唯一。

实际公开专项 **33/33**（既有 21、本次两例、另存探针 10），原有六个正例保持确认；全部 8 确认、25 复核、**720/720** 引用有效。既有语义变异 **15/15**、来源变异 **2/2** 拒绝。新测试红测 8 passed/8 failed；修复后新旧属性测试 **48/48**。最终 canonical 全量 **1026 passed、1 条既有警告**，Ruff、差异检查通过。

十四例重新真实采集，三版同一材料重评仍为 **10/14、10/14、11/14**，逐例状态/指标不变，case-09 保持通过；冻结评分器、oracle 不改。源码 SHA `122ddbd58a0004732c2b0a26a392dce36a3a7ff739ba5fffb47609b4fbb3532c`，**93 代码、65 产品源码、815 导出文件**匹配快照，**793 件历史资产**不变。

- `copy-alternative-regression/20261014/`：冻结合同、用户公开反例、额外公开探针及 Git 验证工具。
- `reports/copy-alternative-followup-20261014/`：首次失败、红/绿、真实专项、新十四例采集/评分、对照与代码证明。
- [copy-alternative-publication-record.json](copy-alternative-publication-record.json)：本批 hash 索引及限定结论。

**有限补修通过，第2步整体仍不关闭。** 本批未进入 case-13；未见环境未建立、验收 `not_run`，旧公开 **0/8** 未重跑、企业材料未运行，通用完整性与生产验收仍未通过；`uv.lock` 单独处理。更广对象与修饰语的确认率未测量。完整规则和复验说明见[验收文档](../../docs/document_relations_acceptance.md)。

## 历史 case-09 有限属性关联（2026-10-14）

修改智能体实现、主审从 Git canonical 副本独立验收。仅产品 `document_relations.py` 增加同页相邻、唯一明确复印件与肯定盖章要求的属性关联：保留两个 ATOM，typed `attribute_parent` 指向先行对象，操作符/成员/终止均有原文证据；节点与块层暴露同一非逻辑 scope。主体切换、问句、否定、条件、泛称、复合对象及范围中断继续复核。

开发前冻结十二例 **12/12**；含后续公开探针的实际验收 **21/21**（6 正例、15 复核例）。实际图语义变异 **15/15 拒绝**且原始引用全部有效，错误版本/坐标 **2/2 拒绝**。十二例/二十一例来源分别 **269/269、475/475** 有效。所有样例都按公开回归记录，没有未见声称。

主审新采集十四例全部执行，三版对同一 graph/context/runtime/执行状态重评为 **10/14、10/14、11/14**。冻结评分器、输入、oracle 未变：只有 case-09 从失败变为通过；case-10 仅来源分母增加，状态/语义错误计数未变。case-07、12、13 仍失败。旧 **9/14、9/14、10/14** 原报告保留，新成绩来自实际产品改进。

最终 **1010 passed、1 条既有警告**，Ruff、差异检查通过；**91 个代码文件、65 个产品源码、786 个导出文件**与快照匹配，源码 SHA `06558a5194ff789acf8b7136bfe776c3587678e068bb233c3d80be3ff929bb39`，**667 件历史资产**不变。新适配器专项 17/17；原历史报告/旧源码守卫仍拒绝新捕获。适配器比较源码元数据，Git 来源另由快照证明。

首轮 21/21 专项仍未通过冻结总体评分，职责加强后旧输出 15/21，以及只补块层证据仍失败的中间版本均归档；首轮 1008 测试不冒充最终结果。源码/测试快照改名 `.py.txt` 保留原字节，十三份原忽略目录测试 XML 已入库，名称别名另存。

- `attribute-regression/20261014/`：冻结合同、十二例、九例后续公开探针及主审检查工具。
- `reports/attribute-followup-20261014/`：实际捕获、三版评分、历史对照、红/中间/绿记录、源码 proof 和隔离状态。
- [attribute-publication-record.json](attribute-publication-record.json)：新资产 hash、限定通过范围及未关闭事项。

**case-09 有限公开回归通过，本批整体仍不关闭。** 独立管理的未见环境没有落实，新增未见文件 0、未见验收 `not_run`；旧公开 **0/8** 未重跑，企业材料未运行，通用/生产验收仍未通过。case-13、07、12 分别立项，`uv.lock` 单独处理。完整指标和复现命令见[验收文档](../../docs/document_relations_acceptance.md)。

## 历史总体基线与隔离预检（2026-10-14）

本批于 2026-10-13 冻结、2026-10-14 完成复验，目录日期保留冻结日期。补齐 `20e79af` 当前十四例基线，不修改产品、既有评分器、oracle 或历史报告。目标导出 **616/616** 个 Git blob 匹配，65 源码 SHA 仍为 `51b1b18212c84ce50e8606106b96e4b5d5b548fb68bab491669cf08cf4e1ea34`；执行智能体和主审各自通过原 Registry/Runtime 真实采集，十四例全部执行、未执行 0。

| 同一份当前采集 | 1.0.3 | 1.0.4 | 1.0.5 合同视图 |
| --- | --- | --- | --- |
| 通过 / 失败 / 未执行 | 9 / 5 / 0 | 9 / 5 / 0 | **10 / 4 / 0** |
| 条件未映射 / 来源未覆盖 | 各 6/37 | 各 2/37 | 各 2/37 |
| scope 成员错误 | 18/50 | 18/50 | 10/50 |
| 原始引用错误 | 0/1083 | 0/1083 | 0/1083 |

当前 10/14 是新采集的评分，不用历史 10/14 代替；旧报告保留。三版读取同一份 graph/context/runtime/执行状态并核对指纹；分差是评分规则差异，不是产品提升。case-07、09、12、13 仍失败。

新适配器只验证身份并调用冻结评分 API：case-03/11 使用原 1.0.5 证据合同，其他十二例按原合同保留 1.0.4。原历史 CLI 的报告 SHA 守卫未改且实测仍拒绝新捕获。输出 create-only；无当前上下文的未执行 case 不评分，明示合同未核验，不伪造来源。新专项 20/20、主审接口探针 22/22，初版错误目录限制、红测试与后续失败均保留；目标提交全量 941 passed，最终 canonical 全量 **961 passed、1 条既有警告**，Ruff/差异检查通过。首轮额外缓存权限警告及禁用缓存的复跑分别保留，未改代码。**85/85 代码 blob 匹配，612/612 历史文件不变**，见独立发布索引。

两份独立采集的三版汇总相同；八处 1.0.3 错误数组只在顺序上不同，错误多重集、指标和状态相同，原数组未改写。

**隔离未建立**：开发 exec 成功读取 PUBLIC canary，身份哈希与主审一致，未观察到授权拒绝。新未见文件 **0**，未见验收 **not_run**。需要开发无法访问的独立审查主体/环境，先做真实 deny-test，并阻断凭据及共享对话/日志泄露，再冻结未见输入；本批未改账号、VM、安全策略或无关服务器。

- `current-baseline-regression/20261013/`：开发前合同/范围冻结、目标提交快照 proof、公开探针及非敏感 canary。
- `reports/current-baseline-20e79af-20261013/`：worker 与主审独立新捕获、三版评分、状态/身份探针、失败与测试记录；pytest scratch 不纳入发布资产。
- [current-baseline-publication-record.json](current-baseline-publication-record.json)：当前成绩、版本/hash 对应和未关闭事项。

H03/H01 公开回归已完成；本批整体、第2步整体、通用/生产验收仍不关闭。旧公开 0/8 未重跑，企业材料未运行，`uv.lock` 单独处理。完整身份说明与复现命令见[验收文档](../../docs/document_relations_acceptance.md)。

## 历史来源职责与有限组标题修复（2026-10-13）

修改智能体只改 `document_relations.py`，主审从 Git canonical 副本复验；旧评分器、输入、oracle 和历史报告不变。**H03/H01 的有限公开修复通过，本批整体不关闭。**

H03 将已验证空行/空白块的物理位置放入 `position_references`，不再将其作为关系 `source_references`；结构原文仍保留，无效身份/版本/坐标和重复 ID 不产生已验证位置。关系证据仍要求非空白引文及正跨度，不给评分器添加空引用豁免。H01 的显式组标题补齐“证明／条件”，实际产品产生两层 `AND(OR, OR)`；局部冲突、非单项选择、组数/标签错误及实质段落中断仍复核。

| H01-H06 | 原基线 | 仅 H03 | canonical |
| --- | --- | --- | --- |
| 实际正例 | 1/3 | 2/3 | **3/3** |
| 实际树合法变异 | 4/8 | 8/8 | **12/12** |
| 假设合法合成树 | 4/4 | 4/4 | **0/0** |
| 错误 confirmed 变异拒绝 | 56/56 | 56/56 | **56/56** |
| 拒绝职责检查 | 18/36 | 36/36 | **56/56** |
| 语义检查中的无效原始来源 | 18/32 | 0/32 | **0/50** |

三个阶段每次六份文件均执行，失败/未执行均为 0。早期 H01 无实际完整树，其语义变异不适用，合成树分开统计。最终强来源检查两组各 6/6 拒绝；外层复核 3/3 只检查完整外层，不保证全部局部状态，也不是企业材料准确率。开发 D01-D05 实际正例 2/2，合法变异 8/8，错误变异及拒绝职责均为 36/36。

canonical **941 passed、1 条既有警告**，含新来源测试 17、标题/边界测试 12、既有评分器测试 89；Ruff、差异检查通过。源码 SHA `51b1b18212c84ce50e8606106b96e4b5d5b548fb68bab491669cf08cf4e1ea34`，65 源码包含在 83/83 代码 blob 对照中，10/10 冻结合同/测试匹配，567 件历史工作区/index 文件不变。基线、红测试、中间源码和采集身份勘误均另存，没有覆盖旧报告。

开发前已记录无法建立独立权限隔离：共享全权限主机/对话不构成未见环境。**新增未见文件 0，未见验收 not_run**；H01-H06 全部是公开回归。企业材料未运行，`partial/manual_review` 不放宽。旧总体 10/14 是历史输出重评，本批未重采 14 例；旧公开 0/8 也未重跑。第2步整体、通用完整性、生产验收仍未通过，`uv.lock` 单独处理。

- `source-role-regression/20261013/`：预先冻结的合同、隔离记录、测试/源码快照、勘误和复验工具。
- `reports/source-role-followup-20261013/`：基线、H03 中间、canonical 真实输出、负例职责、测试与来源 proof。
- [source-role-publication-record.json](source-role-publication-record.json)：新资产哈希、限定通过范围和未关闭事项。

完整分母、快照身份及复现命令见[验收文档](../../docs/document_relations_acceptance.md)。

## 历史边界证据评分合同（2026-10-13）

新增独立 `1.0.5`，分别核对 operator、直接成员 scope、局部 termination 及有限逻辑继承。上层指令不替代局部成员/终止；属性、上下文或结构父级不能授权逻辑继承。原 `1.0.3/1.0.4`、oracle、产品源码和历史报告不改。

同一历史输出重评为 **9/14 → 10/14**，只有 case-11 的指标/状态变化；14 例 graph/context/runtime/执行状态和指纹一致。**这是评分修正，不是解析能力提升**，旧 9/14 保留；仍有四例失败。

canonical 全量 **912 passed、1 条既有警告**，新合约 **89/89**，Ruff 通过；65 源码、19 评测/测试、6 验收工具的 Git blob 匹配。473 个冻结工作区哈希和 473 个历史 canonical blob 均不变，154 个环境换行差异单独核对。

公开开发合法变异 8/8、错误变异拒绝 36/36、强来源拒绝 6/6；父级类型补修 6/6，补修前 4/6 及源码快照保留。六份原预留正例实际仅 **1/3**：H01 条件树缺失，H03 空行定位/证据合同冲突；合法变异 4/8，名义误阻断 4/8 均来自 H03。H01 假设合法合成树 4/4 不算产品通过，负例的 56/56 也不证明每个语义分支独立正确。

预留文件的开发接触范围无法可靠确认，全部降为公开回归，不宣称未见/技术盲测。**本批尚不关闭**；旧公开 0/8、企业未运行、第2步整体及生产验收未通过的边界保持，`uv.lock` 单独处理。

- `boundary-evidence-regression/20261013/`：冻结规则、标注、11 份 TXT、访问披露、原始工具及补修快照。
- `reports/boundary-evidence-20261013/`：保留输出、失败与 canonical 重评、测试 XML、source proof。
- [boundary-evidence-publication-record.json](boundary-evidence-publication-record.json)：文件哈希、评分版本及未关闭事项。

完整原因、指标分母和复现命令见[验收文档](../../docs/document_relations_acceptance.md)。

## 历史评分器原子映射重评（2026-10-12）

新增独立离线评分器 `1.0.4`：以原文全文、精确引用、文件身份/版本及字符坐标补充 confirmed 原子的低相似度人工释义映射。旧 `1.0.3`、oracle、产品源码和历史报告不改；不降低相似度阈值，不放宽分组/边界证据。

主审对 `af7db0f` 同一份已保存输出双版本重评，14 例原始 graph、source_context、runtime 与指纹一致。旧引擎完整复现 **9/14**；新引擎仍为 **9/14**。case-11 映射 **0/4 → 4/4**，评分器条件未映射 **6/37 → 2/37**，不是产品解析改进。case-11 仍因旧评分合同要求终止边界引用覆盖上层选择指令而失败，边界合同另设批次，不写成 10/14。

canonical 导出源码 SHA 仍为 `da6ccd4982e25f3e245070c179f37be03bb47dff2f0d680a54d355cfbc1cd1b0`；65 源码、17 评测/测试 blob 匹配，361 件冻结资产未改。全量 **823 passed**、1 条既有警告，新增匹配/离线合约 **41 passed**，Ruff 通过。

主审首次变异检查 **16/18** 及两个肯定整例失败保留，不改写为 18/18；独立原子来源核对为 4/4。开发查看过公开历史报告字段，本轮不是盲测；新评测没有调用产品 Runtime、Registry 或模型重新生成结果。

- `scorer-remap-regression/20261012/`：冻结记录、测试先行 red 快照、checker 和首次评分器源码。
- `reports/scorer-remap-20261012/`：首次/canonical 双版本评分、对照、范围审计、源码 proof 及测试 XML。
- [scorer-remap-publication-record.json](scorer-remap-publication-record.json)：逐文件 SHA、版本、验收层级与限制。

旧公开 **0/8**、企业材料未运行、第2步整体及生产验收未通过的边界不变，本批未重跑旧公开文件。`uv.lock` 单独处理。完整复现命令与边界见[验收文档](../../docs/document_relations_acceptance.md)。

## 历史继承指令小修（2026-10-12）

`74a311e` 的有限关闭判断因组内指令被上层 OR 覆盖重新打开。本次仅修继承入口：先检查命名组到冒号之间的冲突和数量限定；原句 candidate、外层完整 scope candidate，外层明确 AND 操作符可单独 confirmed，不表示完整关系通过。未冲突组仍确认，材料名不参与新增数量检查；不实现 K-of-N 或矛盾优先级求值。

canonical 源码 SHA `da6ccd4982e25f3e245070c179f37be03bb47dff2f0d680a54d355cfbc1cd1b0`；65 源码及 15 评测/测试 blob 匹配，全量 **782 passed**、1 条既有警告，Ruff 通过。开发前冻结的 8 例通过，公开边界 3/3 与 4/4 通过；3 组局部状态检查共 9/9。既有嵌套 8/8、严格树 2/2、否定 30/30 保持。未改的 1.0.3 总体仍 **9/14**，所有 summary 指标与旧提交相同。

原基线专项 4/8、中间补丁单位边界 2/4 均保留，不能用最终通过报告覆盖。8 份冻结输入与后续 7 份公开审查样例分开记录；共享目录不是技术盲测，发布后都转为公开回归。局部检查脚本在基线观察后建立，其冻结说明如实记录该时间边界。

- `inheritance-regression/20261012/`：24 件 oracle、15 raw TXT、冻结及检查脚本。
- `reports/inheritance-followup-20261012/`：21 件最终/基线/中间报告、source proof、可重建 patch 与全量测试结果。
- [inheritance-publication-record.json](inheritance-publication-record.json)：45 件新资产的 SHA/字节长度与所有范围限制。

旧 125 件冻结文件/评分器/报告未改；旧公开 0/8、企业未运行的历史结论继续保留，本批不据此计算业务误阻断率。第2步整体、通用/生产完整性仍未通过，case-11 旧词面评分和 `uv.lock` 单独处理。复现见[验收文档](../../docs/document_relations_acceptance.md)。

## 历史嵌套专项（2026-10-11）

有限命名组现在保留 `AND(OR(A,B),C)` 和 `AND(OR(A,B),OR(C,D))` 的直接层级，每层 operator/scope/parent 与终止来源单独核验。singleton 以 typed `REQUIRED` context scope 保留要求来源，不新增 self-parent 或改变逻辑 children。未知限定语、组数不完整及不支持选择仍需复核。

主审最终 Git 导出源码 SHA 为 `e92a0d944c1e610b496638ec3b8dafb902b5ec42375477109eb61052e3d9a643`，65 源码及 14 评测/测试 blob 匹配；全量 `767 passed`、1 条既有警告，Ruff 通过。提前冻结的合成嵌套输入 8/8（6 正例、2 复核），公开 case-03/11 严格树专项 2/2，否定专项 30/30；来源错误分别 0/1754、0/448、0/816。

**旧冻结 1.0.3 的 14 例原始结果为 9/14，不能写成 10/14。** case-03 新通过；case-11 的“四个原文材料名 vs oracle 人工释义”词面映射仍失败，虽同一原始字节的严格树专项通过。新增评分器不替换旧完整性评分器，旧脚本、oracle 和报告未改写。其余 case-07/09/12/13 的范围与完整性问题继续待处理。

旧源码 `9f927bb` 用同一新评分器重放为 1/8（正例 0/6、复核例 1/2，八例均执行）；首次独立产品评分 8/8 和首次公开预验 8/14 均连同准确源码叠加包保留。输入先冻结、开发禁止读取私有目录，但共享文件系统仅为策略隔离，不是 certified blind；发布后均转为 public regression。

新增资产与逐文件 hash 索引：

- `nested-regression/20261010/`：16 件 raw TXT、原/有效 oracle、冻结/澄清及公开专项输入。
- `reports/nested-followup-20261011/`：21 件最终/首次报告、source proof 和两个 exact-byte 源码叠加包。
- [nested-publication-record.json](nested-publication-record.json)：时间、评分器 SHA、来源绑定、全部新资产长度与 SHA。

旧公开仍为 0/8、八例实际执行且失败；企业材料 not_run/8 和关系 not_run/14 不变。结构 3/3，raw-file 原文约束 8/10，27 个既有 reliability mock 判断正确，但不证明生产准确率。第2步整体、通用及生产完整性继续未通过，`uv.lock` 独立处理。完整限定范围及复现见[验收文档](../../docs/document_relations_acceptance.md)。

## 历史否定专项（2026-10-10）

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
