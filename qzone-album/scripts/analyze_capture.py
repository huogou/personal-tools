#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
阶段一配套：离线分析抓包产物，输出接口结构摘要。

目标（为阶段二的下载器定稿提供依据）：
1. 找出相册列表接口与照片列表接口分别是哪几条请求、返回什么结构。
2. 找出「原图」与「视频原画」直链字段在哪、长什么样、是否带签名/时效。
3. 找出分页参数（page/start/count）与总量字段。
4. 找出鉴权相关 cookie（p_skey / qq_photo_key 等）实际出现在哪些请求头里。

用法：
    python scripts/analyze_capture.py                       # 分析最新一次抓包
    python scripts/analyze_capture.py --dir 20260910_120000
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CAPTURE_ROOT = ROOT / "captures"

# 疑似字段名（中英文混排，命中即记录）
ALBUM_KEYS = re.compile(r"(albumid|album_id|topicid|topic_id|albumname|album_name|^id$|name|title|total|picnum|priv)", re.I)
PHOTO_KEYS = re.compile(r"(pickey|pic_key|lloc|sloc|origin|raw|originurl|rawurl|url|photoid|picid|is_video|videoflag|videoid|vid|height|width)", re.I)
URL_RE = re.compile(r"https?://[^\s\"'\\<>]+", re.I)
VIDEO_RE = re.compile(r"\.(mp4|mov|m3u8|flv|avi)(\?|$)", re.I)
ORIGIN_HINT = re.compile(r"(origin|raw|/b/|psbe|clarityType|isorig|hd|original)", re.I)
JSONP_RE = re.compile(r"^\s*[A-Za-z_$][\w$.]*\s*\(")


def strip_jsonp(text: str) -> tuple[str, str | None]:
    """剥离 JSONP 回调壳，返回 (纯JSON文本, 回调名)。"""
    m = JSONP_RE.match(text)
    if not m:
        return text, None
    cb = m.group(0).strip().rstrip("(").strip()
    body = text[m.end():]
    # 去掉结尾的 ); 或 })(...);
    body = body.rstrip()
    for tail in (");", ")", ";"):
        if body.endswith(tail):
            body = body[: -len(tail)]
            break
    return body.strip(), cb


def loads_loose(text: str) -> Any:
    """容忍腾讯常见的非标准 JSON（控制字符、尾随分号、单引号等）。"""
    text = text.replace("\x00", "")
    try:
        return json.loads(text)
    except Exception:
        pass
    # 常见兜底：去掉不可见控制字符
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    try:
        return json.loads(cleaned)
    except Exception:
        return None


def walk(obj: Any, path: str = "", out: dict | None = None) -> dict:
    """遍历结构，收集：所有 URL、键名频次、dict 列表样本。"""
    if out is None:
        out = {"urls": [], "keys": Counter(), "lists": []}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out["keys"][str(k)] += 1
            if isinstance(v, str):
                for u in URL_RE.findall(v):
                    out["urls"].append((f"{path}.{k}", u, v))
            else:
                walk(v, f"{path}.{k}", out)
    elif isinstance(obj, list):
        if obj and isinstance(obj[0], dict):
            # 取所有项的字段并集：视频项与照片项字段不同，只看首项会漏
            union: dict[str, Any] = {}
            for it in obj[:50]:
                if isinstance(it, dict):
                    union.update(it)
            out["lists"].append((path, len(obj), union))
        for i, v in enumerate(obj[:2000]):
            walk(v, f"{path}[{i}]", out)
    return out


def classify(url: str) -> str:
    u = url.lower()
    if "fcg_list_album" in u:
        return "相册列表"
    if "cgi_list_photo" in u:
        return "照片列表"
    if "floatview_photo_list" in u:
        return "大图/浮层列表"
    if re.search(r"(video|get_video|videoinfo)", u):
        return "视频"
    if "photo" in u or "album" in u:
        return "相册相关"
    return "其他"


