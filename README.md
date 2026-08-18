# xbskill

> 面向脑力工作者的「快点下班」工作生存与选择系统。把任务、沟通、卡点、领导、选择交给 Agent，获得清晰判断、可直接使用的产物，以及应该解决、调整还是退出的答案。

[![Version](https://img.shields.io/badge/version-1.5.0-2563EB.svg?style=flat-square)](VERSION)
[![skills.sh](https://skills.sh/b/dennydkt/xbskill)](https://skills.sh/b/dennydkt/xbskill)
[![License](https://img.shields.io/badge/license-CC%20BY--NC%204.0-16A34A.svg?style=flat-square)](LICENSE)

**支持：Claude Code、Codex、ZCode、Kimi-CLI，以及其他支持 Skills 的 Agent。**

## xbskill 解决什么问题

判断该用哪个工具这件事本身交给 `$xbskill`：把当下最想处理的一件工作直接发给它，它会判断你现在需要稳住、解卡、看懂、改变还是选择，选一个专科，交付可以直接使用的产物。

| 真实处境 | 你会得到 |
| --- | --- |
| 说不清哪里有问题，反复失败，怀疑问题在自己 | 五坐标扫描、竞争解释、当前一步 |
| 领导一句话里有话，听不懂又不敢问 | 候选解码、辨别动作、回应选项与验证窗口 |
| 想要一句话术：催进度、拒绝、反馈、道歉 | 可直接发送的话术与三种强度变体 |
| 汇报没重点、请示没边界、预期管不住 | 领导可直接决策的信息包 |
| 明知要做却拖不动，或被加活、被甩锅、被越权 | 阻力归因、边界表达、留痕与升级路径 |
| 材料很多、抽象评价、需要找原因 | 现象—冲突—约束—反馈的职场问题说明书 |
| 怀疑这份工作值不值得继续 | 选项、代价、现实试验与退出阈值 |

系统的北极星：帮助你在可接受的身心与伦理成本下完成必要结果，同时保留或增加理解、能力、边界和选择权。它不教你无条件忍受，也不把结构伤害包装成心态问题。

## 安装

### 推荐：支持 Skills 的 Agent（需要 Node.js 环境）

```bash
npx -y skills add dennydkt/xbskill -g --all
```

`-g` 安装到用户级技能目录（全部 Agent 共用），`--all` 安装全部 35 个 skill。也可以去掉 `--all` 交互式选择要装的专科。

### 手动安装

```bash
git clone https://github.com/dennydkt/xbskill.git
# 把 skills/ 下的全部目录复制到你的 Agent 技能目录，例如：
cp -r xbskill/skills/* ~/.agents/skills/
```

## 快速开始

安装完成后，在 Agent 中直接输入：

```text
$xbskill 我领导今天对我做的方案只说了句"还可以再优化"，没给任何方向，他到底什么意思？
```

```text
$xbskill 我每天加班到十点，产出却总被否定，我不知道问题出在我还是环境，要不要考虑换组。
```

已经知道需求时，可直接调用专科：

```text
$xb-talk 帮我写一条催同事交材料的话，不伤关系但要有截止时间
$xb-decode 解码一下：今天例会我被移出了下季度项目的汇报名单
$xb-upward 我要向领导申请两个人力支援下个月的活动，帮我打包汇报
$xb-decode 我想系统学怎么听懂话里有话，用《人民的名义》当教材
```

## 能力一览（35 skills）

| 类别 | 专科 | 一句话交付 |
| --- | --- | --- |
| 主入口 | `xbskill` | 接住问题、判断处境、路由专科、回流反馈 |
| 看懂 | `xb-triage` / `xb-analysis` / `xb-people` / `xb-decode` / `xb-company` / `xb-stakeholder` | 瓶颈定位 / 归因说明书 / 工作画像 / 潜台词解码 / 公司档案 / 多方利益地图 |
| 表达 | `xb-talk` / `xb-upward` / `xb-writing` / `xb-presentation` / `xb-report` / `xb-meeting` | 话术 / 汇报包 / 成稿 / PPT 与答辩 / 周报月报 / 会议推进 |
| 执行 | `xb-goal` / `xb-plan` / `xb-it` / `xb-data` / `xb-automation` / `xb-review` | 目标边界 / 工作包 / IT 修复 / 数据口径 / 自动化 / 验收 |
| 关系与边界 | `xb-conflict` / `xb-boundary` / `xb-action` / `xb-wellbeing` | 冲突方案 / 拒绝与升级 / 阻力归因 / 减压与求助边界 |
| 成长与选择 | `xb-decision` / `xb-career` / `xb-capability` / `xb-learning` / `xb-ai-native` / `xb-knowledge` | 取舍 / 去留 / 能力判级 / 技能训练 / AI 原生发展 / 知识库 |
| 深度支持 | `xb-role-knowledge` / `xb-save` / `xb-restore` / `xb-update` / `xb-builder` / `xb-audit` | 岗位知识单元 / 会话全文与自动分类 / 恢复 / 更新 / 孵化新专科 / 系统审计 |

## v1.5 本地会话记忆

每个真实任务进入收尾检查点时，xbskill 会明确询问是否保存本次会话。用户同意后，可见对话全文、会话摘要、分类账和滚动进度写入项目的 `memory/xbskill/`；人物、公司、目标和表达风格以带来源、置信度与推翻条件的方式增量更新。

保存按当前会话逐次授权。路径穿越、凭据模式、会话历史缺口或写入失败会响亮报错；保存动作不包含 Git、云同步和外发。

## 设计原则

- **单步路由**：一次只处理当前一个瓶颈，不预设长链流程。
- **过程诚实**：区分事实、推断、未知；关键假设、成本与边界显形；缺证据时响亮报错，不静默降级。
- **用户侧北极星**：默认优化你的净收益与选择权，不默认优化雇主产出。
- **可证伪**：重要结论带翻转条件与现实反馈点；解决、调整、退出三种方向都摆在桌面上。

完整模型见 `skills/xbskill/references/`（work-model、agency-model、resolution-standard 等）。

## 与 dbskill 的关系

xbskill 的工程机制（导航壳与专科架构、单步路由、竞争解释、八门验收、知识来源协议等）白盒重写自 [dontbesilent2025/dbskill](https://github.com/dontbesilent2025/dbskill)，遵循其 Keep / Re-derive / Reject 三分法：程序机制保留，领域语义（职场生存与选择）全部独立重推导，有害先验拒绝。重写追踪见 `skills/xbskill/references/dbs-reuse-case.md`。感谢 dbskill 开源这套高质量的方法论工程。

## 更新

```bash
npx -y skills add dennydkt/xbskill -g --all
```

重新执行安装命令即覆盖更新；已安装套件内也可用 `$xb-update` 做差异预览与备份更新。

## 许可证

[CC BY-NC 4.0](LICENSE)：以非商业目的自由使用、修改与分发；须署名并标明修改；禁止商业使用。具体以许可证全文为准。
