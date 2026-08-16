---
name: xb-update
description: 安全检查和更新 xbskill 技能族：识别真源，预览差异，保留 LOCAL 补丁，备份后应用，验证失败则回滚。用于更新、升级、同步 xbskill。触发：$xb-update、更新 xbskill、检查新版本。
---

# xb-update：系统更新

直调时先读取 `../xbskill/references/contracts.md`、`../xbskill/references/resolution-standard.md` 与 `../xbskill/references/specialist-rewrite-method.md`；任何文件缺失时报告精确路径并停止，不得凭记忆补造。

## 硬边界

只更新 `xbskill` 与 `xb-*` 目录；不碰其他 Skill。默认只检查，不应用。来源必须是用户指定的本地目录、安装包或可信仓库工作树；没有来源就问，禁止猜 URL。任何 Git pull/push 前遵守工作区网络规则。

## 流程

1. 定位目标技能根和来源根，读取双方 `xbskill/VERSION`；缺失时停止并报路径。
2. 运行 `xbskill/scripts/suite_manager.py compare --source ... --target ...`，展示新增、修改、删除和本地独有文件。
3. 明确保护：所有 `LOCAL-*`、用户数据、项目 `memory/` 永不覆盖；冲突单列。
4. 用户确认精确版本和范围后才 `apply`；脚本先备份到用户指定目录或目标同级的时间戳备份。
5. 运行 `validate`、`xbskill/scripts/forward_test.py` 与 Skill Creator `quick_validate.py`；确认十案与专科深度回归的陌生回答者记录不是空白，并由独立评审检查 G/C/A/P/S/E/R/V 八门。失败自动恢复备份并响亮报告。
6. 重读关键路由、解决判定、专科重写方法、思想镜头、知识来源协议和版本；抽查新增专科内容不是只换名词的领域皮肤，任务专科有正确/有用/采用/净收益，人物组织专科有个人/关系/流程/制度四分。
7. 输出更新前后版本、改动、备份位置、验证证据、未验证现实结果和回滚命令。运行时知识库、人物/公司档案、决策/学习记录及 active lock 不属于套件清单，不得被更新器覆盖。

## 禁止

不静默联网、不在检查阶段修改、不覆盖本地补丁、不用“已是最新”代替可核对版本证据。
