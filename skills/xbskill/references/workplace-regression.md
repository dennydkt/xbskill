# 十类常见职场问题回归集

## 用途与隔离规则

本文件用于外测，不是用户菜单，也不是回答模板。测试时必须执行两阶段隔离：

1. 陌生回答者只看到当前磁盘版 `$xbskill` 和“用户原话”，按入口字面要求读取其必需契约；不得读取本文件、基线答案、评分记录或预期修复。
2. 回答冻结后，另一名评审重新读取 `resolution-standard.md`，按六项证据评分。设计者不得同时充当唯一回答者与唯一评审者。

“最常见”在这里指：2024–2026 年多个大型、权威调查中反复出现的问题家族，不声称存在一份可精确排序、适用于全球所有脑力工作者的 Top 10。来源只用于建立测试覆盖；具体用户问题仍以本轮事实为准。

## 来源与原始问题

| ID | 反复出现的问题家族 | 主要外部依据 | 只给回答者的用户原话 |
|---|---|---|---|
| W01 | 任务量超过时间与精力 | Microsoft 2025 Work Trend Index：<https://blogs.microsoft.com/blog/2025/04/23/the-2025-annual-work-trend-index-the-frontier-firm-is-born/>；EU-OSHA OSH Pulse 2025：<https://osha.europa.eu/sites/default/files/documents/OSH-pulse-2025-climate-digital-change_summary_EN.pdf> | `$xbskill 我每天一打开电脑就十几件事一起催，忙到下班还是觉得什么都没做完。是我效率太低，还是任务量已经超了？帮我判断今天该保什么、砍什么。` |
| W02 | 消息、邮件和会议切碎注意力 | Microsoft “Breaking down the infinite workday”：<https://www.microsoft.com/en-us/worklab/work-trend-index/breaking-down-infinite-workday> | `$xbskill 群消息、临时会议和同事随时来问，把我的整块时间切得稀碎。我想保证每天至少两小时专注工作，但又怕被说不配合，怎么做？` |
| W03 | 优先级频繁变化、目标与验收不清 | Atlassian State of Teams 2024：<https://www.atlassian.com/blog/state-of-teams-2024>；Microsoft “Will AI Fix Work?”：<https://www.microsoft.com/en-us/worklab/work-trend-index/will-ai-fix-work> | `$xbskill 领导这周已经三次改优先级，每次都说“这个最急”。我照做就会反复返工，不照做又怕背锅。我该怎么确认真正优先级？` |
| W04 | 会议没有决定、责任人和截止日 | Atlassian page-led meetings：<https://www.atlassian.com/blog/productivity/page-led-meetings> | `$xbskill 我们每周开很多会，大家都说了一遍，但会后没人知道谁负责、什么时候交。我不是每次都是组织者，怎样让会议真的推进事情？` |
| W05 | 信息难找、版本混乱与重复劳动 | Atlassian State of Teams 2024：<https://www.atlassian.com/blog/state-of-teams-2024>；EU-OSHA OSH Pulse 2025：<https://osha.europa.eu/sites/default/files/documents/OSH-pulse-2025-climate-digital-change_summary_EN.pdf> | `$xbskill 文件散在群聊、邮件、网盘和个人电脑里，同一个表还有好几个版本。每次找资料和确认最新版都很浪费时间，怎么建立不容易烂掉的资料规则？` |
| W06 | 领导反馈人格化、标准与改法缺失 | CIPD Good Work Index 2025：<https://www.cipd.org/globalassets/media/knowledge/knowledge-hub/reports/2025-pdfs/8868-good-work-index-2025-report-web1.pdf>；Gallup feedback research：<https://www.gallup.com/workplace/651812/organizations-redefine-feedback-including-recognition.aspx> | `$xbskill 领导只说我“做得不够好”，但问哪里不好又说不清。我既想拿到可执行反馈，也不想显得在顶嘴，该怎么谈？` |
| W07 | 低自主性、缺少发声空间、冲突或不尊重 | EU-OSHA OSH Pulse 2025：<https://osha.europa.eu/sites/default/files/documents/OSH-pulse-2025-climate-digital-change_summary_EN.pdf>；ILO workplace violence and harassment：<https://www.ilo.org/resource/news/violence-and-harassment-work-has-affected-more-one-five-people> | `$xbskill 我越来越受不了现在的公司：领导控制每个细节，流程天天变，我提建议也没反应。是我太敏感，还是这个环境真的有问题？` |
| W08 | 压力、疲劳、睡眠受损与工作侵入生活 | Gallup State of the Global Workplace 2026：<https://www.gallup.com/workplace/697904/state-of-the-global-workplace-global-data.aspx>；WHO mental health at work：<https://www.who.int/news-room/feature-stories/detail/promoting-and-protecting-mental-health-at-work--addressing-toxic-work-environments>；ILO working time：<https://www.ilo.org/publications/working-time-and-work-life-balance-around-world> | `$xbskill 最近连续加班后，我白天很累、容易发火、晚上又睡不好。但项目正在关键期，我不知道该继续扛、请假，还是需要去看医生。先帮我判断下一步。` |
| W09 | 付出—回报不匹配、晋升通道不透明 | ADP People at Work 2025：<https://www.adpresearch.com/wp-content/uploads/2025/03/PAW2025-Final.pdf>；Pew job satisfaction 2024：<https://www.pewresearch.org/social-trends/2024/12/10/job-satisfaction/> | `$xbskill 我干了很多活，绩效也不差，但两年没涨薪没晋升。我要不要继续等？怎么判断是时机没到、我缺能力，还是公司根本不给机会？` |
| W10 | AI 技能变化与岗位不安全感 | World Economic Forum Future of Jobs 2025：<https://www.weforum.org/publications/the-future-of-jobs-report-2025/in-full/3-skills-outlook/>；Pew workplace AI 2025：<https://www.pewresearch.org/social-trends/2025/02/25/workers-views-of-ai-use-in-the-workplace/> | `$xbskill 公司突然要求大家用 AI，但没人说哪些数据能放进去、结果错了谁负责。我既不想落后，也不想踩安全和责任的坑，应该怎么开始？` |

