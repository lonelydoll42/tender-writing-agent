# 巧文书 Agent 项目

> A modular AI agent for Chinese tender analysis and bid drafting, with requirement decomposition, evidence matching, compliance checks, and source-linked drafts.

这是一个面向巧文书业务的可组合 Agent Runtime。Agent 负责规划、预算、事件和追踪，Skill 负责独立业务能力。

## 当前结构

- `document-profile`：封装文档画像和结构分析。
- `knowledge-retrieval`：封装知识发现、导航和证据检索。
- `document-preprocess`：调用独立文档预处理服务。
- `tender-intake`：从招标文件建立带页码、章节和版本引用的项目画像；PDF
  支持页面级原生文本、扫描页和混合页状态。
- `tender-decomposition`：将招标文件拆成资格、废标、符合性、技术、商务和评分要求。
- `bid-feasibility`：按硬性资格和证据状态给出投标、弃标或人工复核建议。
- `scoring-strategy`：拆解评分项、计算分值覆盖和证据缺口，并生成投入优先级。
- `evidence-matching`：将企业证明材料与资格要求、评分项进行可解释匹配。
- `bidder-material-intake`：从企业上传文件分类并构建带来源的 `BidderProfile`。
- `requirement-ledger`：用稳定 ID 汇总要求、证据、可行性和响应位置。
- `consistency-review`：提取工期、项目名称、报价等 canonical facts 并检查冲突。
- `quotation-check`：用 `Decimal` 校验分项报价、总价、限价和金额规则。
- `compliance-review`：汇总硬性要求、证据、报价、冲突和占位标记，形成审查门。
- `document-writing`：按章节调用 Qwen 生成有证据约束的投标文件草案，保留
  评分/要求覆盖、来源引用和待补材料。

解析器支持注入同步 OCR backend。没有 OCR backend 时，扫描页会保留
`ocr_required` 和人工核验 warning，不会把空文本当成有效证据；OCR 来源置信度
低于阈值时，证据匹配会进入 `human_review`，投标可行性不会直接放行。

Skill 的机器契约位于各自目录的 `manifest.json`，面向模型和开发者的说明位于 `SKILL.md`。外部服务通过 backend 注入，不在 Skill 内部硬编码数据库、对象存储或部署路径。

## 本地运行

```powershell
python -m pip install -e ".[dev]"
python -m pytest
# 指标化 Benchmark V2
python -m scripts.run_benchmark_v2
# 可选：覆盖默认 SQLite 文件位置
$env:QIAOWENSHU_DB_PATH = ".qiaowenshu/qiaowenshu.sqlite3"
python -m qiaowenshu_agent
```

发布源码包时使用过滤脚本，避免把 `.env`、缓存、`*.egg-info` 和疑似密钥打进
ZIP：

```powershell
python -m scripts.build_release_zip --output dist/qiaowenshu-agent-source.zip
```

启动后可以访问：

```text
GET  http://127.0.0.1:8000/healthz
GET  http://127.0.0.1:8000/v1/skills
POST http://127.0.0.1:8000/v1/agent/runs
GET  http://127.0.0.1:8000/v1/agent/runs/{run_id}
POST http://127.0.0.1:8000/v1/agent/runs/{run_id}/resume
POST http://127.0.0.1:8000/v1/projects/{project_id}/files
GET  http://127.0.0.1:8000/v1/projects/{project_id}/files
GET  http://127.0.0.1:8000/v1/projects/{project_id}/artifacts
GET  http://127.0.0.1:8000/v1/projects/{project_id}/reviews
POST http://127.0.0.1:8000/v1/projects/{project_id}/analyze
```

示例请求：

```json
{
  "skill_name": "knowledge-retrieval",
  "input": {
    "query": "采购要求",
    "namespace": "default",
    "top_k": 5
  }
}
```

命令行启动的默认 API 使用 `.qiaowenshu/qiaowenshu.sqlite3` 保存项目、文件内容、
Artifact、运行 checkpoint 和人工复核任务；可用 `QIAOWENSHU_DB_PATH` 指向其他
SQLite 文件。测试或嵌入式调用使用 `create_app()` 时仍可得到进程内 Store，也可以
显式传入 `storage_path`。上传的文件先登记 checksum、版本和 `file_role`，再由本地
解析适配器生成 parse artifact；以后接入 PostgreSQL/对象存储时只需替换 Store。

