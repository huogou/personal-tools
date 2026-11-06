# -*- coding: utf-8 -*-
"""检查 V1.3 自建 WebView2 控制器是否把页面判为后台页，并验证 IsVisible 修复效果。

输出：同目录 probe_visibility_results.json
"""
import json
import os
import shutil
import sys
import threading
import time

import probe_playback as pp

HERE = pp.HERE
WORK = os.path.join(HERE, "work_vis")
OUT = os.path.join(HERE, "probe_visibility_results.json")
album_api = pp.album_api
album_webview = pp.album_webview

_DOC_EXPR = ("JSON.stringify({visibility:document.visibilityState,"
             "hidden:document.hidden,hasFocus:document.hasFocus(),"
             "w:window.innerWidth,h:window.innerHeight,"
             "ua:navigator.userAgent})")


def main():
    if os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)
    video = os.path.join(WORK, "IMG_0346.mp4")
    shutil.copy2(pp.SAMPLE, video)
    page = os.path.join(WORK, "probe.html")
    with open(page, "w", encoding="utf-8") as fh:
        fh.write(pp._HTML)
    page_url = "file:///" + page.replace("\\", "/")
    url = album_api.to_file_url(video)

    import tkinter as tk
    root = tk.Tk()
    root.geometry("900x600")
    frame = tk.Frame(root, bg="#222")
    frame.pack(fill="both", expand=True)
    root.update()
    host = album_webview.WebViewHost()

    def on_msg(payload):
        try:
            d = json.loads(payload)
        except Exception:
            return
        if "__eval" in d:
            host.deliver_eval(d.get("__eval"), d.get("value"))

    host.on_message = on_msg
    result = {"env": {"video_url": url}, "steps": []}
    box = {"code": 0}

    def jsq(expr, timeout=15):
        return host.evaluate_sync("return (" + expr + ");", timeout=timeout)

    def play_case(tag):
        jsq("window.__lpDiagStart(%s, %s, 'none')" %
            (json.dumps(tag), json.dumps(url)), timeout=15)
        time.sleep(4.0)
        raw = jsq("window.__lpDiagRead()", timeout=15)
        try:
            st = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception:
            st = {"raw": repr(raw)}
        evs = st.get("events") or []
        st["verdict"] = "PLAYABLE" if any(
            e.startswith("playing@") for e in evs) else "NOT_PLAYABLE"
        result["steps"].append({"tag": tag, "state": st})
        print("[%s] %s %s" % (tag, st["verdict"],
                              json.dumps({"play": st.get("play"),
                                          "readyState": st.get("readyState"),
                                          "events": evs},
                                         ensure_ascii=False)), flush=True)
        return st

    def run():
        try:
            ok = host.start(page_url, os.path.join(WORK, "udd"), timeout=40)
            result["env"]["webview_started"] = bool(ok)
            if not ok:
                result["env"]["webview_error"] = host._error
                box["code"] = 1
                return
            attached = threading.Event()
            root.after(0, lambda: (host.attach(frame), attached.set()))
            attached.wait(10)
            time.sleep(1.0)

            doc = jsq(_DOC_EXPR)
            result["env"]["document_state"] = doc
            print("document: " + str(doc), flush=True)

            play_case("V0-before-IsVisible")

            # 所有 .NET 属性访问都必须排到 WebView2 的 STA 线程执行，
            # 跨线程直接读会导致 pythonnet 硬崩溃。
            info = {}

            def make_visible():
                try:
                    info["isvisible_before"] = bool(host.controller.IsVisible)
                except Exception as e:
                    info["before_err"] = str(e)
                try:
                    host.controller.IsVisible = True
                    info["isvisible_after"] = bool(host.controller.IsVisible)
                except Exception as e:
                    info["set_err"] = str(e)
                try:
                    from System.Drawing import Rectangle
                    host.controller.Bounds = Rectangle(0, 0, 880, 560)
                    info["bounds"] = "ok"
                except Exception as e:
                    info["bounds_err"] = str(e)

            with host._lock:
                host._task_queue.append(make_visible)
            time.sleep(1.5)
            result["env"]["controller_info"] = info
            result["env"]["document_state_after"] = jsq(_DOC_EXPR)
            print("controller: %s" % json.dumps(info, ensure_ascii=False),
                  flush=True)
            print("document_after: %s" %
                  str(result["env"]["document_state_after"]), flush=True)

            play_case("V1-after-IsVisible")
        except Exception as e:
            result["error"] = "%s: %s" % (type(e).__name__, e)
            box["code"] = 1
        finally:
            with open(OUT, "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2)
            print("\n结果已写入：" + OUT, flush=True)
            try:
                root.after(0, host.stop)
                root.after(0, root.destroy)
            except Exception:
                pass

    threading.Thread(target=run, daemon=True).start()
    root.mainloop()
    return box["code"]


if __name__ == "__main__":
    sys.exit(main())
