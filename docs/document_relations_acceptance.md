# 文档关系验收

## 状态与边界

### 当前 case-12 有限材料编号语义（2026-10-15）

**case-12 的有限公开回归通过；第2步整体仍不关闭。** 修改智能体实施，主审从固定 Git 字节导出独立验收。先冻结编号、区间、金额的职责合同及二十例，再另存七例公开探针；冻结评分器、oracle、旧测试与历史报告不改。

基线 `c08edec` 中，两个明确材料项在冻结 1.0.3、1.0.4 下均映射 **0/2**，实际图仅保留候选元数据节点。问题属于产品提取缺失，不是评分映射问题。原提交 **861/861** 导出文件与 Git blob 一致；二十例、二十六例和二十七例的首次实际输出分别保留，二十七例基线为 **18/27**，没有把未运行的图变异记作通过。

本批仅确认整句明确写出“仅按材料编号理解：‘编号X至Y’表示编号X项和编号Y项，共两项材料均须提交。”的有限形式，使用原文中文双引号，数量支持“两／二／2”。两个不同标签必须与端点逐字一致，按分段字符串保存，不将 `1.10` 当成小数 `1.1`。即使两个明确标签不相邻，也只生成列出的两项，不补中间项；多级标签保留原文。操作符、成员范围及整句终止边界分别留证，两个叶子的有向父级只指向直接 AND。

裸区间、仅解释编号、数量或端点冲突、重复标签、否定、条件、选择、金额单位和跨块说明不作确认，保留原文及复核原因。普通金额、小数、单个材料编号和无区间的明确清单保留原行为。该规则不提供通用区间展开、跨页承接或企业满足判断；全局 `partial` 和人工复核保持。

| 独立 canonical 检查 | 结果 |
| --- | --- |
| 新实际公开专项 | **27/27**；6 个有限确认、16 个复核、5 个原行为对照，292/292 引用有效 |
| 实际图语义变异 | **21/21 拒绝**；变异原始引用全部有效，独立检查标签、直接成员、有向目标及证据职责 |
| 来源变异 | **2/2 拒绝**；错误版本和坐标另行统计 |
| 既有财务公开专项 | **22/22**、1315/1315 引用有效；23 个语义、2 个来源变异拒绝 |
| 既有属性公开专项 | **33/33**、720/720 引用有效；15 个语义、2 个来源变异拒绝 |
| 修改智能体专项 | 新34项与既有197项合计 **231/231**；交接红测17通过、6失败的原记录保留 |
| 最终全量 | **1087 passed、1 条既有 Starlette 警告**；无失败、错误、跳过 |
| Ruff、差异检查 | 通过；归档失败 traceback 的原空白按精确文件保留 |

主审初版检查器混用了证据职责：要求成员证据连续包含两个叶子，还要求 scope 证据包含提交操作符，使六个合法正例被误拒，工作区结果为 **21/27**。随后按已冻结合同分别核对每个叶子、数量范围和操作符，结果为 **27/27**；初版检查器、原输出、修正后工作区输出均另存。此处是主审职责检查器修正，没有改产品或冻结的总体评分器；最终 canonical 验收仍拒绝全部21个语义和2个来源变异。

最终源码重新实际采集十四例，**14 executed、0 execution_failed、0 not_run**。三版对同一份新捕获重评为 **12/14、12/14、13/14**，上批原报告 **11/14、11/14、12/14** 保留。只有 case-12 改善：原子遗漏2/2 → 0/2、scope 成员错误2/2 → 0/2、分组和父级错误各1/1 → 0/1，整例六项错误归零，引用4 → 27且全部有效。其余十三例状态及全部指标不变；总体引用 **1130/1130** 有效。冻结1.0.5合同视图剩余 case-07 失败，尚未进入跨页补修。

独立 Registry 捕获会生成新文档身份，前后图及上下文不宣称字节相同；输入字节及原文页保持一致，同一捕获内三版 graph/context/runtime 指纹逐例一致。见 [baseline-to-product-comparison.json](../benchmarks/document_relations/reports/numbering-followup-20261015/reviewer/baseline-to-product-comparison.json)。变异拒绝由主审职责检查器核对，不声称冻结评分器覆盖全部变异。

65个产品源码汇总 SHA-256 为 `27af318f62035782d4db08e1d029dfc0a57248c4069afe40b33bb37094f0a7cc`。**99/99代码、870/870导出文件**匹配代码 tree `ca9f0df66235b05765705ecb048db2c3b3854727`，**856件受保护历史文件**的工作区字节与 Git blob 不变。该 tree 只包含代码及发布前资产，不包含后补报告、文档和发布元数据；最终提交继续核对相同99个代码 blob。修改智能体最终产品及测试快照与 canonical 原字节一致，原发布记录24个字段值保持。见 [final-code-proof.json](../benchmarks/document_relations/reports/numbering-followup-20261015/reviewer/final-code-proof.json)。

执行中用户规定智能体只能使用 `gpt-6.1-sol / high`。主智能体及子智能体默认配置、全局 AGENTS 规则已更新并核对，原配置有备份；原修改智能体停止交接，替代实例显式指定模型及推理强度。不能由配置修改推定已运行主会话的实际模型切换，也不将交接前的测试归到替代模型。非敏感审计见 [model-policy.json](../benchmarks/document_relations/reports/numbering-followup-20261015/reviewer/model-policy.json)。

资产、复验入口及 hash 索引见 [numbering-regression/20261015](../benchmarks/document_relations/numbering-regression/20261015/README.md) 和 [numbering-publication-record.json](../benchmarks/document_relations/numbering-publication-record.json)。**新增样例全部为公开回归；独立未见环境未建立，未见验收 `not_run`。** 旧公开原始文件 **0/8** 未重跑，企业材料未运行，通用完整性、生产验收及第2步整体仍未通过；更广编号句式的确认率未测量，`uv.lock` 未纳入本次提交、继续独立处理。

### 历史 case-13 有限财务上下文关联（2026-10-15）

**case-13 的有限公开回归通过；第2步整体仍不关闭。** 修改智能体实施，主审从固定 Git 字节导出独立验收。开发前冻结十五例、合同及修改范围；主体切换、多个同名指标、跨段中断等后续探针另存为公开回归。评分器、oracle、既有测试和历史报告未改。

先对 `57f1a8f` 的实际输出核对映射：冻结 1.0.3、1.0.4 都能一一映射三个原子条件，遗漏为 **0/3**。基线失败来自上下文分组、三个成员、A3 的有向父级和指代证据，不能归因为原子映射。首次真实输出、红测、失败迭代及原始历史报告分别保留。

本批只确认完整、肯定的有限句式：“请提交/提供编号 X 的财务说明，并在说明中列明营业收入。”后接“营业收入应不少于人民币 X 元/万元/亿元。”编号和金额保留原文；同页、相邻实质块可以隔空行，不能跨过标题、其他要求或分页。完整结构中必须恰有这两处“营业收入”，出现额外同名提及即复核；不以局部邻接或未命中少量关键词证明唯一性。其他主体、限定语、条件、否定、选择、替代及未支持句式不作确认。

保留三个 ATOM 和原 `AND(A1,A2)`，增加非逻辑 `financial_context_scope`，直接成员恰为 A1、A2、A3。A3 的 `contextual_parent` 和营业收入指代只指向 A2 字段，不指向说明提交动作、整组或自身。节点与块层提供相同 scope；成员、终止、关系本身、父级及指代均留存说明句与门槛句的原文证据。全局 `partial` 和人工复核保留，不表示企业材料已满足金额要求，也不提供通用主体或时间推断。

| 独立 canonical 检查 | 结果 |
| --- | --- |
| 新实际公开专项 | **22/22**；5 个确认正例、17 个复核例，1315/1315 引用有效 |
| 实际图语义变异 | **23/23 拒绝**，变异原始引用均有效；独立核对有向目标、成员、唯一 ID 和证据职责 |
| 来源变异 | **2/2 拒绝**；版本及坐标损坏单独统计 |
| 原有属性公开专项 | **33/33**；8 个确认、25 个复核，720/720 引用有效；15 个语义、2 个来源变异继续拒绝 |
| 新测试红/绿 | 初始20项中15失败、5通过；最终27项财务测试加32项既有属性测试，59/59 |
| 最终全量 | **1053 passed、1 条既有 Starlette 警告**，无失败、错误、跳过 |
| Ruff、差异检查 | 通过；两份失败测试原始 traceback 只按精确文件保留空白 |

从最终产品源码重新实际采集十四例，**14 executed、0 execution_failed、0 not_run**。三版对同一份新捕获重评为 **11/14、11/14、12/14**，基线新捕获为 **10/14、10/14、11/14**。只有 case-13 的状态和语义错误数改善：scope 成员错误 3/3 → 0/3，父级与指代错误各 1/1 → 0/1，整例六项错误归零；原始引用由38增加到50，均有效。其余十三例状态及全部指标保持；总体引用 **1107/1107** 有效。1.0.5 仍有 case-07、12 失败。

每次独立 Registry 采集会生成新文档身份，所以前后两次 graph/context 的原始哈希不相同，不能声称它们逐字节相同。十四例的输入字节、原文页保持一致；同一捕获内三版 graph/context/runtime 指纹逐例一致。见 [baseline-to-product-comparison.json](../benchmarks/document_relations/reports/financial-context-followup-20261015/reviewer/baseline-to-product-comparison.json) 和 [comparison-identity-note.json](../benchmarks/document_relations/reports/financial-context-followup-20261015/reviewer/comparison-identity-note.json)。变异拒绝由主审独立职责检查器验证，不声称冻结评分器覆盖所有变异。

65 个产品源码汇总 SHA-256 为 `8141956da6314058e73a3c1f64b0f8c058d4fdb5a3c0a1b7068aa1e9e7be45d4`。**96/96 代码、832/832 导出文件**匹配代码 tree `4e330214cea8ff81195b347125d1d361239c70ae`，**819 件受保护历史文件**工作区字节和 Git blob 未变；原发布记录23个字段值保留。该 tree 只包含最终代码及冻结用例，不包含后补报告、文档和发布元数据；最终提交继续核对相同代码 blob。worker 最终产品/测试快照与 canonical 原字节一致；工作区迭代报告仅供诊断，不冒充固定源码验收。见 [final-code-proof.json](../benchmarks/document_relations/reports/financial-context-followup-20261015/reviewer/final-code-proof.json)。

资产、复验命令与 hash 索引见 [financial-context-regression/20261015](../benchmarks/document_relations/financial-context-regression/20261015/README.md) 和 [financial-context-publication-record.json](../benchmarks/document_relations/financial-context-publication-record.json)。**新增样例全部为公开回归；未见环境未建立，未见验收仍为 `not_run`。** 旧公开原始文件 **0/8** 未重跑，企业材料未运行，通用完整性、生产验收及第2步整体仍未通过。更广财务措辞的正确确认率未在本批测量；`uv.lock` 未纳入提交，继续独立处理。

### 历史备选先行对象边界补修（2026-10-14）

**备选对象唯一性的有限补修通过；第2步整体仍不关闭。** 修改智能体实施，主审独立验收。仅产品 `document_relations.py` 收紧先行句判断：不再用“复印件”词频与未命中少量连接词推断唯一性，改为整句匹配有限的肯定单对象形式。冻结评分器、oracle、旧测试和历史报告不改；本批不进入 case-13。

当前形式支持可选“投标人”主体、必须/须/应当/应/需要/需、提交/提供/出具，后接法定代表人身份证、项目经理证书、税务登记证明、营业执照、身份证五类对象之一及“复印件”，允许空白和可选中文句号。其他对象、未支持修饰语、选项、替代、附加用途或复合表达保留候选关系，不能把“未命中有限语法”写成已判定不满足。该有限语法不证明任意证件、企业、人员或时间关联，也不扩大业务权限。

