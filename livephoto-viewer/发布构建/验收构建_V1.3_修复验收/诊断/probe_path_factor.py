# -*- coding: utf-8 -*-
"""定位「长路径播放失败」的诱因：路径长度 vs 空格/中文。

同一页面、同一张卡片，仅替换 video URL 后点击，观察是否起播。
输出：同目录 probe_path_factor_results.json
"""
import json
import os
import shutil
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
import album_api  # noqa: E402
OUT = os.path.join(HERE, "probe_path_factor_results.json")
SRC = os.path.join(TESTDIR, "work_acceptance", "源目录")
DST = os.path.join(TESTDIR, "work_acceptance", "输出目录")
BASE = os.path.join(HERE, "sp2")
SAMPLE = os.path.join(ROOT, "测试样本", "IMG_0346.mp4")


def build_cases():
    if os.path.isdir(BASE):
        shutil.rmtree(BASE, ignore_errors=True)
    os.makedirs(BASE)
    cases = []
    a = os.path.join(BASE, "short")
    os.makedirs(a)
    p1 = os.path.join(a, "v.mp4")
    shutil.copy2(SAMPLE, p1)
    cases.append(("短-无空格", p1))
    b = os.path.join(BASE, "中 文 空 格 目 录")
    os.makedirs(b)
    p2 = os.path.join(b, "v.mp4")
    shutil.copy2(SAMPLE, p2)
    cases.append(("短-含中文空格", p2))
    c = os.path.join(BASE, "a" * 130)
    os.makedirs(c)
    p3 = os.path.join(c, "v.mp4")
    shutil.copy2(SAMPLE, p3)
    cases.append(("长-纯ASCII", p3))
    d = os.path.join(BASE, "长" * 60 + " 空格 目录")
    os.makedirs(d)
    p4 = os.path.join(d, "v.mp4")
    shutil.copy2(SAMPLE, p4)
    cases.append(("长-含中文空格", p4))
    return cases


def main():
    from importlib.machinery import SourceFileLoader
    import importlib.util
    spec = importlib.util.spec_from_loader(
        "lp_main_pf", SourceFileLoader("lp_main_pf",
                                       os.path.join(ROOT,
                                                    "LivePhoto_Backup.pyw")))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cases = build_cases()
    import tkinter as tk
    root = tk.Tk()
    app = mod.App(root)
    root.update()
    app.dst_var.set(DST)
    app.src_var.set(SRC)
    root.update()
    app._switch_tab("album")
    h = app.album_host
    res = {"cases": []}
    try:
        h.api.set_source(SRC)
        end = time.time() + 60
        while time.time() < end and h.api.state != "A4":
            time.sleep(0.3)
        time.sleep(2.0)
        root.lift()
        root.attributes("-topmost", True)
        root.focus_force()
        root.update()
        res["visibility"] = h.web.evaluate_sync(
            "return document.visibilityState;", timeout=10)

        for tag, path in cases:
            url = album_api.to_file_url(path)
            item = {"tag": tag, "path_len": len(path), "url_len": len(url),
                    "exists": os.path.exists(path)}
            h.web.evaluate_sync(
                "window.__lpStopAll && window.__lpStopAll();"
                "window.__lpCards[0].tracks.video = %s;"
                "document.querySelectorAll('.card')[0].click();"
                "return 'clicked';" % json.dumps(url), timeout=15)
            end = time.time() + 13
            last = None
            while time.time() < end:
                raw = h.web.evaluate_sync(
                    "return (JSON.stringify((function(){var c=window.__lpCards[0];"
                    "var v=c&&c.video;return c?{state:c.state,track:c.track,"
                    "fail:c.failCode,rs:v?v.readyState:-1,t:v?v.currentTime:-1,"
                    "playing:document.querySelectorAll('.card.playing').length,"
                    "err:v&&v.error?v.error.code:null}:null;})()));", timeout=12)
                last = raw
                try:
                    d = json.loads(raw) if isinstance(raw, str) else {}
                except Exception:
                    d = {}
                if d.get("playing") == 1 and d.get("rs", 0) >= 2:
                    break
                if d.get("state") == "failed":
                    break
                time.sleep(0.35)
            item["result"] = last
            item["playing"] = bool(
                isinstance(last, str) and '"playing":1' in last.replace(" ", ""))
            res["cases"].append(item)
            print("%-14s path=%3d url=%3d -> %r" %
                  (tag, item["path_len"], item["url_len"], last), flush=True)
            h.web.evaluate_sync("window.__lpStopAll && window.__lpStopAll();"
                                "return 1;", timeout=10)
            time.sleep(0.4)
    except Exception as e:
        res["error"] = "%s: %s" % (type(e).__name__, e)
        print("ERROR " + res["error"], flush=True)
    finally:
        try:
            app.album_host.shutdown()
        except Exception:
            pass
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=2)
        print("written: " + OUT, flush=True)
        try:
            root.destroy()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
