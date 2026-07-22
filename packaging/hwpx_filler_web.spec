# -*- mode: python ; coding: utf-8 -*-
"""hwpx-filler-web onedir 빌드 스펙 (앱 B 웹 프론트엔드 — pywebview + WebView2).

빌드:  .venv/Scripts/pyinstaller packaging/hwpx_filler_web.spec --noconfirm
산출:  dist/hwpx-filler-web/hwpx-filler-web.exe  (onedir·창 모드·콘솔 없음)

배포 형태 = onedir (소이슈 ③ 결정). 스파이크(SPIKE_FINDINGS.md Q3)는 onefile 18.9MB 로 부팅을
확인했으나 'onedir 로 하면 부팅 더 빠름'을 남겼다 — 본작업은 부팅 지연이 큰 데스크톱 앱 UX 를
위해 onedir(COLLECT)로 확정한다. Qt 앱(hwpx_filler.spec)과 동일 형태라 배포 파이프라인도 대칭.

웹 스택은 Qt 런타임을 싣지 않는다 — PySide6 전량 excludes. 링1(gui.txt_state)만 임포트되며
그건 Qt-free(스파이크 Q1). 정적 자산 web/ 을 datas 로 번들(동결 시 _MEIPASS/web 에서 해석).
WebView2 런타임은 Win11 기본 탑재라 별도 동봉 불필요.
"""

from pathlib import Path

SPEC_DIR = Path(SPECPATH)  # noqa: F821 - PyInstaller 주입 전역
REPO = SPEC_DIR.parent
SRC = str(REPO / "src")

# 버전 리소스는 build.ps1 산출 — 있으면 붙이고, 없으면 생략(스펙 단독 검증 가능).
version_path = REPO / "build" / "version" / "hwpx_filler_version.txt"
version_res = str(version_path) if version_path.exists() else None

a = Analysis(
    [str(SPEC_DIR / "hwpx_filler_web_entry.py")],
    pathex=[SRC],
    binaries=[],
    datas=[
        (str(REPO / "web"), "web"),   # index.html·css·js
    ],
    # 지연·간접 임포트 보증(브리지→화면→링1 VM→데이터 팩토리).
    hiddenimports=[
        "hwpxcore.motw",   # 엔트리 self-unblock(포터블 MOTW) — 조건부 임포트 보증
        "hwpxfiller.webapp",
        "hwpxfiller.webapp.app",
        "hwpxfiller.webapp.screens",
        "hwpxcore.native.clipboard",
        "hwpxcore.native.dialogs",
        "hwpxfiller.gui.txt_state",
        "hwpxfiller.core.text_registry",
        "hwpxfiller.core.text_render",
        "hwpxcore.atomic",
        "openpyxl",
        "hwpxfiller.data.excel",
        "hwpxfiller.data.nara",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # 웹 스택은 Qt 를 싣지 않는다 — 링1 은 Qt-free 라 위젯 계층 전량 제외.
        "PySide6", "PyQt5", "PyQt6",
        # 앱 A(diff 리뷰어)는 임포트 그래프 밖.
        "hwpxdiff",
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
    name="hwpx-filler-web",
    version=version_res,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # 창 앱 — 콘솔 없음
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
    name="hwpx-filler-web",
)
