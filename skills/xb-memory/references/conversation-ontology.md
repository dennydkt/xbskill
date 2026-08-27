# xbskill 会话本体模型

## 目的与边界

本模型把会话中的可复用内容表达为带证据、时间和权限边界的实体与断言。它服务项目内跨会话协作，未宣称兼容 RDF、OWL 或通用知识图谱标准。原始 transcript 负责逐字追溯；本体存储负责结构化复用；ContextPacket 负责当前任务最小注入。三者各有职责，禁止相互覆盖。

## 存储结构

```text
<project>/memory/xbskill/
├─ sessions/<session-id>/
│  ├─ transcript.md
│  ├─ session.md
│  ├─ classification.md
│  └─ ontology.json
├─ ontology/
│  ├─ meta.json
│  ├─ entities.json
│  ├─ assertions.json
│  └─ index.json
├─ context/
├─ progress.md
└─ memory-settings.md
```

`ontology.json` 保存本会话冻结增量。`entities.json` 与 `assertions.json` 保存跨会话汇总；同一断言 ID 的内容不可改写。修订通过新断言的 `supersedes` 关系完成。`index.json` 是可重建投影，校验失败时禁止查询并要求重建。

## 实体

允许类型：`person`、`organization`、`project`、`goal`、`work_item`、`artifact`、`decision`、`event`、`constraint`、`capability`、`preference`、`role`、`topic`。

实体 ID 在项目范围稳定，推荐格式为 `<type>:<slug>`。`person:self` 固定表示用户本人。人物代号、公司简称和项目简称可作为 alias；相同 alias 不能证明同一实体。指代不明的实体使用稳定候选 ID并标 `needs_identity`。

## 断言

断言表达 `subject — predicate → object`。对象可以是实体或字面值。每条断言携带：

- `epistemic_status`：用户陈述、可观察事件、助手推断、用户决定或材料证据；
- `confidence`：高、中、低；
- `lifecycle`：active、candidate、disputed、superseded、expired；
- `retention`：long_term 或 session_only；
- `observed_at`、`valid_from`、`valid_until`；
- 会话、轮次、角色和最小证据片段；
- `reversal` 与 `supersedes`。

用户陈述的 active 只证明“用户在该时间与范围内这样陈述”；它不自动证明第三方性格、组织文化或因果关系。助手推断必须保持 candidate。状态、截止时间和角色等函数型谓词在同一作用域出现不同有效值时进入冲突集合，等待时间边界或权威事实裁决。

## 留存和敏感级别

`normal` 可在通过来源与证据门后进入长期本体。`restricted` 默认使用 `session_only`，并完整保存在当前会话的 `ontology.json`；项目级 `ontology/assertions.json` 排除这类断言。用户明确允许跨会话长期检索选定受限断言后，才把这些断言改为 `long_term` 并设置 `authorized_sensitive_long_term=true`。这项授权只改变留存与检索作用域，证据层级、置信度、生命周期、来源、推翻条件和 `supersedes` 原样保留。用户明确排除的内容不进入 transcript 或本体增量。凭据和私钥模式始终阻断整笔事务。

保存前必须显示本体作用域预览，至少包含会话实体、会话断言、普通长期、受限会话级、候选和冲突数量。没有跨会话敏感检索意图时，预览明确告知安全默认并继续写入；只有用户表达长期检索意图时，才逐条展示拟授权断言并询问一次。

## 未来会话检索

查询请求至少写任务文本，并可附实体 ID、实体类型、谓词、时间点、候选/争议项开关和最大断言数。查询器只返回有明确相关信号的项；未命中时返回 `no_match`，不补最近记录。默认过滤受限内容、已过期断言和已被替代断言。

ContextPacket 必须保留断言 ID与来源轮次；候选、争议、冲突、过期和省略分别显形。模型在新会话中引用时说明记录日期与证据层级，并用用户本轮新事实覆盖旧上下文的行动优先级。

## 修订与迁移

纠正旧记忆时追加新断言并列出 `supersedes`。实体合并通过用户确认或一手材料支持的 `same_as`；拆分通过 `different_from`。旧版 `classification.md` 可作为迁移候选来源，迁移项统一从 candidate 开始并保留原会话坐标；未完成逐项复核前不得批量激活。

迁移器逐行保留旧分类内容、旧证据等级、旧目标、旧动作、表格行号和 transcript 精确摘录。旧分类本身属于助手生成的历史解释，所以统一降为 `assistant_inference`、低置信度和 candidate；原来的 `user_statement` 等标签仅进入 `legacy_evidence_level`。同名主体按会话隔离，只有后续确认才建立 `same_as`。普通候选可进入长期检索，受限项保持 `session_only`。查询端必须显式开启候选项，并把 `review_required` 与来源日期一起呈现。

旧迁移 candidate 的 ContextPacket 不携带逐字摘录，只携带会话 ID、轮次、角色和摘录 SHA-256。模型只能使用 `legacy_content` 作为待复核线索；来源邻文不能生成新要求或新事实。用户要求核对原话时，再按坐标读取对应 transcript 片段。
