# 沟通进度与记忆续接合同

## 会话内Checkpoint

每次回答后维护：sync_id、project_scope、organization_scope、updated_at、五域状态、已确认事实及来源轮次、推断/未知、用户纠正、排除项、current_domain、next_question、pending_task、status（in_progress / paused / round_complete）。保留每次回答的进度条目与来源；轮次编号按当前可见transcript，禁止伪造跨压缩历史。

这份进度先在当前对话中；当前会话保存一次即可将其中各轮进度一起保留，后续增量保存沿用session ID。用户尚未授权或项目不明确时，禁止自行创建目录或配置字段。拒答内容不得复制进问题文本、摘要或长期限定字段；仅留“该域拒答”。

## xb-save映射与单一真源

不增加独立环境JSON或人物档案。保存仍用xb-save的schema 2 bundle及原事务脚本：

- transcript保存获准的可见原话，session.md保存本次环境说明、各轮进度和最终Checkpoint，progress.md仅保留最新摘要、sync_id、来源会话和下一问。
- 为当前项目和当前组织的同步任务创建或复用work_item，ID须符合现有单冒号格式（如work_item:context-org-a），名称“职场环境同步”，别名可含“环境同步进度”；不能只凭同名跨组织合并。has_status断言的literal值为当前status。
- has_status使用epistemic_status=artifact_evidence、lifecycle=active，仅证明助手实际生成的沟通记录；source_refs指向包含逐字Checkpoint小结的assistant轮次。用户环境事实必须另外建断言，source_refs指向用户轮次，禁止用助手小结作用户确认。
- qualifiers只使用现有协议允许的标量：tracker="workplace_context"，sync_id、organization_scope、current_domain、next_question、excluded_domains（仅存拒答域名称或“不谈私人情况”等脱敏边界）、domain_location、domain_role、domain_people、domain_company、domain_changes。五域状态按问题指南取值。status与限定字段必须逐项对应当前会话实际记录，不把未回答写为covered。next_question可为下一主题或必要核对项的脱敏描述，禁止把整张表格塞入字段。
- 下一次保存用新has_status断言并以supersedes引用旧进度断言，旧会话和旧断言保留；不能用修改旧transcript实现更新。环境事实复用has_role、reports_to、member_of、constrained_by、prefers等现有谓词；地理/作息限制可建constraint再通过constrained_by连接，禁止增加未注册谓词。
- 所有记录带来源、观察日期、作用域与翻转条件。普通有来源事实可按既有门保存；推断、人格、公司文化概括保持candidate。敏感内容默认session_only，跨会话检索需另行逐项明确同意；凭据一律拒绝。

用户明确保存后，先把最小脱敏Checkpoint作为实际可见的助手回复呈现（状态、已覆盖/跳过/拒答域、下一问和排除范围），供用户纠正。该回复真实进入transcript后才能用artifact_evidence引用，禁止生成一条未实际发出的assistant轮次。未明确回应或未纠正仅证明记录已生成，不能视为用户确认环境事实。随后xb-save预览范围、执行session_store事务、重读校验并回执。任一步失败标未保存；禁止先写进度后补本体。原始各轮进度可在session.md核对，最新状态从本体查，progress只是导航。

## 读取与恢复

新会话用户明确继续环境同步时，先按startup-memory协议在已获准的项目根查询“职场环境同步 环境同步进度”，必要时用memory_ontology.query按work_item与has_status缩小查询。只选当前组织范围的有效进度；先核对日期及用户刚提到的变化，再读取来源session.md中的Checkpoint。加载当前任务相关事实，排除superseded、过期、session_only及无额外授权的受限信息。

限定字段缺失时回到来源会话核对，禁止默认全域未答；存在多个组织或并列进度且不能消歧时先问用户要继续哪段。没有可读记录就说无法确认上次进度，让用户选一方面继续，不重走初始化课程。只剩摘要时明确恢复范围，不能声称各轮完整。

用户纠正后追加新断言并连supersedes。调岗、换公司、领导变动时仅使有关旧信息待复核，当前任务停止依赖相应旧建议；拒答域继续保留。用户要求删除或跨项目搬迁走独立维护授权，保存指令不包含这些动作。


## 主题交流与材料来源兼容

新版 12 项表单的字段 ID、状态、来源和下一组写入现有 Checkpoint，随获准的 session.md 保存。读回时以字段状态计算完成度，显示原进度和下一组。已有五域状态和 schema 2 保持兼容：称呼、岗位、职责映射 role，三个公司项映射 company，汇报协作映射 people，办公方式映射 location，当前变化映射 changes。文档项状态与来源保留在 session.md；文档组的 current_domain 取 role，next_question 写实际的文档项。

旧版仅有五域状态时，从来源会话、可读附件摘录或经授权的公司档案中恢复可定位的字段。只有域名、covered 标记或旧百分比时，说明能恢复的范围，逐项保留未知。旧的域级拒答继续约束对应问题，直到用户主动重开。材料索引保留文件名、日期、定位与已读/未读范围；不增加第二份环境真源或 JSON 字段。

退出时status=paused，保留pending_task和下次可聊的位置。用户明确“保存后处理X”后按xb-save保存本次获准范围，并回到X；不重复征求已明确的普通保存授权。缺路径或保存失败时，报告未保存并暂存会话，立即继续可安全执行的X。用户选择不保存时不写任何进度文件，允许直接做事。保存成功后提供位置，失败不能被写成已完成。
