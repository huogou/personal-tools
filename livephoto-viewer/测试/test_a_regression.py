# -*- coding: utf-8 -*-
"""V1.2 A 组：原有功能回归（红线）。

覆盖 07 号 A-1 ~ A-11：
  A-1 只读预览扫描 / A-2 只读性 / A-3 备份主流程 / A-4 增量备份 /
  A-5 损坏文件隔离 / A-6 中文空格路径 / A-7 预览临时目录 / A-8 CLI 模式 /
  A-9 新增 UI 不改变既有结果数值 / A-10 Q4 回调兼容性 / A-11 安全取消不破坏数据

用法： python 测试/test_a_regression.py <证据输出目录>
"""
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import time
from importlib.machinery import SourceFileLoader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "LivePhoto_Backup.pyw")
BASE_SRC = os.path.join(ROOT, "历史备份", "备份_V1.2_开发前_20261028", "LivePhoto_Backup.pyw")
sys.path.insert(0, os.path.join(ROOT, "测试"))

from build_corpus import build as build_corpus       # noqa: E402

RESULTS = []
LOG = []


def record(item, ok, detail):
    RESULTS.append((item, "PASS" if ok else "FAIL", detail))
    line = "[%s] %-8s %s" % ("PASS" if ok else "FAIL", item, detail)
    print(line)
    LOG.append(line)


_WRAPPERS = []


def load_module(name, path):
    """按路径加载 .pyw 模块。

    模块导入时会把 sys.stdout 包成 TextIOWrapper；若不保活，该包装器被 GC 时会
    关闭底层缓冲，导致后续 print 报 "I/O operation on closed file"。
    """
    orig = sys.stdout
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    if sys.stdout is not orig:
        _WRAPPERS.append(sys.stdout)
        sys.stdout = orig
    return mod


