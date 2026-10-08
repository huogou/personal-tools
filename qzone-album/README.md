# QQ 空间相册下载器 · 阶段一：接口抓包验证

目标：在写任何下载代码之前，先**用真实抓包确认**相册列表、照片列表、原图与视频原画直链的现状。
不猜接口、不写死字段——抓到什么就按什么实现。

## 已锁定的产品要求（阶段二必须遵守）

| 要求 | 约束 |
|---|---|
| 原图 | 图片取原图，视频取原画；拿不到原图必须**显式标记降级**，不得静默用缩略图顶替 |
| 图片 + 视频 | 两者都要下载 |
| 目录结构 | `<下载根>/<QQ号>/<相册名>/`，**同一相册的照片与视频放在同一个文件夹**，不做 `photos/`、`videos/` 二次拆分 |
| 相册名 | 与空间里的相册名一致，不得重命名、不得加序号前缀（仅重名时追加后缀） |

## 窗口程序（双击运行，推荐）

不想碰命令行，直接双击 `dist/QQ相册抓包.exe`：

1. 在 QQ 号框填入你的 QQ 号；
2. 点「开始抓包」→ 浏览器自动弹出；
3. 按界面提示点「继续」：① 登录 → ② 点开相册翻页 → ③ 有视频就播 2~3 秒；
4. 点「分析抓包结果」看接口结构，点「打开抓包文件夹」定位产物。

> 该 exe 是「瘦启动器」，双击后调用已验证的 venv 解释器运行 `scripts/gui.py`，
> 因此必须保持目录结构：exe 与 `scripts/` 同级，`<Python 环境路径>`
> 解释器存在且装好依赖。不要单独把 exe 拿走。
>
> 想重新构建：`python -m pyinstaller --onefile --noconsole --name "QQ相册抓包" qzone_launcher.py`
> （源码在 `scripts/gui.py`）。
>
> 复用已登录 Edge：勾选「复用已登录 Edge」，前提是 Edge 已用
> `--remote-debugging-port=9222 --remote-allow-origins=*` 启动（见下方方式 A）。
> 不勾选则用自带 Chromium，首次扫码，之后登录态保留在 `profile/`。

## 环境准备

```bash
# 建议用独立虚拟环境
python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
playwright install chromium     # 或改用 --browser msedge 复用本机 Edge
```

已就绪的环境（本机已验证）：

```
<Python 环境路径>Scripts\python.exe
playwright + chromium 已安装，qzone.qq.com 访问正常
```

## 方式 A：接管已登录的 Edge（推荐，免扫码）

> 注意：`--browser msedge` **不会**复用你现有 Edge 的登录态。Playwright 必须用独立的
> `user_data_dir`，会开一个全新 profile，照样要扫码。要真正复用登录态，只能走 CDP 接管。

1. **完全退出 Edge**（必须，否则调试端口不生效）。
2. 在 PowerShell 或 Git Bash 执行：

```bash
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222 --remote-allow-origins=* https://qzone.qq.com/
```

3. 确认 Edge 里已是你的 QQ 空间后，另开一个终端执行：

```bash
python scripts/capture_login.py --qq 你的QQ号 --connect-cdp
```

脚本通过 CDP 接管该浏览器，直接复用登录态，跳过扫码；抓完只断开连接，不关闭你的 Edge。


## 关于「播放视频」（只影响抓包，不影响下载）

抓包阶段让你**播放一次视频**，目的不是"播了才能下"，而是诱导浏览器发出换取视频真实地址的
请求，从而把那个接口记录下来。下载阶段一定是通过程序直接调接口拿地址，**不需要播放**。

抓包结果会决定属于哪种情形：

| 情形 | 表现 | 下载阶段怎么做 |
|---|---|---|
| A | 照片列表接口已直接返回视频原画直链 | 直接下，最省事 |
| B | 列表只给 `vid`，需另调接口换播放地址 | 程序按 `vid` 调该接口拿地址 |
| C | 直链带时效签名（`vkey` 等） | 现取现用，抓取与下载间隔不能太长 |

在拿到抓包数据前，我无法判定是哪种——这正是做这一步的原因。

## 步骤一：抓包

### 方式 B：独立 Chromium（需要扫码一次）

```bash
python scripts/capture_login.py --qq 你的QQ号
```

脚本会打开浏览器并停在 `qzone.qq.com`，**请你自己扫码或手动登录**（脚本不会提交账号密码，也不会绕过验证码）。
之后按提示依次：

1. 登录成功 → 回车（脚本自动打开相册页并滚动，抓「相册列表」接口）
2. 点开任意一个相册、翻页把照片加载完 → 回车（抓「照片列表 + 原图直链」）
3. **如果有视频：点开视频并播放 2~3 秒** → 回车（抓「视频原画直链」接口，这一步很关键）

产物在 `captures/<时间戳>/`：

```
index.jsonl     每条请求/响应的元信息
raw/            原始响应体（二进制原样，不改写）
session.json    Playwright 登录态（阶段二直接复用，不用重复扫码）
cookies.txt     打码后的 cookie 清单
```

## 步骤二：离线分析

```bash
python scripts/analyze_capture.py                    # 默认分析最新一次
python scripts/analyze_capture.py --dir 20260910_120000
```

输出五部分：

1. 请求分类统计（哪几条是相册列表 / 照片列表 / 视频接口）
2. 可解析响应的顶层字段与列表结构（含 JSONP 回调名）
3. **原图与视频直链候选**（按域名聚合，标注 `原图?` / `视频`）
4. 鉴权情况（p_skey / qq_photo_key / g_tk 出现在哪些请求里）
5. 分页参数（page / start / count 等）

结构化结果同步写入 `captures/<时间戳>/analysis.json`。

## 步骤三：定稿

拿到 `analysis.json` 后，我据此确定阶段二的：

- 相册列表接口与分页方式
- 照片列表接口与原图字段（含视频原画字段）
- g_tk 用哪个 key 计算、哪些 cookie 必须带
- 并发上限与重试策略的实测依据

## 安全与合规

- 仅登录你本人的账号，仅下载你有权限访问的内容。
- 抓包产物含登录态，**不要外传**；`captures/`、`profile/`、`session/` 已在 `.gitignore` 中。
- 不使用自动化密码登录、不破解验证码/滑块。

---

