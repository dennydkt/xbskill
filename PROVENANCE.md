# 原创与版本证据

## 作者与项目

- 项目：xbskill
- 发起与核心作者：dennydkt
- 官方仓库：https://github.com/dennydkt/xbskill
- 当前源码来源：`skills/` 下的完整套件

## 历史坐标

| 事件 | 时间 | Git 坐标 |
| --- | --- | --- |
| workspace 首次加入 xbskill 完整套件 | 2026-08-09T20:59:48+08:00 | `dennydkt/workspace@67701f65cd39cd16683a1be6574f7369c04e8f3e` |
| 独立项目提取基线 | 2026-08-16T17:22:20+08:00 | `dennydkt/workspace@025488d68e7280e8693543b3193d978cb4db4e5e` |
| 独立源码仓建立 | 2026-08-16T22:53:54+08:00 | `3ad3db3aa43f0836ce9d4903a5c5b6500a60cea0` |

每次正式发布还应具有公开 commit、根级 `VERSION`、`skills/xbskill/manifest.json` 文件摘要和 GitHub Release。四者共同形成版本级证据。

本次与 dbskill 的精确长文本重合审计见 `RIGHTS-AUDIT.json`。该记录包含双方文本树摘要、比较阈值、上游 commit 和局限。

## 核验方法

```bash
git log --reverse --format=fuller
git show <commit>:skills/xbskill/SKILL.md
git show <commit>:skills/xbskill/manifest.json
git diff <older-commit> <newer-commit> -- skills/
```

Git 提交时间可以被本地修改。判断原创与版本先后时，应同时核对公开远端出现时间、提交对象、Release、文件哈希、来源追踪和必要的第三方时间存证。

## 权利边界

xbskill 对自身具体表达、代码、案例、编排和测试主张相应版权。抽象理念、通用方法和第三方材料的权利边界按适用法律与各自许可证判断。dbskill 影响和其他来源见 `NOTICE.md`、`THIRD_PARTY_NOTICES.md` 及 `skills/xbskill/references/dbs-reuse-case.md`。
