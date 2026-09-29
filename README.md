# NX 12 CLI + MCP 建模验证

基于 NXOpen C# Journal 的一个小型建模工具。它提供命令行和本地 MCP stdio 两种入口，支持创建圆柱、分步开通孔、读取实体与特征数量、保存原生 `.prt`，再由独立 NX 进程重开检查。

这是一个**受限的教学与能力验证项目**：目前只支持参数化圆柱和通孔；常驻会话运行于无界面 NX 进程，尚未连接用户当前可见的 NX 窗口，也不支持任意自然语言零件设计。

## 已完成的验证

- 批处理：外径 40 mm、孔径 16 mm、高 60 mm，保存后独立重开得到 1 个实体、3 个特征，体积 63334.5079 mm³，与解析式误差约 1.15×10⁻¹⁶。
- CLI 常驻会话：多个独立命令返回同一 NX 进程 ID；开孔后体积 90477.8684 → 74769.9052 mm³，保存并独立重开通过。
- MCP 常驻会话：`initialize` 和连续 `tools/call` 依次执行 `start/status/create/bore/info/save/stop`；相同 NX 进程 ID，特征数 1 → 3、体积 78539.8163 → 68361.0561 mm³，独立重开通过。
- 脱敏的实验摘要和原生文件 SHA-256 见 [evidence/verified-runs.json](evidence/verified-runs.json)。本机原始日志与 `.prt` 保留在作者本地；原生文件可能带有设备元数据，因此未上传。

## 运行环境

Windows、NX 12（含 `NXBIN/run_journal.exe` 与 NXOpen）、Python 3、.NET Framework 4.x C# 编译器。项目没有随仓库分发 Siemens 程序或授权文件。

默认 NX 12 安装位置是 `E:\Program Files\Siemens\NX 12.0`。其他位置可设置环境变量 `NX12_ROOT`。Windows 上先执行 `build_bridge.cmd` 编译本机桥接客户端；它仅绑定 `127.0.0.1`，每次会话使用随机令牌。

```powershell
git clone https://github.com/Voss0919/nx12-cli-mcp.git
cd nx12-cli-mcp
$env:NX12_ROOT = 'E:\Program Files\Siemens\NX 12.0'
.\build_bridge.cmd
.\nxcli.cmd doctor
.\nxcli.cmd build-tube --outer-d 40 --bore-d 16 --height 60
```

分步操作同一个无界面 NX 进程，每行可以在新的命令行进程运行：

```powershell
.\nxcli.cmd live start
.\nxcli.cmd live status
.\nxcli.cmd live create --outer-d 46 --height 70
.\nxcli.cmd live bore --bore-d 18
.\nxcli.cmd live info
.\nxcli.cmd live save
.\nxcli.cmd live stop
```

要重做 MCP 验证，运行 `py -3 .\verify_mcp_live.py`。MCP 客户端也可将 `py -3 nxcli.py mcp` 配置为本地 stdio 服务；公开工具为 `nx_doctor`、`nx_create_tube`、`nx_live_session`。

输出统一放在被 `.gitignore` 排除的 `artifacts/` 中，不覆盖现有零件。运行时请先通过 `doctor` 核对 NX 路径与桥接客户端状态。

## 代码入口

- [nxcli.py](nxcli.py)：CLI 与 MCP 的共同入口、输入校验和证据记录。
- [journals/CreateTube.cs](journals/CreateTube.cs)：创建圆柱、通孔并保存。
- [journals/LivePipe.cs](journals/LivePipe.cs)：同一 NX 进程中接收有限命令并更新模型。
- [journals/VerifyTube.cs](journals/VerifyTube.cs)：独立重开并读取实体、特征、体积。
- [pipe_client.cs](pipe_client.cs)：本机桥接客户端源码。

体积核对公式：`π × (外径² − 孔径²) × 高度 / 4`。可复现的关键是相同进程 ID 下特征和体积发生变化，随后由另一个 NX 进程重新打开保存的 `.prt`。
