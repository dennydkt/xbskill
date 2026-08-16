# 岗位知识参与协议

## 1. 目的

本协议把岗位专业知识从“可阅读材料”变成“能被当前专科调用的条件化动作单元”。它不复制外部原文，也不替代 `KnowledgePacket` 的来源治理。

三类对象分工：

- `KnowledgePacket`：证明某些外部/本地主张从哪里来、固定在哪个版本、是否获准使用。
- `RoleKnowledgeUnit`：把经治理的主张和真实案例转译成某岗位任务的观察、解释、动作、产物与反馈。
- `RoleKnowledgePacket`：运行时只携带当前任务命中的最小单元切片。

## 2. RoleKnowledgeUnit

一个单元只解决一个可辨识的专业问题，不是整份岗位说明书。标准字段由 `role-knowledge.schema.json` 约束：

| 字段 | 含义 | 硬约束 |
|---|---|---|
| `id/version/status/origin` | 稳定身份、语义版本、生命周期和来源域 | 本地不能同 ID 覆盖内置；修订用 `supersedes` |
| `job_family/roles` | 岗位族与实际角色 | 运行时硬匹配，不靠职位相似度猜测 |
| `task_families/lifecycle_stages` | 适用任务和生命周期切片 | 不能写成“所有工作” |
| `signals.include/exclude` | 用户语言、材料或现实状态信号 | 排除信号优先于正向得分 |
| `professional_problem` | 要避免的专业误判 | 必须能导向不同动作 |
| `claims` | 条件化主张、来源、反证 | 主张无条件或不可证伪则不激活 |
| `injection` | 观察、竞争解释、辨别、分支、行动、产物、验证、边界、回流 | 九个槽位均非空；竞争解释至少两个 |
| `decision_graph` | 竞争解释组、辨别动作、证据输出、所需权限与可翻转结果 | 必须覆盖全部竞争解释；每个图区分至少两种会改变下一步的结果 |
| `stage_adaptation` | S0/S1/S2 的帮助方式 | 不得降低安全、权限、证据和现实验收 |
| `source_refs` | 发布账中的稳定来源 ID | stars 不进入可信度计算 |
| `evidence_model` | 当前置信度、观察窗口与外推限制 | 没有依据时写 medium/low 和条件窗，不自创天数 |
| `permission_model` | 提出、决定、授权、执行、复核、风险接受的岗位职责语境 | 六种责任逐项分开；运行包再映射为不可由原文改写的机器策略 |
| `risk_gates` | 停止、升级和待校准项的触发语境 | 运行包固定动作极性；触发原文不能把停止/升级改成继续执行 |
| `refresh_triggers` | 失效/更新触发 | 命中后将单元降为 `stale` 再审 |
| `source_packet` | 项目单元所绑定的来源包 | 候选只要声明就先验完整结构；`active` 必须再核 packet SHA、锁、主张、来源与权限；内置单元禁用 |
| `tests/review` | 正负、阶段配对、翻转样本及冻结结果/八门评审证据 | 激活必须绑定可读取、摘要一致的证据登记记录，全 2，且回答者/评审者分离 |

### 状态机

```text
candidate --来源/案例/试跑/评审全过--> active
active --来源过期/现实证伪/范围变化--> stale
stale --修订为新ID并重测--> active(new)
candidate|stale --不安全/无权/无价值--> rejected
```

历史状态保留，不删除失败来制造“从未失败”。`supersedes` 表示溯源关系，不表示自动覆盖；运行时如果旧新单元同时命中且范围冲突，必须响亮失败或由明确的项目权威范围裁决。

