# -*- mode: python ; coding: utf-8 -*-
"""V1.3 修复验收版（独立构建，不覆盖 V1.2 正式版与 V1.3 既有构建产物）。

与 ``发布构建/验收构建_V1.3/spec`` 的差异仅两点：
  1. 入口用绝对路径 + pathex 指向项目根，避免相对路径层级错位；
  2. 输出名带「修复验收」标识，产物落在独立目录。
"""
import os

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.path.join(SPECPATH, '..', '..', '..'))
ENTRY = os.path.join(ROOT, 'LivePhoto_Backup.pyw')

datas = []
binaries = []
hiddenimports = ['album_index', 'album_scan', 'album_media', 'album_page',
                 'album_api', 'album_webview', 'album_host']
tmp_ret = collect_all('imageio_ffmpeg')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pythonnet')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    [ENTRY],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='实况照片备份查看器_V1.3_修复验收',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
