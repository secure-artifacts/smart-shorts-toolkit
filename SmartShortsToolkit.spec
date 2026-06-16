# -*- mode: python ; coding: utf-8 -*-
"""
SmartShortsToolkit.spec

PyInstaller 打包配置文件。
生成 macOS 应用程序包: "Smart Shorts Toolkit.app"

使用方式：
    pyinstaller SmartShortsToolkit.spec --noconfirm

注意：
    - FFmpeg / FFprobe 不打包进 .app 内部，应用运行时会在
      系统 PATH 或 /opt/homebrew/bin、/usr/local/bin 中查找。
      用户需自行通过 `brew install ffmpeg` 安装。
    - 如需将 ffmpeg 二进制一起打包，可在 datas 中添加对应路径，
      并修改 utils/ffmpeg_utils.py 的查找逻辑以优先使用打包内路径。
"""

import sys

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.building.osx import BUNDLE

block_cipher = None

a = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("assets", "assets"),
    ],
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SmartShortsToolkit",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,  # 在 Apple Silicon 上构建时自动生成 arm64 版本
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 如有自定义图标，可设置为 "assets/icon.icns"
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="SmartShortsToolkit",
)

app = BUNDLE(
    coll,
    name="Smart Shorts Toolkit.app",
    icon=None,  # 如有自定义图标，可设置为 "assets/icon.icns"
    bundle_identifier="com.smartshortstoolkit.app",
    info_plist={
        "CFBundleName": "Smart Shorts Toolkit",
        "CFBundleDisplayName": "Smart Shorts Toolkit",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,  # 支持深色模式
        "LSMinimumSystemVersion": "13.0",
    },
)