先从 `1b50e96f810209dde21989ad4b25b2e39df40ed9` 导出，**798/798 Git 文件字节匹配**，真实 Registry → Runtime 保存两例首次失败：scope 和 `attribute_parent` 均错误确认、44/44 引用有效。修复后两者均为 `candidate`，原句保留，30/30 引用有效并继续人工复核；未证实业务误放行。确认节点接口不再重复暴露候选 scope，引用检查分母变化不表示解析覆盖提升。首次失败、额外公开探针旧输出和红测均另存，没有覆盖旧报告。

| 独立 canonical 检查 | 结果 |
| --- | --- |
| 本次用户两例 | 2/2 执行并转为候选复核 |
| 既有公开专项 | 21/21；六个确认正例、十五个复核例保持 |
| 另存公开探针 | 10/10；两个确认正例、八个复核例 |
| 全部实际公开专项 | 33/33；8 个确认、25 个复核，720/720 引用有效 |
| 既有实际图变异 | 15/15 语义变异、2/2 来源变异拒绝；原始正例仍通过冻结评分 |
| 新测试红/绿 | 原实现 8 passed、8 failed；修复后新旧属性测试合计 48/48 |
| 最终全量 | 1026 passed、1 条既有 Starlette 警告，无失败/错误/跳过 |
| Ruff、差异检查 | 通过；仅两份原样红测 traceback 单独保留空白 |

主审从最终代码快照重新采集十四例，**14 executed、0 execution_failed、0 not_run**。三版对同一份 graph/context/runtime/执行状态重评仍为 **10/14、10/14、11/14**，case-09 保持通过；各例状态及全部指标与 `1b50e96` 输出一致，引用 1095/1095 有效，三版材料指纹逐例一致。见 [baseline-comparison.json](../benchmarks/document_relations/reports/copy-alternative-followup-20261014/reviewer/baseline-comparison.json)。本批修复不增加总体固定成绩，case-07、12、13 继续失败。

65 个产品源码的汇总 SHA-256 为 `122ddbd58a0004732c2b0a26a392dce36a3a7ff739ba5fffb47609b4fbb3532c`。**93/93 代码、815/815 导出文件**匹配代码及发布前资产 tree `2a6991e2abe07f52b02d71b78b995149e2e75e0a`；**793 件受保护历史文件**工作区字节与 Git blob 未变，原发布记录22个字段值保留。该 tree 不包含随后补充的最终报告、文档和元数据；最终提交另核对同一代码 blob。worker 的最终产品/格式化后测试快照与 canonical 字节相同；格式化前快照留存。见 [final-code-proof.json](../benchmarks/document_relations/reports/copy-alternative-followup-20261014/reviewer/final-code-proof.json)。

资产与复验入口位于 [copy-alternative-regression/20261014](../benchmarks/document_relations/copy-alternative-regression/20261014) 和 [reports/copy-alternative-followup-20261014](../benchmarks/document_relations/reports/copy-alternative-followup-20261014)，索引见 [copy-alternative-publication-record.json](../benchmarks/document_relations/copy-alternative-publication-record.json)。`verify-snapshot.py` 验证 Git/历史字节；实际专项复用未改的 `attribute-regression/20261014/check-acceptance.py`，传入原四份 fixture 及本批两份 fixture；十四例复用原采集脚本和冻结评分 API 适配器，先核对捕获源码 hash 与独立 Git proof，再重评。所有输出必须使用新路径。

**新增样例全部为公开回归，未见环境未建立、未见验收 `not_run`。** 旧公开原始文件 **0/8** 未重跑，企业材料未运行，通用完整性、生产验收及第2步整体仍未通过。更广对象或修饰语的正确确认率没有在本批测量；`uv.lock` 继续独立处理、未纳入提交。

### 历史 case-09 有限属性关联（2026-10-14）

**case-09 的公开回归按有限范围通过；本批整体仍不关闭。** 修改智能体实施，主审从 Git canonical 导出独立验收。产品仅修改 `document_relations.py`，冻结的三版评分器、v2 输入、oracle 和历史报告不改。开发前冻结的 [contract.md](../benchmarks/document_relations/attribute-regression/20261014/contract.md)、十二例及范围清单保持原字节；后续九例公开审查探针单独保存，均不宣称未见。

#### 属性归属与证据职责

仅确认同页、相邻实质要求明确引入唯一复印件，随后单独明确要求“该复印件”加盖公章的有限形式。保留两个原始 ATOM，增加非 AND/OR 的属性 scope 和指向先行对象的 `attribute_parent`；指代、操作符、成员范围、终止边界分别保留来源。属性节点与块层提供同一个 scope，关系 ID、成员、状态及证据一致，不新增逻辑包装。空行可跳过；章节、跨页、其他要求、复合对象、泛称、否定、条件、主体切换和问句进入复核。

例如“须提交法定代表人身份证复印件。／该复印件必须加盖公章。”确认有限属性关联；“该复印件作为附件保存，授权书必须加盖公章。”和“该复印件必须加盖公章？”不能据此确认属性。问句的指代本身可以明确，但不代表肯定盖章要求。该规则不解决企业、人员、时间关联，也不提高业务门禁权限。

首轮真实专项 21/21，但冻结评分仍拒绝 case-09：块层存在关系，成员/终止证据不充分，且属性节点未提供相同 scope 的接口。加强职责检查后，同一旧源码实际为 15/21，六个正例失败；仅补块层完整证据的中间版本仍被冻结评分器拒绝。这些失败、原始输出、测试 XML 和精确源码/验收器快照均保留，不能写成初版已通过。最终补齐完整原句证据及节点入口后再验收。

#### 独立运行与重新采集

| 最终检查 | 结果 |
| --- | --- |
| 开发前冻结十二例 | 12/12 执行并通过；4 个确认正例、8 个复核例 |
| 主审全部公开实际样例 | 21/21 执行并通过；6 个确认正例、15 个复核例 |
| 基于实际图的语义变异 | 15/15 拒绝；各变异原始引用均有效 |
| 身份版本/坐标错误变异 | 2/2 拒绝 |
| 不变实际 case-09 图 | 冻结 1.0.3、1.0.4 均通过 |
| 来源核对 | 十二例 269/269；主审二十一例 475/475 有效 |
| 最终完整测试 | 1010 passed、1 条既有 Starlette 警告；无失败/错误/跳过 |
| Ruff、差异检查 | 通过；归档 traceback 的原空白只作逐文件保留 |

主审重新运行原 Registry → Runtime，十四例全部执行、执行失败与未执行均为 0。三版对同一份新 graph/context/runtime/执行状态重评并核对指纹：

| 同一份新捕获 | 冻结 1.0.3 | 冻结 1.0.4 | 冻结 1.0.5 合同视图 |
| --- | --- | --- | --- |
| 整例通过 / 失败 / 未执行 | 10 / 4 / 0 | 10 / 4 / 0 | **11 / 3 / 0** |
| 条件未映射 / 来源未覆盖 | 各 6/37 | 各 2/37 | 各 2/37 |
| 分组结构错误 | 5/14 | 5/14 | 2/14 |
| 父级关系错误 | 5/16 | 5/16 | 3/16 |
| scope 成员判定错误 | 16/50 | 16/50 | 8/50 |
| 边界证据错误 | 0/17 | 2/17 | 0/17 |
| 原始引用错误 | 0/1095 | 0/1095 | 0/1095 |

与已验收的旧 9/14、9/14、10/14 相比，**仅 case-09 的状态与语义错误计数改善**；case-10 保持通过，仅因候选来源记录增加而改变来源检查分母。case-07、12、13 在当前 1.0.5 视图仍失败；逐项对照见 [baseline-to-product-comparison.json](../benchmarks/document_relations/reports/attribute-followup-20261014/reviewer/baseline-to-product-comparison.json)。本次提升来自实际产品输出，评分合同没有变化；三版之间的分差仍是合同差异。

新增 `run_document_relations_snapshot_rescore.py` 只验证捕获身份并调用冻结评分 API：case-03/11 使用原 1.0.5 sidecar，其他十二例使用原 1.0.4。它比较指定源码 hash 与捕获元数据，**本身不证明 Git 归属**。主审另行核对导出：65 产品源码的汇总 SHA 为 `06558a5194ff789acf8b7136bfe776c3587678e068bb233c3d80be3ff929bb39`，**91/91 代码文件、786/786 导出文件**与 code archive tree `77ce2da6a3465430993b09e9a9a62ba4f862950b` 的 Git blob 匹配；667 件受保护历史文件的工作区 SHA/index blob 未变。该 tree 是代码及发布前资产快照，随后补充的文档/发布元数据不在其中；最终提交继续核对同一代码 blob。原历史报告 SHA 守卫与旧 `20e79af` 源码守卫仍拒绝新捕获，没有放宽。

新增适配器专项 17/17 已独立运行；最终全量包含实际 case-09 的双版本回归及全部既有门禁/解析测试。首轮 1008 passed 属于补证据前版本，另存且不冒充最终成绩。评分脚本退出 1 表示固定案例仍有评分失败，不等于采集未执行。源码与测试归档改用 `.py.txt`，原字节不改；旧记录中的名称通过 [archive-path-aliases.json](../benchmarks/document_relations/reports/attribute-followup-20261014/reviewer/archive-path-aliases.json) 解析。原先指向忽略目录的本批十三份测试 XML 已按原字节入库并登记来源。

资产目录为 [attribute-regression/20261014](../benchmarks/document_relations/attribute-regression/20261014) 和 [reports/attribute-followup-20261014](../benchmarks/document_relations/reports/attribute-followup-20261014)，完整发布/hash 索引见 [attribute-publication-record.json](../benchmarks/document_relations/attribute-publication-record.json)。`verify-snapshot.py` 负责 Git/历史字节核对，`check-acceptance.py` 负责实际输出及职责变异，两者用途分开。

```powershell
$python = (Resolve-Path .venv/Scripts/python.exe).Path
git -c core.autocrlf=false archive --format=zip --output=.qiaowenshu/attribute-replay-NEW.zip HEAD
Expand-Archive -LiteralPath .qiaowenshu/attribute-replay-NEW.zip -DestinationPath .qiaowenshu/attribute-replay-NEW
$export = (Resolve-Path .qiaowenshu/attribute-replay-NEW).Path
& $python "$export/scripts/run_document_relations_eval.py" --bundle "$export/benchmarks/document_relations/reserved/v2" --output replay-attribute-capture-NEW.json --main-reviewer-authorized
$capture = Get-Content -Raw replay-attribute-capture-NEW.json | ConvertFrom-Json
$sha = (Get-FileHash replay-attribute-capture-NEW.json -Algorithm SHA256).Hash.ToLowerInvariant()
& $python "$export/scripts/run_document_relations_snapshot_rescore.py" --bundle "$export/benchmarks/document_relations/reserved/v2" --product-report replay-attribute-capture-NEW.json --expected-report-sha256 $sha --expected-source-tree-sha256 $capture.source_tree_sha256 --output replay-attribute-scores-NEW.json --main-reviewer-authorized
```

归档/报告均使用新路径，并先独立核对提交导出的源码 hash；不能以采集自报 hash 替代来源证明。其余失败案例的只读诊断引用补修前 `20e79af` 输出，case-13 的映射疑点仍是待确认假设，没有据此修改评分器。

