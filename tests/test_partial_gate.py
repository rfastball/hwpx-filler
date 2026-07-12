"""PARTIAL 확정 게이트(위저드 1단계) — Qt 불필요(헤드리스).

핵심 회귀: "다 된 것 같지만 아닌" PARTIAL 상태(필드는 있는데 값이 조용히 누락될 잔존
토큰이 남음)를 게이트가 **조용히 통과시키지 않는다**. PARTIAL 은 (a) 명시 ack 또는
(b) 인라인 컴파일로 COMPILED 가 되기 전까지 진행 불가다(confirm-or-alarm).

ack 는 반사적 dismiss 에 저항해야 한다 — 정확히 재진술된 미해결 이름 전체를 확인할 때만
성립하고, 부분/엉뚱/오래된 확인으로는 게이트가 열리지 않는다(ADR-E).
"""

from __future__ import annotations

from lxml import etree

from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.core.authoring import compile_document
from hwpxfiller.core.fields import FieldDocument
from hwpxfiller.core.template_status import CompileState, TemplateStatus, compile_status
from hwpxfiller.gui.mapping_state import PartialGate, gate_for_template

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
SECTION = "Contents/section0.xml"


def _pkg(section_inner: str) -> HwpxPackage:
    """test_template_status.py 의 인메모리 픽스처 패턴을 차용."""
    sec = (f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{section_inner}</hs:sec>').encode(
        "utf-8"
    )
    pkg = HwpxPackage()
    pkg.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    pkg.stored.add(MIMETYPE_NAME)
    pkg.entries[SECTION] = sec
    return pkg


def _append_plaintext(pkg: HwpxPackage, text: str) -> HwpxPackage:
    """섹션에 평문 문단을 하나 덧붙인다(미컴파일 잔존 토큰 시뮬)."""
    root = etree.fromstring(pkg.entries[SECTION])
    p = etree.SubElement(root, f"{{{HP}}}p")
    run = etree.SubElement(p, f"{{{HP}}}run")
    t = etree.SubElement(run, f"{{{HP}}}t")
    t.text = text
    pkg.entries[SECTION] = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True
    )
    return pkg


def _partial_compilable_pkg() -> HwpxPackage:
    """진짜 필드 1개(계약명) + 미컴파일 평문 ``{{미컴파일필드}}`` → PARTIAL(compilable)."""
    pkg, _ = compile_document(_pkg("<hp:p><hp:run><hp:t>{{계약명}}</hp:t></hp:run></hp:p>"))
    return _append_plaintext(pkg, "{{미컴파일필드}}")


# --------------------------------------------------------------- 순수 결정표
def _status(state: CompileState) -> TemplateStatus:
    # PARTIAL 은 잔존 토큰 카운트가 있어야 자연스럽다(순수 판정은 state 만 본다).
    leftover = 1 if state is CompileState.PARTIAL else 0
    return TemplateStatus(state, field_n=1, compilable_n=leftover, skipped_n=0, stray_n=0)


def test_pure_gate_decision_table():
    """순수 판정 — RAW·PARTIAL 차단, COMPILED·FILLED 통과(Qt·패키지 무관)."""
    assert not PartialGate(_status(CompileState.RAW)).can_proceed()
    assert not PartialGate(_status(CompileState.PARTIAL), ["a"]).can_proceed()

    compiled = PartialGate(_status(CompileState.COMPILED))
    assert compiled.can_proceed()
    assert not compiled.needs_gate()
    assert PartialGate(_status(CompileState.FILLED)).can_proceed()


def test_pure_gate_ack_requires_exact_names():
    """ack 는 정확히 재진술된 이름 전체를 확인할 때만 성립(반사적 dismiss 봉쇄)."""
    gate = PartialGate(_status(CompileState.PARTIAL), ["계약명", "미결"])
    assert not gate.can_proceed()

    gate.acknowledge([])  # 빈 확인 = 불성립
    assert not gate.can_proceed()
    gate.acknowledge(["계약명"])  # 부분 확인 = 불성립
    assert not gate.can_proceed()
    gate.acknowledge(["엉뚱한이름", "계약명"])  # 엉뚱한 이름 = 불성립
    assert not gate.can_proceed()

    gate.acknowledge(["계약명", "미결"])  # 정확히 전체 = 성립
    assert gate.can_proceed()


