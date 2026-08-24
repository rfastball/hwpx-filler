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


def _begin(begin_id: str, name: str, value: str) -> str:
    """여러 문단에 걸치는 기존 책갈피의 **여는** 문단(짝은 :func:`_end`)."""
    return _p(
        f'<hp:ctrl><hp:fieldBegin id="{begin_id}" type="BOOKMARK" name="{name}"/>'
        f"</hp:ctrl><hp:t>{value}</hp:t>"
    )


def _end(begin_id: str, value: str) -> str:
    return _p(f'<hp:t>{value}</hp:t><hp:ctrl><hp:fieldEnd beginIDRef="{begin_id}"/></hp:ctrl>')


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


def test_valid_existing_product_slot_coexists_with_a_new_declaration() -> None:
    """S8-03 완화: **유효한** 기존 Slot 은 거절 사유가 아니다(왕복의 전제 · D6).

    사후조건 ⓐ 는 「기존 ∪ 선언」으로 일반화됐고 기대치는 **문서 위치 순**이다 —
    여기서는 기존 region 이 앞(문단 0)이고 선언 범위가 뒤(문단 2)다.
    """
    pkg = _pkg(
        _bookmark("5", "기존", "A", serialize_slot_metatag(Slot("기존", ()))),
        _text("{{#항목 특약}}"),
        _text("본문"),
        _text("{{/항목}}"),
    )
    report = compile_structure(pkg)

    assert (report.modified, report.refusal) == (True, None)
    assert report.slots == (Slot("특약", ()),)  # 리포트는 **이번에** 만든 것만 말한다
    assert inspect_slots(pkg) == ((Slot("기존", ()), Slot("특약", ())), ())


def test_declaration_before_an_existing_slot_keeps_document_order() -> None:
    """기대치 병합이 이름순·선언순이 아니라 **위치순**임을 반대 배치로 못박는다."""
    pkg = _pkg(
        _text("{{#항목 특약}}"),
        _text("본문"),
        _text("{{/항목}}"),
        _bookmark("5", "기존", "A", serialize_slot_metatag(Slot("기존", ()))),
    )
    report = compile_structure(pkg)

    assert (report.modified, report.refusal) == (True, None)
    assert inspect_slots(pkg) == ((Slot("특약", ()), Slot("기존", ())), ())


def test_preflight_refuses_a_duplicate_slot_id() -> None:
    """선언 id 가 기존 Slot id 와 겹치면 사후조건이 성립할 수 없다 — 전용 code 로 거절."""
    pkg = _pkg(
        _bookmark("5", "다른이름", "A", serialize_slot_metatag(Slot("특약", ()))),
        _text("{{#항목 특약}}"),
        _text("본문"),
        _text("{{/항목}}"),
    )
    before = dict(pkg.entries)
    report = compile_structure(pkg)

    assert report.refusal is not None
    assert [(item.kind, item.code) for item in report.refusal] == [
        (Refusal.EXISTING_PRODUCT, "duplicate-slot-id")
    ]
    assert "'특약'" in report.refusal[0].message
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
    """기존 region 을 새로 감싸는 것은 거절된다 — 조용히 계층을 바꾸지 않는다.

    S8-F2(#853) 전에는 이 자리를 커널 영문 ValueError 가 닫았고 그 문자열이 그대로
    사용자에게 나갔다. 지금은 preflight 가 먼저 서서 구조화 거절로 낸다.
    """
    pkg = _pkg(
        _text("{{#항목 특약}}"),
        _bookmark("5", "기존", "본문", _OPAQUE_METATAG),
        _text("{{/항목}}"),
    )
    before = dict(pkg.entries)

    report = compile_structure(pkg)

    assert report.refusal is not None
    assert [(item.kind, item.code) for item in report.refusal] == [
        (Refusal.EXISTING_REGION_OVERLAP, "기존")
    ]
    assert pkg.entries == before


