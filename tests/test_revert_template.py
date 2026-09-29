"""문서 명령 「원본 템플릿으로 되돌리기」(#1078) — 채운 필드 값을 ``{{이름}}`` 원형으로 되돌린다.

「채워짐」 상태(FILLED)는 퇴역했다: 채운 템플릿은 채우지 않은 템플릿과 똑같이 작동한다. 값을 원형으로
되돌리는 일은 저작 작업대의 문서 명령이 맡고, 값 판독(원형인가)은 그 명령의 가용 판정에만 남는다.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxcore.structural_boundary import scan_structural_boundaries
from hwpxfiller.domain import template_authoring as semantics
from hwpxfiller.domain.authoring import compile_document
from hwpxfiller.domain.fields import FieldDocument
from hwpxfiller.domain.structure_scan import PLACEMENT_OPTION, PLACEMENT_SLOT
from hwpxfiller.domain.template_status import CompileState, compile_status
from hwpxfiller.external import hwpx_authoring
from hwpxfiller.external.hwpx_authoring import analyze_hwpx, apply_hwpx
from hwpxfiller.external.hwpx_product_inspection import (
    AUTHORING_KIND_BY_PRODUCT_KIND,
    PRODUCT_KIND_OPTION,
    PRODUCT_KIND_SLOT,
    PRODUCT_KINDS,
    ProductClassification,
    inspect_product_bookmarks,
)
from hwpxfiller.webapp.screen_authoring import AuthoringController

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
SECTION = "Contents/section0.xml"
REVERT = {"type": semantics.REVERT_TEMPLATE}


def _pkg(section_inner: str, *, extra: "dict[str, str] | None" = None) -> HwpxPackage:
    pkg = HwpxPackage()
    pkg.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    pkg.stored.add(MIMETYPE_NAME)
    for entry, inner in {SECTION: section_inner, **(extra or {})}.items():
        pkg.entries[entry] = f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{inner}</hs:sec>'.encode("utf-8")
    return pkg


def _filled(section_inner: str, values: "dict[str, str]", *, extra: "dict[str, str] | None" = None) -> HwpxPackage:
    """누름틀 변환 뒤 ``values`` 를 생성과 같은 채움 경로로 주입한 문서."""
    pkg, _ = compile_document(_pkg(section_inner, extra=extra))
    for entry in pkg.content_xml_names():
        doc = FieldDocument(pkg.entries[entry], entry=entry)
        for name, value in values.items():
            doc.set_field(name, value)
        pkg.entries[entry] = doc.to_bytes()
    return pkg


def _values(pkg: HwpxPackage) -> "list[tuple[str, str]]":
    return [(field["name"], occurrence["raw"]["value"]) for field in analyze_hwpx(pkg)["fields"]
            for occurrence in field["occurrences"]]


def _availability(pkg: HwpxPackage) -> dict:
    [entry] = semantics.document_commands("hwpx", analyze_hwpx(pkg))
    return entry


# ------------------------------------------------------------------ 값 판독(원형인가)
@pytest.mark.parametrize(("value", "name", "placeholder"), [
    ("{{계약명}}", "계약명", True),
    # 누름틀 변환은 원문 토큰(내부 공백 포함)을 값 런에 남긴다 — 공백은 원형을 바꾸지 않는다.
    ("{{ 계약명 }}", "계약명", True),
    (" {{계약 명}} ", "계약 명", True),
    ("{{x{{계약명}}}}", "x{{계약명}}", True),
    ("{{x{{계약명}}}}", "다른필드", False),
    ("정보시스템 구축", "계약명", False),
    ("{{계약명", "계약명", False),
    ("", "계약명", False),
])
def test_placeholder_reading_absorbs_whitespace(value: str, name: str, placeholder: bool) -> None:
    assert semantics.is_placeholder_value(value, name) is placeholder


@pytest.mark.parametrize(("value", "filled"), [
    ("정보시스템 구축", True), ("{{다른필드}}", True), ("{{ 계약명 }}", False), ("", False), ("  \t", False),
])
def test_only_real_values_count_as_filled(value: str, filled: bool) -> None:
    assert semantics.is_filled_value(value, "계약명") is filled


def test_the_placeholder_round_trips_as_its_own_name() -> None:
    for name in ("계약명", "사업 예산", "x{{계약명}}"):
        assert semantics.is_placeholder_value(semantics.field_placeholder(name), name)


# ------------------------------------------------------------------ 가용 판정
def test_available_only_while_a_field_holds_a_real_value() -> None:
    xml = "<hp:p><hp:run><hp:t>계약명: {{계약명}} 예산 {{ 사업예산 }}</hp:t></hp:run></hp:p>"
    compiled, _ = compile_document(_pkg(xml))
    assert _availability(compiled) == {"type": semantics.REVERT_TEMPLATE, "enabled": False,
                                       "reason": semantics.REASON_NO_FILLED_VALUE, "alternative": None}
    filled = _filled(xml, {"계약명": "정보시스템 구축"})
    assert _availability(filled) == {"type": semantics.REVERT_TEMPLATE, "enabled": True,
                                     "reason": None, "alternative": None}
    assert semantics.filled_value_count("hwpx", analyze_hwpx(filled)) == 1


def test_txt_has_no_filled_values_and_refuses_the_command() -> None:
    """TXT 필드는 ``{{이름}}`` 표기 자체다 — 채운 값이라는 개념이 없어 늘 불가이고 실행도 같은 사유로 거절한다."""
    text = "계약명: {{계약명}}\n"
    [entry] = semantics.document_commands("txt", semantics.analyze("txt", text))
    assert entry == {"type": semantics.REVERT_TEMPLATE, "enabled": False,
                     "reason": semantics.REASON_NO_FILLED_VALUE, "alternative": None}
    with pytest.raises(ValueError, match=semantics.REASON_NO_FILLED_VALUE):
        semantics.apply("txt", text, REVERT)
    with pytest.raises(ValueError, match=semantics.REASON_NO_FILLED_VALUE):
        semantics.preview("txt", text, REVERT)


def test_revert_is_a_button_grade_document_command() -> None:
    assert semantics.confirm_tier(REVERT, {}) == semantics.CONFIRM_BUTTON
    assert semantics.command_label(REVERT) == "원본 템플릿으로 되돌리기"
    assert semantics.REVERT_TEMPLATE in semantics.DOCUMENT_COMMAND_TYPES
    # 선택 명령 표에는 들지 않는다 — 문맥 메뉴·속성 명령 선택은 고른 대상의 명령만 싣는다.
    assert semantics.REVERT_TEMPLATE not in semantics.COMMAND_TYPES


# ------------------------------------------------------------------ HWPX 실행
_TABLE = """
<hp:p><hp:run><hp:tbl><hp:tr>
  <hp:tc><hp:subList><hp:p><hp:run><hp:t>품명</hp:t></hp:run></hp:p></hp:subList></hp:tc>
  <hp:tc><hp:subList><hp:p><hp:run><hp:t>{{공급가액}}</hp:t></hp:run></hp:p></hp:subList></hp:tc>