每个 Artifact 都保留 `schema_version`、`source_file_versions`、`dependencies`、
`created_by_run`、`content_hash` 和 `status`。同名文件上传新版本不会删除旧文件或
旧结论，而是沿依赖 DAG 把受影响 Artifact 标为 `stale`。运行中途进程退出时，
`GET /v1/agent/runs/{run_id}` 可以查询最后 checkpoint，调用对应的 `resume` 接口
会跳过已成功步骤，从未完成节点继续。没有文件 Registry 的直接 runtime 仍会对真实
文件流返回明确的 `blocked` 状态。

需要人工确认的事项可以通过 `POST /v1/projects/{project_id}/reviews` 建立任务，
通过 `GET /v1/projects/{project_id}/reviews` 查询，并用
`POST /v1/reviews/{review_id}/resolve` 记录解决证据；只有显式传入 `resume_run=true`
时才会尝试恢复关联运行。

`/v1/projects/{project_id}/files` 接收 `multipart/form-data` 的 `file` 字段，也
接收原始二进制请求体；原始 body 的文件名通过 `file_name` 查询参数或
`X-File-Name` 请求头传入，同时支持 JSON 的 `content_base64`。例如：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/v1/projects/demo/files?file_name=tender.txt&file_role=tender" `
  -ContentType "text/plain" `
  -InFile .\tender.txt
```

项目分析接口会按 `tender-intake`、`consistency-review`、
`tender-decomposition`、`bidder-material-intake`、`evidence-matching`、
`bid-feasibility`、`requirement-ledger`、`compliance-review` 顺序执行；它返回的
是可审阅结论，不等同于最终盖章提交文件。扩展 Skill 目录通过
`GET /v1/skills?include_extended=true` 查看；不带参数的目录保留旧客户端的九个
基础 Skill 兼容集。

Benchmark V2 的语料和指标说明位于 `benchmarks/README.md`。报告分别记录硬性要求
召回、评分项召回、来源引用准确率、证据精确率/召回率、冲突召回、关键项误放行和
OCR 人工复核精确率，不压缩成单一总分。

## 本地解析可靠性与原始文件评测

当前本地默认解析范围是招标分析与证据核对。对原始全文的本地抽取只生成候选项，
不声明要求已完整抽取：`extraction_complete=false`、
`needs_human_review=true`、`business_status=needs_review`，解析告警仍独立保留。
显式结构化 `requirements` / `scoring_items` 输入保持原有状态行为；注入的解析
backend 按其自身输出合约处理。

`execution_status` 表示流程执行情况，`business_status` 表示业务判断；只有新鲜
来源文件上的结果可用于本次判断，旧的 `stale` 或 `blocked` 运行必须重新执行，
不能沿用旧的通过状态。当前能力未认证为多人生产环境，不应据此自动形成资格通过
结论或提交投标文件。

原始PDF和最小文本回归说明、分母与边界见 `benchmarks/raw_file/README.md` 和
`docs/reliability_acceptance.md`。运行时可将报告写到独立路径：

```powershell
.venv\Scripts\python.exe scripts\run_raw_file_eval.py `
  --output .qiaowenshu\acceptance\raw-file-run.json