# --------------------------------- 5b. 기존 책갈피 겹침 → 구조화 거절(S8-F2 · #853)
@pytest.mark.parametrize(
    ("label", "paragraphs"),
    [
        # 감사 재현: 5문단 문서, p2 를 감싸는 기존 책갈피, p1..p3 을 감싸는 선언.
        (
            "contained",
            (
                _text("머리"),
                _text("{{#항목 특약}}"),
                _bookmark("5", "기존", "본문", _OPAQUE_METATAG),
                _text("{{/항목}}"),
                _text("꼬리"),
            ),
        ),
        # 기존 책갈피가 선언을 감싼다 — 컴파일은 항목 region 을 parent=None 으로 만든다.
        (
            "enclosing",
            (
                _begin("5", "기존", "머리"),
                _text("{{#항목 특약}}"),
                _text("본문"),
                _text("{{/항목}}"),
                _end("5", "꼬리"),
            ),
        ),
        # 부분 교차 — 커널은 crossing region 을 아예 지원하지 않는다.
        (
            "crossing",
            (
                _begin("5", "기존", "머리"),
                _text("{{#항목 특약}}"),
                _end("5", "본문1"),
                _text("본문2"),
                _text("{{/항목}}"),
            ),
        ),
    ],
)
def test_existing_bookmark_overlap_is_a_structured_refusal(
    label: str, paragraphs: "tuple[str, ...]"
) -> None:
    """겹침 세 위상 전부 한국어 구조화 거절 + 무변형 — 커널 영문 문자열은 새지 않는다."""
    pkg = _pkg(*paragraphs)
    before = dict(pkg.entries)

    report = compile_structure(pkg)

    assert report.modified is False, label
    assert report.refusal is not None
    kinds = {item.kind for item in report.refusal}
    assert kinds == {Refusal.EXISTING_REGION_OVERLAP}, label
    message = report.refusal[0].message
    assert "'특약' 범위가 기존 '기존' 책갈피와 겹칩니다" in message
    assert "옮기거나 지운 뒤 다시 변환하세요" in message
    # 커널 문자열 미노출 + 문안 규율(COPY_STYLE_GUIDE §3: em dash·낫표 금지).
    for banned in ("BOOKMARK", "topology", "crossing", "—", "「", "」"):
        assert banned not in message, (label, banned)
    assert pkg.entries == before


def test_kernel_still_refuses_an_enclosing_creation_as_depth_defense() -> None:
    """preflight 가 앞섰다고 커널 방어가 걷히지는 않는다 — 직접 부르면 그대로 거절한다."""
    pkg = _pkg(_text("머리"), _bookmark("5", "기존", "본문", _OPAQUE_METATAG), _text("꼬리"))
    with pytest.raises(ValueError, match="changed existing native topology"):
        create_bookmark_region(pkg, SECTION, 0, 2, name="특약", parent=None)


def test_disjoint_existing_bookmark_still_compiles() -> None:
    """겹치지 않는 기존 책갈피는 종전대로 통과한다(양성 대조 — 과잉 거절 금지)."""
    pkg = _pkg(
        _bookmark("5", "기존", "남의 구간", _OPAQUE_METATAG),
        _text("{{#항목 특약}}"),
        _text("본문"),
        _text("{{/항목}}"),
    )
    report = compile_structure(pkg)

    assert (report.modified, report.refusal) == (True, None)
    assert [name for name, *_rest in _topology(pkg)] == ["기존", "특약"]


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


# ------------------------------------------- 9. 컴파일 뒤 상태(S8-04 #835 양성 대조)
def test_compiled_structure_clears_the_status_notation_channel() -> None:
    """S8-02 산출(마커 0)은 상태 축에서도 잔존 0 이고 상태가 COMPILED 로 선다.

    S8-04 가 세운 「구간 표기 잔존」 채널의 **양성 대조**다. 음성(마커 잔존 → PARTIAL·
    생성 차단)만 세우면 게이트가 늘 빨강이어도 초록으로 보이므로 둘을 함께 못박는다.
    """
    from hwpxfiller.domain.authoring import compile_document
    from hwpxfiller.domain.template_status import CompileState, compile_status

    pkg = _pkg(*(_text(line) for line in (
        "계약 일반사항",
        "{{#항목 특약 특약 사항}}",
        "특약 본문",
        "{{/항목}}",
        "발주자: {{수요기관}}",
    )))
    assert compile_status(pkg).structure_marker_n == 2

    assert compile_structure(pkg).modified is True   # 표기 → native Slot
    pkg, _report = compile_document(pkg)             # 필드 토큰 → 누름틀

    after = compile_status(pkg)
    assert after.structure_marker_n == 0
    assert after.state == CompileState.COMPILED
    assert inspect_slots(pkg)[0] == (Slot("특약", (), "특약 사항"),)
