# -*- coding: utf-8 -*-
"""实况照片备份查看器 V1.3 · WebView2 宿主（内嵌到 Tk 窗口）

职责：把 WebView2 控件嵌入 Tk 主窗口的「相册」页签区，并提供
Python ↔ 前端 的双向消息通道。

为什么不用 pywebview 的窗口（**技术偏差说明，须在实施报告中登记**）：

    设计冻结版 03/02 号写的是「pywebview EdgeChromium 后端」，但实测 pywebview
    存在两处与红线 L11「纯离线、不得监听端口」直接冲突的问题：

    1) ``webview.start()`` 内部逻辑是
       ``if (http.global_server is None) and (http_server or has_local_urls):``
       —— **只要加载的是 ``file://`` 页面，即使 ``http_server=False`` 也会启动
       全局 Bottle HTTP 服务并绑定端口**；
    2) ``webview.start()`` 要求**必须运行在主线程**（否则抛
       ``WebViewException('pywebview must be run on a main thread.')``），
       而 tkinter 同样必须占用主线程，两者无法共存于同一进程。

    本模块改为：用 **pythonnet 直接驱动 pywebview 自带的同一套 WebView2 SDK
    程序集**（``Microsoft.Web.WebView2.Core.dll`` + ``WebView2Loader.dll``），
    自建控制器并嵌入 Tk 窗格。**页面同样以 ``file://`` 加载，全程不监听任何端口**，
    红线 L11 的目的（零端口、零联网）得到**更强**的满足——本模块不涉及
    ``http_server`` 参数，因而不存在"参数被置 True"的隐性风险。

    另一处偏差：``webview.start(http_server=False)`` 这条"强制写法"
    在本方案下**不适用**（不调用 pywebview 的 start），请评审方按
    「实现目标」而非「实现形式」复核红线 L11 的执行项。

实测结论（2026-11-02，探针见实施报告 §U-02）：
    - 必须由 **.NET STA 线程**承载（pythonnet 线程默认 MTA → WebView2 报
      ``RPC_E_CHANGED_MODE``）；
    - 异步任务**不能阻塞等待 ``.Result``**（死锁），必须「轮询 + 泵消息」。

本模块为 V1.3 新增代码，不属于 V1.2 的 12 个受保护函数。
"""

import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import threading
import time

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# 64 位安全：显式声明签名，避免句柄被截断（探针踩过的坑）
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
user32.CreateWindowExW.restype = wt.HWND
user32.SetParent.argtypes = [wt.HWND, wt.HWND]
user32.SetParent.restype = wt.HWND
user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, wt.UINT]
user32.SetWindowPos.restype = wt.BOOL
user32.GetClientRect.argtypes = [wt.HWND, ctypes.c_void_p]
user32.GetClientRect.restype = wt.BOOL
user32.ClientToScreen.argtypes = [wt.HWND, ctypes.c_void_p]
user32.ClientToScreen.restype = wt.BOOL
user32.DestroyWindow.argtypes = [wt.HWND]
user32.DestroyWindow.restype = wt.BOOL
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
kernel32.GetModuleHandleW.restype = wt.HMODULE

WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
SWP_NOZORDER = 0x0004
SWP_SHOWWINDOW = 0x0040

CLSID_SZ = "STATIC"


class WebViewUnavailable(RuntimeError):
    """WebView2 运行时不可用（V-18 降级路径）。"""


def _dll_candidates(name):
    """DLL 查找顺序：pywebview 自带 → PyInstaller 打包目录 → exe 目录 → PATH。"""
    out = []
    try:
        import webview
        lib = os.path.join(os.path.dirname(os.path.realpath(webview.__file__)), "lib")
        out.append(os.path.join(lib, name))
        out.append(os.path.join(lib, "runtimes", "win-x64", "native", name))
    except Exception:
        pass
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        out.append(os.path.join(meipass, name))
    out.append(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), name))
    out.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), name))
    return out


def _resolve(name):
    for p in _dll_candidates(name):
        if os.path.exists(p):
            return p
    return None


