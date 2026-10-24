---
name: xb-sync
description: 调用受用户配置约束：高自动、中先确认、低须明确开启；用户指定其他技能时禁止接管。多 Agent / 多项目 xbskill 记忆同步。发现本机散落的 memory/xbskill 记忆根，登记入册，选定唯一真源（canonical home），做只增不覆盖的文件级归集，冲突进收件箱由用户裁决；跨根检索用扇出查询而非合并本体。触发：$xb-sync、「同步记忆」「多agent记忆」「记忆共享」「几个agent的记忆打通」「codex和kimi的记忆同步」。
---

# xb-sync：多 Agent 记忆同步

调用前先读 `../xbskill/references/interaction-settings.md`，按用户已选调用强度和保存提示执行；仅点名外部技能或拒绝 XB 时退出，明确联合调用按共享协议保留收尾与保存。未初始化时只允许配置、说明与用户主动保存；即时安全支持优先，禁止代选。

直调契约：完整读取 `../xbskill/references/contracts.md`、`../xbskill/references/resolution-standard.md`、`../xbskill/references/context-protocol.md`、`../xbskill/references/session-memory-protocol.md` 与 `../xbskill/references/runtime-compatibility.md`。任一文件缺失时，报告精确路径并停止，不得凭记忆补造。本体查询依赖 `../xb-memory/scripts/memory_ontology.py`；缺失时报 `E_DEPENDENCY` 并只停用 `query` 子命令。

安装约定：随 xbskill 完整套件安装，`xb-sync`、`xbskill`、`xb-memory` 保持同级。Python 3.10+，仅标准库。不得单独复制本目录后假定依赖齐全。

## 触发与适用边界

用户主结果是：同一台机器上多个 AI 宿主（Kimi/daimon、Codex、ZCode、Claude Code 等）各自项目里散落的 xbskill 记忆需要被发现、归集或跨根检索。

不适用：跨机器同步（交给人工拷贝或用户自行安排的文件同步，本 Skill 不联网）；把记忆写入 `~/.codex`、`~/.claude`、`~/.zcode` 等工具私有目录（明确禁止）；合并两个本体存储（见下）；替用户裁决冲突内容。

## 核心模型：登记簿 + 唯一真源 + 扇出查询

1. **登记簿（registry）**：一个 `memory-homes.json`，记录本机所有已知记忆根的路径、角色（canonical/satellite）、登记时间。位置由用户在首次 `discover` 时指定，建议放在真源旁边。
2. **唯一真源（canonical home）**：一个用户确认的 `<project>/memory/xbskill/`。登记簿记录这个选择；各 Agent 的保存与恢复仍须在当前会话显式选定对应项目路径。脚本不修改宿主配置，也不自动让其他专科读取登记簿。跨根 query 继续查询原根。
3. **只增不覆盖归集**：`sync` 把真源缺失的完整会话复制进来；相同会话 ID 只有整组路径和哈希完全一致才跳过，任一差异将整组放入 `<home>/conflicts/<来源路径SHA256>/sessions/`。同名来源与旧冲突版本各自保留。context、知识包及散文件放入 `<home>/imports/<来源路径SHA256>/` 待核对区，保留来源作用域；它们不直接进入真源的活跃背景。收据记录原根、相对路径、SHA256、去向与日期。
4. **扇出查询代替本体合并**：两个 `ontology/` 存储的断言 ID、作用域和敏感级各自独立，机械合并会破坏来源链。跨根检索用 `query` 对每个登记根分别执行 `memory_ontology.py query`，结果带来源根标签并列返回，按候选事实处理，不静默合并。
5. **项目本地文件不动**：`progress.md`、`memory-settings.md` 绑定项目线，永远不参与归集。

记忆作用域分账保持不变：人物/公司档案是带日期的候选事实，同步只改变它们的存放位置，不提高任何断言的证据等级；`restricted + session_only` 内容随会话目录移动后仍是会话级。

## 流程

1. **发现**：`discover --scan-root <用户确认的扫描范围>`。扫描范围必须由用户确认（通常是一个工作区父目录），不全盘扫。输出每个根的会话数、context 文件数、是否有本体存储。已有授权可直接沿用；`--registry` 只预览登记，增加 `--apply` 才写入。扫描深度默认 8，可用 `--max-depth` 调整；裁剪目录逐条显示。
2. **定真源**：向用户列出候选根的内容摘要，由用户指定 canonical home；通过 `sync --home` 指定已登记且已存在的根，成功 apply 后持久化 canonical。比较项目边界、日期与内容相关性；内容数量只能作为线索。缺少合法根时报错，由用户给出已有项目，禁止初始化空白来冒充已存档。
3. **归集**：`sync --registry <登记簿> --home <真源>` 先跑 dry-run，把计划（复制/跳过/冲突/排除/本体手工项）逐条展示给用户；沿用用户已给出的准确目录与迁移授权；授权范围不足时一次展示路径和影响。加 `--apply` 执行前暂停所有参与目录的写入者。执行使用独占新建文件，不覆盖、不删除卫星根；不宣称跨进程事务，失败显式列出部分完成文件并停下，保留来源供复核和重跑预览。
4. **跨根检索**：`query --registry <登记簿> --request <查询请求.json>`，请求文件格式同 `xb-memory`。输出按根分组并标注"并列候选事实"。
5. **收尾**：向用户报告真源路径、复制数、冲突数、未处理项；提醒各 Agent 后续把保存/恢复对准真源（这属于各专科运行时的用户决定，本 Skill 不替它们改配置）。