**隔离仍未建立**：沿用已独立确认的真实 canary 可读取证据；本批没有获得独立管理且开发不可访问的环境，没有新的访问拒绝证明。新增未见文件 0，未见验收 `not_run`；换目录/worktree 不作为替代。需独立管理方先阻断开发的文件、凭据及共享对话/日志访问，再验证实际授权拒绝并冻结输入/答案。旧公开原始文件 **0/8** 未重跑，企业材料未运行，通用完整性、生产验收及第2步整体仍未通过；`uv.lock` 继续单独处理。

### 历史总体基线与隔离预检（2026-10-14）

本批补齐 `20e79af22ef1666dc862234d3f7c555c82eb90e0` 的十四例当前基线，**不修改产品源码、冻结评分器、oracle 或历史报告**。执行智能体采集与主审独立采集分开保存，不复用 `af7db0f` 的历史产品输出。H03/H01 继续标记为公开回归已完成；未见环境没有建立，本批整体仍不关闭。

#### 当前版本的真实采集

2026-10-13 开发前冻结 [contract.md](../benchmarks/document_relations/current-baseline-regression/20261013/contract.md) 与 [scope-freeze.json](../benchmarks/document_relations/current-baseline-regression/20261013/scope-freeze.json)，2026-10-14 完成复验；目录日期保留冻结日期。`core.autocrlf=false` 导出的目标提交 **616/616 个文件**匹配 Git blob，其中 **65/65 产品源码**的汇总 SHA-256 为 `51b1b18212c84ce50e8606106b96e4b5d5b548fb68bab491669cf08cf4e1ea34`。

主审从这个精确副本运行原 `1.0.3` runner，真实执行 Registry → Runtime；十四例全部 `executed`，execution_failed/not_run 均为 0。报告保留实际 graph、注册 source_context、runtime 与执行状态。归档目录没有 Git 根，报告里的 `git_revision_at_run=null`；版本归属由 [product-snapshot-proof.json](../benchmarks/document_relations/current-baseline-regression/20261013/product-snapshot-proof.json) 和逐文件字节证明，不能把旧 `base_commit=bbb8309`（冻结 bundle 的沿革字段）误读成执行版本。

| 同一份新采集的评分 | 冻结 1.0.3 | 冻结 1.0.4 | 冻结 1.0.5 合同视图 |
| --- | --- | --- | --- |
| 整例通过 / 失败 / 未执行 | 9 / 5 / 0 | 9 / 5 / 0 | **10 / 4 / 0** |
| 条件未映射 / 来源未覆盖 | 各 6/37 | 各 2/37 | 各 2/37 |
| 分组结构错误 | 5/14 | 5/14 | 2/14 |
| 父级关系错误 | 6/16 | 6/16 | 4/16 |
| scope 成员判定错误 | 18/50 | 18/50 | 10/50 |
| 边界证据错误 | 0/17 | 2/17 | 0/17 |
| 原始引用错误 | 0/1083 | 0/1083 | 0/1083 |

**新 10/14 来自当前采集，不是把历史 10/14 改名。** 三版在同一捕获中的原始 graph/context/runtime/执行状态与指纹逐例保持不变；评分器间差异不能算产品提升。1.0.5 视图仍失败 case-07、09、12、13；十四份固定合成 TXT 也不能代表任意原始文件或企业材料准确率。旧原件、旧 9/14、旧 10/14 均原样保留。

智能体与主审独立采集的三版汇总完全一致。离线 1.0.3 与采集时评分有八处错误数组顺序差异（主审五例、智能体三例），逐项错误多重集、状态和指标相同；保留原数组，不重写报告来制造字节一致。逐例核对见 [independent-comparison.json](../benchmarks/document_relations/reports/current-baseline-20e79af-20261013/reviewer/independent-comparison.json)。

#### 冻结评分 API 与新适配器

原 `1.0.5 rescore_report` 只接受绑定的历史报告 SHA；主审实测它仍拒绝新捕获，未创建输出，[historical-cli-guard.json](../benchmarks/document_relations/reports/current-baseline-20e79af-20261013/reviewer/historical-cli-guard.json) 保留原错误。没有修改该守卫或伪装新报告身份。

新增 `run_document_relations_current_rescore.py` 仅作验证与调用层：先固定三版评分器、原规则/sidecar、冻结文档、v2 oracle 的 hash，核对新报告 SHA、当前源码树、十四个 case、原始输入/页文本及 Registry 身份/版本，再调用原评分 API。仅 case-03/11 使用原 sidecar 中的 `1.0.5 score_case`，其余十二例按原合同继续使用 `1.0.4`；没有增加 oracle 节点或重新定义证据职责。历史 sidecar 的原报告绑定与对当前输入的适用性分别验证。

接口不限定智能体的 worker 目录，合法主审或临时路径也能使用，输出必须为新路径。未执行的 case 不评分或伪造 graph/context；缺少当前上下文的 sidecar 明示 `not_validated_non_executed`，其他已执行 case 可继续评分。新增专项 **20/20**，主审公开接口探针 **22/22**；它们不是业务误阻断/误放行率。第一版错误目录限制、测试字段/分类假设错误及 Ruff/测试失败均另存，没有修改原捕获来掩盖失败。主审探针在下发任务后记录，不能冒充开发前盲测。

目标提交独立全量 **941 passed、1 条既有 Starlette 警告**；加入适配器/测试后的 Git canonical 副本全量 **961 passed、1 条既有警告**，全仓 Ruff 与差异检查通过。首轮同为 961 passed，但有额外 pytest 缓存写入权限警告，保留 [canonical-tests.xml](../benchmarks/document_relations/reports/current-baseline-20e79af-20261013/reviewer/canonical-tests.xml)；未改代码，仅用 `-p no:cacheprovider` 复跑得到 [canonical-tests-no-cache.xml](../benchmarks/document_relations/reports/current-baseline-20e79af-20261013/reviewer/canonical-tests-no-cache.xml)，两次都无失败/错误/跳过。

65 个产品源码包含在 **85/85 个代码文件**的 canonical Git blob 对照中；**612/612 件既有受保护文件**的工作区 hash 和 staged blob 均未变。code archive base tree 为 `33118c1ed243b47bda1135f9c5a71f847b4fcddd`，不是随后补充发布元数据的整个提交 tree。新资产按原字节入库，Windows 诊断 TXT 仅局部识别 CRLF；五份命令的末尾空行、四份失败 traceback 的缩进空白逐文件保留，没有放宽源码或 oracle 检查。快照、全量结果和逐文件 hash 见本批独立发布索引。

#### 隔离尚未建立

开发智能体的真实 exec **成功读取**主审路径下的 PUBLIC 非敏感 canary，其内容 SHA 与冻结值一致，SID/主机哈希也与主审一致；这不是访问拒绝。工具可见性在主审与智能体上下文中不同，主审另行确认可用 spawn schema 仍没有强制不同 principal、凭据或权限边界的字段。原始预检与主审核对分开保存，没有据此宣称所有外部环境都不可行。

**新增未见文件 0，未见验收 not_run。** 本批没有读取凭据内容、启动 VM、改变账号/安全策略或操作无关服务器。仍需要独立管理的审查主体/环境，开发工具不可访问其文件、凭据及含未见内容的对话/日志；审查方先确认 canary 存在且可读，再让实际开发工具验证明确授权拒绝及其他访问路径。命令不存在、路径不存在或未测试的远端都不能代替拒绝证据，验证通过后才冻结输入和答案。

新资产见 [current-baseline-regression/20261013](../benchmarks/document_relations/current-baseline-regression/20261013) 与 [reports/current-baseline-20e79af-20261013](../benchmarks/document_relations/reports/current-baseline-20e79af-20261013)，发布索引为 [current-baseline-publication-record.json](../benchmarks/document_relations/current-baseline-publication-record.json)。报告中的采集与离线评分分别标识，所有输出 create-only。

```powershell
New-Item -ItemType Directory -Path .qiaowenshu -Force | Out-Null
git -c core.autocrlf=false archive --format=zip --output=.qiaowenshu/product-20e79af-NEW.zip 20e79af22ef1666dc862234d3f7c555c82eb90e0
Expand-Archive -LiteralPath .qiaowenshu/product-20e79af-NEW.zip -DestinationPath .qiaowenshu/product-20e79af-NEW
$python = (Resolve-Path .venv/Scripts/python.exe).Path
& $python .qiaowenshu/product-20e79af-NEW/scripts/run_document_relations_eval.py --bundle .qiaowenshu/product-20e79af-NEW/benchmarks/document_relations/reserved/v2 --output replay-current-capture-NEW.json --main-reviewer-authorized
$sha = (Get-FileHash -LiteralPath replay-current-capture-NEW.json -Algorithm SHA256).Hash.ToLowerInvariant()
& $python scripts/run_document_relations_current_rescore.py --bundle benchmarks/document_relations/reserved/v2 --product-report replay-current-capture-NEW.json --expected-report-sha256 $sha --output replay-current-score-NEW.json --main-reviewer-authorized
```

归档、解压目录和报告均须为新路径；有评分失败时返回 1，不表示采集未执行。**当前总体基线可单独完成；独立未见环境、本批整体、第2步整体、通用完整性与生产验收仍未完成/通过。** 旧公开原始文件 **0/8** 本批未重跑，企业材料仍未运行，`partial/manual_review` 保留，`uv.lock` 单独处理。

### 历史来源职责与有限组标题修复（2026-10-13）

本批由修改智能体实现、主审从 Git canonical 导出副本验收。产品只改 `document_relations.py`；冻结的 `1.0.3/1.0.4/1.0.5` 评分器、原始文件、oracle 和历史报告均未改。**H03 来源职责与 H01 有限标题识别的公开回归通过；未见隔离未建立，本批整体仍不关闭。**

开发前先记录 [isolation-status.json](../benchmarks/document_relations/source-role-regression/20261013/isolation-status.json)。可用智能体仍共享同一主机、全权限文件系统及对话上下文，另建目录、进程或 worktree 不能形成可核实的独立权限边界。因此没有创建所谓新未见文件：新增未见文件 **0**，未见验收 **not_run**，H01-H06 全部沿用公开回归身份。后续未见验收须先取得独立执行主体/环境，验证开发侧不能读取输入、答案及共享对话中的内容，再于开发前冻结；不能事后补样本冒充盲测。

#### 两项有限改动

H03：结构层仍保留空行、纯空白块及其原文位置。关系层的 `parent_relation.position_references` 只记录通过文件身份、版本及原文坐标验证的物理位置；`source_references` 只保留非空白引文且字符跨度大于零的证据。空块不能确认父级、操作符、成员或终止边界；重复 block ID 及无效来源不能留下已验证位置。**没有为评分器添加全局空证据豁免，也没有删除空块以规避检查。**

H01：明确复合组标题的有限名词从“材料／要求”补齐为“材料／要求／证明／条件”，肯定与已有否定入口一致。实际 Registry → Runtime 输出须保留 `AND(OR(A,B), OR(C,D))`、四个独立原子及每层直接子节点、操作符、scope、父级和终止来源，不以合成树代替。局部指令冲突、非单项选择、组数/标签错误及实质段落中断仍复核，`partial/manual_review` 门禁不放宽。

#### 同一公开输入的分阶段结果

| H01-H06 检查 | 原产品基线 | 仅 H03 修复 | 最终 canonical |
| --- | --- | --- | --- |
| 实际产品正例 | 1/3 | 2/3 | **3/3** |
| 基于实际树的合法变异 | 4/8 | 8/8 | **12/12** |
| 假设合法合成树 | 4/4 | 4/4 | **0/0，不再需要替代 H01** |
| 错误 confirmed 图变异拒绝 | 56/56 | 56/56 | **56/56** |
| 可用的拒绝职责检查 | 18/36 | 36/36 | **56/56** |
| 语义检查中原始引用无效 | 18/32 | 0/32 | **0/50** |
| 完整外层关系的复核检查 | 3/3 | 3/3 | **3/3** |