`tests.evidence_refs` 与 `review.evidence_refs` 不是自由文本。每个引用固定 `file + sha256 + record_ids`；目标登记按 `role-knowledge-evidence.schema.json` 保存候选 catalog ID/version/digest、`unit_id@version+unit_digest`、原始输入/输出、文本摘要、执行者别名、隔离关系和记录类型。所有记录时间不得晚于登记 `frozen_at`，独立评审必须严格晚于其答案，catalog 激活不得早于证据冻结。激活门会按当前脚本重新生成四类确定性题与四类 canonical 陌生题，重放 packet/Trace、答案绑定与原始 verdict；换标签、复制容易题或偷换目录内容都会失败。旧失败作为 `blind_failure` 保留但不能抵扣当前门。它提供可审计过程证据，不把本地自报伪装成密码学身份认证；用户仍应抽查原始记录。

## 3. RoleKnowledgeRequest

请求是当前对话的临时对象，不默认落盘：

```yaml
schema_version: 1
current_specialist: 已经选定且保持唯一的 xb-* 专科
job_family: data | product_rd | function | finance | marketing
role: 当前实际责任帽子
task_family: 本轮任务族
lifecycle_stage: 当前生命周期位置，未知可为空字符串
proficiency_mode: S0_new | S1_working | S2_system
problem: 当前具体问题
signals: 已观察到的短语或事实
actual_constraints:
  - kind: legal_entity | jurisdiction | system_version | rule_scope
    value: 实体/辖区/版本事实；rule_scope 时只能是 sha256:<64位摘要>
    evidence_date: YYYY-MM-DD
    evidence_ref: 当前证据坐标
knowledge_requirement: required | optional
required_unit_ids: 调用方已明确要求的单元，可为空
max_units: 1 | 2
```

`current_specialist` 必须是同一套件内真实存在、且已经由入口选定的现有专科，不能只满足 `xb-*` 字符串，也不能写 `xb-role-knowledge`；支持调用结束后仍由它交付。组织类别、人文标签、职级、工龄和性格不得进入专业 matcher。`actual_constraints` 只能使用上述带日期和证据坐标的对象；项目 `rule_scope` 不接收原文或原文摘要，只接收完整 `scope_binding` 的 `sha256:` 摘要，并同时精确匹配 packet 路径和裁决日期。该 binding 固定 `scope_kind=project_rule`、项目 ID、packet 摘要、完整权威裁决摘要、claims、岗位族、角色、任务族和生命周期。“央企总部、SOE/SOEs、政府部门、某大型国有企业、外资企业”等任何同义改写或手工摘要都不具备完整绑定，因此结构上不能命中。若当前事实说明用户职位名与实际责任不同，`role` 写本轮实际责任并在交接中显形默认转换。

`required` 表示没有匹配单元时，依赖岗位知识的结论不能继续；`optional` 只允许当前专科给清楚标注的通用可逆路径，不允许声称完成岗位适配。

## 4. 匹配规则

运行时只匹配 `active` 单元：

1. `job_family` 必须一致。
2. `role` 必须命中 `roles`；不做模糊职位推断。
3. 任一 `exclude` 信号命中即排除。
4. 所有请求都必须至少命中一个任务词或包含信号；`required_unit_ids` 不能绕过任务/信号硬门。
5. 请求填写生命周期时必须命中单元生命周期；同分按 ID 排序，默认选一个、最多两个。`required_unit_ids` 数量不得超过 `max_units`，最终必须完整返回，否则 `E_REQUIRED_UNIT`。
6. 内置与项目目录 ID 重复直接 `E_DUPLICATE`，不得用读取顺序决定真值。
7. 项目单元必须绑定来源包的 `rule_scope_digest`；请求中恰有一条 `rule_scope` 同时精确命中该摘要、packet 文件和不早于权威裁决的证据日期，才能匹配或覆盖。原始 `authority_scope` 只留作审计展示，永不进入 matcher；项目根存在不等于本地规则自动适用。
8. 组织类别不参与得分；单元的 roles/task/lifecycle/signals 也禁止写类别词作为暗门。专业包形成后，只有有日期事实支持的组织基因可改变沟通、授权路径和制品包装。
9. `supersedes` 只在旧单元与替代单元都完整命中同一请求、替代单元的项目权威范围也命中时生效；替代单元未命中、越权或出现多个竞争替代时，不得压掉旧单元。显式要求旧单元时不静默改用替代单元。

