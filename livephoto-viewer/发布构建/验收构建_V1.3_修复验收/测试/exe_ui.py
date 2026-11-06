# -*- coding: utf-8 -*-
"""EXE 人工验收用的 Win32 工具（不修改任何被测代码）。"""
import ctypes
import ctypes.wintypes as wt
import time

from PIL import Image, ImageChops

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetWindowRect.restype = wt.BOOL
user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
user32.ClientToScreen.restype = wt.BOOL
user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.mouse_event.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
                               ctypes.c_uint, ctypes.c_void_p]
user32.PrintWindow.argtypes = [wt.HWND, ctypes.c_void_p, ctypes.c_uint]
user32.PrintWindow.restype = wt.BOOL
user32.GetWindowDC.argtypes = [wt.HWND]
user32.GetWindowDC.restype = ctypes.c_void_p
gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
gdi32.CreateCompatibleDC.restype = ctypes.c_void_p
gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                         ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
gdi32.SelectObject.restype = ctypes.c_void_p
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteObject.restype = wt.BOOL
gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
gdi32.DeleteDC.restype = wt.BOOL
gdi32.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                            ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
                            ctypes.c_uint]
gdi32.GetDIBits.restype = ctypes.c_int
user32.ReleaseDC.argtypes = [wt.HWND, ctypes.c_void_p]
user32.ReleaseDC.restype = ctypes.c_int

ULONG_PTR = ctypes.c_size_t


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", ULONG_PTR)]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD),
                ("wParamH", wt.WORD)]


class _INPUT(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16),
                ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32),
                ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32),
                ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32)]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER),
                ("bmiColors", ctypes.c_uint32 * 3)]


def find_window(title, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        h = user32.FindWindowW(None, title)
        if h:
            return h
        time.sleep(0.3)
    return None


def bring_front(hwnd):
    HWND_TOPMOST = -1
    user32.ShowWindow(wt.HWND(hwnd), 5)
    user32.SetWindowPos(wt.HWND(hwnd), wt.HWND(HWND_TOPMOST), 0, 0, 0, 0,
                        0x0001 | 0x0002 | 0x0040)
    user32.SetForegroundWindow(wt.HWND(hwnd))
    time.sleep(0.4)


def untop(hwnd):
    user32.SetWindowPos(wt.HWND(hwnd), wt.HWND(-2), 0, 0, 0, 0,
                        0x0001 | 0x0002)


def client_to_screen(hwnd, x, y):
    pt = wt.POINT(int(x), int(y))
    user32.ClientToScreen(wt.HWND(hwnd), ctypes.byref(pt))
    return pt.x, pt.y


def click_client(hwnd, x, y, pause=0.25):
    sx, sy = client_to_screen(hwnd, x, y)
    user32.SetCursorPos(sx, sy)
    time.sleep(0.12)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(pause)
    return sx, sy


def click_screen(x, y, pause=0.25):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.12)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(pause)


def _send_inputs(inputs):
    arr = (_INPUT * len(inputs))(*inputs)
    return user32.SendInput(len(inputs), arr, ctypes.sizeof(_INPUT))


def send_unicode(text, per_char_pause=0.02):
    """用 KEYEVENTF_UNICODE 直接发送任意 Unicode 字符（无需输入法）。"""
    for ch in text:
        for flags in (0x0004, 0x0004 | 0x0002):
            inp = _INPUT()
            inp.ki = _KEYBDINPUT(0, ord(ch), flags, 0, 0)
            _send_inputs([inp])
        time.sleep(per_char_pause)
    return True


def send_key(vk, up=False):
    inp = _INPUT()
    inp.ki = _KEYBDINPUT(vk, 0, 0x0002 if up else 0, 0, 0)
    _send_inputs([inp])


def ctrl(key_vk):
    send_key(0x11)                # Ctrl down
    send_key(key_vk)
    send_key(key_vk, up=True)
    send_key(0x11, up=True)


def set_clipboard_text(text):
    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    data = text.encode("utf-16-le") + b"\x00\x00"
    if not user32.OpenClipboard(None):
        return False
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        ptr = kernel32.GlobalLock(h)
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(h)
        user32.SetClipboardData(CF_UNICODETEXT, h)
        return True
    finally:
        user32.CloseClipboard()


def capture(hwnd, path):
    """PrintWindow(PW_RENDERFULLCONTENT) 抓真实渲染内容（含 WebView2 合成层）。"""
    rect = wt.RECT()
    user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None
    hdc = user32.GetWindowDC(wt.HWND(hwnd))
    memdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(memdc, bmp)
    user32.PrintWindow(wt.HWND(hwnd), memdc, 2)
    bi = _BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    got = gdi32.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(wt.HWND(hwnd), hdc)
    if not got:
        return None
    img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1).copy()
    if path:
        img.save(path)
    return img


def frame_diff_ratio(img1, img2, region=None):
    """两张同尺寸截图的差异像素占比（0~1），可只看网格区域。"""
    if img1 is None or img2 is None:
        return None
    a, b = img1, img2
    if region:
        a = a.crop(region)
        b = b.crop(region)
    a = a.convert("L")
    b = b.convert("L")
    d = ImageChops.difference(a, b)
    hist = d.histogram()
    # 亮度差 > 8 视为"画面发生变化"，滤掉编码/渲染噪声
    changed = sum(hist[9:])
    total = a.size[0] * a.size[1]
    return changed / float(total)


def enum_children(hwnd):
    out = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, _l):
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, cls, 256)
        txt = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(h, txt, 512)
        rect = wt.RECT()
        user32.GetWindowRect(wt.HWND(h), ctypes.byref(rect))
        out.append({"hwnd": int(h), "class": cls.value, "text": txt.value,
                    "rect": [rect.left, rect.top, rect.right, rect.bottom],
                    "visible": bool(user32.IsWindowVisible(wt.HWND(h)))})
        return True

    user32.EnumChildWindows(wt.HWND(hwnd), cb, 0)
    return out