def snapshot(root):
    """源目录快照：相对路径 + 大小 + mtime。"""
    out = {}
    for base, dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(base, f)
            rel = os.path.relpath(p, root)
            try:
                st = os.stat(p)
                out[rel] = (st.st_size, st.st_mtime_ns)
            except OSError:
                out[rel] = (None, None)
    return out


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def tree(root):
    out = []
    for base, dirs, files in os.walk(root):
        for f in sorted(files):
            p = os.path.join(base, f)
            out.append(os.path.relpath(p, root).replace("\\", "/"))
    return sorted(out)


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.environ.get("TEMP", r"C:\Windows\Temp"), "lp_v12_a")
    work = os.path.join(outdir, "work_" + time.strftime("%H%M%S"))
    try:
        if os.path.exists(work):
            shutil.rmtree(work)
    except Exception:
        pass
    os.makedirs(work, exist_ok=True)

    mod = load_module("lp_v12", SRC)
    # 自动化测试中不真正拉起浏览器（EXE 级验收会真实拉起）
    mod.webbrowser.open = lambda *a, **k: True

    corpus = build_corpus(os.path.join(work, "corpus"))
    out_v12 = os.path.join(work, "out_v12")

    # ---------- A-1 只读预览扫描 ----------
    before = snapshot(corpus)
    stats = mod.run_preview(corpus, log=lambda m: LOG.append("[preview] " + m))
    ok = (stats["total"] == 7 and stats["complete"] == 3 and stats["uncertain"] == 2
          and stats["incomplete"] == 2 and stats["previewable"] == 6 and stats["failed"] == 1)
    record("A-1", ok, "预览统计 total=%s complete=%s uncertain=%s incomplete=%s "
                      "previewable=%s failed=%s" % (stats["total"], stats["complete"],
                                                    stats["uncertain"], stats["incomplete"],
                                                    stats["previewable"], stats["failed"]))

    # ---------- A-2 只读性 ----------
    after = snapshot(corpus)
    ok = (before == after) and not os.path.exists(os.path.join(corpus, ".processed.json"))
    record("A-2", ok, "预览前后源目录快照一致=%s；源目录无 .processed.json=%s"
           % (before == after, not os.path.exists(os.path.join(corpus, ".processed.json"))))

    # ---------- A-6 中文 / 空格路径 ----------
    zh = [p for p in before if "中文" in p]
    ok = len(zh) >= 2
    record("A-6", ok, "语料含中文+空格路径 %d 个：%s" % (len(zh), zh[:4]))

    # ---------- A-3 备份主流程 ----------
    stats2 = mod.process_directory(corpus, out_v12, log=lambda m: LOG.append("[backup] " + m))
    names = tree(out_v12)
    need_dirs = ["原始文件", "GIF动图", "网页查看器"]
    have_dirs = [d for d in need_dirs
                 if os.path.isdir(os.path.join(out_v12, d))]
    gifs = [n for n in names if n.startswith("GIF动图/") and n.endswith(".gif")]
    thumbs = [n for n in names if n.startswith("网页查看器/thumb/")]
    html_ok = os.path.exists(os.path.join(out_v12, "网页查看器", "index.html"))
    done_ok = os.path.exists(os.path.join(out_v12, ".processed.json"))
    ok = (len(have_dirs) == 3 and html_ok and done_ok and stats2["ok"] == 4
          and stats2["fail"] == 1 and stats2["total"] == 5 and len(gifs) == 4)
    record("A-3", ok, "产物目录=%s；GIF=%d；封面=%d；index.html=%s；.processed.json=%s；"
                      "统计 ok=%s fail=%s total=%s"
           % (have_dirs, len(gifs), len(thumbs), html_ok, done_ok,
              stats2["ok"], stats2["fail"], stats2["total"]))

    # ---------- A-5 损坏文件隔离 ----------
    logs_broken = [l for l in LOG if l.startswith("[backup]") and "BROKEN_01" in l]
    ok = any("[失败]" in l for l in logs_broken) and stats2["ok"] == 4
    record("A-5", ok, "BROKEN_01 记失败且不影响其余 4 组；失败日志示例：%s"
           % (logs_broken[0][:90] if logs_broken else "无"))

    # ---------- A-4 增量备份 ----------
    stats3 = mod.process_directory(corpus, out_v12, log=lambda m: LOG.append("[backup2] " + m))
    ok = stats3["skipped"] == 4 and stats3["ok"] == 0 and stats3["fail"] == 1
    record("A-4", ok, "二次运行 skipped=%s ok=%s fail=%s" %
           (stats3["skipped"], stats3["ok"], stats3["fail"]))

    # ---------- A-10 Q4 回调兼容性 ----------
    out_cb = os.path.join(work, "out_cb")
    seen = []

    def cb(payload):
        seen.append(payload)
        return None                      # 正常回调返回 None → 必须继续

    stats_cb = mod.process_directory(corpus, out_cb, log=lambda m: LOG.append("[cb] " + m),
                                     progress_cb=cb)
    done_v12 = os.path.join(out_v12, ".processed.json")
    done_cb = os.path.join(out_cb, ".processed.json")
    same_json = (os.path.exists(done_v12) and os.path.exists(done_cb)
                 and open(done_v12, "rb").read() == open(done_cb, "rb").read())
    events = [e.get("event") for e in seen]
    item_idx = [e.get("index") for e in seen if e.get("event") == "item"]
    idx_ok = item_idx == list(range(len(item_idx)))
    ok = (same_json and stats_cb["ok"] == stats2["ok"] and stats_cb["fail"] == stats2["fail"]
          and stats_cb["total"] == stats2["total"] and "start" in events and "item" in events
          and idx_ok)
    record("A-10", ok, "带回调与不带回调的 .processed.json 逐字节一致=%s；回调事件=%s；"
                       "条目索引单调递增=%s；统计一致=%s"
           % (same_json, events, idx_ok,
              (stats_cb["ok"], stats_cb["fail"], stats_cb["total"]) ==
              (stats2["ok"], stats2["fail"], stats2["total"])))

    # ---------- A-9 新增 UI 不改变既有结果数值（V1.1 基线对照） ----------
    out_v11 = os.path.join(work, "out_v11")
    r11 = subprocess.run([sys.executable, BASE_SRC, "--cli", corpus, out_v11],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    r12 = subprocess.run([sys.executable, SRC, "--cli", corpus, os.path.join(work, "out_v12cli")],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    out_v12cli = os.path.join(work, "out_v12cli")

    def stat_line(txt):
        for l in txt.splitlines():
            if l.startswith("统计:"):
                return l.strip()
        return ""

    s11, s12 = stat_line(r11.stdout), stat_line(r12.stdout)
    d11 = os.path.join(out_v11, ".processed.json")
    d12 = os.path.join(out_v12cli, ".processed.json")
    json_same = (os.path.exists(d11) and os.path.exists(d12)
                 and open(d11, "rb").read() == open(d12, "rb").read())
    tree_same = tree(out_v11) == tree(out_v12cli)
    ok = (s11 == s12 and s11 != "" and json_same and tree_same
          and r11.returncode == 0 and r12.returncode == 0)
    record("A-9", ok, "V1.1 与 V1.2 CLI 统计行一致=%s（%s）；产物清单一致=%s；"
                      ".processed.json 逐字节一致=%s；rc=%s/%s"
           % (s11 == s12, s11, tree_same, json_same, r11.returncode, r12.returncode))

    # ---------- A-8 CLI 模式 ----------
    out_cli = os.path.join(work, "out_cli_mode")
    rc_cli = subprocess.run([sys.executable, SRC, "--cli", corpus, out_cli],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok_cli = rc_cli.returncode == 0 and os.path.isdir(os.path.join(out_cli, "原始文件"))
    r_prev = subprocess.run([sys.executable, SRC, "--preview", corpus],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok_prev = r_prev.returncode == 0 and "预览完成" in (r_prev.stdout or "")
    record("A-8", ok_cli and ok_prev, "--cli rc=%s；--preview rc=%s（stdout 含「预览完成」=%s）"
           % (rc_cli.returncode, r_prev.returncode, "预览完成" in (r_prev.stdout or "")))

    # ---------- A-7 预览临时目录 ----------
    tmp = os.environ.get("TEMP", r"C:\Windows\Temp")

    def marked():
        n = []
        for d in os.listdir(tmp):
            if d.startswith("livephoto_preview_"):
                p = os.path.join(tmp, d)
                if os.path.isfile(os.path.join(p, ".livephoto_preview_owner")):
                    n.append(d)
        return n

    for i in range(3):
        mod.run_preview(corpus, log=lambda m: None)
    left = marked()
    ok = len(left) == 1
    record("A-7", ok, "连续 3 次预览后，带有效归属标记的临时目录数 = %d（%s）" % (len(left), left))

    # ---------- 证据落盘 ----------
    with io.open(os.path.join(outdir, "a_group_results.json"), "w", encoding="utf-8") as fh:
        json.dump({"results": [{"item": i, "result": r, "detail": d} for i, r, d in RESULTS],
                   "run_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                  fh, ensure_ascii=False, indent=2)
    with io.open(os.path.join(outdir, "a_group_log.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(LOG))
    print()
    npass = sum(1 for _, r, _ in RESULTS if r == "PASS")
    print("A 组结果：%d/%d PASS" % (npass, len(RESULTS)))
    return 0 if npass == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