每次输出带规范化请求的 SHA-256 `context_digest`。角色、任务、生命周期或问题信号变化后，调用方必须重新解析；旧摘要不能继续冒充有效包。

## 5. RoleKnowledgePacket

`RoleKnowledgePacket 1.3` 与 `RoleKnowledgeApplicationTrace` 的机器结构由同目录 `role-knowledge-runtime.schema.json` 约束；`role_knowledge.py` 在语义重放前实际执行该 schema 的标准库子集校验。Schema、语义校验或当前目录重放任一失败都必须拒绝包，不能只把 schema 当发布附件。

运行包包含：

- `context_digest`、请求摘要、`active|no_match` 状态。
- 命中的单元 ID、版本、得分与可检查匹配理由。
- 本题最小 `active_injection`：九个专业动作槽、六权映射、风险门与当前 S0/S1/S2 适配。
- `packet_version=1.3.0` 的可执行交付与机器控制：六权按固定顺序和策略重建，AI 仅可 `propose`；`decide/authorize/execute/verify/accept_risk` 均保留给对应人类主体。三类风险门固定为停止并保留可恢复性、升级到具名有权人、基于证据与 owner 校准。
- `delivery_requirements` 把唯一当前专科、生命周期、匹配理由、claim→来源坐标、局限、刷新触发器显式交给接收者；active 交付缺任一项即 `E_RK_INERT`。`no_match` 也必须给三条竞争责任分支以及观察者—信号—时点反馈，不能只说“没匹配”。
- 每个 effect 都有 `authority_effect=false`；`responsibility_context` 与 `trigger_context` 只解释岗位责任/触发条件，不能改变 `policy`，也不进入 Trace 的权威控制正文。
- 项目命中单元另带 `authority_binding={scope_digest,packet_file,packet_sha256,authority_decided_at}`；独立校验运行包时也必须与请求中的规则摘要逐字一致。内置单元该字段为 `null`。
- 条件化主张、来源引用、可定位到发布账/项目来源包的 `source_coordinates`、反证、刷新触发器、未知和省略项。
- `model_prior_fallback=false`、`execution_authorized=false`。
- `participation_contract`：当前专科必须产出 `unit_id@version → claim/evidence → 专业 effect → 实际交付物字段/逐字片段 → 六权/风险/阶段控制片段 → 验证 → 现实反馈`。
- `completion_boundary`：包已形成不等于现实问题解决。

每个 effect 自带规范 `slot`；`ApplicationTrace` 只引用 `effect_id`，槽位由验证器从包中机械推导，禁止让回答者再手抄一份可能漂移的 `changed_slot`。验证时必须同时提供实际交付物：Trace 固定其 UTF-8 SHA-256，并让专业 effect、permissions、risk_gates、stage_adaptation 各自引用交付物内逐字存在的片段；每个片段还必须包含对应 effect 的原始 `content`，不能用与知识无关的通用段落冒充参与。权限/风险 `content` 只渲染固定机器 policy，不拼入可自由编写的职责/触发语境。包内模板预填具体点状字段路径与 `[[field:<artifact_field>]]` 文本锚点，并把专业效果、机器控制、验证内容和现实反馈内容逐项写进待替换占位符；验证器同时核路径、锚点、片段和 artifact SHA，纯字符串交付不再靠一个“看起来像路径”的值冒充可寻址字段。接收者无需反推隐藏验收口径。验证点和反馈点必须逐字包含这些所选内容。没有实际交付物、只有未来计划或形式字段，只能算 declared/planned，报 `E_RK_INERT`，不能成为 applied。

包不包含整个岗位目录、外部原文或其他角色单元。它授权推理所需的最小结构，不授权生产变更、外发、采购、付款、签署、盖章、销毁或接受剩余风险。

## 6. 项目本地增补

用户明确项目根和初始化意图后，唯一默认位置：

