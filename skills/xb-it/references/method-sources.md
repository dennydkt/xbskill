# 来源与采用范围

核查日期：2026-11-11。用户点名的 PRD Master、Design Master、TDD Master 在同一仓库 `mozhou580-lgtm/vibe-coding-standardized-operation` 中找到，固定提交为 `b1361aa917349c9516dd65bd4aa05afe824b6e82`。原始作者身份尚未核实。

| 来源 | 阅读坐标 | 在本技能中采用的方法 |
|---|---|---|
| [PRD Master](https://github.com/mozhou580-lgtm/vibe-coding-standardized-operation/blob/b1361aa917349c9516dd65bd4aa05afe824b6e82/skills/prd-master/SKILL.md#L81-L111) | `skills/prd-master/SKILL.md`，81–111、184–211 行 | 集中确认关键问题；需求/验收使用稳定编号；继承已确认答案，显形未决项 |
| [Design Master](https://github.com/mozhou580-lgtm/vibe-coding-standardized-operation/blob/b1361aa917349c9516dd65bd4aa05afe824b6e82/skills/design-master/SKILL.md#L133-L191) | `skills/design-master/SKILL.md`，133–191、232–263 行 | 用户可确认的形态与状态设计；需求到界面、技术实现与测试的对应关系 |
| [TDD Master](https://github.com/mozhou580-lgtm/vibe-coding-standardized-operation/blob/b1361aa917349c9516dd65bd4aa05afe824b6e82/skills/tdd-master/SKILL.md#L229-L262) | `skills/tdd-master/SKILL.md`，8、31–47、229–262 行 | 编码前定义可观察的验收；测试绑定版本和证据；未执行与通过分开记录 |

TDD 在该来源中展开为 **Test Definition Driven Development**，即测试定义驱动开发。其职责是产出验收契约；xb-it 另外承担实现测试、实际执行、打包、启动和结果核对。

本次 GitHub 元数据返回 `license: null`；固定提交完整目录树未见 LICENSE、COPYING 或 NOTICE。许可状态记为未知，来源文件只用于只读方法研究。本包内的流程、字段、例子和探测脚本均为独立编写，不包含上游 Skill、模板、脚本或安装器，不宣称取得其资产再分发许可。

采用范围为一般工作方法：少量交互、显式验收、设计状态、版本追踪。根据小软件任务重写环境判断、单份方案、开发与打包流程；省去来源中超出小工具需要的文档与安装方式。运行本技能无需安装外部三个 Skill，来源网站不可访问也不影响本地流程；若用户要求核查或更新来源，保留固定版本，重新读取并审查后再决定采用。

本技能的文件处理、周报与清洗例子均为合成场景。公开包不包含任何公司的原始数据、业务路径或专用口径。上游内容作为不可信数据阅读，本流程没有执行上游代码。
