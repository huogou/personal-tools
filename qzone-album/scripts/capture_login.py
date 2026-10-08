#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
阶段一：QQ 空间相册接口抓包器（只记录，不下载）

设计约束（重要）：
1. 不做自动化账号密码登录、不绕过验证码/滑块。登录由用户在真实浏览器中手动/扫码完成。
2. 只做被动记录：原始响应体原样落盘，不在抓包阶段做任何解析或改写，保证证据可复核。
3. 登录态持久化到 profile/ 与 session/，供阶段二直接复用，避免重复扫码。

产出目录结构：
    captures/<时间戳>/
        index.jsonl       # 每条请求/响应的元信息（url/方法/状态码/头/体文件路径）
        raw/              # 原始响应体（二进制原样）
        session.json      # Playwright storage_state（含 cookies）
        cookies.txt       # 便于人工查看的 cookie 文本（p_skey 等会打码显示到控制台）

用法：
    python scripts/capture_login.py --qq 123456789
    python scripts/capture_login.py --qq 123456789 --browser msedge
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE = ROOT / "profile"
CAPTURE_ROOT = ROOT / "captures"

# 关注的接口关键词：命中者一定记录（即便不是 XHR）
INTEREST_RE = re.compile(
    r"(fcg_list_album|cgi_list_photo|cgi_floatview_photo_list|cgi_get_video"
    r"|get_video|video_info|album|photo|pic_|qzone\.qq\.com)",
    re.I,
)

# 只看这些域，避免把广告/统计埋点全抓进来
HOST_RE = re.compile(r"(qzone\.qq\.com|qq\.com|qpic\.cn|gtimg\.cn|photo\.store|qlogo\.cn)", re.I)

JSONISH_CT = re.compile(r"(json|javascript|text/plain|text/html)", re.I)
MEDIA_CT = re.compile(r"^(image|video|audio)/", re.I)

MAX_BODY = 4 * 1024 * 1024  # 4MB，超过不落盘（避免内存与磁盘浪费）

SENSITIVE_COOKIES = {"p_skey", "skey", "pt4_token", "p_uin", "ptcz", "superkey", "RK"}


def mask_cookies(cookies: list[dict]) -> str:
    lines = []
    for c in cookies:
        name, value = c.get("name", ""), c.get("value", "")
        shown = value
        if name in SENSITIVE_COOKIES and len(value) > 6:
            shown = value[:3] + "*" * (len(value) - 6) + value[-3:]
        lines.append(f"{name}={shown}  (domain={c.get('domain')})")
    return "\n".join(lines)


def safe_name(s: str, limit: int = 70) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s)[:limit] or "unnamed"


class Recorder:
    """被动记录器：把响应落盘并写入 jsonl 索引。"""

    def __init__(self, outdir: Path):
        self.outdir = outdir
        self.rawdir = outdir / "raw"
        self.rawdir.mkdir(parents=True, exist_ok=True)
        self.index_path = outdir / "index.jsonl"
        self._fp = self.index_path.open("a", encoding="utf-8")
        self.count = 0

    def _write_body(self, seq: int, url: str, body: bytes) -> str | None:
        if not body or len(body) > MAX_BODY:
            return None
        fname = f"{seq:04d}_{safe_name(url.split('?')[0][-60:])}.bin"
        (self.rawdir / fname).write_bytes(body)
        return f"raw/{fname}"

    def record(self, response, body: bytes | None) -> None:
        request = response.request
        url = response.url
        if not HOST_RE.search(url):
            return
        rtype = request.resource_type
        ctype = (response.headers or {}).get("content-type", "") or ""
        if not (rtype in ("xhr", "fetch") or INTEREST_RE.search(url) or JSONISH_CT.search(ctype)):
            if not MEDIA_CT.search(ctype):
                return

        self.count += 1
        body_file = None
        if MEDIA_CT.search(ctype):
            # 媒体只记链接不记体，避免几个 GB
            body_file = None
        else:
            body_file = self._write_body(self.count, url, body or b"")

        entry = {
            "seq": self.count,
            "ts": datetime.now().isoformat(timespec="seconds"),
            "method": request.method,
            "url": url,
            "resource_type": rtype,
            "status": response.status,
            "content_type": ctype,
            "content_length": len(body) if body else 0,
            "post_data": (request.post_data or "")[:4000],
            "req_headers": dict(request.headers),
            "resp_headers": dict(response.headers),
            "body_file": body_file,
        }
        self._fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._fp.flush()

    def close(self) -> None:
        self._fp.close()


