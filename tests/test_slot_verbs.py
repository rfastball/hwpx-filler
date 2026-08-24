"""컴파일된 Slot 의 개명·표기로 풀기·삭제(S8-03 #834).

증명하는 것은 넷이다:

1. **개명** — label 만 바뀌고 구조·본문은 한 톨도 안 바뀐다. 빈 값은 label 을 뗀다.
2. **풀기** — 컴파일의 역함수다: 구조가 걷히고 그 자리에 **도로 읽히는** 표기가 선다.
   다른 슬롯이 컴파일된 채 남아 있어도 성립한다(D6 — 경계 이동의 유일한 길).
3. **왕복** — compile → decompile → compile 이 제품 판독·topology 를 원본과 같게 만든다.
4. **롤백** — 사후조건이 깨지면 패키지는 원본으로 돌아가고 파일은 한 바이트도 안 바뀐다.

fixture 는 S8-02(:mod:`tests.test_structure_compile`) 의 헬퍼를 그대로 쓴다 — 같은 문서
형상 위에서 두 방향(컴파일·되돌리기)을 재야 왕복이 같은 대상을 말한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hwpxcore.package import HwpxPackage
import hwpxfiller.external.template_inspection as template_inspection
from hwpxfiller.domain.authoring import (
    PLACEMENT_OPTION,
    PLACEMENT_SLOT,
    begin_marker_text,
    end_marker_text,
    scan_structure,
)
from hwpxfiller.domain.slot import Slot, SlotOption
from hwpxfiller.external.template_inspection import (
    compile_structure,
    decompile_slot,
    decompile_slot_file,
    inspect_slots,
    remove_slot_file,
    rename_slot_label,
    rename_slot_label_file,
    serialize_slot_metatag,
)

from test_structure_compile import (  # noqa: E402 — tests 는 rootdir 경로 임포트다
    CONTENT,
    DECLARED,
    NOTATION,
    SECTION,
    _bookmark,
    _notation_package,
    _pkg,
    _text,
    _texts,
    _topology,
)


def _slot_ids(pkg: HwpxPackage) -> "list[str]":
    slots, diagnostics = inspect_slots(pkg)
    assert diagnostics == ()
    return [slot.id for slot in slots]


#: 항목 2개 + 각자 선택을 가진 표기 문서 — 「다른 슬롯이 남은 채로」 를 재는 대상.
TWO_SLOT_NOTATION = (
    "머리",
    "{{#항목 특약 특약 사항}}",
    "{{#선택 지체상금 지체상금 조항}}",
    "지체상금은 {{지체상금률}} 로 한다.",
    "{{/선택}}",
    "{{/항목}}",
    "{{#항목 부기 부기 사항}}",
    "부기: {{부기문}}",
    "{{/항목}}",
    "꼬리",
)


def _two_slot_package() -> HwpxPackage:
    pkg = _pkg(*(_text(line) for line in TWO_SLOT_NOTATION))
    report = compile_structure(pkg)
    assert (report.modified, report.refusal) == (True, None)
    return pkg


# ------------------------------------------------------------------- 1. 개명
def test_rename_changes_only_the_label() -> None:
    """label 만 바뀐다 — option·본문·문단 수 불변."""
    pkg = _notation_package()
    compile_structure(pkg)
    before_text = _texts(pkg)

    rename_slot_label(pkg, "특약", "계약 특약")

    slots, diagnostics = inspect_slots(pkg)
    assert diagnostics == ()
    assert slots == (Slot("특약", DECLARED[0].options, "계약 특약"),)
    assert _texts(pkg) == before_text


def test_rename_with_an_empty_label_drops_it() -> None:
    """빈 값·공백은 label 을 **뗀다**(payload 에서 키 탈락)."""
    pkg = _notation_package()
    compile_structure(pkg)

    rename_slot_label(pkg, "특약", "   ")

    slots, _ = inspect_slots(pkg)
    assert slots[0].label is None
    assert slots[0].options == DECLARED[0].options
    payload = _topology(pkg)[0][4]
    assert payload == (serialize_slot_metatag(Slot("특약", (), None)),)


def test_rename_collapses_whitespace_so_the_label_can_be_written_back() -> None:
    """되쓰기 불가능한 값을 만들지 않는다 — 접힌 공백만 저장된다."""
    pkg = _notation_package()
    compile_structure(pkg)

    rename_slot_label(pkg, "특약", "  계약   특약  ")

    slots, _ = inspect_slots(pkg)
    assert slots[0].label == "계약 특약"


def test_rename_of_an_absent_slot_is_loud_and_changes_nothing() -> None:
    pkg = _notation_package()
    compile_structure(pkg)
    before = dict(pkg.entries)

    with pytest.raises(ValueError, match="없음|not found"):
        rename_slot_label(pkg, "없음", "새 이름")
    assert pkg.entries == before


def test_rename_is_blocked_by_existing_diagnostics() -> None:
    """fail-closed — 제품 판독이 깨진 문서에서는 변이를 시작하지 않는다."""
    pkg = _pkg(_bookmark("5", "기존", "A", "not json"), _text("본문"))
    before = dict(pkg.entries)

    with pytest.raises(ValueError, match="blocked by diagnostics"):
        rename_slot_label(pkg, "기존", "새 이름")
    assert pkg.entries == before


# --------------------------------------------------------------- 2. 표기로 풀기
def test_decompile_restores_readable_notation() -> None:
    """구조가 걷히고 그 자리에 **스캐너가 도로 읽는** 표기가 선다."""
    pkg = _notation_package()
    compile_structure(pkg)

    decompile_slot(pkg, "특약")

    assert inspect_slots(pkg) == ((), ())
    residue = scan_structure(pkg)
    assert residue.diagnostics == ()
    assert residue.slots == DECLARED
    assert _texts(pkg) == list(NOTATION)  # 마커 문단이 원래 자리로 돌아왔다


def test_decompile_leaves_other_compiled_slots_alone() -> None:
    """다른 슬롯이 컴파일된 채 남는다 — 왕복이 성립하는 유일한 형상(D6)."""
    pkg = _two_slot_package()
    assert _slot_ids(pkg) == ["특약", "부기"]

    decompile_slot(pkg, "특약")

    assert _slot_ids(pkg) == ["부기"]
    residue = scan_structure(pkg)
    assert residue.diagnostics == ()
    assert [slot.id for slot in residue.slots] == ["특약"]


def test_decompile_of_an_absent_slot_is_loud_and_changes_nothing() -> None:
    pkg = _two_slot_package()
    before = dict(pkg.entries)

    with pytest.raises(ValueError, match="없음|not found"):
        decompile_slot(pkg, "없음")
    assert pkg.entries == before


def test_decompile_keeps_a_neighbouring_non_product_region() -> None:
    """범위 밖 남의 책갈피는 이름·MetaTag 그대로 살아남는다.

    (범위 **안**의 남의 region 은 애초에 만들어지지 않는다 — 기존 region 을 새로 감싸는
    컴파일을 커널이 거절한다: ``test_structure_compile`` 이 그 계약을 진다.)
    """
    pkg = _pkg(
        _bookmark("5", "남의구간", "머리", '{"name":"#other"}'),
        _text("{{#항목 특약 특약 사항}}"),
        _text("본문"),
        _text("{{/항목}}"),
    )
    compile_structure(pkg)

    decompile_slot(pkg, "특약")

    names = [item[0] for item in _topology(pkg)]
    assert names == ["남의구간"]
    residue = scan_structure(pkg)
    assert (residue.diagnostics, [slot.id for slot in residue.slots]) == ((), ["특약"])


# ------------------------------------------------------------------- 3. 왕복
def test_compile_decompile_compile_is_semantically_identical() -> None:
    """왕복 종료 조건 — 제품 판독과 topology 가 원본과 같다(다중 슬롯 포함)."""
    pkg = _two_slot_package()
    reference_slots = inspect_slots(pkg)
    reference_topology = _topology(pkg)
    reference_text = _texts(pkg)

    decompile_slot(pkg, "특약")
    report = compile_structure(pkg)

    assert (report.modified, report.refusal) == (True, None)
    assert inspect_slots(pkg) == reference_slots
    assert _topology(pkg) == reference_topology
    assert _texts(pkg) == reference_text


def test_round_trip_of_a_single_slot_document_matches_the_original() -> None:
    pkg = _notation_package()
    compile_structure(pkg)
    reference = (inspect_slots(pkg), _topology(pkg), _texts(pkg))

    decompile_slot(pkg, "특약")
    compile_structure(pkg)

    assert (inspect_slots(pkg), _topology(pkg), _texts(pkg)) == reference
    assert _texts(pkg) == list(CONTENT)


# ------------------------------------------------------------ 4. 사후조건·롤백
def test_decompile_rolls_back_when_the_notation_cannot_be_read_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """되쓴 표기가 도로 읽히지 않으면(마커 텍스트를 비틀어 재현) 원본으로 돌아간다."""
    pkg = _notation_package()
    compile_structure(pkg)
    before = dict(pkg.entries)
    monkeypatch.setattr(
        template_inspection,
        "begin_marker_text",
        lambda kind, identifier, label=None: "{{#항목 다른항목}}",
    )

    with pytest.raises(ValueError, match="postcondition \\(notation\\)"):
        decompile_slot(pkg, "특약")
    assert pkg.entries == before


def test_decompile_rolls_back_when_a_region_would_be_lost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """비제품 region 보존 대조가 어긋나면(판정을 비틀어 재현) 원본으로 돌아간다."""
    pkg = _notation_package()
    compile_structure(pkg)
    before = dict(pkg.entries)
    original = template_inspection._region_identity_counter
    calls: "list[int]" = []

    def drifting(regions):
        calls.append(1)
        shape = original(regions)
        if len(calls) > 1:
            shape[("drift",)] = 1
        return shape

    monkeypatch.setattr(template_inspection, "_region_identity_counter", drifting)
    with pytest.raises(ValueError, match="pre-existing regions"):
        decompile_slot(pkg, "특약")
    assert pkg.entries == before


# -------------------------------------------------------------- 5. 마커 성형
def test_marker_text_matches_the_scanner_grammar() -> None:
    """마커 형식의 단일 출처 — 스캐너가 읽는 문법 그대로."""
    assert begin_marker_text(PLACEMENT_SLOT, "특약", "특약 사항") == "{{#항목 특약 특약 사항}}"
    assert begin_marker_text(PLACEMENT_SLOT, "특약", None) == "{{#항목 특약}}"
    assert begin_marker_text(PLACEMENT_OPTION, "지체상금", "") == "{{#선택 지체상금}}"
    assert end_marker_text(PLACEMENT_SLOT) == "{{/항목}}"
    assert end_marker_text(PLACEMENT_OPTION) == "{{/선택}}"


@pytest.mark.parametrize(
    "identifier",
    ["특약 A", "특약{{", "", "   "],
)
def test_marker_id_that_cannot_be_read_back_is_refused(identifier: str) -> None:
    """되읽기에서 갈라질 값은 추측해 잘라 쓰지 않고 시끄럽게 멈춘다."""
    with pytest.raises(ValueError):
        begin_marker_text(PLACEMENT_SLOT, identifier, None)


def test_marker_label_that_cannot_be_read_back_is_refused() -> None:
    with pytest.raises(ValueError, match="label"):
        begin_marker_text(PLACEMENT_SLOT, "특약", "두  칸")
    with pytest.raises(ValueError, match="label"):
        begin_marker_text(PLACEMENT_SLOT, "특약", "닫는}}괄호")


def test_unknown_placement_kind_is_loud() -> None:
    with pytest.raises(ValueError, match="구간 종류"):
        end_marker_text("field")


# -------------------------------------------------------------- 6. 파일 verb
def test_slot_file_verbs_save_in_place(tmp_path: Path) -> None:
    """성공하면 제자리 저장이고, 반환은 변이 뒤 제품 Slot 목록이다."""
    target = tmp_path / "template.hwpx"
    pkg = _two_slot_package()
    target.write_bytes(pkg.to_bytes())

    renamed = rename_slot_label_file(str(target), "부기", "부기 조항")
    assert [(slot.id, slot.label) for slot in renamed] == [
        ("특약", "특약 사항"),
        ("부기", "부기 조항"),
    ]
    saved = HwpxPackage.from_bytes(target.read_bytes())
    assert inspect_slots(saved)[0][1].label == "부기 조항"

    remaining = decompile_slot_file(str(target), "특약")
    assert [slot.id for slot in remaining] == ["부기"]
    saved = HwpxPackage.from_bytes(target.read_bytes())
    assert scan_structure(saved).slots[0].id == "특약"

    left = remove_slot_file(str(target), "부기")
    assert left == ()


def test_slot_file_verb_leaves_bytes_untouched_on_refusal(tmp_path: Path) -> None:
    """거절은 파일을 열어만 보고 닫는다(compile_structure_file 과 같은 규율)."""
    target = tmp_path / "template.hwpx"
    target.write_bytes(_two_slot_package().to_bytes())
    before = target.read_bytes()

    with pytest.raises(ValueError):
        decompile_slot_file(str(target), "없음")
    assert target.read_bytes() == before


def test_removed_slot_takes_its_content(tmp_path: Path) -> None:
    """삭제는 범위의 본문까지 가져간다(기존 remove_slot 재사용 — 신규 코드 0)."""
    target = tmp_path / "template.hwpx"
    target.write_bytes(_two_slot_package().to_bytes())

    remove_slot_file(str(target), "부기")

    saved = HwpxPackage.from_bytes(target.read_bytes())
    assert [slot.id for slot in inspect_slots(saved)[0]] == ["특약"]
    assert "부기:" not in "".join(_texts(saved, SECTION))


def test_option_order_survives_the_round_trip() -> None:
    """선택 순서는 표기 순서다 — 되돌린 뒤에도 같은 순서로 읽힌다."""
    pkg = _notation_package()
    compile_structure(pkg)
    decompile_slot(pkg, "특약")

    residue = scan_structure(pkg)
    assert residue.slots[0].options == (
        SlotOption("지체상금", 0, "지체상금 조항"),
        SlotOption("하자보수", 1, "하자보수 조항"),
    )
