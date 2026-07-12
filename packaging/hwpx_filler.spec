# -*- mode: python ; coding: utf-8 -*-
"""hwpx-filler onedir 빌드 스펙 (앱 B — 누름틀 문서 생성기).

빌드:  .venv/Scripts/pyinstaller packaging/hwpx_filler.spec --noconfirm
산출:  dist/hwpx-filler/hwpx-filler.exe  (onedir·창 모드·콘솔 없음)

앱 B 의 실의존 = hwpxfiller + hwpxcore + PySide6(QtCore/QtGui/QtWidgets) + lxml + openpyxl.
디자인 토큰은 style.py 에 빌드타임 상수로 구워지므로(gui/design_tokens.json 은 dev 전용)
런타임 데이터 파일이 필요 없다 — datas 는 비어 있다. 앱 A(hwpxdiff)는 임포트 그래프 밖이며,
경계를 넘는 임포트가 나중에 추가돼도 filler exe 가 조용히 비대해지지 않도록 excludes 로 못박는다.
"""

import subprocess
import sys
from pathlib import Path

SPEC_DIR = Path(SPECPATH)  # noqa: F821 - PyInstaller 주입 전역
SRC = str(SPEC_DIR.parent / "src")
version_path = SPEC_DIR.parent / "build" / "version" / "hwpx_filler_version.txt"
if not version_path.exists():
    raise SystemExit("버전 리소스 없음: 먼저 build.ps1을 실행하세요.")

# 아이콘은 빌드 산출물 — 부재 시 생성(커밋 대상 아님).
icon_path = SPEC_DIR / "hwpx-filler.ico"
if not icon_path.exists():
    subprocess.run([sys.executable, str(SPEC_DIR / "make_filler_icon.py")], check=True)

a = Analysis(
    [str(SPEC_DIR / "hwpx_filler_entry.py")],
    pathex=[SRC],
    binaries=[],
    datas=[],
    # 지연 임포트(app.py 의 함수 내 import, data 팩토리→excel/nara, txt 라우팅) 보증.
    hiddenimports=[
        "openpyxl",
        "hwpxfiller.data.excel",
        "hwpxfiller.data.nara",
        "hwpxfiller.gui.home",
        "hwpxfiller.gui.job_editor",
        "hwpxfiller.gui.run_view",
        "hwpxfiller.gui.txt_view",
        "hwpxfiller.gui.txt_state",
        "hwpxfiller.core.text_registry",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # 앱 A(diff 리뷰어)는 통째로 밖 — filler 는 hwpxcore 에만 공유 의존한다.
        "hwpxdiff",
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

# PySide6 6.11의 QtGui 훅은 Windows에서 imageformat/input-context 플러그인의
# 연쇄 의존으로 QML/Quick/Pdf/OpenGL을 수집한다. 이 앱은 QWidget 백엔드만
# 쓰므로, 연결 플러그인과 미사용 DLL을 Analysis 후에 한 번 더 걸러낸다.
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
    name="hwpx-filler",
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
    name="hwpx-filler",
)