三个阶段每次六份文件均实际 executed，execution_failed/not_run 均为 0。前两阶段 H01 尚无实际完整树，因此它的语义变异没有进入“可用的拒绝职责”分母；合成树另列。最终 50 项语义错误变异的原始引用有效，须按操作符、成员范围、终止或继承职责拒绝，不能借用空引用失败冒充语义识别；另 6 项检验无效来源。这里的 **3/3 复核只核对完整外层关系，不保证所有独立局部状态正确**。

D01-D05 的最终实际正例 2/2、合法变异 8/8、错误变异拒绝 36/36；拒绝职责 36/36，其中 32 项语义检查的原始引用有效。旧强来源 checker 对两组准确上层引用的冲突/越界反例分别拒绝 **6/6**，调用者自报标记不能绕过原文。合法图变异、错误图变异及有限 TXT 正例都不是企业材料的误阻断/误放行率。

#### 测试先行、来源与历史保护

新增来源职责测试 **17/17**、标题及有限边界测试 **12/12**，既有评分器专项 **89/89**。先行红测试分别为 7 failed/10 passed、2 failed/9 passed；加强标题反例断言后的旧源码重放为 2 failed/10 passed，全部 XML 与原测试快照保留。来源测试仅修正未使用变量的 F841，标题断言加强为精确核对上层来源，不禁止独立局部 AND；没有把红测试改成通过记录。

Git canonical 导出全量 **941 passed、1 条既有 Starlette 警告**，Ruff 与差异检查通过。源码树 SHA-256 为 `51b1b18212c84ce50e8606106b96e4b5d5b548fb68bab491669cf08cf4e1ea34`；65 个产品源码包含在 **83/83** 个代码文件的 Git blob 对照中，冻结合同/测试资产 **10/10** 匹配。567 个既有受保护文件的工作区哈希及 staged Git blob 均保持不变。code archive base tree 为 `d423b8d8820e6371bd43eb1916ff6195ec1826e7`，发布文档/索引随后添加；此 tree 不是最终整个提交的 tree。

基线与 H03 中间采集的早期 `source_commit` 字段表示 checkout 父提交，不能标识未提交源码；[capture-metadata-erratum.json](../benchmarks/document_relations/source-role-regression/20261013/capture-metadata-erratum.json) 保留勘误，逐文件 hash 与源码汇总才是执行版本依据。最终采集将该字段显式置空，单列 `checkout_base_commit` 与精确源码 hash。三份红 XML 为保留原始 traceback 空白，仅逐文件设定 `-whitespace`，没有豁免源码或 oracle。

冻结合同、隔离披露、测试/中间源码快照及复验工具见 [source-role-regression/20261013](../benchmarks/document_relations/source-role-regression/20261013)；基线、H03 中间及 canonical 报告见 [reports/source-role-followup-20261013](../benchmarks/document_relations/reports/source-role-followup-20261013)，逐文件发布索引见 [source-role-publication-record.json](../benchmarks/document_relations/source-role-publication-record.json)。

```powershell
python benchmarks/document_relations/source-role-regression/20261013/check-public.py --output-directory replay-source-role-NEW --label public-regression
python -m pytest tests/test_document_relations_source_roles.py tests/test_document_relations_proof_headers.py tests/evals/test_document_relations_boundary_rescore.py -q
```

输出目录必须从未存在。本批未重跑 14 例总体产品采集，旧 **9/14 → 10/14** 仍是新旧评分器读取同一份历史输出的评分结果，不是当前源码的总体评分。旧公开原始文件 **0/8、企业材料 not_run/8** 也为未重跑的历史结论。企业材料与真实模型服务本批均未运行，不计算业务准确率。**未见验收、本批整体、第2步整体、通用完整性及生产验收仍未通过；`uv.lock` 继续单独处理。**

### 历史边界证据评分合同（2026-10-13）

本批先冻结三类证据职责及来源标注，再由智能体新增独立评分器 `1.0.5`，主审验收。**产品源码、旧 `1.0.3/1.0.4`、旧 oracle 与历史报告均未改写。仅公开回归中的有限评分修正成立，整批尚不关闭。**

操作符证据证明明确指令；scope 证据证明组的归属及每个直接成员；termination 证据证明最后一个成员之后的局部终止标点。引用须匹配注册身份、版本、原始页、精确字符位置及引文。同一位置的包含区间可提供证明，相邻组的同词不能代替。AND/OR 的直接 children、scope targets 按唯一的精确成员集合核对，不要求数组同序，不能用后代叶子替代直接子组。

上层“每组择一”只能授权操作符，不能代替子组成员或终止来源。继承还须核对已确认父组、组数/标签、带 basis 的逻辑父级及来源、局部指令和原文连续性；调用者填写 `absent/contiguous` 不能绕过原文检查。逻辑授权仅接受 `semantic_parent/logical_parent/condition_parent`，属性、上下文或结构父级不能代替。有限合同不重解释 REQUIRED、attribute/contextual、跨页或 K-of-N。

#### 同输出的评分变化

两版读取同一份 `af7db0f` 的历史输出，输入 SHA-256 仍为 `1745cb650edca81e163fc773c71cd9db96e33b3e2df10dc3b8c208af050eb7b7`。canonical 对照保留全部 14 例 graph、source_context、runtime、执行状态和指纹；**离线重评没有重新调用产品 Runtime、Registry 或模型。**

| 指标 | 1.0.4 | 1.0.5 |
| --- | --- | --- |
| 整例通过 / 失败 / 未执行 | 9 / 5 / 0 | 10 / 4 / 0 |
| 边界证据错误 | 2/17 | 0/17 |
| 分组结构错误 | 5/14 | 2/14 |
| 父级关系错误 | 6/16 | 4/16 |
| scope 成员判定错误 | 18/50 | 10/50 |
| 条件未映射、来源未覆盖 | 各 2/37 | 各 2/37 |
| 原始引用错误 | 0/1083 | 0/1083 |

只有 case-11 的状态/汇总指标变化。它已有上层选择指令、自身成员及局部句末证据，新合同不再要求局部终止引用重复覆盖上层操作符指令；逐角色核对通过后整例通过。这是**评分变化，不是产品解析提升**。旧 **9/14** 不改写；case-07/09/12/13 仍失败。

#### 公开回归与预留失败

| 检查 | canonical 结果 | 解释 |
| --- | --- | --- |
| 新评分器合成合约 | 89/89 | 包含证据职责、继承、输入身份、离线 I/O 和父级类型；不是业务准确率 |
| 开发两份正例的合法变异 | 8/8 | 原产品树及合法的同位置引用变异 |
| 开发错误 confirmed 变异 | 36/36 拒绝 | 仅已列固定案例 |
| 三份开发冲突/越界的强来源反例 | 6/6 拒绝 | 准确上层 OR 引用不能覆盖局部冲突；自报标记无效 |
| 父级类型补充 | 6/6 | 三种逻辑父级通过；属性、上下文、结构父级拒绝 |
| 六份原预留文件实际正例 | **1/3** | H01 条件树不完整；H03 空行定位与现有证据校验合同冲突 |
| 原预留合法变异 / 假设合法合成树 | **4/8、4/4** | 后一项是 H01 人工断言的完整证明树，不是产品解析结果 |
| 原预留错误变异 / 强来源反例 | 56/56、6/6 拒绝 | H03 的空引用也会使负例失败，不能据此证明每种语义错误均被单独识别 |

11 份 TXT 的 Registry 分析链路于开发前采集，全部 executed，execution_failed/not_run 均为 0；canonical 检查读取这些保留输出，未再次运行该产品采集。六份原预留输入、答案、输出及失败均按原字节入库。

H03 的两个空行块保留了 `unresolved parent_relation` 和零长度原文定位，但引用引文为空；未改的全局源校验拒绝它们。冻结 checker 的名义误阻断是 4/8，四项来自同一 H03，不是四份独立文件。本批不放宽来源校验；需另行明确“原文空块定位”和“关系证据”的接口合同。H04-H06 的 `product_review=3/3` 只证明没有错误 confirmed 完整外层 AND；H04 仍有独立 confirmed AND，**不代表所有局部状态均正确**。

**未见验收未达成。** 测试智能体末尾自报曾读取预留 oracle 和历史报告；可用 exec 日志未恢复对应直接读取命令，但证实它读取了含预留路径的主线程输出，接触及使用范围无法可靠确认。该自报与日志证据分开保留，六份全部保守降为公开回归。原冻结记录中的 `private_case_content_used_by_developer=false` 是开发前意图，不是当前保证；不宣称 certified blind，也不事后挑选新文件替代。

#### 快照与发布

canonical 全量 **912 passed、1 条既有 Starlette 警告**，Ruff 通过。源码树仍为 `da6ccd4982e25f3e245070c179f37be03bb47dff2f0d680a54d355cfbc1cd1b0`；65 个产品源码、19 个评测器/测试及 6 个验收工具与 Git blob 匹配。code archive base tree 为 `231f251ed3362619596686ea1bcee34d097988eb`，最终发布元数据随后添加。

473 个既有受保护文件的工作区冻结哈希不变，473 个导出 blob 与旧提交一致；154 项工作区/导出差异均另行证明只来自 CRLF/LF。第一次验收工具混用两套哈希、第二次假定 UTF-8 的失败及工具快照保留，没有修改旧文件来消除差异。两份首次失败 XML 保留原始 traceback 空白，只有这两份归档文件设定 `-whitespace`，不豁免源码或 oracle。

测试先行的两次收集 ImportError 均为零项执行；开发期 64 passed/17 failed、79 passed/2 failed 和合法变异 0/8 等失败也保留。开发期首个 grader 精确源码未完整归档，仅有身份哈希，不能将其冒充最终代码复现。末尾父级类型反例的补修前 **4/6、2 次误接受**及准确源码/测试快照完整保留，修补后为 6/6。

规则、原始/修正工具、冻结与访问记录、11 份 TXT 和补修快照见 [boundary-evidence-regression/20261013](../benchmarks/document_relations/boundary-evidence-regression/20261013)；正式及中间报告见 [reports/boundary-evidence-20261013](../benchmarks/document_relations/reports/boundary-evidence-20261013)，索引为 [boundary-evidence-publication-record.json](../benchmarks/document_relations/boundary-evidence-publication-record.json)。

```powershell
python scripts/run_document_relations_boundary_rescore.py --bundle benchmarks/document_relations/reserved/v2 --product-report benchmarks/document_relations/reports/inheritance-followup-20261012/relations-score.json --expected-report-sha256 1745cb650edca81e163fc773c71cd9db96e33b3e2df10dc3b8c208af050eb7b7 --overlay benchmarks/document_relations/boundary-evidence-regression/20261013/historical-overlay.json --expected-overlay-sha256 526a08805b88192d2351a0c0b45f9cd6060745ba1a931919e069e9d104c86d02 --output replay-boundary-NEW.json --main-reviewer-authorized
python benchmarks/document_relations/boundary-evidence-regression/20261013/check-boundary.py --cases benchmarks/document_relations/boundary-evidence-regression/20261013/reserved-exposed/cases.json --captures benchmarks/document_relations/reports/boundary-evidence-20261013/reserved-capture.json --output replay-reserved-NEW.json
```

输出须使用新路径；前者仍有四例评分失败，后者保留上述失败，返回 1 不表示未执行。企业材料本批未运行，不计算业务误阻断/误放行率；旧公开原始文件 **0/8、企业 not_run/8** 为未重跑的历史结论。**整批、第2步整体、通用完整性与生产验收仍未通过**，`partial/manual_review` 与 `uv.lock` 独立处理的边界不变。下一批应先取得可核实的开发前未见隔离，再处理 H01 及 H03 的合同/解析问题。

