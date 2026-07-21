"""줄배치 레이아웃 캐시(``<hp:linesegarray>``) 스트립 — #95.

``linesegarray`` 는 한글이 저장 시 심는 문단별 줄배치 레이아웃 캐시다. 섹션 트리를
변형(채움·토큰 컴파일)한 뒤 재직렬화하면서 이 캐시를 그대로 통과시키면 실제
텍스트/런 구조와 어긋난 stale 캐시가 되고, 한컴이 이를 "변조(tamper)"로 판정할 수
있다. 선택적 요소라 제거해도 뷰어가 열 때 레이아웃을 재계산할 뿐 의미 손실이 없다.
"""

from __future__ import annotations

from lxml import etree

# 도메인 사실의 단일 출처 — "linesegarray 는 본문 텍스트 없는 레이아웃 캐시".
# 추출 경로(text_extract._IGNORE_P)와 스트립 경로가 함께 참조한다.
LINESEG_LOCAL = "linesegarray"


def strip_line_layout(root: etree._Element) -> None:
    """변형된 섹션 트리에서 stale 줄배치 캐시(``<hp:linesegarray>``)를 전량 제거.

    네임스페이스 불가지(``{*}`` = 모든/무 네임스페이스) — 실템플릿의 접두사/네임스페이스
    변주 대비, 이슈 #95 의 의도된 선택. 부분 스트립은 문서 전역 일관성 검사를 여전히
    건드리므로 섹션 전체를 제거한다. **변형된** 섹션에만 호출할 것 — 미변경 섹션의
    캐시는 유효하므로 보존한다.

    ``with_tail=False``: 제거 요소의 tail 텍스트는 문서 본문이므로 앞 형제/부모에
    되붙여 보존한다(``parent.remove`` 는 tail 을 함께 버려 조용한 텍스트 소실).
    """
    etree.strip_elements(root, f"{{*}}{LINESEG_LOCAL}", with_tail=False)


def serialize_modified_section(root: etree._Element) -> bytes:
    """변형된 섹션 트리의 정본 직렬화 — 스트립과 재직렬화를 한 seam 에 묶는다.

    섹션을 변형·재직렬화하는 모든 쓰기 경로(채움 ``fields.to_bytes``·토큰 컴파일
    ``authoring.compile_document``·미래의 경로)는 이 함수를 쓴다 — 새 경로가 스트립
    호출을 개별적으로 기억하지 않아도 되게(#95 재발 클래스 차단).
    """
    strip_line_layout(root)
    return etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )
