# xb-sync 修复后独立复测冻结记录

判定：本轮独立复测通过，可进入发布。结论适用于下列冻结版本、完整套件安装布局及暂停参与目录写入者的运行前提；跨宿主实际采用仍待真实用户会话验证。

时间：2026-09-04。审计者为独立子代理，未改实现；新增标准库测试 `skills/xb-sync/scripts/test_sync.py`。未读取作者新增的测试或评分表，未读取或修改真实记忆。测试样本均由本套件在全新临时目录创建。

## 冻结版本

- xb_sync.py SHA256：`1C77730EEB88FFFFB5EA3BE50FF3AEF01D91C361B69F4926C4E1ABDF8FDFFB01`
- SKILL.md SHA256：`4B4D3AD81DC6D5B19449D3D7D43648D599123140339F9B58E3E1B88872A77B0B`
- test_sync.py SHA256：`8FBA3F142FE99D6C5683A5988E455478D55BD63AD602C42CBA697697FBAE838A`
- 陌生接收方使用全新临时目录中的完整套件同级安装副本。
- 原始输出与冻结清单保存在维护者审计档案中；公开接收方运行随包测试复验。

## 执行及结果

从完整套件同级布局启动 `python -B <xb-sync>/scripts/test_sync.py`。原安装与全新复制安装初始 10 项通过后，追加整体版本归档及查询包形状验证；最新冻结版隔离执行 12/12 通过、0 失败、0 跳过，用时 6.294 秒。原 8D82383A 开头的实现冻结已被本次版本替代。

| 测试方法 | 覆盖及观察 |
|---|---|
| test_discover_root_itself_and_explicit_apply | 直接扫描 memory/xbskill 命中自身；带 registry 的默认执行不写入，显式 apply 才登记。 |
| test_normal_multiroot_dry_copy_quarantine_and_canonical | 三根正常归集；dry-run 整体快照相同；两个卫星快照保持；会话复制，context/散文件进入 imports，项目配置及根 ontology 排除，来源收据存在，canonical 持久化。 |
| test_multiroot_same_session_path_preserves_both_sources | 两卫星同路径不同内容均保全；首份进入会话，另一份进入冲突区。 |
| test_whole_session_collision_prevents_mixed_provenance | 相同会话 ID 整组隔离，原 transcript 旁未混入卫星 ontology。 |
| test_conflict_source_name_collision_and_prior_versions_preserved | 来源长路径相同尾部产生独立冲突文件；后续更新保留第一版及更新版。 |
| test_updated_conflict_version_keeps_unchanged_session_files | 第二版冲突会话只修改 transcript，稳定的 ontology.json 仍与第二版 transcript 同目录成组保留，第一版完整存在。 |
| test_missing_root_rejected_by_sync_status_and_query | sync/status/query 全部 E_ROOT_MISSING 且非零退出。 |
| test_private_tool_paths_rejected | .codex/.claude/.kimi/.zcode/.kimi_openclaw/Doubao 临时模拟路径全部 E_PRIVATE_PATH，未产生写入。 |
| test_source_file_symlink_rejected | 文件 symlink 报 E_LINK，目标保持空白。 |
| test_destination_directory_link_rejected | Windows junction 报 E_LINK，外部临时目录保持空白。本机实际运行，未跳过。 |
| test_real_query_matches_and_failure_is_nonzero | 调用同级真实 memory_ontology.py，两个根同 ID 不同来源分别 matched；source_refs 与原文对应。破坏两根索引后整体 partial_failure、两个 E_INDEX_DRIFT，非零退出。 |
| test_query_rejects_incomplete_packet_shape | 专用合成子进程只返回 matched 状态而缺少包字段，父脚本识别 E_QUERY、partial_failure、非零退出。 |

## 剩余边界

覆盖范围内未发现发布阻断项。运行仍依赖用户暂停所有参与目录写入者；本轮未验证跨进程事务或对抗性的并发路径替换。其他操作系统若禁止链接创建，测试将明确标记 skip，应由发布方补充对应平台实测。跨宿主采用结果、各专科对 canonical 的实际选定继续按 SKILL.md 的收尾约定验证。

陌生安装检查采用 xb-sync、xb-memory、xbskill 同级副本，真实 query 成功，首次依赖缺失问题已由完整套件安装约定解决。测试脚本只用相对套件路径及临时合成资料，无个人目录或个人资料硬编码。

三律复核：独立代理与新安装副本完成外测；缺失根、私有路径、链接、查询失败均可见并失败退出；隔离临时样本，无额外用户确认循环。

## 跨平台测试入口修正

临时测试根使用 resolve() 取得实际路径，避免 macOS 系统临时目录别名被当成待同步链接。生产同步路径保护保持原样。随包测试脚本的当前摘要为 06178ce1b70242e37e6032702591f7739c65987e61c728f9f3cdf11ca523a2ab。完整套件发布测试覆盖此入口。

## 最终独立评审

2026-09-04，独立评审者对跨平台入口调整后的测试重新执行：12/12 通过，退出 0，耗时 6.649 秒。测试 SHA256 为 `06178ce1b70242e37e6032702591f7739c65987e61c728f9f3cdf11ca523a2ab`；实现与 SKILL 摘要沿用上方冻结值。此前测试摘要漂移导致 E 门暂记 1；核对单行 resolve() 调整及重跑证据后解除。

最终评分：G2 / C2 / A2 / P2 / S2 / E2 / R2 / V2。G/C 有明确目标、竞争解释与辨别动作；A/P/S 保留用户目录决定、组织权限、暂停写入前提和失败边界；E 使用源路径、哈希、日期与冻结测试；R 区分文件完成和现实采用；V 由陌生试用者与独立评审者分别复核。评分只适用于文档声明的本机、暂停写入和完整套件安装范围。
