"""컴파일 수명주기 상태(``compile_status``) 계약 테스트 — 4-상태 파생·재산출·드리프트.

핵심 증명: 상태는 파일에 찍힌 도장이 아니라 스키마·스캔·실제 값에서 매번 **다시 계산**된다.
그래서 재편집으로 새 토큰이 끼면 COMPILED 가 즉시 PARTIAL 로 재판정된다(저장값이 아님).

State is a computed value (never stored): re-editing a compiled doc drifts it back to PARTIAL.
"""

from __future__ import annotations

from lxml import etree

from hwpxfiller.core.authoring import compile_document
from hwpxfiller.core.fields import FieldDocument
from hwpxfiller.core.template_status import CompileState, compile_status
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"

SECTION = "Contents/section0.xml"


def _pkg(section_inner: str) -> HwpxPackage:
    """test_authoring.py 의 인메모리 픽스처 패턴을 그대로 차용."""
    sec = (
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{section_inner}</hs:sec>'
    ).encode("utf-8")
    pkg = HwpxPackage()
    pkg.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    pkg.stored.add(MIMETYPE_NAME)
    pkg.entries[SECTION] = sec
    return pkg


# --------------------------------------------------------------------- RAW
def test_raw_plaintext_token_only():
    """필드 0개 + 본문 평문 ``{{계약명}}`` → RAW(미컴파일 원문)."""
    xml = "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>"
    st = compile_status(_pkg(xml))
    assert st.state == CompileState.RAW
    assert st.field_n == 0


def test_raw_when_no_fields_and_no_tokens():
    """필드도 토큰도 없으면 정직하게 RAW(컴파일된 것이 없음)."""
    xml = "<hp:p><hp:run><hp:t>본문만 있고 토큰 없음</hp:t></hp:run></hp:p>"
    st = compile_status(_pkg(xml))
    assert st.state == CompileState.RAW
    assert st.field_n == 0
    assert st.compilable_n == 0
    assert st.stray_n == 0


# ------------------------------------------------------------------- PARTIAL
def test_partial_field_plus_leftover_token():
    """진짜 누름틀 1개 + 파편에 걸친 토큰 잔존 → PARTIAL('다 된 듯 아닌' 위험)."""
    xml = (
        "<hp:p><hp:run><hp:t>{{계약명}}</hp:t></hp:run></hp:p>"
        "<hp:p><hp:run><hp:t>{{사업</hp:t></hp:run>"
        "<hp:run><hp:t>예산}}</hp:t></hp:run></hp:p>"
    )
    pkg, report = compile_document(_pkg(xml))
    assert report.compiled == ["계약명"]  # 첫 토큰만 컴파일, 파편은 skipped
    st = compile_status(pkg)
    assert st.state == CompileState.PARTIAL
    assert st.field_n == 1
    # 잔존 토큰이 어느 신호로든 소리 나게 남아 있어야 한다.
    assert st.skipped_n >= 1 or st.stray_n >= 1


# ------------------------------------------------------------------ COMPILED
def test_compiled_unfilled_values_are_placeholder_literals():
    """평문 토큰을 컴파일만 하고 채우지 않으면 값이 ``{{name}}`` 리터럴 → COMPILED."""
    xml = "<hp:p><hp:run><hp:t>계약명: {{계약명}} 예산 {{사업예산}}</hp:t></hp:run></hp:p>"
    pkg, report = compile_document(_pkg(xml))
    assert report.compiled == ["계약명", "사업예산"]
    st = compile_status(pkg)
    assert st.state == CompileState.COMPILED
    assert st.field_n == 2
    assert st.stray_n == 0
    assert st.compilable_n == 0


# -------------------------------------------------------------------- FILLED
def test_filled_after_set_field():
    """COMPILED 문서에 실제 값을 주입하면 값이 placeholder 와 달라져 → FILLED."""
    xml = "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>"
    pkg, _ = compile_document(_pkg(xml))
    assert compile_status(pkg).state == CompileState.COMPILED  # 채우기 전

    doc = FieldDocument(pkg.entries[SECTION])
    assert doc.set_field("계약명", "정보시스템 구축 사업") is True
    pkg.entries[SECTION] = doc.to_bytes()  # 패키지 엔트리 재빌드

    st = compile_status(pkg)
    assert st.state == CompileState.FILLED
    assert st.field_n == 1
    assert st.stray_n == 0


# --------------------------------------------------- 저장 없음 / 재산출 / 무변형
def test_recompute_is_readonly_and_stable():
    """두 번 호출해도 결과가 같고 섹션 XML 바이트가 그대로다(계산값·무변형)."""
    xml = "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>"
    pkg, _ = compile_document(_pkg(xml))
    before = pkg.entries[SECTION]

    first = compile_status(pkg)
    second = compile_status(pkg)

    assert pkg.entries[SECTION] == before  # 무변형(도장 안 찍음)
    assert first == second
    assert first.to_dict() == second.to_dict()


# ------------------------------------------------------ 한글 재편집 드리프트 시뮬
def test_reedit_drift_recomputes_compiled_to_partial():
    """COMPILED 에 새 평문 ``{{추가}}`` 를 주입 → 재산출 시 PARTIAL(저장 도장이 아님을 증명)."""
    xml = "<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>"
    pkg, _ = compile_document(_pkg(xml))
    assert compile_status(pkg).state == CompileState.COMPILED

    # 사용자가 한글에서 문단 하나를 새로 타이핑(재편집 드리프트).
    root = etree.fromstring(pkg.entries[SECTION])
    newp = etree.SubElement(root, f"{{{HP}}}p")
    run = etree.SubElement(newp, f"{{{HP}}}run")
    t = etree.SubElement(run, f"{{{HP}}}t")
    t.text = "추가항목: {{추가}}"
    pkg.entries[SECTION] = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )

    st = compile_status(pkg)
    assert st.state == CompileState.PARTIAL  # 도장이었다면 여전히 COMPILED 였을 것
    assert st.field_n == 1
    assert st.compilable_n >= 1 or st.stray_n >= 1
