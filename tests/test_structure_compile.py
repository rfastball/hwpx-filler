"""구간 표기 → native Slot 컴파일과 그 사후조건(S8-02 #833).

증명하는 것은 넷이다:

1. **왕복** — 표기만 쓴 문서를 컴파일하면 선언이 native Slot 구조로 복원되고 표기는
   한 톨도 남지 않는다.
2. **동일성** — 컴파일 산출은 같은 선언을 커널 프리미티브로 손수 지은 패키지와
   의미가 같다(제품 판독 tuple·BOOKMARK 이름·계층·MetaTag payload).
3. **거절** — 표기 진단·기존 native blocker·기존 제품 구조·이름 충돌은 전부 **변이
   0건**으로 거절되고 사유가 구조화돼 남는다(커널 예외 문자열 파싱 없음).
4. **사후조건** — ⓐ 선언 복원 · ⓑ 표기 잔존 0 · ⓒ 기존 region 보존 중 하나라도
   깨지면 패키지는 원본으로 돌아가고 어느 사후조건이 왜 깨졌는지 남는다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from lxml import etree

from hwpxcore.bookmark_region import (
    append_bookmark_metatag,
    create_bookmark_region,
    resolve_bookmark_topology,
)
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
import hwpxfiller.external.template_inspection as template_inspection
from hwpxfiller.domain.authoring import scan_structure
from hwpxfiller.domain.slot import Slot, SlotOption
from hwpxfiller.external.template_inspection import (
    StructureCompileRefusalKind as Refusal,
)
from hwpxfiller.external.template_inspection import (
    compile_structure,
    compile_structure_file,
    inspect_slots,
    serialize_slot_metatag,
    serialize_slot_option_metatag,
    structure_region_name,
)

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"
SECTION = "Contents/section0.xml"
HEADER = "Contents/header0.xml"


# ------------------------------------------------------------------ fixtures
def _p(content: str) -> str:
    return f'<hp:p><hp:run charPrIDRef="0">{content}</hp:run></hp:p>'


def _text(value: str) -> str:
    return _p(f"<hp:t>{value}</hp:t>")


def _bookmark(begin_id: str, name: str, value: str, meta: str = "") -> str:
    payload = f"<hp:metaTag>{meta}</hp:metaTag>" if meta else ""
    return _p(
        f'<hp:ctrl><hp:fieldBegin id="{begin_id}" type="BOOKMARK" name="{name}">'
        f"{payload}</hp:fieldBegin></hp:ctrl>"
        f"<hp:t>{value}</hp:t>"
        f'<hp:ctrl><hp:fieldEnd beginIDRef="{begin_id}"/></hp:ctrl>'
    )


#: 제품 소유가 아닌(``hwpxFiller`` 도 canonical name 도 없는) 남의 MetaTag payload.
_OPAQUE_METATAG = '{"name":"#other"}'


def _entry(inner: str) -> bytes:
    return f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{inner}</hs:sec>'.encode()


def _pkg(*paragraphs: str, header: "tuple[str, ...] | None" = None) -> HwpxPackage:
    entries = {MIMETYPE_NAME: MIMETYPE_VALUE, SECTION: _entry("".join(paragraphs))}
    if header is not None:
        entries[HEADER] = _entry("".join(header))
    return HwpxPackage(entries=entries, stored={MIMETYPE_NAME})


#: 항목 1 · 선택 2 · 본문 · 필드 토큰이 섞인 표준 표기 문서.
NOTATION = (
    "계약 일반사항",
    "{{#항목 특약 특약 사항}}",
    "{{#선택 지체상금 지체상금 조항}}",
    "지체상금은 {{지체상금률}} 로 한다.",
    "{{/선택}}",
    "{{#선택 하자보수 하자보수 조항}}",
    "하자보수 기간은 {{하자기간}} 이다.",
    "{{/선택}}",
    "{{/항목}}",
    "발주자: {{수요기관}}",
)
CONTENT = (
    "계약 일반사항",
    "지체상금은 {{지체상금률}} 로 한다.",
    "하자보수 기간은 {{하자기간}} 이다.",
    "발주자: {{수요기관}}",
)
DECLARED = (
    Slot(
        "특약",
        (
            SlotOption("지체상금", 0, "지체상금 조항"),
            SlotOption("하자보수", 1, "하자보수 조항"),
        ),
        "특약 사항",
    ),
)


def _notation_package() -> HwpxPackage:
    return _pkg(*(_text(line) for line in NOTATION))


def _texts(pkg: HwpxPackage, entry: str = SECTION) -> "list[str]":
    root = etree.fromstring(pkg.entries[entry])
    return [
        "".join(node.itertext())
        for paragraph in root
        for node in paragraph.iter(f"{{{HP}}}t")
    ]


def _topology(pkg: HwpxPackage) -> "list[tuple]":
    return [
        (
            region.name,
            None if region.parent is None else region.parent.name,
            region.start_paragraph,
            region.end_paragraph,
            region.meta_tags,
        )
        for region in resolve_bookmark_topology(pkg)
    ]


# ---------------------------------------------------------------- 1. 왕복 양성
def test_compile_restores_declaration_and_leaves_no_notation() -> None:
    """표기 → native Slot. 선언 전건 복원 · 마커 0 · 본문 텍스트 보존."""
    pkg = _notation_package()
    report = compile_structure(pkg)

    assert report.to_dict() == {
        "modified": True,
        "slots": [
            {
                "id": "특약",
                "label": "특약 사항",
                "options": [
                    {"id": "지체상금", "label": "지체상금 조항"},
                    {"id": "하자보수", "label": "하자보수 조항"},
                ],
            }
        ],
        "options": 2,
        "refusal": None,
    }
    assert inspect_slots(pkg) == (DECLARED, ())

    residue = scan_structure(pkg)
    assert (residue.slots, residue.diagnostics, residue.placements) == ((), (), ())
    assert _texts(pkg) == list(CONTENT)  # 마커 문단만 사라지고 본문은 그대로
    assert json.dumps(report.to_dict(), ensure_ascii=False)  # 상위 링 직렬화 가능


def test_compiled_region_names_and_payloads_follow_the_canonical_shape() -> None:
    """BOOKMARK name 은 선언 id, 제품 의미는 S1 canonical MetaTag payload 하나뿐."""
    pkg = _notation_package()
    compile_structure(pkg)

    assert _topology(pkg) == [
        (
            "특약",
            None,
            1,
            2,
            (serialize_slot_metatag(DECLARED[0]),),
        ),
        (
            "특약/지체상금",
            "특약",
            1,
            1,
            (serialize_slot_option_metatag(DECLARED[0].options[0]),),
        ),
        (
            "특약/하자보수",
            "특약",
            2,
            2,
            (serialize_slot_option_metatag(DECLARED[0].options[1]),),
        ),
    ]
    assert structure_region_name("특약") == "특약"
    assert structure_region_name("특약", "지체상금") == "특약/지체상금"


# -------------------------------------------------- 2. 커널 수동 구성과 의미 동등
def test_compiled_package_matches_manual_kernel_construction() -> None:
    """같은 선언을 커널 프리미티브로 손수 지은 것과 판독 결과가 같다."""
    compiled = _notation_package()
    compile_structure(compiled)

    manual = _pkg(*(_text(line) for line in CONTENT))
    slot = create_bookmark_region(manual, SECTION, 1, 2, name="특약")
    for order, option in enumerate(DECLARED[0].options):
        create_bookmark_region(
            manual,
            SECTION,
            1 + order,
            1 + order,
            name=f"특약/{option.id}",
            parent=next(
                region
                for region in resolve_bookmark_topology(manual)
                if region.name == "특약"
            ),
        )
    del slot  # 핸들은 첫 변이에서 낡는다 — 이름으로 다시 집는 것이 계약이다
    for name, payload in (
        ("특약", serialize_slot_metatag(DECLARED[0])),
        ("특약/지체상금", serialize_slot_option_metatag(DECLARED[0].options[0])),
        ("특약/하자보수", serialize_slot_option_metatag(DECLARED[0].options[1])),
    ):
        append_bookmark_metatag(
            manual,
            next(
                region
                for region in resolve_bookmark_topology(manual)
                if region.name == name
            ),
            payload,
        )

    assert inspect_slots(compiled) == inspect_slots(manual)
    assert _topology(compiled) == _topology(manual)


# ------------------------------------------------------------- 3. 진단 → 변이 0
def test_notation_diagnostic_refuses_with_zero_mutation() -> None:
    """S8-01 진단이 1건이라도 있으면 변환 불가 — 사유를 전량 재진술한다."""
    pkg = _pkg(_text("{{#항목 특약}}"), _text("본문"))
    before = dict(pkg.entries)
    report = compile_structure(pkg)

    assert (report.modified, report.slots, report.options) == (False, (), 0)
    assert report.refusal is not None
    assert [item.kind for item in report.refusal] == [Refusal.NOTATION_DIAGNOSTIC]
    assert report.refusal[0].code == "unbalanced_marker"
    assert "닫는 마커가 없습니다" in report.refusal[0].message
    assert report.to_dict()["refusal"] == [
        {
            "kind": "notation-diagnostic",
            "code": "unbalanced_marker",
            "message": report.refusal[0].message,
        }
    ]
    assert pkg.entries == before


# ------------------------------------------------- 4. preflight blocker → 변이 0
def test_preflight_refuses_unusable_field_pairing() -> None:
    """짝 없는 fieldEnd 하나로 entry 급 신뢰가 무너지면 컴파일하지 않는다."""
    pkg = _pkg(
        _text("{{#항목 특약}}"),
        _text("본문"),
        _text("{{/항목}}"),
        _p('<hp:ctrl><hp:fieldEnd beginIDRef="99"/></hp:ctrl><hp:t>x</hp:t>'),
    )
    before = dict(pkg.entries)
    report = compile_structure(pkg)

    assert report.modified is False
    assert report.refusal is not None
    assert {item.code for item in report.refusal} == {
        "field-pairing-unusable",
        "bookmark-topology-unusable",
    }
    assert all(item.kind is Refusal.NATIVE_BLOCKER for item in report.refusal)
    assert pkg.entries == before


def test_preflight_refuses_unusable_bookmark_metadata() -> None:
    """구조화 blocker kind 를 그대로 받는다 — 커널 예외 문자열을 뜯지 않는다."""
    pkg = _pkg(
        _p(
            '<hp:ctrl><hp:fieldBegin id="5" type="BOOKMARK" name="OLD">'
            "<hp:metaTag><hp:t>nested</hp:t></hp:metaTag>"
            '</hp:fieldBegin></hp:ctrl><hp:t>A</hp:t>'
            '<hp:ctrl><hp:fieldEnd beginIDRef="5"/></hp:ctrl>'
        ),
        _text("{{#항목 특약}}"),
        _text("본문"),
        _text("{{/항목}}"),
    )
    before = dict(pkg.entries)
    report = compile_structure(pkg)

    assert report.refusal is not None
    assert [(item.kind, item.code) for item in report.refusal] == [
        (Refusal.NATIVE_BLOCKER, "bookmark-metadata-unusable")
    ]
    assert pkg.entries == before


def test_preflight_ignores_removal_only_geometry_blockers() -> None:
    """기존 region **삭제** 기하 문제는 새 region **생성**을 막지 않는다(음성 대조)."""
    pkg = _pkg(
        _p(
            "<hp:t>앞</hp:t>"
            '<hp:ctrl><hp:fieldBegin id="5" type="BOOKMARK" name="기존"/></hp:ctrl>'
            "<hp:t>A</hp:t>"
            '<hp:ctrl><hp:fieldEnd beginIDRef="5"/></hp:ctrl>'
        ),
        _text("{{#항목 특약}}"),
        _text("본문"),
        _text("{{/항목}}"),
    )
    report = compile_structure(pkg)

    assert (report.modified, report.refusal) == (True, None)
    assert inspect_slots(pkg) == ((Slot("특약", ()),), ())


def test_preflight_refuses_declaration_outside_a_body_section() -> None:
    """구간은 본문 섹션에서만 만들 수 있다 — 머리말 선언은 조용히 버리지 않는다."""
    pkg = _pkg(
        _text("본문"),
        header=(_text("{{#항목 특약}}"), _text("머리말"), _text("{{/항목}}")),
    )
    before = dict(pkg.entries)
    report = compile_structure(pkg)

    assert report.refusal is not None
    assert [(item.kind, item.code) for item in report.refusal] == [
        (Refusal.UNSUPPORTED_ENTRY, HEADER)
    ]
    assert pkg.entries == before


def test_preflight_refuses_when_product_structure_already_exists() -> None:
    """사후조건 ⓐ 가 성립할 수 없는 문서는 raise 로 흘리지 않고 먼저 거절한다."""
    pkg = _pkg(
        _bookmark("5", "기존", "A", serialize_slot_metatag(Slot("기존", ()))),
        _text("{{#항목 특약}}"),
        _text("본문"),
        _text("{{/항목}}"),
    )
    before = dict(pkg.entries)
    report = compile_structure(pkg)

    assert report.refusal is not None
    assert [(item.kind, item.code) for item in report.refusal] == [
        (Refusal.EXISTING_PRODUCT, "product-slot-present")
    ]
    assert "「기존」" in report.refusal[0].message
    assert pkg.entries == before


def test_preflight_refuses_existing_product_diagnostics() -> None:
    """기존 제품 MetaTag 가 깨져 있으면 그 진단을 그대로 얹어 거절한다."""
    pkg = _pkg(
        _bookmark("5", "기존", "A", "not json"),
        _text("{{#항목 특약}}"),
        _text("본문"),
        _text("{{/항목}}"),
    )
    before = dict(pkg.entries)
    report = compile_structure(pkg)

    assert report.refusal is not None
    assert [(item.kind, item.code) for item in report.refusal] == [
        (Refusal.EXISTING_PRODUCT, "malformed-json")
    ]
    assert pkg.entries == before


def test_preflight_refuses_a_bookmark_name_collision() -> None:
    """같은 이름의 기존 책갈피가 있으면 「신설분 제외」 대조가 갈리므로 먼저 거절한다."""
    pkg = _pkg(
        _bookmark("5", "특약", "A"),
        _text("{{#항목 특약}}"),
        _text("본문"),
        _text("{{/항목}}"),
    )
    before = dict(pkg.entries)
    report = compile_structure(pkg)

    assert report.refusal is not None
    assert [(item.kind, item.code) for item in report.refusal] == [
        (Refusal.NAME_COLLISION, "특약")
    ]
    assert pkg.entries == before


# ------------------------------------------------------- 5. 사후조건 실패 → 롤백
def _twisted_metatag(_slot: Slot) -> str:
    return serialize_slot_metatag(Slot("다른 항목", ()))


def test_postcondition_a_failure_rolls_back_without_deformation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ⓐ 선언 복원이 깨지면 entries 는 원본으로 돌아가고 사유가 구분된다."""
    pkg = _notation_package()
    before = dict(pkg.entries)
    monkeypatch.setattr(
        template_inspection, "serialize_slot_metatag", _twisted_metatag
    )
    with pytest.raises(ValueError, match="postcondition A"):
        compile_structure(pkg)
    assert pkg.entries == before