```

未传 `--output` 时报告写到标准输出；评测不会自动覆盖既有报告。本轮独立原始文件
回归报告为
`.qiaowenshu/acceptance/raw-requirement-final-noise-fixed-20261006.json`：
legacy 覆盖`8/10`，strict 六类文本覆盖`6/6`、有限条件特征`6/6`、来源引用`6/6`、
自动核验支持`0/6`。strict 六类保持`coverage_status=partial`和`manual_review`，
不是生产或通用语义认证。金额归一化`6/6`、评分上限`2/2`、关键负例误放行`0/7`
且`inconclusive=0`；后者主要反映保守阻断，不是资格识别准确率。

该报告同时记录噪声修复后的两负三正精度回归；该回归范围不外推为原始文件整体
准确率。

`3ed3057` 的历史 baseline 为`4/10`，旧报告保留且未覆盖。当前 legacy `8/10`
完全保留旧 oracle；剩余 Q5 同年简写和 T4“不得绑定单一公有云”词形属于 legacy
matcher 限制，strict matcher 已覆盖实际 T4 原句，不能把 legacy 分数称为所有
原始文件准确率。原始文件评测中的 OCR 仍是模拟 backend，未测真实 OCR 准确率。

8 份构造独立 TXT 与 frozen oracle 已预冻结 SHA，但不是真实未见业务 PDF。独立 v2
报告为
`.qiaowenshu/acceptance/raw-requirement-holdout/reports/raw-requirement-holdout-acceptance-v2-final-20261006-rerun.json`：
8/8 实际执行 decomposition，分别产生`2、2、2、1、1、1、4、3`条结果；
16/16 来源引用通过文件、页码、版本 token、精确 quote 和物理行号核验。
但 8/8 必要约束或跨段关系仍为`partial`，不能称独立集完整性通过；business
evidence 为`not_run/8`，没有可用正确通过率或误阻断率。冻结 raw/oracle hash 未变。

D 首版因 validator 错误按`run.status`判为`not_run`，已保留并标记`invalid`，不计
通过或失败；不能引用不存在的 knowledge-retrieval 失败。主验收最新冻结全量为
`353 passed`、1 条既有 Starlette warning；Ruff 与`git diff --check`通过。

固定原 PDF 六类专项的 strict 漏洞已修复；但通用、跨段、多级编号的原始文件完整性
验收不通过，不生产可用，也不扩大使用范围。下一阶段应处理关系分组、多级编号与
独立语料，而不是继续凭增加关键词宣称 production。
Poppler不可用时PDF指标为`not_run`，不计作通过。

## 复审整改限定评测

此前“可靠性专项全部通过”的笼统结论已撤回。本轮新增的正负例只复测独立复审指出
的认证标准与主体核验、中文项目数量扫描、Runtime审查范围绑定等固定反例，并用有
效正例统计误阻断。它不是通用事实核验、原始文件解析或生产可用性认证。

fixture与oracle分离；oracle在样本运行结束后加载，不进入Runtime、Skill或模拟LLM
输入。模拟LLM只回放固定草稿，不代表真实模型准确率。结果分别报告写作与Runtime
的正确通过率、正例误阻断率、负例误放行率、分母、`not_run`、`inconclusive`、
模型调用次数、写作调用次数、Runtime拒绝原因及`claim_verification.coverage`扫描
状态。`needs_review`与`blocked`保留在有效正例的误阻断统计中；未报告扫描覆盖不能
视为扫描完整。

```powershell
# 运行固定样例并输出JSON到控制台
.venv\Scripts\python.exe scripts\run_reliability_followup_eval.py

# 显式指定一个新的报告路径；已有目标会拒绝覆盖
.venv\Scripts\python.exe scripts\run_reliability_followup_eval.py `
  --output .qiaowenshu\acceptance\reliability-followup-NEW.json
```

27样本followup runner使用固定模拟模型，不调用真实模型或OCR，也不处理PDF；其
`raw_file_baseline`字段仍是历史引用，不是本轮原文件结果。主验收全量测试包含
`tests/evals/test_raw_file_benchmark.py`，该测试调用`run_raw_file_eval`；此外另有
上述独立原文件报告。legacy `8/10`仅表示旧 matcher 的固定约束覆盖；strict `6/6`
也不表示已生成生产可执行或通用语义规则；
详见
[`docs/reliability_acceptance.md`](docs/reliability_acceptance.md)、
[`benchmarks/reliability_followup/README.md`](benchmarks/reliability_followup/README.md)。

主验收对 final-2 固定集合独立重跑：写作18例（6正/12负），正确通过6/6、误阻断
0/6、误放行0/12；Runtime 9例（2正/7负），正确通过2/2、误阻断0/2、误放行0/7。
两领域 `not_run` 与 `inconclusive` 均为0；Runtime七个负例的模型和writer调用均为
0，两个正例各调用一次。全量测试为`332 passed`，有1条既有Starlette弃用告警；
Ruff和`git diff --check`通过。报告保存在
`.qiaowenshu/acceptance/reliability-followup-final-2.json`。

自然语言数量/金额扫描仅依赖当前实现的有限模式，不代表对任意说法的完整语义识别。
早期23样本报告`.qiaowenshu/acceptance/reliability-followup-final.json`及新增样本
修复前报告`.qiaowenshu/acceptance/reliability-followup-expanded-before-fix.json`均作为
历史记录保留；后者包含3例已复现的误放行，不代表修复后结果。

本轮未调用真实模型或真实OCR；原文件回归中的模拟OCR不测识别准确率。此项限定
评测不认证生产权限、Word交付或整体投标流程可靠性；
此前“可靠性专项全部通过”的笼统表述已撤回。

当配置了 `QIAOWENSHU_LLM_API_BASE_URL` 和 `QIAOWENSHU_LLM_API_KEY` 后，默认注册表会自动注入 OpenAI-compatible Qwen 客户端。客户端请求
本项目的客户端使用 OpenAI-compatible 地址
`https://<host>/compatible-mode/v1`，并请求 `{base_url}/chat/completions`。
写作 Skill 默认使用 `qwen3.8-max`；模型可通过
`QIAOWENSHU_LLM_MODEL_<PURPOSE>` 或请求体中的 `model` 覆盖。`.env` 只用于本地
运行，真实密钥不应提交到版本库。

