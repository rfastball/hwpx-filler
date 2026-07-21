"""줄배치 레이아웃 캐시(``<hp:linesegarray>``) 스트립 — #95.

``linesegarray`` 는 한글이 저장 시 심는 문단별 줄배치 레이아웃 캐시다. 섹션 트리를
변형(채움·토큰 컴파일)한 뒤 재직렬화하면서 이 캐시를 그대로 통과시키면 실제
텍스트/런 구조와 어긋난 stale 캐시가 되고, 한컴이 이를 "변조(tamper)"로 판정할 수
있다. 선택적 요소라 제거해도 뷰어가 열 때 레이아웃을 재계산할 뿐 의미 손실이 없다.
"""

from __future__ import annotations

from lxml import etree


def strip_line_layout(root: etree._Element) -> None:
    """변형된 섹션 트리에서 stale 줄배치 캐시(``<hp:linesegarray>``)를 전량 제거.

    네임스페이스 불가지 — 로컬명만 매치(실템플릿의 접두사/네임스페이스 변주 대비).
    부분 스트립은 문서 전역 일관성 검사를 여전히 건드리므로 섹션 전체를 제거한다.
    **변형된** 섹션에만 호출할 것 — 미변경 섹션의 캐시는 유효하므로 보존한다.
    """
    for seg in list(root.iter()):
        if isinstance(seg.tag, str) and seg.tag.rsplit("}", 1)[-1] == "linesegarray":
            parent = seg.getparent()
            if parent is not None:
                parent.remove(seg)
