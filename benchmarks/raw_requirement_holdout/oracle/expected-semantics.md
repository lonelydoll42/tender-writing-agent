# Frozen Oracle: Raw Requirement Holdout

Status: pre-freeze oracle, authored independently of implementation patches.
Baseline: `3ed30579e76a63788f31803386856c75b1e9b14c`
Input contract: each raw TXT is the sole input document for its case. Do not supply pre-parsed requirements JSON.

## Evaluation rules

- Judge semantic requirements and their logical structure, not isolated keyword presence.
- Preserve OR alternatives, AND conjunctions, thresholds, date ranges, subject identity, and negation.
- Evidence from different people, documents, or unrelated clauses must not be combined unless the source explicitly permits it.
- Every extracted assertion or evidence item must retain the raw document name, `source_version`, page, and an exact source quote. A form-feed character is a page boundary; page numbering starts at 1. A file with no form-feed is one page.
- A requirement can be extracted correctly while candidate compliance remains unknown. Do not infer implementation capability from a tender requirement.
- `manual` is the expected disposition when technical equivalence or an unstated fact needs expert judgment. Keyword overlap alone is not a passing result.

## Case expectations

### H01 - qualification and finance

- Extract two distinct qualification conditions:
  - Entity proof: valid business license OR legal-person registration proof.
  - Financial/credit proof: key pages of the 2025 audit report OR a bank credit certificate.
- Preserve the OR in each condition. Do not treat capital, establishment date, the 2024 summary, or the 2025 audit table-of-contents-like unrelated material as a substitute.
- The listed valid license and 2025 audit key pages are positive examples for their respective branches.
- Provenance: `holdout-01-qualification-finance.txt`, `source_version=2026-09-18-r2`.
- Anchors:
  - Page 1, quote: `（1）在投标截止日仍处于有效期内的营业执照；`
  - Page 1, quote: `（2）依法登记的法人登记证明。`
  - Pages 1-2, quote: `2025 年度审计报告中的资产负债表和利润表` / `关键页；`
  - Page 1, quote: `2024 年度财务摘要` and `不替代 F-01`

### H02 - alternatives with an expired branch

- Entity proof is satisfied through the valid legal-person registration branch; the expired business license branch is explicitly invalid. Preserve the OR and the negative expiration fact.
- Financial/credit proof is satisfied by the dated bank credit certificate. A directory-only audit artifact, tax screenshot, and old bank statement are not substitutes.
- Do not reject the entity condition merely because the license branch is expired when the registration branch is valid.
- Provenance: `holdout-02-legal-credit-table.txt`, `source_version=2026-09-21-r1`, page 1.
- Anchors:
  - Quote: `法人登记证，登记机关为市级市场监督管理部门，登记日期 2023/11/06`
  - Quote: `营业执照，载明有效期至 2025/02/28`
  - Quote: `二选一的 OR 关系`
  - Quote: `银行资信证明由开户银行于 2026-08-17 出具`
  - Quote: `2025 年审计报告若只出现目录页，不足以替代审计关键页`

### H03 - same-person continuous social insurance, positive

- Extract the project-manager condition as AND:
  1. the named project manager holds the Information System Project Manager certificate; and
  2. that same person was continuously insured by the bidding entity for every month from 2026-03 through 2026-08.
- The listed rows provide the same name and employer for all six months, so the example is positive. Do not use Zhao Ning's unrelated record.
- Provenance: `holdout-03-manager-social-positive.txt`, `source_version=2026-09-24-r3`.
- Anchors:
  - Page 1, quote: `拟派项目经理须持有“信息系统项目管理师”证书`
  - Pages 1-2, quote: `同一自然人作为投标人本单位人员连续缴纳 2026 年 03 月至 2026 年 08 月的社会保险。`
  - Page 2, quote: `2026/03 | 周岚 | 华东智联科技有限公司 | 已缴`
  - Page 2, quote: `2026/08 | 周岚 | 华东智联科技有限公司 | 已缴`
  - Page 2, quote: `赵宁在 2026/08 有一条短期劳务记录`

### H04 - same-person continuous social insurance, negative

- The certificate requirement is present, but the social-insurance chain is not satisfied: Wang Shan's May row cannot fill Chen Li's gap.
- Expected outcome for the compound project-manager condition: not satisfied, not matched. Never combine rows across people.
- Provenance: `holdout-04-manager-social-gap.txt`, `source_version=2026-09-26-r1`.
- Anchors:
  - Page 1, quote: `投标人申报的项目负责人为陈立，所附证书为信息系统项目管理师`
  - Page 2, quote: `2026 年 05 月 | 王珊 | 北辰软件服务有限公司 | 正常`
  - Page 2, quote: `王珊的单月记录不得用来填补陈立的 2026 年 05 月缺口`

