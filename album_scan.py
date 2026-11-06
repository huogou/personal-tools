# -*- coding: utf-8 -*-
"""实况照片备份查看器 V1.3 · 源目录只读扫描模块

职责：只读遍历源目录、按同名基名配对实况照片、推导目录相册与稳定 photo_key、
并提供"拍摄时间倒序"的排序键。

设计依据：``V1.3设计\\04_V1.3_分类体系与数据规格.md``（§二 photo_key、§四 自动归类、
§五 排序 S-4）与 ``03_V1.3_客户端浏览页布局与组件.md``（§五 A2 扫描可取消）。

红线约束：
    - **只读**：本模块只调用 ``os.scandir/os.stat``，**绝不写入源目录**（L12）；
    - **配对规则不变**：与 V1.2 ``scan_groups`` 同为"同名基名（忽略大小写）"配对，
      只取"图片 + 视频"都存在的完整配对（L8），不改变既有语义。

本模块为 V1.3 新增代码，不属于 V1.2 的 12 个受保护函数。
"""

import datetime
import os

PHOTO_EXTS = {".heic", ".heif", ".jpg", ".jpeg", ".png"}
VIDEO_EXTS = {".mov", ".mp4", ".m4v"}
# EXIF 可靠可读的主图扩展名（Pillow 无 HEIC 解码，.heic 一律走 mtime —— 04 号 R-12）
_EXIF_PHOTO_EXTS = {".jpg", ".jpeg", ".png"}

_EXIF_DATETIME_KEYS = ("DateTimeOriginal", "DateTimeDigitized", "DateTime")


class LivePhotoItem(object):
    """一张实况照片（完整配对）的只读视图。"""

    __slots__ = ("key", "name", "photo_path", "video_path", "rel_dir",
                 "rel_path", "dir_album", "sort_ts", "photo_ext")

    def __init__(self, key, name, photo_path, video_path, rel_dir, rel_path,
                 dir_album, sort_ts, photo_ext):
        self.key = key
        self.name = name
        self.photo_path = photo_path
        self.video_path = video_path
        self.rel_dir = rel_dir
        self.rel_path = rel_path
        self.dir_album = dir_album      # 第一层子目录名；根目录散落文件为 None
        self.sort_ts = sort_ts          # 拍摄时间倒序用时间戳
        self.photo_ext = photo_ext

    def to_dict(self):
        return {
            "key": self.key,
            "name": self.name,
            "rel_dir": self.rel_dir,
            "dir_album": self.dir_album,
            "photo_path": self.photo_path,
            "video_path": self.video_path,
            "sort_ts": self.sort_ts,
        }


