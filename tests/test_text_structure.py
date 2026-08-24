"""TXT 구간 표기 스캐너 — 줄 기반(S10-01 #858).

세 가지를 증명한다:

1. **표기 스캔** — ``scan_text_structure`` 가 선언 구조·줄 배치·요약 수치를 복원하고,
   이상 형태는 하나도 조용히 흘리지 않고 진단으로 남긴다(무변형).
2. **매체 동등** — 같은 선언이 TXT 표기와 HWPX 문단 마커에서 **같은 Slot** 으로
   복원된다. 두 스캐너가 한 상태기계(:mod:`hwpxfiller.domain.structure_scan`)를 쓴다는
   사실의 검사 가능한 얼굴이다.
3. **매체 비적용** — ``MARKER_IN_TABLE``·``MARKER_NOT_TOP_LEVEL`` 은 TXT 에 생성 경로
   자체가 없다(문단 트리가 없어 물음이 성립하지 않는다).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from test_authoring_structure import _doc, _p

from hwpxfiller.domain import text_structure
from hwpxfiller.domain.authoring import scan_structure
from hwpxfiller.domain.slot import Slot, SlotOption
from hwpxfiller.domain.structure_scan import StructureDiagnosticKind as Kind
from hwpxfiller.domain.text_structure import scan_text_structure


def _scan_unchanged(text: str):
    """스캔이 무변형임을 확인하며 스캔한다(모든 fixture 공용)."""
    before = str(text)
    scan = scan_text_structure(text)
    assert text == before
    return scan


def _kinds(scan) -> "list[Kind]":
    return [d.kind for d in scan.diagnostics]


def _lines(*lines: str) -> str:
    return "\n".join(lines)


# ------------------------------------------------------------- A. 긍정 대조
_CANONICAL = _lines(
    "계약 일반사항",                             # 0
    "{{#항목 특약 특약 사항}}",                  # 1
    "{{#선택 지체상금 지체상금 조항}}",          # 2
    "지체상금은 {{지체상금률}} 로 한다.",        # 3
    "{{/선택}}",                                 # 4
    "{{#선택 하자보수 하자보수 조항}}",          # 5
    "하자보수 기간은 {{하자기간}} 이다.",        # 6
    "{{/선택}}",                                 # 7
    "{{/항목}}",                                 # 8
    "",                                          # 9
    "{{#항목 부칙}}",                            # 10  label 없음
    "{{#선택 가}}",                              # 11
    "가 본문",                                   # 12
    "{{/선택}}",                                 # 13
    "{{#선택 나}}",                              # 14
    "나 본문",                                   # 15
    "{{/선택}}",                                 # 16
    "{{/항목}}",                                 # 17
    "발주자: {{수요기관}}",                      # 18
)


def test_positive_control_restores_declaration():
    """진단 0 · 항목 2(label 유/무) · 각 선택 2 를 순서까지 복원한다."""
    scan = _scan_unchanged(_CANONICAL)

    assert scan.diagnostics == ()
    assert scan.slots == (
        Slot(
            id="특약",
            options=(
                SlotOption(id="지체상금", order=0, label="지체상금 조항"),
                SlotOption(id="하자보수", order=1, label="하자보수 조항"),
            ),
            label="특약 사항",
        ),
        Slot(
            id="부칙",
            options=(
                SlotOption(id="가", order=0, label=None),
                SlotOption(id="나", order=1, label=None),
            ),
            label=None,
        ),
    )
    assert json.dumps(scan.to_dict())  # 상위 링 직렬화 가능


def test_positive_control_places_ranges_on_line_coordinates():
    """배치는 0-기반 줄 번호이고 내용 경계는 마커 줄을 **제외**한다."""
    scan = _scan_unchanged(_CANONICAL)

    assert [p.to_dict() for p in scan.placements] == [
        {
            "kind": "slot", "slot_id": "특약", "option_id": None,
            "begin_marker_line": 1, "end_marker_line": 8,
            "content_start": 3, "content_end": 6,
        },
        {
            "kind": "option", "slot_id": "특약", "option_id": "지체상금",
            "begin_marker_line": 2, "end_marker_line": 4,
            "content_start": 3, "content_end": 3,
        },
        {
            "kind": "option", "slot_id": "특약", "option_id": "하자보수",
            "begin_marker_line": 5, "end_marker_line": 7,
            "content_start": 6, "content_end": 6,
        },
        {
            "kind": "slot", "slot_id": "부칙", "option_id": None,
            "begin_marker_line": 10, "end_marker_line": 17,
            "content_start": 12, "content_end": 15,
        },
        {
            "kind": "option", "slot_id": "부칙", "option_id": "가",
            "begin_marker_line": 11, "end_marker_line": 13,
            "content_start": 12, "content_end": 12,
        },
        {
            "kind": "option", "slot_id": "부칙", "option_id": "나",
            "begin_marker_line": 14, "end_marker_line": 16,
            "content_start": 15, "content_end": 15,
        },
    ]


def test_positive_control_summary_counts():
    """요약 수치 — 마커는 자격 불문 전수, 필드는 sigil 보호된 고유 필드 수."""
    scan = _scan_unchanged(_CANONICAL)
    assert scan.summary.to_dict() == {
        "slots": 2, "options": 4, "fields": 3, "markers": 12,
    }


def test_blank_line_counts_as_content():
    """빈 줄도 내용이다 — HWPX 가 빈 문단을 세는 것과 동형(빈 범위 오판 방지)."""
    scan = _scan_unchanged(_lines("{{#항목 특약}}", "", "{{/항목}}"))
    assert scan.diagnostics == ()
    assert scan.placements[0].content_start == 1
    assert scan.placements[0].content_end == 1


# ------------------------------------------- B. 진단 전수 (TXT 적용 종별 각 1+)
def test_diagnostic_unbalanced_end_without_begin():
    """1(후) — 닫는 마커의 여는 짝이 없다(항목·선택 양방향)."""
    scan = _scan_unchanged(_lines("본문", "{{/항목}}", "{{/선택}}"))
    assert _kinds(scan) == [Kind.UNBALANCED_MARKER, Kind.UNBALANCED_MARKER]
    assert "여는 「항목」 마커 없이" in scan.diagnostics[0].message
    assert "여는 「선택」 마커 없이" in scan.diagnostics[1].message
    assert scan.slots == ()


def test_diagnostic_unbalanced_begin_without_end_names_the_file_scope():
    """1(전) — 열린 채 파일이 끝났다. scope 명사는 HWPX 의 「content XML」이 아니다."""
    scan = _scan_unchanged(_lines("{{#항목 특약}}", "{{#선택 가}}", "본문"))
    assert _kinds(scan) == [Kind.UNBALANCED_MARKER, Kind.UNBALANCED_MARKER]
    assert "범위가 열린 채 파일이 끝났습니다" in scan.diagnostics[0].message
    assert "content XML" not in scan.diagnostics[1].message
    assert scan.slots == ()  # 미완결 선언은 복원하지 않는다


def test_diagnostic_crossed_range():
    """2 — 항목·선택 범위가 교차한다."""
    scan = _scan_unchanged(
        _lines("{{#항목 특약}}", "{{#선택 가}}", "본문", "{{/항목}}", "{{/선택}}")
    )
    assert Kind.CROSSED_RANGE in _kinds(scan)
    assert "범위가 교차합니다" in scan.diagnostics[0].message


def test_diagnostic_unknown_keyword():
    """3 — 미지 키워드는 조용히 흘리지 않는다."""
    scan = _scan_unchanged(_lines("{{#조건 x}}", "본문", "{{/조건}}"))
    assert _kinds(scan) == [Kind.UNKNOWN_KEYWORD, Kind.UNKNOWN_KEYWORD]
    assert "조건" in scan.diagnostics[0].message


def test_diagnostic_empty_slot_id():
    """4 — 「항목」 마커에 id 가 없다."""
    scan = _scan_unchanged(_lines("{{#항목}}", "본문", "{{/항목}}"))
    assert Kind.EMPTY_SLOT_ID in _kinds(scan)
    assert "id 는 필수입니다" in scan.diagnostics[0].message


def test_diagnostic_empty_option_id():
    """5 — 「선택」 마커에 id 가 없다."""
    scan = _scan_unchanged(
        _lines("{{#항목 특약}}", "{{#선택}}", "본문", "{{/선택}}", "{{/항목}}")
    )
    assert Kind.EMPTY_OPTION_ID in _kinds(scan)


def test_diagnostic_duplicate_slot_id():
    """6 — 같은 파일에서 항목 id 가 두 번 선언됐다."""
    scan = _scan_unchanged(
        _lines(
            "{{#항목 특약}}", "본문", "{{/항목}}",
            "{{#항목 특약}}", "본문", "{{/항목}}",
        )
    )
    assert _kinds(scan) == [Kind.DUPLICATE_SLOT_ID]
    assert "두 번 선언됐습니다" in scan.diagnostics[0].message


def test_diagnostic_duplicate_option_id():
    """7 — 한 항목 안에서 선택 id 가 두 번 선언됐다."""
    scan = _scan_unchanged(
        _lines(
            "{{#항목 특약}}",
            "{{#선택 가}}", "본문", "{{/선택}}",
            "{{#선택 가}}", "본문", "{{/선택}}",
            "{{/항목}}",
        )
    )
    assert _kinds(scan) == [Kind.DUPLICATE_OPTION_ID]


def test_diagnostic_option_outside_slot():
    """8 — 선택이 항목 범위 밖에 있다."""
    scan = _scan_unchanged(_lines("{{#선택 가}}", "본문", "{{/선택}}"))
    assert Kind.OPTION_OUTSIDE_SLOT in _kinds(scan)
    assert "항목 직속만 가능합니다" in scan.diagnostics[0].message


def test_diagnostic_nested_slot():
    """9 — 항목 중첩은 없다."""
    scan = _scan_unchanged(
        _lines("{{#항목 가}}", "{{#항목 나}}", "본문", "{{/항목}}", "{{/항목}}")
    )
    assert Kind.NESTED_SLOT in _kinds(scan)
    assert "항목 중첩은 없습니다" in scan.diagnostics[0].message


def test_diagnostic_nested_option():
    """10 — 선택이 닫히기 전에 선택을 또 열었다."""
    scan = _scan_unchanged(
        _lines(
            "{{#항목 특약}}", "{{#선택 가}}", "{{#선택 나}}",
            "본문", "{{/선택}}", "{{/항목}}",
        )
    )
    assert Kind.NESTED_OPTION in _kinds(scan)


def test_diagnostic_marker_not_alone_two_markers_on_one_line():
    """11(가) — 한 줄에 마커가 2개. 문안은 「문단」이 아니라 「줄」이다."""
    scan = _scan_unchanged("{{#항목 특약}}{{/항목}}")
    assert _kinds(scan) == [Kind.MARKER_NOT_ALONE]
    assert scan.diagnostics[0].message == (
        "한 줄에 구간 마커가 2개 이상입니다 — 마커는 줄을 단독으로 차지해야 합니다."
    )
    assert scan.summary.markers == 2  # 거절돼도 파일에는 남아 있다


def test_diagnostic_marker_not_alone_with_residual_text():
    """11(나) — 마커가 다른 텍스트와 같은 줄에 있다."""
    scan = _scan_unchanged(_lines("앞말 {{#항목 특약}}", "본문", "{{/항목}}"))
    assert _kinds(scan) == [Kind.MARKER_NOT_ALONE, Kind.UNBALANCED_MARKER]
    assert scan.diagnostics[0].message == (
        "구간 마커가 다른 텍스트와 같은 줄에 있습니다 — 마커는 줄을 단독으로 "
        "차지해야 합니다."
    )
    assert scan.diagnostics[0].context == "앞말 {{#항목 특약}}"


def test_diagnostic_empty_range():
    """12 — 범위에 내용 줄이 하나도 없다."""
    scan = _scan_unchanged(_lines("{{#항목 특약}}", "{{/항목}}"))
    assert _kinds(scan) == [Kind.EMPTY_RANGE]


def test_diagnostic_end_marker_extra_text():
    """13 — 닫는 마커는 키워드만 가진다."""
    scan = _scan_unchanged(_lines("{{#항목 특약}}", "본문", "{{/항목 군더더기}}"))
    assert _kinds(scan) == [Kind.END_MARKER_EXTRA_TEXT]
    assert "군더더기" in scan.diagnostics[0].message


@pytest.mark.parametrize("kind", [Kind.MARKER_IN_TABLE, Kind.MARKER_NOT_TOP_LEVEL])
def test_paragraph_tree_diagnostics_have_no_txt_generator(kind: Kind):
    """TXT 비적용 — 문단 트리가 없어 물음 자체가 성립하지 않는다(조용한 통과 아님)."""
    scan = _scan_unchanged(_CANONICAL)
    assert kind not in _kinds(scan)
    # 문자열 grep 이 아니라 AST 로 본다 — 이 모듈의 도크스트링이 두 종별의 **비적용**을
    # 설명하므로 문자열까지 세면 규칙이 제 문서에 걸려 영영 빨강이다(#216 회귀 금지).
    tree = ast.parse(Path(text_structure.__file__).read_text(encoding="utf-8"))
    emitted = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "StructureDiagnosticKind"
    }
    assert emitted and kind.name not in emitted  # 진단을 낼 코드 자체가 없다


# ------------------------------------------------ C. HWPX↔TXT 동등성(#858 축)
_EQUIVALENT = (
    "{{#항목 특약 특약 사항}}",
    "{{#선택 지체상금 지체상금 조항}}",
    "지체상금은 {{지체상금률}} 로 한다.",
    "{{/선택}}",
    "{{#선택 하자보수 하자보수 조항}}",
    "하자보수 기간은 {{하자기간}} 이다.",
    "{{/선택}}",
    "{{/항목}}",
)


def test_same_declaration_restores_identical_slots_across_media():
    """같은 선언은 TXT 표기와 HWPX 문단 마커에서 **같은 Slot 값**으로 복원된다."""
    text_scan = scan_text_structure("\n".join(_EQUIVALENT))
    hwpx_scan = scan_structure(_doc(*(_p(line) for line in _EQUIVALENT)))

    assert text_scan.diagnostics == ()
    assert hwpx_scan.diagnostics == ()
    assert text_scan.slots == hwpx_scan.slots
    assert text_scan.to_dict()["slots"] == hwpx_scan.to_dict()["slots"]
    # 요약도 같은 수치를 본다(좌표만 매체별로 갈린다).
    assert text_scan.summary == hwpx_scan.summary


def test_placement_types_do_not_share_the_hwpx_coordinate_name():
    """#856 D2 — 배치 타입이 갈린다. 줄 좌표가 문단 좌표 이름으로 새지 않는다."""
    text_scan = scan_text_structure("\n".join(_EQUIVALENT))
    hwpx_scan = scan_structure(_doc(*(_p(line) for line in _EQUIVALENT)))

    assert set(text_scan.placements[0].to_dict()) == {
        "kind", "slot_id", "option_id",
        "begin_marker_line", "end_marker_line", "content_start", "content_end",
    }
    assert "entry" in hwpx_scan.placements[0].to_dict()
    assert "begin_marker_index" in hwpx_scan.placements[0].to_dict()