def test_postcondition_b_failure_rolls_back_without_deformation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ⓑ 표기가 남으면 — 마커 문단 삭제를 없애 재현 — 롤백한다."""
    pkg = _notation_package()
    before = dict(pkg.entries)
    monkeypatch.setattr(
        template_inspection,
        "remove_top_level_paragraph",
        lambda *_args, **_kwargs: None,
    )
    with pytest.raises(ValueError, match="postcondition B"):
        compile_structure(pkg)
    assert pkg.entries == before


def test_postcondition_c_failure_rolls_back_without_deformation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ⓒ 기존 region 대조가 어긋나면 롤백한다(판정 자체를 비틀어 재현)."""
    pkg = _notation_package()
    before = dict(pkg.entries)
    original = template_inspection._non_product_region_shape
    calls: "list[int]" = []

    def drifting(regions, created):
        calls.append(1)
        shape = original(regions, created)
        if len(calls) > 1:
            shape["drift"] = 1
        return shape

    monkeypatch.setattr(
        template_inspection, "_non_product_region_shape", drifting
    )
    with pytest.raises(ValueError, match="postcondition C"):
        compile_structure(pkg)
    assert pkg.entries == before


def test_ambiguous_created_region_name_stops_before_committing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """신설 region 이 이름·좌표로 유일하지 않으면 엉뚱한 region 에 태그하지 않는다."""
    pkg = _pkg(
        _text("{{#항목 특약}}"),
        _text("{{#선택 가 가안}}"),
        _text("본문"),
        _text("{{/선택}}"),
        _text("{{/항목}}"),
    )
    before = dict(pkg.entries)
    monkeypatch.setattr(
        template_inspection, "structure_region_name", lambda *_args: "SAME"
    )
    with pytest.raises(ValueError, match="not uniquely resolvable"):
        compile_structure(pkg)
    assert pkg.entries == before


