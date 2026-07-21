"""줄배치 캐시 스트립 헬퍼(#95) 단위 테스트 — 전량 제거·타 요소 불변·네임스페이스 불가지."""

from __future__ import annotations

from lxml import etree

from hwpxcore.lineseg import strip_line_layout

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"


def test_strips_all_lineseg_and_preserves_everything_else():
    xml = f"""<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">
      <hp:p>
        <hp:run><hp:t>본문 텍스트</hp:t></hp:run>
        <hp:linesegarray><hp:lineseg textpos="0"/></hp:linesegarray>
      </hp:p>
      <hp:p>
        <!-- 주석 노드는 tag 가 str 이 아니어도 안전해야 한다 -->
        <hp:run><hp:tab/><hp:t>둘째 문단</hp:t></hp:run>
        <hp:linesegarray/>
      </hp:p>
    </hs:sec>""".encode()
    root = etree.fromstring(xml)
    strip_line_layout(root)
    out = etree.tostring(root, encoding="unicode")
    assert "linesegarray" not in out
    assert "lineseg" not in out  # 자식까지 통째로 제거
    # 타 요소·텍스트는 원형 보존
    assert "본문 텍스트" in out
    assert "둘째 문단" in out
    assert "<hp:tab/>" in out


def test_namespace_agnostic_matches_local_name_only():
    # 접두사·네임스페이스가 달라도(무네임스페이스 포함) 로컬명으로 매치한다.
    xml = (
        '<root xmlns:x="urn:other">'
        "<x:linesegarray/><linesegarray/>"
        "<linesegarrayX/><x:lineseg/>"
        "</root>"
    ).encode()
    root = etree.fromstring(xml)
    strip_line_layout(root)
    out = etree.tostring(root)
    assert b"linesegarray/" not in out
    assert b"linesegarrayX" in out  # 유사 이름은 건드리지 않는다
    assert b"x:lineseg/" in out  # 독립 등장한 lineseg 는 대상 아님


def test_idempotent_on_clean_tree():
    xml = f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}"><hp:p/></hs:sec>'.encode()
    root = etree.fromstring(xml)
    before = etree.tostring(root)
    strip_line_layout(root)
    strip_line_layout(root)
    assert etree.tostring(root) == before
