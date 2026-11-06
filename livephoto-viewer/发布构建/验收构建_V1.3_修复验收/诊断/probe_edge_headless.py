# -*- coding: utf-8 -*-
"""对照组：系统独立 Edge（同一 Chromium 内核，非本应用内嵌方式）能否播放同一 file:// 视频。

用于区分「本机 Chromium/系统媒体能力不可用」与「V1.3 自建 WebView2 控制器不可用」。
输出：同目录 probe_edge_headless_results.json
"""
import html
import json
import os
import re
import shutil
import subprocess
import sys

import probe_playback as pp

HERE = pp.HERE
WORK = os.path.join(HERE, "work_edge")
OUT = os.path.join(HERE, "probe_edge_headless_results.json")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

_TEMPLATE = r"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>edge probe</title></head>
<body data-probe="PENDING">
<video id="v" preload="auto" playsinline style="width:320px;height:240px"></video>
<script>
var st={events:[],play:'pending',playMsg:'',readyState:0,networkState:0,
        error:null,duration:null,currentTime:null,canPlay:null,t0:Date.now()};
var v=document.getElementById('v');
function flush(){ document.body.setAttribute('data-probe', JSON.stringify(st)); }
function snap(){
  st.readyState=v.readyState; st.networkState=v.networkState;
  st.error=v.error?{code:v.error.code,message:v.error.message}:null;
  st.duration=isNaN(v.duration)?null:v.duration;
  st.currentTime=v.currentTime; flush();
}
['loadstart','loadedmetadata','loadeddata','canplay','canplaythrough','playing',
 'progress','stalled','suspend','waiting','error','ended'].forEach(function(ev){
  v.addEventListener(ev,function(){st.events.push(ev+'@'+(Date.now()-st.t0));snap();});
});
st.canPlay=v.canPlayType('video/mp4; codecs="avc1.42E01E"');
v.src=__URL__;
try{
  var p=v.play();
  if(p&&p.then){p.then(function(){st.play='resolved';snap();},
                       function(e){st.play='rejected:'+(e&&e.name);
                                   st.playMsg=String(e&&e.message);snap();});}
  else{st.play='no-promise';}
}catch(e){st.play='throw:'+e.name;st.playMsg=String(e.message);}
snap();
setTimeout(flush,6000);
</script></body></html>"""


def main():
    if not os.path.exists(EDGE):
        print("找不到 Edge：" + EDGE)
        return 1
    if os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)
    video = os.path.join(WORK, "IMG_0346.mp4")
    shutil.copy2(pp.SAMPLE, video)
    url = pp.album_api.to_file_url(video)
    page = os.path.join(WORK, "edge_probe.html")
    with open(page, "w", encoding="utf-8") as fh:
        fh.write(_TEMPLATE.replace("__URL__", json.dumps(url)))

    args = [EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", "--disable-extensions",
            "--autoplay-policy=no-user-gesture-required",
            "--allow-file-access-from-files",
            "--virtual-time-budget=9000",
            "--user-data-dir=" + os.path.join(WORK, "udd"),
            "--dump-dom", "file:///" + page.replace("\\", "/")]
    try:
        r = subprocess.run(args, capture_output=True, timeout=90)
        dom = r.stdout.decode("utf-8", "replace")
        err = r.stderr.decode("utf-8", "replace")[-1500:]
    except Exception as e:
        dom, err, r = "", str(e), None
    m = re.search(r'data-probe="([^"]*)"', dom)
    state = None
    if m:
        try:
            state = json.loads(html.unescape(m.group(1)))
        except Exception:
            state = {"raw": m.group(1)}
    evs = (state or {}).get("events") or []
    verdict = ("PLAYABLE" if any(e.startswith("playing@") for e in evs)
               else "NOT_PLAYABLE")
    result = {
        "env": {"edge": EDGE, "url": url,
                "exit_code": getattr(r, "returncode", None),
                "stderr_tail": err},
        "state": state, "verdict": verdict,
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
