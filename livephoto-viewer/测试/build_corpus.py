# -*- coding: utf-8 -*-
"""V1.2 验收语料构造（07 号 J 组）。

在隔离目录上复制真实样本，构造 7 组语料：
  IMG_0346  .HEIC + .mp4                      → 完整配对
  ONLY_PHOTO 仅 .HEIC                          → 不完整（缺视频）
  ONLY_VIDEO 仅 .mp4                          → 不完整（缺图片）
  MULTI_01  2 图 + 1 视频                      → 待确认（同名多候选）
  BROKEN_01 .HEIC + 损坏 mp4                  → 失败（封面/转码失败）
  中文 名称  中文+空格目录与文件名成对文件       → 编码健壮性
  DUP_01    根目录 + 子目录同名                → 待确认（跨目录合并）

用法： python 测试/build_corpus.py <目标语料目录>
"""
import base64
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE = os.path.join(ROOT, "测试样本")
PHOTO = os.path.join(SAMPLE, "IMG_0346.HEIC")
VIDEO = os.path.join(SAMPLE, "IMG_0346.mp4")

# 最小合法 1x1 JPEG（用作「同名多候选」里的第二张图；程序只按文件名配对，不解码图片）
TINY_JPG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
    "HBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIy"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIA"
    "AhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQA"
    "AAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3"
    "ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWm"
    "p6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEA"
    "AwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSEx"
    "BhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElK"
    "U1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3"
    "uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD3+iii"
    "gD//2Q==")


def _copy(src, dst):
    shutil.copy2(src, dst)


def build(target):
    try:
        if os.path.exists(target):
            shutil.rmtree(target)
    except Exception:
        pass
    os.makedirs(target, exist_ok=True)
    root = os.path.join(target, "照片 导入")
    os.makedirs(root)

    # 1) 完整配对
    d = os.path.join(root, "IMG_0346")
    os.makedirs(d)
    _copy(PHOTO, os.path.join(d, "IMG_0346.HEIC"))
    _copy(VIDEO, os.path.join(d, "IMG_0346.mp4"))

    # 2) 不完整（缺视频）
    d = os.path.join(root, "ONLY_PHOTO")
    os.makedirs(d)
    _copy(PHOTO, os.path.join(d, "ONLY_PHOTO.HEIC"))

    # 3) 不完整（缺图片）
    d = os.path.join(root, "ONLY_VIDEO")
    os.makedirs(d)
    _copy(VIDEO, os.path.join(d, "ONLY_VIDEO.mp4"))

    # 4) 待确认：同名多候选（同一基名 2 图 + 1 视频）
    #    配对规则只按「基名（小写）」匹配，故第二张候选必须是同基名不同扩展名。
    d = os.path.join(root, "MULTI_01")
    os.makedirs(d)
    _copy(PHOTO, os.path.join(d, "MULTI_01.HEIC"))
    with open(os.path.join(d, "MULTI_01.jpg"), "wb") as fh:
        fh.write(TINY_JPG)
    _copy(VIDEO, os.path.join(d, "MULTI_01.mp4"))

    # 5) 失败：损坏视频
    d = os.path.join(root, "BROKEN_01")
    os.makedirs(d)
    _copy(PHOTO, os.path.join(d, "BROKEN_01.HEIC"))
    with open(os.path.join(d, "BROKEN_01.mp4"), "wb") as fh:
        fh.write(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 512)   # 非法的 moov

    # 6) 中文 + 空格
    d = os.path.join(root, "中文 子目录")
    os.makedirs(d)
    _copy(PHOTO, os.path.join(d, "中文 名称.HEIC"))
    _copy(VIDEO, os.path.join(d, "中文 名称.mp4"))

    # 7) 跨目录同名 → 待确认
    d = os.path.join(root, "DUP_01")
    os.makedirs(d)
    _copy(PHOTO, os.path.join(d, "DUP_01.HEIC"))
    _copy(VIDEO, os.path.join(d, "DUP_01.mp4"))
    d2 = os.path.join(root, "DUP_01_子")
    os.makedirs(d2)
    _copy(PHOTO, os.path.join(d2, "DUP_01.HEIC"))

    return root


if __name__ == "__main__":
    tgt = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.environ.get("TEMP", r"C:\Windows\Temp"), "lp_v12_corpus")
    print(build(tgt))
