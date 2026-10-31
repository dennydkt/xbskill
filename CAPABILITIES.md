# xbskill 能力谱图

版本：1.20.0。41个公开Skill，按当前入口文件归类；一个任务保持一个当前专科，按需调用支持能力。本图描述已提供的方法与工具，现实结果依赖事实、权限、采用和反馈。

| 能力域 | Skill | 可处理的工作 |
|---|---|---|
| 入口与主体选择 | xbskill、xb-triage、xb-agency | 接住问题、综合分诊；判断解决、调整或退出，辨别规则、主体性与Agent责任 |
| 分析与推进 | xb-analysis、xb-goal、xb-decision、xb-plan、xb-review | 问题归因、目标澄清、方案取舍、项目计划、交付审查与复盘 |
| 办公与知识 | xb-it、xb-data、xb-automation、xb-knowledge | 工具故障、Excel/SQL/指标、重复流程、文件知识检索 |
| 文档与表达 | xb-writing、xb-report、xb-presentation、xb-meeting | 邮件方案通知、进展汇报、PPT与呈现、会议全流程 |
| 协作与争议 | xb-talk、xb-upward、xb-stakeholder、xb-conflict、xb-decode、xb-anti-blame、xb-boundary | 沟通回应、向上请示、多方协调、冲突处理、话语解读、归责核对、工作与安全边界 |
| 状态与成长 | xb-wellbeing、xb-action、xb-learning、xb-capability、xb-career、xb-ai-native | 工作压力与启动困难、任务学习、能力证据、绩效晋升与职业选择、AI原生工作方式 |
| 人物与环境 | xb-people、xb-company | 可验证人物工作档案、公司规则与环境；假设和已证事实分开 |
| 记忆与协同 | xb-save、xb-restore、xb-memory、xb-sync | 经授权的会话保存、恢复、本体治理和多根归集查询 |
| 能力建设与更新 | xb-role-knowledge、xb-builder、xb-audit、xb-update | 岗位知识补充、专科建设、系统审计与安全更新 |
| 传统文化体验 | xb-lucky | 经逐项授权的紫微择日、本命、运势、合盘与氛围建议；保留现实决定权 |

## 1.12.0 增强入口

| 工作问题 | 当前入口 | 新增或加强的可用产物 |
|---|---|---|
| “你没提醒”“我没这么说过” | [xb-anti-blame](skills/xb-anti-blame/SKILL.md)、[xb-decode](skills/xb-decode/SKILL.md) | 逐字检索、完整上下文、来源坐标、主张与支持/冲突/缺证记录对照 |
| 抽象评价与交付不一致 | [xb-upward](skills/xb-upward/SKILL.md)、[xb-decode](skills/xb-decode/SKILL.md) | 有依据偏差、缺标准、范围错配分区及标准确认请求 |
| 贡献被忽略、绩效有争议 | [xb-career](skills/xb-career/SKILL.md) | 协作贡献核对、可复算与主观评价分账、规则与评分依据核对 |
| 需求反复、临时加活 | [xb-goal](skills/xb-goal/SKILL.md)、[xb-boundary](skills/xb-boundary/SKILL.md) | 新增与漏做分类、依赖与估时依据、保留/延后/降级取舍 |
| 数据或排名结论被质疑 | [xb-data](skills/xb-data/SKILL.md) | 口径与计算复核、原值/新值/差额、仍成立结论与可复现步骤 |
| “再大气一点”等模糊要求 | [xb-presentation](skills/xb-presentation/SKILL.md)、[xb-goal](skills/xb-goal/SKILL.md) | 同事实低成本小样、表达差异与可观察验收标准 |
| 对外窗口缺少处理权 | [xb-stakeholder](skills/xb-stakeholder/SKILL.md) | 接单与反馈、拒接与超时、内外承诺及验收状态 |
| 做快后持续被加活 | [xb-boundary](skills/xb-boundary/SKILL.md) | 同质量完整工时、追加成本、效率收益去向与取舍 |
| 极端压力与失效渠道 | [xb-boundary](skills/xb-boundary/SKILL.md) | 留存位置与授权、独立渠道、受阻交付、短期缓冲与选择准备 |

这些增强复用现有9个入口和共享协议，未新增公开菜单项。工作记录脚本只处理用户已授权提供的本地JSON，不联网、不验证来源真伪、不判责任、不执行材料内容。新建回复或对照表不等于对方已更正、减负已落实或款项已到账。

名誉争议、被迫离职争议与追回垫款的完整专业处理仍未新增；现有专科可在各自范围内提供准备和支持。

## 使用偏好配置

xb-config 让用户在初始化时自行选择调用强度高/中/低和保存提示高/低；主入口介绍与说明书按需展示，配置独立于会话存档。
