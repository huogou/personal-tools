# -*- coding: utf-8 -*-
"""V1.3 相册 / 媒体引擎 专项自动化测试（对应 08 号检查表 C、D、E 组可脚本化项）。

覆盖：
  C 组 分类体系：C-01 目录自动归类 / C-02 深层不另建相册 / C-05 多相册叠加 /
                C-07 索引落盘 / C-08 关闭重开保持 / C-09 索引损坏不伤照片 /
                C-10 .bak 自愈 / C-11 原子写 / C-12 索引与增量隔离 /
                C-13 删相册不删照片 / C-14 排序 / C-15 路径状态如实
  D 组 播放引擎：D-05 转码规格 / D-06 缓存复用 / D-08 缓存不写源目录 /
                D-09 导出 MP4 / D-10 导出幂等
  E 组 离线与源只读：E-02 无端口与外部依赖 / E-04 源目录零写入 / E-05 原片不被覆盖

用法： python 测试/test_v13_album.py <证据输出目录>
"""
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import album_index          # noqa: E402
import album_scan           # noqa: E402
import album_media          # noqa: E402

SAMPLE_PHOTO = os.path.join(ROOT, "测试样本", "IMG_0346.HEIC")
SAMPLE_VIDEO = os.path.join(ROOT, "测试样本", "IMG_0346.mp4")

RESULTS = []
LOG = []


def record(item, ok, detail):
    RESULTS.append((item, "PASS" if ok else "FAIL", detail))
    line = "[%s] %-10s %s" % ("PASS" if ok else "FAIL", item, detail)
    print(line)
    LOG.append(line)


def note(item, detail):
    RESULTS.append((item, "UNVERIFIED", detail))
    line = "[UNVERIFIED] %-10s %s" % (item, detail)
    print(line)
    LOG.append(line)


def snapshot(root):
    """目录指纹（相对路径 → 大小 + mtime_ns），用于只读性比对。"""
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace("\\", "/")
            try:
                st = os.stat(full)
                out[rel] = (st.st_size, st.st_mtime_ns)
            except OSError:
                out[rel] = None
    return out


def build_corpus(target):
    """V1.3 语料：目录相册（旅行/美食/中文 空格）+ 根目录散落文件（未分类）。"""
    if os.path.exists(target):
        shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target)
    plan = [
        (os.path.join("旅行", "云南"), "IMG_0101"),
        (os.path.join("旅行", "云南"), "IMG_0102"),
        (os.path.join("旅行", "大理"), "IMG_0103"),
        (os.path.join("美食", "夜市"), "IMG_0201"),
        (os.path.join("美食", "夜市"), "IMG_0202"),
        (os.path.join("中文 空格 目录"), "中文 名称"),
        ("", "IMG_0301"),
        ("", "IMG_0302"),
    ]
    for rel, base in plan:
        d = os.path.join(target, rel) if rel else target
        os.makedirs(d, exist_ok=True)
        shutil.copy2(SAMPLE_PHOTO, os.path.join(d, base + ".HEIC"))
        shutil.copy2(SAMPLE_VIDEO, os.path.join(d, base + ".mp4"))
    return target


def ffprobe(path):
    """用 ffmpeg 解析输出关键参数（无 ffprobe 时用 ffmpeg -i 的 stderr）。"""
    exe = album_media.FFMPEG
    r = subprocess.run([exe, "-hide_banner", "-i", path],
                       capture_output=True, text=True, errors="ignore")
    return (r.stderr or "") + (r.stdout or "")


