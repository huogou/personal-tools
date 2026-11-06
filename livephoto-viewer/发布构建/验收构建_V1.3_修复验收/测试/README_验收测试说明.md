# V1.3 自动化验收 · 执行说明（修订版）

> 本目录只存放**测试工具**。测试工具不修改产品源码、不修改 EXE、不修改 `dist`、
> 不修改 `测试样本` 与任何原始照片/视频。

## 一、前置条件

| 项 | 要求 |
|---|---|
| 系统 | Windows 10/11 真实桌面会话（**不能锁屏 / 不能无人值守**，需要可见窗口） |
| 运行时 | Edge WebView2 Runtime 已安装 |
| Python | 项目 `.venv-build`（已含 pythonnet / pywebview / Pillow / imageio-ffmpeg） |
| 屏幕 | 建议 100% 缩放；测试会移动鼠标并点击窗口 |

## 二、一条命令

```powershell
cd "D:\SEO\发挥余热\实况照片备份查看器\发布构建\验收构建_V1.3_修复验收\测试"; & "..\..\..\.venv-build\Scripts\python.exe" acceptance_v13_fix.py; Write-Host "ExitCode=$LASTEXITCODE"
```

> 说明：脚本自己写运行日志，不需要 `Tee-Object`。
> **退出码 0 不代表全部通过**，必须以结果 JSON 内每项 `status` 为准。

## 三、输出文件

| 文件 | 说明 |
|---|---|
| `..\证据\acceptance_results.json` | **主结果**：12 项完整列表 + 统计 + 自检 + 历史运行引用 |
| `..\证据\acceptance_run_<时间戳>.log` | 本次运行完整日志（实时写入，异常退出也保留） |
| `..\证据\faulthandler.log` | native 崩溃栈（若为空表示未发生 native 崩溃） |
| `..\证据\T-*.png` | 各测试项截图证据 |

## 四、状态语义（严格执行）

| 状态 | 含义 | 是否算产品通过 | 是否算产品失败 |
|---|---|---|---|
| `PASS` | 实测满足预期 | 是 | — |
| `FAIL` | 实测不满足预期，且可归因于被测产品 | — | 是 |
| `BLOCKED` | 工具/环境缺陷导致无法得出有效结论（如通信超时、卡片未定位、超时中止） | **否** | **否** |
| `UNVERIFIED` | 已执行但无法判定 | 否 | 否 |
| `NOT_RUN` | 未执行（脚本中途异常时由落盘逻辑自动补齐） | 否 | 否 |

> `BLOCKED` 会带 `blocked_by` 字段：`tool_or_env` / `tool_exception` / `timeout`。

## 五、T-00～T-11 测试项与执行方式

| 编号 | 验证点 | 操作方式 | 判定依据 | 证据 |
|---|---|---|---|---|
| T-00 | WebView2 就绪、网格渲染、样本排序稳定 | 切相册页 → `set_source` → 等 A4 | `state=A4` ∧ `visibility=visible` ∧ 首屏卡片>0 ∧ **第 0 张不是 `Z_异常/broken`** | `T-00_就绪.png` |
| T-01 | 单张播放（真实解码） | **真实鼠标点击**卡片中心（视口坐标 + `ClientToScreen`）→ 未起播则补一次 DOM click | 曾进入 `playing` ∧ `readyState≥2` ∧ 无 media error；通信探针 `1+1` 失败则记 `BLOCKED` | `T-01_播放中.png` |
| T-02 | 停止 / 重播 / 播完回静止 | 播放中点击 → 再点击 → 等 `ended` | 停止后 `playing=0/state=idle/src=""`；重播 `currentTime<1s`；播完自动回 `idle` 且释放 `src` | `T-02_重播后.png` |
| T-03 | 连续切换多张 | 按 **key** 定位 IMG_A002/3/4，依次点击 | 每次恰好 1 张 `playing`，旧卡 `src` 全部释放，新卡 `readyState≥2`；定位失败记 `BLOCKED` | `T-03_切换.png` |
| T-04 | 连续点击 / 单实例 | 按 key 定位前 3 张，同卡连点 5 次 + 立刻点另两张 | 任意时刻 `playing≤1` 且 `loading≤1` | `T-04_连点.png` |
| T-05 | 切目录 / 切回备份页释放播放器 | 播放中切分类 → 切回全部 → 播放 → 切回备份页 | 切换后 `playing=0` 且所有 `<video>` 的 `src` 已移除 | `T-05_切换后.png` |
| T-06 | 损坏视频 / 缺失配对 / 未识别 / 有效性分层 | 先滚动加载全部 → 按 key 点 `Z_异常/broken` → 查 `get_photo_detail` | `issues={complete:627, photo_only:1, video_only:1, unknown:1}`；损坏卡片 `failed` 且有明确提示；`playable=None` 且 `probe.decodable=False` | `T-06_异常提示.png` |
| T-07 | 跨目录同名配对 | 扫描后检查 `api.items` 中 `IMG_SAME` | 2 条独立 item、key 不同、每条 photo/video 同目录、两目录不同 | 无截图（数据级） |
| T-08 | >500 张完整加载 | 反复滚动触发分页，直到 `offset==total` | `total>500` ∧ 最终 DOM 卡片数 == total | `T-08_完整加载.png` |
| T-09 | 中文 / 空格 / 长路径 | 按 key 点长路径卡片 | 路径含中文与空格、长度≥180、条目存在且真实起播；定位失败记 `BLOCKED` | `T-09_长路径播放.png` |
| T-10 | 原始文件与正式版保护 | 前后逐文件 `size+SHA256`；正式 EXE 哈希；12 个受保护函数 AST | 源目录零改动；`dist`/V1.2/基线哈希不变；12 函数逐字一致 | 数据级 |
| T-11 | 视频缺失（故障注入） | 测试脚本主动删除 `IMG_A002.mp4` → 点击该卡片 | `failed` 态 + 明确提示 + 不显示虚假播放状态 | `T-11_视频缺失.png` |

> T-11 的删除动作发生在 T-10 保护比对**之后**，并在日志中显式标注为测试注入。

## 六、假绿防护（脚本内置）

| 防护 | 做法 |
|---|---|
| 增量落盘 | 每记录一项即写 JSON；进程异常退出时 `atexit` 再写一次 |
| 12 项齐全 | 未执行项自动补 `NOT_RUN`，不会"消失" |
| 禁止静默改判 | 同一项状态发生变化会写入 `record_overrides` |
| 样本保护 | 测试前后对 `测试样本/IMG_0346.*` 计算 SHA256，写入 `self_check.sample_unchanged` |
| 无跳过机制 | 脚本不存在 SKIP；失败项必须落成 FAIL/BLOCKED |
| 排序稳定 | 损坏样本放 `Z_异常` 且 mtime 调旧；T-00 断言第 0 张不是它 |
| 通信探针 | T-01/T-02 用 `1+1` 探针区分"产品不播"与"页面无响应" |

## 七、已知限制

1. 测试会真实弹窗并移动鼠标，**必须在你能看到屏幕时运行**；
2. 若窗口被遮挡/最小化，WebView2 可能被系统节流，通信探针会失败并记 `BLOCKED`（不算产品失败）；
3. 无真实 iPhone HEVC `.mov` 样本，T-01/T-02 只用 H.264 样本，**不构成 HEVC 兼容性结论**；
4. 脚本不修改产品，也不修复产品缺陷；`FAIL` 需另立修复任务。