### 历史评分器原子映射重评（2026-10-12）

本批由修改智能体新增独立评分器 `1.0.4`，主审只验收原子映射与离线重评。**产品解析源码、旧 `1.0.3` 评分器、冻结 oracle 和历史报告均未修改；case-11 的整例评分仍未通过。**

新规则只为 `certainty=confirmed` 的条件补充严格原文字面匹配：实际节点全文须与 oracle 的原文引文一致，实际引用也须为该精确引文，且通过文档身份、版本、原始字符坐标和同页同行校验。仅允许裁剪全文外侧空白，不删除编号标点，不做数字子串或包含式匹配。旧相似度阈值、candidate 路径、一对一分配、错并错拆、节点状态和分组/边界审查保持原样。这是评分器映射修正，不是通用事实核验。

最小匹配正负例先于实现写入并得到缺少新模块的 `ImportError`，该 red 是**零项执行的收集失败，不是通过记录**。随后补齐离线输入契约，共 **41 项合成自测**：20 项匹配/关系合约与 21 项离线输入合约；主审从 Git canonical 导出副本独立重跑全部通过。全量 **823 passed、1 条既有 Starlette 警告**，Ruff 通过。新增重评拒绝错误报告 SHA、冻结身份、文件版本、原始页文本、运行校验和、重复 case/node ID，以及覆盖已有输出；failed/not_run 不升级为 executed，未执行项不进入指标分母。

#### 同一产品输出的并列评分

两版本均读取 `af7db0f` 已入库的 `inheritance-followup-20261012/relations-score.json`，输入 SHA-256 为 `1745cb650edca81e163fc773c71cd9db96e33b3e2df10dc3b8c208af050eb7b7`。**本批不重新调用产品 Runtime、Registry 或模型生成评测输出**；14 例原始 graph、source_context、runtime 数据及两版本指纹逐项一致。报告中的 executed 状态来自原报告，不表示本批再次执行了产品。

| 指标 | 冻结引擎 1.0.3 离线重评 | 新引擎 1.0.4 离线重评 |
| --- | --- | --- |
| 整例通过 / 失败 / 未执行 | 9 / 5 / 0 | 9 / 5 / 0 |
| case-11 原子映射 | 0/4 | 4/4，四个不同节点及原文位置独立核对 |
| 评分器条件未映射 | 6/37 | 2/37 |
| 评分器来源未覆盖 | 6/37 | 2/37 |
| 分组结构错误 | 5/14 | 5/14 |
| 边界证据错误 | 0/17 | 2/17 |
| 原始引用错误 | 0/1083 | 0/1083 |

旧版本的完整 summary 与原报告一致。只有 case-11 的指标变化；其余 13 例的指标、状态均未变化。上述“条件未映射”减少不能写成产品解析遗漏减少，也不能将总体结果写成 10/14。

**新增可见的边界合同问题没有关闭。** 四个原子可解析后，旧分组评分器才进入 scope/termination-boundary 检查。S1、S2 的 `operator_relation` 引用 P1-L01“每组只需择一”，其 `boundary_source_references` 则引用组内材料行及终结标点；冻结评分合同要求后者也覆盖 P1-L01，因此拒绝两组，继而根组及 parent 仍未匹配。本批不改变 `_scope_evidence` 或分组评分规则，不判断应当修改产品还是评分合同；操作符来源、作用域依据、终止边界的契约须另设正负例后验收。

#### 审计与边界

开发前冻结的 361 件源码、测试及历史资产全部保持字节一致，其中含 164 件关系评测历史资产。产品 canonical 源码树仍为 `da6ccd4982e25f3e245070c179f37be03bb47dff2f0d680a54d355cfbc1cd1b0`；65/65 产品源码、17/17 评测器/测试文件与 Git blob 匹配，code archive base tree 为 `fba946b225b7f2d577f466472d6bbc6d85bc5955`。Windows 导出显式使用 `core.autocrlf=false`。

主审开发前冻结的原始 case-11 变异检查首次为 **16/18**：两个肯定检查原先假设“原子恢复即整例通过”，实际因上述边界合同失败。原 checker、失败报告及其评分器源码快照均保留，**没有改写成 18/18**。正式限定验收依据是 41 项合成合约、14 例同输出对照和独立原文定位 4/4，不据此关闭整例或条件树整体。详情见 [scope-audit.json](../benchmarks/document_relations/reports/scorer-remap-20261012/scope-audit.json)。

本轮是公开回归与已发布输出重评，不是未见文件评测。实现智能体曾查看一份公开历史报告以核对字段；开发期间未报告执行产品重评，正式重评由主审完成。共享目录隔离只是工作约束，不是技术盲测。

冻结记录、red 快照和 checker 位于 [scorer-remap-regression/20261012](../benchmarks/document_relations/scorer-remap-regression/20261012)；首次与 canonical 并列报告、比较记录、测试 XML 及源码 proof 位于 [reports/scorer-remap-20261012](../benchmarks/document_relations/reports/scorer-remap-20261012)，索引见 [scorer-remap-publication-record.json](../benchmarks/document_relations/scorer-remap-publication-record.json)。

```powershell
$sourceReport = "benchmarks/document_relations/reports/inheritance-followup-20261012/relations-score.json"
$sourceSha = "1745cb650edca81e163fc773c71cd9db96e33b3e2df10dc3b8c208af050eb7b7"
foreach ($version in @("1.0.3", "1.0.4")) {
  python scripts/run_document_relations_rescore.py --bundle benchmarks/document_relations/reserved/v2 --product-report $sourceReport --expected-report-sha256 $sourceSha --version $version --output "replay-$version-NEW.json" --main-reviewer-authorized
}
```

输出必须是新路径。两版均存在 failed case，CLI 返回 1 是评分结果，不是未执行。旧公开原始文件 **0/8、企业材料 not_run/8** 为历史结论，本批未重跑；14 例企业材料仍为 not_run/14，不计算业务误阻断/误放行率。**仅本批严格原子映射可按限定范围通过；case-11 整例、完整第2步、通用及生产验收仍未通过。** `partial/manual_review` 门禁不变，`uv.lock` 继续独立处理。

### 历史继承指令小修（2026-10-12）

`74a311e` 的有限嵌套关闭判断因用户复审重新打开：上层“每组任选一项”会覆盖组内“须同时提交”，也会将“任选两项”错误确认为普通 OR。本批只修复这条继承入口，不实现 K-of-N 求值，不自动决定矛盾指令谁优先，不处理 case-11 的旧评分器词面映射。

在本批覆盖的有限命名组格式中，修改智能体先检查**命名组到冒号之间**的局部指令。已识别的 AND/OR 冲突、非单项选择、范围及前后数量限定进入复核；原文保留为 candidate ATOM，外层完整关系及 scope 同步 candidate。外层原文明确的 AND 操作符仍可独立 confirmed，这不代表完整关系通过；未冲突的另一组继续 confirmed OR。冒号后的材料名称不进入新增数量检查。新增数量词形和不在本批语法内的指令仍需另行评测，不能从这 15 个样例外推任意数量表达。

产品源码仅改 `document_relations.py`，其他 64 个源码文件未改。最终 Git canonical 源码树 SHA-256 为 `da6ccd4982e25f3e245070c179f37be03bb47dff2f0d680a54d355cfbc1cd1b0`，archive base tree 为 `fceb609894adfa5ce943cfb3e021d4029ec31421`；65/65 源码及 15/15 评测器/测试 blob 与导出字节一致。主审从该副本运行全量测试：**782 passed、1 条既有 Starlette 警告**，Ruff 通过。

| 验证层 | 本轮结果 | 来源校验及范围 |
| --- | --- | --- |
| 开发前冻结的继承专项 | 8/8：3 肯定、5 复核；0 failed/not_run | 来源错误 0/1512；含用户两个反例、阿拉伯数量、第二组冲突及材料名边界 |
| 公开数量边界回归 | 3/3：1 肯定、2 复核 | 来源错误 0/561；“至少两项”“一项以上”不能当普通 OR |
| 公开单位边界回归 | 4/4：2 肯定、2 复核 | 来源错误 0/808；“至少一份”“至多一件”复核，精确“一份”“一件”保留正例 |
| 独立局部/外层状态检查 | 5/5、2/2、2/2 | 原句保留；无错误 confirmed 局部组；外层保留两分支并复核；未冲突 OR 不被误阻断 |
| 既有嵌套、公开严格树、否定专项 | 8/8、2/2、30/30 | 来源错误分别 0/1754、0/448、0/816 |
| 未修改的 1.0.3 总体评分器 | 9/14；5 failed、0 not_run | 来源错误 0/1083；所有 summary 指标与 `74a311e` 相同 |

这 6 个肯定文本和 9 个复核文本的解析判断不能算作企业材料的业务误阻断/误放行率。企业材料与真实模型服务本批均未运行；旧公开原始文件 **0/8、企业 not_run/8** 的历史边界继续保留，本批没有用新增文本评测替代或重新计算它们。第2步整体、通用完整性、生产验收与主体/时间关联仍未通过，`partial/manual_review` 门禁不变。

#### 冻结与回修记录

原 8 份输入于 2026-10-12 09:07:06（Asia/Shanghai）冻结，SHA-256 为 `66be0f0f6337b6be12acc6ddc2a4a00c5cf892d434226db4dd45bf4bd1917d17`，随后才下发开发任务。开发禁止读取私有目录；共享文件系统仅提供策略隔离，不是 certified blind，首次开发读取时间未知。后续 7 份边界样例已向开发公开，只算公开回归；输入没有并入或改写原 8 例 oracle。

原嵌套评分器及 1.0.3 评分器均未改。另行的 `check-local-review.ps1` 在观察旧基线后建立、最终产品执行前冻结，只额外检查原句/节点/外层状态；其冻结说明明确记录“created after baseline”，不冒充开发前的完整盲测评分器。

旧 `74a311e` 的准确导出源码 `e92a0d94…` 用同一专项评分器重放为 **4/8**（3/3 肯定、1/5 复核），全部实际执行，来源错误仍为 0/1934。主审还发现首次补丁吞掉“至少/至多”前缀、再按数字 1 确认的边界问题：重建源码 `ae770c49…` 在单位专项为 **2/4**，来源错误 0/988。该失败报告、65 文件源码 proof、原始 Git patch 与重建说明均保留；可从 `74a311e` 导出并应用 patch 复现，不用最终源码覆盖中间结果。最终补丁显式记录前缀数量限定后通过上述所有专项。

新资产位于 [inheritance-regression/20261012](../benchmarks/document_relations/inheritance-regression/20261012)，含三组 oracle、15 份 raw TXT、冻结说明及局部检查脚本，共 24 件；[inheritance-followup-20261012](../benchmarks/document_relations/reports/inheritance-followup-20261012) 含 21 件报告/proof/patch/测试结果。旧 125 件冻结资产、评分器/测试及历史报告未改写，逐文件 hash 见 [inheritance-publication-record.json](../benchmarks/document_relations/inheritance-publication-record.json)。发布时开发智能体均已关闭；发布后全部新样例均为 public regression。

```powershell
$env:PYTHONPATH = (Resolve-Path ".\src").Path
python scripts/run_document_relations_nested_eval.py --cases benchmarks/document_relations/inheritance-regression/20261012/cases.json --output replay-inheritance-NEW.json
python scripts/run_document_relations_nested_eval.py --cases benchmarks/document_relations/inheritance-regression/20261012/quantity-boundary-cases.json --output replay-quantity-NEW.json
python scripts/run_document_relations_nested_eval.py --cases benchmarks/document_relations/inheritance-regression/20261012/unit-boundary-cases.json --output replay-unit-NEW.json
& benchmarks/document_relations/inheritance-regression/20261012/check-local-review.ps1 -Cases benchmarks/document_relations/inheritance-regression/20261012/cases.json -Report replay-inheritance-NEW.json -Output replay-local-NEW.json
```

