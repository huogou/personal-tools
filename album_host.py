# -*- coding: utf-8 -*-
"""实况照片备份查看器 V1.3 · 相册页宿主（Tk 侧）

职责：把 WebView2 宿主、桥接 API 与 Tk 主窗口粘在一起：
    - 管理「相册」页的内嵌浏览区（懒启动：首次切到该页才拉起 WebView2）；
    - 承接前端消息 → 调用 :class:`album_api.AlbumApi` → 把结果回传前端；
    - 把 Tk 线程与 WebView 线程之间的调用**安全编组**（对话框必须回 Tk 线程）；
    - 维护源目录/输出目录的**单一事实源**与双向同步（复核裁定 P-1）。

设计依据：``V1.3设计\\03_V1.3_客户端浏览页布局与组件.md`` §六、
``05_播放引擎``（P-1…P-10）、README §四 红线 L11/L12/L14。

本模块为 V1.3 新增代码，不属于 V1.2 的 12 个受保护函数。
"""

import json
import os
import threading

import album_api
import album_page
import album_webview

APP_DIRNAME = "实况照片备份查看器"
FALLBACK_DIRNAME = "相册页"


class AlbumHost(object):
    """「相册」页的宿主（由 Tk 主窗口持有）。"""

    def __init__(self, root, on_album_error=None):
        self.root = root
        self.on_album_error = on_album_error
        self.frame = None
        self.api = None
        self.web = None
        self._started = False
        self._lock = threading.RLock()
        self._source = ""
        self._output_dir = ""
        self._user_data_dir = self._default_user_data_dir()

    # ---------------- 工作目录 ----------------

    @staticmethod
    def _default_user_data_dir():
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, APP_DIRNAME, FALLBACK_DIRNAME)

    def set_source(self, path):
        """由 Tk 侧推送源目录（单一事实源）。"""
        self._source = path or ""

    def set_output_dir(self, path):
        """由 Tk 侧推送输出目录。"""
        self._output_dir = path or ""

    # ---------------- 生命周期 ----------------

    def ensure_started(self):
        """首次进入「相册」页时调用：建页 + 起 WebView2 + 挂载。"""
        with self._lock:
            if self._started:
                return True
            self._started = True
            out = self._work_dir()
            try:
                page = album_page.build_album_page(out)
            except Exception as e:
                self._report("生成相册页失败：%s" % e)
                return False
            url = "file:///" + page.replace("\\", "/")
            self.api = album_api.AlbumApi(self)
            self.web = album_webview.WebViewHost(on_message=self._on_message,
                                                   on_ready=self._on_ready)
            ok = False
            try:
                ok = self.web.start(url, self._user_data_dir, timeout=40)
            except Exception as e:
                self._report("启动浏览组件失败：%s" % e)
                ok = False
            if not ok:
                self._push_state({"state": album_api.STATE_A8,
                                  "source": self._source, "total": 0,
                                  "index_ok": True, "albums": []})
                return False
            if self.frame is not None:
                self.web.attach(self.frame)
            return True

    def _work_dir(self):
        """相册页的写入目录：优先输出目录；未设置时用程序自有数据目录（不写源目录）。"""
        if self._output_dir:
            try:
                os.makedirs(self._output_dir, exist_ok=True)
                return self._output_dir
            except Exception:
                pass
        try:
            os.makedirs(self._user_data_dir, exist_ok=True)
        except Exception:
            pass
        return self._user_data_dir

    def _report(self, msg):
        try:
            if self.on_album_error:
                self.on_album_error(msg)
        except Exception:
            pass

    def stop_playback(self):
        """切回备份页 / 刷新 / 关闭窗口时停播并释放前端 <video> 资源。"""
        if self.web is not None:
            try:
                self.web.evaluate("window.__lpStopAll && window.__lpStopAll();")
            except Exception:
                pass

    def shutdown(self):
        try:
            self.stop_playback()
        except Exception:
            pass
        try:
            if self.web:
                self.web.stop()
        except Exception:
            pass

    # ---------------- 消息桥 ----------------

    def _on_message(self, payload):
        """前端 → Python：``{"rid":n,"method":"...","params":{...}}``。"""
        try:
            data = json.loads(payload) if payload else {}
        except Exception:
            return
        # 自动化测试通道：页面回传 JS 求值结果
        if "__eval" in data:
            try:
                self.web.deliver_eval(data.get("__eval"), data.get("value"))
            except Exception:
                pass
            return
        rid = data.get("rid")
        method = data.get("method")
        params = data.get("params") or {}
        if not method or self.api is None:
            return
        fn = getattr(self.api, method, None)
        if fn is None:
            self._reply(rid, False, {"error": "unknown_method"})
            return
        try:
            res = fn(**params)
        except TypeError:
            try:
                res = fn(params)
            except Exception as e:
                res = {"ok": False, "error": str(e)}
        except Exception as e:
            res = {"ok": False, "error": str(e)}
        if isinstance(res, dict) and "ok" in res:
            ok = bool(res.pop("ok"))
            data_out = res.pop("data", res)
            self._reply(rid, ok, data_out)
        else:
            self._reply(rid, True, res)

    def _reply(self, rid, ok, payload):
        if rid is None or self.web is None:
            return
        js = "window.__lpReply && window.__lpReply(%s, %s, %s);" % (
            json.dumps(rid), "true" if ok else "false",
            json.dumps(payload, ensure_ascii=False))
        self.web.evaluate(js)

    def _on_ready(self):
        self._push_state({"source": self._source})

    def _push_state(self, state):
        if self.web is None:
            return
        try:
            state = dict(state)
            state["kind"] = "state"
            self.web.send(state)
        except Exception:
            pass

    # ---------------- 供 API 调用的宿主接口 ----------------

    def get_source(self):
        return self._source

    def get_output_dir(self):
        return self._work_dir()

    def set_source_display(self, path):
        """相册页改路径 → 同步回备份页（不触发扫描/备份）。"""
        try:
            self.root.after(0, lambda: self._apply_source_display(path))
        except Exception:
            pass

    def _apply_source_display(self, path):
        try:
            cb = getattr(self.root, "_lp_set_source_display", None)
            if cb:
                cb(path)
        except Exception:
            pass

    def pick_folder(self):
        """系统目录选择框（必须在 Tk 线程执行）。"""
        return self._run_on_tk(self._do_pick_folder)

    def _do_pick_folder(self):
        from tkinter import filedialog
        return filedialog.askdirectory(title="选择照片文件夹")

    def prompt_album_name(self):
        """新建相册的名称输入（必须在 Tk 线程执行）。"""
        return self._run_on_tk(self._do_prompt_album)

    def _do_prompt_album(self):
        from tkinter import simpledialog
        return simpledialog.askstring("新建相册", "相册名称（不超过 30 字）：",
                                       parent=self.root)

    def open_external(self, path):
        """用系统默认程序打开（文件或目录）。"""
        if path:
            try:
                os.startfile(path)
            except Exception:
                pass
            return
        try:
            out = self._work_dir()
            page = os.path.join(out, album_page.PAGE_DIRNAME, album_page.PAGE_NAME)
            if os.path.exists(page):
                import webbrowser
                webbrowser.open("file:///" + page.replace("\\", "/"))
        except Exception:
            pass

    def show_wizard(self):
        """打开「使用帮助」向导（必须在 Tk 线程执行）。"""
        return self._run_on_tk(self._do_show_wizard)

    def _do_show_wizard(self):
        try:
            cb = getattr(self.root, "_lp_show_wizard", None)
            if cb:
                cb()
        except Exception:
            pass

    def push_state(self, state):
        self._push_state(state)

    def push_status(self, status):
        if self.web is None:
            return
        try:
            st = dict(status)
            st["kind"] = "status"
            self.web.send(st)
        except Exception:
            pass

    # ---------------- 线程编组 ----------------

    def _run_on_tk(self, fn, timeout=120):
        """把 fn 放到 Tk 线程执行并等待结果（供 WebView 线程调用）。"""
        box = {}
        done = threading.Event()

        def runner():
            try:
                box["v"] = fn()
            except Exception as e:
                box["e"] = e
            finally:
                done.set()

        try:
            self.root.after(0, runner)
        except Exception as e:
            return None
        if not done.wait(timeout):
            return None
        if "e" in box:
            return None
        return box.get("v")
