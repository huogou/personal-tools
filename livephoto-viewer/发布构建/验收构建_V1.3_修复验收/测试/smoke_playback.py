# -*- coding: utf-8 -*-
"""真实应用冒烟：修复 Controller.IsVisible 后，V1.3 相册页能否起播。

在真实 App（LivePhoto_Backup.pyw）+ 真实内嵌 WebView2 中取证，
不修改任何生产代码；结果写入同目录 smoke_playback_results.json。
"""
import importlib.util
import json
import os
import shutil
import sys
import time
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.abspath(__file__))


def find_root():
    p = HERE
    while True:
        if os.path.exists(os.path.join(p, "album_webview.py")):
            return p
        q = os.path.dirname(p)
        if q == p:
            raise RuntimeError("找不到项目根目录")
        p = q


ROOT = find_root()
sys.path.insert(0, ROOT)
SRC = os.path.join(ROOT, "LivePhoto_Backup.pyw")
WORK = os.path.join(HERE, "work_smoke")
OUT = os.path.join(HERE, "smoke_playback_results.json")


def load_module(name, path):
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def main():
    if os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    src = os.path.join(WORK, "源目录 带空格", "旅行 相册")
    os.makedirs(src)
    os.makedirs(os.path.join(WORK, "输出目录"))
    photo = os.path.join(ROOT, "测试样本", "IMG_0346.HEIC")
    video = os.path.join(ROOT, "测试样本", "IMG_0346.mp4")
    for base in ("IMG_0101", "IMG_0102"):
        shutil.copy2(photo, os.path.join(src, base + ".HEIC"))
        shutil.copy2(video, os.path.join(src, base + ".mp4"))

    mod = load_module("lp_main_smoke", SRC)
    import tkinter as tk
    root = tk.Tk()
    app = mod.App(root)
    root.update()
    app.src_var.set(os.path.join(WORK, "源目录 带空格"))
    app.dst_var.set(os.path.join(WORK, "输出目录"))
    root.update()
    app._switch_tab("album")

    result = {"env": {"src": src, "python": sys.version.split()[0]},
              "steps": []}
    steps = []

    def jsq(host, expr, timeout=15):
        return host.web.evaluate_sync("return (%s);" % expr, timeout=timeout)

    def step_wait():
        host = app.album_host
        ok = host is not None and host.web is not None and host.web.core is not None
        result["webview_ready"] = ok
        if not ok:
            result["error"] = "WebView2 未就绪: " + str(getattr(host.web, "_error", ""))
            steps.append("finish")
            return
        api = host.api
        api.set_source(os.path.join(WORK, "源目录 带空格"))
        time.sleep(2.0)
        result["api_state"] = api.state
        result["items"] = len(api.items)
        result["visibility"] = jsq(host, "document.visibilityState")
        result["controller_errors"] = list(host.web.controller_errors)
        print("visibility=%s state=%s items=%s" % (
            result["visibility"], result["api_state"], result["items"]), flush=True)
        steps.append("play")

    def step_play():
        host = app.album_host
        n = jsq(host, "document.querySelectorAll('.card').length")
        result["cards"] = n
        host.web.evaluate_sync(
            "document.querySelector('.card').click(); return 1;", timeout=15)
        end = time.time() + 12
        state = None
        while time.time() < end:
            state = jsq(host, "JSON.stringify({playing:document.querySelectorAll"
                              "('.card.playing').length,rs:(function(){var v="
                              "document.querySelector('.card video');return v?"
                              "v.readyState:-1;})(),t:(function(){var v="
                              "document.querySelector('.card video');return v?"
                              "v.currentTime:-1;})(),err:(function(){var v="
                              "document.querySelector('.card video');return v&&"
                              "v.error?v.error.code:null;})()})")
            try:
                st = json.loads(state)
            except Exception:
                st = {}
            if st.get("playing") == 1 and st.get("rs", 0) >= 2:
                result["steps"].append({"phase": "playing", "state": st})
                break
            time.sleep(0.3)
        result["final"] = state
        print("cards=%s final=%s" % (n, state), flush=True)
        steps.append("finish")

    def finish():
        try:
            if app.album_host:
                app.album_host.shutdown()
        except Exception:
            pass
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
        print("结果已写入：" + OUT, flush=True)
        try:
            root.destroy()
        except Exception:
            pass

    chain = {"wait": step_wait, "play": step_play, "finish": finish}

    def pump():
        if steps:
            chain[steps.pop(0)]()
        root.after(250, pump)

    root.after(1200, lambda: steps.append("wait"))
    root.after(300, pump)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
