"""파일 다이얼로그 필터 문자열 — 단일 출처(RC-34).

지원 확장자의 실질 단일 출처는 :mod:`hwpxfiller.data.factory` 의 ``EXCEL_EXTS`` 다 —
엑셀/CSV 필터는 거기서 **파생**한다. 확장자 정책이 바뀌면(예: ``.xls`` 추가) 모든
파일 다이얼로그가 함께 움직인다 — 화면 단위 하드코딩 사본이 새 형식을 조용히
숨기는 드리프트를 끊는다.

hwpxdiff 는 제품 간 임포트 금지 규칙(tests/test_architecture.py) 때문에 자체
``HWPX_FILTER`` 상수를 소유한다. 재유입(필터 리터럴 하드코딩)은
tests/test_file_filters.py 의 grep 게이트가 막는다.
"""

from __future__ import annotations

from ..data.factory import EXCEL_EXTS

# 데이터 파일(엑셀/CSV) 선택 필터 — EXCEL_EXTS 파생(리터럴 확장자 금지).
EXCEL_FILTER = "엑셀/CSV (" + " ".join(f"*{ext}" for ext in EXCEL_EXTS) + ")"

# HWPX 문서(템플릿·기존 문서) 선택 필터.
HWPX_FILTER = "HWPX (*.hwpx)"