所有输出须为新路径。**本轮仅有限指令继承小修通过，`uv.lock` 继续独立处理；case-11 相似度映射、其它范围/完整性问题均不在本次关闭范围内。**

### 历史嵌套专项（2026-10-11）

本批由修改智能体实现、主审独立验收，只关闭明确有限命名组的嵌套表达与来源传递。case-03 保持 `AND(OR(A1,A2),A3)`，case-11 保持 `AND(OR(A1,A2),OR(A3,A4))`；每层直接子节点、操作符、作用域、parent 来源及终结边界分别核验，不以全部后代叶子代替直接子组。

单项要求仍是 ATOM，不额外制造一元逻辑节点。其 `named_singleton_requirement` 是带 `operator=REQUIRED` 的 typed context scope，用于表达本项属于明确命名要求；target 仅指向本项，不是 self-parent，不改变 `children` 或逻辑树。原文引用和边界同时传递到上层。缺组、重复组、未知限定语及不支持的选择方式继续复核；明确的前置否定不升级成肯定外层 AND。

最终 canonical 源码树 SHA-256 为 `e92a0d944c1e610b496638ec3b8dafb902b5ec42375477109eb61052e3d9a643`，archive base tree 为 `d00acf3ef41471293f582956c0439f8383ae88ec`。65/65 源码及 14/14 评测器/测试 blob 与导出副本一致，仅 `document_relations.py` 的产品源码发生变化；主审从该副本运行全量测试，结果为 **767 passed、1 条既有 Starlette 警告**，全仓 Ruff 通过。

| 验证层 | 最终结果 | 解释 |
| --- | --- | --- |
| 验收侧提前冻结的 8 份嵌套合成输入 | 8/8；0 failed、0 not_run | 6 个明确正例均确认；2 个否定/不完整范围样例正确复核；来源错误 0/1754 |
| 同一评分器重放旧 `9f927bb` | 1/8；8 例实际执行 | 正例 0/6，复核例 1/2；来源错误仍为 0/513 |
| case-03、case-11 原始字节的严格树专项 | 2/2；0 未执行 | 操作符、直接子节点及每层来源边界通过；来源错误 0/448 |
| 未修改的原 1.0.3 关系评分器 | 9/14；5 failed、0 not_run | case-03 新通过；case-11 的原子词面映射仍失败；来源错误 0/1083 |
| 既有否定专项 | 24/24 负例、6/6 正例 | 来源错误 0/816；复杂 NOT 仍不自动求值 |
| 结构回归 | 3/3 | 不是条件完整性或企业满足要求验证 |
| 旧公开原始文件完整性 | 0/8；8 例实际执行、0 未执行 | 企业材料仍为 not_run/8 |
| Raw-file 与 reliability 回归 | 原文约束 8/10；27 个固定 mock 判断正确 | hard false release 0/7 仅为有限门禁策略结果，不是资格识别准确率 |

**旧评分器的边界必须单列。** case-11 实际输出四个不同 ATOM 及两层正确条件树，但冻结 1.0.3 以文本相似度匹配“近两年1.9号表”和人工释义“提交近两年编号1.9的表”时未匹配。原始 9/14 报告、该评分器及其 72 项自测都没有改写，不能将结果称为 10/14，也不能将该四项词面未匹配直接当成四条真实解析遗漏。新增严格树评分器使用同一冻结输入原文中的材料名，并另行检查状态、精确来源及直接子节点；它不是原 14 例完整性评分器的替换。评分器互操作问题应另设批次处理。

### 冻结、首次结果与发布

8 份输入在 2026-10-10 21:03:19（Asia/Shanghai）冻结，晚于该冻结时刻才向开发智能体下发任务；开发侧被要求不读取私有验收目录。共享文件系统仅形成策略隔离，**不是技术隔离或 certified blind**，实际首次开发读取时间未知。原 `cases.json` SHA 为 `b396505c…`，输入冻结文件保持原字节。首次执行前另存 `cases-v2.json`，仅明确区分“否定操作符不可确认”和“缺组时完整 scope 不可确认但肯定操作符可识别”；原文、条件树和第一版没有改写。有效输入 SHA 为 `f4c70551…`，说明及时间另存 `oracle-clarification.json`。

评分器及 9 项合成/mock 契约自测先于私有输入执行冻结。评分器 SHA 为 `da7fba3f95cdf52e47bbda80754c624401d74c5a8b7fa36ee455d6492d1c920e`，自测 SHA 为 `8ca99f35f7899c4a4e35c0a9a963f13013f6441ef0fca860167e8bf5446dc0ea`。它拒绝扁平树、额外冲突 confirmed 分组、借用兄弟边界、错误 scope/parent/operator、cycle、零引用分母及覆盖旧报告；执行状态与语义评分独立记录，builder failed 不冒充 not_run。契约自测不代替真实 Registry -> Runtime -> Intake -> Decomposition 运行。

主审保留三轮对应源码，不用最终报告覆盖首次结果：

- 首次公开预验源码 `0ded295a…` 为 8/14；发现 singleton 来源与边界传递缺失后回修。报告、65 源码/12 评测文件 proof 与 exact-byte source overlay 一并保留。
- 首次验收侧 8 例产品执行在源码 `2b14cc2f…` 上得到 8/8，来源错误 0/1738；严格公开树 2/2，但旧 14 例仍 8/14。该轮报告及 65 源码/14 评测文件 overlay 保留。之后仅完善 singleton 的节点级上下文来源通道。
- 最终源码为上述 `e92a0d94…`，有限专项与全量回归通过；旧 14 例为 9/14。

新产物位于 [nested-followup-20261011](../benchmarks/document_relations/reports/nested-followup-20261011)，21 个报告/proof/源码叠加包均纳入版本控制。两份 source overlay 只包含相应 65 源码及 12/14 评测文件，其 ZIP hash 与原完整 Git archive 不同；独立 manifest 逐文件绑定到原 source proof，能够在 `9f927bb` 导出基础上重建对应源码，而不是只保留不可恢复的 staged tree ID。

8 份 raw TXT、原/有效 oracle、冻结及勘误文件和公开专项输入共 16 件位于 [nested-regression/20261010](../benchmarks/document_relations/nested-regression/20261010)。开发智能体停止后发布，发布后均属于 **public regression**；最终重放不冒称新的盲测。原 84 个历史冻结文件/评分器/报告字节不变。完整路径、长度与 SHA-256 见 [nested-publication-record.json](../benchmarks/document_relations/nested-publication-record.json)。

```powershell
$env:PYTHONPATH = (Resolve-Path ".\src").Path
python scripts/run_document_relations_nested_eval.py --cases benchmarks/document_relations/nested-regression/20261010/cases-v2.json --output replay-nested-NEW.json
python scripts/run_document_relations_nested_eval.py --cases benchmarks/document_relations/nested-regression/20261010/public-nested-cases.json --output replay-public-nested-NEW.json
```

输出路径须从未存在。raw-file/reliability 报告自身不含源码 hash，绑定来自本轮 source proof 和明确指向 canonical export/src 的执行环境。有限合成文本、真实 Registry 链路和 mock 写作结果都不能外推真实 PDF、扫描件、任意语义或真实模型准确率。关系 14 例企业材料仍为 not_run/14，本批 8 例与专项 2 例也没有企业材料，因此不计算业务误阻断/误放行率。

**第2步整体、跨页/跨章节范围、主体与时间关联、通用完整性和生产验收继续未通过；`partial/manual_review` 门禁保留；`uv.lock` 未纳入提交，另设环境复现任务。**

### 历史否定专项（2026-10-10）

用户独立复查发现否定cue可导致关系被错误标记为`confirmed`。本轮记录的反例类型仅包括前置“不需要”“不要求”和后置“无需”；待验收对象是系统对这些否定cue所涉关系的表达与状态判定，不是业务误放行。来源坐标、引文和字符范围有效，只能证明source reference与原文相符，不能证明关系semantics正确。

R4当时的关闭判断在复查`7ed381c`后重新打开。本次由修改智能体统一前置、单行及后置回指的否定检查，主审独立完成正式Git导出复验；**仅关闭这批有限否定入口问题，不关闭第2步整体、通用完整性或生产验收。** 不把否定AND推断成OR或已执行的NOT条件；未支持语义保留带原文证据的`candidate/unresolved`，否定指令被标为标题时也不丢弃。下文R4的`8/14`、`679 passed`及旧source proof继续作为历史记录，旧报告没有改写。

本次canonical源码树SHA-256为`76b23ab8d386616677b424f3f9e97f0b1b04ffae7b2809b0107fb406b2bde6c0`，archive base tree为`14463a4f87df5b468b6a52f4e713c58f1857649f`；65/65源码blob与11/11评测器/测试blob匹配。只有`document_relations.py`的源码字节发生变化，其余64个源码文件保持原样。正式导出副本全量测试为**743 passed、1条既有Starlette警告**，全仓Ruff通过。

专项固定30例为八种否定词（不需要、不要求、不需、无需、无须、不必、不得、不须）分别覆盖前置、真正的单行表达式及后置回指，另有三入口各一例肯定AND与OR。真实Registry -> Runtime -> Intake -> Decomposition执行结果为负例`24/24`、正例`6/6`，`0 failed`、`0 not_run`、source_invalid`0/816`。负例既检查所有逻辑组及内层操作符没有错误confirmed，也要求否定原文留在候选关系中；肯定例必须保留两叶、confirmed操作符及作用域，不能全candidate通过。结构清单的confirmed归属不等于confirmed逻辑操作符。

同一专项评分器在旧`7ed381c`的精确源码导出副本（旧SHA `c96529dc…`）上得到负例`10/24`通过、`14 failed`，正例`6/6`通过、`0 not_run`；全部`1315`条引用仍有效。这再次证明来源有效不能证明关系语义正确。专项是公开人工回归，不是未见语料或企业材料评测，不计算业务误阻断/误放行率；复杂NOT、嵌套分组、跨页范围及主体时间关联仍未完成。

原14例关系评测在新canonical上仍为`8/14`、`6 failed`、`0 not_run`、source_invalid`0/724`，整份summary与R4相同；评分器仍为冻结的`1.0.3`，未改oracle或原72项评分器自测。结构评测`3/3`；旧公开原始文件`0/8`，8例实际执行且全部未通过、业务`not_run/8`；raw-file原文约束`8/10`、hard false release`0/7`，六类新逻辑仍须人工核验。27个既有模拟模型reliability案例的正负判断保持正确，不能外推真实模型或生产准确率。关系14例企业材料仍为`not_run/14`，`uv.lock`不纳入。

新报告另存于`benchmarks/document_relations/reports/negation-followup-20261010`：

