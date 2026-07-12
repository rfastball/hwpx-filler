"""hwpxcore — HWPX 공통 파서(OCF 패키지 + 문서 트리 추출 + 검증).

두 제품이 이 위에 선다(의존 방향은 아래로만):
  - :mod:`hwpxdiff`   — 규격서 개정 비교(읽기 도구)
  - :mod:`hwpxfiller` — 누름틀 값 주입(쓰기 도구)

여기엔 제품 로직을 두지 않는다 — 파싱·패키징·검증뿐.
"""

from __future__ import annotations

from .atomic import write_bytes_atomic, write_text_atomic
from .package import HwpxPackage
from .text_extract import Document, extract_document
from .validate import ValidationReport, validate

__all__ = [
    "write_bytes_atomic",
    "write_text_atomic",
    "HwpxPackage",
    "Document",
    "extract_document",
    "ValidationReport",
    "validate",
]
