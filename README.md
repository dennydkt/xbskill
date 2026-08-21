# xbskill

> 面向脑力工作者的“快点下班”工作生存与选择系统。把任务、沟通、卡点、领导和选择交给 Agent，获得清晰判断、可直接使用的产物，以及解决、调整或退出的行动方向。

[![Version](https://img.shields.io/badge/version-1.7.5-2563EB.svg?style=flat-square)](VERSION)
[![skills.sh](https://skills.sh/b/dennydkt/xbskill)](https://skills.sh/b/dennydkt/xbskill)
[![License](https://img.shields.io/badge/license-AGPL%20%2B%20CC%20BY--NC--SA-16A34A.svg?style=flat-square)](LICENSE)

支持 Claude Code、Codex、ZCode、Kimi-CLI，以及其他支持 Skills 的 Agent。

## 安装

通过 Skills CLI 安装需要 Node.js 22.20 或更高版本。macOS / Linux 推荐安装全部 35 个 Skill：

```bash
DISABLE_TELEMETRY=1 npx -y skills add dennydkt/xbskill -g --all
```

Windows PowerShell：

```powershell
$env:DISABLE_TELEMETRY = "1"
npx -y skills add dennydkt/xbskill -g --all
```

该命令保持普通试用路径：无需注册、许可申请、授权码或额外运行服务。`DISABLE_TELEMETRY=1` 关闭上游 Skills CLI 遥测；去掉 `--all` 可以交互式选择安装。

套件校验、`xb-save`、`xb-knowledge` 与 `xb-role-knowledge` 需要 Python 3.10+。其余纯文本专科没有 Python 或 Node.js 依赖。

macOS / Linux 手动安装：

```bash
git clone https://github.com/dennydkt/xbskill.git
cp -r xbskill/skills/* ~/.agents/skills/
```

## 快速开始

```text
$xbskill 我每天加班到十点，产出却总被否定。我想知道问题在方法、协作还是环境，也想判断要不要换组。
```

已经知道需求时，可以直接调用专科：

```text
$xb-talk 帮我写一条催同事交材料的话，保留关系并明确截止时间
$xb-data 帮我核对这份表的口径、异常和结论
$xb-upward 把我的人力申请整理成领导可直接决策的信息包
$xb-career 比较留下、换组和外部机会，给我现实试验和翻转条件
```

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

## 能力一览

完整套件包含 35 个 Skill：

- 主入口：`xbskill`
- 看懂：`xb-triage` `xb-analysis` `xb-people` `xb-decode` `xb-company` `xb-stakeholder`
- 表达：`xb-talk` `xb-upward` `xb-writing` `xb-presentation` `xb-report` `xb-meeting`
- 执行：`xb-goal` `xb-plan` `xb-it` `xb-data` `xb-automation` `xb-review`
- 关系与边界：`xb-conflict` `xb-boundary` `xb-action` `xb-wellbeing`
- 成长与选择：`xb-decision` `xb-career` `xb-capability` `xb-learning` `xb-ai-native` `xb-knowledge`
- 深度支持：`xb-role-knowledge` `xb-save` `xb-restore` `xb-update` `xb-builder` `xb-audit`

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
