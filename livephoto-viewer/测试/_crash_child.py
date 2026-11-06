# -*- coding: utf-8 -*-
"""崩溃模拟子进程（K-5）：在第 N 个条目处理完成后被强杀（os._exit）。

用法： python _crash_child.py <源目录> <输出目录> <退出前处理完的条目数>
"""
import importlib.util
import os
import sys
from importlib.machinery import SourceFileLoader

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "LivePhoto_Backup.pyw")

src_dir = sys.argv[1]
out_dir = sys.argv[2]
kill_after = int(sys.argv[3])

loader = SourceFileLoader("lp_crash", SRC)
spec = importlib.util.spec_from_loader("lp_crash", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)


def cb(payload):
    if payload.get("event") == "item" and payload.get("index") >= kill_after:
        sys.stdout.flush()
        os._exit(9)          # 模拟「任务管理器结束进程」
    return None


mod.process_directory(src_dir, out_dir, log=lambda m: None, progress_cb=cb)
print("NO_CRASH")
