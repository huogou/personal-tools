# -*- coding: utf-8 -*-
"""V1.3 播放故障分层定位探针（真实 WebView2）

A/B 已证明 file:// 权限参数与虚拟主机名映射都不足以让 <video> 起播。
本探针继续分层，判断卡点位于「子资源加载层」还是「媒体管线层」：
  S1 <img> 加载 file:// 本地图片
  S2 <img> 加载虚拟主机名 https:// 本地图片
  S3 fetch() 虚拟主机名资源
  S4 <video> 使用 blob: URL（Python 读文件字节 → base64 → Blob）
  S5 <video> 使用 data: URL

输出：同目录 probe_media_stack_results.json
"""
import base64
import json
import os
import shutil
import sys
import threading
import time

import probe_playback as pp

HERE = pp.HERE
WORK = os.path.join(HERE, "work_stack")
OUT = os.path.join(HERE, "probe_media_stack_results.json")
album_api = pp.album_api
album_webview = pp.album_webview

_EXTRA = r"""
window.__lpStack = {};
function __lpNow(st){ return Math.round(performance.now() - st.t0); }
window.__lpStackImg = function(name, url){
  var st = {name:name, kind:'img', t0:performance.now(), url:url,
            events:[], complete:false, w:0, h:0};
  window.__lpStack[name] = st;
  var im = new Image();
  im.onload = function(){ st.events.push('load@'+__lpNow(st));
    st.complete=true; st.w=im.naturalWidth; st.h=im.naturalHeight; };
  im.onerror = function(){ st.events.push('error@'+__lpNow(st)); };
  im.style.cssText='width:120px;height:120px';
  document.body.appendChild(im);
  im.src = url;
  return 'started';
};
window.__lpStackFetch = function(name, url){
  var st = {name:name, kind:'fetch', t0:performance.now(), url:url,
            events:[], ok:false, len:0, err:null, status:null};
  window.__lpStack[name] = st;
  fetch(url).then(function(r){ st.status=r.status; return r.arrayBuffer(); })
    .then(function(b){ st.ok=true; st.len=b.byteLength;
                       st.events.push('ok@'+__lpNow(st)); })
    .catch(function(e){ st.err=String(e); st.events.push('err@'+__lpNow(st)); });
  return 'started';
};
window.__lpStackVideo = function(name, b64, kind){
  var st = {name:name, kind:kind, t0:performance.now(), events:[],
            play:'pending', playMsg:'', readyState:0, networkState:0,
            error:null, duration:null, currentTime:null, paused:null,
            bytes:0};
  window.__lpStack[name] = st;
  var old = window.__lpStackVideoEl;
  if (old){ try{old.pause();old.removeAttribute('src');old.load();old.remove();}catch(e){} }
  try {
    var bin = atob(b64);
    var arr = new Uint8Array(bin.length);
    for (var i=0; i<bin.length; i++){ arr[i]=bin.charCodeAt(i); }
    st.bytes = arr.length;
    var blob = new Blob([arr], {type:'video/mp4'});
    var url = (kind === 'blob') ? URL.createObjectURL(blob)
                                : 'data:video/mp4;base64,' + b64;
    var v = document.createElement('video');
    v.setAttribute('playsinline',''); v.preload='auto';
    v.style.cssText='width:320px;height:240px;background:#000';
    document.body.appendChild(v);
    window.__lpStackVideoEl = v;
    function snap(){
      st.readyState=v.readyState; st.networkState=v.networkState;
      st.error = v.error ? {code:v.error.code,message:v.error.message} : null;
      st.duration = isNaN(v.duration)?null:v.duration;
      st.currentTime=v.currentTime; st.paused=v.paused;
    }
    ['loadstart','loadedmetadata','loadeddata','canplay','canplaythrough',
     'playing','progress','stalled','suspend','waiting','error','ended'
    ].forEach(function(ev){
      v.addEventListener(ev, function(){
        st.events.push(ev+'@'+__lpNow(st)); snap(); });
    });
    v.src = url;
    try {
      var p = v.play();
      if (p && p.then){
        p.then(function(){st.play='resolved';snap();},
               function(e){st.play='rejected:'+(e&&e.name);
                           st.playMsg=String(e&&e.message);snap();});
      } else { st.play='no-promise'; }
    } catch(e){ st.play='throw:'+e.name; st.playMsg=String(e.message); }
    snap();
    return 'started:'+arr.length;
  } catch(e){ st.err=String(e); return 'ERR:'+e; }
};
window.__lpStackRead = function(name){
  return JSON.stringify(window.__lpStack[name]);
};
"""

