# 实况照片备份查看器

Windows 上的 iPhone 实况照片备份与浏览工具。

实况照片（Live Photo）由一张 HEIC 主图和一段 MOV 视频组成，上传到云盘或移动硬盘后，这两个文件很容易被拆散、丢掉视频，照片就变成"不会动"的静态图。本工具把它们成对备份，并提供一个不联网的本地相册，可以直接在应用里播放实况视频。

## 功能

**备份**

- HEIC + MOV 成对保存，全程只读源文件，不修改、不删除原始照片
- 增量处理：已备份过的照片自动跳过，二次运行只补新增部分
- 自动生成 GIF 动图，以及一份离线网页查看器（双击 `index.html` 即可浏览和分享）
- 备份前检查路径冲突与磁盘剩余空间，过程中可安全取消

**相册**

- 应用内「相册」页，内嵌 WebView2，纯本地运行，不联网、不监听端口
- 点开才播放，播完回静止；同一时刻只播放一张
- 原视频无法直接解码时自动转为 H.264 MP4；仍不可用则降级为明确标注的 GIF 预览，不冒充视频播放
- 按源文件夹自动分类，可叠加手动相册
- 大目录分页加载；缺失配对、损坏文件、未识别格式分别给出提示

## 环境要求

- Windows 10 / 11
- WebView2 Runtime（Windows 11 自带；Windows 10 需安装 Evergreen Runtime）
- Python 3.9 及以上（仅源码方式运行需要）

## 源码运行

```bash
pip install -r requirements.txt
python LivePhoto_Backup.pyw
```

也可以双击 `启动备份查看器.bat`，脚本会自动补齐依赖后启动。

## 打包为单文件 EXE

```bash
pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed ^
  --name 实况照片备份查看器 LivePhoto_Backup.pyw
```

## 命令行

```bash
# 备份（不弹界面）
实况照片备份查看器.exe --cli <照片文件夹> <输出文件夹>

# 只读预览（只扫描、不改动任何文件，在浏览器中查看结果）
实况照片备份查看器.exe --preview <照片文件夹>
```

## 输出目录结构

```
输出文件夹\
├── 原始文件\      HEIC + MOV 原样保存
├── GIF动图\       每张照片对应的 GIF
└── 网页查看器\     index.html + 缩略图，双击即可浏览
```

相册索引与转码缓存写在输出文件夹下的 `相册索引.json`、`播放缓存\` 中，源目录不会被写入。

## 主要文件

| 文件 | 说明 |
|---|---|
| `LivePhoto_Backup.pyw` | 主程序：备份流程、界面、相册页宿主 |
| `album_scan.py` | 扫描源目录并按（目录，文件名）配对主图与视频 |
| `album_index.py` | 相册索引的读写与分组 |
| `album_media.py` | 视频有效性探测与 H.264 转码 |
| `album_api.py` | 相册页与 Python 侧之间的桥接 API |
| `album_page.py` | 相册页的 HTML / CSS / JS |
| `album_webview.py` | WebView2 宿主（进程内直驱，不使用本地端口） |
| `album_host.py` | 相册页生命周期与状态下发 |
| `使用说明.txt` | 面向使用者的操作说明 |

## 已知限制

- 仓库不包含示例照片，首次运行请自行选择照片文件夹
- HEVC 视频能否直接播放取决于系统解码组件；无法直解时会自动转码为 H.264，转码由内置 ffmpeg 完成
- 相册页依赖 WebView2 Runtime；未安装时会提供"用浏览器打开"的降级入口
- 仅支持 Windows 桌面

## 许可

个人自用工具，未做公开发布准备。
