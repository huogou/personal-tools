# -*- coding: utf-8 -*-
"""
实况照片备份查看器 (LivePhoto Backup Viewer)
============================================
把 iPhone 实况照片（.heic + .mov 双件套）从云盘/移动硬盘的“拆散状态”恢复成
可在一台普通 Windows 电脑上查看实况动态的工具。

功能：
  1. 扫描源文件夹，按文件名自动配对 主图(.heic/.heif/.jpg) + 视频(.mov/.mp4)
  2. 保留原始双件套（原样复制，不压缩）
  3. 用内置 ffmpeg 把每张实况转成 GIF 动态图（任何电脑都能双击看动态）
  4. 生成网页查看器（双击 index.html，悬停/点击即可播放实况，体验接近手机）
  5. 增量备份：处理过的照片不会重复转换

用法：
  双击本文件 -> 图形界面操作
  或命令行：python LivePhoto_Backup.pyw --cli "<源文件夹>" "<输出文件夹>"
"""

import os
import sys
import io
import json
import shutil
import subprocess
import threading
import queue
import webbrowser
import tempfile
import time
from urllib.parse import quote

try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG = "ffmpeg"  # 兜底：如果系统自带 ffmpeg 也可用

# V1.3 新增：相册页相关模块（索引 / 扫描 / 媒体引擎 / 前端 / 桥接 / WebView2 宿主）
# 说明：这些模块为 V1.3 全新代码，不改动 V1.2 的 12 个受保护函数。
try:
    import album_host
except Exception:      # pragma: no cover - 相册页不可用时不影响备份页
    album_host = None

# 兼容文件名编码（Windows 中文路径）；打包成 exe 窗口模式时 stdout/stderr 为 None，需判空
if sys.stdout is not None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr is not None:
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 主图 / 视频扩展名
PHOTO_EXTS = {".heic", ".heif", ".jpg", ".jpeg", ".png"}
VIDEO_EXTS = {".mov", ".mp4", ".m4v"}


def find_live_photos(src_dir):
    """扫描源目录，返回 [{name, photo_path, video_path}, ...] 匹配列表。"""
    pairs = {}
    for root, dirs, files in os.walk(src_dir):
        for f in files:
            base, ext = os.path.splitext(f)
            ext = ext.lower()
            full = os.path.join(root, f)
            if ext in PHOTO_EXTS or ext in VIDEO_EXTS:
                key = base.lower()
                entry = pairs.setdefault(key, {"name": base})
                if ext in PHOTO_EXTS:
                    entry["photo_path"] = full
                else:
                    entry["video_path"] = full
    return [v for v in pairs.values() if "photo_path" in v and "video_path" in v]


def _run_ffmpeg(args):
    """执行 ffmpeg，失败抛异常。"""
    try:
        r = subprocess.run([FFMPEG, "-y", "-loglevel", "error"] + args,
                           capture_output=True, text=True)
    except FileNotFoundError:
        raise RuntimeError("找不到 ffmpeg，请先执行依赖安装（install_deps.bat）")
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:500])
    return r


def convert_to_gif(video_path, gif_path, max_width=540, fps=12):
    """把视频转成短循环 GIF。"""
    vf = f"fps={fps},scale={max_width}:-1:flags=lanczos"
    _run_ffmpeg(["-i", video_path, "-vf", vf, "-loop", "0", gif_path])


def extract_cover(video_path, cover_path):
    """从视频抽取第一帧作为静态封面（jpg）。"""
    _run_ffmpeg(["-i", video_path, "-vframes", "1", "-q:v", "3", cover_path])


def load_done(output_dir):
    """读取增量记录。"""
    p = os.path.join(output_dir, ".processed.json")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}
    return {}


def save_done(output_dir, done):
    with open(os.path.join(output_dir, ".processed.json"), "w", encoding="utf-8") as fh:
        json.dump(done, fh, ensure_ascii=False, indent=2)


