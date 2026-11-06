# -*- coding: utf-8 -*-
"""实况照片备份查看器 V1.3 · 媒体引擎（转码 / 封面 / 缓存 / 导出）

职责：为「相册」页提供媒体三轨兜底的 T2（转码 MP4）与 T3（GIF）落地能力，
以及安卓友好的 MP4 导出。

设计依据：``V1.3设计\\05_V1.3_播放引擎与媒体兼容规范.md``（冻结版 V1.1）
    §三 转码规格 ｜ §四 缓存策略 ｜ §五 封面抽取 ｜ §六 导出 MP4

红线约束：
    - **写入仅落输出目录**，源目录零写入（L12）；
    - **不覆盖** ``原始文件/`` 中的原片；
    - 缓存清理只作用于本工具创建的 ``播放缓存/`` 目录，绝不触碰用户文件（L4）；
    - 转码/导出失败必须**显式抛错**，由上层显式提示，不得静默降级（L14）。

本模块为 V1.3 新增代码，不属于 V1.2 的 12 个受保护函数。
"""

import hashlib
import os
import shutil
import subprocess

try:
    import imageio_ffmpeg
    FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:      # pragma: no cover - 依赖缺失时的兜底路径
    FFMPEG = "ffmpeg"

CACHE_DIRNAME = "播放缓存"
EXPORT_DIRNAME = "安卓分享"
COVER_WIDTH = 360
CRF = "22"

# 转码参数（05 号 §三）：H.264 + yuv420p + main/4.0 + faststart + AAC
_TRANSCODE_ARGS = [
    "-map", "0:v:0", "-map", "0:a:0?",
    "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
    "-c:v", "libx264", "-preset", "medium", "-crf", CRF,
    "-pix_fmt", "yuv420p", "-profile:v", "main", "-level", "4.0",
    "-movflags", "+faststart",
    "-c:a", "aac", "-b:a", "128k", "-ac", "2",
]


class MediaError(RuntimeError):
    """媒体处理失败（转码/抽帧/空间不足）。消息面向用户，不得暗示照片损坏。"""


def _run_ffmpeg(args):
    try:
        r = subprocess.run([FFMPEG, "-y", "-loglevel", "error"] + args,
                           capture_output=True, text=True)
    except FileNotFoundError:
        raise MediaError("找不到视频处理引擎，无法准备可播放版本")
    if r.returncode != 0:
        raise MediaError((r.stderr or "").strip()[:300] or "视频处理失败")
    return r


# ---------- 缓存 ----------

def cache_key(path, root=None):
    """缓存键：``sha1(相对路径|mtime_ns|size)`` 前 16 位（05 号 §四）。

    源文件改动 → mtime/size 变化 → 键变化 → 自动重新生成。
    """
    try:
        st = os.stat(path)
        mtime, size = st.st_mtime_ns, st.st_size
    except OSError:
        mtime, size = 0, 0
    try:
        rel = os.path.relpath(path, root) if root else os.path.basename(path)
    except ValueError:
        rel = os.path.basename(path)
    rel = rel.replace("\\", "/")
    h = hashlib.sha1(("%s|%d|%d" % (rel, mtime, size)).encode("utf-8")).hexdigest()
    return h[:16]


def cache_dirs(output_dir):
    base = os.path.join(os.path.abspath(output_dir), CACHE_DIRNAME)
    return (os.path.join(base, "video"), os.path.join(base, "cover"), base)


def ensure_dirs(output_dir):
    vid, cov, _ = cache_dirs(output_dir)
    os.makedirs(vid, exist_ok=True)
    os.makedirs(cov, exist_ok=True)
    return vid, cov


# ---------- 只读有效性探测 ----------

