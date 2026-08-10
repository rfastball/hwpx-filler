"""hwpxcore — HWPX 공통 파서(OCF 패키지 + 문서 트리 추출 + 검증).

제품 :mod:`hwpxfiller`(누름틀 값 주입)가 이 위에 선다. 의존 방향은 아래로만이다.

여기엔 제품 로직을 두지 않는다 — 파싱·패키징·검증뿐. 이 규칙은 제품이 하나가 된
지금도 유효하다: 별도 저장소 ``hwpx-diff``(규격서 개정 비교, 읽기 도구)가 이 계층의
**사본**을 들고 있어, 제품 색이 스며들면 두 사본을 대조할 수 없게 된다.
파서를 고칠 때 저쪽에도 필요한 변경인지 판단하고, 필요하면 각각 반영한다.
"""

from __future__ import annotations

from .text_extract import Document, extract_document
from .validate import ValidationReport, validate

__all__ = [
    "Document",
    "extract_document",
    "ValidationReport",
    "validate",
]