def build_html(output_dir, items):
    """生成网页查看器 index.html。items: [{name, gif_path_rel, cover_path_rel, photo_name}]"""
    cards = []
    for it in items:
        cards.append(
            '<div class="card" title="点击播放/暂停">'
            f'<img class="cover" src="{it["cover_rel"]}" alt="{it["name"]}">'
            f'<img class="mov" src="{it["gif_rel"]}" alt="{it["name"]}">'
            f'<div class="lbl">{it["name"]}</div>'
            "</div>"
        )
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>实况照片查看器</title>
<style>
  body{margin:0;font-family:"Microsoft YaHei",sans-serif;background:#101418;color:#eee}
  header{padding:20px;text-align:center;background:#1a2027}
  header h1{margin:0;font-size:20px}
  header p{margin:6px 0 0;color:#9aa5b1;font-size:13px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px;padding:20px}
  .card{position:relative;height:220px;border-radius:10px;overflow:hidden;background:#222;cursor:pointer}
  .card img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;transition:transform .2s}
  .card img.mov{display:none}
  .card.playing img.cover{display:none}
  .card.playing img.mov{display:block}
  .card:hover img.cover{transform:scale(1.04)}
  .lbl{position:absolute;left:0;right:0;bottom:0;padding:8px;font-size:12px;text-align:center;
       background:linear-gradient(transparent,#000a)}
  footer{text-align:center;color:#6b7681;padding:16px;font-size:12px}
</style>
</head>
<body>
<header>
  <h1>📷 我的实况照片</h1>
  <p>共 __COUNT__ 张 · 悬停预览，点击播放/暂停动态</p>
</header>
<div class="grid">__CARDS__</div>
<footer>由「实况照片备份查看器」生成 · 原始双件套请查看「原始文件」文件夹</footer>
<script>
  document.querySelectorAll('.card').forEach(function(c){
    c.addEventListener('click', function(){
      c.classList.toggle('playing');
    });
  });
</script>
</body>
</html>"""
    html = html.replace("__COUNT__", str(len(items))).replace("__CARDS__", "\n".join(cards))
    out = os.path.join(output_dir, "网页查看器", "index.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    return out


def _notify_progress(progress_cb, payload, log):
    """调用进度回调；返回 True 表示「用户请求取消」。

    约定（Q4 裁定 / 任务书 §3）：
      - 仅当回调**显式返回 False** 时视为请求取消；返回 None 或其它值一律继续；
      - 回调只用于报告进度与请求取消，不改变任何备份业务规则；
      - 回调抛异常时记录 [警告] 并继续备份，不静默改变备份结果。
    """
    if progress_cb is None:
        return False
    try:
        r = progress_cb(payload)
    except Exception as e:
        log(f"[警告] 进度回调异常（本次进度未上报，备份继续）: {e}")
        return False
    return r is False


def process_directory(src_dir, output_dir, keep_raw=True, make_gif=True, make_html=True,
                      log=print, progress_cb=None):
    """核心处理流程。返回统计信息 dict。

    V1.2 变更（仅限进度回调所需的最小调整，业务规则不变）：
      - 新增可选参数 progress_cb；**不传回调时行为与 V1.1 完全一致**（CLI 旧调用方式兼容）。
      - 回调载荷：{"event": "start"|"item", "index": int, "total": int, "name": str, ...}。
      - 仅当回调显式返回 False 才请求取消；取消在**条目之间的安全检查点**生效，
        当前条目完整处理完（复制/转码）后才停止，绝不中断单个文件的写入。
      - 取消后照常 save_done，已成功条目照常记录，未处理条目不会写进 .processed.json。
      - 条目处理完成后立即落盘 .processed.json（键与值含义不变）：满足"崩溃后已完成条目
        不丢失"的要求；正常跑完时文件内容与 V1.1 逐字节一致。
    """
    os.makedirs(output_dir, exist_ok=True)
    pairs = find_live_photos(src_dir)
    if not pairs:
        log("未在源目录找到成对的实况照片（需要 主图+同名视频）。")
        return None

    raw_dir = os.path.join(output_dir, "原始文件")
    gif_dir = os.path.join(output_dir, "GIF动图")
    done = load_done(output_dir)

    stats = {"total": 0, "skipped": 0, "ok": 0, "fail": 0, "new_gif": 0}
    stats["total"] = len(pairs)
    items = []  # 用于网页
    total = len(pairs)
    cancelled = False

    if _notify_progress(progress_cb, {"event": "start", "total": total}, log):
        cancelled = True

    for idx, p in enumerate(pairs):
        if cancelled:
            break
        key = os.path.splitext(os.path.basename(p["video_path"].lower()))[0] + "|" + os.path.dirname(p["video_path"])
        if key in done and done[key]:
            stats["skipped"] += 1
        else:
            try:
                if keep_raw:
                    os.makedirs(raw_dir, exist_ok=True)
                    shutil.copy2(p["photo_path"], os.path.join(raw_dir, os.path.basename(p["photo_path"])))
                    shutil.copy2(p["video_path"], os.path.join(raw_dir, os.path.basename(p["video_path"])))
                if make_gif:
                    os.makedirs(gif_dir, exist_ok=True)
                    gif_path = os.path.join(gif_dir, p["name"] + ".gif")
                    if not os.path.exists(gif_path):
                        convert_to_gif(p["video_path"], gif_path)
                        stats["new_gif"] += 1
                done[key] = True
                stats["ok"] += 1
                log(f"[成功] {p['name']}")
            except Exception as e:
                stats["fail"] += 1
                log(f"[失败] {p['name']}: {e}")
                done[key] = False
            # V1.2：条目处理完立即落盘（异常退出/取消都不丢已完成记录）
            save_done(output_dir, done)
        if _notify_progress(progress_cb, {"event": "item", "index": idx, "total": total,
                                           "name": p["name"]}, log):
            cancelled = True

    save_done(output_dir, done)

    if cancelled:
        remaining = max(0, total - stats["ok"] - stats["skipped"] - stats["fail"])
        log(f"[已取消] 用户取消，完成 {stats['ok']} 组，未处理 {remaining} 组（下次备份自动续传）。")
        return stats

    if make_html:
        video_map = {p["name"]: p["video_path"] for p in pairs}
        for p in pairs:
            if not os.path.exists(os.path.join(gif_dir, p["name"] + ".gif")):
                continue
            items.append({
                "name": p["name"],
                "cover_rel": "thumb/" + p["name"] + ".jpg",
                "gif_rel": "../GIF动图/" + p["name"] + ".gif",
            })
        # 抽封面
        thumb_dir = os.path.join(output_dir, "网页查看器", "thumb")
        os.makedirs(thumb_dir, exist_ok=True)
        for it in items:
            cover = os.path.join(thumb_dir, it["name"] + ".jpg")
            if not os.path.exists(cover):
                try:
                    extract_cover(video_map[it["name"]], cover)
                except Exception:
                    continue
        html_path = build_html(output_dir, items)
        log(f"网页查看器已生成: {html_path}")

    log(f"统计: 共{stats['total']}张，新处理{stats['ok']}，跳过{stats['skipped']}，失败{stats['fail']}。")
    return stats


# ---------- 只读预览（V1.1 新增，独立于备份流程） ----------

PREVIEW_TEMP_DIR = None  # 跟踪上一次预览临时目录，便于刷新时清理


def to_file_url(path):
    """把本地绝对路径转成 file:/// URL（兼容中文/空格）。"""
    p = os.path.abspath(path).replace("\\", "/")
    return "file:///" + quote(p, safe="/:")


def scan_groups(src_dir):
    """扫描源目录，按同名基名分组，并做轻量分类（非完整五态诊断）。

    返回 [{name, photos:[...], videos:[...], status}, ...]，status 取值：
      complete   : 恰好 1 图 + 1 视频（可靠配对）
      uncertain  : 同名多候选（图或视频多于 1 个），保留并标记待确认
      incomplete : 仅有图或仅有视频，不臆断另一类已丢失
    """
    groups = {}
    for root, dirs, files in os.walk(src_dir):
        for f in files:
            base, ext = os.path.splitext(f)
            ext = ext.lower()
            full = os.path.join(root, f)
            if ext in PHOTO_EXTS or ext in VIDEO_EXTS:
                key = base.lower()
                g = groups.setdefault(key, {"name": base, "photos": [], "videos": []})
                if ext in PHOTO_EXTS:
                    g["photos"].append(full)
                else:
                    g["videos"].append(full)
    results = []
    for key, g in groups.items():
        np, nv = len(g["photos"]), len(g["videos"])
        if np == 1 and nv == 1:
            status = "complete"
        elif np > 1 or nv > 1:
            status = "uncertain"   # 同名多候选，不静默覆盖
        else:
            status = "incomplete"  # 仅有图或仅有视频
        results.append({"name": g["name"], "photos": g["photos"],
                        "videos": g["videos"], "status": status})
    return results


def build_preview_html(temp_dir, items, stats):
    """生成统一只读预览页 index.html（引用原始文件 file://，不复制）。"""
    badge_map = {"complete": "完整配对", "uncertain": "待确认", "incomplete": "不完整"}
    cards = []
    for it in items:
        badge = badge_map.get(it["status"], it["status"])
        cls = it["status"]
        if it.get("cover_rel"):
            inner = f'<img class="cover" src="{it["cover_rel"]}" alt="{it["name"]}">'
        else:
            inner = '<div class="ph">无封面<br>（仅图片或无配对视频）</div>'
        cards.append(
            f'<div class="card {cls}" data-video="{it["video_url"]}" data-name="{it["name"]}">'
            f'{inner}'
            f'<div class="badge">{badge}</div>'
            f'<div class="lbl">{it["name"]}</div>'
            f'</div>'
        )
    stats_line = (f'扫描 {stats["total"]} · 完整配对 {stats["complete"]} · '
                  f'可预览 {stats["previewable"]} · 待确认/异常 {stats["uncertain"] + stats["incomplete"]} · 失败 {stats["failed"]}')
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>实况照片只读预览</title>
<style>
  body{margin:0;font-family:"Microsoft YaHei",sans-serif;background:#101418;color:#eee}
  header{padding:18px;text-align:center;background:#1a2027}
  header h1{margin:0;font-size:20px}
  header p{margin:6px 0 0;color:#9aa5b1;font-size:13px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px;padding:20px}
  .card{position:relative;height:220px;border-radius:10px;overflow:hidden;background:#222;cursor:pointer}
  .card img.cover{width:100%;height:100%;object-fit:cover}
  .card .ph{display:flex;align-items:center;justify-content:center;height:100%;color:#889;font-size:13px;text-align:center;padding:10px}
  .badge{position:absolute;top:8px;left:8px;padding:3px 8px;border-radius:10px;font-size:11px;background:#2f6fed;color:#fff}
  .card.uncertain .badge{background:#e0a800}
  .card.incomplete .badge{background:#888}
  .lbl{position:absolute;left:0;right:0;bottom:0;padding:8px;font-size:12px;text-align:center;background:linear-gradient(transparent,#000a)}
  #overlay{position:fixed;inset:0;background:#000c;display:none;align-items:center;justify-content:center;flex-direction:column;z-index:10}
  #overlay.show{display:flex}
  #player{max-width:90vw;max-height:80vh;background:#000}
  #back{margin-top:14px;padding:8px 22px;border:0;border-radius:8px;background:#2f6fed;color:#fff;font-size:14px;cursor:pointer}
  #err{color:#ffd27f;margin-top:10px;font-size:13px;max-width:80vw;text-align:center}
  footer{text-align:center;color:#6b7681;padding:16px;font-size:12px}
</style>
</head>
<body>
<header>
  <h1>📷 实况照片只读预览</h1>
  <p>__STATS__</p>
</header>
<div class="grid">__CARDS__</div>
<div id="overlay">
  <video id="player" controls playsinline></video>
  <div id="err"></div>
  <button id="back">返回网格</button>
</div>
<footer>只读预览 · 直接播放原始视频，未复制/修改任何原始文件</footer>
<script>
  var player = document.getElementById('player');
  var overlay = document.getElementById('overlay');
  var err = document.getElementById('err');
  function show(url){
    err.textContent = '';
    player.src = url;
    var p = player.play();
    if (p && p.catch) { p.catch(function(){}); }
    overlay.classList.add('show');
  }
  function hide(){
    try { player.pause(); } catch(e){}
    player.removeAttribute('src');
    try { player.load(); } catch(e){}
    overlay.classList.remove('show');
  }
  document.querySelectorAll('.card').forEach(function(c){
    c.addEventListener('click', function(){
      var url = c.getAttribute('data-video');
      if (!url) {
        err.textContent = '该条目没有可播放的视频（仅图片或配对不完整）。';
        overlay.classList.add('show');
        return;
      }
      show(url);
    });
  });
  player.addEventListener('error', function(){
    err.textContent = '该视频编码（可能为 HEVC）当前浏览器无法播放。可改用原备份 GIF 或系统自带播放器打开原始文件。';
  });
  document.getElementById('back').addEventListener('click', hide);
  overlay.addEventListener('click', function(e){ if (e.target === overlay) hide(); });
</script>
</body>
</html>"""
    html = html.replace("__STATS__", stats_line).replace("__CARDS__", "\n".join(cards))
    out = os.path.join(temp_dir, "index.html")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)
    return out


PREVIEW_DIR_PREFIX = "livephoto_preview_"          # 预览临时目录名前缀
PREVIEW_MARKER_NAME = ".livephoto_preview_owner"   # 归属标记文件名（用于确认目录确属本工具）
PREVIEW_MARKER_TEXT = "livephoto-backup-viewer/read-only-preview/v1.1"


def _is_our_preview_dir(path):
    """严格判断目录是否确属本工具：必须是目录、且含内容匹配的归属标记文件。

    仅靠文件名匹配不足以证明归属，因此必须同时满足标记文件校验，
    避免误删用户或其他程序创建的同名目录。
    """
    try:
        if not os.path.isdir(path):
            return False
        marker = os.path.join(path, PREVIEW_MARKER_NAME)
        if not os.path.isfile(marker):
            return False
        with open(marker, "r", encoding="utf-8") as fh:
            return fh.read().strip() == PREVIEW_MARKER_TEXT
    except Exception:
        return False


def cleanup_stale_preview_dirs(log=print, keep=None):
    """清理本工具遗留的预览临时目录（CLI 独立进程运行时同样生效）。

    - 只处理 temp 目录下以 livephoto_preview_ 开头的目录；
    - 只删除含有效归属标记、能够确认属于本工具的目录；
    - 无法确认归属的一律跳过并提示，不做任何删除；
    - 清理失败只记录警告，不影响预览主流程。
    """
    removed = []
    skipped = []
    base = tempfile.gettempdir()
    try:
        names = os.listdir(base)
    except Exception as e:
        log(f"[警告] 临时目录枚举失败，跳过残留清理: {e}")
        return removed
    for name in names:
        if not name.startswith(PREVIEW_DIR_PREFIX):
            continue
        path = os.path.join(base, name)
        if keep and os.path.abspath(path) == os.path.abspath(keep):
            continue
        if not _is_our_preview_dir(path):
            skipped.append(path)
            continue
        try:
            shutil.rmtree(path)
            removed.append(path)
        except Exception as e:
            log(f"[警告] 清理预览临时目录失败(已跳过): {path} -> {e}")
    if skipped:
        log(f"[提示] 发现 {len(skipped)} 个同名但无法确认归属的临时目录，已跳过不删除。")
    if removed:
        log(f"已清理残留预览临时目录 {len(removed)} 个。")
    return removed


def run_preview(src_dir, log=print):
    """只读预览主流程：扫描源目录（不复制/不生成 GIF），生成统一预览页并打开。"""
    global PREVIEW_TEMP_DIR
    results = scan_groups(src_dir)
    total = len(results)
    complete = sum(1 for r in results if r["status"] == "complete")
    uncertain = sum(1 for r in results if r["status"] == "uncertain")
    incomplete = sum(1 for r in results if r["status"] == "incomplete")
    previewable = sum(1 for r in results if r["videos"])  # 有视频即可尝试预览
    failed = 0

    # 准备独立临时目录（仅用于封面缓存与预览页，绝不写入原始目录）
    # 清理本工具遗留的预览目录：跨进程（CLI 每次独立启动）也能生效；
    # 仅清理带有效归属标记、可确认属于本工具的目录，清理失败只告警不中断。
    cleanup_stale_preview_dirs(log=log)
    PREVIEW_TEMP_DIR = tempfile.mkdtemp(prefix=PREVIEW_DIR_PREFIX)
    try:
        with open(os.path.join(PREVIEW_TEMP_DIR, PREVIEW_MARKER_NAME), "w", encoding="utf-8") as fh:
            fh.write(PREVIEW_MARKER_TEXT)
    except Exception as e:
        log(f"[警告] 写入预览目录归属标记失败(该目录后续不会被自动清理): {e}")
    thumb_dir = os.path.join(PREVIEW_TEMP_DIR, "thumb")
    os.makedirs(thumb_dir, exist_ok=True)

    items = []
    for r in results:
        if not r["videos"]:
            # 仅有图片（不完整）：列入网格但不作为可预览实况
            items.append({"name": r["name"], "status": r["status"],
                          "video_url": "", "cover_rel": ""})
            continue
        vid = r["videos"][0]
        video_url = to_file_url(vid)
        cover_rel = ""
        try:
            cover = os.path.join(thumb_dir, r["name"] + ".jpg")
            if not os.path.exists(cover):
                extract_cover(vid, cover)
            cover_rel = "thumb/" + r["name"] + ".jpg"
        except Exception as e:
            log(f"[封面失败] {r['name']}: {e}")
            failed += 1
        items.append({"name": r["name"], "status": r["status"],
                      "video_url": video_url, "cover_rel": cover_rel})

    stats = {"total": total, "complete": complete, "uncertain": uncertain,
             "incomplete": incomplete, "previewable": previewable, "failed": failed}
    html_path = build_preview_html(PREVIEW_TEMP_DIR, items, stats)
    log(f"预览已生成: {html_path}")
    log(f"统计: 扫描{total} · 完整{complete} · 可预览{previewable} · 待确认{uncertain} · 不完整{incomplete} · 失败{failed}")
    try:
        webbrowser.open(html_path)
        log("已在默认浏览器打开预览（只读，未复制/修改原始文件）。")
    except Exception as e:
        log(f"[提示] 无法自动打开浏览器: {e}，请手动打开: {html_path}")
    return stats


# ---------- V1.2 安全判定与空间预检（03 号 §6.1 / §6.2） ----------

GIF_SIZE_ESTIMATE = 2 * 1024 * 1024     # 单张 GIF 约 2MB（05 号文档口径）
SPACE_CHECK_TIMEOUT = 3.0               # 空间预检超时上限（秒）


def format_bytes(n):
    """把字节数格式化成人类可读的体积文本。"""
    if n is None:
        return "-"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "-"
    if n < 0:
        n = 0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _norm_path(p):
    """规范化路径：abspath → normpath → normcase → 去掉尾部路径分隔符。"""
    if p is None:
        raise ValueError("路径为空")
    s = str(p).strip().strip('"')
    if not s:
        raise ValueError("路径为空")
    s = os.path.abspath(s)
    s = os.path.normpath(s)
    s = os.path.normcase(s)
    if len(s) > 3 and s[-1] in ("\\", "/"):
        s = s[:-1]
    return s


def _long_path(p):
    """尽力而为：用 GetLongPathNameW 展开 8.3 短文件名。失败返回 None。"""
    try:
        import ctypes
        from ctypes import wintypes
        fn = ctypes.windll.kernel32.GetLongPathNameW
        fn.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        fn.restype = wintypes.DWORD
        buf = ctypes.create_unicode_buffer(32768)
        n = fn(str(p), buf, len(buf))
        if n == 0 or n > len(buf):
            return None
        return buf.value
    except Exception:
        return None


def _path_variants(p):
    """返回同一路径的等价形式集合（规范化 / realpath / 长路径名）。"""
    variants = set()
    base = _norm_path(p)
    variants.add(base)
    try:
        rp = os.path.realpath(p)
        if rp:
            variants.add(_norm_path(rp))
    except Exception:
        pass
    lp = _long_path(p)
    if lp:
        try:
            variants.add(_norm_path(lp))
        except Exception:
            pass
    return variants


def _is_under(child, parent):
    """child 是否位于 parent 内部（必须以路径分隔符为边界，禁止裸 startswith）。"""
    if child == parent:
        return False
    if parent.endswith("\\") or parent.endswith("/"):
        return child.startswith(parent)
    if not child.startswith(parent):
        return False
    return child[len(parent)] in ("\\", "/")


def check_path_relation(src_dir, out_dir):
    """判定「照片文件夹」与「备份输出目录」的关系。

    返回 {"status": ..., "detail": ...}，status 取值：
      ok          —— 两个目录互相独立，可以备份
      same        —— 两者指向同一个位置（拦截）
      out_in_src  —— 输出目录位于源目录内部（拦截）
      src_in_out  —— 源目录位于输出目录内部（拦截，防递归污染）
      unknown     —— 无法可靠判定（拦截，不得放行）
    """
    try:
        s_variants = _path_variants(src_dir)
        o_variants = _path_variants(out_dir)
    except Exception as e:
        return {"status": "unknown", "detail": str(e)}
    if not s_variants or not o_variants:
        return {"status": "unknown", "detail": "路径无法解析"}
    if s_variants & o_variants:
        return {"status": "same", "detail": "两个目录指向同一个位置"}
    for s in s_variants:
        for o in o_variants:
            if _is_under(o, s):
                return {"status": "out_in_src", "detail": "输出目录位于照片文件夹内部"}
    for s in s_variants:
        for o in o_variants:
            if _is_under(s, o):
                return {"status": "src_in_out", "detail": "照片文件夹位于输出目录内部"}
    return {"status": "ok", "detail": "两个目录互相独立"}


def estimate_backup_size(src_dir, timeout=SPACE_CHECK_TIMEOUT, include_gif=True):
    """估算本次备份需要的磁盘空间（三态）。

    返回 {"state": "ok"|"timeout"|"error", "need": int, "pairs": int, "detail": str}
      ok      —— 估算完成，need 为预计占用字节数
      timeout —— 超过 timeout 秒仍未遍历完（目录过大）＝「未完成检查」
      error   —— 读取失败（如权限不足）＝「检查失败」
    两种异常态都**不得**被解读为「空间充足」。
    """
    deadline = time.monotonic() + max(0.2, float(timeout))
    try:
        groups = {}
        counter = 0
        for root, dirs, files in os.walk(src_dir):
            for f in files:
                base, ext = os.path.splitext(f)
                ext = ext.lower()
                if ext not in PHOTO_EXTS and ext not in VIDEO_EXTS:
                    continue
                try:
                    size = os.path.getsize(os.path.join(root, f))
                except OSError:
                    size = 0
                g = groups.setdefault(base.lower(), {"photo": None, "video": None})
                if ext in PHOTO_EXTS:
                    g["photo"] = size
                else:
                    g["video"] = size
                counter += 1
                if counter % 200 == 0 and time.monotonic() > deadline:
                    return {"state": "timeout", "need": 0, "pairs": 0, "detail": "遍历目录超时"}
            if time.monotonic() > deadline:
                return {"state": "timeout", "need": 0, "pairs": 0, "detail": "遍历目录超时"}
        need = 0
        pairs = 0
        for g in groups.values():
            if g["photo"] is None or g["video"] is None:
                continue
            pairs += 1
            need += g["photo"] + g["video"]
        if include_gif:
            need += pairs * GIF_SIZE_ESTIMATE
        return {"state": "ok", "need": need, "pairs": pairs, "detail": ""}
    except Exception as e:
        return {"state": "error", "need": 0, "pairs": 0, "detail": str(e)}


def check_free_space(out_dir):
    """返回目标目录所在磁盘的可用字节数；无法确定时抛异常。"""
    p = os.path.abspath(str(out_dir).strip().strip('"'))
    probe = p
    while probe and not os.path.isdir(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    if not os.path.isdir(probe):
        raise OSError("找不到可用于检查剩余空间的目录")
    return shutil.disk_usage(probe).free


# ---------- V1.2 设计令牌（02 号《桌面 UI 视觉设计规范》） ----------

C = {
    # 基础色板
    "primary": "#2F6FED", "primary_hover": "#2559C9",
    "surface": "#FFFFFF", "window": "#F5F7FA", "window_alt": "#EEF1F5",
    "border": "#D0D7DE", "border_strong": "#A8B3BF",
    "text_primary": "#1F2328", "text_secondary": "#57606A", "text_tertiary": "#6E7781",
    "disabled_fg": "#8B949E", "disabled_bg": "#EFF1F3",
    "preview_green": "#1F9D55", "preview_green_hover": "#178346",
    # 状态色三件套（文字色 / 底色 / 边框色）+ 符号
    "success": "#1A7F37", "success_bg": "#E6F4EA", "success_bd": "#A6D8B8",
    "progress": "#0969DA", "progress_bg": "#DDF4FF", "progress_bd": "#82B7E8",
    "warning": "#9A6700", "warning_bg": "#FFF8C5", "warning_bd": "#D4A72C",
    "uncertain": "#BC4C00", "uncertain_bg": "#FFF1E5", "uncertain_bd": "#E8A87C",
    "danger": "#CF222E", "danger_bg": "#FFEBE9", "danger_bd": "#F0B1AC",
    "neutral": "#57606A", "neutral_bg": "#F0F3F7", "neutral_bd": "#D0D7DE",
}

SP = {"win": 16, "section": 12, "card_in": 12, "ctrl": 8, "inline": 6, "line": 4}

# 状态 → (文字色, 底色, 边框色, 符号)；三重编码：颜色 + 符号 + 文字
STATUS = {
    "idle":      ("#57606A", "#F0F3F7", "#D0D7DE", "○"),
    "progress":  ("#0969DA", "#DDF4FF", "#82B7E8", "●"),
    "success":   ("#1A7F37", "#E6F4EA", "#A6D8B8", "✓"),
    "warning":   ("#9A6700", "#FFF8C5", "#D4A72C", "⚠"),
    "uncertain": ("#BC4C00", "#FFF1E5", "#E8A87C", "？"),
    "danger":    ("#CF222E", "#FFEBE9", "#F0B1AC", "✕"),
    "neutral":   ("#57606A", "#F0F3F7", "#D0D7DE", "○"),
}

# ---------- V1.2 用户可见文案（06 号《UI 文案与异常提示清单》） ----------

COPY = {
    "no_src": {
        "title": "还没选照片文件夹",
        "body": "请先告诉程序照片放在哪里。\n\n"
                "点「照片文件夹」右边的「浏览」，选中存放照片的文件夹（会自动扫描子文件夹）。",
        "btn": "好的，去选择",
    },
    "no_dst": {
        "title": "还没选备份输出文件夹",
        "body": "请告诉程序备份要存到哪里。\n\n"
                "点「备份输出到」右边的「浏览」，选一个和照片文件夹完全分开的文件夹"
                "（比如在 D 盘新建一个「实况照片备份」文件夹）。",
        "btn": "好的，去选择",
    },
    "path_same": {
        "title": "备份位置不能和照片位置相同（或互相包含）",
        "body": "你选的备份输出目录就是照片所在的文件夹，或两个目录互相包含（一个在另一个里面）。"
                "这样备份会把文件复制进自己里面，结果不可预测。\n\n"
                "请重新选一个和照片文件夹完全分开的文件夹，比如 D 盘新建一个「实况照片备份」文件夹。",
        "btn": "重新选择",
    },
    "path_unknown": {
        "title": "无法确认两个文件夹的关系",
        "body": "程序在检查「照片文件夹」和「备份输出到」的关系时遇到异常（可能是特殊路径或系统限制），"
                "为了安全，这次备份不能开始。\n\n"
                "请把两个文件夹换成更简单的常规路径（如 D 盘根目录下的两个普通文件夹）后重试；"
                "如反复出现，请把文件夹路径截图反馈。",
        "btn": "重新选择",
    },
    "space_short": {
        "title": "目标硬盘空间可能不够",
        "body": "本次备份大约需要 {need}，目标盘当前只剩 {free}。空间不足时备份会中途失败，留下不完整文件。\n\n"
                "换一个空间够的盘，或清理目标盘后重试。（估算值，实际以文件大小为准）",
    },
    "space_unknown": {
        "title": "空间检查未完成",
        "body": "因为照片文件夹较大（或读取受限），程序**没有完成**空间检查——"
                "**这不是「空间足够」，只是没查成**。空间不足时备份会中途失败，已成功部分会保留。\n\n"
                "建议先自行确认目标盘剩余空间明显大于照片文件夹体积，再继续；或换一个空间充裕的盘。",
    },
    "close_ask": {
        "title": "备份还没完成，要继续等待吗",
        "body": "正在备份。程序不会中途强行中断写入；你可以等它跑完，或选择「安全取消」——"
                "当前这张处理完后停止，已完成的都会保留，下次备份自动接着做。\n\n"
                "建议等它跑完（通常几分钟内）。",
    },
    "cancel_ask": {
        "title": "确定要取消这次备份吗",
        "body": "已经复制完成的文件会保留，当前正在处理的这一张做完后就停止；"
                "剩下的下次备份会自动接着做，不会重复。\n\n"
                "如果只是想看看进度，可以选「继续备份」。",
    },
    "cancel_done": {
        "title": "备份已取消",
        "body": "已完成 {ok} 组并已保存记录；其余 {rest} 组未处理。你的原始照片一个都没动。",
    },
    "backup_done": {
        "body": "成功 {ok} 组 · 已跳过 {skipped} 组（之前备份过）· 失败 {fail} 组。你的原始照片一个都没动。",
    },
    "write_fail": {
        "title": "有文件没写进去",
        "body": "常见原因：目标盘满了、文件被其他程序占用、或目标文件夹没有写入权限。"
                "已成功的部分不受影响，原始照片始终没被改动。",
    },
}

DELETE_ORIGIN_WARNING = "未经验证的备份不能作为删除原文件的依据"

# ---------- V1.2 向导文案（04 号 / 05 号文档） ----------

WIZARD_A_STEPS = [
    {
        "title": "先确认手机里的照片是「会动的」",
        "blocks": [
            ("p", "1. 打开 iPhone 的「照片」App，找到你想备份的照片。"),
            ("p", "2. 看照片左上角：如果有一个「实况」小标志（ISO 感光符号样式的圆圈），"
                  "说明它是一张实况照片——按住屏幕松手就能看到当时那一两秒的动态。"),
            ("p", "3. 没有这个标志的照片就是普通静态照片，它不需要这个工具，直接备份就行。"),
            ("warn", "准备用数据线导入的话，请检查你的数据线支持传文件（不是所有充电线都能传数据）。"
                     "便宜的充电线插上电脑常常只能充电、电脑里看不到照片。"),
            ("warn", "「实况」开关如果被关掉了（拍照时顶部的同心圆图标划掉了），"
                     "新拍的照片不会带动态。想拍会动的，先把这个开关打开。"),
            ("p", "本步需要手动：全部由用户在手机上完成。"),
        ],
        "next": "下一步：把照片传到电脑",
    },
    {
        "title": "把照片传到电脑——两条路，选你顺手的",
        "blocks": [
            ("h", "路线一：数据线（推荐，最完整）"),
            ("p", "1. 用支持传文件的数据线把 iPhone 连到电脑。"),
            ("p", "2. 手机上如果弹出「要信任此电脑吗」，点「信任」并输入锁屏密码。"),
            ("p", "3. 打开电脑的「此电脑」→ 找到 iPhone 设备 → 进 Internal Storage\\DCIM 文件夹，"
                  "把照片文件夹整个复制到电脑硬盘（比如 D:\\照片\\iPhone导出）。"),
            ("p", "4. 或者用 Windows 自带的「照片」App 导入（开始菜单搜「照片」→ 导入）。"),
            ("h", "路线二：你已经在用的同步 / 传输方式"),
            ("p", "iCloud 照片、网盘、微信 / QQ 文件传输助手等都可以，把照片先弄到电脑某个文件夹里就行。"),
            ("p", "不确定怎么弄的话，优先用路线一。"),
            ("warn", "不同的手机系统版本、电脑系统版本、相册设置，导出来的文件可能不一样。"
                     "本工具不能保证每种情况都能拿到完整的「图片+视频」两个文件。"),
            ("warn", "如果 iPhone 的相机设置里开了「高效」格式，导出的可能是 .heic 图片和 .mov 视频；"
                     "如果开了「兼容性优先」，可能只有 .jpg 没有视频。"
                     "没有视频 = 传到电脑后照片不会动，这是导出方式的问题，不是照片坏了。"),
            ("warn", "用微信等聊天工具传照片，通常只传静态图片、丢掉动态，不建议用这种方式备份实况照片。"),
            ("p", "本步需要手动：全部由用户完成。"),
        ],
        "next": "下一步：检查导入结果",
    },
    {
        "title": "扫描一下，看看传全了没有",
        "blocks": [
            ("p", "1. 回到本工具主窗口，点「照片文件夹」旁边的「浏览」，选中刚才照片导入到的文件夹。"),
            ("p", "2. 点绿色按钮「只读预览」——它会扫描这个文件夹（包括子文件夹），"
                  "然后在浏览器里打开一个预览页。放心，这一步只是看，不会复制、不会修改你的任何文件。"),
            ("p", "3. 扫描完，回到本工具窗口看统计结果："),
            ("li", "完整配对 — 图片和视频都找到了，这张照片的动态保住了 → 不用管，等备份"),
            ("li", "待确认 — 同一个名字的文件出现了好几份，程序不敢替你做主 → 点进预览页逐组核对，留下要的那份"),
            ("li", "不完整 — 当前配对规则下未找到可匹配的关联文件（只有图或只有视频），"
                   "程序不能判断文件是否损坏 → 先别删任何文件！"),
            ("li", "失败 — 个别文件读不出来 → 看操作日志里的具体原因"),
            ("warn", "实况照片 = 一张静态图 + 一小段视频，两个文件名字相同。程序只按文件名配对，"
                     "它只能告诉你「按当前配对规则没有找到匹配的关联文件」，不能判断文件是不是坏了。"),
            ("warn", "遇到「不完整」，通常是导入的时候只传了一半（比如某些网盘默认不传视频）。"
                     "建议：换个方式重新导一次（优先数据线），然后再扫一遍。"),
            ("warn", "也可能是你自己把某张普通照片和某个视频放在了一起凑巧同名——在预览页点开看一眼就能确认。"),
            ("p", "本步：选目录、点预览 = 用户手动；扫描、配对、分类 = 程序自动。"),
        ],
        "next": "下一步：先预览，再备份",
    },
    {
        "title": "最后一步——先看，再存，后删",
        "blocks": [
            ("h", "第①看"),
            ("p", "在预览页（浏览器里）点几张照片，确认动态正常播放。"
                  "有的视频在浏览器里可能放不出来（提示编码不支持），不代表文件坏了，备份后原文件还在。"),
            ("h", "第②存"),
            ("p", "1. 在主窗口选好「备份输出到」的文件夹（建议 D 盘，别和照片文件夹选同一个）。"),
            ("p", "2. 点「开始备份」，会弹出确认框告诉你：备份多少张、存到哪里、大概需要多少空间。确认后才开始。"),
            ("p", "3. 备份完成后，窗口里会出现「打开备份目录」的快捷入口。"),
            ("h", "第③删（最关键的一句）"),
            ("key", "打开备份目录，随机点开几张照片确认能正常打开之后，才考虑删除电脑或手机上的原文件。"
                    "没验证过备份，一个原文件都别删。"),
            ("warn", "备份前确认目标硬盘剩余空间够（确认框会帮你估算）。"),
            ("warn", "重复备份不会重复转换，已经处理过的照片会自动跳过。"),
            ("warn", "本工具预览时从不修改你的原照片；备份只是「复制」，原文件始终留在原地，直到你自己动手删。"),
            ("p", "本步：选输出目录、点备份、确认 = 用户手动；复制 / 转 GIF / 生成网页 = 程序自动。"),
        ],
        "next": "完成，去扫描",
    },
]

WIZARD_B_GOALS = [
    ("A", "保留原始素材", "图片和视频两个文件都原样传过去，以后随时可以找回完整动态",
     "想长期归档、以后可能换回 iPhone 的人"),
    ("B", "方便看动态", "转成 GIF 动图传过去，点开就动，任何手机都能看",
     "主要想给家人朋友看「会动的照片」的人"),
    ("C", "传视频版动态", "把原始视频文件传到手机，用手机播放器看完整动态",
     "在意画质、想保留原始视频的人"),
    ("D", "只要静态照片", "只要那张主图，动态无所谓",
     "只是要普通照片的人"),
]

WIZARD_B_GOAL_TEXT = {
    "A": [
        ("h", "怎么做"),
        ("p", "把备份输出目录里「原始文件」文件夹中的成对文件（同一个名字的 .heic 图 + .mov 视频）一起传到手机。"),
        ("ok", "程序支持：已实现——备份时已把成对原文件复制到「原始文件\\」，直接传即可。"),
        ("p", "优点：素材最完整、画质无损；两个文件都在，随时能找回动态。"),
        ("warn", "限制（必须告知）：安卓相册通常把它们当两个独立文件——图库里看到的是一张静态图，"
                 "视频要单独点开播。不能像 iPhone 那样按住就出动态。"),
    ],
    "B": [
        ("h", "怎么做"),
        ("p", "把备份输出目录里「GIF动图」文件夹中的 .gif 文件传到手机。"),
        ("ok", "程序支持：已实现——备份时勾选「转为 GIF 动图」即可生成。"),
        ("p", "优点：任何安卓手机、任何相册都能直接看动态，还能发微信（注意微信可能再次压缩）。"),
        ("warn", "限制（必须告知）：GIF 画质和色彩比原片差（GIF 格式天生只有 256 色）、每张约 2MB、"
                 "无声（实况本来也无声）；它是「模仿动态」，不是实况照片本身。"),
    ],
    "C": [
        ("h", "怎么做"),
        ("p", "你的电脑上已经有原始视频文件（.mov 或 .mp4），把它传到手机就能用手机播放器看完整动态。"),
        ("warn", "本工具不能把视频单独转成其他格式（如 mp4 转码），它只会「原样复制」。"
                 ".mov 文件大部分安卓手机的视频播放器能直接放；如果放不了，装一个免费播放器（如 VLC）即可。"),
        ("warn", "视频方案看到的动态和实况照片的「按住播放」体验不一样，它就是一段普通视频。"),
        ("ok", "程序支持：部分——只支持「原样复制」.mov/.mp4 文件（复制 ≠ 格式转换，文件内容一个字节都不变）；"
               "不支持任何格式转换（本轮不实现、不提供按钮）。"),
        ("p", "优点：动态完整、画质无损。"),
        ("warn", "限制：图库里可能缩略图空白或被当成普通视频；.mov 兼容性看具体手机。"),
    ],
    "D": [
        ("h", "怎么做"),
        ("p", "直接传「原始文件」里的 .heic 图——但注意：很多安卓手机打不开 .heic。"),
        ("warn", "如果打不开，说明你的导出方式给的是 HEIC 格式；最省事的办法是在 iPhone 上重新导出 JPG，"
                 "或用电脑工具转换。本工具不做图片格式转换（未实现，不提供按钮）。"),
    ],
}

WIZARD_B_ROUTES = [
    ("1. 数据线", "手机用数据线连电脑 → 手机弹窗选「文件传输 / MTP」→ "
                  "在电脑「此电脑」里打开手机存储 → 把文件复制进去", "最直接，速度最快，推荐"),
    ("2. 局域网 / 本地工具", "你如果已经在用本地网络传输方式（如路由器自带的共享、SMB、"
                            "你熟悉的免费局域网工具），按它的说明传", "不想插线"),
    ("3. 云盘 / 同步盘", "传到你在用的云盘，手机端再下载", "文件多、两台设备不在身边"),
]

WIZARD_B_CHECKS = [
    "文件都传完了：手机上看到的文件数量 = 电脑上选中的数量",
    "静态图能打开：随机点 3 张图，都能显示",
    "动态能播放：目标 B（GIF）点开就动；目标 A / C（原始文件）的 .mov 视频能用手机播放器播放",
    "（仅目标 A）明白：图库里看到静态图是正常的，动态在单独的视频文件里",
]

WIZARD_B_RULES = [
    "手机上「只看到静态图片」≠ 文件损坏，多数是安卓相册不认实况格式。"
    "本工具不能保证安卓手机图库把传过去的文件识别为原生实况照片——"
    "原生识别取决于手机系统与图库对相应格式及关联机制的支持，与文件本身无关。",
    "未经验证的备份不能作为删除原文件的依据：手机上验证通过之前，不要删电脑上的备份；"
    "电脑备份验证通过之前，不要删 iPhone / 电脑上的原文件。一层一层来。",
    "传完先别清空回收站 / 云盘回收站，万一传坏了还有救。",
]


# ---------- 图形界面 ----------

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import tkinter.font as tkfont

FONTS = {}

FIRST_RUN_DIR_NAME = "LivePhotoBackupViewer"
FIRST_RUN_FLAG_NAME = "first_run_v12.flag"


def _pick_font_family(root):
    """按 02 号 §2.1 的优先级挑一个系统自带中文字体。"""
    try:
        families = set(tkfont.families(root))
    except Exception:
        families = set()
    for fam in ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei"):
        if fam in families:
            return fam
    return "TkDefaultFont"


def init_fonts(root):
    """集中定义字体（02 号 §2）：全局统一引用，不再散落各控件。"""
    global FONTS
    fam = _pick_font_family(root)

    def f(size, weight="normal", underline=False):
        return tkfont.Font(root=root, family=fam, size=size, weight=weight, underline=underline)

    FONTS = {
        "h1": f(16, "bold"),
        "h2": f(12, "bold"),
        # 02 号 §2.2 规定 h3 = 10.5pt；Tk 的 font -size 只接受整数，故取 10pt（视觉差异可忽略）
        "h3": f(10, "bold"),
        "body": f(10),
        "body_bold": f(10, "bold"),
        "caption": f(9),
        "caption_bold": f(9, "bold"),
        "stat": f(20, "bold"),
        "link": f(9, "normal", True),
    }
    return FONTS


def make_card(parent):
    """伪卡片：白底 + 1px 直角边框（02 号 §5）。"""
    return tk.Frame(parent, bg=C["surface"], highlightthickness=1,
                    highlightbackground=C["border"])


def make_link(parent, text, command, color=None):
    """文字链接（02 号 §4.2）。"""
    lbl = tk.Label(parent, text=text, bg=parent.cget("bg"), fg=color or C["primary"],
                   font=FONTS["link"], cursor="hand2")
    lbl.bind("<Button-1>", lambda e: command())
    return lbl


def primary_button(parent, text, command, green=False, compact=False):
    """主按钮：蓝（备份）/ 绿（预览）；40px 高大按钮或紧凑按钮。"""
    return tk.Button(
        parent, text=text, command=command,
        bg=C["preview_green"] if green else C["primary"],
        fg="#FFFFFF",
        activebackground=C["preview_green_hover"] if green else C["primary_hover"],
        activeforeground="#FFFFFF", disabledforeground="#FFFFFF",
        font=FONTS["body_bold"], relief="flat", bd=0, highlightthickness=0,
        padx=16 if compact else 24, pady=7 if compact else 13, cursor="hand2")


def secondary_button(parent, text, command):
    """次按钮：白底 1px 灰边。"""
    return tk.Button(
        parent, text=text, command=command,
        bg=C["surface"], fg=C["text_primary"],
        activebackground=C["window_alt"], activeforeground=C["text_primary"],
        disabledforeground=C["disabled_fg"],
        font=FONTS["body"], relief="flat", bd=0, highlightthickness=1,
        highlightbackground=C["border"], highlightcolor=C["primary"],
        padx=16, pady=8, cursor="hand2")


def enable_btn(btn, enabled, kind="primary"):
    """按 02 号 §4.2 切换按钮的启用/禁用外观。

    tk.Button 没有 -disabledbackground 选项，禁用态底色只能通过重新设置
    background 实现，故统一走本函数，避免各处自行 configure 走样。
    """
    if enabled:
        if kind == "green":
            btn.configure(state="normal", bg=C["preview_green"], fg="#FFFFFF",
                          activebackground=C["preview_green_hover"], activeforeground="#FFFFFF")
        elif kind == "primary":
            btn.configure(state="normal", bg=C["primary"], fg="#FFFFFF",
                          activebackground=C["primary_hover"], activeforeground="#FFFFFF")
        else:
            btn.configure(state="normal", bg=C["surface"], fg=C["text_primary"],
                          activebackground=C["window_alt"], activeforeground=C["text_primary"])
    else:
        if kind == "secondary":
            btn.configure(state="disabled", bg=C["disabled_bg"], fg=C["disabled_fg"],
                          disabledforeground=C["disabled_fg"])
        else:
            btn.configure(state="disabled", bg="#B9C4D4", fg="#FFFFFF",
                          disabledforeground="#FFFFFF")


def _trunc(s, n):
    s = str(s)
    return s if len(s) <= n else s[:n - 1] + "…"


def _log_tag(msg):
    """日志行 → 颜色标签（02 号 §6 / 03 号 §6：仅加颜色，日志内容不变）。"""
    if msg.startswith("[成功]"):
        return "ok"
    if msg.startswith("[失败]") or msg.startswith("[封面失败]"):
        return "fail"
    if msg.startswith("[警告]") or msg.startswith("[已取消]"):
        return "warn"
    if msg.startswith("[提示]"):
        return "dim"
    return "info"


def first_run_flag_path():
    """首次启动向导的标记文件路径（Q6：落盘、只弹一次）。"""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    try:
        d = os.path.join(base, FIRST_RUN_DIR_NAME)
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, FIRST_RUN_FLAG_NAME)
    except Exception:
        return None


class Badge(tk.Frame):
    """状态徽章：颜色 + 符号 + 文字 三重编码（02 号 §6）。"""

    def __init__(self, parent, kind="neutral", text=""):
        fg, bg, bd, sym = STATUS[kind]
        super().__init__(parent, bg=bg, highlightthickness=1, highlightbackground=bd)
        self._label = tk.Label(self, text="", bg=bg, fg=fg, font=FONTS["body"])
        self._label.pack(padx=6, pady=1)
        self.set(kind, text)

    def set(self, kind, text):
        fg, bg, bd, sym = STATUS[kind]
        self.configure(bg=bg, highlightbackground=bd)
        self._label.configure(bg=bg, fg=fg, text=text)


class ModalDialog(tk.Toplevel):
    """统一风格的自定义弹窗。

    tkinter 原生 messagebox 只能给出「是 / 否 / 确定」，无法提供设计要求的
    「继续等待 / 安全取消并退出」「重新选择」「我已确认，继续备份」等按钮文案，
    因此统一使用本控件承载 06 号文案清单的四要素与按钮规范。
    """

    def __init__(self, parent, title, body, buttons, default=0, width=520):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=C["window"])
        self.resizable(False, False)
        self.transient(parent)
        self.result = None

        tk.Label(self, text=title, font=FONTS["h2"], bg=C["window"],
                 fg=C["text_primary"], anchor="w").pack(fill="x", padx=SP["card_in"],
                                                        pady=(SP["card_in"], SP["ctrl"]))
        tk.Label(self, text=body, font=FONTS["body"], bg=C["window"], fg=C["text_primary"],
                 justify="left", anchor="w", wraplength=width - 2 * SP["card_in"]).pack(
            fill="x", padx=SP["card_in"], pady=(0, SP["card_in"]))

        row = tk.Frame(self, bg=C["window"])
        row.pack(fill="x", padx=SP["card_in"], pady=(0, SP["card_in"]))
        for label, value, kind in reversed(buttons):
            if kind == "primary":
                btn = primary_button(row, label, lambda v=value: self.close(v), compact=True)
            else:
                btn = secondary_button(row, label, lambda v=value: self.close(v))
            btn.pack(side="right", padx=(SP["ctrl"], 0))

        self.bind("<Return>", lambda e: self.close(buttons[default][1]))
        self.bind("<Escape>", lambda e: self.close(None))
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.update_idletasks()
        x = parent.winfo_rootx() + max(0, (parent.winfo_width() - self.winfo_width()) // 2)
        y = parent.winfo_rooty() + max(0, (parent.winfo_height() - self.winfo_height()) // 2)
        self.geometry(f"+{x}+{y}")
        self.grab_set()
        self.focus_set()
        self.wait_window()

    def close(self, value=None):
        if self.result is None:
            self.result = value
        try:
            self.grab_release()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass


class SummaryDialog(tk.Toplevel):
    """备份摘要二次确认（06 号 #8 前置；07 号 D-4 五要素、D-11 返回修改）。"""

    def __init__(self, app, src, dst, keep_raw, make_gif, make_html, space):
        super().__init__(app.root)
        self.app = app
        self.src = src
        self.dst = dst
        self.result = None
        self.title("确认开始备份")
        self.configure(bg=C["window"])
        self.resizable(False, False)
        self.transient(app.root)
        self.protocol("WM_DELETE_WINDOW", self._close)

        tk.Label(self, text="确认开始备份", font=FONTS["h2"], bg=C["window"],
                 fg=C["text_primary"], anchor="w").pack(fill="x", padx=SP["card_in"],
                                                        pady=(SP["card_in"], SP["ctrl"]))
        card = make_card(self)
        card.pack(fill="x", padx=SP["card_in"])
        inner = tk.Frame(card, bg=C["surface"])
        inner.pack(fill="x", padx=SP["card_in"], pady=SP["card_in"])

        self.v_content = self._row(inner, "备份内容", "正在统计…")
        self.v_target = self._row(inner, "备份到", dst)
        self.v_space = self._row(inner, "预计占用空间", self._space_text(space))
        self.v_raw = self._row(
            inner, "原始文件",
            "保留（原样复制图片+视频）" if keep_raw
            else "不保留（备份里将没有原始文件，无法长期归档）")
        self.v_check = self._row(inner, "空间检查", self._check_text(space))
        self.v_opts = self._row(inner, "本次选项",
                                self._opts_text(keep_raw, make_gif, make_html))
        tk.Label(self, text="确认后才会开始备份。备份只是「复制」，你的原始照片始终留在原地。",
                 font=FONTS["caption"], bg=C["window"], fg=C["text_tertiary"],
                 anchor="w").pack(fill="x", padx=SP["card_in"], pady=(SP["ctrl"], 0))

        row = tk.Frame(self, bg=C["window"])
        row.pack(fill="x", padx=SP["card_in"], pady=(SP["card_in"], SP["card_in"]))
        self.btn_go = primary_button(row, "开始备份", self._start, compact=True)
        enable_btn(self.btn_go, False, "primary")
        self.btn_go.pack(side="right", padx=(SP["ctrl"], 0))
        self.btn_back = secondary_button(row, "返回修改", self._close)
        self.btn_back.pack(side="right")

        self.update_idletasks()
        x = app.root.winfo_rootx() + max(0, (app.root.winfo_width() - self.winfo_width()) // 2)
        y = app.root.winfo_rooty() + max(0, (app.root.winfo_height() - self.winfo_height()) // 2)
        self.geometry(f"+{x}+{y}")
        self.grab_set()
        threading.Thread(target=self._compute, daemon=True).start()
        self.wait_window()

    # ---------- 内部 ----------
    def _row(self, parent, label, value):
        r = tk.Frame(parent, bg=C["surface"])
        r.pack(fill="x", pady=2)
        tk.Label(r, text=label, font=FONTS["caption"], bg=C["surface"], fg=C["text_secondary"],
                 width=10, anchor="w").pack(side="left")
        v = tk.Label(r, text=value, font=FONTS["body"], bg=C["surface"], fg=C["text_primary"],
                     anchor="w", justify="left")
        v.pack(side="left", fill="x", expand=True, padx=(SP["ctrl"], 0))
        return v

    @staticmethod
    def _space_text(space):
        state = (space or {}).get("state", "none")
        if state == "ok":
            need = format_bytes(space.get("need"))
            free = space.get("free")
            if free is None:
                return f"预计需要 {need}（目标盘可用空间未确认）"
            return f"预计需要 {need}（目标盘可用 {format_bytes(free)}）"
        if state == "timeout":
            return "未完成检查（目录过大已跳过）"
        if state == "error":
            return "检查失败（可能无读取权限）"
        return "未检查"

    @staticmethod
    def _check_text(space):
        state = (space or {}).get("state", "none")
        return {"ok": "已完成", "timeout": "未完成（超时）", "error": "失败"}.get(state, "未检查")

    @staticmethod
    def _opts_text(keep_raw, make_gif, make_html):
        parts = []
        parts.append("保留原始双件套 ✓" if keep_raw else "保留原始双件套 ✗")
        parts.append("转 GIF ✓" if make_gif else "转 GIF ✗")
        parts.append("生成网页 ✓" if make_html else "生成网页 ✗")
        return " · ".join(parts)

    def _compute(self):
        try:
            pairs = find_live_photos(self.src)
            done = load_done(self.dst)
            skipped = 0
            for p in pairs:
                key = (os.path.splitext(os.path.basename(p["video_path"].lower()))[0]
                       + "|" + os.path.dirname(p["video_path"]))
                if key in done and done[key]:
                    skipped += 1
            self.app.q.put(("summary", (self, len(pairs), skipped, None)))
        except Exception as e:
            self.app.q.put(("summary", (self, 0, 0, str(e))))

    def apply_stats(self, total, skipped, err):
        if err:
            self.v_content.configure(text=f"统计失败：{err}")
        else:
            self.v_content.configure(
                text=f"本次将备份 {total} 组实况照片（跳过 {skipped} 组 · 新增 {max(0, total - skipped)} 组）")
        try:
            enable_btn(self.btn_go, True, "primary")
        except Exception:
            pass

    def _start(self):
        self.result = "start"
        self._close()

    def _close(self):
        if self.result is None:
            self.result = "back"
        try:
            self.grab_release()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass


class WizardA(tk.Toplevel):
    """iPhone 导入 Windows 操作向导（04 号文档）。"""

    def __init__(self, parent, start_step=0, on_finish=None):
        super().__init__(parent)
        self.title("使用帮助 · 把照片导入电脑")
        self.configure(bg=C["window"])
        self.geometry("520x560")
        self.minsize(480, 520)
        self.transient(parent)
        self.step = max(0, min(len(WIZARD_A_STEPS) - 1, start_step))
        self.on_finish = on_finish
        self.protocol("WM_DELETE_WINDOW", self._close)

        self.head = tk.Label(self, text="", font=FONTS["caption"], bg=C["window"],
                             fg=C["text_secondary"], anchor="w")
        self.head.pack(fill="x", padx=SP["card_in"], pady=(SP["card_in"], SP["ctrl"]))
        self.title_lbl = tk.Label(self, text="", font=FONTS["h2"], bg=C["window"],
                                  fg=C["text_primary"], anchor="w", justify="left", wraplength=460)
        self.title_lbl.pack(fill="x", padx=SP["card_in"])
        self.body = tk.Text(self, bg=C["surface"], fg=C["text_primary"], font=FONTS["body"],
                            relief="flat", bd=0, highlightthickness=0, wrap="word",
                            spacing1=4, spacing3=4, state="disabled")
        self.body.pack(fill="both", expand=True, padx=SP["card_in"], pady=(SP["ctrl"], 0))
        self.body.tag_configure("p", font=FONTS["body"], foreground=C["text_primary"],
                                lmargin1=0, lmargin2=10)
        self.body.tag_configure("h", font=FONTS["body_bold"], foreground=C["text_primary"],
                                lmargin1=0, lmargin2=10, spacing1=8)
        self.body.tag_configure("li", font=FONTS["body"], foreground=C["text_secondary"],
                                lmargin1=10, lmargin2=10)
        self.body.tag_configure("warn", font=FONTS["body"], foreground=C["warning"],
                                background=C["warning_bg"], lmargin1=0, lmargin2=10,
                                spacing1=8, spacing3=8)
        self.body.tag_configure("ok", font=FONTS["body"], foreground=C["success"],
                                background=C["success_bg"], lmargin1=0, lmargin2=10,
                                spacing1=8, spacing3=8)
        self.body.tag_configure("key", font=FONTS["body_bold"], foreground=C["uncertain"],
                                background=C["uncertain_bg"], lmargin1=0, lmargin2=10,
                                spacing1=8, spacing3=8)

        row = tk.Frame(self, bg=C["window"])
        row.pack(fill="x", padx=SP["card_in"], pady=(SP["ctrl"], SP["card_in"]))
        self.btn_next = primary_button(row, "下一步", self._next, compact=True)
        self.btn_next.pack(side="right")
        self.btn_prev = secondary_button(row, "上一步", self._prev)
        self.btn_prev.pack(side="right", padx=(0, SP["ctrl"]))
        self.btn_close = secondary_button(row, "关闭", self._close)
        self.btn_close.pack(side="left")
        self._render()

    def _render(self):
        step = WIZARD_A_STEPS[self.step]
        n = len(WIZARD_A_STEPS)
        dots = " ".join("●" if i <= self.step else "○" for i in range(n))
        self.head.configure(text=f"[ 第 {self.step + 1} 步 / 共 {n} 步 ]    {dots}")
        self.title_lbl.configure(text=step["title"])
        self.body.configure(state="normal")
        self.body.delete("1.0", tk.END)
        for tag, text in step["blocks"]:
            self.body.insert(tk.END, text + "\n", tag)
        self.body.configure(state="disabled")
        enable_btn(self.btn_prev, self.step > 0, "secondary")
        self.btn_next.configure(text=step["next"])

    def _next(self):
        if self.step >= len(WIZARD_A_STEPS) - 1:
            self._finish()
            return
        self.step += 1
        self._render()

    def _prev(self):
        if self.step > 0:
            self.step -= 1
            self._render()

    def _finish(self):
        self._close()
        if self.on_finish:
            try:
                self.on_finish()
            except Exception:
                pass

    def _close(self):
        try:
            self.destroy()
        except Exception:
            pass


class WizardB(tk.Toplevel):
    """备份与安卓手机传输操作向导（05 号文档）。"""

    TITLES = ["你想在安卓手机上得到什么？", "方案与限制", "怎么传到手机",
              "先确认能打开，再谈删原文件"]

    def __init__(self, parent, on_finish=None):
        super().__init__(parent)
        self.title("使用帮助 · 传到安卓手机")
        self.configure(bg=C["window"])
        self.geometry("520x560")
        self.minsize(480, 520)
        self.transient(parent)
        self.step = 0
        self.goal = "A"
        self.on_finish = on_finish
        self.protocol("WM_DELETE_WINDOW", self._close)

        self.head = tk.Label(self, text="", font=FONTS["caption"], bg=C["window"],
                             fg=C["text_secondary"], anchor="w")
        self.head.pack(fill="x", padx=SP["card_in"], pady=(SP["card_in"], SP["ctrl"]))
        self.title_lbl = tk.Label(self, text="", font=FONTS["h2"], bg=C["window"],
                                  fg=C["text_primary"], anchor="w", justify="left", wraplength=460)
        self.title_lbl.pack(fill="x", padx=SP["card_in"])
        self.content = tk.Frame(self, bg=C["window"])
        self.content.pack(fill="both", expand=True, padx=SP["card_in"], pady=(SP["ctrl"], 0))

        row = tk.Frame(self, bg=C["window"])
        row.pack(fill="x", padx=SP["card_in"], pady=(SP["ctrl"], SP["card_in"]))
        self.btn_next = primary_button(row, "下一步", self._next, compact=True)
        self.btn_next.pack(side="right")
        self.btn_prev = secondary_button(row, "上一步", self._prev)
        self.btn_prev.pack(side="right", padx=(0, SP["ctrl"]))
        self.btn_close = secondary_button(row, "关闭", self._close)
        self.btn_close.pack(side="left")
        self._render()

    # ---------- 渲染 ----------
    def _render(self):
        for child in self.content.winfo_children():
            child.destroy()
        n = len(self.TITLES)
        dots = " ".join("●" if i <= self.step else "○" for i in range(n))
        self.head.configure(text=f"[ 第 {self.step + 1} 步 / 共 {n} 步 ]    {dots}")
        self.title_lbl.configure(text=self.TITLES[self.step])
        if self.step == 0:
            self._render_goal()
        elif self.step == 1:
            self._render_blocks(WIZARD_B_GOAL_TEXT.get(self.goal, []))
        elif self.step == 2:
            self._render_routes()
        else:
            self._render_check()
        enable_btn(self.btn_prev, self.step > 0, "secondary")
        self.btn_next.configure(text="完成" if self.step == n - 1 else "下一步")

    def _text_widget(self):
        txt = tk.Text(self.content, bg=C["surface"], fg=C["text_primary"], font=FONTS["body"],
                      relief="flat", bd=0, highlightthickness=0, wrap="word",
                      spacing1=4, spacing3=4, height=14, state="disabled")
        txt.pack(fill="both", expand=True)
        txt.tag_configure("p", font=FONTS["body"], foreground=C["text_primary"],
                           lmargin1=0, lmargin2=10)
        txt.tag_configure("h", font=FONTS["body_bold"], foreground=C["text_primary"],
                           lmargin1=0, lmargin2=10, spacing1=8)
        txt.tag_configure("li", font=FONTS["body"], foreground=C["text_secondary"],
                           lmargin1=10, lmargin2=10)
        txt.tag_configure("warn", font=FONTS["body"], foreground=C["warning"],
                           background=C["warning_bg"], lmargin1=0, lmargin2=10,
                           spacing1=8, spacing3=8)
        txt.tag_configure("ok", font=FONTS["body"], foreground=C["success"],
                           background=C["success_bg"], lmargin1=0, lmargin2=10,
                           spacing1=8, spacing3=8)
        return txt

    def _render_blocks(self, blocks):
        txt = self._text_widget()
        txt.configure(state="normal")
        for tag, text in blocks:
            txt.insert(tk.END, text + "\n", tag)
        txt.configure(state="disabled")

    def _render_goal(self):
        tk.Label(self.content,
                 text="iPhone 的实况照片是苹果的专属格式（一张图 + 一段视频绑定播放）。"
                      "安卓手机的相册通常不认识这种绑定关系——传过去之后，你大概率只能看到一张静态图片。"
                      "这不是文件坏了，是安卓相册不认。所以先想清楚你要什么，再动手。",
                 font=FONTS["caption"], bg=C["window"], fg=C["text_tertiary"],
                 justify="left", anchor="w", wraplength=460).pack(
            fill="x", pady=(0, SP["ctrl"]))
        var = tk.StringVar(value=self.goal)
        var.trace_add("write", lambda *a: setattr(self, "goal", var.get()))
        for code, name, one, who in WIZARD_B_GOALS:
            card = tk.Frame(self.content, bg=C["surface"], highlightthickness=1,
                            highlightbackground=C["border"])
            card.pack(fill="x", pady=2)
            tk.Radiobutton(card, text=f"{code}. {name}", variable=var, value=code,
                           bg=C["surface"], fg=C["text_primary"], activebackground=C["surface"],
                           activeforeground=C["text_primary"], font=FONTS["body_bold"],
                           anchor="w", highlightthickness=0, bd=0, relief="flat",
                           cursor="hand2").pack(anchor="w", padx=SP["ctrl"], pady=(SP["ctrl"], 0))
            tk.Label(card, text=one, font=FONTS["caption"], bg=C["surface"], fg=C["text_secondary"],
                     anchor="w", justify="left", wraplength=400).pack(fill="x", padx=SP["ctrl"])
            tk.Label(card, text=f"适合：{who}", font=FONTS["caption"], bg=C["surface"],
                     fg=C["text_tertiary"], anchor="w", justify="left", wraplength=400).pack(
                fill="x", padx=SP["ctrl"], pady=(0, SP["ctrl"]))

    def _render_routes(self):
        txt = self._text_widget()
        txt.configure(state="normal")
        for title, how, who in WIZARD_B_ROUTES:
            txt.insert(tk.END, title + "\n", "h")
            txt.insert(tk.END, how + "\n", "li")
            txt.insert(tk.END, "适合：" + who + "\n", "li")
        txt.insert(tk.END, "⚠ 注意事项\n", "h")
        txt.insert(tk.END, "不假设你装了某个特定 App；上面只列「类型」，具体以你手机和已有服务为准。\n", "warn")
        txt.insert(tk.END, "传输大视频时保持手机亮屏、别断线（MTP 传输中断最常见）。\n", "warn")
        txt.insert(tk.END, "用微信 / QQ 传 GIF 可以，但传原始 .mov / .heic 会被压缩甚至改格式，"
                           "传输原始素材请走数据线或云盘。\n", "warn")
        txt.configure(state="disabled")

    def _render_check(self):
        tk.Label(self.content, text="核对清单（勾选式，仅作阅读辅助，不会保存）：",
                 font=FONTS["caption"], bg=C["window"], fg=C["text_secondary"],
                 anchor="w").pack(fill="x", pady=(0, SP["ctrl"]))
        for item in WIZARD_B_CHECKS:
            tk.Checkbutton(self.content, text=item, bg=C["surface"], fg=C["text_primary"],
                           activebackground=C["surface"], activeforeground=C["text_primary"],
                           font=FONTS["caption"], anchor="w", highlightthickness=0,
                           bd=0, relief="flat", cursor="hand2").pack(fill="x", pady=1)
        tk.Label(self.content, text="⚠ 三条铁律", font=FONTS["body_bold"], bg=C["window"],
                 fg=C["warning"], anchor="w").pack(fill="x", pady=(SP["ctrl"], 2))
        for rule in WIZARD_B_RULES:
            tk.Label(self.content, text="· " + rule, font=FONTS["caption"], bg=C["window"],
                     fg=C["text_secondary"], anchor="w", justify="left",
                     wraplength=440).pack(fill="x", pady=2)

    # ---------- 翻页 ----------
    def _next(self):
        if self.step >= len(self.TITLES) - 1:
            self._close()
            if self.on_finish:
                try:
                    self.on_finish()
                except Exception:
                    pass
            return
        self.step += 1
        self._render()

    def _prev(self):
        if self.step > 0:
            self.step -= 1
            self._render()

    def _close(self):
        try:
            self.destroy()
        except Exception:
            pass


class App:
    """V1.2 主窗口（03 号《主窗口布局与组件说明》六区信息架构）。"""

    def __init__(self, root):
        self.root = root
        init_fonts(root)
        root.title("实况照片备份查看器 V1.3")
        root.geometry("860x680")
        root.minsize(760, 600)
        root.configure(bg=C["window"])
        self.q = queue.Queue()

        self._cancel_requested = False
        self._backup_running = False
        self._preview_running = False
        self._close_after_cancel = False
        self._scan_state = "idle"
        self._stats = {}
        self._groups = []
        self._failed_names = []
        self._preview_html = ""
        self._last_dst = ""
        self._space = {"state": "none", "need": 0, "free": None, "pairs": 0, "key": None}
        self._space_token = 0
        self._space_job = None
        self._spin_job = None
        self._spin_count = 0
        self._spin_base = ""
        self._stat_cols = 0
        self._opt_expanded = False
        self._dir_text = ""
        self._space_text = ""
        self._dir_color = C["text_secondary"]
        self._space_color = C["text_secondary"]
        self._cur_tab = "backup"
        self._syncing_source = False
        self.album_host = None
        if album_host is not None:
            try:
                self.album_host = album_host.AlbumHost(
                    root, on_album_error=self._on_album_error)
            except Exception:
                self.album_host = None

        self.keep = tk.BooleanVar(value=True)
        self.gif = tk.BooleanVar(value=True)
        self.webb = tk.BooleanVar(value=True)

        self._build_ui()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.bind("<Alt-b>", lambda e: self.start())
        root.bind("<Alt-p>", lambda e: self.start_preview())
        self.backup_btn.configure(underline=0)
        self.prev_btn.configure(underline=0)
        self.root.after(120, self._poll)
        self.root.after(500, self.maybe_show_first_run)

    # ================= 界面构建 =================
    def _build_ui(self):
        try:
            style = ttk.Style(self.root)
            style.theme_use("clam")
            style.configure("LP.Horizontal.TProgressbar", troughcolor=C["window_alt"],
                            background=C["primary"], bordercolor=C["border"],
                            lightcolor=C["primary"], darkcolor=C["primary"], thickness=8)
        except Exception:
            pass
        # V1.3：主窗口改为「备份 / 相册」双页签（V1.3 03 号 §一）。
        # 「备份」页内部控件 / 布局 / 文案与 V1.2 完全一致，仅可视高度 −32px（页签条占位）。
        self._build_tabbar(self.root)
        self.pages = tk.Frame(self.root, bg=C["window"])
        self.pages.pack(fill="both", expand=True)
        self.page_backup = tk.Frame(self.pages, bg=C["window"])
        self.page_album = tk.Frame(self.pages, bg=C["window"])
        self.page_backup.pack(fill="both", expand=True)

        outer = tk.Frame(self.page_backup, bg=C["window"])
        outer.pack(fill="both", expand=True, padx=SP["win"], pady=SP["win"])

        # 上部内容区（可滚动）：实际 tkinter 控件高度超过设计稿的 564px 预算，
        # 若不提供滚动，最小尺寸 760x600 下内容会被裁切（违反 G-2），故此处可滚动。
        mid = tk.Frame(outer, bg=C["window"])
        mid.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(mid, bg=C["window"], highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.vbar = ttk.Scrollbar(mid, orient="vertical", command=self.canvas.yview)
        self.vbar_visible = False
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.content = tk.Frame(self.canvas, bg=C["window"])
        self._content_win = self.canvas.create_window((0, 0), window=self.content, anchor="nw")
        self.content.bind("<Configure>", self._on_content_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self._build_header(self.content)
        self._build_dirs(self.content)
        self._build_result(self.content)
        self._build_actions(self.content)
        self._build_help(self.content)
        self._build_log(outer)
        self._bind_wheel(self.content)

        # V1.3：「相册」页（内嵌 WebView2，首次切入时懒启动）
        self.album_frame = tk.Frame(self.page_album, bg=C["window"])
        self.album_frame.pack(fill="both", expand=True)
        if self.album_host is not None:
            try:
                self.album_host.frame = self.album_frame
            except Exception:
                pass

        # V1.3：源目录 / 输出目录双向同步（复核裁定 P-1：仅同步显示，不触发扫描或备份）
        try:
            self.src_var.trace_add("write", self._on_src_changed_v13)
            self.dst_var.trace_add("write", self._on_dst_changed_v13)
        except Exception:
            pass
        self._on_dst_changed_v13()

    # ================= V1.3 页签 =================

    def _build_tabbar(self, parent):
        """页签条（06 号 §二：高 32px，选中页签顶部 2px 主色指示条）。"""
        bar = tk.Frame(parent, bg=C["window"], height=32)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)
        self._tab_bar = bar
        self._tab_inds = {}
        self._tab_labels = {}
        self._tab_frames = {}
        for key, text in (("backup", "备份"), ("album", "相册")):
            f = tk.Frame(bar, bg=C["window"])
            f.pack(side="left", fill="y")
            ind = tk.Frame(f, bg=C["primary"], height=2)
            lbl = tk.Label(f, text=text, bg=C["window"], fg=C["text_secondary"],
                           font=FONTS["body"], padx=16, cursor="hand2")
            lbl.pack(fill="both", expand=True)
            for w in (f, lbl):
                w.bind("<Button-1>", lambda e, k=key: self._switch_tab(k))
            self._tab_inds[key] = ind
            self._tab_labels[key] = lbl
            self._tab_frames[key] = f
        # 初始选中「备份」
        self._tab_inds["backup"].pack(fill="x", side="top", before=self._tab_labels["backup"])
        self._tab_labels["backup"].configure(bg=C["surface"], fg=C["text_primary"],
                                             font=FONTS["body_bold"])
        self._tab_frames["backup"].configure(bg=C["surface"])

    def _switch_tab(self, key):
        """切换页签（仅容器显隐，不重排「备份」页任何控件）。"""
        if key == getattr(self, "_cur_tab", "backup"):
            return
        self._cur_tab = key
        for k, lbl in self._tab_labels.items():
            ind = self._tab_inds[k]
            if k == key:
                ind.pack(fill="x", side="top", before=lbl)
                lbl.configure(bg=C["surface"], fg=C["text_primary"], font=FONTS["body_bold"])
                self._tab_frames[k].configure(bg=C["surface"])
            else:
                ind.pack_forget()
                lbl.configure(bg=C["window"], fg=C["text_secondary"], font=FONTS["body"])
                self._tab_frames[k].configure(bg=C["window"])
        if key == "album":
            self.page_backup.pack_forget()
            self.page_album.pack(fill="both", expand=True)
            if self.album_host is not None:
                try:
                    self.album_host.ensure_started()
                except Exception as e:
                    self._log("[相册] 启动失败: %s" % e)
        else:
            # V1.3 修复：离开相册页时停播并释放 <video>，避免后台继续解码
            if self.album_host is not None:
                try:
                    self.album_host.stop_playback()
                except Exception:
                    pass
            self.page_album.pack_forget()
            self.page_backup.pack(fill="both", expand=True)

    # ================= V1.3 源目录 / 输出目录同步 =================

    def _on_src_changed_v13(self, *_args):
        """备份页改源目录 → 同步到相册页（仅显示同步，不触发扫描/备份）。"""
        if getattr(self, "_syncing_source", False) or self.album_host is None:
            return
        try:
            path = self.src_var.get().strip().strip('"')
        except Exception:
            return
        self.album_host.set_source(path)
        api = getattr(self.album_host, "api", None)
        if api is not None:
            try:
                api.sync_source_path(path)
            except Exception:
                pass

    def _on_dst_changed_v13(self, *_args):
        """备份页改输出目录 → 告知相册页（索引与缓存落在此目录）。"""
        if self.album_host is None:
            return
        try:
            self.album_host.set_output_dir(self.dst_var.get().strip().strip('"'))
        except Exception:
            pass

    def _lp_set_source_display(self, path):
        """相册页改路径 → 回填备份页输入框（不触发扫描/备份）。"""
        try:
            self._syncing_source = True
            self.src_var.set(path)
        except Exception:
            pass
        finally:
            self._syncing_source = False

    def _lp_show_wizard(self):
        """相册页请求打开使用向导。"""
        try:
            self._open_help()
        except Exception:
            pass

    def _on_album_error(self, msg):
        try:
            self._log("[相册] " + str(msg))
        except Exception:
            pass

    def _on_content_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._sync_vbar()

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._content_win, width=event.width)
        self._sync_vbar()

    def _sync_vbar(self):
        try:
            bb = self.canvas.bbox("all")
            need = bb is not None and (bb[3] - bb[1]) > (self.canvas.winfo_height() + 2)
        except Exception:
            need = False
        if need and not self.vbar_visible:
            self.vbar.pack(side="right", fill="y")
            self.vbar_visible = True
        elif not need and self.vbar_visible:
            self.vbar.pack_forget()
            self.vbar_visible = False

    def _bind_wheel(self, widget):
        try:
            widget.bind("<MouseWheel>", self._on_wheel)
            for child in widget.winfo_children():
                self._bind_wheel(child)
        except Exception:
            pass

    def _on_wheel(self, event):
        try:
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass

    def _build_header(self, parent):
        hdr = tk.Frame(parent, bg=C["window"])
        hdr.pack(fill="x", pady=(0, SP["section"]))
        left = tk.Frame(hdr, bg=C["window"])
        left.pack(side="left", fill="x", expand=True)
        row = tk.Frame(left, bg=C["window"])
        row.pack(anchor="w")
        tk.Label(row, text="实况照片备份查看器", font=FONTS["h1"], bg=C["window"],
                 fg=C["text_primary"]).pack(side="left")
        ver = tk.Frame(row, bg=C["neutral_bg"], highlightthickness=1,
                       highlightbackground=C["neutral_bd"])
        ver.pack(side="left", padx=(SP["inline"], 0))
        tk.Label(ver, text="V1.2", font=FONTS["caption"], bg=C["neutral_bg"],
                 fg=C["neutral"]).pack(padx=5, pady=1)
        tk.Label(left, text="备份 iPhone 实况照片，让动态永远不丢", font=FONTS["caption"],
                 bg=C["window"], fg=C["text_secondary"]).pack(anchor="w", pady=(2, 0))
        make_link(hdr, "? 使用帮助", self._open_help).pack(side="right", anchor="ne")

    def _build_dirs(self, parent):
        card = make_card(parent)
        card.pack(fill="x", pady=(0, SP["section"]))
        inner = tk.Frame(card, bg=C["surface"])
        inner.pack(fill="x", padx=SP["card_in"], pady=SP["card_in"])

        row1 = tk.Frame(inner, bg=C["surface"])
        row1.pack(fill="x", pady=(0, SP["ctrl"]))
        tk.Label(row1, text="照片文件夹", font=FONTS["body"], bg=C["surface"],
                 fg=C["text_primary"], width=9, anchor="e").pack(side="left")
        self.src_var = tk.StringVar()
        self.dst_var = tk.StringVar()
        self.src = tk.Entry(row1, font=FONTS["body"], bg=C["surface"], fg=C["text_primary"],
                            textvariable=self.src_var,
                            relief="flat", highlightthickness=1, highlightbackground=C["border"],
                            highlightcolor=C["primary"], insertbackground=C["text_primary"])
        self.src.pack(side="left", fill="x", expand=True, padx=SP["ctrl"])
        secondary_button(row1, "浏览", self._pick_src).pack(side="left")
        self.src_badge = Badge(row1, "idle", "○ 未开始")
        self.src_badge.pack(side="left", padx=(SP["ctrl"], 0))

        row2 = tk.Frame(inner, bg=C["surface"])
        row2.pack(fill="x", pady=(0, SP["ctrl"]))
        tk.Label(row2, text="备份输出到", font=FONTS["body"], bg=C["surface"],
                 fg=C["text_primary"], width=9, anchor="e").pack(side="left")
        self.dst = tk.Entry(row2, font=FONTS["body"], bg=C["surface"], fg=C["text_primary"],
                            textvariable=self.dst_var,
                            relief="flat", highlightthickness=1, highlightbackground=C["border"],
                            highlightcolor=C["primary"], insertbackground=C["text_primary"])
        self.dst.pack(side="left", fill="x", expand=True, padx=SP["ctrl"])
        secondary_button(row2, "浏览", self._pick_dst).pack(side="left")

        tk.Label(inner, text="重复备份会自动跳过已处理的照片 · "
                              "建议备份完成并抽查后，再删除电脑或手机上的原文件",
                 font=FONTS["caption"], bg=C["surface"], fg=C["text_tertiary"],
                 anchor="w").pack(fill="x")
        self.dir_msg = tk.Label(inner, text="", font=FONTS["caption"], bg=C["surface"],
                                fg=C["text_secondary"], anchor="w")
        self.space_msg = tk.Label(inner, text="", font=FONTS["caption"], bg=C["surface"],
                                  fg=C["text_secondary"], anchor="w")
        # 两行提示默认不占位，由 _set_captions 按需显示（空行会白白吃掉约 15px 高度）

        self.src_var.trace_add("write", self._on_paths_changed)
        self.dst_var.trace_add("write", self._on_paths_changed)

    def _build_result(self, parent):
        self.result_host = tk.Frame(parent, bg=C["window"])
        self.result_host.pack(fill="x", pady=(0, SP["section"]))

        self.empty_card = make_card(self.result_host)
        einner = tk.Frame(self.empty_card, bg=C["surface"])
        einner.pack(padx=SP["card_in"], pady=SP["card_in"])
        tk.Label(einner, text="还没有扫描", font=FONTS["h3"], bg=C["surface"],
                 fg=C["text_secondary"]).pack()
        tk.Label(einner, text="选好上面的照片文件夹后，点「只读预览」—— 只看不动你的文件",
                 font=FONTS["caption"], bg=C["surface"], fg=C["text_tertiary"]).pack(
            pady=(SP["line"], 0))

        self.scan_frame = tk.Frame(self.result_host, bg=C["window"])
        self.stats_host = tk.Frame(self.scan_frame, bg=C["window"])
        self.stats_host.pack(fill="x")
        self.stats_host.bind("<Configure>", self._on_stats_resize)
        self._stat_cards = []
        spec = [("total", "发现照片", "共发现 0 组照片", "neutral"),
                ("complete", "完整配对", "图和视频都在，可以直接备份", "success"),
                ("previewable", "可预览", "点「只读预览」就能在浏览器里看动态", "progress"),
                ("uncertain", "待确认", "同名文件多于一组，需要你人工看一眼", "uncertain"),
                ("incomplete", "不完整", "只有图或只有视频，先别急着删原文件", "warning"),
                ("failed", "失败", "个别文件读不出来，详情看日志", "danger")]
        for key, lbl, why, color in spec:
            card = make_card(self.stats_host)
            num = tk.Label(card, text="0", font=FONTS["stat"], bg=C["surface"], fg=C[color])
            num.pack(anchor="w")
            tk.Label(card, text=lbl, font=FONTS["body"], bg=C["surface"],
                     fg=C["text_primary"]).pack(anchor="w")
            why_lbl = tk.Label(card, text=why, font=FONTS["caption"], bg=C["surface"],
                               fg=C["text_secondary"], justify="left", anchor="w",
                               wraplength=110)
            why_lbl.pack(anchor="w", fill="x", pady=(2, 0))
            self._stat_cards.append({"key": key, "card": card, "num": num, "why": why_lbl})

        self.next_band = tk.Frame(self.scan_frame, bg=C["progress_bg"], highlightthickness=1,
                                  highlightbackground=C["progress_bd"])
        self.next_band.pack(fill="x", pady=(SP["ctrl"], 0))
        self.next_lbl = tk.Label(self.next_band, text="", font=FONTS["body"],
                                 bg=C["progress_bg"], fg=C["progress"], anchor="w",
                                 justify="left", wraplength=760)
        self.next_lbl.pack(fill="x", padx=SP["ctrl"], pady=SP["line"])

        self.folds_host = tk.Frame(self.scan_frame, bg=C["window"])
        self.folds_host.pack(fill="x")
        self.fold_uncertain = self._make_fold(self.folds_host, "uncertain", "待确认", "uncertain")
        self.fold_incomplete = self._make_fold(self.folds_host, "warning", "不完整", "incomplete")
        self.fold_failed = self._make_fold(self.folds_host, "danger", "失败", "failed")
        for fold in (self.fold_uncertain, self.fold_incomplete, self.fold_failed):
            fold["frame"].pack(fill="x", pady=(0, 4))

        link_row = tk.Frame(self.scan_frame, bg=C["window"])
        link_row.pack(fill="x", pady=(2, 0))
        make_link(link_row, "在预览页查看全部 →", self._open_preview_page).pack(side="left")

    def _make_fold(self, parent, kind, title, data_key):
        frame = tk.Frame(parent, bg=C["surface"], highlightthickness=1,
                         highlightbackground=C["border"])
        head = tk.Frame(frame, bg=C["window"])
        head.pack(fill="x", padx=SP["ctrl"], pady=SP["line"])
        badge = Badge(head, kind, f"{STATUS[kind][3]} {title} 0")
        badge.pack(side="left")
        toggle = tk.Label(head, text="▸ 展开", font=FONTS["caption"], bg=C["window"],
                           fg=C["primary"], cursor="hand2")
        toggle.pack(side="left", padx=(SP["ctrl"], 0))
        body = tk.Frame(frame, bg=C["surface"])
        fold = {"kind": kind, "title": title, "data_key": data_key,
                "frame": frame, "badge": badge,
                "toggle": toggle, "body": body, "items": [], "expanded": False}
        toggle.bind("<Button-1>", lambda e, f=fold: self._toggle_fold(f))
        return fold

    def _build_actions(self, parent):
        card = make_card(parent)
        card.pack(fill="x", pady=(0, SP["section"]))
        inner = tk.Frame(card, bg=C["surface"])
        inner.pack(fill="x", padx=SP["card_in"], pady=SP["card_in"])

        acts = tk.Frame(inner, bg=C["surface"])
        acts.pack(fill="x")
        col1 = tk.Frame(acts, bg=C["surface"])
        col1.pack(side="left")
        self.prev_btn = primary_button(col1, "只读预览", self.start_preview, green=True)
        self.prev_btn.pack(anchor="w")
        tk.Label(col1, text="在浏览器看动态，不改动、不复制任何文件", font=FONTS["caption"],
                 bg=C["surface"], fg=C["text_tertiary"]).pack(anchor="w", pady=(2, 0))
        col2 = tk.Frame(acts, bg=C["surface"])
        col2.pack(side="left", padx=(SP["ctrl"], 0))
        self.backup_btn = primary_button(col2, "开始备份", self.start)
        self.backup_btn.pack(anchor="w")
        tk.Label(col2, text="原样复制图片+视频，可同时生成 GIF 和网页", font=FONTS["caption"],
                 bg=C["surface"], fg=C["text_tertiary"]).pack(anchor="w", pady=(2, 0))

        self.opts = tk.Frame(inner, bg=C["surface"])
        self.opts.pack(fill="x", pady=(SP["ctrl"], 0))
        self.opt_summary = tk.Label(self.opts, text="", font=FONTS["caption"], bg=C["surface"],
                                    fg=C["text_secondary"], cursor="hand2", anchor="w")
        self.opt_summary.pack(fill="x")
        self.opt_summary.bind("<Button-1>", self._toggle_opts)
        self.opt_body = tk.Frame(self.opts, bg=C["surface"])
        self._build_opt_body()
        self._update_opt_summary()

        self._build_task_card(inner)

    def _build_opt_body(self):
        def add_row(text, var, note=None, warn=None):
            r = tk.Frame(self.opt_body, bg=C["surface"])
            r.pack(fill="x", anchor="w", pady=1)
            tk.Checkbutton(r, text=text, variable=var, bg=C["surface"], fg=C["text_primary"],
                           activebackground=C["surface"], activeforeground=C["text_primary"],
                           font=FONTS["caption"], anchor="w", highlightthickness=0,
                           bd=0, relief="flat", cursor="hand2").pack(side="left")
            w = None
            if note:
                tk.Label(r, text=note, font=FONTS["caption"], bg=C["surface"],
                         fg=C["text_tertiary"], anchor="w").pack(side="left", padx=(4, 0))
            if warn:
                w = tk.Label(r, text=warn, font=FONTS["caption"], bg=C["surface"],
                             fg=C["warning"], anchor="w")
            var.trace_add("write", lambda *a: self._on_opt_changed())
            return w

        self.keep_warn = add_row(
            "保留原始双件套（图片+视频原样保存）", self.keep, None,
            "⚠ 关掉后备份里将没有原始文件，以后无法找回动态，不建议关闭")
        add_row("转为 GIF 动图", self.gif, "——每张约 2MB，任何电脑双击就能看动态")
        add_row("生成网页查看器", self.webb, "——像手机相册一样翻看，悬停自动播放")

    def _build_task_card(self, parent):
        self.task = tk.Frame(parent, bg=C["surface"], highlightthickness=1,
                             highlightbackground=C["border"])
        head = tk.Frame(self.task, bg=C["surface"])
        head.pack(fill="x", padx=SP["card_in"], pady=(SP["ctrl"], 0))
        self.task_name = tk.Label(head, text="正在备份", font=FONTS["body_bold"],
                                  bg=C["surface"], fg=C["text_primary"])
        self.task_name.pack(side="left")
        self.cancel_btn = secondary_button(head, "取消备份", self._on_cancel_click)
        self.cancel_btn.pack(side="right", padx=(0, SP["ctrl"]))
        self.task_badge = Badge(head, "progress", "● 备份中…")
        self.task_badge.pack(side="right")

        self.task_run_box = tk.Frame(self.task, bg=C["surface"])
        self.task_bar = ttk.Progressbar(self.task_run_box, style="LP.Horizontal.TProgressbar",
                                        maximum=100, value=0)
        self.task_bar.pack(fill="x", pady=(SP["ctrl"], 0))
        self.task_detail = tk.Label(self.task_run_box, text="", font=FONTS["caption"],
                                    bg=C["surface"], fg=C["text_tertiary"], anchor="w")
        self.task_detail.pack(fill="x", pady=(2, 0))
        self.task_hint = tk.Label(self.task_run_box,
                                  text="当前这张做完后停止，已完成的保留",
                                  font=FONTS["caption"], bg=C["surface"],
                                  fg=C["text_tertiary"], anchor="w")
        self.task_hint.pack(fill="x", pady=(2, 0))

        self.task_done_box = tk.Frame(self.task, bg=C["surface"])
        self.task_summary = tk.Label(self.task_done_box, text="", font=FONTS["caption"],
                                     bg=C["surface"], fg=C["text_secondary"], anchor="w",
                                     justify="left")
        self.task_summary.pack(fill="x", pady=(SP["ctrl"], 0))
        self.task_actions = tk.Frame(self.task_done_box, bg=C["surface"])
        self.task_actions.pack(fill="x")
        self.task_note = tk.Label(self.task_done_box, text="", font=FONTS["caption"],
                                  bg=C["surface"], fg=C["warning"], anchor="w", justify="left")
        self.task_note.pack(fill="x", pady=(6, 0))

    def _build_help(self, parent):
        host = tk.Frame(parent, bg=C["window"])
        host.pack(fill="x", pady=(0, SP["section"]))
        host.columnconfigure(0, weight=1)
        host.columnconfigure(1, weight=1)
        items = [("▸", "把照片导入电脑", "数据线 / iCloud 两条路线怎么选",
                  lambda: self._open_wizard_a(0)),
                 ("?", "「待确认」「不完整」是什么意思", "看懂扫描结果的每个标记",
                  lambda: self._open_wizard_a(2)),
                 ("✓", "安全备份三步走", "先预览 → 再备份 → 抽查后再删原文件",
                  lambda: self._open_wizard_a(3)),
                 ("↗", "传到安卓手机", "四种传法与各自的限制",
                  lambda: self._open_wizard_b())]
        for i, (icon, title, desc, cmd) in enumerate(items):
            card = tk.Frame(host, bg=C["surface"], highlightthickness=1,
                            highlightbackground=C["border"], cursor="hand2")
            card.grid(row=i // 2, column=i % 2, sticky="nsew",
                      padx=(0 if i % 2 == 0 else SP["ctrl"] // 2, SP["ctrl"] // 2),
                      pady=(0, SP["ctrl"] // 2))
            card.bind("<Button-1>", lambda e, c=cmd: c())
            tk.Label(card, text=icon, font=FONTS["h3"], bg=C["surface"], fg=C["primary"],
                     width=2).pack(side="left", padx=(SP["ctrl"], 0), pady=SP["ctrl"])
            box = tk.Frame(card, bg=C["surface"])
            box.pack(side="left", fill="x", expand=True, padx=(0, SP["ctrl"]), pady=SP["ctrl"])
            tk.Label(box, text=title, font=FONTS["caption_bold"], bg=C["surface"],
                     fg=C["text_primary"], anchor="w").pack(fill="x")
            tk.Label(box, text=desc, font=FONTS["caption"], bg=C["surface"],
                     fg=C["text_tertiary"], anchor="w").pack(fill="x")
        tk.Label(parent, text="更多问题？查看随附的《使用说明.txt》", font=FONTS["caption"],
                 bg=C["window"], fg=C["text_tertiary"], anchor="w").pack(fill="x")

    def _build_log(self, parent):
        card = make_card(parent)
        card.pack(fill="x", pady=(SP["section"], 0))
        head = tk.Frame(card, bg=C["surface"])
        head.pack(fill="x", padx=SP["card_in"], pady=(SP["ctrl"], 0))
        tk.Label(head, text="操作日志", font=FONTS["h3"], bg=C["surface"],
                 fg=C["text_primary"]).pack(side="left")
        self.clear_link = make_link(head, "清空", self._clear_log)
        self.clear_link.pack(side="right")
        body = tk.Frame(card, bg=C["window_alt"])
        body.pack(fill="both", expand=True, padx=SP["card_in"], pady=(SP["ctrl"], SP["card_in"]))
        self.log = tk.Text(body, height=8, state="disabled", bg=C["window_alt"],
                           fg=C["text_secondary"], font=FONTS["caption"], relief="flat",
                           bd=0, highlightthickness=0, spacing1=2, spacing3=2, wrap="word")
        self.log.pack(side="left", fill="both", expand=True, padx=SP["ctrl"], pady=SP["ctrl"])
        sb = ttk.Scrollbar(body, orient="vertical", command=self.log.yview)
        sb.pack(side="right", fill="y", pady=SP["ctrl"])
        self.log.configure(yscrollcommand=sb.set)
        for tag, color in (("ok", C["success"]), ("fail", C["danger"]),
                           ("warn", C["warning"]), ("dim", C["text_tertiary"]),
                           ("info", C["text_secondary"])):
            self.log.tag_configure(tag, foreground=color)

    # ================= 交互：目录与行内校验 =================
    def _pick_src(self):
        d = filedialog.askdirectory(title="选择包含实况照片的文件夹")
        if d:
            self.src.delete(0, tk.END)
            self.src.insert(0, d)
            self.src.focus_set()

    def _pick_dst(self):
        d = filedialog.askdirectory(title="选择输出备份的文件夹")
        if d:
            self.dst.delete(0, tk.END)
            self.dst.insert(0, d)
            self.dst.focus_set()

    def _on_paths_changed(self, *args):
        self._validate_paths()
        if self._space_job:
            try:
                self.root.after_cancel(self._space_job)
            except Exception:
                pass
        self._space_job = self.root.after(900, self._schedule_space_check)

    def _validate_paths(self):
        src = self.src.get().strip().strip('"')
        dst = self.dst.get().strip().strip('"')
        msg = ""
        bad_src = False
        if src and not os.path.isdir(src):
            msg = "这个文件夹不存在，请重新选择"
            bad_src = True
        elif src and dst:
            rel = check_path_relation(src, dst)
            if rel["status"] == "same":
                msg = "备份位置不能和照片位置相同，请换一个输出文件夹"
            elif rel["status"] in ("out_in_src", "src_in_out"):
                msg = "备份位置不能放在照片文件夹里面（或反过来），请换一个输出文件夹"
            elif rel["status"] == "unknown":
                msg = "无法确认两个文件夹的关系，请重新选择"
        self._dir_text = msg
        self._dir_color = C["danger"] if msg else C["text_secondary"]
        self._sync_captions()
        self.src.configure(highlightbackground=C["danger"] if bad_src else C["border"])

    def _sync_captions(self):
        """按「校验提示 → 空间提示」的固定顺序显示两行行内提示，空行不占高度。"""
        for child in (self.dir_msg, self.space_msg):
            child.pack_forget()
        if self._dir_text:
            self.dir_msg.configure(text=self._dir_text, fg=self._dir_color)
            self.dir_msg.pack(fill="x")
        if self._space_text:
            self.space_msg.configure(text=self._space_text, fg=self._space_color)
            self.space_msg.pack(fill="x")

    # ================= 交互：空间预检 =================
    @staticmethod
    def _space_key(src, dst):
        try:
            return (os.path.normcase(os.path.abspath(src)),
                    os.path.normcase(os.path.abspath(dst)))
        except Exception:
            return (str(src), str(dst))

    def _schedule_space_check(self):
        self._space_job = None
        src = self.src.get().strip().strip('"')
        dst = self.dst.get().strip().strip('"')
        if not src or not os.path.isdir(src) or not dst:
            self._space = {"state": "none", "need": 0, "free": None, "pairs": 0, "key": None}
            self._render_space()
            return
        key = self._space_key(src, dst)
        self._space_token += 1
        token = self._space_token
        include_gif = bool(self.gif.get())
        self._space_text = "正在检查目标盘剩余空间…"
        self._space_color = C["text_tertiary"]
        self._sync_captions()

        def work():
            st = estimate_backup_size(src, timeout=SPACE_CHECK_TIMEOUT, include_gif=include_gif)
            try:
                free = check_free_space(dst)
            except Exception:
                free = None
            self.q.put(("space", (token, key, st, free)))

        threading.Thread(target=work, daemon=True).start()

    def _on_space_result(self, payload):
        token, key, st, free = payload
        if token != self._space_token:
            return
        self._space = {"state": st["state"], "need": st["need"], "free": free,
                       "pairs": st.get("pairs", 0), "key": key}
        self._render_space()

    def _render_space(self):
        sp = self._space
        state = sp["state"]
        text = ""
        color = C["text_secondary"]
        if state == "ok":
            need = format_bytes(sp["need"])
            if sp["free"] is None:
                text = f"预计需要 {need} · 目标盘可用空间未确认，请自行确认磁盘剩余空间"
                color = C["warning"]
            elif sp["need"] > sp["free"]:
                text = f"预计需要 {need} · 目标盘可用 {format_bytes(sp['free'])}（空间不足 ⚠）"
                color = C["warning"]
            else:
                text = f"预计需要 {need} · 目标盘可用 {format_bytes(sp['free'])}"
                color = C["text_secondary"]
        elif state == "timeout":
            text = "空间检查未完成（目录过大已跳过），开始备份前请自行确认磁盘剩余空间"
            color = C["warning"]
        elif state == "error":
            text = "空间检查失败（可能无读取权限），请自行确认磁盘剩余空间"
            color = C["warning"]
        self._space_text = text
        self._space_color = color
        self._sync_captions()

    def _refresh_space_blocking(self, src, dst):
        """开始备份时再确认一次空间（超时/失败必须明确标注，不得静默放行）。"""
        key = self._space_key(src, dst)
        sp = self._space
        if sp["state"] == "ok" and sp["key"] == key:
            return
        self._space_text = "正在检查目标盘剩余空间…"
        self._space_color = C["text_tertiary"]
        self._sync_captions()
        self.root.update_idletasks()
        include_gif = bool(self.gif.get())
        st = estimate_backup_size(src, timeout=SPACE_CHECK_TIMEOUT, include_gif=include_gif)
        try:
            free = check_free_space(dst)
        except Exception:
            free = None
        self._space = {"state": st["state"], "need": st["need"], "free": free,
                       "pairs": st.get("pairs", 0), "key": key}
        self._render_space()

    # ================= 交互：只读预览 =================
    def start_preview(self):
        if self._preview_running or self._backup_running:
            return
        src = self.src.get().strip().strip('"')
        if not src or not os.path.isdir(src):
            self._notice(COPY["no_src"]["title"], COPY["no_src"]["body"],
                         COPY["no_src"]["btn"], after=lambda: self.src.focus_set())
            return
        self._preview_running = True
        self._scan_state = "scanning"
        enable_btn(self.prev_btn, False, "green")
        self.prev_btn.configure(text="预览中…")
        self.src_badge.set("progress", "● 扫描中")
        self._start_spin("扫描中")
        self._set_next("正在扫描照片文件夹（会自动包含子文件夹）。大文件夹会多等一会儿，"
                       "扫完会自动在浏览器打开预览页。", "progress")
        threading.Thread(target=self._work_preview, args=(src,), daemon=True).start()

    def _work_preview(self, src):
        failed_names = []

        def logger(m):
            if m.startswith("[封面失败]"):
                failed_names.append(m[len("[封面失败]"):].split(":")[0].strip())
            self._log(m)

        try:
            stats = run_preview(src, log=logger)
            groups = scan_groups(src)
            html_path = os.path.join(PREVIEW_TEMP_DIR, "index.html") if PREVIEW_TEMP_DIR else ""
            self.q.put(("done_preview", (stats, groups, failed_names, None, html_path)))
        except Exception as e:
            self._log("预览发生错误: " + str(e))
            self.q.put(("done_preview", (None, [], [], str(e), "")))

    def _on_preview_done(self, payload):
        stats, groups, failed_names, err, html_path = payload
        self._preview_running = False
        enable_btn(self.prev_btn, True, "green")
        self.prev_btn.configure(text="只读预览")
        self._stop_spin()
        if err:
            self._scan_state = "idle"
            self.src_badge.set("danger", "✕ 预览失败")
            self._set_next(f"预览失败：{err}。源目录未被改动，可以重试。", "danger")
            return
        self.src_badge.set("success", "✓ 已扫描")
        self._scan_state = "scanned"
        self._stats = stats or {}
        self._groups = groups or []
        self._failed_names = failed_names or []
        self._preview_html = html_path or ""
        self._render_stats()
        self._render_folds()
        self.empty_card.pack_forget()
        self.scan_frame.pack(fill="x")
        self._update_next_step()

    # ================= 交互：扫描结果展示 =================
    def _render_stats(self):
        s = self._stats or {}
        for item in self._stat_cards:
            key = item["key"]
            val = s.get(key, 0) or 0
            item["num"].configure(text=str(val))
            if key == "total":
                item["why"].configure(text=f"共发现 {val} 组照片")

    def _update_next_step(self):
        if self._scan_state == "scanning":
            self._set_next("正在扫描照片文件夹（会自动包含子文件夹）。大文件夹会多等一会儿，"
                           "扫完会自动在浏览器打开预览页。", "progress")
            return
        if self._scan_state != "scanned":
            if self.src.get().strip():
                self._set_next("照片文件夹已选好。建议先点「只读预览」看看里面有什么、"
                               "配对是否完整，再决定备份。", "info")
            else:
                self._set_next("第一步：选好照片文件夹，点「只读预览」看看扫描结果", "info")
            return
        s = self._stats or {}
        uncertain = s.get("uncertain", 0) or 0
        incomplete = s.get("incomplete", 0) or 0
        failed = s.get("failed", 0) or 0
        tail = f"（另有 {failed} 组处理失败，详情看日志）" if failed else ""
        if uncertain:
            self._set_next(f"⚠ 有 {uncertain} 组同名照片需要你确认，"
                           f"建议先点开预览页逐组核对，再决定是否备份{tail}", "warn")
        elif incomplete:
            self._set_next(f"⚠ 有 {incomplete} 组文件不完整（缺图或缺视频）。"
                           f"程序不会判断文件损坏，建议检查导入方式后重新扫描{tail}", "warn")
        else:
            self._set_next(f"✓ 全部配对完整，可以放心点「开始备份」{tail}", "ok")

    def _set_next(self, text, kind="info"):
        style = {"info": (C["progress_bg"], C["progress"], C["progress_bd"]),
                 "warn": (C["uncertain_bg"], C["uncertain"], C["uncertain_bd"]),
                 "ok": (C["success_bg"], C["success"], C["success_bd"]),
                 "danger": (C["danger_bg"], C["danger"], C["danger_bd"])}
        bg, fg, bd = style.get(kind, style["info"])
        self.next_band.configure(bg=bg, highlightbackground=bd)
        self.next_lbl.configure(text=text, bg=bg, fg=fg)

    def _render_folds(self):
        data = {
            "uncertain": [(g["name"], self._group_sub(g))
                          for g in self._groups if g["status"] == "uncertain"],
            "incomplete": [(g["name"], self._group_sub(g))
                           for g in self._groups if g["status"] == "incomplete"],
            "failed": [(n, "视频文件读不出来，详情见下方操作日志") for n in self._failed_names],
        }
        for fold in (self.fold_uncertain, self.fold_incomplete, self.fold_failed):
            fold["items"] = data[fold["data_key"]]
            sym = STATUS[fold["kind"]][3]
            fold["badge"].set(fold["kind"], f"{sym} {fold['title']} {len(fold['items'])}")
            self._render_fold_body(fold)

    def _render_fold_body(self, fold):
        for child in fold["body"].winfo_children():
            child.destroy()
        if not fold["expanded"]:
            fold["body"].pack_forget()
            return
        items = fold["items"]
        if not items:
            tk.Label(fold["body"], text="没有", font=FONTS["caption"], bg=C["surface"],
                     fg=C["text_tertiary"]).pack(anchor="w", padx=SP["ctrl"], pady=2)
            fold["body"].pack(fill="x")
            return
        sym = STATUS[fold["kind"]][3]
        shown = items if fold["expanded"] else items[:6]
        for name, sub in shown:
            row = tk.Frame(fold["body"], bg=C["surface"])
            row.pack(fill="x", padx=SP["ctrl"], pady=2)
            Badge(row, fold["kind"], f"{sym} {fold['title']}").pack(side="left")
            tk.Label(row, text=_trunc(name, 26), font=FONTS["caption"], bg=C["surface"],
                     fg=C["text_primary"], anchor="w").pack(side="left", padx=(SP["ctrl"], 0))
            tk.Label(row, text=sub, font=FONTS["caption"], bg=C["surface"],
                     fg=C["text_tertiary"], anchor="w").pack(side="left", padx=(SP["ctrl"], 0))
        if not fold["expanded"] and len(items) > 6:
            make_link(fold["body"], f"查看全部 {len(items)} 条",
                      lambda f=fold: self._toggle_fold(f)).pack(anchor="w", padx=SP["ctrl"])
        fold["body"].pack(fill="x")

    def _toggle_fold(self, fold):
        fold["expanded"] = not fold["expanded"]
        fold["toggle"].configure(text="▾ 收起" if fold["expanded"] else "▸ 展开")
        self._render_fold_body(fold)

    @staticmethod
    def _group_sub(g):
        if g["status"] == "uncertain":
            paths = g["photos"] or g["videos"]
            d = os.path.basename(os.path.dirname(paths[0])) if paths else ""
            return f"同名 {len(g['photos'])} 图 {len(g['videos'])} 视频 · 位于「{d}」"
        if g["status"] == "incomplete":
            return "只有图片，没有同名视频" if g["photos"] else "只有视频，没有同名图片"
        return ""

    def _on_stats_resize(self, event):
        width = event.width
        cols = 6 if width >= 6 * 120 + 5 * SP["ctrl"] else 3
        if cols == self._stat_cols:
            return
        self._stat_cols = cols
        for i, item in enumerate(self._stat_cards):
            r, c = divmod(i, cols)
            item["card"].grid(row=r, column=c, sticky="nsew",
                              padx=(0, SP["ctrl"] // 2), pady=(0, SP["ctrl"] // 2))
        for c in range(6):
            self.stats_host.columnconfigure(c, weight=1 if c < cols else 0)

    # ================= 交互：备份选项 =================
    def _toggle_opts(self):
        self._opt_expanded = not self._opt_expanded
        if self._opt_expanded:
            self.opt_body.pack(fill="x", pady=(4, 0))
        else:
            self.opt_body.pack_forget()
        self._update_opt_summary()

    def _update_opt_summary(self):
        if self._opt_expanded:
            self.opt_summary.configure(text="▾ 备份选项（点击收起）")
            return
        parts = ["保留原图和视频 ✓" if self.keep.get() else "保留原图和视频 ✗",
                 "转 GIF ✓" if self.gif.get() else "转 GIF ✗",
                 "生成网页 ✓" if self.webb.get() else "生成网页 ✗"]
        self.opt_summary.configure(text="▸ 备份选项（当前：" + " · ".join(parts) + "）")

    def _on_opt_changed(self):
        self._update_opt_summary()
        try:
            if self.keep.get():
                self.keep_warn.pack_forget()
            else:
                self.keep_warn.pack(side="left", padx=(4, 0))
        except Exception:
            pass

    # ================= 交互：备份 =================
    def start(self):
        if self._backup_running:
            return
        src = self.src.get().strip().strip('"')
        dst = self.dst.get().strip().strip('"')
        if not src or not os.path.isdir(src):
            self._notice(COPY["no_src"]["title"], COPY["no_src"]["body"],
                         COPY["no_src"]["btn"], after=lambda: self.src.focus_set())
            return
        if not dst:
            self._notice(COPY["no_dst"]["title"], COPY["no_dst"]["body"],
                         COPY["no_dst"]["btn"], after=lambda: self.dst.focus_set())
            return

        # ① 路径安全硬拦截（相同 / 互相嵌套 / 判定失败，一律停止，无绕过按钮）
        rel = check_path_relation(src, dst)
        if rel["status"] in ("same", "out_in_src", "src_in_out"):
            self._notice(COPY["path_same"]["title"], COPY["path_same"]["body"],
                         COPY["path_same"]["btn"], after=self._pick_dst)
            return
        if rel["status"] == "unknown":
            self._notice(COPY["path_unknown"]["title"], COPY["path_unknown"]["body"],
                         COPY["path_unknown"]["btn"], after=self._pick_dst)
            return

        # ② 磁盘空间预检（超时/失败必须明确标注「未完成检查」，不得误报充足）
        self._refresh_space_blocking(src, dst)
        sp = self._space
        if sp["state"] == "ok" and sp["free"] is not None and sp["need"] > sp["free"]:
            body = COPY["space_short"]["body"].format(need=format_bytes(sp["need"]),
                                                      free=format_bytes(sp["free"]))
            r = self._ask(COPY["space_short"]["title"], body,
                          [("重新选择", "reselect", "primary"), ("仍要继续", "go", "secondary")])
            if r != "go":
                self._pick_dst()
                return
        elif sp["state"] in ("timeout", "error"):
            r = self._ask(COPY["space_unknown"]["title"], COPY["space_unknown"]["body"],
                          [("回去检查空间", "back", "primary"),
                           ("我已确认，继续备份", "go", "secondary")])
            if r != "go":
                return

        # ③ 备份摘要二次确认
        keep = bool(self.keep.get())
        gif = bool(self.gif.get())
        web = bool(self.webb.get())
        dlg = SummaryDialog(self, src, dst, keep, gif, web, dict(self._space))
        if dlg.result != "start":
            return
        self._start_backup(src, dst, keep, gif, web)

    def _start_backup(self, src, dst, keep, gif, web):
        self._backup_running = True
        self._cancel_requested = False
        self._last_dst = dst
        enable_btn(self.backup_btn, False, "primary")
        self.backup_btn.configure(text="备份中…")
        enable_btn(self.prev_btn, False, "green")
        self.prev_btn.configure(text="预览不可用")
        self._show_task_running()
        threading.Thread(target=self._work_backup, args=(src, dst, keep, gif, web),
                         daemon=True).start()

    def _work_backup(self, src, dst, keep, gif, web):
        def logger(m):
            self._log(m)

        def progress(payload):
            self.q.put(("progress", payload))
            return False if self._cancel_requested else None

        try:
            process_directory(src, dst, keep_raw=keep, make_gif=gif, make_html=web,
                              log=logger, progress_cb=progress)
            self.q.put(("backup_done", (None, None)))
        except Exception as e:
            self._log("发生错误: " + str(e))
            self.q.put(("backup_done", (None, str(e))))

    def _on_progress(self, p):
        ev = p.get("event")
        total = p.get("total", 0)
        if ev == "start":
            self.task_bar.configure(maximum=max(1, total))
            self.task_bar["value"] = 0
            self.task_detail.configure(text=f"共 {total} 组 · 正在准备…")
        elif ev == "item":
            idx = p.get("index", 0)
            self.task_bar["value"] = idx + 1
            self.task_detail.configure(
                text=f"已处理 {idx + 1} / {total} 组 · 当前：{p.get('name', '')}")

    def _on_backup_done(self, payload):
        err, stats = payload
        self._backup_running = False
        enable_btn(self.backup_btn, True, "primary")
        self.backup_btn.configure(text="开始备份")
        enable_btn(self.prev_btn, True, "green")
        self.prev_btn.configure(text="只读预览")
        cancelled = self._cancel_requested
        if stats is None and not err:
            self._show_task_message("warning", "⚠ 没有可备份的内容",
                                    "未在源目录找到成对的实况照片（需要 主图+同名视频）。"
                                    "你的原始照片没有被改动。")
        elif err:
            self._show_task_message("danger", "✕ 备份失败",
                                    "备份过程中发生错误：" + err + "\n\n" + COPY["write_fail"]["body"])
        else:
            ok = stats.get("ok", 0)
            skipped = stats.get("skipped", 0)
            fail = stats.get("fail", 0)
            total = stats.get("total", 0)
            if cancelled:
                rest = max(0, total - ok - skipped - fail)
                self._show_task_done("neutral", "○ 已取消", "备份已取消",
                                     COPY["cancel_done"]["body"].format(ok=ok, rest=rest))
                self._set_next("○ 备份已取消：已完成 " + str(ok) + " 组，其余未处理，"
                               "下次备份自动续传。", "info")
            elif fail:
                self._show_task_done("warning", "⚠ 部分失败", "备份结果",
                                     COPY["backup_done"]["body"].format(ok=ok, skipped=skipped,
                                                                     fail=fail))
                self._set_next("⚠ 备份完成，但有 " + str(fail) + " 组失败（详情看日志）。"
                               "建议打开输出目录抽查几张，确认能打开后再删除原文件。", "warn")
            else:
                self._show_task_done("success", "✓ 备份完成", "备份结果",
                                     COPY["backup_done"]["body"].format(ok=ok, skipped=skipped,
                                                                     fail=fail))
                self._set_next("✓ 备份完成！建议打开输出目录抽查几张，"
                               "确认能打开后再删除电脑或手机上的原文件。", "ok")
        if self._close_after_cancel:
            self._close_after_cancel = False
            self.root.after(300, self.root.destroy)

    # ================= 任务卡 =================
    def _show_task_running(self):
        self.task.pack(fill="x", pady=(SP["ctrl"], 0))
        self.task_done_box.pack_forget()
        self.task_run_box.pack(fill="x", padx=SP["card_in"], pady=(SP["ctrl"], 0))
        self.task_name.configure(text="正在备份")
        self.task_badge.set("progress", "● 备份中…")
        enable_btn(self.cancel_btn, True, "secondary")
        self.cancel_btn.configure(text="取消备份")
        self.cancel_btn.pack(side="right", padx=(0, SP["ctrl"]))
        self.task_bar.configure(maximum=100, value=0)
        self.task_detail.configure(text="共 0 组 · 正在准备…")
        self.task_hint.configure(text="当前这张做完后停止，已完成的保留")

    def _show_task_done(self, kind, badge_text, name, summary):
        self._show_task_message(kind, badge_text, summary, name=name)
        self.task_note.configure(
            text="⚠ 建议先打开备份目录抽查几张能正常打开，再删除电脑或手机上的原文件")
        make_link(self.task_actions, "↗ 打开备份目录", self._open_backup_dir).pack(
            side="left", padx=(0, SP["ctrl"]))
        if self._last_dst and os.path.exists(os.path.join(self._last_dst, "网页查看器", "index.html")):
            make_link(self.task_actions, "↗ 打开网页查看器", self._open_backup_web).pack(side="left")

    def _show_task_message(self, kind, badge_text, summary, name="备份结果"):
        self.task.pack(fill="x", pady=(SP["ctrl"], 0))
        self.task_run_box.pack_forget()
        self.task_done_box.pack(fill="x", padx=SP["card_in"], pady=(SP["ctrl"], 0))
        self.task_name.configure(text=name)
        self.task_badge.set(kind, badge_text)
        try:
            self.cancel_btn.pack_forget()
        except Exception:
            pass
        self.task_summary.configure(text=summary)
        self.task_note.configure(text="")
        for child in self.task_actions.winfo_children():
            child.destroy()

    def _open_backup_dir(self):
        path = self._last_dst
        if not path or not os.path.isdir(path):
            self._log("[提示] 备份目录不存在，无法打开。")
            return
        try:
            os.startfile(path)
        except Exception as e:
            self._log(f"[提示] 无法打开备份目录: {e}，请手动打开: {path}")

    def _open_backup_web(self):
        path = os.path.join(self._last_dst, "网页查看器", "index.html")
        if not os.path.exists(path):
            self._log("[提示] 网页查看器尚未生成。")
            return
        try:
            webbrowser.open(path)
        except Exception as e:
            self._log(f"[提示] 无法打开网页查看器: {e}")

    def _open_preview_page(self):
        if not self._preview_html or not os.path.exists(self._preview_html):
            self._log("[提示] 预览页不存在，请重新点「只读预览」。")
            return
        try:
            webbrowser.open(self._preview_html)
        except Exception as e:
            self._log(f"[提示] 无法打开预览页: {e}")

    # ================= 取消与关闭 =================
    def _on_cancel_click(self):
        if self._cancel_requested:
            return
        r = self._ask(COPY["cancel_ask"]["title"], COPY["cancel_ask"]["body"],
                      [("继续备份", "keep", "primary"), ("确定取消", "cancel", "secondary")])
        if r == "cancel":
            self._request_cancel()

    def _request_cancel(self):
        self._cancel_requested = True
        try:
            self.task_badge.set("progress", "● 取消中")
            enable_btn(self.cancel_btn, False, "secondary")
            self.cancel_btn.configure(text="取消中…")
        except Exception:
            pass
        self._log("[提示] 已请求取消备份：当前条目处理完后停止，已完成的会保留。")

    def _on_close(self):
        if self._backup_running:
            r = self._ask(COPY["close_ask"]["title"], COPY["close_ask"]["body"],
                          [("继续等待", "wait", "primary"), ("安全取消并退出", "cancel", "secondary")])
            if r == "cancel":
                self._close_after_cancel = True
                self._request_cancel()
            return
        # V1.3：关闭前释放内嵌浏览组件（不触碰任何文件）
        if self.album_host is not None:
            try:
                self.album_host.shutdown()
            except Exception:
                pass
        self.root.destroy()

    # ================= 日志 =================
    def _log(self, msg):
        self.q.put(("log", msg))

    def _append_log(self, msg):
        self.log.configure(state="normal")
        self.log.insert(tk.END, msg + "\n", _log_tag(msg))
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    def _clear_log(self):
        if self._backup_running or self._preview_running:
            return
        self.log.configure(state="normal")
        self.log.delete("1.0", tk.END)
        self.log.configure(state="disabled")

    # ================= 状态徽章轮换 =================
    def _start_spin(self, base):
        self._spin_base = base
        self._spin_count = 0
        self._spin_tick()

    def _spin_tick(self):
        self._spin_count += 1
        dots = "." * (self._spin_count % 3 + 1)
        self.src_badge.set("progress", f"● {self._spin_base}{dots}")
        self._spin_job = self.root.after(600, self._spin_tick)

    def _stop_spin(self):
        if self._spin_job:
            try:
                self.root.after_cancel(self._spin_job)
            except Exception:
                pass
            self._spin_job = None

    # ================= 帮助与向导 =================
    def _open_help(self):
        self._open_wizard_a(0)

    def _open_wizard_a(self, step):
        WizardA(self.root, start_step=step)

    def _open_wizard_b(self):
        WizardB(self.root)

    def _after_wizard(self):
        try:
            self.root.focus_force()
            self.prev_btn.focus_set()
        except Exception:
            pass

    def maybe_show_first_run(self):
        """Q6：仅首次启动自动弹出向导一次；可关闭、不重复弹、可从帮助入口重开。"""
        path = first_run_flag_path()
        if not path or os.path.exists(path):
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("shown")
        except Exception:
            return
        WizardA(self.root, start_step=0, on_finish=self._after_wizard)

    # ================= 弹窗封装 =================
    def _notice(self, title, body, button="好的", after=None):
        ModalDialog(self.root, title, body, [(button, "ok", "primary")])
        if after:
            try:
                after()
            except Exception:
                pass

    def _ask(self, title, body, buttons):
        dlg = ModalDialog(self.root, title, body, buttons)
        return dlg.result

    # ================= 事件轮询 =================
    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._append_log(payload)
                elif kind == "space":
                    self._on_space_result(payload)
                elif kind == "progress":
                    self._on_progress(payload)
                elif kind == "done_preview":
                    self._on_preview_done(payload)
                elif kind == "backup_done":
                    self._on_backup_done(payload)
                elif kind == "summary":
                    dlg, total, skipped, err = payload
                    try:
                        if dlg.winfo_exists():
                            dlg.apply_stats(total, skipped, err)
                    except Exception:
                        pass
        except queue.Empty:
            pass
        except Exception as e:
            if sys.stdout is not None:
                import traceback
                traceback.print_exc()
            try:
                self._append_log("[警告] 界面刷新异常（不影响备份任务）: %s" % e)
            except Exception:
                pass
        self.root.after(100, self._poll)


def main():
    if "--cli" in sys.argv:
        # 命令行模式：python LivePhoto_Backup.pyw --cli 源 输出
        try:
            i = sys.argv.index("--cli")
            args = sys.argv[i + 1:]
            if len(args) < 2:
                print("用法: LivePhoto_Backup.pyw --cli <源文件夹> <输出文件夹>")
                return
            src, dst = args[0], args[1]
            print(f"源: {src}\n输出: {dst}")
            process_directory(src, dst)
            print("完成。")
        except Exception as e:
            print("错误:", e)
        return
    if "--preview" in sys.argv:
        # 只读预览命令行模式：LivePhoto_Backup.pyw --preview <源文件夹>
        try:
            i = sys.argv.index("--preview")
            args = sys.argv[i + 1:]
            if not args:
                print("用法: LivePhoto_Backup.pyw --preview <源文件夹>")
                return
            src = args[0]
            print(f"预览源: {src}")
            run_preview(src, log=print)
            print("预览完成（请查看自动打开的浏览器；若未打开，按日志提示手动打开）。")
        except Exception as e:
            print("错误:", e)
        return
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
