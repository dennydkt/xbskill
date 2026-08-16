# 岗位纵深来源账与内化边界

## 目录

1. 使用规则
2. 已激活的官方来源
3. GitHub 候选固定账
4. 被拒绝或仅作发现的来源
5. 从来源到 xbskill 机制的追踪
6. 更新与失效协议

## 1. 使用规则

本文件记录本轮岗位纵深的来源、版本坐标、许可边界和功能重实现结果。它不是运行时依赖：xbskill 不下载、不安装、不执行这些仓库，也不把 stars 当可信度、成熟度或能力标准。

`stars_use: discovery_only`：星数只记录带时间的候选发现信号，绝不参与证据加权。

来源状态：

- `activated`：来源能支持一项明确机制，已按 xbskill 语言重新推导，并保留适用边界。
- `supporting`：用于交叉检查结构，不单独支撑关键结论。
- `discovery_only`：只帮助发现主题；不把内容内化为规则。
- `rejected`：因许可、版本、权威性、安全或适用性原因明确不用。

许可原则：只内化可独立重实现的功能关系，不复制外部图表、模板、题库或大段文字；许可不清时降为发现线索。外部产品“具有某功能”只证明一种可能对象关系，不能证明企业已经采用、过程有效或岗位具备该能力。

抓取时点：除单独注明外，GitHub metadata 为 **2026-08-11（Asia/Shanghai）** 的只读结果；stars 会变化。精确引用固定在 40 位 commit，默认分支只作背景。

## 2. 已激活的官方来源

### 2.1 跨岗位能力与角色责任