| 产物 | 结果 | SHA-256 |
| --- | --- | --- |
| [否定专项](../benchmarks/document_relations/reports/negation-followup-20261010/negation-score.json) | 24负例与6正例均通过；0未执行 | `33c851cdc3cad24146ca263e092a17acca093c349f702d0d5f5163b43dd76e08` |
| [旧源码专项重放](../benchmarks/document_relations/reports/negation-followup-20261010/baseline-negation-score.json) | 16通过、14失败、0未执行；绑定旧源码 | `917ee6839ee5747d4f0b36e6531663512e1203ed3f4ca7c0b2cbfb8cb112422e` |
| [关系复验](../benchmarks/document_relations/reports/negation-followup-20261010/relations-score.json) | 8通过、6失败、0未执行 | `4f733f5879bceb8d5147144f60e3236411a5018b700477260a52ad17dfcf5a89` |
| [结构复验](../benchmarks/document_relations/reports/negation-followup-20261010/structure-score.json) | 3/3通过 | `7b786f3c0d1e744efbd3b4de9dbe4c1f5858e9b8192562bbdb0ac1fa75a3ba1c` |
| [旧公开文件复验](../benchmarks/document_relations/reports/negation-followup-20261010/old-public-score.json) | 0/8；0未执行；业务未运行 | `f9341bab8e0a4514da1860b36d1daa882c6ee5f7e0431f354ec50a99be6daf16` |
| [Raw-file复验](../benchmarks/document_relations/reports/negation-followup-20261010/raw-file-score.json) | 原文约束8/10；hard false release 0/7 | `293013a89f8b9a8727c04975bf0080d31f76be45901671b316f7897a751c5bcb` |
| [Reliability复验](../benchmarks/document_relations/reports/negation-followup-20261010/reliability-score.json) | 27个固定模拟案例判断正确 | `101b76740fccf47100e0737ca5a536611b11143bb23bac30efacaae4c7c1d79c` |
| [本次source proof](../benchmarks/document_relations/reports/negation-followup-20261010/source-proof.json) | 65源码及11评测/测试blob匹配 | `11ad2384b9e826940a0da04437b2d326236b949f00ffe5f1a1e804ac717cf48f` |

专项评分器`run_document_relations_negation_eval.py`的SHA-256为`245871311639815ad0ec35fb7d06f27d2c43b4afe450327902be559570733e43`，6项契约自测的SHA-256为`1b7637a57c2c941e933870907f829f8031646364f22a96671a97c53d38a5cbed`。正负预期冻结在该脚本中；报告保留每例输入、预期、未归一化actual graph与注册来源上下文。raw-file及reliability报告自身不含源码hash，本次源码绑定依靠上述source proof和显式指向canonical export/src的执行上下文。

复现时从所验证的源码导出根目录执行，输出必须是新路径：

```powershell
$env:PYTHONPATH = (Resolve-Path ".\src").Path
python scripts/run_document_relations_negation_eval.py --output replay-negation-NEW.json
python scripts/run_document_relations_eval.py --bundle benchmarks/document_relations/reserved/v2 --output replay-relations-NEW.json --main-reviewer-authorized
```

首次有效产品评分由主审在源码树SHA-256 `93ad62e4729baedb9f149a781afa8b712987e9424818a4a5c82052af25d2b417` 上执行：`0/14 passed`、`14 failed`、`0 not_run`，14例全部实际运行。严格来源校验发现`103/194`条产品引用的locator与裁剪后的char bounds不一致；这是产品输出的真实问题，未放宽或归一化。首次有效报告和source proof均原样发布并保留。grader后续契约修正不会覆盖该历史结果。

**R4最终canonical**由主审在源码树SHA-256 `c96529dc1fbf531aaac92e46f0e259ea24b2d64625f50fdd2d4fe981d41f485f`上执行，grader `1.0.3`结果为`8/14 passed`、`6 failed`、`0 not_run`。source proof SHA-256为`819b8ebe322da3c814a26fd4e370437d504df2c2c933be8ed2fe4a80a03a8831`，archive base tree为`35f5faafa934f5ffe7f014440c8a3c827ebfd499`；65/65源码blob及9/9评测器/测试blob匹配。canonical导出源码测试为679 passed、1条既有Starlette警告，Ruff通过。R3在相同产品源码SHA、grader `1.0.2`下为`7/14`；7到8是operator关系布局适配导致的评分器契约差异，不是产品提升。

| 产物 | 结果 | SHA-256 |
| --- | --- | --- |
| [R4关系评分](../benchmarks/document_relations/reports/final-20261010/relations-score.json) | 8通过、6失败、0未运行 | `6ef9a977ff5525b2a656485faaf716d9f0ed4b7ce44e94c34272f3b6322c9921` |
| [结构评分](../benchmarks/document_relations/reports/final-20261010/structure-score.json) | 3/3通过 | `f7f337511cf8caaed03765446631c9e513b1919d11f18bf76564b154d6c4f231` |
| [既有公开原始文件完整性评分](../benchmarks/document_relations/reports/final-20261010/old-public-score.json) | 8例全失败、0未运行；业务not_run/8 | `b986ab89803305b9d4d2038eeb7843f30c39580b228562f1f406719c2160efb8` |
| [Raw-file评分](../benchmarks/document_relations/reports/final-20261010/raw-file-score.json) | 必要原文约束8/10；hard false release 0/7 | `f3c06b4fb8d74bc5c46fd553ab93d7ccd3169a2cd76bfaed8f28b3e63aba694e` |
| [Reliability评分](../benchmarks/document_relations/reports/final-20261010/reliability-score.json) | writing正6/6、负12/12；runtime正2/2、负7/7；误阻断/误放行均0 | `7eda6dd6d4cb238c9b04a8fab4241f351377be4b5be8ae9e03644a3ec51036dc` |
| [R4 source proof](../benchmarks/document_relations/reports/final-20261010/source-proof.json) | 65/65源码与9/9评测器/测试blob匹配 | `819b8ebe322da3c814a26fd4e370437d504df2c2c933be8ed2fe4a80a03a8831` |
| [R3 operator适配前评分](../benchmarks/document_relations/reports/pre-operator-adapter-20261010/relations-score.json) | 同一产品源码、grader 1.0.2：7/14 | `6fa93b74cf4c53344221f14a0da9322945de39c8cd9277650a9e931c6cfed56f` |
| [R3 source proof](../benchmarks/document_relations/reports/pre-operator-adapter-20261010/source-proof.json) | 同一源码树SHA；archive base不同 | `e44d68dc5ed4b890cc44703664fdf454dc0d723b352ce318975989d080394c8d` |

R4关系失败项为case-03、07、09、11、12、13，具体主题列于[基准README](../benchmarks/document_relations/README.md)。case-11未解析的是两组材料AND(OR, OR)嵌套；case-13的`contextual_scope_no_flat_operator`财务说明与收入属性上下文绑定未解析，1.10金额只是反例背景，额外非法原子为0。主要指标为原子遗漏`6/37`、错并`0/34`、错拆`0/37`、scope成员错误`21/50`、operator结构错误`6/14`、source_invalid`0/724`、review-handling errors`0/19`。`forbidden`为`1/16`，由显式跨页成员未完整识别导致，不是业务误放行率。有限scope可confirmed；K-of-N scope仍为candidate，operator与semantic parent为unresolved。**R4当时的有限关闭判断仅属历史；本次否定专项结论见上文，Step 2整体、通用及生产完整性仍未关闭。**企业材料`not_run/14`。

R4评估parent、scope、reference的confirmed/candidate/unresolved关系，以及有原文依据的AND/OR作用域。编号层级本身不是业务AND，也不是已确认的语义parent。主体、同人、时间及复杂NOT不在范围内。所有运行输入都是人工构造的UTF-8 TXT，非实际企业材料，也非业务PDF。

输入TXT是唯一注册到真实Registry的文件。Markdown oracle和machine oracle只由评分器读取，不进入Registry、Runtime、Intake或Decomposition。评分链路为Registry -> Runtime -> TenderIntake -> TenderDecomposition，结果取自decomposition的`document_relations`与`relation_analysis`。

### Skill与来源身份边界

下游Skill和调用方必须区分来源坐标与来源身份：`source_reference_status=verified`只表示引文、页行及字符位置与原文坐标自洽；`source_identity_status=registry_verified`才表示身份对应真实Registry注册的文件及版本；`caller_asserted`只表示调用方给出的身份声明，不能当作Registry核验。三者不能互相替代，也不授予访问、处理或写作授权。即使关系graph通过验收，也不代表企业材料已满足要求，更不等于允许生成或提交投标内容；业务资格和写作授权必须由独立的业务证据及授权流程决定。

据主审转述，独立D曾在同一R4源码树SHA上无mock复验当时列出的四类有限探针及candidate helper：否定条件、外部条号与本清单条号、本构造器未知六级结构、来源身份；在这些实际探针中未发现错误confirmed。该结论是绑定`c96529dc1fbf531aaac92e46f0e259ea24b2d64625f50fdd2d4fe981d41f485f`及其有限探针范围的历史观察，不是企业材料验收或写作授权，也不覆盖用户本轮提出的前置“不需要”“不要求”和后置“无需”三类反例。新反例已表明旧D结果不能外推为这些否定cue处理正确或当前专项通过。

共享文件系统只能形成策略隔离，不是技术隔离，也不是certified blind。A/B以`fork_context=false`分别于2026-10-09约14:44（Asia/Shanghai）启动，晚于v2在14:42:19.892冻结；冻结时未获准读取私有语料。14例及其oracle现已发布，并只称public regression。发布时刻、A/B读取授权时刻及实际首次读取时间状态记录在[publication-record.json](../benchmarks/document_relations/publication-record.json)：`first_read_at`为null/未知；先前的`08:59:30`仅为A自报且已撤回，不能作为实际读取时刻。授权时间不冒充实际读取时间。

## 冻结沿革

评分沿革保留两个版本；只将v2作为规范运行输入：

| 版本 | 分类 | 指纹 | freeze.json SHA-256 | 发布路径与处理 |
| --- | --- | --- | --- | --- |
| v1 `.qiaowenshu/acceptance/private-condition-relations-20261009` | `rejected-annotated-container` | `a60343e423e1ba28c4cf7d43c8a5e771f978640234c8206ba54b9899b3ce518f` | `294e0c028279a308cdf8571ef6f090501a31bfb0ab7d8f329199d926723a81e0` | 原字节发布于`benchmarks/document_relations/reserved/v1`；因容器注释行使page/line不对应运行输入物理坐标，在产品评分前拒绝，不能作为有效输入计分。 |
| v2 `.qiaowenshu/acceptance/private-condition-relations-v2-20261009` | `normative-clean-input` | `eb7322ccbdafba33db9ab17a6bc35c793fdce2ff9cb0bad82a38d5920e0d6864` | `14072deebb73f993759272f19ca687649903c201b49f0d5ff78ede926a8dfcb2` | 原字节发布于`benchmarks/document_relations/reserved/v2`；14份清洁TXT、14份MD oracle及machine oracle，是规范运行输入。 |

两版语义答案未改变。v2迁移只清除了输入容器标记并将坐标指向清洁TXT的真实物理page/line；source引用在冻结时逐条校验。评分器按v2固定manifest SHA、payload SHA/长度和排序指纹校验，另以原始TXT独立复核oracle引用坐标。

**冻结metadata勘误：**冻结manifest的`developer_status_at_freeze`写有“A/B remain paused per user”，措辞不准确。冻结时A/B尚未创建或启动，用户也未显式要求暂停。两名agent约于14:44 forkfalse启动，晚于v2冻结，且未获私有目录读取权限。此勘误仅记于本文和发布record；不修改已冻结manifest或其SHA。

## 固定评分规则