def analyze_dir(d: Path) -> str:
    """分析一个抓包目录，返回控制台文本（GUI 可调用）。"""
    index = d / "index.jsonl"
    if not index.exists():
        return f"找不到索引文件：{index}"

    entries = [json.loads(x) for x in index.read_text(encoding="utf-8").splitlines() if x.strip()]
    out: list[str] = []
    out.append(f"抓包目录：{d}")
    out.append(f"总记录数：{len(entries)}\n")

    by_class: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_class[classify(e["url"])].append(e)

    out.append("=== 1. 请求分类 ===")
    for k, v in sorted(by_class.items(), key=lambda x: -len(x[1])):
        out.append(f"  {k:<12} {len(v):>4} 条")

    out.append("\n=== 2. 可解析的接口响应（含 JSONP 剥离） ===")
    results = []
    for e in entries:
        if not e.get("body_file"):
            continue
        raw = (d / e["body_file"]).read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("gbk", errors="ignore")
        stripped, cb = strip_jsonp(text)
        data = loads_loose(stripped)
        if data is None:
            continue
        info = walk(data)
        results.append({"entry": e, "data": data, "info": info, "callback": cb})

    out.append(f"  成功解析 {len(results)} / {sum(1 for e in entries if e.get('body_file'))} 条带体响应\n")
    for r in results:
        e = r["entry"]
        top = list(r["data"].keys())[:12] if isinstance(r["data"], dict) else f"list[{len(r['data'])}]"
        out.append(f"  [{classify(e['url'])}] {e['url'][:110]}")
        out.append(f"      回调={r['callback']}  顶层字段={top}")
        if r["info"]["lists"]:
            for p, n, sample in r["info"]["lists"][:3]:
                keys = list(sample.keys())
                interesting = [k for k in keys if ALBUM_KEYS.search(k) or PHOTO_KEYS.search(k)]
                out.append(f"      列表 {p or '$'}：{n} 项，关键字段 {interesting[:14]}")
        out.append("")

    out.append("=== 3. 原图 / 视频直链候选 ===")
    url_groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for r in results:
        for field, u, full in r["info"]["urls"]:
            host = u.split("/")[2] if "//" in u else "?"
            url_groups[host].append((field, u))
    for host, items in sorted(url_groups.items(), key=lambda x: -len(x[1]))[:12]:
        out.append(f"\n  [host] {host}  共 {len(items)} 个链接")

        def rank(item: tuple[str, str]) -> int:
            _, u = item
            if VIDEO_RE.search(u):
                return 0
            if ORIGIN_HINT.search(u):
                return 1
            return 2

        seen: set[str] = set()
        printed = 0
        for field, u in sorted(items, key=rank):
            sig = u[:130]
            if sig in seen:
                continue
            seen.add(sig)
            tag = "视频" if VIDEO_RE.search(u) else ("原图?" if ORIGIN_HINT.search(u) else "缩略?")
            out.append(f"      {tag:<5} {field:<32} {u[:130]}")
            printed += 1
            if printed >= 8:
                break
        if printed == 0:
            out.append(f"      样本 {items[0][1][:130]}")

    out.append("\n=== 4. 鉴权相关 ===")
    cookies_seen = Counter()
    for e in entries:
        c = e.get("req_headers", {}).get("cookie", "")
        for name in re.findall(r"([\w_]+)=", c):
            if name.lower() in {"p_skey", "skey", "p_uin", "uin", "pt4_token", "qq_photo_key", "ptcz"}:
                cookies_seen[name] += 1
    out.append(f"  请求中出现的鉴权 cookie：{dict(cookies_seen)}")
    gtk_users = [e["url"][:90] for e in entries if "g_tk=" in e["url"]]
    out.append(f"  URL 中带 g_tk 的请求数：{len(gtk_users)}")
    for u in gtk_users[:5]:
        out.append(f"      {u}")

    out.append("\n=== 5. 分页参数 ===")
    page_params = Counter()
    for e in entries:
        for k in re.findall(
            r"[?&](page|pageStart|pageNum|page_start|page_num|pagenum|start|begin|offset|count|num|hostUin|topicId|albumid)=([^&]*)",
            e["url"],
            re.I,
        ):
            page_params[k[0]] += 1
    out.append(f"  {dict(page_params)}")
    sample_vals: dict[str, set[str]] = defaultdict(set)
    for e in entries:
        for k, v in re.findall(r"[?&](pageStart|pageNum|page|start|count|num)=([^&]*)", e["url"], re.I):
            sample_vals[k].add(v)
    for k, vs in sample_vals.items():
        out.append(f"      {k} 取值样本：{sorted(vs)[:12]}")

    out_file = d / "analysis.json"
    payload = [
        {
            "url": r["entry"]["url"],
            "class": classify(r["entry"]["url"]),
            "callback": r["callback"],
            "top_keys": list(r["data"].keys())[:30] if isinstance(r["data"], dict) else None,
            "key_freq": dict(r["info"]["keys"].most_common(40)),
            "lists": [{"path": p, "n": n, "keys": list(s.keys())} for p, n, s in r["info"]["lists"]],
            "urls": [{"field": f, "url": u} for f, u, _ in r["info"]["urls"][:50]],
        }
        for r in results
    ]
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out.append(f"\n结构化结果已写入：{out_file}")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=None, help="captures 下的目录名，默认取最新")
    args = ap.parse_args()

    if args.dir:
        d = CAPTURE_ROOT / args.dir
    else:
        dirs = sorted([p for p in CAPTURE_ROOT.iterdir() if p.is_dir()])
        if not dirs:
            print("captures 下没有抓包目录，请先运行 capture_login.py")
            return 1
        d = dirs[-1]

    text = analyze_dir(d)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
