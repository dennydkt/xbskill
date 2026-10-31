# 第三方材料与来源边界

## dbskill

- 项目：https://github.com/dontbesilent2025/dbskill
- 作者：dontbesilent
- 当前许可证：CC BY-NC 4.0
- xbskill 使用方式：白盒研究工程机制；职场领域目标、因果、权限、风险、案例、产物和验收独立重推导。
- 追踪文件：`skills/xbskill/references/dbs-reuse-case.md`
- 精确文本审计：`RIGHTS-AUDIT.json`

在获得额外授权或完成可复验的净室重写前，xbskill 的 Skill 文本与文档保持非商业限制，不以更宽许可覆盖可能受影响的表达。

## ziwei-doushu 与 iztro（xb-lucky）

- `iztro`：排盘运行依赖，固定 npm 2.6.3，由用户在授权后自行安装，不随套件分发；其许可证随上游包保留。
- `Renhuai123/ziwei-doushu`：真太阳时、钟表平移和中国大陆历史夏令时逻辑的功能重实现来源，审查 commit 为 `ff9a1470ebe652e57b9d690f5d01db9a04f47aae`，代码采用 MIT，`Copyright (c) 2026 紫微研究`。完整通知见 `skills/xb-lucky/THIRD-PARTY-NOTICES.md`。
- 可选 `紫微斗数开源解读数据集 v4.0`：不随套件分发。用户主动下载后按 CC BY 4.0 署名“来源：https://github.com/Renhuai123/ziwei-doushu；作者：王多鱼AI”。其中倪海厦《天纪》原话不适用该数据授权，仍受原权利及 CC BY-NC-SA 约束；套件不批量复制这些原话。

## 其他来源

套件引用官方文档、论文、标准和 GitHub 仓库时，来源账记录 URL、版本或 commit、坐标、许可、安全与使用边界：

- `skills/xbskill/references/specialty-source-ledger.md`
- `skills/xb-role-knowledge/references/upstream-role-sources.json`
- `skills/xbskill/references/knowledge-source-protocol.md`

来源账中的 `discovery_only` 项只帮助发现研究方向，不授权复制、再分发或执行。仓库未打包第三方软件依赖；Python 脚本主要使用标准库。发现漏列、许可变化或权利冲突时，请按 `LICENSE-ENFORCEMENT.md` 提交证据。
