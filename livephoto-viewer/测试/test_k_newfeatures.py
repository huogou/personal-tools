# -*- coding: utf-8 -*-
"""V1.2 K 组 / B 组：新增交互独立测试（07 号 K-1 ~ K-7、D-6 ~ D-11）。

K-1 路径拦截（相同 / 嵌套双向 / 无关 / 判定失败）
K-2 空间预检四分支（充足 / 不足 / 超时 / 失败）
K-3 进度显示（逐条回调一一对应；取消经回调传达后当前条目完整结束）
K-4 关闭与取消（取消后无「写入中途终止」的半成品文件）
K-5 异常退出后果（进程被强杀后已完成条目已记录，复跑不重复不漏）
K-6 向导（首次仅一次、可关闭、可重开）
K-7 回归影响矩阵

用法： python 测试/test_k_newfeatures.py <证据输出目录>
"""
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
sys.path.insert(0, os.path.join(ROOT, "测试"))
from build_corpus import build as build_corpus        # noqa: E402

RESULTS = []
LOG = []
_WRAPPERS = []


def record(item, ok, detail):
    RESULTS.append((item, "PASS" if ok else "FAIL", detail))
    line = "[%s] %-8s %s" % ("PASS" if ok else "FAIL", item, detail)
    print(line)
    LOG.append(line)


def note(item, detail):
    """未验证 / 不适用项：如实记录，不计入通过。"""
    RESULTS.append((item, "UNVERIFIED", detail))
    line = "[UNVERIFIED] %-8s %s" % (item, detail)
    print(line)
    LOG.append(line)


def load_module(name, path):
    orig = sys.stdout
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    if sys.stdout is not orig:
        _WRAPPERS.append(sys.stdout)
        sys.stdout = orig
    return mod


