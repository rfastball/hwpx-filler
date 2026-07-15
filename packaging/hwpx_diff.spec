# -*- mode: python ; coding: utf-8 -*-
"""hwpx-diff onedir 빌드 스펙 (앱 A — 규격서 개정 diff 리뷰어, 웹 프론트엔드).

빌드:  .venv/Scripts/pyinstaller packaging/hwpx_diff.spec --noconfirm
산출:  dist/hwpx-diff/hwpx-diff.exe  (onedir·창 모드·콘솔 없음)

#22 로 PySide6 GUI → pywebview(WebView2) 웹 프론트엔드로 이관했다. 웹 스택은 Qt 런타임을
싣지 않는다 — 비교 엔진(hwpxdiff.diff)은 Qt-free 라 뷰 계층만 웹으로 교체됐다(PySide6 전량
excludes). 정적 자산 web-diff/ 을 datas 로 번들(동결 시 _MEIPASS/web-diff 에서 해석).
앱 B(hwpxfiller)·데이터 레이어(openpyxl)는 임포트 그래프 밖 — 명시 excludes 로 못박는다.
WebView2 런타임은 Win11 기본 탑재라 별도 동봉 불필요(hwpx_filler_web.spec 와 대칭).
"""

from pathlib import Path

SPEC_DIR = Path(SPECPATH)  # noqa: F821 - PyInstaller 주입 전역
REPO = SPEC_DIR.parent
SRC = str(REPO / "src")

# 버전 리소스는 build.ps1 산출 — 있으면 붙이고, 없으면 생략(스펙 단독 검증 가능).
version_path = REPO / "build" / "version" / "hwpx_diff_version.txt"
version_res = str(version_path) if version_path.exists() else None
# 아이콘은 커밋된 정적 리소스 — 있으면 붙인다(Qt 의존 make_icon 호출 제거).
icon_path = SPEC_DIR / "hwpx-diff.ico"
icon_res = str(icon_path) if icon_path.exists() else None

a = Analysis(
    [str(SPEC_DIR / "hwpx_diff_entry.py")],
    pathex=[SRC],
    binaries=[],
    datas=[
        (str(REPO / "web-diff"), "web-diff"),   # index.html·css·js
    ],
    # 지연·간접 임포트 보증(브리지→화면 컨트롤러→비교 엔진→네이티브 다이얼로그).
    hiddenimports=[
        "hwpxdiff.webapp",
        "hwpxdiff.webapp.app",
        "hwpxdiff.webapp.screen_diff",
        "hwpxdiff.diff",
        "hwpxcore.native.dialogs",
        "hwpxcore.native.clipboard",
        "hwpxcore.atomic",
        "lxml",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # 웹 스택은 Qt 를 싣지 않는다 — 엔진은 Qt-free 라 위젯 계층 전량 제외.
        "PySide6", "PyQt5", "PyQt6",
        # 앱 B(메일머지)와 그 데이터 레이어는 임포트 그래프 밖.
        "hwpxfiller",
        "openpyxl",
        # 표준 슬리밍.
        "tkinter", "unittest", "pydoc", "matplotlib", "numpy",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name="hwpx-diff",
    icon=icon_res,
    version=version_res,
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
