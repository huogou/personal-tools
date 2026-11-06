# -*- coding: utf-8 -*-
"""V1.3 自建 WebView2 环境 A/B 定位（真实视频播放）

独立 Edge 已证明同一 file:// 视频在本机可播（playing@179ms / readyState=4）。
本探针逐一隔离 V1.3 自建环境的差异项，找出使媒体管线失效的那一个：
  E0 当前生产配置：中文路径 user_data_dir + 无浏览器参数
  E1 纯 ASCII user_data_dir
  E2 中文 UDD + --disable-gpu
  E3 纯 ASCII UDD + --disable-gpu
  E4 中文 UDD + --autoplay-policy=no-user-gesture-required
  E5 中文 UDD + --allow-file-access-from-files --autoplay-policy=... --disable-gpu

输出：同目录 probe_env_ab_results.json
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time

import probe_playback as pp

HERE = pp.HERE
WORK = os.path.join(HERE, "work_env")
OUT = os.path.join(HERE, "probe_env_ab_results.json")
album_api = pp.album_api
album_webview = pp.album_webview


def main():
    if os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)
    video = os.path.join(WORK, "源目录 中文", "IMG_0346.mp4")
    os.makedirs(os.path.dirname(video))
    shutil.copy2(pp.SAMPLE, video)
    html_path = os.path.join(WORK, "probe.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(pp._HTML)
    page_url = "file:///" + html_path.replace("\\", "/")
    url = album_api.to_file_url(video)

    ascii_root = os.path.join(tempfile.gettempdir(), "lp_v13_ascii_udd")
    shutil.rmtree(ascii_root, ignore_errors=True)
    os.makedirs(ascii_root, exist_ok=True)
    cn_root = os.path.join(WORK, "用户数据 中文")

    configs = [
        ("E0-生产配置-中文UDD", cn_root, ""),
        ("E1-ASCII-UDD", os.path.join(ascii_root, "p1"), ""),
        ("E2-中文UDD-disable-gpu", os.path.join(cn_root, "p2"), "--disable-gpu"),
        ("E3-ASCII-UDD-disable-gpu", os.path.join(ascii_root, "p3"), "--disable-gpu"),
        ("E4-中文UDD-autoplay", os.path.join(cn_root, "p4"),
         "--autoplay-policy=no-user-gesture-required"),
        ("E5-中文UDD-组合", os.path.join(cn_root, "p5"),
         "--disable-gpu --allow-file-access-from-files "
         "--autoplay-policy=no-user-gesture-required"),
    ]

    import tkinter as tk
    root = tk.Tk()
    root.geometry("900x600")
    frame = tk.Frame(root, bg="#222")
    frame.pack(fill="both", expand=True)
    root.update()
    result = {"env": {"python": sys.version.split()[0],
                      "video_url": url, "page_url": page_url,
                      "ascii_udd_root": ascii_root}, "configs": []}
    box = {"code": 0}

    def run():
        try:
            for name, udd, args in configs:
                print("\n======== %s ========" % name, flush=True)
                os.makedirs(udd, exist_ok=True)
                host = album_webview.WebViewHost(browser_args=args)

                def on_msg(payload, _h=host):
                    try:
                        d = json.loads(payload)
                    except Exception:
                        return
                    if "__eval" in d:
                        _h.deliver_eval(d.get("__eval"), d.get("value"))

                host.on_message = on_msg
                ok = host.start(page_url, udd, timeout=40)
                entry = {"name": name, "udd": udd, "browser_args": args,
                         "webview_started": bool(ok),
                         "webview_error": host._error}
                if not ok:
                    entry["verdict"] = "BLOCKED"
                    result["configs"].append(entry)
                    continue
                attached = threading.Event()
                root.after(0, lambda _h=host: (_h.attach(frame), attached.set()))
                attached.wait(10)
                time.sleep(1.0)
                host.evaluate_sync(
                    "return window.__lpDiagStart(%s, %s, 'none');" %
                    (json.dumps(name, ensure_ascii=False),
                     json.dumps(url, ensure_ascii=False)), timeout=15)
                time.sleep(4.0)
                raw = host.evaluate_sync("return window.__lpDiagRead();", timeout=15)
                try:
                    st = json.loads(raw) if isinstance(raw, str) else (raw or {})
                except Exception:
                    st = {"raw": repr(raw)}
                entry["state"] = st
                evs = st.get("events") or []
                entry["verdict"] = "PLAYABLE" if (
                    any(e.startswith("playing@") for e in evs)
                    and st.get("readyState", 0) >= 2
                    and st.get("play") == "resolved") else "NOT_PLAYABLE"
                result["configs"].append(entry)
                print("%s -> %s | %s" % (
                    name, entry["verdict"],
                    json.dumps({"play": st.get("play"),
                                "readyState": st.get("readyState"),
                                "events": evs}, ensure_ascii=False)), flush=True)
                try:
                    root.after(0, host.stop)
                except Exception:
                    pass
                time.sleep(0.7)
        except Exception as e:
            result["error"] = "%s: %s" % (type(e).__name__, e)
            box["code"] = 1
        finally:
            with open(OUT, "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2)
            print("\n结果已写入：" + OUT, flush=True)
            try:
                root.after(0, root.destroy)
            except Exception:
                pass

    threading.Thread(target=run, daemon=True).start()
    root.mainloop()
    return box["code"]


if __name__ == "__main__":
    sys.exit(main())
