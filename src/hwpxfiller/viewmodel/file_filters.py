"""파일 다이얼로그 필터 문자열 — 단일 출처(RC-34).

지원 확장자의 단일 출처는 :mod:`hwpxfiller.domain.data_source` 의
``SUPPORTED_DATA_FILE_EXTENSIONS`` 다. 엑셀/CSV 필터와 concrete source factory가
함께 파생하므로 확장자 정책이 바뀌면(예: ``.xls`` 추가) 모든 파일 다이얼로그가
함께 움직인다 — 화면 단위 하드코딩 사본이 새 형식을 조용히 숨기는 드리프트를 끊는다.

재유입(필터 리터럴 하드코딩)은 tests/test_file_filters.py 의 grep 게이트가 막는다.
"""

from __future__ import annotations

from ..domain.data_source import CONTRACT_LIST_FILE_EXTENSIONS as CONTRACT_LIST_EXTS
from ..domain.data_source import SUPPORTED_DATA_FILE_EXTENSIONS as EXCEL_EXTS

# 데이터 파일(엑셀/CSV) 선택 필터 — EXCEL_EXTS 파생(리터럴 확장자 금지).
EXCEL_FILTER = "엑셀/CSV (" + " ".join(f"*{ext}" for ext in EXCEL_EXTS) + ")"

# 같은 EXCEL_EXTS 파생, Win32 comdlg32 파일 다이얼로그(웹 프론트, 에픽 #20)용 확장자 패턴.
# Win32 필터는 세미콜론 구분(Qt 는 공백). 설명 문자열은 웹앱 다이얼로그 호출부가 붙인다 —
# 단일 출처(EXCEL_EXTS)는 같아 화면별 확장자 하드코딩 사본을 만들지 않는다.
EXCEL_FILTER_PATTERN = ";".join(f"*{ext}" for ext in EXCEL_EXTS)

# 계약 목록(SQLite ``.db``·``.pclm``) 패턴 — CONTRACT_LIST_EXTS 파생.
CONTRACT_LIST_FILTER_PATTERN = ";".join(f"*{ext}" for ext in CONTRACT_LIST_EXTS)

# 파일 고르기 한 입구가 받는 전부(엑셀/CSV + 계약 목록) — 두 정본의 합집합 파생.
DATA_FILE_FILTER_PATTERN = ";".join(f"*{ext}" for ext in (*EXCEL_EXTS, *CONTRACT_LIST_EXTS))

# 파일 고르기 한 입구(웹앱 pick_data_file)의 Win32 (설명, 패턴) 목록 — 엑셀/CSV 와 계약 목록을
# 함께 받는다. 첫 항목이 둘의 합집합이라 기본 보기에서 두 종류가 다 보인다.
DATA_FILE_FILTERS = [
    ("데이터 파일", DATA_FILE_FILTER_PATTERN),
    ("엑셀/CSV 데이터", EXCEL_FILTER_PATTERN),
    ("계약 목록 자료", CONTRACT_LIST_FILTER_PATTERN),
    ("모든 파일", "*.*"),
]

# 등록·다시 연결 폼의 「찾아보기」(웹앱 pick_pool_data_file) 목록 — 그 폼의 좌표는 엑셀 경로라
# 엑셀/CSV 만 연다(계약 목록은 파일 고르기 입구가 DB 자리를 채운 등록 폼으로 잇는다).
EXCEL_FILE_FILTERS = [("엑셀/CSV 데이터", EXCEL_FILTER_PATTERN), ("모든 파일", "*.*")]

# HWPX 문서(템플릿·기존 문서) 선택 필터. Win32 comdlg32 는 (설명, 패턴) 쌍을 받으므로
# 패턴을 따로 낸다 — 설명 문자열이 패턴에서 파생해 둘이 갈릴 자리가 없다.
HWPX_FILTER_PATTERN = "*.hwpx"
HWPX_FILTER = f"HWPX ({HWPX_FILTER_PATTERN})"
