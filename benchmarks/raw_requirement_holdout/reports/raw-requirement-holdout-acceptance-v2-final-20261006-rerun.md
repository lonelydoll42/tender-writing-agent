# Raw Requirement Holdout Acceptance v2 Final

- 状态：`completed`
- 历史错误报告：`invalid-validator`，未覆盖。
- parser 数据源：`step_data[step.skill_name] = step.result.data`，整体 failed/partial 不阻断 decomposition 评估。
- business evidence：`not_run`，分母 8；不换算为 FalseBlock 率。
- 输入/oracle hash：`True`；产品 hash：`True`。

## 逐例结果

### H01 holdout-01-qualification-finance.txt
- runtime：`completed`；decomposition step：`success`；parser：`executed`；requirements：`2`
- 缺失锚点诊断：`['营业执照', '法人登记', '2025', '审计', '银行资信', 'OR']`
- oracle 语义评估：`partial`；保留：仅保留两条材料标题，未保留营业执照/法人登记 OR、审计关键页/银行资信 OR 的必要条件。
- 逻辑遗漏：`['主体证明 OR 分支', '财务/资信 OR 分支', '2025 审计关键页约束']`；解释：`manual_review_required`；source refs：`2`
- source refs：`[{"document_id": "file_27559fff58464254", "file_id": null, "page": 1, "source_version": "file_27559fff58464254:v1", "quote": "1.1 投标人应提交以下主体证明材料之一：", "locator": "artifact_file_27559fff58464254_1:p1:l7", "actual_line": 7, "raw_file": "holdout-01-qualification-finance.txt"}, {"document_id": "file_27559fff58464254", "file_id": null, "page": 1, "source_version": "file_27559fff58464254:v1", "quote": "2.1 投标人应提供下列材料之一：", "locator": "artifact_file_27559fff58464254_1:p1:l15", "actual_line": 15, "raw_file": "holdout-01-qualification-finance.txt"}]`

### H02 holdout-02-legal-credit-table.txt
- runtime：`completed`；decomposition step：`success`；parser：`executed`；requirements：`2`
- 缺失锚点诊断：`['法人登记', '2025/02/28']`
- oracle 语义评估：`partial`；保留：保留了 OR 说明、有效性与银行资信日期，但没有完整提取法人登记有效分支和营业执照过期分支。
- 逻辑遗漏：`['法人登记分支', '营业执照过期事实', 'OR 两分支的结构化闭合']`；解释：`manual_review_required`；source refs：`2`
- source refs：`[{"document_id": "file_fa52f574bef442e8", "file_id": null, "page": 1, "source_version": "file_fa52f574bef442e8:v1", "quote": "说明：A、B 是二选一的 OR 分支；只要 A 有效，本项即可成立，不得因缺少一份新的营业执照而判定不合格。统一社会信用代码、办公地址和法定代表人姓名仅为核对信息。", "locator": "artifact_file_fa52f574bef442e8_1:p1:l11", "actual_line": 11, "raw_file": "holdout-02-legal-credit-table.txt"}, {"document_id": "file_fa52f574bef442e8", "file_id": null, "page": 1, "source_version": "file_fa52f574bef442e8:v1", "quote": "2.1 银行资信证明由开户银行于 2026-08-17 出具，明确写有“资信状况良好”，可作为本项材料。", "locator": "artifact_file_fa52f574bef442e8_1:p1:l15", "actual_line": 15, "raw_file": "holdout-02-legal-credit-table.txt"}]`

### H03 holdout-03-manager-social-positive.txt
- runtime：`completed`；decomposition step：`success`；parser：`executed`；requirements：`2`
- 缺失锚点诊断：`['2026']`
- oracle 语义评估：`partial`；保留：保留证书条件和 AND/连续六个月提示，但未把同一自然人、同一投标人及 2026-03 至 2026-08 月份集合结构化。
- 逻辑遗漏：`['同一自然人约束', '同一投标人约束', '六个月时间范围']`；解释：`manual_review_required`；source refs：`2`
- source refs：`[{"document_id": "file_e82bdb9aa65343c2", "file_id": null, "page": 1, "source_version": "file_e82bdb9aa65343c2:v1", "quote": "1.1 拟派项目经理须持有“信息系统项目管理师”证书，证书姓名应与投标文件中的项目经理姓名一致；并由", "locator": "artifact_file_e82bdb9aa65343c2_1:p1:l7", "actual_line": 7, "raw_file": "holdout-03-manager-social-positive.txt"}, {"document_id": "file_e82bdb9aa65343c2", "file_id": null, "page": 2, "source_version": "file_e82bdb9aa65343c2:v1", "quote": "1.2 本条是 AND 关系：证书条件和同人、同一投标人、连续六个月的社保条件必须同时满足。只提供任意一项不能通过。", "locator": "artifact_file_e82bdb9aa65343c2_1:p2:l3", "actual_line": 12, "raw_file": "holdout-03-manager-social-positive.txt"}]`