</hp:tr></hp:tbl></hp:run></hp:p>
"""


def test_every_filled_value_returns_to_its_placeholder() -> None:
    body = ("<hp:p><hp:run><hp:t>계약명: {{계약명}} / {{계약명}} 예산 {{ 사업예산 }}</hp:t></hp:run></hp:p>"
            + _TABLE)
    pkg = _filled(body, {"계약명": "정보시스템 구축", "공급가액": "1,000,000원"},
                  extra={"Contents/section1.xml": "<hp:p><hp:run><hp:t>{{담당자}}</hp:t></hp:run></hp:p>"})
    second = FieldDocument(pkg.entries["Contents/section1.xml"], entry="Contents/section1.xml")
    second.set_field("담당자", "홍길동")
    pkg.entries["Contents/section1.xml"] = second.to_bytes()
    untouched = [entry for entry in pkg.entries if entry not in pkg.content_xml_names()]
    before = {entry: pkg.entries[entry] for entry in untouched}

    result, impact = apply_hwpx(pkg, REVERT)

    assert sorted(_values(result)) == sorted([
        ("계약명", "{{계약명}}"), ("계약명", "{{계약명}}"), ("사업예산", "{{ 사업예산 }}"),
        ("공급가액", "{{공급가액}}"), ("담당자", "{{담당자}}")])
    # 되돌린 결과는 원본 템플릿이다 — 상태는 변환됨, 명령은 다시 불가다.
    assert compile_status(result).state is CompileState.COMPILED
    assert _availability(result)["enabled"] is False
    assert impact["affected"] == 4
    assert impact["message"] == "사라지는 것: 필드 값 4개"
    assert impact["label"] == "원본 템플릿으로 되돌리기"
    assert impact["before"] == "" and impact["after"] == ""
    assert sorted(impact["changed_entries"]) == [SECTION, "Contents/section1.xml"]
    assert {entry: result.entries[entry] for entry in untouched} == before


def test_a_section_without_filled_values_keeps_its_bytes() -> None:
    pkg = _filled("<hp:p><hp:run><hp:t>{{계약명}}</hp:t></hp:run></hp:p>", {"계약명": "값"},
                  extra={"Contents/section1.xml": "<hp:p><hp:run><hp:t>{{ 담당자 }}</hp:t></hp:run></hp:p>"})
    original = pkg.entries["Contents/section1.xml"]
    result, impact = apply_hwpx(pkg, REVERT)
    assert impact["changed_entries"] == [SECTION]
    assert result.entries["Contents/section1.xml"] == original


def test_revert_refuses_when_nothing_is_filled() -> None:
    compiled, _ = compile_document(_pkg("<hp:p><hp:run><hp:t>{{계약명}}</hp:t></hp:run></hp:p>"))
    original = dict(compiled.entries)
    with pytest.raises(ValueError, match=semantics.REASON_NO_FILLED_VALUE):
        apply_hwpx(compiled, REVERT)
    assert compiled.entries == original


@pytest.mark.parametrize("failure", ["unmatched", "unfillable"])
def test_revert_is_all_or_nothing(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    """한 자리라도 쓸 수 없으면 아무 자리도 고치지 않는다 — 일부만 되돌린 문서를 성공으로 내지 않는다."""
    pkg = _filled("<hp:p><hp:run><hp:t>{{가}} {{나}}</hp:t></hp:run></hp:p>", {"가": "1", "나": "2"})
    original = dict(pkg.entries)
    real = FieldDocument.set_field

    def failing(self: FieldDocument, name: str, value: str) -> bool:
        if name != "나":
            return real(self, name, value)
        if failure == "unmatched":
            return False
        written = real(self, name, value)
        self._note(name, "occurrence_unfillable")
        return written

    monkeypatch.setattr(hwpx_authoring.FieldDocument, "set_field", failing)
    with pytest.raises(ValueError, match="내용 보존을 확인할 수 없습니다"):
        apply_hwpx(pkg, REVERT)
    assert pkg.entries == original


# ------------------------------------------------------------------ 저작 세션(편집 사슬)
def test_session_projects_availability_and_applies_through_the_edit_chain(tmp_path: Path) -> None:
    ctrl = AuthoringController(lambda _name, _snapshot: None, directory=tmp_path / "home")
    pkg = _filled("<hp:p><hp:run><hp:t>계약명: {{계약명}}</hp:t></hp:run></hp:p>", {"계약명": "정보시스템 구축"})
    opened = ctrl.dispatch("new", {"media": "hwpx", "content": base64.b64encode(pkg.to_bytes()).decode("ascii")})
    sid = opened["session_id"]
    ctrl.sessions[sid].rhwp_editable = True

    def tab() -> dict:
        return next(item for item in ctrl.snapshot()["tabs"] if item["id"] == sid)

    assert tab()["document_commands"] == [{"type": semantics.REVERT_TEMPLATE, "enabled": True,
                                           "reason": None, "alternative": None}]
    plan = ctrl.dispatch("preview", {"session_id": sid, "revision": 0, "command": REVERT})
    assert plan["confirm"] == semantics.CONFIRM_BUTTON
    assert plan["message"] == "사라지는 것: 필드 값 1개"
    assert plan["body_changed"] is True
    assert plan["field_delta"] == {"added_fields": [], "removed_fields": []}
    assert plan["created"] is None and plan["renamed"] is None
    # 미리보기는 세션을 바꾸지 않는다 — 적용은 편집기가 되돌려 준 내용의 update 다(실행 취소 가능한 한 편집).
    assert tab()["revision"] == 0 and tab()["document_commands"][0]["enabled"] is True
    ctrl.dispatch("update", {"session_id": sid, "revision": 0, "content": plan["content"]})
    assert tab()["revision"] == 1
    assert tab()["document_commands"][0] == {"type": semantics.REVERT_TEMPLATE, "enabled": False,
                                             "reason": semantics.REASON_NO_FILLED_VALUE, "alternative": None}
    reverted = HwpxPackage.from_bytes(base64.b64decode(plan["content"]))
    assert _values(reverted) == [("계약명", "{{계약명}}")]

    txt = ctrl.dispatch("new", {"media": "txt", "content": "{{이름}}\n"})
    txt_tab = next(item for item in ctrl.snapshot()["tabs"] if item["id"] == txt["session_id"])
    assert txt_tab["document_commands"][0]["enabled"] is False
    with pytest.raises(ValueError, match=semantics.REASON_NO_FILLED_VALUE):
        ctrl.dispatch("preview", {"session_id": txt["session_id"], "revision": 0, "command": REVERT})


# ------------------------------------------------------------------ L-5 kind 어휘
def test_wire_and_authoring_kind_vocabularies_map_one_to_one() -> None:
    assert PRODUCT_KINDS == {PRODUCT_KIND_SLOT, PRODUCT_KIND_OPTION}
    assert set(AUTHORING_KIND_BY_PRODUCT_KIND) == PRODUCT_KINDS
    assert sorted(AUTHORING_KIND_BY_PRODUCT_KIND.values()) == sorted({PLACEMENT_SLOT, PLACEMENT_OPTION})

    pkg = _pkg("".join(f"<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>" for text in ("머리", "갑", "을", "끝")))
    pkg, _ = apply_hwpx(pkg, {"type": "create_slot", "entry": SECTION, "start_paragraph": 1,
                              "end_paragraph": 2, "id": "계약방식"})
    pkg, _ = apply_hwpx(pkg, {"type": "create_option", "entry": SECTION, "start_paragraph": 1,
                              "end_paragraph": 1, "id": "일반", "slot_id": "계약방식"})
    analysis = analyze_hwpx(pkg)
    authored = {slot["id"]: slot["kind"] for slot in analysis["slots"]}
    authored |= {option["id"]: option["kind"] for slot in analysis["slots"] for option in slot["options"]}
    assert authored == {"계약방식": PLACEMENT_SLOT, "일반": PLACEMENT_OPTION}
    wired = {item.product_id: item.kind for item in inspect_product_bookmarks(scan_structural_boundaries(pkg)).observations
             if item.classification is ProductClassification.KNOWN_PRODUCT}
    assert wired == {"계약방식": PRODUCT_KIND_SLOT, "일반": PRODUCT_KIND_OPTION}
    assert {product_id: AUTHORING_KIND_BY_PRODUCT_KIND[kind] for product_id, kind in wired.items()} == authored


def test_region_commands_default_to_the_slot_kind() -> None:
    """``kind`` 없는 영역 명령은 항목을 가리킨다 — 기본값은 한 곳(``_region_kind``)이다."""
    assert hwpx_authoring._region_kind({}) == PLACEMENT_SLOT
    assert hwpx_authoring._region_kind({"kind": PLACEMENT_OPTION}) == PLACEMENT_OPTION
