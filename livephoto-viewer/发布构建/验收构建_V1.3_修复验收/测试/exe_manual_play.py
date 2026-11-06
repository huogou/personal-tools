# -*- coding: utf-8 -*-
"""V1.3 修复版 EXE 人工播放验收（真实 GUI EXE + 真实鼠标 + 连续抓帧）。

不修改任何被测源码/配置/测试脚本，只操作 GUI 并用 PrintWindow 连续抓帧，
以「画面是否真的在变化」作为视频实际播放的客观判据（而非按钮状态）。

输出：../证据/exe_manual_play_results.json + EXE-M*.png
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import subprocess
import sys
import time

import exe_ui as ui

HERE = os.path.dirname(os.path.abspath(__file__))
ACCEPT = os.path.dirname(HERE)
EVID = os.path.join(ACCEPT, "证据")
EXE = os.path.join(ACCEPT, "exe", "实况照片备份查看器_V1.3_修复验收.exe")
SRC = os.path.join(HERE, "work_manual", "源目录 中文 空格")
DST = os.path.join(HERE, "work_manual", "输出目录")
OUT = os.path.join(EVID, "exe_manual_play_results.json")
TITLE = "实况照片备份查看器 V1.3"

# 客户区坐标（依据 860x680 默认窗口与 EXE-01/02 截图实测）
POS_SRC_ENTRY = (300, 150)
POS_DST_ENTRY = (300, 202)
POS_TAB_ALBUM = (100, 16)
POS_TAB_BACKUP = (40, 16)
POS_PICK_BTN = (438, 421)
POS_CARD1 = (300, 140)
POS_CARD2 = (520, 140)

LOG = []
RESULT = {"steps": [], "checks": {}, "shots": []}


def log(msg):
    print(msg, flush=True)
    LOG.append(str(msg))


def shot(hwnd, name):
    p = os.path.join(EVID, name)
    img = ui.capture(hwnd, p)
    if img is not None:
        RESULT["shots"].append(name)
    return img


def find_root():
    p = HERE
    while not os.path.exists(os.path.join(p, "测试样本", "IMG_0346.mp4")):
        q = os.path.dirname(p)
        if q == p:
            raise RuntimeError("找不到项目根目录")
        p = q
    return p


def prepare_corpus():
    import shutil
    root = find_root()
    photo = os.path.join(root, "测试样本", "IMG_0346.HEIC")
    video = os.path.join(root, "测试样本", "IMG_0346.mp4")
    if os.path.isdir(os.path.join(HERE, "work_manual")):
        shutil.rmtree(os.path.join(HERE, "work_manual"), ignore_errors=True)
    os.makedirs(SRC)
    os.makedirs(DST)
    for i in (1, 2):
        shutil.copy2(photo, os.path.join(SRC, "IMG_M%03d.HEIC" % i))
        shutil.copy2(video, os.path.join(SRC, "IMG_M%03d.mp4" % i))
    return {"photo": photo, "video": video}


def type_path(hwnd, xy, text, tag):
    ui.bring_front(hwnd)
    sx, sy = ui.click_client(hwnd, xy[0], xy[1])
    time.sleep(0.3)
    ui.send_unicode(text)
    time.sleep(0.4)
    RESULT["steps"].append("%s：点击客户区%s（屏幕 %s,%s）并输入路径" %
                           (tag, xy, sx, sy))
    log("%s -> 输入 %s" % (tag, text))


def find_dialog(timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        h = ui.user32.FindWindowW("#32770", None)
        if h and ui.user32.IsWindowVisible(wt.HWND(h)):
            return h
        time.sleep(0.3)
    return None


def fill_folder_dialog(dlg, path):
    """向原生文件夹选择对话框填入路径并确认（两种策略，均留证）。"""
    info = {"children": [], "strategy": "", "ok": False}
    kids = ui.enum_children(dlg)
    info["children"] = kids[:40]
    edits = [k for k in kids if "Edit" in k["class"] and k["visible"]]
    info["edit_count"] = len(edits)
    ui.bring_front(dlg)
    if edits:
        h = edits[0]["hwnd"]
        ui.user32.SetWindowTextW(wt.HWND(h), path)
        time.sleep(0.4)
        ui.user32.PostMessageW(wt.HWND(dlg), 0x0111, 1, 0)   # WM_COMMAND IDOK
        time.sleep(1.2)
        info["strategy"] = "SetWindowText+IDOK"
        if not ui.user32.IsWindow(wt.HWND(dlg)):
            info["ok"] = True
            return info
    # 策略二：直接键盘输入 + 两次回车
    ui.send_unicode(path)
    time.sleep(0.5)
    ui.send_key(0x0D)
    time.sleep(1.0)
    ui.send_key(0x0D)
    time.sleep(1.0)
    info["strategy"] += "+SendInput"
    info["ok"] = not bool(ui.user32.IsWindow(wt.HWND(dlg)))
    return info


def frames(hwnd, n, interval, prefix):
    out = []
    for i in range(n):
        img = shot(hwnd, "%s_%02d.png" % (prefix, i))
        out.append(img)
        time.sleep(interval)
    return out


def motion(hwnd, prefix, n=6, interval=0.28, region=(210, 40, 876, 560)):
    imgs = frames(hwnd, n, interval, prefix)
    diffs = [ui.frame_diff_ratio(imgs[i], imgs[i + 1], region)
             for i in range(len(imgs) - 1)]
    diffs = [d for d in diffs if d is not None]
    return {"diff_ratios": [round(d, 5) for d in diffs],
            "max": round(max(diffs), 5) if diffs else None,
            "mean": round(sum(diffs) / len(diffs), 5) if diffs else None}


def main():
    os.makedirs(EVID, exist_ok=True)
    corpus = prepare_corpus()
    RESULT["env"] = {"exe": EXE, "src": SRC, "dst": DST,
                     "media": corpus["photo"] + " + " + corpus["video"],
                     "method": "真实鼠标点击 + SendInput 输入 + PrintWindow 连续抓帧"}
    if not os.path.exists(EXE):
        RESULT["error"] = "EXE 不存在"
        _write()
        return 1
    proc = subprocess.Popen([EXE])
    hwnd = ui.find_window(TITLE, timeout=120)
    if not hwnd:
        RESULT["error"] = "未找到主窗口"
        try:
            proc.kill()
        except Exception:
            pass
        _write()
        return 1
    RESULT["env"]["hwnd"] = int(hwnd)
    log("主窗口出现 hwnd=%s" % hwnd)
    ui.bring_front(hwnd)
    shot(hwnd, "EXE-M01_启动.png")

    # P1 填写源/输出目录
    type_path(hwnd, POS_SRC_ENTRY, SRC, "P1-源目录")
    type_path(hwnd, POS_DST_ENTRY, DST, "P1-输出目录")
    shot(hwnd, "EXE-M02_已填路径.png")

    # P2 进入相册页
    ui.bring_front(hwnd)
    ui.click_client(hwnd, POS_TAB_ALBUM[0], POS_TAB_ALBUM[1])
    time.sleep(9.0)
    shot(hwnd, "EXE-M03_相册页A1.png")
    RESULT["steps"].append("P2：点击「相册」页签并等待 WebView2 加载")

    # P3 触发扫描：点击 A1 空态「选择照片文件夹」，随后向原生对话框
    # 直接发送完整路径并回车确认（不依赖读取对话框内部控件）。
    ui.bring_front(hwnd)
    ui.click_client(hwnd, POS_PICK_BTN[0], POS_PICK_BTN[1], pause=2.2)
    dlg = find_dialog(6)
    RESULT["checks"]["dialog_detected"] = bool(dlg)
    ui.send_unicode(SRC)
    time.sleep(0.9)
    ui.send_key(0x0D)          # 导航到该文件夹
    time.sleep(1.6)
    ui.send_key(0x0D)          # 确认选择
    time.sleep(3.5)
    if not dlg:
        dlg = find_dialog(2)
    if dlg:
        ui.user32.PostMessageW(wt.HWND(dlg), 0x0010, 0, 0)
        time.sleep(1.0)
    RESULT["steps"].append("P3：点击空态按钮并在目录对话框输入路径+回车")
    shot(hwnd, "EXE-M05_扫描后.png")

    # P4 播放前静止基线
    ui.bring_front(hwnd)
    baseline = motion(hwnd, "EXE-M06_静止基线", n=4, interval=0.3)
    RESULT["checks"]["static_baseline"] = baseline
    log("静止基线帧差：%s" % baseline)

    # P5 点击第一张 → 视频是否真的在动
    ui.bring_front(hwnd)
    ui.click_client(hwnd, POS_CARD1[0], POS_CARD1[1], pause=0.15)
    playing = motion(hwnd, "EXE-M07_播放中", n=7, interval=0.26)
    RESULT["checks"]["playing"] = playing
    log("播放中帧差：%s" % playing)
    shot(hwnd, "EXE-M08_播放中定格.png")

    # P6 再点同一张 → 停止
    time.sleep(0.4)
    ui.bring_front(hwnd)
    ui.click_client(hwnd, POS_CARD1[0], POS_CARD1[1], pause=0.5)
    stopped = motion(hwnd, "EXE-M09_停止后", n=4, interval=0.3)
    RESULT["checks"]["stopped"] = stopped
    log("停止后帧差：%s" % stopped)

    # P7 再点 → 从头重播
    ui.bring_front(hwnd)
    ui.click_client(hwnd, POS_CARD1[0], POS_CARD1[1], pause=0.15)
    replay = motion(hwnd, "EXE-M10_重播", n=5, interval=0.26)
    RESULT["checks"]["replay"] = replay
    log("重播帧差：%s" % replay)

    # P8 切另一张 → 单实例（画面持续动，且只有一张卡片区域在动）
    ui.bring_front(hwnd)
    ui.click_client(hwnd, POS_CARD2[0], POS_CARD2[1], pause=0.15)
    switch = motion(hwnd, "EXE-M11_切换第二张", n=5, interval=0.26)
    RESULT["checks"]["switch_card"] = switch
    log("切换第二张帧差：%s" % switch)
    shot(hwnd, "EXE-M12_第二张播放.png")

    # P9 切回备份页 → 相册页应停止/离开
    ui.bring_front(hwnd)
    ui.click_client(hwnd, POS_TAB_BACKUP[0], POS_TAB_BACKUP[1], pause=0.6)
    time.sleep(1.2)
    shot(hwnd, "EXE-M13_切回备份页.png")
    RESULT["checks"]["back_to_backup"] = {"screenshot": "EXE-M13_切回备份页.png"}
    RESULT["steps"].append("P9：切回备份页并截图")

    # P10 退出
    ui.user32.PostMessageW(wt.HWND(hwnd), 0x0010, 0, 0)
    time.sleep(3.0)
    exited = proc.poll() is not None
    if not exited:
        proc.kill()
    RESULT["checks"]["exit"] = {"exited": exited,
                                "returncode": proc.returncode}
    RESULT["steps"].append("P10：WM_CLOSE 退出，exited=%s rc=%s" %
                           (exited, proc.returncode))

    # 判定（全部由帧差实测计算）
    base = baseline.get("max") or 0
    thr = max(0.004, base * 3)
    RESULT["checks"]["threshold"] = round(thr, 5)
    RESULT["verdict"] = {
        "video_actually_playing": bool(
            (playing.get("max") or 0) > thr
            and (playing.get("max") or 0) > 0.01),
        "stop_after_second_click": bool(
            (stopped.get("max") or 1) <= thr),
        "replay_moves": bool((replay.get("max") or 0) > thr),
        "switch_moves": bool((switch.get("max") or 0) > thr),
        "exit_ok": bool(exited),
    }
    log("判定：%s" % json.dumps(RESULT["verdict"], ensure_ascii=False))
    _write()
    return 0


def _write():
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(RESULT, fh, ensure_ascii=False, indent=2)
    log("结果已写入：" + OUT)


if __name__ == "__main__":
    sys.exit(main())