def webview2_runtime_present():
    """探测本机是否装有 WebView2 运行时（E-1：注册表 EdgeUpdate Clients）。

    返回 True/False；探测异常一律返回 False（宁可降级，不假装可用）。
    """
    try:
        import winreg
        key = (r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"
               r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}")
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, key) as k:
                    pv, _ = winreg.QueryValueEx(k, "pv")
                    if pv:
                        return True
            except OSError:
                continue
    except Exception:
        pass
    # 兜底：运行时目录
    for base in (r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application",
                 r"C:\Program Files\Microsoft\EdgeWebView\Application"):
        if os.path.isdir(base):
            return True
    return False


class WebViewHost(object):
    """把 WebView2 嵌入 Tk 窗口的宿主。

    用法::

        host = WebViewHost(on_message)
        if host.start(page_url, user_data_dir):
            host.attach(tk_frame)     # 嵌入并跟随布局
    """

    def __init__(self, on_message=None, on_ready=None, browser_args="",
                 virtual_hosts=None):
        self.on_message = on_message
        self.on_ready = on_ready
        self.hwnd = None
        self.core = None
        self.controller = None
        self._thread = None
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._lock = threading.RLock()
        self._ready_flag = False
        self._error = ""
        self._task_queue = []
        self._eval_waiters = {}
        # V1.3 播放修复：WebView2 默认会静默挂起 file:// 页面里的 file:// 媒体
        # 子资源（readyState 恒 0、error 恒 null、play() Promise 永不 settle）。
        # browser_args 与 virtual_hosts 均为可选；不传时行为与原实现完全一致。
        # virtual_hosts 元素为 (虚拟主机名, 本地文件夹绝对路径)，由 WebView2
        # 内部拦截，不监听任何端口、不联网（红线 L11）。
        self.browser_args = browser_args or ""
        self.virtual_hosts = list(virtual_hosts or [])
        self.virtual_host_errors = []
        self.controller_errors = []

    # ---------------- 生命周期 ----------------

    def start(self, url, user_data_dir, timeout=30):
        """启动 STA 线程并创建控制器；成功返回 True。"""
        core_dll = _resolve("Microsoft.Web.WebView2.Core.dll")
        loader = _resolve("WebView2Loader.dll")
        if not core_dll or not loader:
            self._error = "缺少 WebView2 组件（%s）" % ("Core.dll" if not core_dll else "Loader")
            return False
        try:
            os.add_dll_directory(os.path.dirname(loader))
        except Exception:
            pass
        try:
            kernel32.LoadLibraryW(ctypes.c_wchar_p(loader))
        except Exception:
            pass
        try:
            import clr
            clr.AddReference(core_dll)
            from Microsoft.Web.WebView2.Core import (CoreWebView2Environment,
                                                      CoreWebView2EnvironmentOptions)
            from System.Threading import (Thread as NetThread, ThreadStart,
                                          ApartmentState)
            from System import IntPtr
        except Exception as e:
            self._error = "无法加载 WebView2 组件：%s" % e
            return False

        user_data_dir = os.path.abspath(user_data_dir)
        try:
            os.makedirs(user_data_dir, exist_ok=True)
        except Exception:
            pass

        def worker():
            try:
                self._run_sta(CoreWebView2Environment, CoreWebView2EnvironmentOptions,
                              NetThread, ThreadStart, ApartmentState, IntPtr,
                              url, user_data_dir)
            except Exception as e:
                self._error = "%s: %s" % (type(e).__name__, e)
            finally:
                self._ready.set()

        try:
            th = NetThread(ThreadStart(worker))
            th.SetApartmentState(ApartmentState.STA)
            th.IsBackground = True
            th.Start()
        except Exception as e:
            self._error = "无法启动浏览组件：%s" % e
            return False
        self._ready.wait(timeout)
        return self._ready_flag

    def _run_sta(self, CoreWebView2Environment, CoreWebView2EnvironmentOptions,
                 NetThread, ThreadStart, ApartmentState, IntPtr, url, user_data_dir):
        msg = wt.MSG()

        def pump(seconds):
            end = time.time() + seconds
            while time.time() < end:
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                time.sleep(0.005)

        def await_task(task, timeout=30):
            end = time.time() + timeout
            while not task.IsCompleted and time.time() < end:
                pump(0.05)
            return task.Result

        # 先建一个「顶层弹出窗口」作为 WebView2 的宿主：
        # 子窗口（WS_CHILD）必须带父 HWND，而真正的父窗口在 Tk 侧 attach() 时才确定，
        # 故此处建顶层窗口并保持隐藏，随后由 SetParent 挂入 Tk 窗格。
        WS_POPUP = 0x80000000
        hwnd = user32.CreateWindowExW(
            0, CLSID_SZ, "", WS_POPUP, 0, 0, 10, 10,
            None, None, kernel32.GetModuleHandleW(None), None)
        if not hwnd:
            self._error = "无法创建内嵌窗口"
            return
        self.hwnd = hwnd

        opts = CoreWebView2EnvironmentOptions()
        if self.browser_args:
            try:
                opts.AdditionalBrowserArguments = self.browser_args
            except Exception as e:
                self.virtual_host_errors.append("browser_args: %s" % e)
        env = await_task(CoreWebView2Environment.CreateAsync(None, user_data_dir, opts))
        ctrl = await_task(env.CreateCoreWebView2ControllerAsync(IntPtr(hwnd)))
        core = ctrl.CoreWebView2
        self.core = core
        self.controller = ctrl

        if self.virtual_hosts:
            try:
                from Microsoft.Web.WebView2.Core import CoreWebView2HostResourceAccessKind
                kind = CoreWebView2HostResourceAccessKind.Allow
            except Exception as e:
                kind = None
                self.virtual_host_errors.append("access_kind: %s" % e)
            if kind is not None:
                for vhost, folder in self.virtual_hosts:
                    try:
                        core.SetVirtualHostNameToFolderMapping(vhost, folder, kind)
                    except Exception as e:
                        self.virtual_host_errors.append("%s: %s" % (vhost, e))

        def on_msg(sender, args):
            try:
                payload = args.TryGetWebMessageAsString()
            except Exception:
                payload = ""
            try:
                self.on_message(payload) if self.on_message else None
            except Exception:
                pass

        core.WebMessageReceived += on_msg

        done = threading.Event()

        def on_nav(sender, args):
            done.set()

        core.NavigationCompleted += on_nav
        core.Navigate(url)

        deadline = time.time() + 25
        while time.time() < deadline and not done.is_set():
            pump(0.05)

        self._ready_flag = True
        self._ready.set()
        if self.on_ready:
            try:
                self.on_ready()
            except Exception:
                pass

        # 消息泵常驻，直到 stop()
        while not self._stop.is_set():
            pump(0.02)
            with self._lock:
                pending, self._task_queue = self._task_queue, []
            for fn in pending:
                try:
                    fn()
                except Exception:
                    pass

    def stop(self):
        # 退出前先在 WebView2 的 STA 线程执行前端停播：pause + removeAttribute('src')
        # + load()，避免关闭窗口后仍残留解码器/播放状态。
        def _cleanup():
            try:
                if self.core is not None:
                    self.core.ExecuteScriptAsync(
                        "window.__lpStopAll && window.__lpStopAll();")
            except Exception:
                pass

        with self._lock:
            self._task_queue.append(_cleanup)
        time.sleep(0.15)          # 让 STA 消息泵处理一次排队任务
        self._stop.set()
        if self.hwnd:
            try:
                user32.DestroyWindow(self.hwnd)
            except Exception:
                pass
            self.hwnd = None

    # ---------------- 嵌入 Tk ----------------

    def attach(self, tk_widget):
        """把内嵌窗口挂到 Tk 控件所在区域，并跟随其布局变化。"""
        if not self.hwnd or tk_widget is None:
            return False
        try:
            root = tk_widget.winfo_toplevel()
            parent = root.winfo_id()
            user32.SetParent(self.hwnd, parent)
        except Exception:
            return False
        self._widget = tk_widget
        try:
            tk_widget.bind("<Configure>", self._on_configure, add="+")
        except Exception:
            pass
        self._on_configure(None)
        return True

    def _on_configure(self, _evt=None):
        w = getattr(self, "_widget", None)
        if not w or not self.hwnd:
            return
        try:
            root = w.winfo_toplevel()
            rh = root.winfo_id()
            # 客户区物理尺寸 vs Tk 逻辑尺寸 → DPI 缩放系数
            rect = (wt.RECT)()
            user32.GetClientRect(rh, ctypes.byref(rect))
            phys_w = rect.right - rect.left
            tk_w = max(1, root.winfo_width())
            scale = phys_w / float(tk_w) if tk_w else 1.0

            pt = wt.POINT(0, 0)
            user32.ClientToScreen(rh, ctypes.byref(pt))
            x = int((w.winfo_rootx() - pt.x) * scale)
            y = int((w.winfo_rooty() - pt.y) * scale)
            cw = int(w.winfo_width() * scale)
            ch = int(w.winfo_height() * scale)
            user32.SetWindowPos(self.hwnd, None, x, y, max(1, cw), max(1, ch),
                                 SWP_NOZORDER | SWP_SHOWWINDOW)
            self.sync_controller_bounds(x, y, cw, ch)
        except Exception:
            pass

    def sync_controller_bounds(self, x, y, w, h):
        """把宿主窗口的可见性/尺寸同步给 WebView2 控制器（播放故障根因修复）。

        本模块用隐藏的 ``WS_POPUP`` 宿主窗口调用
        ``CreateCoreWebView2ControllerAsync``，控制器的 ``IsVisible`` 因此为
        false，Chromium 把整页判为后台页（``document.visibilityState=hidden``），
        媒体子系统被挂起：<video> 恒 ``readyState=0``、``error=null``、
        ``play()`` Promise 永不 settle，只在 3.3s 后抛 ``stalled``。
        ``SetParent``/``SetWindowPos`` 只显示 Win32 窗口，**不会**改变控制器的
        .NET 属性，必须显式同步。

        所有 .NET 属性访问都排到创建控制器的 STA 线程执行；跨线程读写
        pythonnet 对象会导致进程硬崩溃。
        """
        x, y = int(x), int(y)
        w, h = max(1, int(w)), max(1, int(h))
        if w < 50 or h < 50:          # 布局尚未完成时给一个可用尺寸
            w, h = max(w, 800), max(h, 600)

        def _do():
            ctrl = self.controller
            if ctrl is None:
                return
            try:
                from System.Drawing import Rectangle
                ctrl.Bounds = Rectangle(x, y, w, h)
            except Exception as e:
                self.controller_errors.append("bounds: %s" % e)
            try:
                if not ctrl.IsVisible:
                    ctrl.IsVisible = True
            except Exception as e:
                self.controller_errors.append("isvisible: %s" % e)
            try:
                ctrl.NotifyParentWindowPositionChanged()
            except Exception:
                pass

        with self._lock:
            self._task_queue.append(_do)

    # ---------------- 与前端通信 ----------------

    def evaluate(self, js):
        """在页面内执行 JS（用于把 API 结果回传前端）。"""
        with self._lock:
            if self.core is None:
                return False

            def _do():
                try:
                    self.core.ExecuteScriptAsync(js)
                except Exception:
                    pass
            self._task_queue.append(_do)
            return True

    def evaluate_sync(self, expr, timeout=10):
        """执行 JS 语句体并**等待其结果**（自动化测试用）。

        ``expr`` 是**语句体**（可用 ``return`` 返回值），页面侧需提供
        ``window.__lpEval(token, value)`` 把值回传给 Python。
        """
        token = "lp%d" % int(time.time() * 1000000)
        box = {}
        done = threading.Event()
        with self._lock:
            self._eval_waiters[token] = (box, done)
        script = ("window.__lpEval && window.__lpEval(%s, (function(){try{"
                  "%s}catch(e){return 'ERR:'+e;}})());"
                  % (json.dumps(token), expr))
        if not self.evaluate(script):
            with self._lock:
                self._eval_waiters.pop(token, None)
            return None
        if not done.wait(timeout):
            with self._lock:
                self._eval_waiters.pop(token, None)
            return None
        return box.get("v")

    def deliver_eval(self, token, value):
        """接收页面回传�� JS 求值结果。"""
        with self._lock:
            entry = self._eval_waiters.pop(token, None)
        if entry:
            box, done = entry
            box["v"] = value
            done.set()

    def send(self, obj):
        """向页面推送一个 JS 对象（``window.__lpEvent({...})``）。"""
        payload = json.dumps(obj, ensure_ascii=False)
        js = "window.__lpEvent && window.__lpEvent(%s);" % payload
        return self.evaluate(js)
