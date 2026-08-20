# xbskill 跨平台运行时协议

## 适用范围

本协议管理 xbskill 在 Windows、macOS 与 Linux 上调用 Python 脚本、使用 Skills CLI、校验安装结果和报告依赖缺口的方式。脚本型专科与维护命令在执行前读取本文件；文件缺失时报告绝对路径并停止脚本步骤。

## 功能与依赖分层

| 使用场景 | Python 3.10+ | Node.js 22.20+ |
|---|---:|---:|
| 纯文本诊断、写作、沟通与决策专科 | 否 | 否 |
| 套件校验、`xb-save`、`xb-knowledge`、`xb-role-knowledge` | 是 | 否 |
| 通过 `npx skills` 安装或更新 | 否 | 是 |
| 手动复制完整 `skills/` 套件 | 校验时使用 | 否 |

所有随包 Python 脚本只使用标准库。缺少 Node.js 时可改用手动复制；缺少 Python 3.10+ 时，纯文本专科仍可使用，脚本型功能与安装校验必须停止。

## Python 3 解析

文档中的 `<PYTHON3>` 是经验证的 Python 3.10+ 启动命令占位符，禁止把它作为字面命令执行。

1. macOS / Linux：只接受 `python3`；先运行 `python3 --version`，版本低于 3.10 时报告 `E_RUNTIME_PYTHON_VERSION`。
2. Windows：优先 `py -3`，其次 `python`；候选命令必须返回 Python 3.10+。
3. 找不到合格解释器时报告 `E_RUNTIME_PYTHON_MISSING`，列出已检查的命令和当前平台。
4. 已解析命令在当前任务内保持一致。禁止把脚本改写成手工写入流程，也禁止切换到来源不明的解释器。

直接命令示例：

```bash
# macOS / Linux
python3 -B path/to/script.py
```

```powershell
# Windows；安装器提供 py 启动器时优先
py -3 -B path\to\script.py

# Windows；没有 py 且 python 已验证为 3.10+
python -B path\to\script.py
```

## Skills CLI 与遥测

xbskill 运行期不包含账号、遥测或回传。Skills CLI 是独立的上游安装器，其默认行为由上游版本决定。公开安装与更新命令必须显式设置 `DISABLE_TELEMETRY=1`；用户主动选择其他设置时，以用户决定为准。

```bash
# macOS / Linux
DISABLE_TELEMETRY=1 npx -y skills add dennydkt/xbskill -g --all
```

```powershell
# Windows PowerShell
$env:DISABLE_TELEMETRY = "1"
npx -y skills add dennydkt/xbskill -g --all
```

安装前运行 `node --version`。低于 22.20.0 时报告 `E_RUNTIME_NODE_VERSION`；命令缺失时报告 `E_RUNTIME_NODE_MISSING`，同时给出手动复制路径。

## 路径与文本格式

- 运行命令使用绝对路径；含空格、中文或 Unicode 组合字符时必须使用参数数组或正确引号。
- 禁止把 Windows 盘符、反斜杠或 PowerShell 语法写入 macOS/Linux 命令。
- 发布套件的文本文件统一使用 UTF-8 与 LF；发现 CRLF、孤立 CR 或 NUL 时停止发布。
- 路径比较通过 `pathlib.Path` 解析，目录边界检查保留 symlink/junction/reparse point 防护。

## 验证边界

`macos-latest` CI 可以证明命令、解释器、文件系统、安装器和脚本回归在 GitHub macOS runner 上通过。Codex、Claude Code 等桌面宿主的发现与交互仍需真实宿主实测；CI 结果不得替代该结论。