def probe_video(path, timeout=20):
    """只读探测视频，区分「文件存在 / 可读取 / 可解出画面帧」。

    返回 ``{exists, size, readable, decodable, detail, header}``。
    本函数**不宣称浏览器可播放**：codec/容器是否被 WebView2 接受只能由前端
    ``<video>`` 的 ``playing`` 事件确认（原 ``get_photo_detail`` 把
    ``can_play`` 硬编码为 True，属于未经证实的结论，已移除）。
    全程只读源文件，不写、不移动、不修改。
    """
    out = {"exists": False, "size": 0, "readable": False,
           "decodable": False, "detail": "", "header": ""}
    try:
        out["exists"] = os.path.isfile(path)
        if not out["exists"]:
            out["detail"] = "not_found"
            return out
        out["size"] = os.path.getsize(path)
    except OSError as e:
        out["detail"] = "stat_failed:%s" % e
        return out
    if out["size"] == 0:
        out["detail"] = "empty_file"
        return out
    try:
        with open(path, "rb") as fh:
            head = fh.read(32)
        out["header"] = head[4:12].decode("latin1", "replace")
    except OSError as e:
        out["detail"] = "unreadable:%s" % e
        return out
    try:
        r = subprocess.run(
            [FFMPEG, "-v", "error", "-i", path, "-frames:v", "1",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        out["detail"] = "probe_timeout"
        return out
    except FileNotFoundError:
        out["detail"] = "ffmpeg_missing"
        return out
    except Exception as e:
        out["detail"] = "probe_error:%s" % e
        return out
    err = (r.stderr or "").strip()
    if r.returncode == 0:
        out["readable"] = True
        out["decodable"] = True
        out["detail"] = "ok"
    else:
        out["readable"] = ("Invalid data found" not in err
                           and "moov atom not found" not in err)
        out["detail"] = err[:200] or "decode_failed"
    return out


# ---------- T2 转码 ----------

def transcode_to_mp4(src_video, dst_mp4):
    """把实况视频转成 H.264 MP4（安卓/微信/QQ 全兼容，05 号 §三）。

    失败抛 :class:`MediaError`，**不静默降级**。
    """
    os.makedirs(os.path.dirname(dst_mp4), exist_ok=True)
    _run_ffmpeg(["-i", src_video] + _TRANSCODE_ARGS + [dst_mp4])
    if not os.path.exists(dst_mp4) or os.path.getsize(dst_mp4) == 0:
        raise MediaError("转换没有产出文件")
    return dst_mp4


def ensure_transcoded(output_dir, video_path, root=None):
    """返回可播放的 H.264 MP4 路径（命中缓存则不重复转码）。"""
    vid_dir, _ = ensure_dirs(output_dir)
    key = cache_key(video_path, root)
    dst = os.path.join(vid_dir, key + ".mp4")
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        return dst
    return transcode_to_mp4(video_path, dst)


# ---------- 封面 ----------

def ensure_cover(output_dir, video_path, root=None, name=None):
    """抽取视频首帧作静止封面（05 号 §五）。

    优先复用备份产物 ``网页查看器/thumb/<name>.jpg``（零额外转码），
    否则写入 ``播放缓存/cover/<key>.jpg``；都失败返回 None（前端显示占位，不空白）。
    """
    if name:
        legacy = os.path.join(os.path.abspath(output_dir), "网页查看器", "thumb", name + ".jpg")
        if os.path.exists(legacy):
            return legacy
    _, cov_dir = ensure_dirs(output_dir)
    key = cache_key(video_path, root)
    dst = os.path.join(cov_dir, key + ".jpg")
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        return dst
    try:
        os.makedirs(cov_dir, exist_ok=True)
        _run_ffmpeg(["-i", video_path, "-vframes", "1",
                     "-vf", "scale=%d:-1:flags=lanczos" % COVER_WIDTH,
                     "-q:v", "4", dst])
        return dst if os.path.exists(dst) else None
    except MediaError:
        return None


# ---------- 空间预检（05 号 §四 / R-9） ----------

def rough_space_check(target_dir, need_bytes, timeout_state_unknown=False):
    """粗空间预检，返回 ``{"state": "ok"|"insufficient"|"unknown", "need": int, "free": int}``。

    预检失败/超时 → ``unknown``，**调用方必须显示「未完成空间检查」，不得静默放行**
    （V1.2 红线 L4 精神）。本函数**不删除任何文件**。
    """
    need = max(0, int(need_bytes))
    try:
        probe = os.path.abspath(target_dir)
        while probe and not os.path.isdir(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        if not os.path.isdir(probe):
            return {"state": "unknown", "need": need, "free": 0}
        free = shutil.disk_usage(probe).free
    except Exception:
        return {"state": "unknown", "need": need, "free": 0}
    if free < need:
        return {"state": "insufficient", "need": need, "free": free}
    return {"state": "ok", "need": need, "free": free}


# ---------- 导出 MP4（05 号 §六） ----------

def export_dir(output_dir):
    return os.path.join(os.path.abspath(output_dir), EXPORT_DIRNAME)


def _unique_path(directory, base_name, ext):
    """同名冲突时追加 -2、-3（05 号 §六）。"""
    cand = os.path.join(directory, base_name + ext)
    n = 2
    while os.path.exists(cand):
        cand = os.path.join(directory, "%s-%d%s" % (base_name, n, ext))
        n += 1
    return cand


def export_mp4(items, output_dir, should_cancel=None, on_progress=None):
    """批量导出安卓友好 MP4。

    ``items``：含 ``name`` / ``video_path`` 的对象序列。
    返回 ``{"files": [...], "dir": str, "skipped": [...], "cancelled": bool}``。

    - 已存在且不旧于源视频 → 跳过（"已是最新"，不重复转码）；
    - 取消 = 当前文件处理完即停（L5 无强杀）；
    - 失败抛 :class:`MediaError`（显式提示，不静默）。
    """
    outdir = export_dir(output_dir)
    os.makedirs(outdir, exist_ok=True)
    exported, skipped = [], []
    cancelled = False

    for idx, it in enumerate(items):
        if should_cancel is not None and should_cancel():
            cancelled = True
            break
        src = getattr(it, "video_path", None) or (it.get("video_path") if isinstance(it, dict) else None)
        name = getattr(it, "name", None) or (it.get("name") if isinstance(it, dict) else None)
        if not src or not os.path.exists(src):
            raise MediaError("找不到原视频文件：%s" % (name or src))

        base = name or os.path.splitext(os.path.basename(src))[0]
        dst = os.path.join(outdir, base + ".mp4")
        try:
            src_mtime = os.path.getmtime(src)
        except OSError:
            src_mtime = 0
        if os.path.exists(dst) and os.path.getsize(dst) > 0 and os.path.getmtime(dst) >= src_mtime:
            skipped.append(dst)
        else:
            transcode_to_mp4(src, dst)
            exported.append(dst)
        if on_progress is not None:
            on_progress(idx + 1, len(items), base)

    return {"files": exported, "skipped": skipped, "dir": outdir, "cancelled": cancelled}


def estimate_export_size(items):
    """粗估导出所需空间（源视频体积 × 1.3 系数，H.264 常见放大）。"""
    total = 0
    for it in items:
        src = getattr(it, "video_path", None) or (it.get("video_path") if isinstance(it, dict) else None)
        if src:
            try:
                total += os.path.getsize(src)
            except OSError:
                pass
    return int(total * 1.3) + (1 << 20)
