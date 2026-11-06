# -*- coding: utf-8 -*-
"""实况照片备份查看器 V1.3 · 相册页前端（生成 HTML/CSS/JS）

职责：生成「相册」页的静态页面（分类栏 + 工具条 + 网格 + 状态条），
实现 8 态状态机与播放契约 P-1…P-10。

设计依据：``V1.3设计\\03_V1.3_客户端浏览页布局与组件.md``（布局/状态机/桥接 API）、
``05_V1.3_播放引擎与媒体兼容规范.md``（播放契约）、
``06_V1.3_视觉规范增补.md``（§三/§四/§四.1 深色侧色值）、
``07_V1.3_文案与异常提示清单.md``（V-01…V-21 文案原文）。

关键契约（不可妥协）：
    P-1 默认静止封面    P-2 点击才播        P-3 播完回静止
    P-4 再点从头重播    P-5 同时只播一张    P-6 播放中点击即停
    P-7 Esc 停止        P-8 悬停不自动播放  P-9 失败显式提示
    P-10 点击状态管理幂等（连点/双击不错乱）

本模块为 V1.3 新增代码，不属于 V1.2 的 12 个受保护函数。
"""

import os

PAGE_DIRNAME = "相册页"
PAGE_NAME = "album.html"

# 文案（07 号原文，勿改写）
COPY = {
    "a1_title": "还没选择照片文件夹",
    "a1_desc": "选一个存放实况照片的文件夹，程序会按子文件夹自动整理成相册（与备份页共用同一个文件夹）",
    "a1_tip": "通常是 iPhone 导出的照片目录",
    "a1_action": "选择照片文件夹",
    "a4_title": "这个文件夹里没找到实况照片",
    "a4_desc": "实况照片是两个同名文件：一张图片 + 一段视频",
    "a4_tip": "检查导入时没有把图片和视频拆散",
    "a4_action": "换个文件夹",
    "a4_action2": "看导入向导",
    "a6_title": "相册索引读不出来",
    "a6_desc": "照片本身没有任何问题，只是分类记录损坏了",
    "a6_tip": "可以从文件夹结构重新生成分类",
    "a6_action": "重新生成分类",
    "a6_action2": "先看照片",
    "a7_title": "这台电脑缺少浏览组件",
    "a7_desc": "看实况照片需要 Edge 浏览器组件，Windows 10/11 通常自带",
    "a7_tip": "点下面的按钮改用浏览器打开",
    "a7_action": "用浏览器打开",
    "v21_title": "这个文件夹打不开",
    "v21_desc": "路径可能已移动、被删除，或当前账户没有读取权限",
    "v21_tip": "换一个文件夹，或检查磁盘连接",
    "v21_action": "换个文件夹",
    "v15_title": "正在准备可播放版本…",
    "v15_desc": "这段视频需要先转换一下格式",
    "v15_tip": "只转换一次，以后直接播放",
    "v16_title": "这段实况暂时播不出来",
    "v16_desc": "视频读不出来，照片本身没有问题",
    "v16_tip": "可以用系统播放器打开原文件",
    "v16_action": "用系统播放器打开",
    "v17_badge": "动画版本",
    "v17_tip": "GIF 会循环播放",
    "v19_title": "已导出 MP4 视频",
    "v19_desc": "文件在「安卓分享」文件夹里，手机上点一下就能播",
    "v19_tip": "发微信/QQ 都可以",
    "st_cancelled": "已取消，显示上次结果",
    "st_path_changed": "路径已变更，点「刷新」重新扫描",
    "st_index_broken": "索引异常，分类暂不可用",
    "st_saving": "正在保存分类…",
}

