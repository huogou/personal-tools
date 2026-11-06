# -*- coding: utf-8 -*-
"""新构建 EXE 的真实运行验证（不替换正式版）。

EXE-1 GUI：启动新 EXE → 窗口出现 → 切到「相册」页 → 截图取证 → 正常关闭。
EXE-2 CLI：新 CLI EXE 跑一次真实备份流程 → 校验产物 → 源目录零改动。

注意：EXE 属独立进程，无法像源码直跑那样读取 WebView2 内部 JS 状态，
因此 EXE 级「点击播放」只能由人工确认，本脚本如实标 UNVERIFIED。
输出：../证据/exe_smoke_results.json
"""
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

from PIL import ImageGrab

HERE = os.path.dirname(os.path.abspath(__file__))
ACCEPT = os.path.dirname(HERE)
EXE_DIR = os.path.join(ACCEPT, "exe")
EVID = os.path.join(ACCEPT, "证据")
GUI = os.path.join(EXE_DIR, "实况照片备份查看器_V1.3_修复验收.exe")
CLI = os.path.join(EXE_DIR, "实况照片备份查看器_V1.3_修复验收_cli.exe")
WORK = os.path.join(HERE, "work_exe")
OUT = os.path.join(EVID, "exe_smoke_results.json")
TITLE = "实况照片备份查看器 V1.3"
LOG = []

u = ctypes.windll.user32
u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
u.GetWindowRect.restype = wt.BOOL
u.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
u.mouse_event.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
                          ctypes.c_uint, ctypes.c_void_p]


def find_root():
    p = HERE
    while True:
        if os.path.exists(os.path.join(p, "测试样本", "IMG_0346.mp4")):
            return p
        q = os.path.dirname(p)
        if q == p:
            raise RuntimeError("找不到项目根")
        p = q


ROOT = find_root()
SAMPLE_PHOTO = os.path.join(ROOT, "测试样本", "IMG_0346.HEIC")
SAMPLE_VIDEO = os.path.join(ROOT, "测试样本", "IMG_0346.mp4")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot(root):
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for fn in sorted(filenames):
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root).replace("\\", "/")
            out[rel] = {"size": os.path.getsize(p), "sha256": sha256(p)}
    return out


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


