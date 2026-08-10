"""파일 다이얼로그 필터 문자열 — 단일 출처(RC-34).

지원 확장자의 단일 출처는 :mod:`hwpxfiller.data.base` 의
``SUPPORTED_DATA_FILE_EXTENSIONS`` 다. 엑셀/CSV 필터와 concrete source factory가
함께 파생하므로 확장자 정책이 바뀌면(예: ``.xls`` 추가) 모든 파일 다이얼로그가
함께 움직인다 — 화면 단위 하드코딩 사본이 새 형식을 조용히 숨기는 드리프트를 끊는다.

재유입(필터 리터럴 하드코딩)은 tests/test_file_filters.py 의 grep 게이트가 막는다.
"""

from __future__ import annotations

from ..domain.data_source import SUPPORTED_DATA_FILE_EXTENSIONS as EXCEL_EXTS

# 데이터 파일(엑셀/CSV) 선택 필터 — EXCEL_EXTS 파생(리터럴 확장자 금지).
EXCEL_FILTER = "엑셀/CSV (" + " ".join(f"*{ext}" for ext in EXCEL_EXTS) + ")"

# 같은 EXCEL_EXTS 파생, Win32 comdlg32 파일 다이얼로그(웹 프론트, 에픽 #20)용 확장자 패턴.
# Win32 필터는 세미콜론 구분(Qt 는 공백). 설명 문자열은 웹앱 다이얼로그 호출부가 붙인다 —
# 단일 출처(EXCEL_EXTS)는 같아 화면별 확장자 하드코딩 사본을 만들지 않는다.
EXCEL_FILTER_PATTERN = ";".join(f"*{ext}" for ext in EXCEL_EXTS)

# HWPX 문서(템플릿·기존 문서) 선택 필터.
HWPX_FILTER = "HWPX (*.hwpx)"