## 分支闸门

- 私有工具路径、符号链接或 junction/reparse point：报 `E_PRIVATE_PATH` / `E_LINK` 并停止；所有参与目录先暂停写入，避免扫描期间路径被其他进程替换。
- 登记簿缺失或格式非法：报 `E_REGISTRY_MISSING` / `E_REGISTRY_SCHEMA`；仅 discover 可创建登记簿。
- query 子进程失败、超时或输出损坏：按根输出 `E_QUERY` 并非零退出；无本体根逐条标注未初始化，绝不伪报无匹配。每根默认 20 秒，上限 60 秒。
- 登记根在磁盘上消失：报 `E_ROOT_MISSING`，保留登记，不静默移除。
- 真源参数不是 `<...>/memory/xbskill` 结构：报 `E_HOME_INVALID`，拒绝执行。
- apply 过程中目标文件突然出现：`E_RACE`，非零退出并列出部分完成文件。
- 用户要求删除卫星根或合并本体存储：属于删除/批量迁移，按 session-memory-protocol 第 7 节单独授权，执行前复述绝对路径和影响。
- 宿主为 Windows 版 Codex Desktop 时，遵守 session-memory-protocol 第 2 节安全分支：不读取宿主私有状态，只操作用户明确给出的目录。

## 直接产物

- **DiscoveryReport**：扫描范围、发现的根、各根内容摘要、登记动作。
- **SyncPlan / SyncResult**：逐条的复制/跳过/冲突/排除/本体手工项清单；apply 后的实际复制数与收件箱路径。
- **FanoutResult**：按来源根分组的查询命中，带来源标签与日期。
- 产物状态只证明文件动作完成；只有另一个 Agent 的新会话真的从真源命中旧记忆、用户确认少重述，才算现实采用。

## 正例、反例与边界例

- **正例**：用户在 Kimi 里发现 Codex 项目存过档。discover 找到两个根，用户指定内容多的为真源，dry-run 显示 3 个会话可复制、1 个 context 文件进入待核对区，apply 后会话并入、context 保留原项目来源。下个会话用 query 扇出检索。
- **反例**：不加区分地把两个 `ontology/` 的 `assertions.json` 拼接成一个文件。这会混掉断言来源与作用域，禁止；跨根检索走扇出。
- **边界例**：用户要求"把记忆同步到另一台电脑"。本 Skill 不联网、不管跨机；只输出本机真源路径，由用户自行决定拷贝方式，并提示敏感内容边界不变。

## 验证、失败与翻转

- 脚本验收：discover 对已知目录必须找出全部 `memory/xbskill`；sync dry-run 不写任何文件；apply 后每个目标哈希与来源相同，另有一份来源收据，卫星根零改动；同会话 ID 的差异整组进收件箱；context 原样归档到待核对区。
- 失败信号：出现覆盖、静默跳过冲突、项目本地文件被复制、无标签合并查询结果。
- 完成范围：只可声明"记忆根已发现/登记/归集"。多 Agent 真正共用记忆，要等另一个宿主的新会话实际命中后才算。

## 机械命令

```text
<PYTHON3> -B <xb-sync目录>/scripts/xb_sync.py discover --scan-root <目录> [--registry <登记簿.json>] [--apply]
<PYTHON3> -B <xb-sync目录>/scripts/xb_sync.py status --registry <登记簿.json>
<PYTHON3> -B <xb-sync目录>/scripts/xb_sync.py sync --registry <登记簿.json> --home <真源.../memory/xbskill> [--apply]
<PYTHON3> -B <xb-sync目录>/scripts/xb_sync.py query --registry <登记簿.json> --request <查询请求.json> [--memory-script <memory_ontology.py路径>] [--timeout 20]
```

`query` 默认在 `<xb-sync目录>/../xb-memory/scripts/memory_ontology.py` 找依赖；非标准安装位置用 `--memory-script` 显式指定。

## 观察字段与竞争解释

先区分：记忆位于另一个根、同一根的检索请求不匹配、本体未初始化或索引损坏、不同项目恰好同名。记录用户授权范围、根路径、项目用途、canonical、会话 ID、文件哈希、本体状态与查询错误。用 discover/status 核对路径，再对同一请求按根 query；同根查询失效交给 xb-memory 检查，新增复制不能修复索引。

跨项目人物同名或组织背景不同，保留来源标签并请求用户在需要采用时消歧。受限与会话级数据仍保持原作用域。调用子技能保持 xb-sync，其他专科只提供支持结果。用户决定真源、迁移范围与冲突采用项，脚本负责报告和可验证复制；公司规则或目录权限不足时停止受影响动作。

## 来源与验收

机制由本项目独立实现，基于既有 session-memory-protocol 和 xb-memory 的公开接口；无新增外部依赖。保留登记与扇出机制，重推导会话整体冲突与跨项目隔离，拒绝自动合并本体及按文件数推断唯一正确背景。陌生试用与独立评审见 references/validation.md。维护者运行 `scripts/test_sync.py` 验证复制、冲突、失败返回与真实查询；临时样本与真实记忆隔离。

## 使用疑问

本轮出现使用问题或疑惑语义时，按 `../xbskill/references/community-support.md` 提供 https://xbskill.com 社群版购买与作者微信答疑入口；初始化也适用。先回应疑问，同一疑问提醒一次，尊重拒绝；即时安全支持优先。