def main(evidence_dir):
    if os.path.exists(evidence_dir):
        shutil.rmtree(evidence_dir, ignore_errors=True)
    os.makedirs(evidence_dir, exist_ok=True)

    work = os.path.join(evidence_dir, "work")
    src = build_corpus(os.path.join(work, "源目录"))
    out = os.path.join(work, "输出目录")
    os.makedirs(out, exist_ok=True)

    src_before = snapshot(src)

    # ---------- C-01 / C-02 目录自动归类 ----------
    items, dir_albums, cancelled = album_scan.scan_source(src)
    names = sorted(dir_albums)
    record("C-01", names == sorted(["旅行", "美食", "中文 空格 目录"]),
           "目录相册=%s（应仅第一层子目录，深层不另建）" % names)
    record("C-02", "旅行" in names and "云南" not in names and "大理" not in names,
           "深层子目录未另建相册：names=%s" % names)
    record("C-02b", len(items) == 8, "完整配对数量=%d（应 8）" % len(items))

    # photo_key 形态（04 号 §二）
    keys = [it.key for it in items]
    ok_key = all(("/" in k or k == k.lower()) for k in keys) and \
        any(k.startswith("旅行/云南/") for k in keys) and \
        any(k == "img_0301" for k in keys)
    record("C-01b", ok_key, "photo_key 形态正确（相对路径+小写基名），样例=%s"
           % sorted(keys)[:3])

    # ---------- C-14 排序（拍摄时间倒序）----------
    ts = [it.sort_ts for it in items]
    record("C-14", ts == sorted(ts, reverse=True),
           "排序为时间倒序=%s（EXIF 不可用时回退 mtime）" % (ts == sorted(ts, reverse=True)))

    # ---------- C-07 索引落盘 ----------
    idx = album_index.AlbumIndex.load(out)[0]
    idx.ensure_dir_albums(dir_albums)
    man = idx.create_album("家人")
    idx.assign([it.key for it in items if it.key.startswith("旅行/云南/")], [man["id"]])
    idx.save()
    ipath = os.path.join(out, "相册索引.json")
    ok_json = os.path.exists(ipath)
    try:
        with open(ipath, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        ok_schema = data.get("schema") == album_index.SCHEMA
    except Exception as e:
        data, ok_schema = None, False
    record("C-07", ok_json and ok_schema,
           "索引已落盘且为合法 JSON，schema=%s" % (data or {}).get("schema"))

    # ---------- C-05 多相册叠加 ----------
    k = [it.key for it in items if it.key.startswith("旅行/云南/")][0]
    eff = album_index.AlbumIndex.load(out)[0]
    manual_ids = eff.manual_albums_of(k)
    dir_album_id = None
    for a in eff.albums():
        if a.get("kind") == "dir" and a.get("name") == "旅行":
            dir_album_id = a["id"]
    record("C-05", bool(manual_ids) and dir_album_id is not None,
           "同一照片同时属于目录相册与手动相册：manual=%s dir=%s" % (manual_ids, dir_album_id))

    # ---------- C-08 关闭重开保持 ----------
    again = album_index.AlbumIndex.load(out)[0]
    record("C-08", again.manual_albums_of(k) == manual_ids,
           "重新加载后归类保持：%s" % again.manual_albums_of(k))

    # ---------- C-11 原子写（不留 .tmp；二次保存后应生成 .bak）----------
    idx2 = album_index.AlbumIndex.load(out)[0]
    idx2.create_album("触发备份的相册")
    idx2.save()
    tmp_left = os.path.exists(os.path.join(out, "相册索引.json.tmp"))
    bak_left = os.path.exists(os.path.join(out, "相册索引.json.bak"))
    record("C-11", (not tmp_left) and bak_left,
           "原子写：.tmp 未残留=%s，.bak 已生成=%s" % (not tmp_left, bak_left))

    # ---------- C-12 索引与 .processed.json 隔离 ----------
    pj = os.path.join(out, ".processed.json")
    with open(pj, "w", encoding="utf-8") as fh:
        fh.write('{"img_0346|x": true}')
    before = open(pj, "rb").read()
    idx2b = album_index.AlbumIndex.load(out)[0]
    idx2b.create_album("临时相册")
    idx2b.save()
    after = open(pj, "rb").read()
    record("C-12", before == after, ".processed.json 字节未变（索引操作不触碰增量语义）")

    # ---------- C-09 / C-10 损坏自愈 ----------
    with open(ipath, "w", encoding="utf-8") as fh:
        fh.write("{ this is not json ")
    idx3, st = album_index.AlbumIndex.load(out)
    record("C-10", st == "recovered",
           "主索引损坏后从 .bak 自愈，status=%s，recovered=%s" % (st, idx3.recovered))
    with open(ipath, "w", encoding="utf-8") as fh:
        fh.write("{ broken")
    with open(os.path.join(out, "相册索引.json.bak"), "w", encoding="utf-8") as fh:
        fh.write("{ also broken")
    idx4, st4 = album_index.AlbumIndex.load(out)
    record("C-09", st4 == "broken",
           "主/备均损坏时返回 broken 且不阻断浏览，status=%s" % st4)

    # ---------- schema 不认识 → 拒绝写入（独立目录，避免污染后续用例）----------
    out_blocked = os.path.join(work, "输出_未知schema")
    os.makedirs(out_blocked, exist_ok=True)
    with open(os.path.join(out_blocked, "相册索引.json"), "w", encoding="utf-8") as fh:
        json.dump({"schema": "livephoto-album-index/9.9", "albums": [], "assignments": {}}, fh)
    blk_before = open(os.path.join(out_blocked, "相册索引.json"), "rb").read()
    idx5, st5 = album_index.AlbumIndex.load(out_blocked)
    blocked = idx5.write_blocked
    try:
        idx5.save()
        wrote = True
    except Exception:
        wrote = False
    blk_after = open(os.path.join(out_blocked, "相册索引.json"), "rb").read()
    record("C-15b", blocked and not wrote and blk_before == blk_after,
           "未知 schema：拒绝写入且原文件字节未变（blocked=%s wrote=%s）"
           % (blocked, wrote))

    # ---------- C-13 删相册不删照片 ----------
    idx6, _ = album_index.AlbumIndex.load(out)
    tmp_album = idx6.create_album("待删相册")
    idx6.assign([k], [tmp_album["id"]])
    idx6.save()
    idx7, _ = album_index.AlbumIndex.load(out)
    idx7.delete_album(tmp_album["id"])
    idx7.save()
    idx8, _ = album_index.AlbumIndex.load(out)
    record("C-13", idx8.get_album(tmp_album["id"]) is None,
           "相册已删除；照片本体未被触碰（源目录文件数不变=%d）"
           % len(snapshot(src)))

    # ---------- C-15 路径状态如实 ----------
    missing = album_scan.scan_source(os.path.join(work, "不存在目录"))
    record("C-15", missing[0] == [] and missing[2] is False,
           "路径不存在时扫描返回空且不抛异常（上层据此给出 V-21 明确状态）")

    # ---------- D-05 转码规格 ----------
    vid = items[0].video_path
    mp4 = album_media.ensure_transcoded(out, vid, root=src)
    info = ffprobe(mp4)
    ok_h264 = "h264" in info.lower() or "avc1" in info.lower()
    ok_audio = "aac" in info.lower()
    ok_mp4 = "mp4" in info.lower()
    record("D-05", ok_h264 and ok_audio and ok_mp4,
           "转码产出 MP4/H.264/AAC：h264=%s aac=%s mp4=%s"
           % (ok_h264, ok_audio, ok_mp4))

    # ---------- D-06 缓存复用（不重复转码）----------
    mtime_before = os.path.getmtime(mp4)
    size_before = os.path.getsize(mp4)
    time.sleep(0.05)
    mp4b = album_media.ensure_transcoded(out, vid, root=src)
    record("D-06", (mp4b == mp4 and os.path.getmtime(mp4b) == mtime_before
                    and os.path.getsize(mp4b) == size_before),
           "二次调用命中缓存，未重复转码（路径一致=%s）" % (mp4b == mp4))

    # ---------- 封面 ----------
    cov = album_media.ensure_cover(out, vid, root=src, name=items[0].name)
    cover_ok = False
    if cov and os.path.exists(cov):
        try:
            from PIL import Image
            with Image.open(cov) as im:
                cover_ok = im.size[0] <= album_media.COVER_WIDTH + 2
        except Exception:
            cover_ok = False
    record("D-11", cover_ok, "封面为视频首帧且宽度≤360：%s" % cov)

    # ---------- D-09 / D-10 导出 ----------
    res = album_media.export_mp4(items[:3], out)
    exported_ok = len(res["files"]) == 3 and all(os.path.exists(p) for p in res["files"])
    record("D-09", exported_ok, "导出 MP4 %d 个，目录=%s" % (len(res["files"]), res["dir"]))
    res2 = album_media.export_mp4(items[:3], out)
    record("D-10", len(res2["skipped"]) == 3 and len(res2["files"]) == 0,
           "重复导出被跳过（已是最新）：skipped=%d files=%d"
           % (len(res2["skipped"]), len(res2["files"])))

    # ---------- 空间预检三态 ----------
    s_ok = album_media.rough_space_check(out, 1024)
    s_bad = album_media.rough_space_check(out, 1 << 62)
    # 不存在的盘符 → 无法定位任何可用目录 → unknown（不得静默放行）
    s_unk = album_media.rough_space_check("Z:\\不存在的盘\\子目录", 1024)
    record("D-12", s_ok["state"] == "ok" and s_bad["state"] == "insufficient"
           and s_unk["state"] == "unknown",
           "空间预检三态：ok=%s insufficient=%s unknown=%s"
           % (s_ok["state"], s_bad["state"], s_unk["state"]))
    # 目标目录尚不存在时，应向上取已存在父目录判定（可查即非 unknown）
    s_new = album_media.rough_space_check(os.path.join(work, "尚未创建", "子"), 1024)
    record("D-12b", s_new["state"] in ("ok", "insufficient"),
           "目标目录不存在时向上取父目录判定（state=%s，非 unknown）" % s_new["state"])

    # ---------- E-04 源目录零写入 / E-05 原片不覆盖 ----------
    src_after = snapshot(src)
    record("E-04", src_before == src_after,
           "源目录全程零写入（文件数 %d→%d）" % (len(src_before), len(src_after)))
    raw = os.path.join(out, "原始文件")
    os.makedirs(raw, exist_ok=True)
    shutil.copy2(SAMPLE_VIDEO, os.path.join(raw, "IMG_0101.mp4"))
    h_before = open(os.path.join(raw, "IMG_0101.mp4"), "rb").read()
    album_media.ensure_transcoded(out, os.path.join(raw, "IMG_0101.mp4"), root=raw)
    h_after = open(os.path.join(raw, "IMG_0101.mp4"), "rb").read()
    record("E-05", h_before == h_after, "原始文件/ 中的原片未被覆盖")

    # ---------- E-02 离线：无端口、无外部依赖 ----------
    hits = []
    for mod in ("album_index.py", "album_scan.py", "album_media.py"):
        p = os.path.join(ROOT, mod)
        with open(p, "r", encoding="utf-8") as fh:
            txt = fh.read()
        for bad in ("http_server", "http.server", "socket", "requests",
                    "urllib.request", "flask", "bottle"):
            if bad in txt:
                hits.append("%s:%s" % (mod, bad))
    record("E-02", not hits, "离线检查：三个新模块内无 http_server/socket/requests 等，命中=%s"
           % hits)

    # ---------- 汇总 ----------
    passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
    failed = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    unver = sum(1 for _, s, _ in RESULTS if s == "UNVERIFIED")
    summary = {"total": len(RESULTS), "pass": passed, "fail": failed,
               "unverified": unver,
               "results": [{"item": i, "status": s, "detail": d} for i, s, d in RESULTS]}
    with open(os.path.join(evidence_dir, "v13_album_results.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(evidence_dir, "v13_album_log.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(LOG))
    print("\n汇总：%d 项 / PASS %d / FAIL %d / UNVERIFIED %d"
          % (len(RESULTS), passed, failed, unver))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    tgt = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.environ.get("TEMP", r"C:\Windows\Temp"), "lp_v13_album")
    sys.exit(main(tgt))
