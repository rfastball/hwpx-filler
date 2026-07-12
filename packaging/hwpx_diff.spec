# -*- mode: python ; coding: utf-8 -*-
"""hwpx-diff onedir 빌드 스펙 (앱 A — 규격서 개정 diff 리뷰어).

빌드:  .venv/Scripts/pyinstaller packaging/hwpx_diff.spec --noconfirm
산출:  dist/hwpx-diff/hwpx-diff.exe  (onedir·창 모드·콘솔 없음)

diff 경로의 실제 의존은 PySide6(QtCore/QtGui/QtWidgets) + lxml + 표준库뿐이다.
앱 B(메일머지)의 데이터 레이어(openpyxl 등)는 임포트 그래프에 없지만, 후일 누군가
공유 모듈에 임포트를 추가해도 diff exe 가 조용히 비대해지지 않도록 명시 excludes 로
못박는다.
"""

import subprocess
import sys
from pathlib import Path

SPEC_DIR = Path(SPECPATH)  # noqa: F821 - PyInstaller 주입 전역
SRC = str(SPEC_DIR.parent / "src")
version_path = SPEC_DIR.parent / "build" / "version" / "hwpx_diff_version.txt"
if not version_path.exists():
    raise SystemExit("버전 리소스 없음: 먼저 build.ps1을 실행하세요.")

# 아이콘은 빌드 산출물 — 부재 시 생성(커밋 대상 아님).
icon_path = SPEC_DIR / "hwpx-diff.ico"
if not icon_path.exists():
    subprocess.run([sys.executable, str(SPEC_DIR / "make_icon.py")], check=True)

a = Analysis(
    [str(SPEC_DIR / "hwpx_diff_entry.py")],
    pathex=[SRC],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # 주입 제품(hwpxfiller)은 통째로 밖 — diff 는 hwpxcore 에만 의존한다.
        "hwpxfiller",
        "openpyxl",
        # 표준 슬리밍.
        "tkinter",
        "unittest",
        "pydoc",
        # PySide6 대형 모듈(미사용) 방어.
        "PySide6.QtNetwork",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtPdf",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtMultimedia",
        "PySide6.QtSql",
        "PySide6.QtTest",
        "PySide6.QtDesigner",
        "PySide6.QtOpenGL",
        "PySide6.QtOpenGLWidgets",
    ],
    noarchive=False,
)

# QtGui 훅이 imageformat/input-context 플러그인 의존으로 수집하는 미사용
# QML/Quick/Pdf/OpenGL 연쇄를 제거한다. diff 앱은 QWidget 백엔드만 쓴다.
SLIM_QT_BINARIES = {
    "opengl32sw.dll",
    "qpdf.dll",
    "qtvirtualkeyboardplugin.dll",
    "qt6network.dll",
    "qt6opengl.dll",
    "qt6pdf.dll",
    "qt6quick.dll",
    "qt6virtualkeyboard.dll",
}
a.binaries = [
    item for item in a.binaries
    if Path(item[0]).name.lower() not in SLIM_QT_BINARIES
    and not Path(item[0]).name.lower().startswith("qt6qml")
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name="hwpx-diff",
    icon=str(icon_path),
    version=str(version_path),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # 창 앱 — 콘솔 없음(--selfcheck 출력은 파이프로만 보임)
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
    name="hwpx-diff",
)
