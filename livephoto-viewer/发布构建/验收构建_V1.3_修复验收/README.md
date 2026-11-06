# V1.3 播放故障与核心相册缺陷修复 · 独立验收目录

> 本目录是**本轮修复的独立交付区**：不覆盖 `dist\实况照片备份查看器.exe`（V1.2 正式版），
> 不覆盖 `发布构建\验收构建_V1.3\`（V1.3 既有构建产物），不改动 `历史备份\` 任何基线。

## 一、目录结构

| 路径 | 内容 |
|---|---|
| `spec\` | 独立 PyInstaller spec（GUI + CLI），输出名带「修复验收」标识 |
| `exe\` | 本轮新构建的 EXE（不替换正式版） |
| `build_work_gui\` / `build_work_cli\` | PyInstaller 中间产物 |
| `logs\` | 构建日志 |
| `诊断\` | 根因定位探针（真实 WebView2 实测，含 A/B 对照） |
| `测试\` | 验收脚本（真实应用 + 真实 WebView2 + 真实 `<video>` 解码） |
| `证据\` | 验收结果 JSON、界面截图 |
| `实况照片备份查看器_V1.3_播放故障与核心相册缺陷修复验收报告V1.0.md` | 交付报告 |

## 二、根因诊断探针（已执行，结论已固化）

```powershell
cd 诊断
..\..\..\.venv-build\Scripts\python.exe probe_playback.py       # 基线：file:// 视频永不起播
..\..\..\.venv-build\Scripts\python.exe probe_fix_ab.py          # A/B：权限参数 / 虚拟主机名映射
..\..\..\.venv-build\Scripts\python.exe probe_media_stack.py     # 分层：图片/fetch 正常，媒体管线挂起
..\..\..\.venv-build\Scripts\python.exe probe_edge_headless.py   # 对照：独立 Edge 同一视频可播
..\..\..\.venv-build\Scripts\python.exe probe_env_ab.py          # 隔离：UDD 编码 / GPU / autoplay 参数
..\..\..\.venv-build\Scripts\python.exe probe_visibility.py      # 定位：Controller.IsVisible=false
```

结论：**根因是 WebView2 控制器 `IsVisible=false`（宿主窗口隐藏创建），Chromium 把页面判为
后台页并挂起媒体子系统**。详见 `诊断/probe_visibility_results.json` 与报告 §二。

## 三、验收测试（需在真实桌面会话执行）

前置：本机需有 Edge WebView2 Runtime；`.venv-build` 内已装 pythonnet / pywebview / Pillow /
imageio-ffmpeg。测试会真实弹窗并操作真实视频解码，**请勿在锁屏/无人值守状态下运行**。

```powershell
cd 测试
..\..\..\.venv-build\Scripts\python.exe acceptance_v13_fix.py
```

- 结果：`证据\acceptance_results.json`（逐项 env/样本/步骤/预期/实际/PASS-FAIL/证据）
- 截图：`证据\T-00…T-11_*.png`
- 退出码为 0 只代表脚本跑完，**判定以 JSON 内每项 status 为准**。

单项冒烟（只验证「点击能起播」）：

```powershell
..\..\..\.venv-build\Scripts\python.exe smoke_playback.py
```

## 四、真实样本缺口（必须如实对待）

| 缺口 | 影响 | 处置 |
|---|---|---|
| 无真实 iPhone **HEVC `.mov`** 样本（全项目 .mov/.hevc 计数为 0） | 无法给出 HEVC 直解（T1）兼容性结论 | 本轮**不宣称**任何 HEVC 兼容性；H.264/HEVC 走 T2 转码兜底的结论留待真实样本到位后补测 |
| 批量语料为项目自带真实 iPhone 14 导出样本（`测试样本\IMG_0346.HEIC/.mp4`，H.264 Main 960x1280 2.008s）的**硬链接副本** | 可验证数量/分页/配对/路径，不可代表真实 iPhone 全量目录结构 | 已在报告「样本」栏逐项标注 |
| 依赖系统 Edge WebView2 Runtime（本机 153.0.4234.48） | 无该运行时的机器走 A8 降级页 | 未安装运行时的机器无法完成真实播放验收 |

## 五、最终验收（2026-11-06）

- 报告：`实况照片备份查看器_V1.3_修复版最终验收报告V1.0.md`
- 结论：**验收通过**（2026-11-06 产品负责人确认；人工 EXE 播放 PASS；保护项 PASS）
- 结论变更（不篡改历史）：初次「验收失败」→ 人工确认后「有条件通过」→ **「验收通过」**（详见报告 §9.0）
- 失败主因指向验收脚本缺陷（物理点击未计标题栏偏移、`index_of` 失败静默回退到第 0 张损坏样本、无超时落盘），**不是已证实的产品功能缺陷**
- 独立实测：同一页面 4 种路径（含 861 字符 URL）全部 `playing / readyState=4`；`诊断\probe_path_factor_results.json`
- 保护核对：12 个零改动受保护函数 AST 逐字一致；`build_html` 仅删 5 行悬停逻辑；正式版与 V1.2 基线哈希未变（`证据\protected_check_results.json`）
- 原修复报告 §七 的「11 个」为**数字笔误**，实为 **12 个**（以本目录最终验收报告 §七 为准）

### EXE 人工播放辅助工具

```powershell
cd 测试
..\..\..\.venv-build\Scripts\python.exe exe_manual_play.py
```

脚本会用真实鼠标操作 EXE，并用 `PrintWindow` 连续抓帧、以帧差判定"画面是否真的在动"。
**已知限制**：Tk 原生目录选择对话框无法在无人值守下可靠操作，需人工在该对话框中选定
`测试\work_manual\源目录 中文 空格`，其余步骤自动完成并留证（`证据\exe_manual_play_results.json`、`EXE-M*.png`）。

## 六、测试工具修订（2026-11-06）

- 报告：`实况照片备份查看器_V1.3_自动化验收工具最终修订报告V1.0.md`
- 执行说明：`测试\README_验收测试说明.md`
- 脚本：`测试\acceptance_v13_fix.py`（修订后 SHA256 `348336E5EFA2C49C8B98271D8817791D7E47B44C9427853309C9217335A870BD`）
- 新增状态体系：`PASS / FAIL / BLOCKED / UNVERIFIED / NOT_RUN`；
  **工具/环境缺陷记 `BLOCKED`，既不算产品失败，也不算通过**
- 12 项计划强制齐备：中途异常时未执行项自动补 `NOT_RUN`
- 历史 T-01/T-02 FAIL 原样保留：`测试\acceptance_run*.txt` + `证据\history\` 副本 + 结果 JSON 的 `history_runs`
- 本轮**未执行**测试，修订效果待运行验证

**一条命令**：

```powershell
cd "D:\SEO\发挥余热\实况照片备份查看器\发布构建\验收构建_V1.3_修复验收\测试"; & "..\..\..\.venv-build\Scripts\python.exe" acceptance_v13_fix.py; Write-Host "ExitCode=$LASTEXITCODE"
```

**结果**：`证据\acceptance_results.json`（另有 `证据\acceptance_run_<时间戳>.log`、`证据\faulthandler.log`）
