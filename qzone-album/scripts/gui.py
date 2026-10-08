#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
QQ 空间相册抓包 · 窗口程序（双击即可运行，无命令行）

功能与 scripts/capture_login.py 完全一致，只是交互从「终端输入」改为「按钮 + 弹窗」：
1. 填入 QQ 号，点「开始抓包」
2. 浏览器自动打开；按界面提示依次：登录 → 点开相册 → 播视频 → 点「继续」
3. 点「分析抓包结果」查看接口结构，点「打开文件夹」定位产物

复用已登录 Edge：勾选「复用已登录 Edge」，前提是 Edge 已用
  --remote-debugging-port=9222 --remote-allow-origins=*
启动（详见 README）。未勾选则使用自带 Chromium，首次需扫码，之后登录态会保留。
"""

from __future__ import annotations

import json
import re
import sys
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextEdit, QCheckBox, QMessageBox, QFileDialog,
)

# 运行位置：打包后 __file__ 在 _MEIPASS，用 exe 所在目录；脚本运行用上一级 proj
if getattr(sys, "frozen", False):
    BASE = Path(sys.executable).resolve().parent
else:
    BASE = Path(__file__).resolve().parent.parent

CAPTURE_ROOT = BASE / "captures"
DEFAULT_PROFILE = BASE / "profile"

HOST_RE = re.compile(r"(qzone\.qq\.com|qq\.com|qpic\.cn|gtimg\.cn|photo\.store|qlogo\.cn)", re.I)
INTEREST_RE = re.compile(
    r"(fcg_list_album|cgi_list_photo|cgi_floatview_photo_list|cgi_get_video"
    r"|get_video|video_info|album|photo|pic_|qzone\.qq\.com)", re.I)
JSONISH_CT = re.compile(r"(json|javascript|text/plain|text/html)", re.I)
MEDIA_CT = re.compile(r"^(image|video|audio)/", re.I)
MAX_BODY = 4 * 1024 * 1024
SENSITIVE = {"p_skey", "skey", "pt4_token", "p_uin", "ptcz", "superkey", "RK"}
CDP_URL = "http://127.0.0.1:9222"


def safe_name(s: str, limit: int = 70) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", s)[:limit] or "unnamed"


def mask_cookies(cookies: list[dict]) -> str:
    lines = []
    for c in cookies:
        n, v = c.get("name", ""), c.get("value", "")
        shown = v
        if n in SENSITIVE and len(v) > 6:
            shown = v[:3] + "*" * (len(v) - 6) + v[-3:]
        lines.append(f"{n}={shown}")
    return "\n".join(lines)


class Signals(QObject):
    log = Signal(str)
    status = Signal(str)
    need_continue = Signal(str)
    finished = Signal(bool, str)


class Worker(QThread):
    def __init__(self, qq: str, use_edge: bool):
        super().__init__()
        self.qq = qq
        self.use_edge = use_edge
        self.sig = Signals()
        self._cont = threading.Event()
        self._stop = False
        self.outdir: Path | None = None

    # ---- 界面暂停/继续 ----
    def _wait(self, msg: str) -> None:
        self.sig.need_continue.emit(msg)
        self._cont.wait()
        self._cont.clear()

    def allow_continue(self) -> None:
        self._cont.set()

    # ---- 抓包核心 ----
    def _on_resp(self, resp, rawdir: Path, idx, count) -> None:
        try:
            url = resp.url
            if not HOST_RE.search(url):
                return
            rtype = resp.request.resource_type
            ctype = (resp.headers or {}).get("content-type", "") or ""
            if not (rtype in ("xhr", "fetch") or INTEREST_RE.search(url) or JSONISH_CT.search(ctype)):
                if not MEDIA_CT.search(ctype):
                    return
            body = None
            if not MEDIA_CT.search(ctype):
                try:
                    body = resp.body()
                except Exception:
                    body = None
            if body and len(body) > MAX_BODY:
                body = None
            count[0] += 1
            body_file = None
            if body:
                fname = f"{count[0]:04d}_{safe_name(url.split('?')[0][-60:])}.bin"
                (rawdir / fname).write_bytes(body)
                body_file = f"raw/{fname}"
            entry = {
                "seq": count[0], "ts": datetime.now().isoformat(timespec="seconds"),
                "method": resp.request.method, "url": url, "resource_type": rtype,
                "status": resp.status, "content_type": ctype, "content_length": len(body) if body else 0,
                "post_data": (resp.request.post_data or "")[:4000],
                "req_headers": dict(resp.request.headers), "resp_headers": dict(resp.headers),
                "body_file": body_file,
            }
            idx.write(json.dumps(entry, ensure_ascii=False) + "\n")
            idx.flush()
            self.sig.status.emit(f"已记录 {count[0]} 条")
        except Exception:
            pass

    @staticmethod
    def _scroll(page, rounds: int = 6) -> None:
        for _ in range(rounds):
            try:
                page.mouse.wheel(0, 24000)
            except Exception:
                pass
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                pass
            page.wait_for_timeout(1200)

    def run(self) -> None:
        try:
            self._run_impl()
            self.sig.finished.emit(True, "抓包完成")
        except Exception as e:
            self.sig.log.emit(f"[错误] {e}")
            self.sig.finished.emit(False, str(e))

    def _run_impl(self) -> None:
        from playwright.sync_api import sync_playwright

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        outdir = CAPTURE_ROOT / stamp
        (outdir / "raw").mkdir(parents=True, exist_ok=True)
        idx = (outdir / "index.jsonl").open("a", encoding="utf-8")
        self.outdir = outdir
        count = [0]
        self.sig.log.emit(f"抓包目录：{outdir}")

        with sync_playwright() as p:
            if self.use_edge:
                try:
                    browser = p.chromium.connect_over_cdp(CDP_URL)
                except Exception as e:
                    self.sig.log.emit("CDP 连接失败：请确认 Edge 已用 --remote-debugging-port=9222 启动。")
                    raise
                ctx = browser.contexts[0]
                self.sig.log.emit("已接管 Edge，复用登录态")
            else:
                ctx = p.chromium.launch_persistent_context(
                    user_data_dir=str(DEFAULT_PROFILE), viewport={"width": 1440, "height": 900},
                    args=["--disable-blink-features=AutomationControlled"])
                self.sig.log.emit("已启动内置 Chromium（首次需扫码）")
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            ctx.on("response", lambda r: self._on_resp(r, outdir / "raw", idx, count))

            page.goto("https://qzone.qq.com/", wait_until="domcontentloaded", timeout=60000)
            cookies = ctx.cookies()
            has_login = any(c.get("name") in ("p_skey", "skey") and c.get("value") for c in cookies)
            if self.use_edge and has_login:
                self.sig.log.emit("检测到登录态，跳过扫码")
            else:
                self._wait("① 请在浏览器中扫码/登录 QQ 空间，完成后点「继续」")

            page.goto(f"https://user.qzone.qq.com/{self.qq}/album",
                      wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(3000)
            self._scroll(page, 6)
            self._wait("② 相册列表已抓。请点开任意相册并翻页加载照片，完成后点「继续」")
            self._scroll(page, 8)
            self._wait("③ 有视频则点开播放 2~3 秒；无视频直接点「继续」")
            page.wait_for_timeout(2000)

            try:
                ctx.storage_state(path=str(outdir / "session.json"))
            except Exception:
                self.sig.log.emit("登录态保存失败（不影响已抓数据）")
            (outdir / "cookies.txt").write_text(mask_cookies(ctx.cookies()), encoding="utf-8")
            if self.use_edge:
                browser.close()
            else:
                ctx.close()
        idx.close()
        self.sig.log.emit(f"抓包完成，共 {count[0]} 条。点「分析抓包结果」查看接口。")


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QQ 空间相册抓包工具")
        self.setMinimumWidth(560)
        self.worker: Worker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("QQ 号："))
        self.qq = QLineEdit()
        self.qq.setPlaceholderText("你的 QQ 号")
        row.addWidget(self.qq)
        self.use_edge = QCheckBox("复用已登录 Edge（需先按 README 用调试端口启动）")
        row.addWidget(self.use_edge)
        layout.addLayout(row)

        self.btn_start = QPushButton("开始抓包")
        self.btn_analyze = QPushButton("分析抓包结果")
        self.btn_folder = QPushButton("打开抓包文件夹")
        self.btn_continue = QPushButton("继续 ▶")
        self.btn_continue.setEnabled(False)
        self.btn_continue.setStyleSheet("QPushButton{background:#1d9e75;color:white;font-weight:bold}")
        for b in (self.btn_start, self.btn_analyze, self.btn_folder, self.btn_continue):
            b.setMinimumHeight(34)
        h1 = QHBoxLayout()
        h1.addWidget(self.btn_start)
        h1.addWidget(self.btn_continue)
        layout.addLayout(h1)
        h2 = QHBoxLayout()
        h2.addWidget(self.btn_analyze)
        h2.addWidget(self.btn_folder)
        layout.addLayout(h2)

        self.status = QLabel("就绪")
        layout.addWidget(self.status)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(280)
        layout.addWidget(self.log)

        self.btn_start.clicked.connect(self.start)
        self.btn_continue.clicked.connect(self.cont)
        self.btn_analyze.clicked.connect(self.analyze)
        self.btn_folder.clicked.connect(self.open_folder)

    def logline(self, s: str) -> None:
        self.log.append(s)

    def start(self) -> None:
        qq = self.qq.text().strip()
        if not qq.isdigit():
            QMessageBox.warning(self, "提示", "请先填写正确的 QQ 号")
            return
        self.btn_start.setEnabled(False)
        self.btn_continue.setEnabled(False)
        self.worker = Worker(qq, self.use_edge.isChecked())
        self.worker.sig.log.connect(self.logline)
        self.worker.sig.status.connect(self.status.setText)
        self.worker.sig.need_continue.connect(self.on_need_continue)
        self.worker.sig.finished.connect(self.on_finished)
        self.logline("启动中…")
        self.worker.start()

    def cont(self) -> None:
        if self.worker:
            self.worker.allow_continue()
        self.btn_continue.setEnabled(False)

    def on_need_continue(self, msg: str) -> None:
        self.logline(msg)
        self.status.setText("等待你操作")
        self.btn_continue.setEnabled(True)

    def on_finished(self, ok: bool, msg: str) -> None:
        self.btn_start.setEnabled(True)
        self.btn_continue.setEnabled(False)
        self.status.setText("就绪" if ok else "失败")
        self.logline(msg)

    def analyze(self) -> None:
        try:
            from analyze_capture import analyze_dir
        except Exception as e:
            self.logline(f"[错误] 无法加载分析模块：{e}")
            return
        dirs = sorted([p for p in CAPTURE_ROOT.iterdir() if p.is_dir()])
        if not dirs:
            self.logline("还没有抓包数据")
            return
        text = analyze_dir(dirs[-1])
        self.logline("")
        self.logline("=== 分析结果 ===")
        for line in text.splitlines():
            self.logline(line)

    def open_folder(self) -> None:
        d = CAPTURE_ROOT
        d.mkdir(parents=True, exist_ok=True)
        QFileDialog.getExistingDirectory(self, "抓包文件夹", str(d))


def main() -> None:
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