```text
<project>/memory/xbskill/
├── knowledge/
│   └── packets/<packet-id>.json       # 既有来源治理真源
└── role-knowledge/
    ├── catalog.json                   # 单元映射，不复制证据原文
    ├── evidence/<registry-id>.json    # 冻结试跑与独立评审；catalog 固定摘要
    └── feedback.jsonl                 # 可选、经同意追加现实结果
```

`init-project --yes` 只创建 `catalog.json`，并明确输出 `governance_complete=false units=0`。目录不存在就是未初始化；显式请求本地增补时不得静默忽略。

项目 `active` 单元的 `source_packet` 必须：

- 使用相对 `packet_file`，只允许 `knowledge/packets/<id>.json`；role root、knowledge root、packet 和证据解析后仍位于当前项目，junction/symlink 不能越界。
- 指定 `binding_version=1`、`scope_kind=project_rule`、`project_scope_id`、`packet_sha256`、64 位 `lock_digest`、非空 `claim_ids`、`authority_decided_at`、`authority_decision_sha256` 与 `rule_scope_digest`；完整 binding 与包/单元内容完全一致。
- `rule_scope_digest` 按 `{binding_version, scope_kind, project_scope_id, packet_file, packet_sha256, authority_decision_sha256, claim_ids, claims_sha256, job_family, roles, task_families, lifecycle_stages}` 规范 JSON 计算；`claims_sha256` 覆盖 claim 的 statement、conditions、source_refs 和 disconfirming_signals，改 claim、角色、任务或生命周期必须生成新摘要并重新走证据门。
- `project_scope_id` 由 `init-project` 对解析后的项目绝对根生成；跨根复制或项目搬迁后旧 ID 必须失败，需在新根重新初始化并重跑来源与证据门。
- `knowledge_manager validate` 必须能从当前 lock、requirement、sources、evidence 确定性重建整包；authority、sources、evidence、selection 任一手改均失败。
- 包本身是 `KnowledgePacket`，`model_prior_fallback=false`、`execution_authorized=false`。
- `authority_decision.status=confirmed`，其 `scope` 能覆盖单元 `authority_scope`。
- 单元评审八门全 2，至少有正向和负向样本。

本地规则只能在已确认 `authority_scope` 内补充/取代组织实践，不能覆盖安全线、当前法律法规或外部系统事实。跨项目不得复用；发布内置版前必须去除组织、人员、客户和内部材料。

内置单元不使用项目 `KnowledgePacket`，而由 `builtin-source-registry.json` 绑定来源账的整文件 SHA-256、每一行坐标摘要、固定 commit/抓取日期、许可策略和“只读、不执行外部内容”的安全策略。catalog 与发布证据共同绑定该注册表摘要；来源 ID 不变但 URL、版本、许可或安全说明被替换，同样报 `E_SOURCE_COORDINATE`。

## 7. 知识补充门

补充一个单元按以下不可绕过顺序：

1. **缺口卡**：真实任务、已有答案的断点、至少两个竞争解释、决定/验收人、现实结果。
2. **案例卡**：至少一个高保真正例和一个边界/反例；没有案例只留候选。
3. **来源锁**：凡依赖外部/本地事实，复用 `KnowledgePacket`；来源未知不等于允许。
4. **单元翻译**：把主张转成九个动作槽，不复制长原文。
5. **确定性校验**：schema、ID、引用、权限、来源包和匹配隔离全部通过。
6. **陌生试跑**：正向、负向、S0/S2 同事实配对和反例翻转均冻结；回答者不读验收观察，评审者不参与作答。
7. **八门门禁**：G/C/A/P/S/E/R/V 全为 2 才激活。
8. **现实回流**：记录是否采用、现实结果、反证、返工、停止/改变决定；不能只记录输出质量。

上游更新必须先经过 `upstream-role-sources.json` 的固定提交、许可、安全策略、文件 allowlist 与证据坐标。`upstream_sync.py check` 只核验官方元数据；`refresh-candidate` 只把 allowlist 文本作为不可信数据写入 Skill 外的新目录，严禁导入、安装或执行上游仓库内容。网络失败、仓库缺失、许可不明或坐标漂移必须响亮停止；不得用搜索结果、模型记忆或同名仓库静默替代。