### H04 holdout-04-manager-social-gap.txt
- runtime：`completed`；decomposition step：`success`；parser：`executed`；requirements：`1`
- 缺失锚点诊断：`['信息系统项目管理师', 'AND']`
- oracle 语义评估：`partial`；保留：保留同人连续社保、王珊不得填补陈立缺口及不可跨人拼接。
- 逻辑遗漏：`['证书条件的完整文本', 'AND 结构字段', '2026-03 至 2026-08 的完整月份约束']`；解释：`manual_review_required`；source refs：`1`
- source refs：`[{"document_id": "file_51a99647ad114e8f", "file_id": null, "page": 2, "source_version": "file_51a99647ad114e8f:v1", "quote": "项目负责人资格要求同时包含证书和 2026/03-08 的同人连续社保。王珊的单月记录不得用来填补陈立的 2026 年 05 月缺口；不得把两个人的记录拼成一个满足项。", "locator": "artifact_file_51a99647ad114e8f_1:p2:l11", "actual_line": 22, "raw_file": "holdout-04-manager-social-gap.txt"}]`

### H05 holdout-05-identity-oauth-no-replace.txt
- runtime：`completed`；decomposition step：`success`；parser：`executed`；requirements：`1`
- 缺失锚点诊断：`['OAuth', 'OIDC', 'AND']`
- oracle 语义评估：`partial`；保留：保留禁止替换条件。
- 逻辑遗漏：`['OAuth2.0/OIDC OR 协议条件', '与现有身份系统完成对接', '两个条件的 AND 结构']`；解释：`manual_review_required`；source refs：`1`
- source refs：`[{"document_id": "file_55dff5c2c58947f7", "file_id": null, "page": 1, "source_version": "file_55dff5c2c58947f7:v1", "quote": "（b）不得以新建登录中心、迁移账号或其他方式替换采购人现有身份系统。", "locator": "artifact_file_55dff5c2c58947f7_1:p1:l13", "actual_line": 13, "raw_file": "holdout-05-identity-oauth-no-replace.txt"}]`

### H06 holdout-06-identity-replacement-negative.txt
- runtime：`completed`；decomposition step：`success`；parser：`executed`；requirements：`1`
- 缺失锚点诊断：`['导入', '关闭', '不得']`
- oracle 语义评估：`partial`；保留：保留 OAuth2.0/OIDC 与替换冲突的叙述，并识别为 manual_review/partial。
- 逻辑遗漏：`['迁移账号事实', '关闭原登录入口事实', '新 IAM 独占认证事实的独立结构']`；解释：`manual_review_required`；source refs：`1`
- source refs：`[{"document_id": "file_198c3bf31cb94383", "file_id": null, "page": 1, "source_version": "file_198c3bf31cb94383:v1", "quote": "本方案确实列出了 OAuth2.0/OIDC 协议，但其前提是用新 IAM 替换现有身份系统。若采购要求是“与现有身份系统对接且禁止替换”，本方案不能作为满足依据。", "locator": "artifact_file_198c3bf31cb94383_1:p1:l18", "actual_line": 18, "raw_file": "holdout-06-identity-replacement-negative.txt"}]`