def test_pre_existing_region_outside_the_range_survives_compilation() -> None:
    """범위 밖 비제품 region 은 이름·MetaTag·계층 그대로 살고 위치만 당겨진다."""
    pkg = _pkg(
        _text("머리"),
        _bookmark("5", "기존", "남의 구간", _OPAQUE_METATAG),
        _text("{{#항목 특약}}"),
        _text("본문"),
        _text("{{/항목}}"),
    )
    report = compile_structure(pkg)

    assert report.modified is True
    assert _topology(pkg) == [
        ("기존", None, 1, 1, (_OPAQUE_METATAG,)),
        ("특약", None, 2, 2, (serialize_slot_metatag(Slot("특약", ())),)),
    ]


def test_pre_existing_region_inside_the_range_is_refused_loudly() -> None:
    """기존 region 을 새로 감싸는 것은 커널이 거절한다 — 조용히 계층을 바꾸지 않는다."""
    pkg = _pkg(
        _text("{{#항목 특약}}"),
        _bookmark("5", "기존", "본문", _OPAQUE_METATAG),
        _text("{{/항목}}"),
    )
    before = dict(pkg.entries)

    with pytest.raises(ValueError, match="changed existing native topology"):
        compile_structure(pkg)
    assert pkg.entries == before


# ------------------------------------------------------------------- 6. no-op
def test_document_without_markers_is_a_no_op() -> None:
    """바꿀 마커가 없으면 modified=False 이고 entries 는 한 바이트도 안 바뀐다."""
    pkg = _pkg(_text("계약명: {{계약명}}"), _text("본문"))
    before = dict(pkg.entries)
    report = compile_structure(pkg)

    assert (report.modified, report.slots, report.options, report.refusal) == (
        False,
        (),
        0,
        None,
    )
    assert pkg.entries == before


