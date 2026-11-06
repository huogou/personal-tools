# -*- coding: utf-8 -*-
"""最小诊断：确认清理残留 WebView2 后，前端状态推送与网格渲染是否恢复。

输出：同目录 probe_frontend_state_results.json
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ACCEPT = os.path.dirname(HERE)
TESTDIR = os.path.join(ACCEPT, "测试")
sys.path.insert(0, TESTDIR)


def find_root():
    p = HERE
    while not os.path.exists(os.path.join(p, "album_webview.py")):
        q = os.path.dirname(p)
        if q == p:
            raise RuntimeError("root not found")
        p = q
    return p


ROOT = find_root()
sys.path.insert(0, ROOT)
OUT = os.path.join(HERE, "probe_frontend_state_results.json")
SRC = os.path.join(TESTDIR, "work_acceptance", "源目录")
DST = os.path.join(TESTDIR, "work_acceptance", "输出目录")


def main():
    from importlib.machinery import SourceFileLoader
    import importlib.util
    spec = importlib.util.spec_from_loader(
        "lp_main_state", SourceFileLoader("lp_main_state",
                                          os.path.join(ROOT,
                                                       "LivePhoto_Backup.pyw")))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    import tkinter as tk
    root = tk.Tk()
    app = mod.App(root)
    root.update()
    app.dst_var.set(DST)
    app.src_var.set(SRC)
    root.update()
    app._switch_tab("album")
    h = app.album_host
    res = {"src": SRC, "src_exists": os.path.isdir(SRC), "steps": []}
    try:
        h.api.set_source(SRC)          # 显式扫描（与 acceptance T-00 一致）
        end = time.time() + 60
        while time.time() < end and h.api.state != "A4":
            time.sleep(0.3)
        time.sleep(3.0)
        res["api_state"] = h.api.state
        res["items"] = len(h.api.items)

        def q(expr, t=15):
            v = h.web.evaluate_sync("return (%s);" % expr, timeout=t)
            res["steps"].append({"expr": expr, "value": v})
            return v

        res["S"] = q("JSON.stringify({state:S.state,album:S.album,"
                     "offset:S.offset,total:S.total})")
        res["cards"] = q("window.__lpCards ? window.__lpCards.length : -1")
        res["dom_cards"] = q("document.querySelectorAll('.card').length")
        res["has_webview"] = q("!!(window.chrome && window.chrome.webview)")
        res["user_agent"] = q("navigator.userAgent")
        # 关键：把窗口真正置顶并激活，再观察页面可见性（Chromium 会按窗口
        # 是否被遮挡/最小化决定 media pipeline 是否运行，仅 IsVisible=true 不够）
        res["visibility_before_foreground"] = q("document.visibilityState")
        root.lift()
        root.attributes("-topmost", True)
        root.focus_force()
        root.update()
        time.sleep(1.5)
        res["visibility_after_foreground"] = q("document.visibilityState")
        # 点击第 0 张，验证是否真实起播（与 acceptance T-01 同口径）
        h.web.evaluate_sync(
            "document.querySelectorAll('.card')[0].click(); return 'clicked';",
            timeout=15)
        end = time.time() + 18
        play = None
        while time.time() < end:
            raw = h.web.evaluate_sync(
                "return (JSON.stringify((function(){var c=window.__lpCards[0];"
                "var v=c&&c.video;return c?{state:c.state,track:c.track,"
                "rs:v?v.readyState:-1,t:v?v.currentTime:-1,"
                "playing:document.querySelectorAll('.card.playing').length,"
                "err:v&&v.error?v.error.code:null}:null;})()));", timeout=12)
            play = raw
            try:
                d = json.loads(raw) if isinstance(raw, str) else {}
            except Exception:
                d = {}
            if d.get("playing") == 1 and d.get("rs", 0) >= 2:
                break
            time.sleep(0.4)
        res["play_after_click"] = play
    except Exception as e:
        res["error"] = "%s: %s" % (type(e).__name__, e)
    finally:
        try:
            app.album_host.shutdown()
        except Exception:
            pass
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2)
        print(json.dumps(res, ensure_ascii=False, indent=2)[:2000], flush=True)
        try:
            root.destroy()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