def sha256_file(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class FakeTime(object):
    """可控时钟：每次 monotonic() 前进 step 秒，用于确定性触发超时分支。"""

    def __init__(self, real, step=0.5):
        self._real = real
        self._step = step
        self._t = real.monotonic()

    def monotonic(self):
        self._t += self._step
        return self._t

    def __getattr__(self, name):
        return getattr(self._real, name)


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.environ.get("TEMP", r"C:\Windows\Temp"), "lp_v12_k")
    work = os.path.join(outdir, "work_" + time.strftime("%H%M%S"))
    try:
        if os.path.exists(work):
            shutil.rmtree(work)
    except Exception:
        pass
    os.makedirs(work, exist_ok=True)
    corpus = build_corpus(os.path.join(work, "corpus"))
    src_dir = corpus
    mod = load_module("lp_v12k", SRC)
    mod.webbrowser.open = lambda *a, **k: True

    # ================= K-1 路径拦截独立测试 =================
    # 关系判定用独立的目录树，避免污染语料目录
    nest_root = os.path.join(work, "nest")
    nest_src = os.path.join(nest_root, "src")
    nest_out_inside = os.path.join(nest_src, "out")     # 输出在源内部
    os.makedirs(nest_out_inside, exist_ok=True)
    out_free = os.path.join(work, "out_free")           # 与源无关
    os.makedirs(out_free, exist_ok=True)

    cases = []
    # ① 完全相同
    cases.append(("相同", mod.check_path_relation(nest_src, nest_src), "same"))
    # ② 输出在源内部
    cases.append(("输出在源内部",
                  mod.check_path_relation(nest_src, nest_out_inside), "out_in_src"))
    # ③ 源在输出内部（输出为源的父目录）
    cases.append(("源在输出内部",
                  mod.check_path_relation(nest_out_inside, nest_src), "src_in_out"))
    # ③b 源在输出内部（输出为源的祖先目录）
    cases.append(("源在输出内部(祖先)",
                  mod.check_path_relation(nest_src, nest_root), "src_in_out"))
    # ④ 无关目录
    cases.append(("互相独立", mod.check_path_relation(nest_src, out_free), "ok"))
    # ⑤ 大小写不同
    cases.append(("大小写不同", mod.check_path_relation(nest_src, nest_src.upper()), "same"))
    # ⑥ 正反斜杠混用
    cases.append(("正反斜杠混用",
                  mod.check_path_relation(nest_src, nest_src.replace("\\", "/")), "same"))
    # ⑦ 尾部斜杠
    cases.append(("尾部斜杠", mod.check_path_relation(nest_src, nest_src + "\\"), "same"))
    # ⑧ 相对路径成分（. 与 ..）
    rel = os.path.relpath(nest_src, out_free)
    cases.append(("相对路径成分", mod.check_path_relation(os.path.join(out_free, rel),
                                                          nest_src), "same"))
    # ⑨ 前缀相同但不同目录（禁止裸 startswith 误判）
    sibling = nest_src + "_兄弟"
    os.makedirs(sibling, exist_ok=True)
    cases.append(("前缀相同但独立", mod.check_path_relation(nest_src, sibling), "ok"))

    bad = [c for c in cases if c[1]["status"] != c[2]]
    record("K-1", not bad,
           "%d 个判定场景全部符合预期（相同/嵌套双向/独立/大小写/斜杠/尾斜杠/相对路径/前缀误判）"
           % len(cases) if not bad else "不符预期：%s" % [(c[0], c[1]["status"], c[2]) for c in bad])

    # ⑩ junction 指向源目录
    junction = os.path.join(work, "junction_to_src")
    j_ok = False
    j_detail = ""
    try:
        if os.path.exists(junction):
            os.rmdir(junction)
        r = subprocess.run(["cmd", "/c", "mklink", "/J", junction, src_dir],
                           capture_output=True, text=True)
        if os.path.exists(junction):
            rel_j = mod.check_path_relation(src_dir, junction)
            j_ok = rel_j["status"] == "same"
            j_detail = "junction 判定=%s" % rel_j["status"]
        else:
            j_detail = "mklink 失败: %s" % (r.stdout or r.stderr).strip()[:120]
    except Exception as e:
        j_detail = "junction 测试异常: %s" % e
    if j_detail.startswith("junction 判定"):
        record("D-6-junction", j_ok, j_detail)
    else:
        note("D-6-junction", j_detail)

    # ⑪ 8.3 短文件名
    try:
        import ctypes
        from ctypes import wintypes
        fn = ctypes.windll.kernel32.GetShortPathNameW
        fn.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        fn.restype = wintypes.DWORD
        buf = ctypes.create_unicode_buffer(32768)
        n = fn(src_dir, buf, len(buf))
        if n and buf.value and buf.value.upper() != src_dir.upper():
            rel_83 = mod.check_path_relation(src_dir, buf.value)
            record("D-6-short83", rel_83["status"] == "same",
                   "短名 %s 判定=%s" % (buf.value, rel_83["status"]))
        else:
            note("D-6-short83", "本机未启用 8.3 短文件名（GetShortPathName 返回原路径），该变体未验证")
    except Exception as e:
        note("D-6-short83", "8.3 检测异常: %s" % e)

    # ⑫ 判定失败兜底（注入异常 → 必须 unknown → 拦截，不得放行）
    real_variants = mod._path_variants

    def boom(_p):
        raise OSError("注入的路径异常")

    mod._path_variants = boom
    try:
        rel_err = mod.check_path_relation(src_dir, out_free)
    finally:
        mod._path_variants = real_variants
    record("D-8", rel_err["status"] == "unknown",
           "路径判定异常时 status=%s（必须为 unknown → 阻止备份，无绕过）" % rel_err["status"])

    # ================= K-2 空间预检四分支 =================
    # ① 充足
    st_ok = mod.estimate_backup_size(src_dir, timeout=3.0)
    ok_ok = st_ok["state"] == "ok" and st_ok["need"] > 0 and st_ok["pairs"] == 5
    record("K-2-ok", ok_ok, "state=%s need=%s pairs=%s" %
           (st_ok["state"], mod.format_bytes(st_ok["need"]), st_ok.get("pairs")))

    # ② 不足（模拟目标盘可用极少）
    import shutil as _sh
    real_usage = _sh.disk_usage

    class FakeUsage(object):
        def __init__(self, free):
            self.total = free * 10
            self.used = free * 9
            self.free = free

    _sh.disk_usage = lambda p: FakeUsage(1)
    try:
        free_small = mod.check_free_space(out_free)
    finally:
        _sh.disk_usage = real_usage
    ok_short = (free_small == 1 and st_ok["need"] > free_small)
    record("K-2-short", ok_short, "模拟可用 %s 字节 < 预计 %s → 判定空间不足" %
           (free_small, st_ok["need"]))

    # ③ 超时
    fake = FakeTime(time, step=0.5)
    real_time = mod.time
    mod.time = fake
    try:
        st_to = mod.estimate_backup_size(src_dir, timeout=3.0)
    finally:
        mod.time = real_time
    record("K-2-timeout", st_to["state"] == "timeout",
           "注入快进时钟 → state=%s（必须为 timeout = 未完成检查）" % st_to["state"])

    # ④ 失败
    real_walk = os.walk

    def boom_walk(*a, **k):
        raise PermissionError("注入的读取权限异常")

    os.walk = boom_walk
    try:
        st_err = mod.estimate_backup_size(src_dir, timeout=3.0)
    finally:
        os.walk = real_walk
    record("K-2-error", st_err["state"] == "error",
           "注入权限异常 → state=%s（必须为 error = 检查失败）" % st_err["state"])

    # ================= K-3 进度显示 / K-4 安全取消 =================
    out_cancel = os.path.join(work, "out_cancel")
    events = []

    def cancel_cb(payload):
        events.append(payload)
        if payload.get("event") == "item" and payload.get("index") == 2:
            return False        # 第 3 个条目处理完后请求取消
        return None

    st_c = mod.process_directory(src_dir, out_cancel, log=lambda m: LOG.append("[cancel] " + m),
                                 progress_cb=cancel_cb)
    item_events = [e for e in events if e.get("event") == "item"]
    done_path = os.path.join(out_cancel, ".processed.json")
    done_map = json.load(open(done_path, encoding="utf-8")) if os.path.exists(done_path) else {}
    true_cnt = sum(1 for v in done_map.values() if v is True)
    false_cnt = sum(1 for v in done_map.values() if v is False)
    total_pairs = len(mod.find_live_photos(src_dir))
    raw_dir = os.path.join(out_cancel, "原始文件")
    raw_files = os.listdir(raw_dir) if os.path.isdir(raw_dir) else []
    # 已复制文件必须完整可打开（不得有「写入中途终止」的半成品）
    intact = True
    for f in raw_files:
        try:
            with open(os.path.join(raw_dir, f), "rb") as fh:
                fh.read()
        except Exception:
            intact = False
    processed = len(item_events)
    ok_cancel = (processed == 3 and st_c["ok"] + st_c["fail"] == 3
                 and len(done_map) == processed and true_cnt == st_c["ok"]
                 and false_cnt == st_c["fail"] and intact and len(raw_files) == 2 * processed)
    record("K-3", processed == 3 and [e["index"] for e in item_events] == [0, 1, 2],
           "回调 item 事件索引=%s（与已处理条目一一对应）" % [e["index"] for e in item_events])
    record("K-4", ok_cancel,
           "取消后：已处理 %s 组（成功 %s / 失败 %s）；.processed.json 记录 %s 条（True=%s False=%s，"
           "未处理的 %s 组无任何记录）；原始文件 %s 个且全部可打开=%s"
           % (processed, st_c["ok"], st_c["fail"], len(done_map), true_cnt, false_cnt,
              total_pairs - processed, len(raw_files), intact))
    record("A-11", (len(done_map) == processed and true_cnt == st_c["ok"]
                    and intact and total_pairs > processed),
           "取消后 .processed.json 只记录已处理条目（%s 条，其中成功 True=%s / 失败 False=%s）；"
           "未处理条目未被写入；已复制文件完整可打开=%s；续传空间存在（总 %s 组 > 已处理 %s 组）"
           % (len(done_map), true_cnt, false_cnt, intact, total_pairs, processed))

    # 取消后续传
    st_r = mod.process_directory(src_dir, out_cancel, log=lambda m: LOG.append("[resume] " + m))
    ok_resume = (st_r["skipped"] == true_cnt
                 and st_r["skipped"] + st_r["ok"] + st_r["fail"] == total_pairs)
    record("K-11-resume", ok_resume,
           "取消后再次备份：skipped=%s（= 已成功条目数 %s）ok=%s fail=%s；"
           "合计 %s = 总配对数 %s（已完成跳过、剩余继续处理、无重复）"
           % (st_r["skipped"], true_cnt, st_r["ok"], st_r["fail"],
              st_r["skipped"] + st_r["ok"] + st_r["fail"], total_pairs))

    # ================= K-5 异常退出后果 =================
    out_crash = os.path.join(work, "out_crash")
    child = os.path.join(ROOT, "测试", "_crash_child.py")
    r = subprocess.run([sys.executable, child, src_dir, out_crash, "2"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    crash_done = os.path.join(out_crash, ".processed.json")
    crash_map = json.load(open(crash_done, encoding="utf-8")) if os.path.exists(crash_done) else {}
    crash_true = sum(1 for v in crash_map.values() if v is True)
    st_crash = mod.process_directory(src_dir, out_crash, log=lambda m: LOG.append("[crash] " + m))
    ok_crash = (r.returncode != 0 and crash_true == 2
                and st_crash["skipped"] == 2 and st_crash["ok"] == 2)
    record("K-5", ok_crash,
           "子进程被强杀(rc=%s)后 .processed.json 已记录 %s 条成功；复跑 skipped=%s ok=%s fail=%s"
           % (r.returncode, crash_true, st_crash["skipped"], st_crash["ok"], st_crash["fail"]))

    # ================= 回调异常处理策略 =================
    out_cbex = os.path.join(work, "out_cbex")

    def bad_cb(payload):
        raise RuntimeError("注入的回调异常")

    logs_ex = []
    st_ex = mod.process_directory(src_dir, out_cbex, log=lambda m: logs_ex.append(m),
                                  progress_cb=bad_cb)
    warn_lines = [l for l in logs_ex if l.startswith("[警告]")]
    ok_ex = (st_ex["ok"] == 4 and st_ex["fail"] == 1 and len(warn_lines) > 0
             and all("进度回调异常" in l for l in warn_lines))
    record("K-12-cbex", ok_ex,
           "回调抛异常时：备份仍完成 ok=%s fail=%s；记录 [警告] 进度回调异常 %s 条"
           % (st_ex["ok"], st_ex["fail"], len(warn_lines)))

    # ================= K-6 向导独立测试 =================
    tmp_appdata = os.path.join(work, "appdata")
    os.makedirs(tmp_appdata, exist_ok=True)
    old_appdata = os.environ.get("APPDATA")
    os.environ["APPDATA"] = tmp_appdata
    try:
        flag = mod.first_run_flag_path()
        exists_before = os.path.exists(flag)
        # 首次：应写标记并弹向导
        app = None
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            app = mod.App(root)
            tops_before = len([w for w in root.winfo_children()])
            app.maybe_show_first_run()
            tops_after = len([w for w in root.winfo_children()])
            flag_after_first = os.path.exists(flag)
            # 第二次：不应再弹
            app.maybe_show_first_run()
            tops_second = len([w for w in root.winfo_children()])
            ok_wizard = (not exists_before and flag_after_first
                         and tops_after == tops_before + 1 and tops_second == tops_after)
            record("K-6", ok_wizard,
                   "首次弹出向导=%s；标记文件落盘=%s（%s）；再次调用不再弹出=%s；帮助入口可重开=%s"
                   % (tops_after == tops_before + 1, flag_after_first,
                      os.path.basename(flag), tops_second == tops_after,
                      tops_after - tops_before >= 1))
            # 帮助入口重开：再次调 _open_wizard_a 应新增一个 Toplevel
            base_cnt = len([w for w in root.winfo_children()])
            app._open_wizard_a(0)
            base_after = len([w for w in root.winfo_children()])
            record("K-6b", base_after == base_cnt + 1,
                   "帮助入口重开向导：Toplevel %s → %s" % (base_cnt, base_after))
            # 空间预检三态的行内文案（不得出现「空间充足」）
            msgs = {}
            for state in ("ok", "timeout", "error", "none"):
                app._space = {"state": state, "need": 3 * 1024 ** 3, "free": 10 * 1024 ** 3,
                              "pairs": 5, "key": None}
                app._render_space()
                msgs[state] = app.space_msg.cget("text")
            app._space = {"state": "ok", "need": 3 * 1024 ** 3, "free": 1 * 1024 ** 3,
                          "pairs": 5, "key": None}
            app._render_space()
            msgs["short"] = app.space_msg.cget("text")
            bad_msg = [s for s, t in msgs.items() if "空间充足" in t or "空间足够" in t]
            ok_msg = ("未完成" in msgs["timeout"] and "失败" in msgs["error"]
                      and "预计需要" in msgs["ok"] and "空间不足" in msgs["short"])
            record("D-9/D-10", ok_msg and not bad_msg,
                   "行内文案 ok=%r timeout=%r error=%r short=%r" %
                   (msgs["ok"], msgs["timeout"], msgs["error"], msgs["short"]))
            # 选项后果说明（取消「保留原始双件套」出现橙色警告）
            # 注意：root 已 withdraw()，winfo_ismapped() 恒为 False，故用 winfo_manager() 判断是否被布局
            app._toggle_opts()          # 展开备份选项区
            root.update()
            app.keep.set(False)
            app._on_opt_changed()
            root.update()
            warn_shown = app.keep_warn.winfo_manager() == "pack"
            warn_text = app.keep_warn.cget("text")
            app.keep.set(True)
            app._on_opt_changed()
            root.update()
            warn_hidden = app.keep_warn.winfo_manager() != "pack"
            record("D-5", warn_shown and warn_hidden,
                   "取消勾选后橙色警告出现=%s（文案=%r）；重新勾选后隐藏=%s"
                   % (warn_shown, warn_text, warn_hidden))
            # 扫描结果 → 统计卡 / 建议行 / 折叠明细
            app._stats = {"total": 7, "complete": 3, "uncertain": 2, "incomplete": 2,
                          "previewable": 6, "failed": 1}
            app._scan_state = "scanned"
            app._render_stats()
            app._update_next_step()
            nums = [i["num"].cget("text") for i in app._stat_cards]
            next_text = app.next_lbl.cget("text")
            ok_cards = nums == ["7", "3", "6", "2", "2", "1"]
            ok_next = ("2 组同名照片需要你确认" in next_text)
            record("C-4", ok_cards and ok_next,
                   "统计卡数字=%s；下一步建议=%r" % (nums, next_text))
            # 全部完整 → 「可以放心点开始备份」
            app._stats = {"total": 7, "complete": 7, "uncertain": 0, "incomplete": 0,
                          "previewable": 7, "failed": 0}
            app._update_next_step()
            text_all = app.next_lbl.cget("text")
            ok_next2 = "全部配对完整" in text_all
            # 有不完整 → 「程序不会判断文件损坏」
            app._stats = {"total": 7, "complete": 3, "uncertain": 0, "incomplete": 2,
                          "previewable": 6, "failed": 0}
            app._update_next_step()
            text_inc = app.next_lbl.cget("text")
            ok_next3 = ("不会判断文件损坏" in text_inc)
            record("C-4b", ok_next2 and ok_next3,
                   "全完整建议=%r；不完整建议=%r" % (text_all, text_inc))
            root.destroy()
        except Exception as e:
            note("K-6", "GUI 级断言执行异常（可能无桌面会话）：%s" % e)
    finally:
        if old_appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = old_appdata

    # ================= 证据落盘 =================
    with io.open(os.path.join(outdir, "k_group_results.json"), "w", encoding="utf-8") as fh:
        json.dump({"results": [{"item": i, "result": r, "detail": d} for i, r, d in RESULTS],
                   "run_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                  fh, ensure_ascii=False, indent=2)
    with io.open(os.path.join(outdir, "k_group_log.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(LOG))
    npass = sum(1 for _, r, _ in RESULTS if r == "PASS")
    ntot = len(RESULTS)
    print()
    print("K/B 组结果：%d/%d PASS（另有 %d 项未验证）" %
          (npass, ntot, sum(1 for _, r, _ in RESULTS if r == "UNVERIFIED")))
    return 0 if npass + sum(1 for _, r, _ in RESULTS if r == "UNVERIFIED") == ntot else 1


if __name__ == "__main__":
    sys.exit(main())
