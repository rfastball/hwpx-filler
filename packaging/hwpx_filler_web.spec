# -*- mode: python ; coding: utf-8 -*-
"""hwpx-filler-web onedir 빌드 스펙 (앱 B 웹 프론트엔드 — pywebview + WebView2).

빌드:  .venv/Scripts/pyinstaller packaging/hwpx_filler_web.spec --noconfirm
산출:  dist/hwpx-filler-web/hwpx-filler-web.exe  (onedir·창 모드·콘솔 없음)

배포 형태 = onedir (소이슈 ③ 결정). 스파이크(SPIKE_FINDINGS.md Q3)는 onefile 18.9MB 로 부팅을
확인했으나 'onedir 로 하면 부팅 더 빠름'을 남겼다 — 본작업은 부팅 지연이 큰 데스크톱 앱 UX 를
위해 onedir(COLLECT)로 확정한다. Qt 앱(hwpx_filler.spec)과 동일 형태라 배포 파이프라인도 대칭.

웹 스택은 Qt 런타임을 싣지 않는다 — PySide6 전량 excludes. 링1 ViewModel 은 Qt-free 라
(스파이크 Q1) 위젯 계층 없이 임포트된다. 검증된 build/web/ 산출물을 datas 로 번들
(동결 시 _MEIPASS/web 에서 seal과 전체 트리를 다시 검증).
WebView2 런타임은 Win11 기본 탑재라 별도 동봉 불필요.

hiddenimports 는 **해소 가능한 이름만** 담는다 — PyInstaller 는 없는 이름을 경고로만
넘기므로 유령 항목이 계약처럼 남는다. verify_specs.py 가 find_spec 으로 그것을 거절한다.
"""

import sys
from pathlib import Path

SPEC_DIR = Path(SPECPATH)  # noqa: F821 - PyInstaller 주입 전역
REPO = SPEC_DIR.parent
SRC = str(REPO / "src")

# 동결 런타임이 실어 가는 CPython 자체의 라이선스(PSF-2.0 + 동봉 C 라이브러리 일부) — 빌드에 쓴
# 인터프리터 설치본의 LICENSE.txt 를 그대로 싣는다(#1107). 없으면 조용히 빼지 않고 빌드를 멈춘다:
# 고지 없는 런타임 동봉은 성공이 아니다.
PYTHON_LICENSE = Path(sys.base_prefix) / "LICENSE.txt"
if not PYTHON_LICENSE.is_file():
    raise SystemExit(f"CPython LICENSE.txt 를 찾지 못했습니다: {PYTHON_LICENSE}")

# 버전 리소스는 build.ps1 산출 — 있으면 붙이고, 없으면 생략(스펙 단독 검증 가능).
version_path = REPO / "build" / "version" / "hwpx_filler_version.txt"
version_res = str(version_path) if version_path.exists() else None

# 아이콘은 커밋된 정적 리소스(#258 문서나르미 심벌 — scripts/render_document_narmi_branding.py 산출).
icon_path = SPEC_DIR / "hwpx-filler.ico"
icon_res = str(icon_path) if icon_path.exists() else None

# 매뉴얼 기반 튜토리얼 원본 네 개만 싣는다. 실습 사본은 사용자가 시작할 때 준비하며,
# 과거 examples/onboarding 생성 자산과 스크립트는 계속 동결·비동봉이다.
TUTORIAL_ASSETS = (
    "물품 구매입찰 공고.hwpx",
    "낙찰자 선정 및 계약체결 안내.txt",
    "계약방법 결정 및 구매추진 안내.txt",
    "공고목록.xlsx",
)
for name in TUTORIAL_ASSETS:
    if not (REPO / "examples" / "tutorial" / name).is_file():
        raise SystemExit(f"튜토리얼 원본이 없습니다: {name}")

a = Analysis(
    [str(SPEC_DIR / "hwpx_filler_web_entry.py")],
    pathex=[SRC],
    binaries=[],
    datas=[
        (str(REPO / "build" / "web"), "web"),  # sealed Vite output only
        *((str(REPO / "examples" / "tutorial" / name), "examples/tutorial") for name in TUTORIAL_ASSETS),
        # 프로젝트 라이선스 + 제3자 고지 취합본 — 설치본·포터블 산출물 동봉(사용자 확정: 파일
        # 동봉만, 앱 내 표면 없음). Inno Setup [Files] 는 이 dist 폴더 전체를 재귀 복사하므로
        # 여기 한 곳만 채우면 두 배포 형태 모두 실린다.
        (str(REPO / "LICENSE"), "."),
        (str(REPO / "THIRD_PARTY_NOTICES"), "."),
        # THIRD_PARTY_NOTICES 가 가리키는 원문 동봉본(#1107). 경로 목록은
        # scripts/verify_packaged_web.py 의 REQUIRED_NOTICE_FILES 가 배포본에서 다시 확인한다.
        (str(REPO / "vendor" / "rhwp" / "LICENSE.txt"), "licenses/rhwp"),
        (str(REPO / "vendor" / "rhwp" / "THIRD_PARTY_LICENSES.txt"), "licenses/rhwp"),
        (str(REPO / "vendor" / "rhwp" / "FONTS.txt"), "licenses/rhwp"),
        (str(REPO / "vendor" / "rhwp" / "SourceHanSerifK-OFL.txt"), "licenses/rhwp"),
        (str(REPO / "vendor" / "rhwp" / "canvaskit-wasm-LICENSE.txt"), "licenses/rhwp"),
        (str(REPO / "frontend" / "fonts" / "OFL.txt"), "licenses/pretendard"),
        (str(PYTHON_LICENSE), "licenses/python"),
    ],
    # 지연·간접 임포트 보증(브리지→화면→링1 VM→데이터 팩토리).
    hiddenimports=[
        "hwpxfiller.host.motw",   # 엔트리 self-unblock(포터블 MOTW) — 조건부 임포트 보증
        "hwpxfiller.webapp",
        "hwpxfiller.webapp.app",
        "hwpxfiller.webapp.screens",
        "hwpxfiller.host.native.clipboard",
        "hwpxfiller.host.native.dialogs",
        "hwpxfiller.external.text_registry",
        "hwpxfiller.domain.text_render",
        "hwpxfiller.external.atomic",
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
        # 빌드 환경(dev·build 그룹)에서 딸려 오던 비런타임 패키지(#1107).
        # - PIL: openpyxl.drawing.image 가 try/except ImportError 로만 찾는다. 앱은
        #   load_workbook(read_only=True)만 써서 그림 파트를 읽지 않는다(src/ 는 PIL 미사용).
        # - setuptools(+_distutils_hack·pkg_resources): cffi 의 컴파일 경로
        #   (ffi.compile/verify → _shimmed_dist_utils)만 부른다. clr_loader 는 cffi ABI
        #   모드(cdef + dlopen)만 쓰므로 런타임에 닿지 않는다.
        "PIL", "setuptools", "_distutils_hack", "pkg_resources",
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
    icon=icon_res,
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
