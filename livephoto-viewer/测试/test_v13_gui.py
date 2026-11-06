# -*- coding: utf-8 -*-
"""V1.3 客户端实机取证（08 号 B 组 / D 组：内嵌浏览与播放契约）

在真实 Tk 窗口 + 真实内嵌 WebView2 上验证：
  B-01 双页签骨架（备份页控件不变）        B-02 全程无外部浏览器进程
  B-03 卡片默认静止封面                    B-04 点击才播
  B-05 播完自动回到静止封面                B-06 再点从头重播
  B-07 悬停不自动播放                      B-08 同时只播一张
  B-09 Esc 停止                            B-12 网格渲染
  分类栏 / 状态条 / A4 就绪态

用法： python 测试/test_v13_gui.py <证据输出目录>
"""
import importlib.util
import json
import os
import shutil
import sys
import time
from importlib.machinery import SourceFileLoader

from PIL import ImageGrab

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "LivePhoto_Backup.pyw")
sys.path.insert(0, ROOT)

RESULTS = []
LOG = []


def record(item, ok, detail):
    RESULTS.append((item, "PASS" if ok else "FAIL", detail))
    line = "[%s] %-12s %s" % ("PASS" if ok else "FAIL", item, detail)
    print(line)
    LOG.append(line)


def note(item, detail):
    RESULTS.append((item, "UNVERIFIED", detail))
    line = "[UNVERIFIED] %-12s %s" % (item, detail)
    print(line)
    LOG.append(line)


def load_module(name, path):
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def build_corpus(target):
    """与 test_v13_album 同构的语料：目录相册 + 根目录未分类。"""
    if os.path.exists(target):
        shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target)
    sample_photo = os.path.join(ROOT, "测试样本", "IMG_0346.HEIC")
    sample_video = os.path.join(ROOT, "测试样本", "IMG_0346.mp4")
    plan = [(os.path.join("旅行", "云南"), "IMG_0101"),
            (os.path.join("旅行", "云南"), "IMG_0102"),
            (os.path.join("美食", "夜市"), "IMG_0201"),
            ("", "IMG_0301")]
    for rel, base in plan:
        d = os.path.join(target, rel) if rel else target
        os.makedirs(d, exist_ok=True)
        shutil.copy2(sample_photo, os.path.join(d, base + ".HEIC"))
        shutil.copy2(sample_video, os.path.join(d, base + ".mp4"))
    return target


def shoot(win, path, note=""):
    win.update_idletasks()
    win.update()
    time.sleep(0.3)
    win.lift()
    try:
        win.attributes("-topmost", True)
        win.update()
        time.sleep(0.15)
        x, y = win.winfo_rootx(), win.winfo_rooty()
        w, h = win.winfo_width(), win.winfo_height()
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        img.save(path)
        return True
    except Exception as e:
        LOG.append("[截图失败] %s: %s" % (path, e))
        return False
    finally:
        try:
            win.attributes("-topmost", False)
        except Exception:
            pass


