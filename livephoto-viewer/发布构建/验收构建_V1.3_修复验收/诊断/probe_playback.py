# -*- coding: utf-8 -*-
"""V1.3 播放故障根因诊断探针（真实 WebView2 控件，只读）

用途：在**不修改任何现有源码**的前提下，于真实内嵌 WebView2 中直接观察
<video> 对本地 file:// 视频的加载/播放行为，判定 readyState=0 的直接原因。

输出：同目录 probe_playback_results.json
用法：.venv-build\\Scripts\\python.exe 诊断\\probe_playback.py
"""
import json
import os
import shutil
import sys
import threading
import time
import urllib.parse

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
import album_api          # noqa: E402  复用生产 URL 生成函数
import album_webview      # noqa: E402

WORK = os.path.join(HERE, "work")
SAMPLE = os.path.join(ROOT, "测试样本", "IMG_0346.mp4")

_HTML = r"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>playback probe</title></head><body style="background:#222;color:#eee">
<div id="out">probe</div>
<script>
"use strict";
window.__lpEval = function(token, value){
  if (window.chrome && window.chrome.webview){
    window.chrome.webview.postMessage(JSON.stringify({__eval: token, value: value}));
  }
};
window.__lpDiagState = null;
window.__lpDiagVideo = null;
function snap(st, v){
  st.readyState = v.readyState;
  st.networkState = v.networkState;
  st.currentSrc = v.currentSrc;
  st.error = v.error ? {code: v.error.code, message: v.error.message} : null;
  st.paused = v.paused;
  st.currentTime = v.currentTime;
  st.duration = isNaN(v.duration) ? null : v.duration;
  st.at = Math.round(performance.now() - st.t0);
}
window.__lpDiagStart = function(name, url, mode){
  var old = window.__lpDiagVideo;
  if (old){ try{ old.pause(); old.removeAttribute('src'); old.load(); old.remove(); }catch(e){} }
  var v = document.createElement('video');
  v.setAttribute('playsinline','');
  v.setAttribute('preload', mode === 'auto' ? 'auto' : 'none');
  if (mode === 'muted'){ v.muted = true; }
  v.style.cssText = 'width:320px;height:240px;background:#000';
  document.body.appendChild(v);
  window.__lpDiagVideo = v;
  var st = {
    name: name, url: url, mode: mode, t0: performance.now(),
    events: [], play: 'pending', playMsg: '',
    ua: (navigator.userActivation) ? navigator.userActivation.isActive : 'n/a',
    uaEver: (navigator.userActivation) ? navigator.userActivation.hasBeenActive : 'n/a',
    canPlayH264: v.canPlayType('video/mp4; codecs="avc1.42E01E"'),
    canPlayMP4: v.canPlayType('video/mp4'),
    readyState: 0, networkState: 0, error: null, currentSrc: '',
    paused: null, currentTime: null, duration: null, at: 0
  };
  window.__lpDiagState = st;
  ['loadstart','loadedmetadata','loadeddata','canplay','canplaythrough',
   'playing','progress','stalled','suspend','waiting','error','abort','emptied','ended'
  ].forEach(function(ev){
    v.addEventListener(ev, function(){
      st.events.push(ev + '@' + Math.round(performance.now() - st.t0));
      snap(st, v);
    });
  });
  v.src = url;
  if (mode === 'auto'){ try { v.load(); } catch(e){} }
  try {
    var p = v.play();
    if (p && p.then){
      p.then(function(){ st.play = 'resolved'; snap(st, v); },
             function(e){ st.play = 'rejected:' + (e && e.name);
                          st.playMsg = String(e && e.message); snap(st, v); });
    } else { st.play = 'no-promise'; }
  } catch(e){ st.play = 'throw:' + e.name; st.playMsg = String(e.message); }
  snap(st, v);
  return 'started';
};
window.__lpDiagRead = function(){ return JSON.stringify(window.__lpDiagState); };
</script></body></html>"""


def to_url(path):
    return album_api.to_file_url(path)


def main():
    if os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    # 中文 + 空格 + 较长路径样本
    srcdir = os.path.join(WORK, "源目录 带空格", "旅行 相册 子目录" * 3)
    os.makedirs(srcdir)
    video = os.path.join(srcdir, "IMG_0346.mp4")
    shutil.copy2(SAMPLE, video)

    html_path = os.path.join(WORK, "probe.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(_HTML)
    page_url = "file:///" + html_path.replace("\\", "/")

    host = album_webview.WebViewHost(on_message=None)

    def on_msg(payload):
        try:
            data = json.loads(payload)
        except Exception:
            return
        if "__eval" in data:
            host.deliver_eval(data.get("__eval"), data.get("value"))

    host.on_message = on_msg

    # 真实可见窗口：WebView2 控制器在隐藏窗口下不会正常渲染/加载媒体，
    # 因此按生产路径用 Tk 主窗口承载并 attach（与 test_v13_gui.py 同构）。
    import tkinter as tk
    root = tk.Tk()
    root.geometry("900x600")
    frame = tk.Frame(root, bg="#222")
    frame.pack(fill="both", expand=True)
    root.update()
    box = {"exit_code": 0}

    result = {"env": {
        "python": sys.version.split()[0],
        "webview2_runtime": album_webview.webview2_runtime_present(),
        "page_url": page_url,
        "video_path": video,
        "video_size": os.path.getsize(video),
        "video_url_production_fn": to_url(video),
    }, "cases": []}

    url = to_url(video)
    # 相对路径（与页面同目录树），用于区分「file:// 权限」与「URL 编码」问题
    rel_url = urllib.parse.quote(
        os.path.relpath(video, os.path.dirname(html_path)).replace("\\", "/"),
        safe="/")

    cases = [
        ("A-生产路径-file-none", url, "none"),
        ("B-file-auto-load", url, "auto"),
        ("C-file-muted", url, "muted"),
        ("D-相对路径", rel_url, "none"),
    ]

    def run_tests():
        try:
            ok = host.start(page_url, os.path.join(WORK, "udd"), timeout=40)
            result["env"]["webview_started"] = bool(ok)
            result["env"]["webview_error"] = host._error
            print(json.dumps(result["env"], ensure_ascii=False, indent=2))
            if not ok:
                box["exit_code"] = 1
                return
            attached = threading.Event()

            def do_attach():
                try:
                    host.attach(frame)
                finally:
                    attached.set()

            root.after(0, do_attach)
            attached.wait(10)
            time.sleep(1.2)

            for name, u, mode in cases:
                expr = "return window.__lpDiagStart(%s, %s, %s);" % (
                    json.dumps(name, ensure_ascii=False),
                    json.dumps(u, ensure_ascii=False),
                    json.dumps(mode))
                start = host.evaluate_sync(expr, timeout=10)
                time.sleep(3.5)
                raw = host.evaluate_sync("return window.__lpDiagRead();", timeout=10)
                try:
                    st = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    st = {"raw": repr(raw)}
                st = st or {}
                st["start_reply"] = start
                result["cases"].append(st)
                print("\n[%s]\n%s" % (name, json.dumps(st, ensure_ascii=False, indent=2)))
        except Exception as e:
            result["error"] = "%s: %s" % (type(e).__name__, e)
            box["exit_code"] = 1
        finally:
            try:
                root.after(0, host.stop)
            except Exception:
                pass
            out = os.path.join(HERE, "probe_playback_results.json")
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2)
            print("\n结果已写入：" + out)
            try:
                root.after(0, root.destroy)
            except Exception:
                pass

    threading.Thread(target=run_tests, daemon=True).start()
    root.mainloop()
    return box["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
