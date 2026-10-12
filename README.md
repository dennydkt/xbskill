# xbskill

> 面向脑力工作者的“快点下班”工作生存与选择系统。把任务、沟通、卡点、领导和选择交给 Agent，获得清晰判断、可直接使用的产物，以及解决、调整或退出的行动方向。

[![Version](https://img.shields.io/badge/version-1.14.1-2563EB.svg?style=flat-square)](VERSION)
[![skills.sh](https://skills.sh/b/dennydkt/xbskill)](https://skills.sh/b/dennydkt/xbskill)
[![License](https://img.shields.io/badge/license-AGPL%20%2B%20CC%20BY--NC--SA-16A34A.svg?style=flat-square)](LICENSE)

支持 Claude Code、Codex、ZCode、Kimi-CLI，以及其他支持 Skills 的 Agent。

完整能力范围与本次增强见 [能力谱图](CAPABILITIES.md)。可选的工作记录精确检索需要 Python 3.10+；相关专科仍可对用户直接提供的材料执行文本核对。

## 安装

通过 Skills CLI 安装需要 Node.js 22.20 或更高版本。macOS / Linux 推荐安装全部 40 个 Skill：

```bash
DISABLE_TELEMETRY=1 npx -y skills add dennydkt/xbskill -g --all
```

Windows PowerShell：

```powershell
$env:DISABLE_TELEMETRY = "1"
npx -y skills add dennydkt/xbskill -g --all
```

该命令保持普通试用路径：无需注册、许可申请、授权码或额外运行服务。`DISABLE_TELEMETRY=1` 关闭上游 Skills CLI 遥测；去掉 `--all` 可以交互式选择安装。

套件校验、`xb-save`、`xb-memory`、`xb-knowledge` 与 `xb-role-knowledge` 需要 Python 3.10+。其余纯文本专科没有 Python 或 Node.js 依赖。

macOS / Linux 手动安装：

```bash
git clone https://github.com/dennydkt/xbskill.git
cp -r xbskill/skills/* ~/.agents/skills/
```

## 快速开始

**保存一次，换对话继续。** 使用 `xb-save` 保存对话与进度，并通过本体构建人物、事件、关系和决定的拟人化记忆系统。未来调用 xbskill 时，获得同一项目文件授权的 Agent 可以读取相关历史。换 Kimi、DeepSeek 等产品时，由你提供可读记忆文件继续使用；普通聊天仅恢复已经提供的材料。具体步骤与运行条件见 [记忆与跨产品衔接](skills/xbskill/references/memory-portability.md)。

**斜杠菜单选择 `xbskill 主入口｜从这里开始`。** 不知道该调用哪个子 Skill 时，问 xbskill。子功能按各自 `xb-*` 名称显示“子技能”或“设置”。 安装完成后调用 `$xbskill`，由你自行选择两项设置：

| 配置项 | 可选值（无默认值） |
|---|---|
| 调用强度 | 高：自动参与，直接用 XB 处理相关工作请求；中：先问再参与，同意后进入；低：点名才参与，平时继续原来的 AI 工作流 |
| 保存提示 | 高：每次回复提醒，用户发出保存指令后才写入；低：平时不提醒，想留存时主动说“保存对话” |

初始化每个档位用一句话解释行为，详细案例与适用偏好等你追问再展开。详细解释见 [配置指南](skills/xb-config/references/configuration-guide.md)。档位与回答质量无关，保存提醒也不代表自动保存。

以后通过 `$xb-config` 查看或修改。配置存于当前项目 `.xbskill/config.json`，独立于会话记忆。明确指定其他技能时，所有强度都让出控制权。

问法举例：

```text
$xbskill 同事栽赃我，帮我反击！
$xbskill 领导PUA我，我该怎么办
```

**子 Skill 说明书：** 想查看时回复“查看子 Skill 说明书”，也可以点名某个子 Skill。Agent 等用户明确反馈后才展示说明，默认不报完整菜单。

首次由 Agent 安装完成后或每次明确调用主入口时，展示主入口定位、问法、xb-save 本体记忆与衔接条件、说明书查看邀请；内部回流不重复。无交互安装器只复制文件，安装后的首次主入口调用完成介绍与必选配置。调用强度约束 Agent 的派发与执行；宿主是否预先加载技能描述须另行验证。

## 你会得到什么

| 真实处境 | 典型交付 |
| --- | --- |
| 问题说不清、反复失败 | 事实、冲突、候选解释和当前一步 |
| 领导话里有话、关系难判断 | 候选解码、辨别动作、回应与观察窗口 |
| 催办、拒绝、反馈、道歉 | 可直接发送的话术和强度变体 |
| 汇报没重点、请示没边界 | 决策信息包、风险和明确请求 |
| 拖不动、被加活、被甩锅 | 阻力归因、边界表达、留痕与升级路径 |
| 工作去留与长期选择 | 选项、代价、现实试验和退出阈值 |

系统服务用户的长期净收益与选择权：在可接受的身心与伦理成本下完成必要结果，同时增加理解、能力、边界和可选择空间。

## 子 Skill 说明书

完整套件包含 40 个 Skill。用户明确要求查看时，Agent 从 [使用手册](skills/xbskill/references/user-guide.md) 的专科速查定位，再读取对应 `SKILL.md` 说明输入、产物和边界。用户只发任务或选择配置时，直接推进该任务或配置。

配置入口是 `$xb-config`，主入口是 `$xbskill`；完整目录按需展开。

## 设计原则

- 单步路由：一次处理当前一个瓶颈，现实反馈回来后再决定下一步。
- 过程诚实：事实、推断和未知分账；缺来源、权限或证据时明确停下。
- 权限分离：建议、决定、授权、执行、复核和风险承担分别标记。
- 可证伪：重要判断带翻转条件、观察窗口和下一反馈点。
- 用户侧价值：产物、现实采用和用户净收益分别验收。

## 与 dbskill 的关系

xbskill 的部分工程机制经过对 [dontbesilent2025/dbskill](https://github.com/dontbesilent2025/dbskill) 的白盒研究。职场领域目标、语义、权限、风险、案例、产物和验收由 xbskill 独立重推导。详细追踪见 `skills/xbskill/references/dbs-reuse-case.md`，许可边界见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 开放与原创证明

- Python 脚本：AGPL-3.0-or-later。
- Skill 文本和其他内容：CC BY-NC-SA 4.0。
- 普通安装、本地试用、学习和非商业内部使用保持直接可用。
- 公开再分发需要署名、标明修改并遵守对应许可证。
- 修改版需显著标注非官方版本，避免来源混淆。

完整规则见 [LICENSE](LICENSE)、[ATTRIBUTION.md](ATTRIBUTION.md) 和 [TRADEMARKS.md](TRADEMARKS.md)。作者链、基线提交与核验方法见 [PROVENANCE.md](PROVENANCE.md)。

## 更新

macOS / Linux：

```bash
DISABLE_TELEMETRY=1 npx -y skills add dennydkt/xbskill -g --all
```

Windows PowerShell：

```powershell
$env:DISABLE_TELEMETRY = "1"
npx -y skills add dennydkt/xbskill -g --all
```

重新执行安装命令即可覆盖更新；套件内也可以使用 `$xb-update` 预览差异并先做备份。

## 参与和反馈

- Bug 与功能建议：使用 GitHub Issue 模板。
- 修改与贡献：[CONTRIBUTING.md](CONTRIBUTING.md)
- 安全问题：[SECURITY.md](SECURITY.md)
- 许可或署名问题：[LICENSE-ENFORCEMENT.md](LICENSE-ENFORCEMENT.md)
- 引用方式：[CITATION.cff](CITATION.cff)

### 多 Agent 记忆归集

`xb-sync` 发现同机多个项目的记忆根，预览后归集完整会话；差异会话进入冲突收件箱，跨项目背景进入带来源的待核对区。本体保留原根，可按根并列查询。各宿主保存与恢复仍须明确项目路径，跨机器传输由用户另行安排。
