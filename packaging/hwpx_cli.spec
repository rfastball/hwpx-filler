# -*- mode: python ; coding: utf-8 -*-
"""hwpx-cli onedir 빌드 스펙 — 자동화와 템플릿 관리 하위명령."""

from pathlib import Path

SPEC_DIR = Path(SPECPATH)  # noqa: F821 - PyInstaller 주입 전역
SRC = str(SPEC_DIR.parent / "src")

a = Analysis(
    [str(SPEC_DIR / "hwpx_cli_entry.py")],
    pathex=[SRC],
    binaries=[],
    datas=[],
    # cli.py의 하위명령·소스 분기가 함수 내 import를 쓴다. 정적 분석에
    # 우연히 기대지 않고 번들 계약으로 명시한다.
    hiddenimports=[
        "hwpxfiller.core.schema",
        "hwpxfiller.core.authoring",
        "hwpxfiller.core.lint",
        "hwpxfiller.core.mapping",
        "hwpxfiller.core.text_render",
        "hwpxfiller.data.excel",
        "hwpxfiller.data.nara",
        "openpyxl",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # CLI에는 GUI 런타임이 필요 없다.
        "hwpxdiff",
        "PySide6",
        "tkinter",
        "unittest",
        "pydoc",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name="hwpx-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    exclude_binaries=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="hwpx-cli",
)
