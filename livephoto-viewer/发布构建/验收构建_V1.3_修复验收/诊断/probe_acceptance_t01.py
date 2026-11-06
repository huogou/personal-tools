# -*- coding: utf-8 -*-
"""只读诊断：复现 acceptance_v13_fix.py 的 T-01，定位其失败根因。

不修改任何被测源码与验收脚本，只复用其语料构造并额外打印前端状态。
输出：同目录 probe_acceptance_t01_results.json
"""
import importlib.util
import json
import os
import sys
import time
from importlib.machinery import SourceFileLoader

HERE = os.path.dirname(os.path.abspath(__file__))
TESTDIR = os.path.join(os.path.dirname(HERE), "测试")
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
spec = importlib.util.spec_from_file_location(
    "acc", os.path.join(TESTDIR, "acceptance_v13_fix.py"))
acc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acc)
OUT = os.path.join(HERE, "probe_acceptance_t01_results.json")


def main():
    corpus = acc.build_corpus()
    res = {"corpus": {"pairs": corpus["pairs_total"],
                      "long": len(corpus["a_longest_path"])}, "steps": []}
    mod = acc.load_module("lp_main_probe", os.path.join(ROOT,
                                                        "LivePhoto_Backup.pyw"))
    import tkinter as tk
    root = tk.Tk()
    app = mod.App(root)
    root.update()
    app.dst_var.set(acc.DST_DIR)
    app.src_var.set(acc.SRC_DIR)
    root.update()
    app._switch_tab("album")
    h = app.album_host
    web = h.web

    def jsq(expr, timeout=20):
        t0 = time.time()
        v = web.evaluate_sync("return (%s);" % expr, timeout=timeout)
        return {"value": v, "ms": int((time.time() - t0) * 1000)}

    def step(name, expr):
        r = jsq(expr)
        r["name"] = name
        res["steps"].append(r)
        print("%-28s %6d ms  %r" % (name, r["ms"], r["value"])[:400], flush=True)
        return r["value"]

    try:
        end = time.time() + 60
        while time.time() < end and h.api.state != "A4":
            time.sleep(0.3)
        time.sleep(2.5)
        res["api_state"] = h.api.state
        res["items"] = len(h.api.items)
        step("visibility", "document.visibilityState")
        step("cards_len", "window.__lpCards ? window.__lpCards.length : -1")
        step("dom_cards", "document.querySelectorAll('.card').length")
        step("S_state", "JSON.stringify({state:S.state,album:S.album,"
                        "offset:S.offset,total:S.total,busy:S.loadingMore})")
        step("first_key", "window.__lpCards[0] ? window.__lpCards[0].key : null")
        key = "A_常规/" + corpus["long_name"] + "/img_a001"
        res["probe_key"] = key
        step("findIndex", "window.__lpCards.findIndex(function(c){"
                          "return c.key===%s;})" % json.dumps(key,
                                                             ensure_ascii=False))
        step("card0_info", "JSON.stringify((function(){var c=window.__lpCards[0];"
                           "return c?{key:c.key,state:c.state,"
                           "hasVideo:!!c.video}:null;})())")
        # 点第 0 张（DOM 事件），观察起播
        step("click0", "document.querySelectorAll('.card')[0].click(), 'ok'")
        end = time.time() + 12
        last = None
        while time.time() < end:
            r = jsq("JSON.stringify((function(){var c=window.__lpCards[0];"
                    "var v=c&&c.video;return c?{state:c.state,track:c.track,"
                    "rs:v?v.readyState:-1,t:v?v.currentTime:-1,"
                    "playing:document.querySelectorAll('.card.playing').length,"
                    "err:v&&v.error?v.error.code:null}:null;})())", timeout=12)
            last = r
            try:
                d = json.loads(r["value"]) if isinstance(r["value"], str) else {}
            except Exception:
                d = {}
            if d.get("playing") == 1 and d.get("rs", 0) >= 2:
                break
            time.sleep(0.4)
        res["after_click"] = last
        print("after_click: %r" % (last,), flush=True)
    except Exception as e:
        res["error"] = "%s: %s" % (type(e).__name__, e)
        print("ERROR: " + res["error"], flush=True)
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
