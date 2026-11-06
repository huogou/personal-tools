# -*- coding: utf-8 -*-
"""V1.3 播放修复方案 A/B 对照实验（真实 WebView2，不改生产 URL 逻辑）

对照三种最小候选，均以真实 <video> 的 readyState/playing 事件/play() Promise
是否 settle 为判据，选出唯一有证据的修复方案：
  C0 基线（当前 V1.3，无任何 WebView2 配置）
  C1 CoreWebView2EnvironmentOptions.AdditionalBrowserArguments
     = "--allow-file-access-from-files"
  C2 SetVirtualHostNameToFolderMapping（WebView2 内部拦截，零端口、零联网）
  C3 虚拟主机名映射 + 仍用 file:// 视频 URL（验证映射是否有全局副作用）

输出：同目录 probe_fix_ab_results.json
"""
import json
import os
import shutil
import sys
import threading
import time

import probe_playback as pp

HERE = pp.HERE
ROOT = pp.ROOT
album_api = pp.album_api
album_webview = pp.album_webview
WORK = pp.WORK
OUT = os.path.join(HERE, "probe_fix_ab_results.json")


def main():
    if os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    srcdir = os.path.join(WORK, "源目录 带空格", "旅行 相册 长路径" * 3)
    os.makedirs(srcdir)
    video = os.path.join(srcdir, "IMG_0346.mp4")
    shutil.copy2(pp.SAMPLE, video)
    html_path = os.path.join(WORK, "probe.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(pp._HTML)
    page_url = "file:///" + html_path.replace("\\", "/")

    file_url = album_api.to_file_url(video)
    vhost = "lp-probe.local"
    vhost_url = "https://%s/IMG_0346.mp4" % vhost

    configs = [
        ("C0-基线-无配置", {}, file_url),
        ("C1-allow-file-access",
         {"browser_args": "--allow-file-access-from-files"}, file_url),
        ("C2-虚拟主机名映射",
         {"virtual_hosts": [(vhost, srcdir)]}, vhost_url),
        ("C3-虚拟映射仍用fileURL",
         {"virtual_hosts": [(vhost, srcdir)]}, file_url),
    ]

    import tkinter as tk
    root = tk.Tk()
    root.geometry("900x600")
    frame = tk.Frame(root, bg="#222")
    frame.pack(fill="both", expand=True)
    root.update()

    result = {"env": {
        "python": sys.version.split()[0],
        "webview2_runtime": album_webview.webview2_runtime_present(),
        "video_path": video,
        "file_url": file_url,
        "vhost_url": vhost_url,
    }, "configs": []}
    box = {"code": 0}

    def run():
        try:
            for idx, (name, kwargs, url) in enumerate(configs):
                print("\n======== %s ========" % name, flush=True)
                host = album_webview.WebViewHost(
                    browser_args=kwargs.get("browser_args", ""),
                    virtual_hosts=kwargs.get("virtual_hosts"))

                def on_msg(payload, _h=host):
                    try:
                        d = json.loads(payload)
                    except Exception:
                        return
                    if "__eval" in d:
                        _h.deliver_eval(d.get("__eval"), d.get("value"))

                host.on_message = on_msg
                udd = os.path.join(WORK, "udd%d" % idx)
                ok = host.start(page_url, udd, timeout=40)
                entry = {"name": name, "kwargs": {
                    k: (v if k == "browser_args" else [list(x) for x in v])
                    for k, v in kwargs.items()},
                    "url": url, "webview_started": bool(ok),
                    "webview_error": host._error}
                if not ok:
                    entry["verdict"] = "BLOCKED"
                    result["configs"].append(entry)
                    print(json.dumps(entry, ensure_ascii=False, indent=2), flush=True)
                    box["code"] = 1
                    continue

                attached = threading.Event()

                def do_attach(_h=host):
                    try:
                        _h.attach(frame)
                    finally:
                        attached.set()

                root.after(0, do_attach)
                attached.wait(10)
                time.sleep(1.0)

                expr = "return window.__lpDiagStart(%s, %s, 'none');" % (
                    json.dumps(name, ensure_ascii=False),
                    json.dumps(url, ensure_ascii=False))
                host.evaluate_sync(expr, timeout=10)
                time.sleep(4.0)
                raw = host.evaluate_sync("return window.__lpDiagRead();", timeout=10)
                try:
                    st = json.loads(raw) if isinstance(raw, str) else (raw or {})
                except Exception:
                    st = {"raw": repr(raw)}
                entry["state"] = st
                entry["virtual_host_errors"] = list(host.virtual_host_errors)
                # 判定：真实起播必须有 playing 事件 + readyState>=2 + play() 已 resolve
                evs = st.get("events") or []
                entry["verdict"] = "PLAYABLE" if (
                    any(e.startswith("playing@") for e in evs)
                    and st.get("readyState", 0) >= 2
                    and st.get("play") == "resolved") else "NOT_PLAYABLE"
                result["configs"].append(entry)
                print(json.dumps(entry, ensure_ascii=False, indent=2), flush=True)
                try:
                    root.after(0, host.stop)
                except Exception:
                    pass
                time.sleep(0.8)
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