- 每个冻结source引用均按输入字节解码后的真实页、物理行和引文复核；递归引用总数按冻结分母统计，重复引用另报unique数。
- 每条产品source reference须与该次Registry注册文件的docid/version一致；page和char bounds须为严格整数，char slice须逐字等于quote且落在同一物理行。grader从已注册raw page text和零基`char_start`独立推导物理行；若产品提供`line`/`line_number`，必须与推导值一致。`locator`若为`pN:cSTART-END`，也必须与page及offset一致。缺line时只在独立deep-copy scoring shadow graph中添加派生`line_number`，原产品graph不改写或伪称已有line。任何无效产品source reference单独计入`source_invalid`分子/分母，并使case失败。此检查由grader直接对注册的原始TXT完成，不调用被测domain验证器。
- 条件按page/line、精确引文片段及条件文本一对一匹配；quote允许是oracle长引文中的合法精确子片段。共享block不合并原子。一个ATOM覆盖多个confirmed原子会计入错误合并；一个原子映射到多个confirmed ATOM会计入错误拆分。条件遗漏与合并使用各自冻结分母，可在同一case重复计数，互不替代。
- confirmed AND/OR按每层直接children、operator、status和来源证据比较。`operator_relation.source_references`必须逐项对应冻结`boundary_basis`中的同类显式AND/OR cue；只引用相反操作词或材料名，即使group其他refs含正确cue也失败。`scope_relation.source_references`、成员节点source及`boundary_source_references`分别核验；scope来源须锚定冻结边界或对应成员原文，termination boundary须覆盖冻结边界。所有实际引用另由grader对注册TXT逐条验证doc/version、物理行和原始字符偏移。缺失嵌套层或把树压平成叶节点集合均失败。semantic parent可由confirmed condition-node/scope成员图佐证；legacy物理block parent不能单独证明confirmed语义parent。
- 单项`REQUIRED`允许由confirmed ATOM表达，也允许保留带confirmed来源依据的一元AND边界。
- `forbidden`按冻结claim方向判定。scope类区分“必须包含明确成员”“禁止错误并组”和“禁止确认未完整范围”，不能把`members`集合统一解释为禁止并组。明确禁止“并成一个组”的claim按AND/OR直接children检查；合法`AND(OR(A,B),OR(C,D))`祖先含有全部叶节点但不构成扁平并组，只有将这些成员直接压入一个AND/OR节点才违规；已匹配冻结expected group的节点不自我判违规。编号/金额类condition负例只检查同源位置上未匹配oracle、且把数值误生成为材料/编号条件的额外confirmed ATOM；不因同一行存在合法预算原子而禁止它。
- confirmed正例必须confirmed；candidate/unresolved按oracle状态进入复核覆盖。全candidate不能通过显式正例。缺失必要关系与实际执行失败分别记为failed；只有未执行的关系分析记为not_run，不计为通过。
- `operator_group_structure`按每个case内唯一confirmed AND/OR group id计失败单位；不把error条数当失败单位。REQUIRED不纳入该比例的分子或分母。原始重复错误条数单独列在`event_counts`，明确为非比例事件计数。所有比例型metric均须满足`0 <= numerator <= denominator`；零分母记`not_applicable`。
- report列出每case状态、错误和各真实分母。企业/业务材料固定为`not_run/14`，不计算业务通过率、误阻断率或误放行率。已执行case须保留未归一化的`actual_graph`及`source_context`（注册输入SHA、版本、页文本和form-feed分隔符），以便在不重跑产品pipeline的情况下复核同一输出。

## 评分器契约勘误

初始无效报告发布于`benchmarks/document_relations/reports/initial-invalid-evaluator/first-score.json`，其source proof在同目录，均按原字节保留。报告SHA-256为`be7ab34ceec03e0e2f39e0a8457e23b0d209653f625a897da673fbf0bd2c4b5a`；proof SHA-256为`fbfa9fa4115fba0e3506cbe225e56469219d9f9c0d76ed9fd064034d50a8b453`。该无效报告的`0/14`、`source_invalid 194/194`及`condition_omission 37/37`由grader错误要求产品引用必须自带line字段引起；合法Registry引用可仅提供`page`、`locator=pN:cSTART-END`、char bounds和quote。此结果是grader互操作失败，不能解释为产品行为。

首份报告的`operator_group_structure 17/14`也不是有效比例：旧实现按error条数计分，分子混入多个组单位及非confirmed组。修正版只按confirmed AND/OR唯一组单位计比例，REQUIRED不混入；重复error保留为`group_structure_error_events`非比例计数。冻结oracle原子、作用域和其他语义分母均不变。

scope的`prohibit_merge`修正为检查产品AND/OR节点的直接children，不再用后代叶节点集合判断。合法嵌套OR子组的AND祖先不会因包含全部叶成员而误判；将同一组成员扁平化为全AND或全OR直接children会被记为违规。

修正grader后，主审在相同产品源码快照重新执行pipeline，得到首次有效评分；这不是对旧输出的离线精确重评。初始无效报告未保留`actual_graph`或`source_context`，无法据此离线重评。首次有效报告位于`benchmarks/document_relations/reports/first-valid/first-valid-score.json`，source proof在同目录；SHA-256分别为`281c34dc9af8f36f5648731afa132d03e4fa5a5598e43cd052de1f623e294d76`和`5eb6419bab8b8f1435a55a076359614c1d83708bd8242cca39b0846a2231ba32`。结果为`0/14 passed`、`14 failed`、`0 not_run`；`source_invalid=103/194`源于产品references沿用整块locator、char bounds却裁剪到span。该定位不一致按真实产品输出计错，未放宽校验。首次有效报告保留未归一化`actual_graph`和注册`source_context`，可供主审复核；本轮不自行重放它。

两份评分的source proof对应同一source tree SHA-256 `93ad62e4729baedb9f149a781afa8b712987e9424818a4a5c82052af25d2b417`，但archive base各自不同：初始无效报告的proof为`803ccb0ef95d343bd9eba7a7cf866e99a2e95357`；首次有效报告的proof为`3c5fd779cfdc7c988d4bf719168fc03ad8c2a435`。两份proof均记录65/65 source blobs及9/9 evaluator/test blobs匹配。后续typed-parent修改是grader契约兼容勘误，不改冻结语义、首次报告或产品结果。

**Typed parent适配勘误：**case04/05的confirmed parent表示显式文本清单中的可见条目归属，不要求confirmed逻辑scope，也不要求AND。grader将结构清单关系与semantic parent分层处理：结构关系须带明确layer和basis、confirmed有向成员边指向真实存在的共同目标，且目标实体自身来源支持冻结原文中的显式清单cue；不能用目标不存在的相同ID、借用quote或仅把既有physical parent状态改为confirmed来通过。semantic parent同样要求明确语义layer/basis、正确方向和来源覆盖。case09/13的`attribute_scope`及`contextual_scope_no_flat_operator`可直接承载属性/上下文scope，不捏造AND。新增正负grader自测为公开合成fixture；oracle和first-valid报告字节均不变，也未从产品结果调整答案。

**执行分类勘误（grader 1.0.1）：**成功或部分成功的decomposition步骤若在`relation_analysis`中标记`not_run`，但`unprocessed_structures.reason=builder_failed`，必须归类为`failed`，记录已尝试但构建失败；明确`no_document_structures`以及真实跳过/未配置仍归类为`not_run`。新增公开mock测试覆盖builder失败与无文档结构两种情形。此修正只影响执行分类，不改oracle、first-valid历史报告或产品输出。评分器维护智能体在1.0.1该勘误阶段未运行产品评分；这不代表项目整体未评分。

**Candidate原文映射勘误（grader 1.0.2）：**只对冻结oracle标为`certainty=candidate`的原子增加严格source-literal后备映射：actual text须包含精确冻结`source.quote`；同页/行的实际source quote须包含该引文，且来源引用须通过原始char坐标验证。该路径不依赖oracle中“可能/对象不明”等复核解释文字。实际节点status仍独立核对，confirmed不能冒充candidate；一对一匹配以及confirmed原子的错并/错拆计量保持不变。错quote、错行、坏offset或无关text均不能通过，不降低全局相似度阈值，也不对confirmed原子启用字面后备。新增公开自测覆盖candidate正例及这些负例、状态升级和同源双candidate单节点。此grader契约修正不改冻结oracle、首次有效报告/proof或任何开发评分。评分器维护智能体在1.0.2该勘误阶段未读取产品图或运行产品评分；这不代表项目整体未评分。A开发后的后续重放应另称public regression，并记录实际新src SHA，不解释为本次修正带来的产品提升。

**Operator review布局勘误（grader 1.0.3）：**operator review覆盖从`condition_nodes[].operator_relation`、节点`scope_relation.operator_relation`、`block_relations[].scope_relations[].operator_relation`及显式`block_relations[].operator_relations`收集。每条均只使用自身status和`source_references`；不得从包装层`scope.status`或裸`operator_status`推断操作符状态。包装层显式给出的`operator_status`若与内层关系status冲突，该记录不作为证据。新增合成自测覆盖四种关系通道，以及scope unresolved不能提升candidate operator、裸状态字段无来源不构成证据、错来源和包装状态矛盾拒绝。此修正仅补齐grader数据布局契约，不改domain、oracle、旧报告或source校验。评分器维护智能体在该维护阶段未运行产品评分；主审随后以该版本完成R4 canonical。

## 运行与报告

从仓库根目录复现关系评分时，使用公开入库v2 bundle，并显式将`PYTHONPATH`指向待复现源码导出的`src`目录。复现结果须写入新路径；不能用旧私有bundle路径或覆盖已发布报告：

```powershell
$env:PYTHONPATH = (Resolve-Path ".\src").Path
python scripts/run_document_relations_eval.py `
  --bundle benchmarks/document_relations/reserved/v2 `
  --output benchmarks/document_relations/reports/replay-NEW.json `
  --main-reviewer-authorized
```

R4各评测执行时均显式令`PYTHONPATH`指向canonical export的`src`；raw-file与reliability报告本身没有内置src hash，其源码绑定来自source proof和export上下文，不应称报告自身含有该hash。以上命令是复现方式，不表示本次重新运行；本次R4已由主审执行。输出路径必须是新路径，runner拒绝覆盖已有报告。运行报告记录真实时间、Git revision/worktree状态、按既有binarydigest规则计算的`src/**/*.py` SHA-256、评分器自身SHA-256、冻结manifest/payload验证、来源坐标验证、v1/v2输入沿革及每case详情。该flag是调用者对主审授权的显式确认，不构成身份或技术隔离证明。

原始冻结件及历史、R3、R4报告/proof均逐文件核对长度与SHA-256并按原字节发布。发布后14例属于public regression，不再称unseen或blind holdout。`.gitattributes`对每个CRLF冻结payload、proof及R4 raw/reliability报告精确设置`-text whitespace=cr-at-eol`；LF评分JSON仅设置精确路径`-text`并继续检查真实尾随空格，没有目录级空白豁免。runner以`create_only`方式创建新报告，拒绝覆盖已有目标；不声称文件系统层只读或防篡改。

评分器接口现冻结为version `1.0.3`、report schema `document-relations-acceptance-eval-v1`。脚本SHA-256为`26330942263746e6794deb7def70e17f4848bb64f2fe7ebb4011f5784ca57483`，公开自测SHA-256为`7fb5e3694d8614e962c6061e50d2de8b15c29a2bc6d02e808048f161ac371228`；公开自测72项通过，当前Python环境另有1条`asyncio_mode`未知配置警告，Ruff通过。1.0.2的脚本/测试SHA-256 `3ed8831e0ceb6e070c1be6954d0159cc9811eb9aede20d9833298189e356f02c` / `4dd8484172dd755050c01924d5b80887481d35b6f0c10bf2be5f19b6bd75cb38`及64项测试记录为历史版本；1.0.0/1.0.1沿革同样保留在publication record中。历史报告未改写。接口需传`--bundle`与新的`--output`，主审产品评分另显式传`--main-reviewer-authorized`。任何后续评分器改动都必须升级版本并重新记录hash；主审后续重评使用1.0.3。

既有验收结论保持原样：**既有公开原始文件完整性评测8例实际运行且全失败（`0/8`，`0 not_run`）**，企业材料`not_run/8`，通用及生产验收未通过。该`0/8`不是本批关系状态评测结果。本批企业材料为`not_run/14`，不计算业务通过率、误阻断或误放行。本文件不改写历史报告，也不改变`uv.lock`。