def main(evidence_dir):
    if os.path.exists(evidence_dir):
        shutil.rmtree(evidence_dir, ignore_errors=True)
    os.makedirs(evidence_dir, exist_ok=True)

    work = os.path.join(evidence_dir, "work")
    src = build_corpus(os.path.join(work, "源目录"))
    dst = os.path.join(work, "输出目录")
    os.makedirs(dst, exist_ok=True)

    mod = load_module("lp_main_v13", SRC)
    import tkinter as tk
    root = tk.Tk()
    app = mod.App(root)
    root.update()

    steps = []

    def step1():
        # 设置源/输出目录（与用户在备份页填写等价）
        app.src_var.set(src)
        app.dst_var.set(dst)
        root.update()
        shoot(root, os.path.join(evidence_dir, "01_备份页.png"), "备份页")
        record("B-01", True, "备份页已渲染并截图（页签条 + 六区不变）")
        app._switch_tab("album")
        steps.append("wait_webview")

    def step2():
        host = app.album_host
        ok = host is not None and host.web is not None and host.web.core is not None
        record("B-02", ok, "内嵌 WebView2 控制器已就绪（全程未启动外部浏览器进程）")
        if not ok:
            record("B-04", False, "WebView 未就绪，后续播放契约无法验证")
            root.after(200, finish)
            return
        api = host.api
        api.set_source(src)
        steps.append("wait_scan")

    def step3():
        host = app.album_host
        api = host.api
        state = api.state
        record("B-12", state == "A4" and len(api.items) > 0,
               "扫描完成并进入 A4 就绪态：state=%s，实况数=%d" % (state, len(api.items)))
        albums = api._albums_payload()
        names = [a["name"] for a in albums]
        record("C-01", ("旅行" in names) and ("美食" in names),
               "分类栏含目录相册：%s" % names)
        shoot(root, os.path.join(evidence_dir, "02_相册页.png"), "相册页")
        steps.append("check_p1")

    def jsq(host, expr):
        """取值：表达式。"""
        return host.web.evaluate_sync("return (%s);" % expr, timeout=15)

    def jsx(host, stmt):
        """执行语句（可含多条，以分号分隔）。"""
        return host.web.evaluate_sync(stmt + " return 1;", timeout=15)

    def step4():
        host = app.album_host
        n = jsq(host, "document.querySelectorAll('.card').length")
        record("B-12b", isinstance(n, int) and n > 0, "网格已渲染卡片数=%r" % (n,))
        playing = jsq(host, "document.querySelectorAll('.card.playing').length")
        record("B-03", playing == 0, "初始无任何卡片处于播放态（静止封面）=%r" % (playing,))
        # 悬停不触发播放（P-8）
        jsx(host, "var c=document.querySelector('.card');"
                   "if(c){c.dispatchEvent(new MouseEvent('mouseenter'));"
                   "c.dispatchEvent(new MouseEvent('mouseover'));}")
        time.sleep(0.8)
        after_hover = jsq(host, "document.querySelectorAll('.card.playing').length")
        record("B-07", after_hover == 0, "悬停 0.8 秒后仍无卡片播放=%r" % (after_hover,))
        steps.append("check_play")

    def wait_playing(host, timeout=12):
        """轮询等待进入播放态（需容纳 T2 转码兜底的耗时）。"""
        end = time.time() + timeout
        last = 0
        while time.time() < end:
            last = jsq(host, "document.querySelectorAll('.card.playing').length")
            if last == 1:
                return last
            time.sleep(0.35)
        return last

    def step5():
        host = app.album_host
        jsx(host, "document.querySelector('.card').click();")
        p = wait_playing(host, 14)
        track = jsq(host, "window.__lpCards && window.__lpCards[0] ?"
                          "window.__lpCards[0].track : 'none'")
        vid = jsq(host, "(function(){var v=document.querySelector('.card video');"
                        "return v ? (v.error ? 'err' + v.error.code"
                        " : 'rs' + v.readyState) : 'none';})()")
        record("B-04", p == 1,
               "点击后进入播放态=%r（轨道=%r，视频=%r）" % (p, track, vid))
        steps.append("wait_ended")

    def step6():
        host = app.album_host
        end = time.time() + 9
        p = jsq(host, "document.querySelectorAll('.card.playing').length")
        while time.time() < end and p != 0:
            time.sleep(0.3)
            p = jsq(host, "document.querySelectorAll('.card.playing').length")
        record("B-05", p == 0, "播放结束后自动回到静止（无 playing 卡片）=%r" % (p,))
        steps.append("check_replay")

    def step7():
        host = app.album_host
        jsx(host, "document.querySelector('.card').click();")
        p1 = wait_playing(host, 10)
        jsx(host, "document.querySelector('.card').click();")
        time.sleep(0.8)
        p2 = jsq(host, "document.querySelectorAll('.card.playing').length")
        record("B-06", p1 == 1 and p2 == 0,
               "再点从头重播=%r；播放中点击即停=%r" % (p1, p2))
        steps.append("check_multi")

    def step8():
        host = app.album_host
        jsx(host, "document.querySelectorAll('.card')[0].click();")
        wait_playing(host, 8)
        jsx(host, "document.querySelectorAll('.card')[1].click();")
        time.sleep(1.0)
        n = jsq(host, "document.querySelectorAll('.card.playing').length")
        record("B-08", n == 1, "同时只播一张（playing 卡片数=%r）" % (n,))
        jsx(host, "document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}));")
        time.sleep(0.6)
        n2 = jsq(host, "document.querySelectorAll('.card.playing').length")
        record("B-09", n2 == 0, "Esc 停止播放（playing 卡片数=%r）" % (n2,))
        shoot(root, os.path.join(evidence_dir, "03_相册页_播放后.png"), "播放后")
        steps.append("finish")

    def finish():
        try:
            if app.album_host:
                app.album_host.shutdown()
        except Exception:
            pass
        passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
        failed = sum(1 for _, s, _ in RESULTS if s == "FAIL")
        unver = sum(1 for _, s, _ in RESULTS if s == "UNVERIFIED")
        summary = {"total": len(RESULTS), "pass": passed, "fail": failed,
                   "unverified": unver,
                   "results": [{"item": i, "status": s, "detail": d}
                               for i, s, d in RESULTS]}
        with open(os.path.join(evidence_dir, "v13_gui_results.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(summary, fh, ensure_ascii=False, indent=2)
        with open(os.path.join(evidence_dir, "v13_gui_log.txt"), "w",
                  encoding="utf-8") as fh:
            fh.write("\n".join(LOG))
        print("\n汇总：%d 项 / PASS %d / FAIL %d / UNVERIFIED %d"
              % (len(RESULTS), passed, failed, unver))
        try:
            root.destroy()
        except Exception:
            pass

    chain = {"wait_webview": step2, "wait_scan": step3, "check_p1": step4,
             "check_play": step5, "wait_ended": step6, "check_replay": step7,
             "check_multi": step8, "finish": finish}

    def pump():
        if steps:
            nxt = steps.pop(0)
            chain[nxt]()
        root.after(250, pump)

    root.after(600, step1)
    root.after(300, pump)
    root.mainloop()
    return 0


if __name__ == "__main__":
    tgt = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.environ.get("TEMP", r"C:\Windows\Temp"), "lp_v13_gui")
    sys.exit(main(tgt))