_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>实况照片 · 相册</title>
<style>
  :root{
    --grid-bg:#101418; --bar-bg:#1A2027; --card-bg:#222;
    --primary:#2F6FED;              /* 图形/边框/指示条；深底不作文字色 */
    --info:#58A6FF;                 /* 进行中/转码中 */
    --ok:#1F9D55;                   /* 成功 */
    --warn:#E0A800;                 /* 警告/索引异常 */
    --uncertain:#E8A87C;            /* 待确认 */
    --err:#F85149;                  /* 错误/失败 */
    --manual:#7EE2A8;               /* 手动相册徽标 */
    --dir:#9FC0FF;                  /* 目录相册徽标 */
    --dim:#9AA5B1;                  /* 辅助文字 */
    --grp:#8B98A6;                  /* 分组标题 */
    --name:#E6E6E6;                 /* 卡片名 */
  }
  *{box-sizing:border-box}
  html,body{margin:0;height:100%}
  body{background:var(--grid-bg);color:var(--name);
       font-family:"Microsoft YaHei UI","Microsoft YaHei",sans-serif;font-size:13px;overflow:hidden}
  #app{display:flex;height:100vh}

  /* ---------- 分类栏 200px ---------- */
  #side{width:200px;flex:none;background:var(--bar-bg);border-right:1px solid #2b333c;
        display:flex;flex-direction:column}
  #side .scroll{flex:1;overflow-y:auto}
  #side .grp{display:flex;align-items:center;gap:6px;height:28px;padding:0 12px;
             color:var(--grp);font-size:11px;cursor:pointer;user-select:none}
  #side .grp .ar{font-size:9px;transition:transform .15s}
  #side .grp.closed .ar{transform:rotate(-90deg)}
  #side .grp.closed + .items{display:none}
  #side .it{display:flex;align-items:center;gap:6px;height:28px;padding:0 12px 0 26px;
             cursor:pointer;border-left:2px solid transparent}
  #side .it:hover{background:#1f2831}
  #side .it.on{background:rgba(47,111,237,.16);border-left-color:var(--primary);color:#fff}
  #side .it .dot{width:6px;height:6px;border-radius:50%;flex:none}
  #side .it .dot.dir{background:var(--dir)}
  #side .it .dot.man{background:var(--manual)}
  #side .it .n{margin-left:auto;font-size:11px;color:var(--dim)}
  #side .new{margin:8px 12px 12px;height:32px;border:1px dashed #3b4753;border-radius:6px;
             color:var(--dim);display:flex;align-items:center;justify-content:center;
             font-size:12px;cursor:pointer;min-height:44px}
  #side .new:hover{border-color:var(--primary);color:#9fc0ff}

  /* ---------- 主区 ---------- */
  #main{flex:1;display:flex;flex-direction:column;min-width:0}
  #tools{height:44px;flex:none;background:var(--bar-bg);border-bottom:1px solid #2b333c;
         display:flex;align-items:center;gap:10px;padding:0 16px}
  #tools .path{font-size:12px;color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  #tools .sp{flex:1}
  #tools .tb{font-size:12px;padding:5px 10px;border:1px solid #34404d;border-radius:6px;
             color:#cfd8e3;cursor:pointer;background:#1e262f;white-space:nowrap;min-height:28px}
  #tools .tb:hover{border-color:var(--primary);color:#9fc0ff}
  #tools .tb.pri{background:var(--primary);border-color:var(--primary);color:#fff}
  #tools .tb[disabled]{opacity:.45;cursor:not-allowed}

  #grid{flex:1;overflow-y:auto;padding:16px;align-content:start;
        display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}
  #grid.empty{display:block}

  .card{position:relative;aspect-ratio:3/4;border-radius:10px;overflow:hidden;
        background:var(--card-bg);cursor:pointer;transition:transform .2s;outline:none}
  .card:hover{transform:scale(1.04)}
  .card:focus-visible{box-shadow:0 0 0 2px var(--primary)}
  .card .media{width:100%;height:100%;object-fit:cover;display:block;background:var(--card-bg)}
  .card .ind{position:absolute;inset:0;display:none;align-items:center;justify-content:center;pointer-events:none}
  .card.playing .ind{display:flex}
  .card .ind span{width:36px;height:36px;border-radius:50%;background:rgba(0,0,0,.55);
                  display:flex;align-items:center;justify-content:center;color:#fff;font-size:13px}
  .card.loading .ind{display:flex}
  .card .tags{position:absolute;top:6px;left:6px;display:flex;gap:4px;flex-wrap:wrap;max-width:90%}
  .card .tags b{font-weight:400;font-size:10px;padding:1px 6px;border-radius:8px;
                background:rgba(0,0,0,.55);color:#cfd8e3;white-space:nowrap}
  .card .tags b.dir{color:var(--dir)}
  .card .tags b.man{color:var(--manual)}
  .card .tags b.errtag{background:var(--err);color:#1b1b1b}
  .card .badge{position:absolute;top:6px;right:6px;font-size:10px;padding:1px 6px;border-radius:8px;
               background:rgba(0,0,0,.6);color:var(--name)}
  .card .badge.err{background:var(--err);color:#1b1b1b}
  .card .badge.anim{background:rgba(0,0,0,.6);color:var(--name)}
  .card .badge.busy{background:var(--info);color:#101418}
  .card .lbl{position:absolute;left:0;right:0;bottom:0;padding:14px 8px 8px;font-size:11px;
             background:linear-gradient(transparent,#000a);color:var(--name);
             white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

  /* ---------- 状态条 26px ---------- */
  #status{height:26px;flex:none;background:var(--bar-bg);border-top:1px solid #2b333c;
          display:flex;align-items:center;gap:14px;padding:0 16px;font-size:11px;color:var(--dim)}
  #status .warn{color:var(--warn)}
  #status .info{color:var(--info)}

  /* ---------- 状态覆盖层 ---------- */
  .ov{position:absolute;inset:0;display:none;align-items:center;justify-content:center;
      flex-direction:column;gap:10px;text-align:center;padding:40px;background:var(--grid-bg)}
  .ov.on{display:flex}
  .ov .t{font-size:15px;color:#dfe6ee}
  .ov .d{font-size:12px;color:var(--dim);max-width:440px;line-height:1.8}
  .ov .s{font-size:12px;color:#7f8b99}
  .ov .b{margin-top:4px;padding:7px 18px;border-radius:6px;background:var(--primary);
         color:#fff;font-size:12px;cursor:pointer;border:none;min-height:36px}
  .ov .b.ghost{background:transparent;border:1px solid #34404d;color:#cfd8e3}
  #app{position:relative}
  .hidden{display:none !important}
</style>
</head>
<body>
<div id="app">
  <div id="side">
    <div class="scroll" id="sideList"></div>
    <div class="new" id="btnNewAlbum">＋ 新建相册</div>
  </div>
  <div id="main">
    <div id="tools">
      <span class="path" id="toolPath">—</span>
      <span class="sp"></span>
      <button class="tb" id="btnRefresh">刷新</button>
      <button class="tb" id="btnExport">导出 MP4</button>
    </div>
    <div id="grid"></div>
    <div id="status"><span id="stMain">共 0 张</span><span id="stExtra"></span></div>
  </div>
  <div class="ov" id="ovA1"></div>
  <div class="ov" id="ovA4"></div>
  <div class="ov" id="ovA5"></div>
  <div class="ov" id="ovA6"></div>
  <div class="ov" id="ovA8"></div>
</div>
<script>
"use strict";
const COPY = __COPY__;

/* ================= 桥接 ================= */
let __rid = 0;
const __pending = {};
const API_TIMEOUT_MS = 45000;    // 转码/大目录扫描可能较慢，但不能无限等待
function api(method, params){
  return new Promise(function(resolve){
    const rid = ++__rid;
    let done = false;
    const timer = setTimeout(function(){
      if (done) return;
      done = true; delete __pending[rid];
      resolve({ok:false, error:"timeout"});
    }, API_TIMEOUT_MS);
    __pending[rid] = function(payload){
      if (done) return;
      done = true; clearTimeout(timer);
      resolve(payload);
    };
    const msg = JSON.stringify({rid: rid, method: method, params: params || {}});
    if (window.chrome && window.chrome.webview) {
      window.chrome.webview.postMessage(msg);
    } else {
      done = true; clearTimeout(timer); delete __pending[rid];
      resolve({ok:false, error:"no_bridge"});
    }
  });
}
window.__lpReply = function(rid, ok, payload){
  const cb = __pending[rid];
  if (cb){ delete __pending[rid]; cb({ok: ok, data: payload}); }
};
window.__lpEvent = function(ev){
  if (ev && ev.kind === "state") { applyState(ev); }
  if (ev && ev.kind === "status") { setStatus(ev); }
  if (ev && ev.kind === "stop_all") { stopAll(); }
};
/* 自动化测试通道：把 JS 求值结果回传 Python（配合 album_webview.evaluate_sync） */
window.__lpEval = function(token, value){
  if (window.chrome && window.chrome.webview){
    window.chrome.webview.postMessage(JSON.stringify({__eval: token, value: value}));
  }
};

/* ================= 全局状态 ================= */
const S = {
  state: "A1",
  source: "",
  total: 0,
  albums: [],
  album: "all",
  photos: [],
  offset: 0,
  issues: null,
  loadingMore: false,
  indexOk: true,
  selection: new Set()
};

/* ================= 播放契约 P-1…P-10 =================
   修复要点：起播必须有超时与显式成功判据（playing 事件/play() resolve），
   否则 WebView2 在媒体挂起时会永久停在 loading，T2 兜底永远不会触发。 */
const PLAY_TIMEOUT_MS = 8000;
let playing = null;            // 当前占用播放实例的卡片（loading 期间也占位，P-5）
let playSeq = 0;               // 全局序号，用于作废已被新点击取代的异步回调

function clearBadges(card){
  Array.prototype.forEach.call(
    card.el.querySelectorAll('.badge.err, .badge.anim, .badge.busy'),
    function(b){ b.remove(); });
}
function releaseVideo(card){
  if (card.cancelPlay){ try { card.cancelPlay(); } catch(e){} card.cancelPlay = null; }
  const v = card.video;
  if (!v) return;
  try { v.pause(); } catch(e){}
  try {
    v.onended = null; v.onerror = null;
    v.onloadedmetadata = null; v.oncanplay = null;
  } catch(e){}
  try { v.removeAttribute('src'); v.load(); } catch(e){}
}
function stopCard(card){
  if (!card) return;
  card.token = (card.token || 0) + 1;      // 作废该卡片所有在途异步
  releaseVideo(card);
  if (card.gifEl){ try { card.gifEl.remove(); } catch(e){} card.gifEl = null; }
  clearBadges(card);
  card.state = "idle";
  card.track = "";
  card.failCode = "";
  card.el.classList.remove("playing","loading","failed","anim");
  if (playing === card) playing = null;
}
function stopAll(){
  if (playing) stopCard(playing);
  (window.__lpCards || []).forEach(function(c){
    if (c && c.state !== "idle") stopCard(c);
  });
  playing = null;
}
window.__lpStopAll = stopAll;      // 供 Python 侧在切页签/关闭窗口时调用

function failMessage(code){
  if (code === "video_missing")   return "找不到对应的视频文件";
  if (code === "video_unreadable")return "这段视频读不出来，照片本身没有问题";
  if (code === "decode_failed")   return "这段视频无法解码，暂时播不出来";
  if (code === "transcode_failed")return "转换成可播放版本失败，照片本身没有问题";
  if (code === "timeout")         return "视频加载超时，暂时播不出来";
  if (code === "not_found")       return "这张照片已不在扫描结果里";
  return COPY.v16_title;
}
function failCard(card, code){
  stopCard(card);
  card.state = "failed";
  card.failCode = code || "unknown";
  card.el.classList.add("failed");
  const b = document.createElement('div');
  b.className = 'badge err';
  b.textContent = failMessage(card.failCode);
  card.el.appendChild(b);
  setStatus({main: failMessage(card.failCode), extra: COPY.v16_tip, cls: "warn"});
}
function playVideo(card, url, token){
  return new Promise(function(resolve, reject){
    const v = card.video;
    if (!v){ reject(new Error("no_video_element")); return; }
    let settled = false, timer = null;
    function done(err){
      if (settled) return;
      settled = true;
      if (timer){ clearTimeout(timer); timer = null; }
      if (card.cancelPlay && card.cancelPlay.__token === token)
        card.cancelPlay = null;
      if (err) reject(err); else resolve();
    }
    const cancel = function(){ done(new Error("cancelled")); };
    cancel.__token = token;
    card.cancelPlay = cancel;
    try { v.pause(); } catch(e){}
    v.onloadedmetadata = function(){
      if (token !== card.token) return;
    };
    v.onerror = function(){
      const code = v.error ? v.error.code : 0;
      done(new Error("decode:" + code));
    };
    v.onended = function(){          /* P-3 播完回静止 */
      done();                        // 先收尾，避免 stopCard 把 Promise 判成取消再触发 T2
      if (token === card.token) stopCard(card);
      updateStatus();
    };
    v.src = url;
    v.preload = "auto";
    try { v.load(); } catch(e){}
    const p = v.play();
    if (p && p.then){
      p.then(function(){
        if (token !== card.token){ try { v.pause(); } catch(e){} done(new Error("cancelled")); return; }
        if (v.readyState < 2){       // 没有真实媒体数据，不宣布播放成功
          done(new Error("no_media_data:rs" + v.readyState));
          return;
        }
        card.state = "playing";
        card.el.classList.remove("loading");
        card.el.classList.add("playing");
        playing = card;
        done();
      }).catch(function(e){ done(e || new Error("play_rejected")); });
    } else {
      done(new Error("play_no_promise"));
    }
    timer = setTimeout(function(){
      done(new Error("timeout:rs" + v.readyState + ",ns" + v.networkState));
    }, PLAY_TIMEOUT_MS);
  });
}
async function startCard(card){
  if (card.state === "loading") return;              /* P-10 loading 期间忽略重复点击 */
  if (card.state === "playing" || card.state === "anim"){
    stopCard(card); return;                          /* P-6 播放中点击即停 */
  }
  if (playing && playing !== card) stopCard(playing);  /* P-5 同时只播一张 */
  stopCard(card);                                    // 清 failed 态，保证可从头重播
  const token = ++playSeq;
  card.token = token;
  card.state = "loading";
  card.track = "T1";
  card.el.classList.add("loading");
  playing = card;                                    // loading 期间即占用，杜绝并发
  setStatus({main: "", extra: ""});
  try {
    await playVideo(card, card.tracks.video, token);  /* T1 原视频直解 */
    if (token === card.token && card.state === "playing")
      setStatus({main: "正在播放实况视频", extra: "再点一次可停止", cls: ""});
    return;
  } catch(e){
    if (token !== card.token) return;                // 已被新点击/停播作废
  }
  /* T1 失败 → T2 转码 → 明确失败（05 号 §2.2） */
  setStatus({main: COPY.v15_title, extra: COPY.v15_tip, cls: "info"});
  let r;
  try { r = await api("prepare_media", {key: card.key}); }
  catch(e){ r = {ok:false, error:"timeout"}; }
  if (token !== card.token) return;
  if (r.ok && r.data && r.data.track === "transcode"){
    card.track = "T2";
    try {
      await playVideo(card, r.data.url, token);
      if (token === card.token && card.state === "playing")
        setStatus({main: "正在播放（转码版本）", extra: "再点一次可停止", cls: ""});
      return;
    } catch(e2){
      if (token !== card.token) return;
    }
  } else if (r.ok && r.data && r.data.track === "gif"){
    /* T3 是「动画版本」降级展示，不进入 playing 态、不计入单实例播放成功，
       也不得被当作实况视频播放成功的证据。 */
    card.track = "T3";
    stopCard(card);
    const img = document.createElement("img");
    img.className = "media"; img.src = r.data.url;
    card.el.insertBefore(img, card.el.firstChild);
    card.gifEl = img;
    card.state = "anim";
    card.el.classList.add("anim");
    const badge = document.createElement('div');
    badge.className = 'badge anim';
    badge.textContent = COPY.v17_badge + '（非实况视频）';
    card.el.appendChild(badge);
    setStatus({main: "动画版本，仅作预览", extra: "这不是实况视频播放", cls: "warn"});
    return;
  }
  card.track = "fail";
  const code = r.ok ? ((r.data && r.data.error) || "no_media_track")
                    : (r.error || "no_media_track");
  failCard(card, code);
}
function onCardClick(card){
  if (card.state === "loading") return;              /* P-10 */
  if (card.state === "playing" || card.state === "anim"){
    stopCard(card); return;                          /* P-6 */
  }
  startCard(card);                                   // failed 态点击 = 从头重播
}
document.addEventListener("keydown", function(e){
  if (e.key === "Escape"){ stopAll(); }              /* P-7 */
});

/* ================= 渲染 ================= */
function esc(s){
  return String(s == null ? "" : s).replace(/[&<>"']/g, function(c){
    return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c];
  });
}
function setStatus(o){
  document.getElementById("stMain").textContent = o.main || "";
  const ex = document.getElementById("stExtra");
  ex.textContent = o.extra || "";
  ex.className = o.cls || "";
}
function renderSide(){
  const box = document.getElementById("sideList");
  let h = "";
  h += itemHtml("all", "全部", "", S.total);
  h += itemHtml("none", "未分类", "", countUn());
  h += '<div class="grp" data-grp="dir"><span class="ar">▼</span>目录相册</div><div class="items">';
  S.albums.filter(function(a){return a.kind === "dir";}).forEach(function(a){
    h += itemHtml(a.id, a.name, "dir", a.count); });
  h += '</div>';
  h += '<div class="grp" data-grp="man"><span class="ar">▼</span>手动相册</div><div class="items">';
  S.albums.filter(function(a){return a.kind === "manual";}).forEach(function(a){
    h += itemHtml(a.id, a.name, "man", a.count); });
  h += '</div>';
  box.innerHTML = h;
  Array.prototype.forEach.call(box.querySelectorAll(".it"), function(el){
    el.addEventListener("click", function(){
      Array.prototype.forEach.call(box.querySelectorAll(".it"), function(x){ x.classList.remove("on"); });
      el.classList.add("on");
      S.album = el.dataset.alb;
      loadPhotos(true);
    });
  });
  Array.prototype.forEach.call(box.querySelectorAll(".grp"), function(el){
    el.addEventListener("click", function(){
      el.classList.toggle("closed");
    });
  });
}
function itemHtml(id, name, kind, n){
  const dot = kind === "dir" ? '<span class="dot dir"></span>'
             : kind === "man" ? '<span class="dot man"></span>' : '';
  const on = (S.album === id) ? " on" : "";
  return '<div class="it' + on + '" data-alb="' + esc(id) + '">' + dot +
         '<span>' + esc(name) + '</span><span class="n">' + (n || 0) + '</span></div>';
}
function countUn(){
  let n = 0;
  S.photos.forEach(function(p){ if (!p.albums || p.albums.length === 0) n++; });
  return n;
}
function renderGrid(items, append){
  const g = document.getElementById("grid");
  if (!append){
    stopAll();                       // 重建网格前先释放所有播放器资源
    g.innerHTML = "";
    window.__lpCards = [];
  }
  items.forEach(function(p){
    const el = document.createElement("div");
    el.className = "card"; el.tabIndex = 0;
    el.setAttribute("aria-label", p.name + "，" + (p.albums || []).join("、") + "，点击播放");
    let tags = "";
    (p.albums || []).slice(0, 2).forEach(function(a){
      tags += '<b class="' + (a.kind === "dir" ? "dir" : "man") + '">' +
              (a.kind === "dir" ? "▸ " : "● ") + esc(a.name) + '</b>'; });
    if ((p.albums || []).length > 2)
      tags += '<b>+' + ((p.albums || []).length - 2) + '</b>';
    if (p.media_state === "missing")
      tags += '<b class="errtag">视频缺失</b>';
    el.innerHTML =
      '<video class="media" poster="" preload="none" playsinline></video>' +
      '<div class="ind"><span>▶</span></div>' +
      '<div class="tags">' + tags + '</div>' +
      '<div class="lbl">' + esc(p.name) + '</div>';
    g.appendChild(el);
    const card = {el: el, key: p.key, name: p.name, state: "idle", track: "",
                  video: el.querySelector("video"), gifEl: null,
                  tracks: {video: p.media}};
    window.__lpCards.push(card);
    el.addEventListener("click", function(){ onCardClick(card); });
    el.addEventListener("keydown", function(e){
      if (e.key === "Enter" || e.key === " "){ e.preventDefault(); onCardClick(card); }
    });
    observeThumb(card);
  });
}
/* 封面懒加载：进入视口 ±200px 才请求（03 号 §4.1），逐张抽帧代价高 */
let __io = null;
function observeThumb(card){
  if (!__io){
    __io = new IntersectionObserver(function(entries){
      entries.forEach(function(en){
        if (!en.isIntersecting) return;
        const c = en.target.__card;
        __io.unobserve(en.target);
        if (!c || c.thumbLoaded) return;
        c.thumbLoaded = true;
        api("get_thumb", {key: c.key}).then(function(r){
          if (r.ok && r.data && r.data.thumb){ c.video.poster = r.data.thumb; }
        });
      });
    }, {root: document.getElementById("grid"), rootMargin: "200px"});
  }
  el_add_observe(card);
}
function el_add_observe(card){
  card.el.__card = card;
  __io.observe(card.el);
}
function applyState(ev){
  const prevState = S.state;
  if (ev.state) S.state = ev.state;
  if (typeof ev.source === "string") S.source = ev.source;
  if (typeof ev.total === "number") S.total = ev.total;
  if (ev.index_ok !== undefined) S.indexOk = ev.index_ok;
  const ovs = {A1:"ovA1", A4:"ovA4", A5:"ovA5", A6:"ovA6", A8:"ovA8"};
  Object.keys(ovs).forEach(function(k){
    document.getElementById(ovs[k]).classList.remove("on");
  });
  document.getElementById("grid").classList.toggle("empty",
      ["A1","A4","A5","A6","A8"].indexOf(S.state) >= 0);
  document.getElementById("side").classList.toggle("hidden",
      ["A1","A8"].indexOf(S.state) >= 0);
  document.getElementById("toolPath").textContent = S.source || "—";
  if (S.state === "A1"){
    showOv("ovA1", COPY.a1_title, COPY.a1_desc, COPY.a1_tip,
           [[COPY.a1_action, "pick_source_folder", ""],
            [COPY.a4_action, "pick_source_folder", "ghost"]]);
  } else if (S.state === "A4"){
    showOv("ovA4", COPY.a4_title, COPY.a4_desc, COPY.a4_tip,
           [[COPY.a4_action, "pick_source_folder", ""],
            [COPY.a4_action2, "show_wizard", "ghost"]]);
  } else if (S.state === "A5"){
    showOv("ovA5", COPY.a4_title, COPY.a4_desc, COPY.a4_tip,
           [[COPY.a4_action, "pick_source_folder", ""]]);
  } else if (S.state === "A6"){
    showOv("ovA6", COPY.a6_title, COPY.a6_desc, COPY.a6_tip,
           [[COPY.a6_action, "rebuild_index", ""],
            [COPY.a6_action2, "continue_without_index", "ghost"]]);
  } else if (S.state === "A8"){
    showOv("ovA8", COPY.a7_title, COPY.a7_desc, COPY.a7_tip,
           [[COPY.a7_action, "open_external", ""]]);
  }
  if (ev.issues){ S.issues = ev.issues; }
  if (ev.albums){ S.albums = ev.albums; renderSide(); }
  /* 统一走分页接口；无论初始进入 A4 还是扫描完成重新进入 A4 都会重新取数 */
  if (S.state === "A4" && (prevState !== "A4" || ev.force_reload)){
    loadPhotos(true);
  } else if (S.state !== "A4"){
    stopAll();
  }
  if (ev.status){
    setStatus({main: ev.status.main || "", extra: ev.status.extra || "",
               cls: ev.status.cls || ""});
  }
}
function showOv(id, t, d, s, buttons){
  const el = document.getElementById(id);
  let h = '<div class="t">' + esc(t) + '</div><div class="d">' + esc(d) +
          '</div><div class="s">' + esc(s) + '</div>';
  buttons.forEach(function(b){
    h += '<button class="b ' + (b[2] || "") + '" data-act="' + esc(b[1]) + '">' +
         esc(b[0]) + '</button>';
  });
  el.innerHTML = h;
  el.classList.add("on");
  Array.prototype.forEach.call(el.querySelectorAll(".b"), function(btn){
    btn.addEventListener("click", function(){
      const act = btn.dataset.act;
      if (act === "pick_source_folder"){ api("pick_source_folder", {}); }
      else if (act === "rebuild_index"){ api("rebuild_index", {}); }
      else if (act === "continue_without_index"){ api("continue_without_index", {}); }
      else if (act === "open_external"){ api("open_external", {}); }
      else if (act === "show_wizard"){ api("show_wizard", {}); }
    });
  });
}
const PAGE_SIZE = 200;
function updateStatus(){
  let main = "共 " + S.total + " 张 · 已加载 " + S.offset + " 张 · 当前：" +
             albumName(S.album);
  if (S.offset < S.total) main += " · 向下滚动加载更多";
  main += " · " + (S.indexOk ? "索引已保存" : COPY.st_index_broken);
  let extra = "";
  if (S.issues){
    const bits = [];
    if (S.issues.photo_only)  bits.push("仅图片 " + S.issues.photo_only);
    if (S.issues.video_only)  bits.push("仅视频 " + S.issues.video_only);
    if (S.issues.uncertain)   bits.push("待确认 " + S.issues.uncertain);
    if (S.issues.unknown)     bits.push("未识别 " + S.issues.unknown);
    if (bits.length) extra = "未完成配对/未识别：" + bits.join("、");
  }
  setStatus({main: main, extra: extra, cls: extra ? "warn" : ""});
}
async function loadPhotos(reset){
  if (S.loadingMore) return;
  if (reset) S.offset = 0;
  if (S.offset > 0 && S.offset >= S.total) return;
  S.loadingMore = true;
  let r;
  try {
    r = await api("list_photos",
                  {album_id: S.album, offset: S.offset, limit: PAGE_SIZE});
  } finally {
    S.loadingMore = false;
  }
  if (!r.ok || !r.data){
    setStatus({main: "照片列表读取失败", extra: String(r.error || ""), cls: "warn"});
    return;
  }
  const items = r.data.items || [];
  S.total = r.data.total || 0;
  S.offset += items.length;
  if (r.data.issues) S.issues = r.data.issues;
  S.photos = reset ? items : S.photos.concat(items);
  renderGrid(items, !reset);
  renderSide();
  updateStatus();
}
function albumName(id){
  if (id === "all") return "全部";
  if (id === "none") return "未分类";
  const a = S.albums.filter(function(x){return x.id === id;})[0];
  return a ? a.name : "";
}
document.getElementById("btnRefresh").addEventListener("click", function(){ api("refresh", {}); });
document.getElementById("btnExport").addEventListener("click", function(){ api("export_mp4", {}); });
document.getElementById("btnNewAlbum").addEventListener("click", function(){ api("create_album_prompt", {}); });
document.getElementById("grid").addEventListener("scroll", function(){
  const g = this;
  if (g.scrollTop + g.clientHeight >= g.scrollHeight - 320){
    if (S.offset < S.total) loadPhotos(false);
  }
});

/* ================= 启动 ================= */
(async function init(){
  const r = await api("get_state", {});
  if (r.ok && r.data) applyState(r.data);
})();
</script>
</body>
</html>
"""


def build_album_page(output_dir):
    """生成相册页 HTML，返回文件路径。

    页面写到 ``输出目录/相册页/album.html``，用 ``file://`` 加载（红线 L11）。
    """
    d = os.path.join(os.path.abspath(output_dir), PAGE_DIRNAME)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, PAGE_NAME)
    html = _HTML.replace("__COPY__", _json_for_js(COPY))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return path


def _json_for_js(obj):
    import json
    return json.dumps(obj, ensure_ascii=False)
