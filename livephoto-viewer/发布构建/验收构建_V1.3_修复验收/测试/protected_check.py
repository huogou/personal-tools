# -*- coding: utf-8 -*-
"""受保护资产与受保护函数真实复核（不依赖 GUI）。"""
import ast
import difflib
import hashlib
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "证据", "protected_check_results.json")
ZERO = ("scan_groups", "find_live_photos", "convert_to_gif", "extract_cover",
        "build_html", "build_preview_html", "to_file_url",
        "cleanup_stale_preview_dirs", "_is_our_preview_dir",
        "run_preview", "load_done", "save_done", "_run_ffmpeg")


def find_root():
    p = HERE
    while not os.path.exists(os.path.join(p, "LivePhoto_Backup.pyw")):
        q = os.path.dirname(p)
        if q == p:
            raise RuntimeError("root not found")
        p = q
    return p


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def funcs(path):
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    tree = ast.parse(text)
    return {n.name: ast.get_source_segment(text, n) for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def main():
    root = find_root()
    cur = os.path.join(root, "LivePhoto_Backup.pyw")
    base = os.path.join(root, "历史备份", "备份_V1.3_开发前_20261102",
                        "LivePhoto_Backup.pyw")
    assets = [os.path.join(root, "dist", "实况照片备份查看器.exe"),
              os.path.join(root, "发布构建", "验收构建_V1.2",
                           "实况照片备份查看器_V1.2.exe"),
              os.path.join(root, "发布构建", "验收构建_V1.3",
                           "实况照片备份查看器_V1.3.exe"),
              os.path.join(root, "发布构建", "验收构建_V1.3",
                           "实况照片备份查看器_V1.3_cli.exe"),
              base]
    fb, fc = funcs(base), funcs(cur)
    res = {"baseline": base, "current": cur, "functions": {}}
    for n in ZERO:
        res["functions"][n] = {
            "identical": bool(n in fb and n in fc and fb[n] == fc[n]),
            "baseline_lines": len(fb.get(n, "").splitlines())}
    res["process_directory_identical"] = bool(
        fb.get("process_directory") == fc.get("process_directory")
        and fb.get("process_directory") is not None)
    res["build_html_diff"] = list(difflib.unified_diff(
        fb.get("build_html", "").splitlines(),
        fc.get("build_html", "").splitlines(), "baseline", "current",
        lineterm=""))
    res["assets"] = {}
    for p in assets:
        rel = os.path.relpath(p, root)
        if os.path.exists(p):
            st = os.stat(p)
            res["assets"][rel] = {"size": st.st_size, "sha256": sha(p)}
        else:
            res["assets"][rel] = {"missing": True}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    print("written:", OUT)


main()