# ---------------------------------------------- D. 선택 투영(S10-03 #860)
# 「포함할 내용」이 고른 것만 남기는 **순수 함수**의 계약. 마커는 저작 표기라 언제나 걷히고,
# 고르지 않은 선택 범위만 접힌다 — 항목 직속 문구는 선택의 대상이 아니므로 남는다.


def test_selection_projection_keeps_only_chosen_options():
    scan = _scan_unchanged(_CANONICAL)
    selected = {"특약": frozenset({"하자보수"}), "부칙": frozenset({"가"})}

    assert text_structure.visible_lines(_CANONICAL, scan, selected) == (
        0, 6, 9, 12, 18,
    )
    assert text_structure.project_selected_text(_CANONICAL, scan, selected) == _lines(
        "계약 일반사항",
        "하자보수 기간은 {{하자기간}} 이다.",
        "",
        "가 본문",
        "발주자: {{수요기관}}",
    )


def test_selection_projection_hides_every_option_when_nothing_is_chosen():
    """선택 0 건이면 그 항목의 선택 범위는 전부 접힌다 — 1개짜리도 자동 선택하지 않는다."""
    scan = _scan_unchanged(_CANONICAL)

    projected = text_structure.project_selected_text(_CANONICAL, scan, {})
    assert projected == _lines("계약 일반사항", "", "발주자: {{수요기관}}")
    # 마커는 어느 경우에도 새지 않는다(저작 표기가 산출 텍스트로 흘러가면 그것이 결함이다).
    assert "{{#" not in projected and "{{/" not in projected