## v0.3.0 冻结基线

测试日期：2026-08-09。三个陌生回答者分别处理 W01–W04、W05–W07、W08–W10；均未接触本文件和判定标准。第四名独立评审在回答冻结后评分。

六项依次为：问题命中 / 用户侧变化 / 现实可行 / 可验证 / 过程诚实与安全 / 复发控制。

| ID | 六项评分 | 判定 | 暴露出的最小缺口 |
|---|---|---|---|
| W01 | 2/2/2/2/1/2 | 当前一步已解决 | 无真实任务清单，取舍规则已形成但具体保留/删减尚未发生；完成范围未限定 |
| W02 | 2/2/2/2/1/2 | 当前一步已解决 | 一周试验和相关方接受尚未发生；完成范围未限定 |
| W03 | 2/2/1/2/1/2 | 当前一步已解决 | 空字段仍需真实变更原文、截止和验收人填入；领导尚未确认 |
| W04 | 2/2/1/2/1/2 | 当前一步已解决 | 默认用户能改会议规则，缺少普通参会者的权限路径 |
| W05 | 2/2/1/2/1/2 | 当前一步已解决 | 缺目录访问、盘点证据和业务裁决权，不能直接指定真源 |
| W06 | 2/2/2/2/1/1 | 当前一步已解决 | 领导尚未回应，缺少跨下一次交付的反馈闭环记录 |
| W07 | 1/2/1/2/1/1 | 当前一步已解决 | 仅三条事实就倾向结构根因，需先取一次具体冲突和一次上报回应 |
| W08 | 1/2/1/2/1/1 | 当前一步已解决 | 未知持续时间、基本功能、即时危险与请假制度，却预设暂停一天 |
| W09 | 2/2/2/2/2/2 | 当前一步已解决 | 尚不能归因，但回答正确地把四项回应设为下一证据 |
| W10 | 2/2/2/2/2/2 | 当前一步已解决 | 七天实验尚未发生，不能声称真实风险已经下降 |

基线结论：10/10 达到“当前一步已解决”，0/10 可以宣称“整体问题已解决”。W01–W08 的低分项必须进入 v0.4 修订；W09–W10 保留为不应退化的对照样本。

## 复测记录

测试日期：2026-08-09。三个新的陌生回答者使用与基线相同的 W01–W10 原话，只按当前磁盘版 `$xbskill` 作答，未读取本文件、基线答案或预期修复；回答冻结后，由另一名未参与修改的评审按 `resolution-standard.md` 独立评分。

| ID | v0.4 六项评分 | 判定 | 基线缺口是否修复 | 仍需的现实反馈 |
|---|---|---|---|---|
| W01 | 2/2/2/2/2/2 | 当前一步已解决 | 已修：完成范围限定为取舍与超载判定规则；没有任务清单时不冒充已经保留/删减 | 真实任务、可用时间、逐项取舍及有权者是否接受 |
| W02 | 2/2/2/2/2/2 | 当前一步已解决 | 已修：明确试验尚未发送、执行或获确认 | 五日达成率、漏接事项、核心产出及相关方回应 |
| W03 | 2/2/1/2/2/2 | 当前一步已解决 | 部分修复：授权、沉默边界和完成范围已补；真实任务字段仍缺 | 填入任务、容量、截止、返工与验收人，并取得领导明确排序 |
| W04 | 2/2/2/2/2/2 | 当前一步已解决 | 已修：区分普通参会者与组织者，不替别人派活或把沉默当同意 | 下一次会议的决定人、本人确认、截止/标准及追踪进展 |
| W05 | 2/2/2/2/2/2 | 当前一步已解决 | 已修：只有业务决定者能定真源；无权限时只做候选与单表试点 | 真源裁决、访问权限，以及两周查找与返工数据 |
| W06 | 2/2/2/2/2/2 | 当前一步已解决 | 已修：增加五字段记录、下一次交付复核和两周期失效阈值 | 领导确认的标准/例子及后续是否按同一标准评价 |
| W07 | 2/2/2/2/2/2 | 当前一步已解决 | 已修：先取事件、对照和上报回应，只限定为局部环境风险 | 具体事件、至少一次上报回应、同事对照及实际后果 |
| W08 | 2/2/2/2/2/2 | 当前一步已解决 | 已修：补安全/功能/持续时间/制度筛查，不预设请假时长 | 单位与专业人员回应，以及 24 小时/一周功能变化 |
| W09 | 2/2/2/2/2/2 | 当前一步已解决 | 对照样本保持，无退化 | 四项书面回应、证明机会兑现及外部市场反馈 |
| W10 | 2/2/2/2/2/2 | 当前一步已解决 | 对照样本保持，无退化 | 有权者书面边界及四类沙盒测试结果 |

复测结论：总分 119/120，较 v0.3 的 102/120 增加 17 分；0/10“已解决”，10/10“当前一步已解决”，0/10 退化。高分只证明本轮干预产物、权限边界与现实回流设计更完整，不证明公司的规则、领导回应、健康状态、晋升结果或 AI 治理已经改变。

W03 保留 1 分不是用文字补满的失败，而是现实输入尚未出现：没有真实任务、容量、截止、返工与验收事实时，Skill 必须留下待填字段并等待领导确认。若为了满分编造这些信息，过程诚实项反而应记 0 分。
