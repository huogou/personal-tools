# personal-tools · 个人常用工具集

个人日常使用的自用工具集合。均为独立小工具，无服务器、无后端、无云依赖，本地运行，数据不出本机。

## 工具清单

| 工具 | 说明 | 技术栈 | 入口 |
|---|---|---|---|
| 网站图片 Alt 标签检查工具 | 批量检测网页图片的 Alt 标签写法情况，输出 Excel 报告 | Python + BeautifulSoup + openpyxl | `alt-scanner/alt_scanner.py` |
| 实况照片备份查看器 | 把 iPhone 实况照片从云盘/硬盘一键备份成 GIF 动图，生成可分享的网页查看器 | Python + Pillow + imageio-ffmpeg | `livephoto-viewer/LivePhoto_Backup.pyw` |
| QQ 空间相册下载器 | 抓取本人 QQ 空间相册的照片与视频并批量下载到本地 | Python + Playwright + 自研 GUI | `qzone-album/scripts/gui.py` |

---

## alt-scanner · 网站图片 Alt 标签检查工具

批量检测网站图片的 Alt 标签写法，输出 Excel 报告，便于 SEO 优化与无障碍检查。

**技术栈**：Python + BeautifulSoup（HTML 解析）+ openpyxl（Excel 输出）

**特点**：
- 抓取站点图片清单，逐张检查 alt 属性写法
- 输出 Excel 报告：图片地址、alt 现状、建议写法
- 22EI 图片检测需求的标准执行工具

**运行**：
```bash
pip install -r alt-scanner/requirements.txt   # 如有
python alt-scanner/alt_scanner.py
```

---

## livephoto-viewer · 实况照片备份查看器

iPhone 实况照片（Live Photo）的备份与查看工具。双件套原样保存，不丢动态照片的动态部分。

**技术栈**：Python + Pillow（图像处理）+ imageio-ffmpeg（动图编码，内置无需外部软件）+ PyInstaller（绿色单文件打包）

**核心能力**：
- **双件套原样备份** —— iPhone 实况照片由一张 HEIC 静态图 + 一段 MOV 视频组成，工具成对保存，绝不丢动态部分
- **自动转 GIF** —— 实况照片一键转换为 GIF 动图，内置编码引擎，无需安装额外软件
- **网页查看器** —— 自动生成可分享的网页查看页面，悬停自动播放、点击暂停
- **增量备份** —— 已处理过的照片自动跳过，二次运行只补新增部分
- **绿色单文件** —— 打包为单个 EXE，拷到 U 盘即可运行，无需安装 Python

**运行**：
```bash
# 方式一：绿色版（无需 Python）
双击 livephoto-viewer/dist/实况照片备份查看器.exe

# 方式二：源码运行（自动补齐依赖）
双击 livephoto-viewer/启动备份查看器.bat
```

**注意**：`dist/` 目录为打包产物，未纳入版本管理，可由源码重新构建。

---

## qzone-album · QQ 空间相册下载器

QQ 空间相册的照片与视频批量下载工具（自用）。

**技术栈**：Python + Playwright（浏览器自动化）+ 自研 GUI（tkinter）

**核心能力**：
- **免扫码抓包** —— 通过 CDP 接管已登录的 Edge 浏览器直接抓取接口，避免重复扫码登录
- **离线分析** —— 抓包结果离线解析，确认接口契约后再写下载逻辑
- **GUI 窗口程序** —— 双击运行，瘦启动器与源码同级

**产品约束（设计时必须遵守）**：
- 图片取原图、视频取原画；**拿不到时必须显式标记降级，不得静默用缩略图顶替**
- 目录结构保持 `<下载根>/<QQ号>/<相册名>/`（照片与视频同夹，不做二次拆分）
- 相册名与 QQ 空间保持一致

**安全合规**：仅登录本人账号、仅下载有权限内容；不使用自动化密码登录、不破解验证码；抓包产物含登录态，**不得外传**。

**运行**：
```bash
python qzone-album/scripts/gui.py
```

**环境**：Python 3，依赖见 `qzone-album/requirements.txt`

---

## 通用约定

- **无服务器、无后端、无云服务** —— 全部本地运行，数据不出本机
- **无账号体系** —— 不需要注册登录（qzone-album 复用浏览器已有登录态）
- **打包产物不入库** —— `dist/` 等可由源码重建的目录不纳入版本管理
- **凭据不入库** —— 任何密钥 / 口令 / 令牌 / 私钥一律不进版本库（见各目录 `.gitignore`）
- **一次性检测报告不入库** —— 临时产物（如 alt 检测导出的 Excel）属个人数据，不作��品展示

---

## 环境要求

| 工具 | Python | 外部依赖 |
|---|---|---|
| alt-scanner | 3.8+ | openpyxl |
| livephoto-viewer | 3.8+ | Pillow、imageio-ffmpeg |
| qzone-album | 3.8+ | Playwright、Edge 浏览器 |

三个工具相互独立，可单独取用。