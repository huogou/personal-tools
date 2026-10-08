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

try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    FFMPEG = "ffmpeg"  # 兜底：如果系统自带 ffmpeg 也可用

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
  // 悬停自动播放
  document.querySelectorAll('.card').forEach(function(c){
    c.addEventListener('mouseenter', function(){ c.classList.add('playing'); });
    c.addEventListener('mouseleave', function(){ c.classList.remove('playing'); });
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


def process_directory(src_dir, output_dir, keep_raw=True, make_gif=True, make_html=True, log=print):
    """核心处理流程。返回统计信息 dict。"""
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

    for p in pairs:
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

    save_done(output_dir, done)

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


# ---------- 图形界面 ----------

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


class App:
    def __init__(self, root):
        self.root = root
        root.title("实况照片备份查看器")
        root.geometry("640x520")
        root.configure(bg="#f2f4f7")
        self.q = queue.Queue()

        pad = {"padx": 12, "pady": 6}
        tk.Label(root, text="iPhone 实况照片备份查看器", font=("Microsoft YaHei", 15, "bold"), bg="#f2f4f7").pack(anchor="w", **pad)
        tk.Label(root, text="把云盘/硬盘里‘变回静态’的实况照片，一键还原成可播放动态的备份。", bg="#f2f4f7", fg="#666").pack(anchor="w", **pad)

        frm = tk.Frame(root, bg="#f2f4f7")
        frm.pack(fill="x", **pad)
        tk.Label(frm, text="照片文件夹：", bg="#f2f4f7").pack(side="left")
        self.src = tk.Entry(frm, width=42)
        self.src.pack(side="left", padx=4)
        tk.Button(frm, text="浏览", command=self._pick_src).pack(side="left")

        frm2 = tk.Frame(root, bg="#f2f4f7")
        frm2.pack(fill="x", **pad)
        tk.Label(frm2, text="输出文件夹：", bg="#f2f4f7").pack(side="left")
        self.dst = tk.Entry(frm2, width=42)
        self.dst.pack(side="left", padx=4)
        tk.Button(frm2, text="浏览", command=self._pick_dst).pack(side="left")

        self.keep = tk.BooleanVar(value=True)
        self.gif = tk.BooleanVar(value=True)
        self.webb = tk.BooleanVar(value=True)
        opt = tk.Frame(root, bg="#f2f4f7")
        opt.pack(anchor="w", **pad)
        tk.Checkbutton(opt, text="保留原始双件套（原样复制）", variable=self.keep, bg="#f2f4f7").pack(side="left", padx=6)
        tk.Checkbutton(opt, text="转为 GIF 动图", variable=self.gif, bg="#f2f4f7").pack(side="left", padx=6)
        tk.Checkbutton(opt, text="生成网页查看器", variable=self.webb, bg="#f2f4f7").pack(side="left", padx=6)

        self.go = tk.Button(root, text="开始备份", font=("Microsoft YaHei", 12, "bold"),
                            bg="#2f6fed", fg="white", padx=20, pady=6, command=self.start)
        self.go.pack(anchor="w", **pad)

        self.prog = ttk.Progressbar(root, maximum=100)
        self.prog.pack(fill="x", **pad)

        self.log = tk.Text(root, height=12, state="disabled", bg="#0f1419", fg="#c8d0d8")
        self.log.pack(fill="both", expand=True, **pad)

        self.root.after(200, self._poll)

    def _pick_src(self):
        d = filedialog.askdirectory(title="选择包含实况照片的文件夹")
        if d:
            self.src.delete(0, tk.END)
            self.src.insert(0, d)

    def _pick_dst(self):
        d = filedialog.askdirectory(title="选择输出备份的文件夹")
        if d:
            self.dst.delete(0, tk.END)
            self.dst.insert(0, d)

    def _log(self, msg):
        self.q.put(("log", msg))

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log.configure(state="normal")
                    self.log.insert(tk.END, payload + "\n")
                    self.log.see(tk.END)
                    self.log.configure(state="disabled")
                elif kind == "done":
                    self.go.configure(state="normal", text="开始备份")
                    self.prog["value"] = 100
        except queue.Empty:
            pass
        self.root.after(200, self._poll)

    def start(self):
        src = self.src.get().strip().strip('"')
        dst = self.dst.get().strip().strip('"')
        if not src or not os.path.isdir(src):
            messagebox.showwarning("提示", "请先选择正确的照片文件夹。")
            return
        if not dst:
            messagebox.showwarning("提示", "请选择输出文件夹。")
            return
        self.go.configure(state="disabled", text="处理中…")
        self.prog["value"] = 0
        t = threading.Thread(target=self._work, args=(src, dst), daemon=True)
        t.start()

    def _work(self, src, dst):
        def logger(m):
            self._log(m)
        try:
            process_directory(src, dst, keep_raw=self.keep.get(), make_gif=self.gif.get(),
                              make_html=self.webb.get(), log=logger)
            self.q.put(("done", None))
        except Exception as e:
            self._log("发生错误: " + str(e))
            self.q.put(("done", None))


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
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