def print_window(hwnd, path):
    """用 PrintWindow(PW_RENDERFULLCONTENT) 抓窗口内容。

    WebView2 用 DirectComposition 合成，GDI 屏幕截图只能得到黑屏，
    必须走 PrintWindow 才能取到真实渲染结果。
    """
    from PIL import Image
    gdi32 = ctypes.windll.gdi32
    user32 = ctypes.windll.user32
    rect = wt.RECT()
    user32.GetWindowRect(wt.HWND(hwnd), ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return False
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
        return False
    img = Image.frombuffer("RGB", (w, h), buf, "raw", "BGRX", 0, 1)
    img.save(path)
    return True


def grab(hwnd, path):
    """优先 PrintWindow（可抓到 WebView2 合成层），失败再退回屏幕截图。"""
    HWND_TOPMOST = -1
    HWND_NOTOPMOST = -2
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_SHOWWINDOW = 0x0040
    try:
        u.ShowWindow(wt.HWND(hwnd), 5)          # SW_SHOW
        u.SetWindowPos(wt.HWND(hwnd), wt.HWND(HWND_TOPMOST), 0, 0, 0, 0,
                       SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        u.SetForegroundWindow(wt.HWND(hwnd))
        time.sleep(0.8)
        ok = print_window(hwnd, path)
        if not ok:
            rect = wt.RECT()
            u.GetWindowRect(wt.HWND(hwnd), ctypes.byref(rect))
            ImageGrab.grab(bbox=(rect.left, rect.top, rect.right,
                                 rect.bottom)).save(path)
            ok = True
    except Exception as e:
        LOG.append("截图失败 %s: %s" % (path, e))
        ok = False
    finally:
        try:
            u.SetWindowPos(wt.HWND(hwnd), wt.HWND(HWND_NOTOPMOST), 0, 0, 0, 0,
                           SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        except Exception:
            pass
    return os.path.basename(path) if ok else ""


def gui_check():
    res = {"steps": [], "screens": []}
    if not os.path.exists(GUI):
        res["error"] = "GUI EXE 不存在：" + GUI
        return res
    proc = subprocess.Popen([GUI])
    hwnd = None
    end = time.time() + 120
    while time.time() < end:
        h = u.FindWindowW(None, TITLE)
        if h:
            hwnd = h
            break
        if proc.poll() is not None:
            res["error"] = "EXE 提前退出，returncode=%s" % proc.returncode
            return res
        time.sleep(0.5)
    if not hwnd:
        res["error"] = "120 秒内未找到主窗口"
        try:
            proc.kill()
        except Exception:
            pass
        return res
    res["steps"].append("主窗口出现 hwnd=%s" % hwnd)
    time.sleep(2.0)
    res["screens"].append(grab(hwnd, os.path.join(EVID, "EXE-01_启动.png")))
    rect = wt.RECT()
    u.GetWindowRect(wt.HWND(hwnd), ctypes.byref(rect))
    # 「相册」页签位于客户区顶部页签条内：客户区坐标 (100, 16)
    pt = wt.POINT(0, 0)
    u.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
    u.ClientToScreen(wt.HWND(hwnd), ctypes.byref(pt))
    x = pt.x + 100
    y = pt.y + 16
    HWND_TOPMOST = -1
    HWND_NOTOPMOST = -2
    u.SetWindowPos(wt.HWND(hwnd), wt.HWND(HWND_TOPMOST), 0, 0, 0, 0,
                   0x0001 | 0x0002 | 0x0040)
    u.SetForegroundWindow(wt.HWND(hwnd))
    time.sleep(0.6)
    u.SetCursorPos(x, y)
    time.sleep(0.2)
    u.mouse_event(0x0002, 0, 0, 0, 0)
    u.mouse_event(0x0004, 0, 0, 0, 0)
    res["steps"].append("置顶后点击「相册」页签（客户区 100,16）@(%d,%d)" % (x, y))
    time.sleep(16.0)
    u.SetWindowPos(wt.HWND(hwnd), wt.HWND(HWND_NOTOPMOST), 0, 0, 0, 0,
                   0x0001 | 0x0002 | 0x0040)
    alive = proc.poll() is None
    res["alive_after_album_tab"] = alive
    res["screens"].append(grab(hwnd, os.path.join(EVID, "EXE-02_相册页.png")))
    res["steps"].append("切相册页后进程存活=%s" % alive)
    u.PostMessageW(wt.HWND(hwnd), 0x0010, 0, 0)   # WM_CLOSE
    time.sleep(4.0)
    if proc.poll() is None:
        try:
            proc.kill()
        except Exception:
            pass
        res["steps"].append("WM_CLOSE 后未自行退出，已强制结束")
    else:
        res["steps"].append("WM_CLOSE 后正常退出，returncode=%s" % proc.returncode)
    res["returncode"] = proc.returncode
    res["ok"] = bool(alive)
    return res


def cli_check():
    res = {"steps": []}
    if not os.path.exists(CLI):
        res["error"] = "CLI EXE 不存在：" + CLI
        return res
    if os.path.isdir(WORK):
        shutil.rmtree(WORK, ignore_errors=True)
    src = os.path.join(WORK, "源目录")
    dst = os.path.join(WORK, "输出目录")
    os.makedirs(os.path.join(src, "旅行 相册"))
    for i in (1, 2):
        shutil.copy2(SAMPLE_PHOTO,
                     os.path.join(src, "旅行 相册", "IMG_E%03d.HEIC" % i))
        shutil.copy2(SAMPLE_VIDEO,
                     os.path.join(src, "旅行 相册", "IMG_E%03d.mp4" % i))
    os.makedirs(dst)
    before = snapshot(src)
    t0 = time.time()
    try:
        r = subprocess.run([CLI, "--cli", src, dst], timeout=600,
                           capture_output=True, text=True, errors="replace")
        rc = r.returncode
        err = (r.stderr or "")[-600:]
    except Exception as e:
        rc = None
        err = str(e)
    elapsed = time.time() - t0
    after = snapshot(src)
    changed = sorted(k for k in set(before) & set(after)
                     if before[k] != after[k])
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    out_files = []
    for dirpath, dirnames, filenames in os.walk(dst):
        for fn in sorted(filenames):
            p = os.path.join(dirpath, fn)
            out_files.append({"rel": os.path.relpath(p, dst).replace("\\", "/"),
                              "size": os.path.getsize(p)})
    res["steps"] = [
        "returncode=%s, 耗时 %.1fs" % (rc, elapsed),
        "输出产物 %d 个：%s" % (len(out_files),
                                [f["rel"] for f in out_files][:12]),
        "源目录改动=%s 新增=%s 删除=%s" % (changed, added, removed),
    ]
    res["returncode"] = rc
    res["stderr_tail"] = err
    res["output_files"] = out_files
    res["source_unchanged"] = (not changed and not added and not removed)
    res["ok"] = bool(rc == 0 and res["source_unchanged"] and len(out_files) > 0)
    return res


def main():
    os.makedirs(EVID, exist_ok=True)
    out = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "gui_exe": GUI, "cli_exe": CLI}
    if os.path.exists(GUI):
        out["gui_exe_size"] = os.path.getsize(GUI)
        out["gui_exe_sha256"] = sha256(GUI)
    if os.path.exists(CLI):
        out["cli_exe_size"] = os.path.getsize(CLI)
        out["cli_exe_sha256"] = sha256(CLI)
    print("== EXE-1 GUI ==", flush=True)
    out["gui"] = gui_check()
    print(json.dumps(out["gui"], ensure_ascii=False, indent=2), flush=True)
    print("== EXE-2 CLI ==", flush=True)
    out["cli"] = cli_check()
    print(json.dumps(out["cli"], ensure_ascii=False, indent=2), flush=True)
    out["note"] = ("EXE 为独立进程，无法读取 WebView2 内部 JS 状态；"
                   "EXE 级「点击播放」需人工确认，脚本不据此宣称播放通过。")
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print("\n结果已写入：" + OUT, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