# --------------------------------------------------------------- 8. 파일 verb
def test_compile_structure_file_saves_only_on_mutation(tmp_path: Path) -> None:
    """성공하면 제자리 저장, 거절·no-op 이면 파일 바이트 무변형."""
    target = tmp_path / "template.hwpx"
    target.write_bytes(_notation_package().to_bytes())
    report = compile_structure_file(str(target))

    assert report.modified is True
    saved = HwpxPackage.from_bytes(target.read_bytes())
    assert inspect_slots(saved) == (DECLARED, ())

    # 이미 컴파일된 파일을 다시 부르면 표기가 없으므로 no-op — 저장하지 않는다.
    unchanged = target.read_bytes()
    again = compile_structure_file(str(target))
    assert (again.modified, again.refusal) == (False, None)
    assert target.read_bytes() == unchanged


def test_compile_structure_file_leaves_bytes_untouched_on_refusal(
    tmp_path: Path,
) -> None:
    """거절은 파일을 열어만 보고 닫는다."""
    target = tmp_path / "broken.hwpx"
    target.write_bytes(_pkg(_text("{{#항목 특약}}"), _text("본문")).to_bytes())
    before = target.read_bytes()

    report = compile_structure_file(str(target))

    assert report.modified is False
    assert report.refusal is not None
    assert target.read_bytes() == before
