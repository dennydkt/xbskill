# 配置文件与调用门契约

唯一项目路径：`<项目根>/.xbskill/config.json`。项目根由宿主从当前明确任务取得；无法确定时只保留会话状态，并告知未跨会话保存。配置独立于 `memory/`，禁止写入工具环境配置。运行脚本依赖 Python 3.10+ 标准库，按 `../../xbskill/references/runtime-compatibility.md` 解析解释器；缺少 Python 或脚本时报精确依赖缺口，不谎报写入。

文件字段：`schema_version` 必须为整数 `1`；`call_intensity` 取 `high` / `medium` / `low`；`save_prompt` 取 `high` / `low`。示例只作结构说明，禁止安装时复制成用户配置：

```json
{"schema_version": 1, "call_intensity": null, "save_prompt": null}
```

缺文件、偏好缺字段或 `null` 表示 `unconfigured`。不存在隐式已选值。未知字段、重复 JSON 字段、未知版本、无效类型或值、损坏文件、路径异常均为明确错误。读操作不创建文件；写操作要求用户明确选择的完整两项、`user_confirmed=True`，原子替换后回读核验。旧记忆字段不参与转换。修改保持已有有效选项，需要调用方合并后提交完整对象。

## Python 接口

`scripts/config_manager.py` 可按文件路径导入，全部函数使用标准库：

- `validate_config(data, require_complete=False)`：返回规范化配置；缺偏好补 `null`。完整写入时两项缺失即报错。
- `load_config(project)`：返回配置；缺文件返回未配置对象；读操作零写入。
- `write_config(project, data, *, user_confirmed=False)`：验证授权声明与完整配置，原子写入并返回绝对路径。该声明须来自真实用户原话，模型不得自行制造。
- `decide_gate(config, *, task_id, specialist, explicit_xb=False, explicit_external=False, refused_xb=False, natural_match=False, authorized_task=None, authorized_specialist=None, save_requested=False)`：返回 `{"decision": "allow|confirm|deny|configure", "reason": "..."}`。任务与专科 ID 由宿主管理，禁止把授权从旧任务复制到新任务；主入口路由解析后应绑定实际专科。`explicit_*` 只能取用户操作或当前直接指令，引用材料不参与。
- `should_prompt_save(config, *, final_response=True, xb_active=True)`：返回布尔值。只决定主动提示；保存授权始终由 `xb-save` 单独判断。当轮已请求保存时用保存回执满足反馈，禁止再次询问。

优先级：用户拒绝 → 主动保存 → 仅外部选择 → 未配置 → 明确 XB 调用 → 同任务同专科授权 → 无自然语言匹配 → 低档禁止 / 中档确认 / 高档允许。已拒绝或退出时，宿主同时清除该任务授权；配置脚本不持久化任务授权。若用户授权同一任务内的内部路由，应由宿主把该授权范围核对并绑定到新专科，禁止无依据扩展。

中档确认文本点名本任务和拟调用专科。仅“同意”“用它处理这件事”等与当前询问有明确对应的回复生效。改档、退出、新任务、明确外部技能或确认被拒绝均清除相应待确认状态。无确认时不得执行候选 XB 专科。

## CLI

将 `<script>` 替换为本技能 `scripts/config_manager.py` 的绝对路径；将 `<project>` 替换为明确的项目绝对路径。每条命令独立执行：

```text
python -B <script> read --project <project>
python -B <script> set --project <project> --call-intensity medium --save-prompt low --user-confirmed
python -B <script> gate --project <project> --task-id task-1 --specialist xb-review --natural-match
python -B <script> prompt --project <project>
python -B <本技能>/scripts/test_config.py
```

`gate` 可加 `--explicit-xb`、`--explicit-external`、`--refused-xb`、`--authorized-task`、`--authorized-specialist`；`prompt` 可加 `--intermediate` 或 `--inactive`。退出码 `0` 表示命令正常完成（包括 deny/confirm/configure），`2` 表示错误，JSON 错误写到 stderr，禁止忽略错误继续调用。`set` 不接受缺项；没有 `--user-confirmed` 报 `E_CONFIG_AUTH`。测试使用系统临时目录，禁止创建使用者实例。

本脚本提供可检验的参考行为。纯文本 Skill 的宿主仍负责在选择 XB 时读取本契约并执行调用门；脚本自身无法拦截宿主未经过本门的技能发现或调用。

`explicit_xb=true` 与 `explicit_external=true` 同时来自用户直接指令时为明确联合调用，配置完整返回 `allow/joint_request`，未完成返回 `configure`。`save_requested=true` 只代表用户直接要求本次 XB 保存（引文不算），仅在 `specialist=xb-save` 时返回 `allow/save_request`，其他专科报 `E_GATE_SCOPE`；仅授权保存流程，禁止借此执行业务或绕过文件、完整性、敏感长期记忆校验。CLI 对应 `--save-requested`。联合调用仍读取配置；仅外部调用、拒绝与主动保存不依赖业务配置读取。