_HTML = pp._HTML.replace("</script></body></html>", _EXTRA + "\n</script></body></html>")


def main():
    if os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)
    srcdir = os.path.join(WORK, "源目录 带空格", "长路径 子目录" * 3)
    os.makedirs(srcdir)
    video = os.path.join(srcdir, "IMG_0346.mp4")
    shutil.copy2(pp.SAMPLE, video)
    jpg = os.path.join(srcdir, "IMG_0346.jpg")
    shutil.copy2(os.path.join(pp.ROOT, "测试样本", "网页查看器", "thumb",
                              "IMG_0346.jpg"), jpg)
    html_path = os.path.join(WORK, "probe.html")
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(_HTML)
    page_url = "file:///" + html_path.replace("\\", "/")

    with open(video, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")

    vhost = "lp-stack.local"
    file_video = album_api.to_file_url(video)
    file_jpg = album_api.to_file_url(jpg)
    vhost_jpg = "https://%s/IMG_0346.jpg" % vhost
    vhost_video = "https://%s/IMG_0346.mp4" % vhost

    import tkinter as tk
    root = tk.Tk()
    root.geometry("900x600")
    frame = tk.Frame(root, bg="#222")
    frame.pack(fill="both", expand=True)
    root.update()

    host = album_webview.WebViewHost(virtual_hosts=[(vhost, srcdir)])

    def on_msg(payload):
        try:
            d = json.loads(payload)
        except Exception:
            return
        if "__eval" in d:
            host.deliver_eval(d.get("__eval"), d.get("value"))

    host.on_message = on_msg
    result = {"env": {
        "python": sys.version.split()[0],
        "video_bytes": len(base64.b64decode(b64)),
        "file_video": file_video, "vhost_video": vhost_video,
    }, "cases": []}
    box = {"code": 0}

    def jsq(expr, timeout=20):
        return host.evaluate_sync("return (" + expr + ");", timeout=timeout)

    def run():
        try:
            ok = host.start(page_url, os.path.join(WORK, "udd"), timeout=40)
            result["env"]["webview_started"] = bool(ok)
            result["env"]["webview_error"] = host._error
            result["env"]["virtual_host_errors"] = []
            if not ok:
                box["code"] = 1
                return
            attached = threading.Event()
            root.after(0, lambda: (host.attach(frame), attached.set()))
            attached.wait(10)
            time.sleep(1.0)
            result["env"]["virtual_host_errors"] = list(host.virtual_host_errors)

            jobs = [
                ("S1-img-file", "__lpStackImg('S1-img-file', %s)" %
                 json.dumps(file_jpg), 2.5),
                ("S2-img-vhost", "__lpStackImg('S2-img-vhost', %s)" %
                 json.dumps(vhost_jpg), 2.5),
                ("S3-fetch-vhost", "__lpStackFetch('S3-fetch-vhost', %s)" %
                 json.dumps(vhost_video), 3.0),
                ("S4-video-blob", "__lpStackVideo('S4-video-blob', %s, 'blob')" %
                 json.dumps(b64), 5.0),
                ("S5-video-dataurl", "__lpStackVideo('S5-video-dataurl', %s, 'data')" %
                 json.dumps(b64), 5.0),
                ("S6-video-vhost", None, 4.0),
            ]
            for name, expr, wait in jobs:
                if expr is not None:
                    r = jsq(expr, timeout=30)
                else:
                    r = jsq("__lpDiagStart(%s, %s, 'none')" %
                            (json.dumps(name), json.dumps(vhost_video)), timeout=15)
                time.sleep(wait)
                if name == "S6-video-vhost":
                    raw = jsq("__lpDiagRead()", timeout=15)
                else:
                    raw = jsq("__lpStackRead(%s)" % json.dumps(name), timeout=15)
                try:
                    st = json.loads(raw) if isinstance(raw, str) else (raw or {})
                except Exception:
                    st = {"raw": repr(raw)}
                st = st or {}
                st["start_reply"] = r if isinstance(r, str) else repr(r)
                evs = st.get("events") or []
                st["verdict"] = ("PLAYABLE" if any(
                    e.startswith("playing@") for e in evs) else
                    ("LOADED" if st.get("ok") or st.get("complete") else
                     "NOT_PLAYABLE"))
                result["cases"].append(st)
                print("\n[%s] %s\n%s" % (
                    name, st["verdict"],
                    json.dumps({k: v for k, v in st.items()
                                if k not in ("url",)}, ensure_ascii=False)),
                    flush=True)
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