### H05 - existing identity integration, positive constraint

- Extract both required conditions as AND:
  1. integrate with the existing identity system using OAuth2.0 OR OIDC; and
  2. do not replace the purchaser's existing identity system.
- LDAP is not an alternative to the specified protocol integration. A new IAM is permissible only if it does not replace the existing identity authority.
- This is a requirement excerpt, not independent proof that a particular vendor has implemented the integration. Do not mark vendor capability as matched without implementation evidence.
- Provenance: `holdout-05-identity-oauth-no-replace.txt`, `source_version=2026-09-29-r2`, page 1.
- Anchors:
  - Quote: `通过 OAuth2.0 或 OpenID Connect（OIDC）与现有身份系统完成身份对接`
  - Quote: `不得以新建登录中心、迁移账号或其他方式替换采购人现有身份系统`
  - Quote: `LDAP 支持不能替代本条规定的 OAuth2.0/OIDC 对接`

### H06 - identity replacement, negative

- The proposed solution supports OAuth2.0/OIDC but explicitly migrates accounts, shuts down the existing login entry point, and makes the new IAM the sole authentication service.
- Expected outcome against a preserve-and-integrate requirement: not satisfied because replacement is prohibited. Protocol keyword presence does not override the negated constraint.
- Provenance: `holdout-06-identity-replacement-negative.txt`, `source_version=2026-10-01-r1`, page 1.
- Anchors:
  - Quote: `本方案提供新的 IAM 中心，支持 OAuth 2.0、OIDC 和 LDAP。`
  - Quote: `将现有账号导入新 IAM`
  - Quote: `关闭原有登录入口`
  - Quote: `由新 IAM 负责全部认证`

### H07 - transport plus database crypto, manual review

- Extract an AND condition:
  1. all external and administrative interfaces use TLS >= 1.2, with TLS 1.0 and 1.1 disabled; and
  2. sensitive database fields use national cryptography OR an independently verified equivalent-strength algorithm.
- TLS 1.2/1.3 is positive evidence for the transport branch. The text naming AES-256-GCM does not establish equivalent strength for sensitive database fields by itself.
- Expected overall disposition: `manual` for the database branch and therefore for the compound condition. Do not return matched solely from `TLS 1.2`, `国密`, or `AES-256-GCM` keyword hits.
- Provenance: `holdout-07-transport-db-crypto-manual.txt`, `source_version=2026-10-02-r4`, page 1.
- Anchors:
  - Quote: `最低为 TLS 1.2；TLS 1.0 和 TLS 1.1 不得启用。`
  - Quote: `身份证号、银行卡号等敏感字段须采用国密算法保护`
  - Quote: `或采用经独立测评确认安全强度等效的算法`
  - Quote: `需结合密码算法、密钥长度、模式、密钥管理和测评结论人工核验`
  - Quote: `数据库存储使用 AES-256-GCM`

### H08 - platform portability, three-way conjunction

- Extract all three as AND conditions:
  1. deployment on a domestic Linux distribution, with the stated Kylin or UnionTech server adaptation target;
  2. PostgreSQL compatibility at version 14 or later, not a MySQL-only implementation; and
  3. no binding to one public-cloud provider, with independent operation on purchaser-owned infrastructure.
- Optional cloud plugins do not negate the no-single-cloud-binding condition. Cloud-plugin names or counts are not evidence of portability.
- This excerpt defines requirements and compatibility targets; it does not provide an executed deployment test or prove a particular vendor's compatibility. Do not infer vendor compliance from the requirement table.
- Provenance: `holdout-08-platform-portability-positive.txt`, `source_version=2026-10-04-r2`.
- Anchors:
  - Page 1, quote: `国产 Linux 操作系统上稳定部署`
  - Page 1, quote: `兼容 PostgreSQL 14 及以上版本`
  - Page 2, quote: `不得绑定单一公有云厂商`
  - Page 2, quote: `1.1、1.2 和 2.1 为 AND 关系`
  - Page 2, quote: `云插件数量、容器编排工具名称和监控产品名称，不能替代`

## Scope and limitations

These are authored synthetic acceptance fixtures, not actual unseen procurement projects. They exercise six specified condition families and selected logical, temporal, negation, provenance, noise, and manual-review behaviors; they do not establish generalization to real-world tender corpora. No real LLM or OCR was used. Text page anchors use form-feed boundaries and are not PDF-rendered pages.

The oracle is frozen independently of implementation output. If any implementation agent had access to these files before the freeze notification, affected cases must be reported as exposed public regression cases, not blind holdout results. This preparation step does not establish or claim access isolation.