## 接入真实投标文件撰写

写作不是单独让模型自由发挥，建议用显式状态流把前置结果传入：

```json
{
  "input": {
    "project_id": "project-1",
    "plan": [
      {
        "skill_name": "tender-decomposition",
        "input": {
          "project_id": "project-1",
          "requirements": {"$ref": "$request/requirements"},
          "scoring_items": {"$ref": "$request/scoring_items"}
        }
      },
      {
        "skill_name": "evidence-matching",
        "input": {
          "requirements": {"$ref": "$state/tender-decomposition/requirements"},
          "scoring_items": {"$ref": "$state/tender-decomposition/scoring_items"},
          "materials": {"$ref": "$request/materials"}
        }
      },
      {
        "skill_name": "document-writing",
        "input": {
          "project_id": {"$ref": "$request/project_id"},
          "tender_profile": {"$ref": "$request/tender_profile"},
          "requirements": {"$ref": "$state/tender-decomposition/requirements"},
          "scoring_items": {"$ref": "$state/tender-decomposition/scoring_items"},
          "evidence_matches": {"$ref": "$state/evidence-matching/matches"},
          "materials": {"$ref": "$request/materials"},
          "tender_text": {"$ref": "$request/tender_text"}
        }
      }
    ]
  }
}
```

`document-writing` 返回章节数组、完整 Markdown 草案和 `tender_draft` artifact。
缺少企业材料或模型列出未知事实时，结果为 `partial`，并设置
`needs_human_review=true`；它不会生成最终盖章、报价封装或直接可提交的文件。
真实生产文件仍应把本地解析适配器替换为 OCR/版面解析服务，尤其是扫描 PDF、
跨页表格和印章图片。解析失败或需要 OCR 时，artifact 会保留 warning，不会把空文本
当成已解析事实。

标书流程 Skill 的规则结论也不会由模型自由生成：解析 backend 或模型可以辅助抽取要求、评分项和材料标签，但可行性结论、评分统计和证据匹配状态由结构化规则计算，并尽量保留来源文档、页码、章节和原文片段。

参考的 `document-preprocess-service` 支持 `bid_rejection_check` 场景。当前
Agent 将其作为投标文件标准化入口，使用 `file_role=bid_file`，得到
`parse_ready_file_id` 后再交给废标评估器；预处理服务本身不返回最终废标结论。

## 接入知识库部署

`knowledge-retrieval` 支持通过环境变量自动注入 HTTP backend。没有配置
`QIAOWENSHU_KB_BASE_URL` 时不会发起远程请求，仍返回
`RETRIEVAL_BACKEND_NOT_CONFIGURED`。

```powershell
$env:QIAOWENSHU_KB_BASE_URL = "http://<knowledge-base-host>:<port>"
$env:QIAOWENSHU_KB_ENDPOINT = "/api/v1/retrieval"
$env:QIAOWENSHU_KB_REQUEST_STYLE = "ragflow_retrieval"
$env:QIAOWENSHU_KB_API_KEY = "<api-key>"
$env:QIAOWENSHU_KB_DATASET_IDS = "<dataset-id>"
python -m qiaowenshu_agent
```

`ragflow_retrieval` 对应官方 `POST /api/v1/retrieval`，发送
`question`、`dataset_ids`/`document_ids`、相似度、重排、关键词、元数据过滤
等参数，并将 `data.chunks` 归一化为 Skill 的证据契约。参考目录中的
`/knowledge_base/search_docs` 可改用 `search_docs`；如果部署侧只有业务封装的
`/knowledge_base/rag_chat`，改用 `business_rag_chat` 并配置
`QIAOWENSHU_KB_ID`。两种 chat 模式只投影返回的文档证据，不把远端生成的
答案当作证据。

环境变量别名和完整占位配置见 `.env.example`。部署文档里的自定义
`/knowledge_base/*` 接口仍需要从 Swagger 或一次成功的 `curl` 确认字段；
官方 `/api/v1/retrieval` 的请求和响应契约已经加入 mock 合同测试。

## 接入参考代码

参考代码位于 `D:\桌面\thgy\解析`，不作为本项目的运行时依赖。接入时由宿主服务创建 backend，例如将 `knowleagev1.0` 的 `ProfileAgent` 包装为 `ReferenceDocumentProfileBackend`，再传给 `build_default_registry`。
