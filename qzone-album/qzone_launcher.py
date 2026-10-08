#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
瘦启动器：双击后调用本地 venv 的 pythonw 运行 scripts/gui.py。
自身不含 PySide6 / Playwright，避免打包脆弱性；依赖走已验证的 venv。
"""
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(sys.executable).resolve().parent
GUI = BASE / "scripts" / "gui.py"

# 虚拟环境解释器（需含 PySide6 + Playwright + Chromium）
# 换机器运行时：改此处默认值，或用环境变量 QZ_ALBUM_PY 指定解释器路径
VENV_PY = os.environ.get(
    "QZ_ALBUM_PY",
    r"<你的虚拟环境路径>\Scripts\pythonw.exe",
)


def main() -> int:
    if not GUI.exists():
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication(sys.argv)
        QMessageBox.critical(None, "启动失败", f"找不到界面脚本：\n{GUI}\n请确认程序文件未被移动。")
        return 1
    if not Path(VENV_PY).exists():
        from PySide6.QtWidgets import QApplication, QMessageBox
        app = QApplication(sys.argv)
        QMessageBox.critical(None, "启动失败", f"找不到运行环境：\n{VENV_PY}\n请先安装依赖。")
        return 1
    # pythonw 不弹控制台；GUI 自身为窗口程序
    subprocess.Popen([VENV_PY, str(GUI)], cwd=str(BASE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
