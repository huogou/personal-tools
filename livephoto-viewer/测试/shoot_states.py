# -*- coding: utf-8 -*-
"""V1.2 界面状态截图取证（视觉证据）。

在真实 Tk 窗口上逐个渲染设计包的界面态 / 向导页 / 拦截弹窗并截图，
用于 B 组（视觉规范）与 C 组（信息架构）验收取证。

用法： python 测试/shoot_states.py <证据输出目录> [语料目录]
"""
import importlib.util
import os
import sys
import time
from importlib.machinery import SourceFileLoader

from PIL import ImageGrab

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "LivePhoto_Backup.pyw")
sys.path.insert(0, os.path.join(ROOT, "测试"))
from build_corpus import build as build_corpus        # noqa: E402

_WRAPPERS = []
SHOTS = []


def load_module(name, path):
    orig = sys.stdout
    loader = SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    if sys.stdout is not orig:
        _WRAPPERS.append(sys.stdout)
        sys.stdout = orig
    return mod


def shoot(win, path, note=""):
    """把窗口区域截屏保存。"""
    win.update_idletasks()
    win.update()
    time.sleep(0.35)
    win.lift()
    try:
        win.attributes("-topmost", True)
    except Exception:
        pass
    win.update()
    time.sleep(0.25)
    x, y = win.winfo_rootx(), win.winfo_rooty()
    w, h = win.winfo_width(), win.winfo_height()
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    img.save(path)
    try:
        win.attributes("-topmost", False)
    except Exception:
        pass
    SHOTS.append((os.path.basename(path), w, h, note))
    print("SHOT %-30s %dx%d  %s" % (os.path.basename(path), w, h, note))


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.environ.get("TEMP", r"C:\Windows\Temp"), "lp_v12_shots")
    corpus = sys.argv[2] if len(sys.argv) > 2 else build_corpus(
        os.path.join(os.environ.get("TEMP", r"C:\Windows\Temp"), "lp_v12_shot_corpus"))
    os.makedirs(outdir, exist_ok=True)

    # 隔离首次向导标记，避免自动弹窗干扰截图
    tmp_appdata = os.path.join(outdir, "appdata")
    os.makedirs(tmp_appdata, exist_ok=True)
    os.environ["APPDATA"] = tmp_appdata

    mod = load_module("lp_v12s", SRC)
    mod.webbrowser.open = lambda *a, **k: True

    import tkinter as tk
    root = tk.Tk()
    root.geometry("860x680+80+60")
    app = mod.App(root)
    root.deiconify()
    root.update()

    # ---- S1 空态 ----
    shoot(root, os.path.join(outdir, "main_S1_空态.png"), "S1 空态：还没有扫描")

    # ---- S2 已选未扫 ----
    app.src_var.set(corpus)
    app.dst_var.set(os.path.join(outdir, "备份输出"))
    root.update()
    time.sleep(1.5)
    root.update()
    shoot(root, os.path.join(outdir, "main_S2_已选未扫.png"), "S2 已选未扫 + 行内空间预检")

    # ---- S4 已扫描（走真实的只读预览流程）----
    app.start_preview()
    for _ in range(80):
        root.update()
        time.sleep(0.2)
        if not app._preview_running:
            break
    time.sleep(0.6)
    root.update()
    shoot(root, os.path.join(outdir, "main_S4_已扫描.png"),
          "S4 已扫描：6 张统计卡 + 建议行 + 折叠明细")

    # ---- S5 处理中（模拟进度）----
    app._backup_running = True
    app._show_task_running()
    app.task_bar.configure(maximum=5, value=2)
    app.task_detail.configure(text="已处理 2 / 5 组 · 当前：IMG_0346")
    root.update()
    shoot(root, os.path.join(outdir, "main_S5_备份中.png"), "S5 备份中：任务卡 + 进度 + 取消入口")

    # ---- S6 完成 ----
    app._backup_running = False
    app._last_dst = os.path.join(outdir, "备份输出")
    app._show_task_done("success", "✓ 备份完成", "备份结果",
                        "成功 4 组 · 已跳过 0 组 · 失败 1 组。你的原始照片一个都没动。")
    root.update()
    shoot(root, os.path.join(outdir, "main_S6_备份完成.png"),
          "S6 备份完成：结果卡 + 打开目录/查看器入口")

    # ---- 最小尺寸 760x600（统计卡 3+3 换行）----
    root.geometry("760x600+80+60")
    root.update()
    time.sleep(0.5)
    root.update()
    shoot(root, os.path.join(outdir, "main_min_760x600.png"), "G-2 最小尺寸 760x600")

    # ---- 大尺寸拉伸 ----
    root.geometry("1280x900+40+40")
    root.update()
    time.sleep(0.5)
    root.update()
    shoot(root, os.path.join(outdir, "main_large_1280x900.png"), "G-3 大尺寸拉伸 1280x900")
    root.geometry("860x680+80+60")
    root.update()

    # ---- 向导 A 第 1 步 ----
    wiz = mod.WizardA(root, start_step=0)
    wiz.deiconify()
    root.update()
    time.sleep(0.5)
    shoot(wiz, os.path.join(outdir, "wizardA_step1.png"), "E-2 向导A 第1步")
    wiz.step = 2
    wiz._render()
    root.update()
    time.sleep(0.4)
    shoot(wiz, os.path.join(outdir, "wizardA_step3.png"), "E-2 向导A 第3步（扫描结果说明）")
    wiz.step = 3
    wiz._render()
    root.update()
    time.sleep(0.4)
    shoot(wiz, os.path.join(outdir, "wizardA_step4.png"), "E-2 向导A 第4步（先看再存后删）")
    wiz.destroy()

    # ---- 向导 B ----
    wizb = mod.WizardB(root)
    wizb.deiconify()
    root.update()
    time.sleep(0.5)
    shoot(wizb, os.path.join(outdir, "wizardB_step1.png"), "E-3 向导B 第1步（四目标单选）")
    for code in ("A", "B", "C", "D"):
        wizb.goal = code
        wizb.step = 1
        wizb._render()
        root.update()
        time.sleep(0.35)
        shoot(wizb, os.path.join(outdir, "wizardB_step2_%s.png" % code),
              "E-3 向导B 第2步 目标 %s" % code)
    wizb.step = 3
    wizb._render()
    root.update()
    time.sleep(0.4)
    shoot(wizb, os.path.join(outdir, "wizardB_step4.png"), "E-3 向导B 第4步（验证清单 + 三条铁律）")
    wizb.destroy()

    # ---- 路径安全拦截弹窗（不可绕过）----
    app.src_var.set(corpus)
    app.dst_var.set(corpus)
    root.update()
    dlg = mod.ModalDialog(root, mod.COPY["path_same"]["title"], mod.COPY["path_same"]["body"],
                          [(mod.COPY["path_same"]["btn"], "ok", "primary")])
    dlg.destroy()

    root.destroy()
    print("\n共 %d 张截图" % len(SHOTS))


if __name__ == "__main__":
    main()