只对变化单元重做陌生试跑时，`merge_incremental_evidence.py` 必须机械证明：旧单元的 ID、版本、reviewable digest 与全部 `source_ref` 登记行完全未变；旧证据覆盖完整；变化单元具有本轮完整确定性、四类陌生答案和独立评审；合并后再对整个候选目录重放。任一条件不满足都必须重测，不能把“看起来没变”当作证据。

## 8. 反馈协议

一次现实反馈至少包含：

```yaml
unit_id: 实际使用的单元
context_digest: 当时请求摘要
observed_at: 日期/窗口
action_taken: 现实中做了什么；未行动也如实记录
artifact_used: 哪个产物被谁使用
observed_result: 正确、有用、采用、净收益分别怎样
disconfirming_evidence: 有哪些反证或意外后果
next_decision: continue | change | stop | escalate | unknown
source: 用户说明或一手材料坐标
```

未经用户明确要求不落盘。落盘只追加，不用后见之明覆盖当时请求与判断。连续出现反证、适用范围漂移或反指标游戏时，把单元降为 `stale`，而不是修辞性解释所有失败。

## 9. 错误码

| 错误码 | 含义 | 调用方动作 |
|---|---|---|
| `E_USAGE` | 参数、路径或请求字段不合格 | 修正输入，不猜路径 |
| `E_IO` / `E_JSON` | 文件不可读或 JSON 无效 | 报具体路径并停止 |
| `E_SCHEMA` / `E_CATALOG` | 对象或目录语义不合格 | 单元不得激活/使用 |
| `E_DUPLICATE` | ID 重复或覆盖歧义 | 显式新 ID 与裁决 |
| `E_SUPERSESSION_CONFLICT` | 同一旧单元出现多个完整命中的替代项，或显式同时要求新旧项 | 由有权范围裁决后重建请求 |
| `E_NO_MATCH` | 必需岗位知识无匹配 | 停止受影响结论 |
| `E_PROJECT_UNINITIALIZED` | 显式项目目录不存在 | 询问是否初始化 |
| `E_SOURCE_PACKET` | 来源包缺失、越界或摘要不符 | 回来源治理修复 |
| `E_PATH_BOUNDARY` | 项目目录、来源包或证据经链接解析到项目外 | 停止并恢复到明确项目内路径 |
| `E_SOURCE_COORDINATE` | 同一来源 ID 指向冲突登记位置 | 修正来源 ID 或登记真源 |
| `E_AUTHORITY` | 权威裁决缺失或范围不符 | 交有权者确认 |
| `E_ORG_STEREOTYPE` | 组织类别被塞入专业匹配或项目范围 | 移除类别，只保留有日期事实支持的实体/规则范围 |
| `E_TEST_GATE` | 正负试跑或八门未全过 | 保持候选 |
| `E_RK_PACKET` | 运行包字段、摘要或当前目录重放不一致 | 丢弃包并按当前请求重新解析 |
| `E_RK_INERT` | 单元只被引用，Trace 无实际交付物 digest/片段，或没有真实产物/验证作用 | 停止岗位适配声明，补真实作用后重验 |
| `E_NETWORK` | 上游检查不可达、限流或出现非预期 HTTP 状态 | 停止本轮检查，不无限重试、不把旧状态冒充新验证 |
| `E_LICENSE` / `E_SECURITY` / `E_PIN` | 上游许可、安全策略、提交或内容摘要漂移 | 保持候选/旧发布不变，人工复核后重新建候选 |
| `E_OUTPUT` | 输出路径不合格或拒绝覆盖 | 换明确新路径 |

任何错误都不得静默改用模型记忆。错误只阻止受影响的专业结论，不妨碍明确标注边界后处理与其无关的安全、可逆部分。