def scroll_to_bottom(page, rounds: int = 6, wait_ms: int = 1500) -> None:
    """模拟滚动，触发相册/照片的懒加载与分页请求。"""
    for i in range(rounds):
        try:
            page.mouse.wheel(0, 24000)
        except Exception:
            pass
        try:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception:
            pass
        page.wait_for_timeout(wait_ms)
        print(f"    ... 滚动 {i + 1}/{rounds}", end="\r", flush=True)
    print(" " * 40, end="\r")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--qq", required=True, help="你的 QQ 号，用于拼相册页地址")
    ap.add_argument("--browser", default="chromium", choices=["chromium", "msedge", "chrome"])
    ap.add_argument("--profile", default=str(DEFAULT_PROFILE))
    ap.add_argument("--headless", action="store_true", help="无头模式（登录建议用有头）")
    ap.add_argument(
        "--connect-cdp",
        nargs="?",
        const="http://127.0.0.1:9222",
        default=None,
        help="接管已用 --remote-debugging-port 启动的 Edge/Chrome，复用其现有登录态（推荐）",
    )
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("缺少依赖，请先执行：pip install -r requirements.txt && playwright install chromium")
        return 2

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outdir = CAPTURE_ROOT / stamp
    outdir.mkdir(parents=True, exist_ok=True)
    Path(args.profile).mkdir(parents=True, exist_ok=True)

    rec = Recorder(outdir)
    print(f"[抓包目录] {outdir}")

    def on_response(resp):
        body = None
        ctype = (resp.headers or {}).get("content-type", "") or ""
        if not MEDIA_CT.search(ctype):
            try:
                body = resp.body()
            except Exception:
                body = None
        try:
            rec.record(resp, body)
        except Exception as exc:  # 单个响应失败不能中断整场抓包
            print(f"  [warn] 记录失败 {resp.url[:80]}: {exc}")

    with sync_playwright() as p:
        cdp_mode = bool(args.connect_cdp)
        if cdp_mode:
            # 接管已在运行的浏览器：复用现有登录态，无需扫码
            browser = p.chromium.connect_over_cdp(args.connect_cdp)
            ctx = browser.contexts[0]
            ctx.on("response", on_response)  # 绑在 context 上，覆盖所有标签页
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            print(f"[CDP] 已接管 {args.connect_cdp}，复用现有登录态")
        else:
            launch_map = {"chromium": p.chromium, "msedge": p.msedge, "chrome": p.chrome}
            launcher = launch_map[args.browser]
            ctx = launcher.launch_persistent_context(
                user_data_dir=args.profile,
                headless=args.headless,
                channel=None if args.browser == "chromium" else args.browser,
                viewport={"width": 1440, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.on("response", on_response)

        print("\n=== 步骤 1/4：登录 ===")
        page.goto("https://qzone.qq.com/", wait_until="domcontentloaded", timeout=60000)
        cookies = ctx.cookies()
        has_login = any(c.get("name") in ("p_skey", "skey") and c.get("value") for c in cookies)
        if cdp_mode and has_login:
            print("检测到已有登录态，无需扫码。")
            input("确认页面显示的是你自己的 QQ 空间后，按 Enter 继续... ")
        else:
            print("请用手机 QQ 扫码或手动登录。")
            input("登录成功并进入自己的空间后，回到本窗口按 Enter 继续... ")

        cookies = ctx.cookies()
        print("\n当前 Cookie（敏感值已打码）：")
        print(mask_cookies(cookies))

        print("\n=== 步骤 2/4：抓「相册列表」接口 ===")
        album_url = f"https://user.qzone.qq.com/{args.qq}/album"
        print(f"打开：{album_url}")
        page.goto(album_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        scroll_to_bottom(page, rounds=6)
        print(f"已记录 {rec.count} 条")

        print("\n=== 步骤 3/4：抓「照片列表 + 原图直链」接口 ===")
        print("请在浏览器里点开任意一个相册，翻几页让照片全部加载出来。")
        input("完成后回到本窗口按 Enter 继续... ")
        scroll_to_bottom(page, rounds=8)
        print(f"已记录 {rec.count} 条")

        print("\n=== 步骤 4/4：抓「视频原画直链」接口 ===")
        print("如果相册里有视频：请点开视频并播放 2~3 秒（会触发取真实播放地址的接口）。")
        print("如果没有视频，直接按 Enter 跳过。")
        input("完成后回到本窗口按 Enter 继续... ")
        page.wait_for_timeout(2000)
        print(f"已记录 {rec.count} 条")

        session_path = outdir / "session.json"
        try:
            ctx.storage_state(path=str(session_path))
            print(f"\n登录态已保存：{session_path}")
        except Exception as exc:
            print(f"\n[warn] 登录态保存失败（不影响已抓到的数据）：{exc}")
        (outdir / "cookies.txt").write_text(mask_cookies(ctx.cookies()), encoding="utf-8")
        if cdp_mode:
            browser.close()  # 只断开连接，不关闭你的浏览器
            print("已断开 CDP 连接，你的 Edge 保持原样")
        else:
            ctx.close()

    rec.close()
    print(f"\n抓包完成：共 {rec.count} 条记录")
    print(f"索引：{rec.index_path}")
    print(f"原始响应：{outdir / 'raw'}")
    print(f"\n下一步：python scripts/analyze_capture.py --dir {outdir.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
