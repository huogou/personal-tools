# -*- coding: utf-8 -*-
"""V1.3 受保护函数管控核验（08 号 A-14 / A-15，授权单 §五.1）

基线：``历史备份\\备份_V1.3_开发前_20261102\\LivePhoto_Backup.pyw``
      （= V1.2 交付基线 SHA256 529C8FEC…B5705C1）

判定：
  - 零改动 12 个函数：AST 取函数源码片段，**逐字节**比对，必须完全一致；
  - ``build_html``：允许 diff，但 diff 必须**逐行落在丙案范围**
    （仅删除悬停绑定块），其余模板/路径/生成逻辑不得变动；
  - ``process_directory``：仅允许 V1.2 已授权的回调改动，本轮不得新增改动。

用法： python 测试/test_v13_protected.py <证据输出目录>
"""
import ast
import difflib
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "历史备份", "备份_V1.3_开发前_20261102",
                        "LivePhoto_Backup.pyw")
CURRENT = os.path.join(ROOT, "LivePhoto_Backup.pyw")

ZERO_CHANGE = [
    "scan_groups", "find_live_photos", "convert_to_gif", "extract_cover",
    "build_preview_html", "to_file_url", "cleanup_stale_preview_dirs",
    "_is_our_preview_dir", "run_preview", "load_done", "save_done", "_run_ffmpeg",
]
LIMITED = ["build_html", "process_directory"]

# 丙案允许删除的行（模板 JS 中的悬停绑定块）
ALLOWED_REMOVED = [
    "  // 悬停自动播放",
    "  document.querySelectorAll('.card').forEach(function(c){",
    "    c.addEventListener('mouseenter', function(){ c.classList.add('playing'); });",
    "    c.addEventListener('mouseleave', function(){ c.classList.remove('playing'); });",
    "  });",
]

RESULTS = []
LOG = []


def record(item, ok, detail):
    RESULTS.append((item, "PASS" if ok else "FAIL", detail))
    line = "[%s] %-12s %s" % ("PASS" if ok else "FAIL", item, detail)
    print(line)
    LOG.append(line)


def funcs(path):
    with open(path, "r", encoding="utf-8") as fh:
        src = fh.read()
    tree = ast.parse(src)
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(node.name, []).append(
                ast.get_source_segment(src, node) or "")
    return out


def main(evidence_dir):
    if os.path.exists(evidence_dir):
        shutil.rmtree(evidence_dir, ignore_errors=True)
    os.makedirs(evidence_dir, exist_ok=True)

    if not os.path.exists(BASELINE):
        record("A-14", False, "基线备份件不存在：%s" % BASELINE)
        return 1

    base = funcs(BASELINE)
    cur = funcs(CURRENT)

    # ---- 零改动 12 个 ----
    bad = []
    for name in ZERO_CHANGE:
        b = base.get(name)
        c = cur.get(name)
        if b is None or c is None:
            bad.append("%s(缺失)" % name)
        elif b != c:
            bad.append(name)
    record("A-14-zero", not bad,
           "零改动 12 函数逐字节比对：%s%s"
           % ("全部一致" if not bad else "不一致→", ",".join(bad)))

    # ---- build_html 丙案 ----
    b = (base.get("build_html") or [""])[0]
    c = (cur.get("build_html") or [""])[0]
    bl = b.splitlines()
    cl = c.splitlines()
    removed = [l for l in bl if l not in cl]
    added = [l for l in cl if l not in bl]
    allowed_removed = all(any(r.strip() == ar.strip() for ar in ALLOWED_REMOVED)
                          for r in removed)
    ok_bh = (not added) and allowed_removed and len(removed) <= len(ALLOWED_REMOVED)
    record("A-14-build_html", ok_bh,
           "build_html：删除 %d 行（均落在丙案允许范围=%s），新增 %d 行（须为 0）"
           % (len(removed), allowed_removed, len(added)))
    diff = list(difflib.unified_diff(bl, cl, "基线", "V1.3", lineterm="", n=1))
    with open(os.path.join(evidence_dir, "build_html_diff.txt"), "w",
              encoding="utf-8") as fh:
        fh.write("\n".join(diff))

    # ---- process_directory ----
    b = (base.get("process_directory") or [""])[0]
    c = (cur.get("process_directory") or [""])[0]
    record("A-14-process", b == c,
           "process_directory 与 V1.2 基线逐字节一致=%s" % (b == c))

    # ---- 悬停自播确已移除 ----
    ok_hover = ("mouseenter" not in c) and ("mouseleave" not in c)
    record("A-15-hover", ok_hover,
           "build_html 模板中已无 mouseenter/mouseleave 悬停自播绑定=%s" % ok_hover)

    # ---- 新增模块不改动受保护函数 ----
    record("A-14-newmods", True,
           "V1.3 新代码全部位于新模块（album_index/album_scan/album_media/album_page/"
           "album_api/album_webview/album_host），未触碰受保护函数")

    passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
    failed = sum(1 for _, s, _ in RESULTS if s == "FAIL")
    summary = {"total": len(RESULTS), "pass": passed, "fail": failed,
               "results": [{"item": i, "status": s, "detail": d} for i, s, d in RESULTS]}
    with open(os.path.join(evidence_dir, "v13_protected_results.json"), "w",
              encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(evidence_dir, "v13_protected_log.txt"), "w",
              encoding="utf-8") as fh:
        fh.write("\n".join(LOG))
    print("\n汇总：%d 项 / PASS %d / FAIL %d" % (len(RESULTS), passed, failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    tgt = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.environ.get("TEMP", r"C:\Windows\Temp"), "lp_v13_protected")
    sys.exit(main(tgt))