def scan_source(root, should_cancel=None, issues=None):
    """只读扫描源目录，返回 ``(items, dir_albums, cancelled)``。

    - ``items``：完整配对的实况照片列表（已排序：拍摄时间倒序）
    - ``dir_albums``：按发现顺序排列的目录相册名（源根第一层子目录）
    - ``cancelled``：True 表示被用户取消，**调用方不得落盘半成品索引**（03 号 A2）

    ``should_cancel`` 为无参可调用对象，返回 True 表示请求在**安全检查点**停止。
    ``issues`` 可选 dict，原地累积 ``complete/photo_only/video_only/uncertain/unknown``
    计数，用于把「缺失配对 / 无法识别格式 / 同目录多候选」显式呈现给用户。

    配对单元是 **(所在目录, 基名小写)**，不是全库基名：不同子目录下的同名
    文件各自配对，绝不跨目录关联（原实现会把不同目录同名文件合并成一组，
    取 [0] 静默丢弃其余，甚至把 A 目录图片配上 B 目录视频）。
    """
    root = os.path.abspath(root)
    items = []
    dir_albums = []
    seen_dirs = set()
    issues = issues if issues is not None else {}
    for k in ("complete", "photo_only", "video_only", "uncertain", "unknown"):
        issues.setdefault(k, 0)

    # (目录, 基名小写) → {photo: [...], video: [...]}；多候选保留全部
    groups = {}

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        filenames.sort()
        for fn in filenames:
            base, ext = os.path.splitext(fn)
            ext = ext.lower()
            if ext not in PHOTO_EXTS and ext not in VIDEO_EXTS:
                issues["unknown"] += 1
                continue
            full = os.path.join(dirpath, fn)
            g = groups.setdefault((dirpath, base.lower()),
                                  {"photos": [], "videos": []})
            if ext in PHOTO_EXTS:
                g["photos"].append((full, ext))
            else:
                g["videos"].append(full)

        if should_cancel is not None and should_cancel():
            return [], [], True

    for (dirpath, base_lower), g in groups.items():
        if not g["photos"] or not g["videos"]:
            if g["photos"]:
                issues["photo_only"] += 1
            elif g["videos"]:
                issues["video_only"] += 1
            continue
        # 同目录同名多候选：计入"待确认"，按确定性顺序取第一个，不静默合并
        if len(g["photos"]) > 1 or len(g["videos"]) > 1:
            issues["uncertain"] += 1
        issues["complete"] += 1
        photo_path, photo_ext = g["photos"][0]
        video_path = g["videos"][0]
        name = os.path.splitext(os.path.basename(photo_path))[0]

        rel_path = os.path.relpath(photo_path, root).replace("\\", "/")
        rel_dir = os.path.dirname(rel_path).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""

        dir_album = None
        if rel_dir:
            dir_album = rel_dir.split("/")[0]
            if dir_album not in seen_dirs:
                seen_dirs.add(dir_album)
                dir_albums.append(dir_album)

        key = (rel_dir + "/" + name.lower()) if rel_dir else name.lower()
        items.append(LivePhotoItem(
            key=key, name=name, photo_path=photo_path, video_path=video_path,
            rel_dir=rel_dir, rel_path=rel_path, dir_album=dir_album,
            sort_ts=_sort_timestamp(photo_path, video_path, photo_ext),
            photo_ext=photo_ext,
        ))

    items.sort(key=lambda it: (-it.sort_ts, it.key.lower()))
    return items, dir_albums, False


def _sort_timestamp(photo_path, video_path, photo_ext):
    """拍摄时间戳：主图 EXIF 优先 → 视频 mtime → 主图 mtime。

    .heic/.heif 无 EXIF 读取能力（Pillow 无 HEIC 解码），直接走 mtime（04 号 R-12）。
    """
    if photo_ext in _EXIF_PHOTO_EXTS:
        ts = _exif_timestamp(photo_path)
        if ts:
            return ts
    for p in (video_path, photo_path):
        try:
            return os.path.getmtime(p)
        except OSError:
            continue
    return 0.0


def _exif_timestamp(path):
    """从 Pillow 可解码图片的 EXIF 读 DateTimeOriginal；失败返回 None。"""
    try:
        from PIL import Image
        with Image.open(path) as im:
            exif = None
            try:
                exif = im.getexif()
            except Exception:
                exif = None
            if not exif:
                return None
            raw = None
            for k in _EXIF_DATETIME_KEYS:
                # 36867=DateTimeOriginal, 36868=DateTimeDigitized, 306=DateTime
                tag = {"DateTimeOriginal": 36867, "DateTimeDigitized": 36868,
                       "DateTime": 306}[k]
                val = exif.get(tag)
                if val:
                    raw = val
                    break
            if not raw:
                return None
            text = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else str(raw)
            dt = datetime.datetime.strptime(text.strip()[:19], "%Y:%m:%d %H:%M:%S")
            return dt.timestamp()
    except Exception:
        return None


def count_groups(root):
    """统计目录内各状态数量（供状态条/空态判断使用，只读）。

    返回 ``{"complete": n, "photo_only": n, "video_only": n, "uncertain": n}``。
    """
    root = os.path.abspath(root)
    groups = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in filenames:
            base, ext = os.path.splitext(fn)
            ext = ext.lower()
            if ext not in PHOTO_EXTS and ext not in VIDEO_EXTS:
                continue
            g = groups.setdefault((dirpath, base.lower()), {"p": 0, "v": 0})
            if ext in PHOTO_EXTS:
                g["p"] += 1
            else:
                g["v"] += 1
    out = {"complete": 0, "photo_only": 0, "video_only": 0, "uncertain": 0}
    for g in groups.values():
        if g["p"] and g["v"]:
            if g["p"] > 1 or g["v"] > 1:
                out["uncertain"] += 1
            out["complete"] += 1
        elif g["p"]:
            out["photo_only"] += 1
        else:
            out["video_only"] += 1
    return out
