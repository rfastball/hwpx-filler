"""제품 불가지 HWPX 형식 kernel(OCF 패키지 + 문서 트리 추출).

제품 의미와 환경 효과는 :mod:`hwpxfiller` 경계가 소유한다.
"""

from __future__ import annotations

from .text_extract import Document, extract_document

__all__ = [
    "Document",
    "extract_document",
]