# --------------------------------------------- 실제 PARTIAL 템플릿 파생(스캔+상태)
def test_partial_template_blocks_until_ack():
    """PARTIAL 템플릿 → 게이트 차단; 구체 이름 재진술 후 ack → 통과(수용 1·2)."""
    gate = gate_for_template(_partial_compilable_pkg())
    assert gate.state is CompileState.PARTIAL
    assert gate.needs_gate()
    assert not gate.can_proceed()

    # 메시지가 구체 토큰 이름을 재진술한다(범용 메시지 아님).
    assert "미컴파일필드" in gate.unmet_tokens
    assert "미컴파일필드" in gate.message()

    gate.acknowledge(gate.unmet_tokens)  # 정확한 이름 전체 확인
    assert gate.can_proceed()
    assert "확인함" in gate.message()


def test_partial_stray_inside_field_value_blocks():
    """필드 값 자리에 미해결 ``{{미결}}`` 이 남은 stray 채널 PARTIAL 도 차단·재진술."""
    pkg, _ = compile_document(
        _pkg("<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>")
    )
    doc = FieldDocument(pkg.entries[SECTION])
    assert doc.set_field("계약명", "{{미결}}") is True
    pkg.entries[SECTION] = doc.to_bytes()

    gate = gate_for_template(pkg)
    assert gate.state is CompileState.PARTIAL
    assert "미결" in gate.unmet_tokens  # stray 이름 재진술
    assert not gate.can_proceed()
    gate.acknowledge(gate.unmet_tokens)
    assert gate.can_proceed()


def test_raw_blocks_and_compiled_filled_pass():
    """RAW 차단, COMPILED·FILLED 게이트 없이 통과(수용 3)."""
    raw = gate_for_template(
        _pkg("<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>")
    )
    assert raw.state is CompileState.RAW
    assert not raw.can_proceed()

    pkg, _ = compile_document(
        _pkg("<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>")
    )
    compiled = gate_for_template(pkg)
    assert compiled.state is CompileState.COMPILED
    assert compiled.can_proceed() and not compiled.needs_gate()

    doc = FieldDocument(pkg.entries[SECTION])
    assert doc.set_field("계약명", "정보시스템 구축") is True
    pkg.entries[SECTION] = doc.to_bytes()
    filled = gate_for_template(pkg)
    assert filled.state is CompileState.FILLED
    assert filled.can_proceed()


def test_whitespace_name_token_is_ackable():
    """무명 토큰 ``{{   }}``(공백뿐) — compilable 로 PARTIAL 트리거되지만 정제 이름은 "".

    열거가 트리거와 어긋나 unmet 이 비면 ack 가 '0개 토큰' dead-end 가 된다. 대표 라벨로
    열거해 ack 가 실제로 게이트를 열 수 있어야 한다(Finding 2).
    """
    pkg, _ = compile_document(_pkg("<hp:p><hp:run><hp:t>{{계약명}}</hp:t></hp:run></hp:p>"))
    pkg = _append_plaintext(pkg, "{{   }}")

    gate = gate_for_template(pkg)
    assert gate.state is CompileState.PARTIAL
    assert gate.unmet_tokens  # 무명 토큰도 대표 라벨로 열거 → 비어 있지 않음
    assert not gate.can_proceed()

    gate.acknowledge(gate.unmet_tokens)
    assert gate.can_proceed()  # 더 이상 0-토큰 dead-end 가 아니다


def test_inline_compile_flips_partial_to_compiled():
    """PARTIAL(compilable) → compile_document 적용 → COMPILED, 게이트 통과(수용 4).

    위저드 [여기서 컴파일] 의 핵심 파생을 순수 계층에서 증명한다(위젯은 이걸 그대로 호출).
    """
    pkg = _partial_compilable_pkg()
    assert gate_for_template(pkg).state is CompileState.PARTIAL

    compiled_pkg, report = compile_document(pkg)
    assert report.modified
    assert "미컴파일필드" in report.compiled

    gate = gate_for_template(compiled_pkg)
    assert gate.state is CompileState.COMPILED
    assert gate.can_proceed()
    # 컴파일본은 실제로 잔존 토큰이 사라진 상태여야 한다.
    assert compile_status(compiled_pkg).compilable_n == 0