def test_selection_projection_keeps_lines_directly_under_a_slot():
    """항목 직속(선택 밖) 줄은 언제나 보인다 — 항목을 연 것이 공통 문구를 고르게 하지 않는다."""
    text = _lines(
        "머리말",                        # 0
        "{{#항목 첨부}}",                # 1
        "공통 안내",                     # 2
        "{{#선택 가}}",                  # 3
        "가 본문",                       # 4
        "{{/선택}}",                     # 5
        "맺음 안내",                     # 6
        "{{/항목}}",                     # 7
    )
    scan = _scan_unchanged(text)

    assert text_structure.visible_lines(text, scan, {}) == (0, 2, 6)
    assert text_structure.visible_lines(
        text, scan, {"첨부": frozenset({"가"})}
    ) == (0, 2, 4, 6)


def test_selection_projection_preserves_original_line_endings():
    """줄 끝 문자는 원문 그대로 옮긴다 — 투영이 CRLF 템플릿의 줄바꿈을 갈아입히지 않는다."""
    text = "머리말\r\n{{#항목 첨부}}\r\n{{#선택 가}}\r\n가 본문\r\n{{/선택}}\r\n{{/항목}}\r\n꼬리말\r\n"
    scan = _scan_unchanged(text)

    assert text_structure.project_selected_text(
        text, scan, {"첨부": frozenset({"가"})}
    ) == "머리말\r\n가 본문\r\n꼬리말\r\n"


def test_selection_projection_refuses_when_the_scan_carries_diagnostics():
    """진단 1건 이상 = 좌표 불신뢰. 반쪽을 그리지 않고 시끄럽게 거절한다(fail-closed)."""
    text = _lines("{{#항목 첨부}}", "본문", "")  # 닫는 마커 없음
    scan = _scan_unchanged(text)
    assert scan.diagnostics

    with pytest.raises(text_structure.TextStructureProjectionError):
        text_structure.visible_lines(text, scan, {})
    with pytest.raises(text_structure.TextStructureProjectionError):
        text_structure.project_selected_text(text, scan, {})


def test_selection_projection_is_identity_for_a_slotless_template():
    """마커 0 건이면 투영은 항등이다 — 기존 TXT 작업 경로가 이 함수를 지나도 무변화."""
    text = _lines("수신: {{수신}}", "건명: {{건명}}", "")
    scan = _scan_unchanged(text)

    assert text_structure.project_selected_text(text, scan, {}) == text
