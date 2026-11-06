# -*- coding: utf-8 -*-
"""同一张卡片、同一页面，对比「长中文路径 URL」与「短路径 URL」的播放结果。

用于判定生产页面播放失败是否由路径长度/编码引起。
输出：同目录 probe_long_path_results.json
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
OUT = os.path.join(HERE, "probe_long_path_results.json")
SRC = os.path.join(TESTDIR, "work_acceptance", "源目录")
DST = os.path.join(TESTDIR, "work_acceptance", "输出目录")
SHORT_DIR = os.path.join(HERE, "sp")
SHORT_VIDEO = os.path.join(SHORT_DIR, "v.mp4")


def main():
    from importlib.machinery import SourceFileLoader
    import importlib.util
    spec = importlib.util.spec_from_loader(
        "lp_main_lp", SourceFileLoader("lp_main_lp",
                                       os.path.join(ROOT,
                                                    "LivePhoto_Backup.pyw")))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if os.path.isdir(SHORT_DIR):
        shutil.rmtree(SHORT_DIR, ignore_errors=True)
    os.makedirs(SHORT_DIR)
    shutil.copy2(os.path.join(ROOT, "测试样本", "IMG_0346.mp4"), SHORT_VIDEO)
    short_url = album_api.to_file_url(SHORT_VIDEO)

    import tkinter as tk
    root = tk.Tk()
    app = mod.App(root)
    root.update()
    app.dst_var.set(DST)
    app.src_var.set(SRC)
    root.update()
    app._switch_tab("album")
    h = app.album_host
    res = {"short_url": short_url, "cases": []}
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

        first = h.api.items[0]
        long_url = album_api.to_file_url(first.video_path)
        res["first_key"] = first.key
        res["long_url_len"] = len(long_url)
        res["path_len"] = len(first.video_path)
        res["visibility"] = h.web.evaluate_sync(
            "return document.visibilityState;", timeout=10)

        def try_url(tag, url):
            st = {"tag": tag, "url_len": len(url)}
            h.web.evaluate_sync(
                "window.__lpStopAll && window.__lpStopAll();"
                "window.__lpCards[0].tracks.video = %s;"
                "document.querySelectorAll('.card')[0].click();"
                "return 'clicked';" % json.dumps(url), timeout=15)
            end = time.time() + 16
            last = None
            while time.time() < end:
                raw = h.web.evaluate_sync(
                    "return (JSON.stringify((function(){var c=window.__lpCards[0];"
                    "var v=c&&c.video;return c?{state:c.state,track:c.track,"
                    "fail:c.failCode,rs:v?v.readyState:-1,"
                    "ns:v?v.networkState:-1,t:v?v.currentTime:-1,"
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
            st["result"] = last
            res["cases"].append(st)
            print("%-10s len=%4d -> %r" % (tag, len(url), last), flush=True)

        try_url("短路径", short_url)
        h.web.evaluate_sync("window.__lpStopAll && window.__lpStopAll();"
                            "return 1;", timeout=10)
        time.sleep(0.5)
        try_url("长路径", long_url)
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
