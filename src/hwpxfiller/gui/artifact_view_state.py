"""생성된 Artifact 의 **구조 관찰** 스냅샷 — S7-02 · #824 의 데이터 반쪽(링1).

## 무엇을 보는가

이 모듈은 **이미 만들어진 문서**(생성 후 실물)를 본다. 입력은 관찰 커널이 검증하고 다시
파싱한 **열린 package** 하나뿐이다 — 여기서 파일을 열지 않고, digest 도 모르고, 원장도
되읽지 않는다. 검증의 권위는 커널이 지고 이 층은 그 결과를 화면이 그릴 수 있는
JSON-safe 값으로 **투영만** 한다(링1: Qt-free · DOM-free · 파일 IO 0).

## Projection 과 Artifact View 는 다른 어휘다(#820 D4)

여기 나오는 값은 **생성 후** 실물의 관찰이다. 생성 **전** 값을 그리던 확인 면과 그
projection 은 #957 에서 철거됐지만 어휘 규율은 남는다 — 이 모듈의 공개 이름과 dict 키에는
``preview``·``projection`` 어근을 쓰지 않고 observed/artifact 계열만 쓴다. 그 규율은
테스트가 직렬화 전문을 훑어 지킨다.

## 충실도는 구조 뷰, 못 본 구간은 숨기지 않는다(#820 D3)

투영의 원천은 :func:`hwpxcore.extract_document` 다 — 문단 텍스트와 표의 행/열,
``span``/``addr`` 병합 메타를 그대로 나른다(렌더러·페이지 조판·서식 재현은 비범위, #360).
그 커널이 모델링하지 못한 구조는 ``CoverageLedger`` 에 소리 나게 남는데, 이 스냅샷은 그
원장을 ``unrendered_regions`` 로 **항상** 실어 보낸다(비어 있어도 키는 있다). 「표시하지
못한 구간」을 키째 지우면 화면은 완전한 관찰과 부분 관찰을 구분할 수 없고, 사용자는 못 본
구간을 본 것으로 착각한다.

부분 포섭은 **거절이 아니다**(#820 §3 ``ARTIFACT_PARTIAL_COVERAGE``). 관찰은 성립하고
스냅샷은 그대로 서며, ``coverage_code`` 는 그 옆에 병기되는 사유일 뿐이다.

## 미치환 표식은 값이 아니라 사건이다

빈 값·미치환 토큰이 빈칸으로 새지 않고 표식으로 남는 것이 제품 계약이라, 실물에 그 표식이
남았다면 관찰은 그것을 **세어서** 드러낸다. 표식 산식의 정본은
:data:`hwpxfiller.domain.job.MISSING_MARKER` 하나이므로 여기서는 문자열을 다시 적지 않고
그 상수에서 정규식을 파생한다 — 정본이 바뀌면 이 검출도 같이 움직인다.
"""
from __future__ import annotations

import re
from typing import Iterator

from hwpxcore import extract_document

from ..domain.job import MISSING_MARKER

#: 부분 포섭 병기 코드(#820 §3). 관찰은 성립하므로 **거절 코드가 아니다** — 화면은 이
#: 코드를 「표시하지 못한 구간」 병기의 사유로만 쓴다.
ARTIFACT_PARTIAL_COVERAGE = "ARTIFACT_PARTIAL_COVERAGE"

#: 스냅샷 형상의 이름표 — 소비자가 형상을 되묻지 않고 분기할 수 있게 값에 박는다.
_SNAPSHOT_KIND = "artifact-observation/v1"

#: 미치환 표식 검출기 — :data:`MISSING_MARKER` **에서 파생**한다(문자열 재기술 금지).
#: 자리표시자만 비탐욕 그룹으로 바꾸므로 표식 정본이 바뀌면 이 패턴도 따라 바뀐다.
_MISSING_MARKER_RE = re.compile(
    re.escape(MISSING_MARKER).replace(re.escape("{field}"), "(?P<field>.+?)")
)


def _iter_block_texts(blocks: "list") -> "Iterator[str]":
    """블록 목록을 문서 순서로 훑으며 문단 텍스트를 낸다(표 셀·중첩 표 재귀 포함).

    ``Document.to_dict()`` 산출 형상(dict) 위에서 돈다 — 데이터클래스와 dict 두 벌을
    훑는 경로를 만들지 않기 위해서다.
    """
    for block in blocks:
        if block.get("type") == "paragraph":
            yield block.get("text", "")
            continue
        # 문단이 아니면 표다 — 행/열을 타고 셀 안으로 재귀한다(중첩 표 포함).
        for row in block.get("rows", []):
            for cell in row:
                yield from _iter_block_texts(cell.get("blocks", []))


def _missing_value_markers(regions: "list") -> "list[dict]":
    """영역 목록에서 미치환 표식을 필드별로 합산 — 필드 이름 정렬로 결정적 순서."""
    counts: "dict[str, int]" = {}
    for region in regions:
        for text in _iter_block_texts(region.get("blocks", [])):
            for match in _MISSING_MARKER_RE.finditer(text):
                name = match.group("field")
                counts[name] = counts.get(name, 0) + 1
    return [{"field": name, "count": counts[name]} for name in sorted(counts)]


def observed_artifact_snapshot(package: object) -> dict:
    """검증된 열린 package 를 JSON-safe 관찰 스냅샷으로 투영한다.

    ``package`` 는 관찰 커널이 **이미 검증·재파싱한** 열린 package 다(경로·바이트는
    받지 않는다 — :func:`hwpxcore.extract_document` 의 package-only 관문이 그것을
    소리 나게 거절한다).

    반환 dict 의 키:

    - ``kind`` — 스냅샷 형상 이름표.
    - ``sections``/``headers``/``footers`` — 문단·표 구조 그대로(병합 메타 보존).
    - ``unrendered_regions`` — ``{"counts", "examples"}``. 「표시하지 못한 구간」 병기용
      이고 비어 있어도 **키는 항상 있다**.
    - ``partial_coverage`` — 못 본 구간이 하나라도 있으면 참.
    - ``coverage_code`` — 부분이면 :data:`ARTIFACT_PARTIAL_COVERAGE`, 아니면 빈 문자열.
    - ``missing_value_markers`` — ``[{"field", "count"}, ...]``, 필드 이름 정렬.
    """
    payload = extract_document(package).to_dict()
    unhandled = payload["unhandled"]
    partial = bool(unhandled)
    regions = [*payload["sections"], *payload["headers"], *payload["footers"]]
    return {
        "kind": _SNAPSHOT_KIND,
        "sections": payload["sections"],
        "headers": payload["headers"],
        "footers": payload["footers"],
        "unrendered_regions": {
            "counts": unhandled,
            "examples": payload["unhandled_examples"],
        },
        "partial_coverage": partial,
        "coverage_code": ARTIFACT_PARTIAL_COVERAGE if partial else "",
        "missing_value_markers": _missing_value_markers(regions),
    }