| ID / 状态 | 来源 | 内化机制 | 边界 |
|---|---|---|---|
| OFF-01 `activated` | [UK Government Digital and Data Profession Capability Framework](https://ddat-capability-framework.service.gov.uk/) 及 [产品经理](https://ddat-capability-framework.service.gov.uk/role/product-manager)、[交互设计师](https://ddat-capability-framework.service.gov.uk/role/interaction-designer)、[前端开发](https://ddat-capability-framework.service.gov.uk/role/frontend-developer)、[软件开发](https://ddat-capability-framework.service.gov.uk/role/software-developer)、[技术架构](https://ddat-capability-framework.service.gov.uk/role/technical-architect)、[交付管理](https://ddat-capability-framework.service.gov.uk/role/delivery-manager)、[数据分析](https://ddat-capability-framework.service.gov.uk/role/data-analyst)、[数据工程](https://ddat-capability-framework.service.gov.uk/role/data-engineer)、[数据治理](https://ddat-capability-framework.service.gov.uk/role/data-governance-manager) | 岗位围绕真实结果、生命周期、跨专业接口和递增责任深度；按任务证据适配帮助，而非按年限 | 页面内容按 Open Government Licence v3.0 使用；xbskill 将多级角色压缩为三种用户帮助阶段，不声称一一换算 |
| OFF-02 `supporting` | [SFIA 9：How SFIA works](https://sfia-online.org/en/about-sfia/how-sfia-works?set_language=en) | 用自主性、影响、复杂度、知识等责任维度交叉验证“阶段不是年限” | SFIA 有独立许可；不复制其等级文本、图表或岗位定义，只保留 xbskill 自有的五项证据轴 |

### 2.2 数据岗位与生命周期

| ID / 状态 | 来源 | 内化机制 | 边界 |
|---|---|---|---|
| OFF-D01 `activated` | [UK Government Data Quality Framework](https://www.gov.uk/government/publications/the-government-data-quality-framework/the-government-data-quality-framework) | 数据质量贯穿生产、处理、使用与反馈；从用户需要、元数据、源头根因、风险/成本和循环改进构造九段闭环 | 政府框架提供检查面，具体质量阈值、owner 和法规由用户组织决定 |
| OFF-D02 `supporting` | [Government Data Maturity Assessment](https://www.gov.uk/government/publications/data-maturity-assessment-for-government-framework) | 将组织成熟度与个人任务能力分开 | 页面注明框架正在修订；不固化其评分和成熟度结论 |
| OFF-D03 `supporting` | [DAMA-DMBOK 官方介绍](https://dama.org/learning-resources/dama-data-management-body-of-knowledge-dmbok/) | 交叉检查数据管理覆盖域 | 正文和图表受版权保护；不复制框架内容，不用它替代本地责任与证据 |

### 2.3 产品研发与运行

| ID / 状态 | 来源 | 内化机制 | 边界 |
|---|---|---|---|
| OFF-P01 `activated` | [GOV.UK Agile delivery](https://www.gov.uk/service-manual/agile-delivery)、[Discovery](https://www.gov.uk/service-manual/agile-delivery/how-the-discovery-phase-works)、[Alpha](https://www.gov.uk/service-manual/agile-delivery/how-the-alpha-phase-works)、[Measuring service success](https://www.gov.uk/service-manual/measuring-success/measuring-the-success-of-your-service) | 先理解问题、验证高风险假设、允许 no-build/stop，以研究、产品结果、运行和成本多源反馈迭代 | 政府服务阶段不是所有企业的强制流程；内化为生命周期决定门，不复制组织形式 |
| OFF-P02 `activated` | [WCAG 2.2 Recommendation](https://www.w3.org/TR/2024/REC-WCAG22-20241212/) 与 [WAI-ARIA APG introduction](https://www.w3.org/WAI/ARIA/apg/about/introduction/) | 可访问性成为设计、实现、测试和发布合同；自动、人工、辅助技术/用户验证互不替代 | APG 明确是 informative，不是规范或生产设计系统；命中实际合规时锁定适用标准版本 |
| OFF-P03 `activated` | [DORA Continuous Delivery](https://dora.dev/capabilities/continuous-delivery/)、[Monitoring and Observability](https://dora.dev/capabilities/monitoring-and-observability/)、[Loosely Coupled Teams](https://dora.dev/capabilities/loosely-coupled-teams/) | 小批次、可发布、可观测反馈和团队自治边界共同构成工程闭环 | 相关关系不能机械变成单团队 KPI；具体目标和因果需本地证据 |
| OFF-P04 `activated` | Google SRE：[Monitoring Distributed Systems](https://sre.google/sre-book/monitoring-distributed-systems/) 与 [Embracing Risk](https://sre.google/sre-book/embracing-risk/) | 把用户侧结果、SLI/SLO、错误预算、告警和风险取舍接入运行反馈 | SRE 实践不是所有产品的固定组织结构；阈值不得从来源外推到用户系统 |
| OFF-P05 `supporting` | [Google Cloud Well-Architected Framework](https://docs.cloud.google.com/architecture/framework?hl=en) | 交叉检查质量属性、运行和演进维度 | 云厂商框架不证明某云产品或架构适合用户，不能替代选型证据 |

### 2.4 职能岗位与记录

| ID / 状态 | 来源 | 内化机制 | 边界 |
|---|---|---|---|
| OFF-F01 `activated` | [UK Government Functional Standard GovS 002: Project delivery](https://projectdelivery.gov.uk/govs-002-project-delivery-functional-standard/) 与 [APM Competence Framework](https://www.apm.org.uk/resources/find-a-resource/competence-framework/) | 项目入口、治理、计划、控制、角色、采购、风险与收益回流；以知识应用、结果和复杂度看能力 | 不复制受保护的完整能力框架；政府标准不是所有公司的强制制度 |
| OFF-F02 `supporting` | [IAAP CAP Body of Knowledge](https://www.iaap-hq.org/page/CAPBOK) | 交叉检查行政任务域：沟通、软件/数据、办公室/记录、会议/活动/项目和运营 | 考试知识体系不是岗位真相，不复制题纲或认证内容 |
| OFF-F03 `activated` | [ISO 15489-1:2016 官方页](https://www.iso.org/standard/62542.html) 与 [NARA recordkeeping requirements](https://www.archives.gov/records-mgmt/policy/agency-recordkeeping-requirements.html) | 记录形成、捕获、元数据、责任、维护、处置；会议记录区分参会、材料、讨论、决定、后续行动和责任 | ISO 正文受版权保护；NARA 是美国联邦语境，只内化通用记录字段，不当中国法律 |
| OFF-F04 `activated` | [NIST SP 800-61 Rev.3](https://csrc.nist.gov/pubs/sp/800/61/r3/final) | 事件准备、响应、恢复、行动记录和事后改进的状态链 | 网络安全事件框架只提供事件对象关系；行政/运营事件需按本地风险重推导 |
| OFF-F05 `activated` | 中国官方：[党政机关公文处理工作条例](https://www.gov.cn/zhengce/2013-02/22/content_2640088.htm)、[国家档案局第13号令](https://www.saac.gov.cn/daj/szda/201810/891d8b7717e549a185afc4796ba8c6b9.shtml)、[保守国家秘密法](https://www.npc.gov.cn/npc/c2/c30834/202402/t20240227_434859.html) | 公文、公务档案和保密成为条件触发的法规门；先判断主体与事项是否适用 | 不把党政机关规则默认套给企业普通文书；具体密级、归档和处置由有权规则决定 |
| OFF-F06 `activated` | [中华人民共和国公司法](https://www.samr.gov.cn/zw/zfxxgk/fdzdgknr/fgs/art/2023/art_067c072db6ef4679a2e0180996be4cf8.html) 第 138 条 | “秘书”角色先辨义；上市公司董事会秘书命中法定职责时单独建模 | 不由通用 xbskill 提供法律结论；需锁定当前法规、章程和有权专业意见 |

### 2.5 组织环境与中国实体

| ID / 状态 | 来源 | 内化机制 | 边界 |
|---|---|---|---|
| OFF-O01 `activated` | [中央企业合规管理办法](https://www.sasac.gov.cn/n2588035/n2588320/n2588335/c26018430/content.html) 与 [国企重大事项前置研究官方问答](https://www.ndrc.gov.cn/fggz/gbzj/xxyd/202111/t20211130_1306302_ext.html) | 央企场景优先核验具体企业层级、事项清单、合规与党委会/董事会/经理层实际权责 | 直接适用范围有边界；不得推广为“所有国企都慢/都走同一链”，前置研究也不替代有权主体决定 |
| OFF-O02 `activated` | [政府采购法实施条例](https://xzfg.moj.gov.cn/front/law/detail?LawID=417) | 采购适用先看主体、财政性资金和事项，不看单位印象 | “国企采购=政府采购”“事业单位所有采购都适用”均不得成立 |
| OFF-O03 `activated` | [外商投资法](https://www.npc.gov.cn/zgrdw/pc/13_2/2019-03/15/content_2083830.htm) 与 [个人信息保护法](https://www.npc.gov.cn/npc/c2/c30834/202108/t20210820_313088.html) | 外企场景分开核验法律实体、HQ/本地权责与真实数据流；跨境个人信息单独过门 | 投资关系不定义企业文化；是否跨境、适用何机制需当前事实与专业复核 |
| OFF-O04 `activated` | [民营经济促进法](https://www.npc.gov.cn/npc/c2/c30834/202504/t20250430_445088.html) | 民营类别是法律/所有权入口，不是创始人文化或管理成熟度结论 | 类别可能与外商投资等交叉；真实决定、流程和激励仍看案例 |
| OFF-O05 `activated` | [事业单位人事管理条例](https://www.gov.cn/zhengce/2014-05/15/content_2680034.htm) | 事业单位先核验单位性质、主管部门、分类和事项规则 | 不与政府机关混同，不从单一样本外推全部事业单位 |

## 3. GitHub 候选固定账

### 3.1 数据工程与治理

| ID / repo | Stars；LICENSE；分支；固定 commit | 已内化机制 | 适用边界 |
|---|---|---|---|
| GH-D01 [`datahub-project/datahub`](https://github.com/datahub-project/datahub) | 12,508；Apache-2.0；`master`；`b6ba908404cea72e4ef5e1524e7809915693f2eb` | [README L117–134、219–220](https://github.com/datahub-project/datahub/blob/b6ba908404cea72e4ef5e1524e7809915693f2eb/README.md#L117-L134) 与 [lineage tutorial L1–79](https://github.com/datahub-project/datahub/blob/b6ba908404cea72e4ef5e1524e7809915693f2eb/docs/api/tutorials/lineage.md#L1-L79)：源—转换—消费、列映射、影响分析 | 自动血缘可不完整/错误；目录不等于治理；README 不是岗位标准 |
| GH-D02 [`open-metadata/OpenMetadata`](https://github.com/open-metadata/OpenMetadata) | 14,841；Apache-2.0；`main`；`1cf935be11b10b7eb664efec73bbc49e6daa84bb` | [README L11–40](https://github.com/open-metadata/OpenMetadata/blob/1cf935be11b10b7eb664efec73bbc49e6daa84bb/README.md#L11-L40)：owner、语义、质量、freshness、血缘、政策、契约、使用和数据产品组成上下文包 | 产品能力陈述不证明企业采用或数据可信 |
| GH-D03 [`apache/airflow`](https://github.com/apache/airflow) | 46,438；Apache-2.0；`main`；`655740bb98282ca64d5bde2aeec65da8c56b1930` | [README L45–47](https://github.com/apache/airflow/blob/655740bb98282ca64d5bde2aeec65da8c56b1930/README.md#L45-L47)：工作流代码化、版本化、测试、调度和监控 | 编排器不是计算/流处理引擎；任务成功不证明数据正确 |
| GH-D04 [`fivetran/great_expectations`](https://github.com/fivetran/great_expectations) | 11,705；Apache-2.0；`develop`；`39765c6ed0d44071d0d802169e568ed0bff10c41` | [README L16–20](https://github.com/fivetran/great_expectations/blob/39765c6ed0d44071d0d802169e568ed0bff10c41/README.md#L16-L20)：质量期望、可执行规则、验证结果和共享语言 | “通过”只证明已测试条件；阈值和错误成本必须来自用途与 owner |
| GH-D05 [`OpenLineage/OpenLineage`](https://github.com/OpenLineage/OpenLineage) | 2,596；Apache-2.0；`main`；`7c5f2e767a7c1671be049cc56f77394627b4ba2f` | [README L12–40](https://github.com/OpenLineage/OpenLineage/blob/7c5f2e767a7c1671be049cc56f77394627b4ba2f/README.md#L12-L40)：run/job/dataset/facets 的跨工具事件模型 | 事件规范不证明血缘完整、正确或治理闭环 |
| GH-D06 [`dbt-labs/dbt-core`](https://github.com/dbt-labs/dbt-core) | 13,615；Apache-2.0；`main`；`c5f2ba00b9cb63b95bf152e764f885690f82df18` | [README L41–45](https://github.com/dbt-labs/dbt-core/blob/c5f2ba00b9cb63b95bf152e764f885690f82df18/README.md#L41-L45)：分析模型作为版本化依赖图并测试转换 | 当时 `main` 明示 v2 alpha；接口不内化，模型测试不替代源头控制和业务授权 |

### 3.2 产品研发

| ID / repo | Stars；LICENSE；分支；固定 commit | 已内化机制 | 适用边界 |
|---|---|---|---|
| GH-P01 [`alphagov/govuk-design-system`](https://github.com/alphagov/govuk-design-system) | 658；MIT；`main`；`efb0d77d38b7ed7f921697564d2c47723d434977` | [贡献门 L13–100](https://github.com/alphagov/govuk-design-system/blob/efb0d77d38b7ed7f921697564d2c47723d434977/src/community/contribution-criteria/index.md#L13-L100)、[持续研究 L10–48](https://github.com/alphagov/govuk-design-system/blob/efb0d77d38b7ed7f921697564d2c47723d434977/src/community/continuous-research/index.md#L10-L48)、[无障碍验证 L210–274](https://github.com/alphagov/govuk-design-system/blob/efb0d77d38b7ed7f921697564d2c47723d434977/src/accessibility/accessibility-strategy/index.md#L210-L274)：有用、可用、一致、可复用到发布的证据门 | 政府服务/该系统语境；使用组件不自动使服务可访问 |
| GH-P02 [`google/eng-practices`](https://github.com/google/eng-practices) | 23,310；CC BY 3.0；`master`；`3bb3ec25b3b0199f4940b1aa75f0ac5c5753301c`；已归档 | [review standard L5–68](https://github.com/google/eng-practices/blob/3bb3ec25b3b0199f4940b1aa75f0ac5c5753301c/review/reviewer/standard.md#L5-L68)、[looking for L9–80](https://github.com/google/eng-practices/blob/3bb3ec25b3b0199f4940b1aa75f0ac5c5753301c/review/reviewer/looking-for.md#L9-L80)、[small changes L46–63](https://github.com/google/eng-practices/blob/3bb3ec25b3b0199f4940b1aa75f0ac5c5753301c/review/developer/small-cls.md#L46-L63)：证据优先、小而完整、持续改善 | 归档历史指南，不是持续更新标准 |
| GH-P03 [`github/docs`](https://github.com/github/docs) | 20,643；内容 CC BY 4.0/代码 MIT；`main`；`5cc4248e19d93bdcf592090568afb2a25b0ad8da` | [CD L23–40](https://github.com/github/docs/blob/5cc4248e19d93bdcf592090568afb2a25b0ad8da/content/actions/get-started/continuous-deployment.md#L23-L40)、[环境门 L47–55](https://github.com/github/docs/blob/5cc4248e19d93bdcf592090568afb2a25b0ad8da/content/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments.md#L47-L55)、[发布史 L20–42](https://github.com/github/docs/blob/5cc4248e19d93bdcf592090568afb2a25b0ad8da/content/actions/how-tos/deploy/configure-and-manage-deployments/view-deployment-history.md#L20-L42)：环境门、批准、并发和可追踪发布 | GitHub Actions 产品行为，不写成普适 CI/CD 事实 |
| GH-P04 [`microsoft/api-guidelines`](https://github.com/microsoft/api-guidelines) | 23,316；CC BY 4.0；`vNext`；`a7022a299442a8352431874e63ec4dff548a1b81` | [目标/兼容 L38–66](https://github.com/microsoft/api-guidelines/blob/a7022a299442a8352431874e63ec4dff548a1b81/azure/Guidelines.md#L38-L66)、[幂等/错误 L134–173](https://github.com/microsoft/api-guidelines/blob/a7022a299442a8352431874e63ec4dff548a1b81/azure/Guidelines.md#L134-L173)、[破坏变更 L16–49](https://github.com/microsoft/api-guidelines/blob/a7022a299442a8352431874e63ec4dff548a1b81/azure/VersioningGuidelines.md#L16-L49)：契约、例外、重试/幂等和版本兼容 | 主要面向 Azure data-plane API，需按本地协议重推导 |
| GH-P05 [`OWASP/ASVS`](https://github.com/OWASP/ASVS) | 3,541；CC BY-SA 4.0；`master`；`cdc8a0f68ac2a9f9e3739266acdac0e4a98badee` | [稳定边界 L38–47](https://github.com/OWASP/ASVS/blob/cdc8a0f68ac2a9f9e3739266acdac0e4a98badee/README.md#L38-L47) 与 [验证用途 L49–115](https://github.com/OWASP/ASVS/blob/cdc8a0f68ac2a9f9e3739266acdac0e4a98badee/5.0/en/0x03-What-is-the-ASVS.md#L49-L115)：安全目标可 pass/fail，设计决定与实现验证分开 | 默认分支在开发；现实使用锁稳定版；ASVS 等级不是人员能力等级 |
| GH-P06 [`open-telemetry/opentelemetry-specification`](https://github.com/open-telemetry/opentelemetry-specification) | 4,302；Apache-2.0；`main`；`2f143d3a282aabd1866e31d39a3e2caa3abe36c6` | [signals/context L50–73](https://github.com/open-telemetry/opentelemetry-specification/blob/2f143d3a282aabd1866e31d39a3e2caa3abe36c6/specification/overview.md#L50-L73)、[trace L117–136](https://github.com/open-telemetry/opentelemetry-specification/blob/2f143d3a282aabd1866e31d39a3e2caa3abe36c6/specification/overview.md#L117-L136)：分信号、统一上下文关联 | telemetry 规范不定义产品结果、告警策略或 SLO |
| GH-P07 [`donnemartin/system-design-primer`](https://github.com/donnemartin/system-design-primer) | 362,992；CC BY 4.0；`master`；`ae9bbd7b02d90b9866215de185217d33f39ab733` | [需求—设计—扩展—估算 L226–276](https://github.com/donnemartin/system-design-primer/blob/ae9bbd7b02d90b9866215de185217d33f39ab733/README.md#L226-L276)：先约束和估算，再设计与权衡 | 面试教材；样例架构不能当生产标准 |
| GH-P08 [`storybookjs/storybook`](https://github.com/storybookjs/storybook) | 90,805；MIT；`next`；`8686f18aa61995a781b094d66bead49c55f15627` | [隔离 UI L47–49](https://github.com/storybookjs/storybook/blob/8686f18aa61995a781b094d66bead49c55f15627/README.md#L47-L49) 与 [设计/测试 L83–142](https://github.com/storybookjs/storybook/blob/8686f18aa61995a781b094d66bead49c55f15627/README.md#L83-L142)：组件状态成为设计、开发、测试共用合同 | 工具存在不等于测试充分或符合 WCAG |
| GH-P09 `activated` [`nextlevelbuilder/ui-ux-pro-max-skill`](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) | 115,482；MIT；`main`；`abb7f2fd5a083fa1ff55c326a963ff0d95c33f99` | [`.claude/skills/ui-ux-pro-max/SKILL.md`](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/abb7f2fd5a083fa1ff55c326a963ff0d95c33f99/.claude/skills/ui-ux-pro-max/SKILL.md) L20–33、L49–65、L72–91；[`src/ui-ux-pro-max/data/ux-guidelines.csv`](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/abb7f2fd5a083fa1ff55c326a963ff0d95c33f99/src/ui-ux-pro-max/data/ux-guidelines.csv) L29–46、L55–70、L79–100；[`references/pro-rules.md`](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/abb7f2fd5a083fa1ff55c326a963ff0d95c33f99/references/pro-rules.md) L63–109：把任务影响与约束转成有顺序的体验检查，以项目级 MASTER 和有理由的局部 override 管理一致性，再回到实际界面状态与无障碍验证 | 只内化优先级、规则继承和验证关系，不复制规则表、模板或生成资产；`ui-reasoning` 仅作 `discovery_only`，规则命中不证明真实体验或合规 |
| GH-P10 `activated` [`mohitagw15856/pm-claude-skills`](https://github.com/mohitagw15856/pm-claude-skills) | 1,271；MIT；`main`；`0625128f0eb225e2811868e480816dbfa6f690f5` | [`skills/discovery-interview-guide/SKILL.md`](https://github.com/mohitagw15856/pm-claude-skills/blob/0625128f0eb225e2811868e480816dbfa6f690f5/skills/discovery-interview-guide/SKILL.md) L10–50、L54–80、L100–133；[`skills/user-research-synthesis/SKILL.md`](https://github.com/mohitagw15856/pm-claude-skills/blob/0625128f0eb225e2811868e480816dbfa6f690f5/skills/user-research-synthesis/SKILL.md) L25–119、L140–165；[`skills/competitive-analysis/SKILL.md`](https://github.com/mohitagw15856/pm-claude-skills/blob/0625128f0eb225e2811868e480816dbfa6f690f5/skills/competitive-analysis/SKILL.md) L17–32、L50–99、L108–125；[`skills/assumption-mapper/SKILL.md`](https://github.com/mohitagw15856/pm-claude-skills/blob/0625128f0eb225e2811868e480816dbfa6f690f5/skills/assumption-mapper/SKILL.md) L16–53、L55–84、L93–109；[`skills/experiment-designer/SKILL.md`](https://github.com/mohitagw15856/pm-claude-skills/blob/0625128f0eb225e2811868e480816dbfa6f690f5/skills/experiment-designer/SKILL.md) L10–42、L44–77；[`skills/metric-tree-builder/SKILL.md`](https://github.com/mohitagw15856/pm-claude-skills/blob/0625128f0eb225e2811868e480816dbfa6f690f5/skills/metric-tree-builder/SKILL.md) L10–44、L58–71：把问题假设、最近实际行为、证据冲突、关键假设和可翻转实验连到结果/护栏观测 | 只重实现证据关系，不复制访谈、分析、实验或指标模板；`user-research-synthesis` L167–187 的固定数字不采用，样本、窗口和判断线必须按任务校准 |
| GH-P11 `discovery_only` [`deanpeters/Product-Manager-Skills`](https://github.com/deanpeters/Product-Manager-Skills) | 6,398；CC BY-NC-SA 4.0；`main`；`e58cff6818f50142bcd64558bfad5bf7a99c6f9b` | [`skills/discovery-process/SKILL.md`](https://github.com/deanpeters/Product-Manager-Skills/blob/e58cff6818f50142bcd64558bfad5bf7a99c6f9b/skills/discovery-process/SKILL.md) L36–58、L184–223、L247–265、L287–315、L324–360；[`skills/competitive-analysis-process/SKILL.md`](https://github.com/deanpeters/Product-Manager-Skills/blob/e58cff6818f50142bcd64558bfad5bf7a99c6f9b/skills/competitive-analysis-process/SKILL.md) L35–66、L84–144、L146–157、L184–195；[`skills/opportunity-solution-tree/SKILL.md`](https://github.com/deanpeters/Product-Manager-Skills/blob/e58cff6818f50142bcd64558bfad5bf7a99c6f9b/skills/opportunity-solution-tree/SKILL.md) L38–70、L155–200、L214–264、L270–350、L371–415；[`skills/prioritization-advisor/SKILL.md`](https://github.com/deanpeters/Product-Manager-Skills/blob/e58cff6818f50142bcd64558bfad5bf7a99c6f9b/skills/prioritization-advisor/SKILL.md) L39–78、L275–327、L394–428；[`skills/epic-hypothesis/SKILL.md`](https://github.com/deanpeters/Product-Manager-Skills/blob/e58cff6818f50142bcd64558bfad5bf7a99c6f9b/skills/epic-hypothesis/SKILL.md) L38–70、L89–191、L224–267：只用于发现产品探索、机会与优先级主题 | 非商业且相同方式共享的许可边界不进入内置岗位主张；不复制流程、树、题库或模板，`prioritization-advisor` L203–255 占位内容明确排除 |

### 3.3 职能、记录与事件

| ID / repo | Stars；LICENSE；分支；固定 commit | 已内化机制 | 适用边界 |
|---|---|---|---|
| GH-F01 [`makeplane/plane`](https://github.com/makeplane/plane) | 55,787；AGPL-3.0；默认分支 HEAD `1c8a60f858d8472aa56e29994ec1c7926da2c6ce` | [README L51–67](https://github.com/makeplane/plane/blob/1c8a60f858d8472aa56e29994ec1c7926da2c6ce/README.md#L51-L67)：工作项—周期—模块—视图—页面—分析对象；笔记转行动 | 只内化对象关系；不复制 UI/代码，部署涉及 AGPL |
| GH-F02 [`opf/openproject`](https://github.com/opf/openproject) | 15,818；GPL-3.0；默认分支 HEAD `df1aecd1af103a28189b585494fc79c59d694c22` | [README L16–26](https://github.com/opf/openproject/blob/df1aecd1af103a28189b585494fc79c59d694c22/README.md#L16-L26)：项目/组合、计划、成本、协作、议程和纪要为关联对象 | 产品功能不是项目专业标准，也不构成部署推荐 |
| GH-F03 [`architecture-decision-record/architecture-decision-record`](https://github.com/architecture-decision-record/architecture-decision-record) | 16,627；GitHub `NOASSERTION`，内容/模板混合许可；HEAD `1a5978e82396cd1a394e015f3d2ec6e3b30c1691` | [README L68–72、100–132](https://github.com/architecture-decision-record/architecture-decision-record/blob/1a5978e82396cd1a394e015f3d2ec6e3b30c1691/README.md#L100-L132)：决定保留语境与后果、追加式决定链 | 只做功能重实现，不复制任一模板；混合许可阻止整体复用 |
| GH-F04 [`paperless-ngx/paperless-ngx`](https://github.com/paperless-ngx/paperless-ngx) | 44,149；GPL-3.0；HEAD `855669ddf93e25fe5c45420781e191a7df63884d` | [README L20–22](https://github.com/paperless-ngx/paperless-ngx/blob/855669ddf93e25fe5c45420781e191a7df63884d/README.md#L20-L22)：捕获、索引、检索和归档对象意识 | 不是法定档案系统；仓库有明文存储/不可信主机 [安全警告 L102–103](https://github.com/paperless-ngx/paperless-ngx/blob/855669ddf93e25fe5c45420781e191a7df63884d/README.md#L102-L103) |
| GH-F05 [`Netflix/dispatch`](https://github.com/Netflix/dispatch) | 6,497；Apache-2.0；HEAD `dd2837e82a0bf5565b1b4b4b91ea30b7262d4061`；已归档 | [README L28–32](https://github.com/Netflix/dispatch/blob/dd2837e82a0bf5565b1b4b4b91ea30b7262d4061/README.md#L28-L32)：事件资源、参与者、通知、任务和事后复盘状态链 | 已归档，不建议成为依赖；安全事件泛化为行政事件时必须重推导 |

### 3.4 金融投研

| ID / repo | Stars；LICENSE；分支；固定 commit | 已内化机制 | 适用边界 |
|---|---|---|---|
| GH-R01 `activated` [`anthropics/financial-services`](https://github.com/anthropics/financial-services) | 34,169；Apache-2.0；`main`；`38652224c10610fa52eee2acee3ac712dcff01f2` | [`plugins/vertical-plugins/equity-research/skills/thesis-tracker/SKILL.md`](https://github.com/anthropics/financial-services/blob/38652224c10610fa52eee2acee3ac712dcff01f2/plugins/vertical-plugins/equity-research/skills/thesis-tracker/SKILL.md) L10–32、L34–65；[`earnings-analysis/SKILL.md`](https://github.com/anthropics/financial-services/blob/38652224c10610fa52eee2acee3ac712dcff01f2/plugins/vertical-plugins/equity-research/skills/earnings-analysis/SKILL.md) L35–52、L108–142；[`catalyst-calendar/SKILL.md`](https://github.com/anthropics/financial-services/blob/38652224c10610fa52eee2acee3ac712dcff01f2/plugins/vertical-plugins/equity-research/skills/catalyst-calendar/SKILL.md) L10–52、L54–82；[`idea-generation/SKILL.md`](https://github.com/anthropics/financial-services/blob/38652224c10610fa52eee2acee3ac712dcff01f2/plugins/vertical-plugins/equity-research/skills/idea-generation/SKILL.md) L10–18、L64–72、L74–109；[`initiating-coverage/references/valuation-methodologies.md`](https://github.com/anthropics/financial-services/blob/38652224c10610fa52eee2acee3ac712dcff01f2/plugins/vertical-plugins/equity-research/skills/initiating-coverage/references/valuation-methodologies.md) L131–155、L356–408：把可证伪论点、催化剂、财报实际/基线/新预测桥与估值情景敏感性连成更新链 | 只内化对象关系，不复制研究模板、筛选条件或方法权重；来源不能证明投资建议正确，也不授权推荐、交易、调仓或接受投资风险 |

### 3.5 营销

| ID / repo | Stars；LICENSE；分支；固定 commit | 已内化机制 | 适用边界 |
|---|---|---|---|
| GH-M01 `activated` [`coreyhaines31/marketingskills`](https://github.com/coreyhaines31/marketingskills) | 43,865；MIT；`main`；`7868cb9251fad80a73d26e488a5ad5f6c4a9f335` | [`skills/customer-research/SKILL.md`](https://github.com/coreyhaines31/marketingskills/blob/7868cb9251fad80a73d26e488a5ad5f6c4a9f335/skills/customer-research/SKILL.md) L31–110、L137–148；[`skills/product-marketing/SKILL.md`](https://github.com/coreyhaines31/marketingskills/blob/7868cb9251fad80a73d26e488a5ad5f6c4a9f335/skills/product-marketing/SKILL.md) L16–51、L76–121、L232–243；[`skills/marketing-plan/SKILL.md`](https://github.com/coreyhaines31/marketingskills/blob/7868cb9251fad80a73d26e488a5ad5f6c4a9f335/skills/marketing-plan/SKILL.md) L41–79、L81–99、L157–164、L184–205；[`skills/copywriting/SKILL.md`](https://github.com/coreyhaines31/marketingskills/blob/7868cb9251fad80a73d26e488a5ad5f6c4a9f335/skills/copywriting/SKILL.md) L12–57、L106–143、L149–166；[`skills/ab-testing/SKILL.md`](https://github.com/coreyhaines31/marketingskills/blob/7868cb9251fad80a73d26e488a5ad5f6c4a9f335/skills/ab-testing/SKILL.md) L25–64、L98–116、L166–216、L236–273：把客户证据与内部观点分账，把优先级和不做项连接资源约束，并在看结果前固定假设、主指标、护栏和低流量替代分支 | 只重实现证据、计划与实验关系，不复制研究、计划、文案或实验模板；不证明本地客户事实、因果、合规或渠道效果，样本与判断线须按任务校准 |

## 4. 被拒绝或仅作发现的来源

| 来源 | 状态 | 理由 |
|---|---|---|
| [`nilbuild/developer-roadmap`](https://github.com/nilbuild/developer-roadmap)（原 `kamranahmedse/developer-roadmap`） | `rejected` | 364,098 stars 仅带来发现价值；自定义限制性许可证明确限制内容复用。未复制或蒸馏其路线图，只确认候选岗位名。固定 commit `643e56c0b853d97fffb53046577ce59b8a4d32da` |
| [`DataTalksClub/data-engineering-zoomcamp`](https://github.com/DataTalksClub/data-engineering-zoomcamp) | `discovery_only` | 44,485 stars；GitHub API 为 `NOASSERTION`。只观察“基础—端到端项目—同伴评审”的训练关系，不复制课程、代码或资产；课程完成不等于生产能力 |
| GH-X01 [`VoltAgent/awesome-agent-skills`](https://github.com/VoltAgent/awesome-agent-skills) | `discovery_only` | 29,991 stars；MIT；`main`；固定 commit `63097f81f4d00d5e13ffad8b3ad371a2d46f1afa`。[`README.md`](https://github.com/VoltAgent/awesome-agent-skills/blob/63097f81f4d00d5e13ffad8b3ad371a2d46f1afa/README.md) L58–77、L1897–1908、L1930–1937、L1952–1956 与 [`CONTRIBUTING.md`](https://github.com/VoltAgent/awesome-agent-skills/blob/63097f81f4d00d5e13ffad8b3ad371a2d46f1afa/CONTRIBUTING.md) L15–27 只用于发现候选主题和目录关系；聚合收录不证明单项许可、质量、安全或岗位事实，不进入 RoleKnowledge claim |
| `K-Dense-AI/claude-admin-skills`（无 GH-ID） | `unavailable` | 2026-08-11 只读 GitHub API 返回 404，且该组织当时 13 个公开仓库中没有可验证替代项；没有固定 commit 和证据坐标，因此不造 commit、不登记为来源，也不支撑任何结论 |
| 任一仓库 stars、README 宣传或功能列表 | `discovery_only` | stars 会变化且不证明质量；README 是作者陈述；功能存在不证明本地采用、可信、安全、合规或现实效果 |

## 5. 从来源到 xbskill 机制的追踪

| xbskill 新机制 | 主要证据 IDs | 功能重实现结果 |
|---|---|---|
| 岗位上下文与三阶段帮助 | OFF-01、OFF-02、OFF-F01 | `role-context-model.md`：阶段按任务证据，和 L0–L4 分账 |
| 企业数据九段闭环 | OFF-D01、GH-D01–D06 | `data-work-specialties.md`：决定、源头、管道、治理、服务、分析、采用与退役连成一条证据链 |
| 产品研发全生命周期与角色合同 | OFF-P01–P05、GH-P01–P08 | `product-rd-specialties.md`：探索、体验/API、增量、发布、运行与迭代对象；含 no-build、回滚和观测 |
| 产品问题证伪与体验规则继承补强 | GH-P09、GH-P10 | `product-rd-specialties.md` 与候选 RoleKnowledgeUnit：最近行为/冲突证据/最便宜翻转实验，以及 MASTER—override—实际状态/无障碍验证关系 |
| 职能事项与记录工程 | OFF-F01–F06、GH-F01–F05 | `function-work-specialties.md`：事项卡、权力图、会议/决定、采购、事件和记录对象 |
| 金融投研论点与证据更新 | GH-R01 | `finance-marketing-specialties.md` 与候选 RoleKnowledgeUnit：可证伪论点、财报基线桥、估值情景和敏感性；不授予交易权 |
| 营销证据与受控实验 | GH-M01 | `finance-marketing-specialties.md` 与候选 RoleKnowledgeUnit：客户证据分账、计划优先级/不做项、预注册实验、护栏和低流量分支 |
| 组织策略基因与反刻板交互 | OFF-O01–O05 | `organization-strategy-genome.md`：类别只排序问题，真实案例激活可证伪基因 |
| 陌生外测与回归 | 上述全部仅作观察面 | `role-specialty-regression.md` 与自动脚本验证输出行为，而非检查关键词堆积 |

## 6. 更新与失效协议

1. 外部来源只在受影响专业事实发生变化、现有案例暴露缺口或用户要求刷新时重查，不为追逐 stars 定期改模型。
2. 更新 GitHub 机制前重新记录抓取时间、license、默认分支、40 位 commit 和精确坐标；默认分支内容不能覆盖旧的固定证据。
3. 官方规则按实体、地域、事项和生效版本判断；高风险法律/合规结论必须重新联网核验并交有权专业人员复核。
4. 来源冲突按问题类型裁决：规范看当前适用官方文本，实现行为看固定版本与测试，效果主张看研究质量，本地流程看本地真源。无法裁决就并列并停止受影响结论。
5. 任一来源被归档、改许可、出现安全问题或适用语境变化，先把相应 claim 标为 stale/rejected；运行时保留通用安全路径，不静默换成模型记忆。