### H07 holdout-07-transport-db-crypto-manual.txt
- runtime：`completed`；decomposition step：`success`；parser：`executed`；requirements：`4`
- 缺失锚点诊断：`[]`
- oracle 语义评估：`partial`；保留：原始必要条件文本和人工核验限制均被逐条保留。
- 逻辑遗漏：`['TLS 条件与数据库条件的 AND 结构化 check_rule', '禁止关键词直接 matched 的规则字段']`；解释：`manual_review_required`；source refs：`4`
- source refs：`[{"document_id": "file_0ab29ef6dffd4497", "file_id": null, "page": 1, "source_version": "file_0ab29ef6dffd4497:v1", "quote": "1.1 所有外部接口和管理接口的加密传输协议最低为 TLS 1.2；TLS 1.0 和 TLS 1.1 不得启用。", "locator": "artifact_file_0ab29ef6dffd4497_1:p1:l7", "actual_line": 7, "raw_file": "holdout-07-transport-db-crypto-manual.txt"}, {"document_id": "file_0ab29ef6dffd4497", "file_id": null, "page": 1, "source_version": "file_0ab29ef6dffd4497:v1", "quote": "2.1 身份证号、银行卡号等敏感字段须采用国密算法保护，或采用经独立测评确认安全强度等效的算法。", "locator": "artifact_file_0ab29ef6dffd4497_1:p1:l11", "actual_line": 11, "raw_file": "holdout-07-transport-db-crypto-manual.txt"}, {"document_id": "file_0ab29ef6dffd4497", "file_id": null, "page": 1, "source_version": "file_0ab29ef6dffd4497:v1", "quote": "2.2 “等效强度”不能仅凭算法名称或关键词判定，需结合密码算法、密钥长度、模式、密钥管理和测评结论人工核验。若投标材料只写“支持国密/高强度加密”，不得直接视为数据库敏感字段已经满足。", "locator": "artifact_file_0ab29ef6dffd4497_1:p1:l13", "actual_line": 13, "raw_file": "holdout-07-transport-db-crypto-manual.txt"}, {"document_id": "file_0ab29ef6dffd4497", "file_id": null, "page": 1, "source_version": "file_0ab29ef6dffd4497:v1", "quote": "本条由传输版本条件与数据库字段保护条件组成。任一条件缺少可核验事实时，整体不得依据关键词直接标记为 matched；应保留实际页码、文档、source_version 和原文 quote，并将技术等效性送人工复核。", "locator": "artifact_file_0ab29ef6dffd4497_1:p1:l24", "actual_line": 24, "raw_file": "holdout-07-transport-db-crypto-manual.txt"}]`

### H08 holdout-08-platform-portability-positive.txt
- runtime：`completed`；decomposition step：`success`；parser：`executed`；requirements：`3`
- 缺失锚点诊断：`['PostgreSQL', '14', 'AND']`
- oracle 语义评估：`partial`；保留：保留国产 Linux 和不得绑定单一公有云，并保留可选云插件不能替代约束的说明。
- 逻辑遗漏：`['PostgreSQL 14 及以上条件', '三项 AND 结构', '插件可选与核心条件的非替代关系字段']`；解释：`manual_review_required`；source refs：`3`
- source refs：`[{"document_id": "file_28fc1c7c41724998", "file_id": null, "page": 1, "source_version": "file_28fc1c7c41724998:v1", "quote": "1.1 软件应能够在国产 Linux 操作系统上稳定部署，至少完成对麒麟或统信服务器版的适配验证。", "locator": "artifact_file_28fc1c7c41724998_1:p1:l7", "actual_line": 7, "raw_file": "holdout-08-platform-portability-positive.txt"}, {"document_id": "file_28fc1c7c41724998", "file_id": null, "page": 2, "source_version": "file_28fc1c7c41724998:v1", "quote": "2.1 方案不得绑定单一公有云厂商。除云环境外，应支持采购人自有机房或其他符合条件的基础设施独立运行；不得把某一家云厂商的专有服务作为系统不可替代的前置条件。", "locator": "artifact_file_28fc1c7c41724998_1:p2:l3", "actual_line": 14, "raw_file": "holdout-08-platform-portability-positive.txt"}, {"document_id": "file_28fc1c7c41724998", "file_id": null, "page": 2, "source_version": "file_28fc1c7c41724998:v1", "quote": "系统可以提供阿里云、腾讯云或其他云平台的适配插件，但插件属于可选扩展。云插件数量、容器编排工具名称和监控产品名称，不能替代“不得绑定单一公有云厂商”的约束。", "locator": "artifact_file_28fc1c7c41724998_1:p2:l16", "actual_line": 27, "raw_file": "holdout-08-platform-portability-positive.txt"}]`
