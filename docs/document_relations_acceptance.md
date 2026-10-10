# 文档关系验收

## 状态与边界

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

R4关系失败项为case-03、07、09、11、12、13，具体主题列于[基准README](../benchmarks/document_relations/README.md)。case-11未解析的是两组材料AND(OR, OR)嵌套；case-13的`contextual_scope_no_flat_operator`财务说明与收入属性上下文绑定未解析，1.10金额只是反例背景，额外非法原子为0。主要指标为原子遗漏`6/37`、错并`0/34`、错拆`0/37`、scope成员错误`21/50`、operator结构错误`6/14`、source_invalid`0/724`、review-handling errors`0/19`。`forbidden`为`1/16`，由显式跨页成员未完整识别导致，不是业务误放行率。有限scope可confirmed；K-of-N scope仍为candidate，operator与semantic parent为unresolved。**本批基础关系状态与有限显式AND/OR可按限定范围关闭；Step 2整体、通用及生产完整性仍未关闭。**企业材料`not_run/14`。

本轮只评估parent、scope、reference的confirmed/candidate/unresolved关系，以及有原文依据的AND/OR作用域。编号层级本身不是业务AND，也不是已确认的语义parent。主体、同人、时间及复杂NOT不在范围内。所有运行输入都是人工构造的UTF-8 TXT，非实际企业材料，也非业务PDF。

输入TXT是唯一注册到真实Registry的文件。Markdown oracle和machine oracle只由评分器读取，不进入Registry、Runtime、Intake或Decomposition。评分链路为Registry -> Runtime -> TenderIntake -> TenderDecomposition，结果取自decomposition的`document_relations`与`relation_analysis`。

### Skill与来源身份边界

下游Skill和调用方必须区分来源坐标与来源身份：`source_reference_status=verified`只表示引文、页行及字符位置与原文坐标自洽；`source_identity_status=registry_verified`才表示身份对应真实Registry注册的文件及版本；`caller_asserted`只表示调用方给出的身份声明，不能当作Registry核验。三者不能互相替代，也不授予访问、处理或写作授权。即使关系graph通过验收，也不代表企业材料已满足要求，更不等于允许生成或提交投标内容；业务资格和写作授权必须由独立的业务证据及授权流程决定。

据主审转述，独立D在同一R4源码树SHA上无mock复验四类边界问题及candidate helper：否定条件、外部条号与本清单条号、本构造器未知六级结构、来源身份；未发现错误confirmed。该结果仅绑定`c96529dc1fbf531aaac92e46f0e259ea24b2d64625f50fdd2d4fe981d41f485f`，不是企业材料验收或写作授权，也不外推到其他源码版本。

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
