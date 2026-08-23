"""S7-02 · #824 — Artifact 구조 관찰 스냅샷(링1) 의 헤드리스 계약.

합성 package 는 ``tests/test_extract_synthetic.py`` 가 머리말/꼬리말 경로를 세울 때 쓴
방식(``HwpxPackage`` 에 ``Contents/*.xml`` 바이트를 직접 얹기)을 그대로 따른다 — 파일 IO
없이 관찰 층만 태우기 위해서다.
"""

from __future__ import annotations

import json

from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.domain.job import MISSING_MARKER
from hwpxfiller.gui.artifact_view_state import (
    ARTIFACT_PARTIAL_COVERAGE,
    observed_artifact_snapshot,
)

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"


def _para(text: str) -> str:
    return f"<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>"


def _package(entries: "dict[str, str]") -> HwpxPackage:
    """``{"section0": 본문조각}`` 을 최소 HWPX package 로 감싼다(디스크 접촉 없음)."""
    pkg = HwpxPackage()
    pkg.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    pkg.stored.add(MIMETYPE_NAME)
    for name, inner in entries.items():
        pkg.entries[f"Contents/{name}.xml"] = (
            f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{inner}</hs:sec>'
        ).encode("utf-8")
    return pkg


def test_paragraph_text_projected_into_snapshot_sections():
    """문단 텍스트가 스냅샷 ``sections`` 에 그대로 투영된다(머리말/꼬리말도 제 영역으로)."""
    snapshot = observed_artifact_snapshot(
        _package(
            {
                "section0": _para("계약 상대자 귀하") + _para("붙임 서류 1부."),
                "header0": _para("머리말 문구"),
                "footer0": _para("꼬리말 문구"),
            }
        )
    )
    assert snapshot["kind"] == "artifact-observation/v1"
    assert [b["text"] for b in snapshot["sections"][0]["blocks"]] == [
        "계약 상대자 귀하",
        "붙임 서류 1부.",
    ]
    assert snapshot["headers"][0]["blocks"][0]["text"] == "머리말 문구"
    assert snapshot["footers"][0]["blocks"][0]["text"] == "꼬리말 문구"


def test_table_rows_columns_and_merge_metadata_survive():
    """표의 행·열 구조와 ``span``/``addr`` 병합 메타가 스냅샷에 보존된다."""
    inner = """
    <hp:p><hp:run>
      <hp:tbl>
        <hp:tr>
          <hp:tc>
            <hp:cellAddr colAddr="0" rowAddr="0"/>
            <hp:cellSpan colSpan="2" rowSpan="1"/>
            <hp:subList><hp:p><hp:run><hp:t>병합 머리</hp:t></hp:run></hp:p></hp:subList>
          </hp:tc>
        </hp:tr>
        <hp:tr>
          <hp:tc>
            <hp:cellAddr colAddr="0" rowAddr="1"/>
            <hp:cellSpan colSpan="1" rowSpan="1"/>
            <hp:subList><hp:p><hp:run><hp:t>좌</hp:t></hp:run></hp:p></hp:subList>
          </hp:tc>
          <hp:tc>
            <hp:cellAddr colAddr="1" rowAddr="1"/>
            <hp:cellSpan colSpan="1" rowSpan="1"/>
            <hp:subList><hp:p><hp:run><hp:t>우</hp:t></hp:run></hp:p></hp:subList>
          </hp:tc>
        </hp:tr>
      </hp:tbl>
    </hp:run></hp:p>
    """
    snapshot = observed_artifact_snapshot(_package({"section0": inner}))
    table = snapshot["sections"][0]["blocks"][0]
    assert table["type"] == "table"
    assert [len(row) for row in table["rows"]] == [1, 2]
    head = table["rows"][0][0]
    assert head["span"] == {"colSpan": 2, "rowSpan": 1}
    assert head["addr"] == {"colAddr": 0, "rowAddr": 0}
    assert [c["blocks"][0]["text"] for c in table["rows"][1]] == ["좌", "우"]
    assert table["rows"][1][1]["addr"] == {"colAddr": 1, "rowAddr": 1}


def test_missing_value_markers_counted_across_paragraphs_and_cells():
    """미치환 표식은 문단·표 셀(중첩 포함)을 가로질러 필드별로 합산된다.

    표식 문자열은 여기서도 정본 :data:`MISSING_MARKER` 로 만든다 — 검출기와 테스트가
    각자 문자열을 적으면 정본이 움직여도 둘 다 초록인 사각이 생긴다.
    """
    contract = MISSING_MARKER.format(field="계약명")
    amount = MISSING_MARKER.format(field="금액")
    inner = f"""
    {_para(f"계약명: {contract}")}
    <hp:p><hp:run>
      <hp:tbl><hp:tr>
        <hp:tc><hp:subList>
          <hp:p><hp:run><hp:t>{contract}</hp:t></hp:run></hp:p>
        </hp:subList></hp:tc>
        <hp:tc><hp:subList>
          <hp:p><hp:run>
            <hp:tbl><hp:tr><hp:tc><hp:subList>
              <hp:p><hp:run><hp:t>{amount}</hp:t></hp:run></hp:p>
            </hp:subList></hp:tc></hp:tr></hp:tbl>
          </hp:run></hp:p>
        </hp:subList></hp:tc>
      </hp:tr></hp:tbl>
    </hp:run></hp:p>
    """
    snapshot = observed_artifact_snapshot(
        _package({"section0": inner, "footer0": _para(contract)})
    )
    # 필드 이름 정렬로 결정적 — 계약명(본문 1 + 셀 1 + 꼬리말 1) / 금액(중첩 셀 1).
    assert snapshot["missing_value_markers"] == [
        {"field": "계약명", "count": 3},
        {"field": "금액", "count": 1},
    ]


def test_clean_document_reports_no_missing_markers():
    """표식이 없는 문서는 빈 목록을 낸다 — 키를 지우지 않는다."""
    snapshot = observed_artifact_snapshot(_package({"section0": _para("정상 문구")}))
    assert snapshot["missing_value_markers"] == []


def test_unknown_structure_is_flagged_but_observation_still_stands():
    """미포섭 구간은 「표시하지 못한 구간」으로 병기되고 관찰 자체는 성립한다(#820 §3)."""
    inner = "<hp:p><hp:run><hp:t>본문 문구</hp:t></hp:run><hp:someNewThing/></hp:p>"
    snapshot = observed_artifact_snapshot(_package({"section0": inner}))
    assert snapshot["partial_coverage"] is True
    assert snapshot["coverage_code"] == ARTIFACT_PARTIAL_COVERAGE
    assert snapshot["unrendered_regions"]["counts"]["someNewThing"] == 1
    assert "someNewThing" in snapshot["unrendered_regions"]["examples"]
    # 부분 포섭은 거절이 아니다 — 본 것은 그대로 서 있다.
    assert snapshot["sections"][0]["blocks"][0]["text"] == "본문 문구"


def test_full_coverage_keeps_empty_ledger_keys_present():
    """완전 포섭이어도 ``unrendered_regions`` 키는 사라지지 않는다(숨기지 않는다)."""
    snapshot = observed_artifact_snapshot(_package({"section0": _para("정상 문구")}))
    assert snapshot["partial_coverage"] is False
    assert snapshot["coverage_code"] == ""
    assert snapshot["unrendered_regions"] == {"counts": {}, "examples": {}}


def test_snapshot_survives_json_roundtrip():
    """스냅샷은 JSON-safe 다 — 링2 로 넘길 값에 비직렬화 객체가 섞이지 않는다."""
    inner = (
        _para(MISSING_MARKER.format(field="계약명"))
        + "<hp:p><hp:run><hp:tbl><hp:tr><hp:tc>"
        "<hp:cellSpan colSpan=\"1\" rowSpan=\"1\"/>"
        "<hp:subList><hp:p><hp:run><hp:t>셀</hp:t></hp:run></hp:p></hp:subList>"
        "</hp:tc></hp:tr></hp:tbl></hp:run></hp:p>"
        + "<hp:unknownThing/>"
    )
    snapshot = observed_artifact_snapshot(_package({"section0": inner}))
    assert json.loads(json.dumps(snapshot, ensure_ascii=False)) == snapshot


def _key_paths(value: object, prefix: str = "") -> "list[str]":
    """직렬화 가능한 값의 모든 dict 키 경로를 모은다."""
    paths: "list[str]" = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.append(path)
            paths.extend(_key_paths(child, path))
    elif isinstance(value, list):
        for item in value:
            paths.extend(_key_paths(item, f"{prefix}[]"))
    return paths


def test_vocabulary_keeps_artifact_view_distinct_from_projection():
    """스냅샷 키 경로 어디에도 ``preview``/``projection`` 어근이 없다(#820 D4).

    Projection(생성 **전** 예고)과 Artifact View(생성 **후** 실물 관찰)가 데이터 층에서
    같은 낱말을 쓰면 두 사건이 화면에서 구분되지 않는다.
    """
    inner = (
        _para(MISSING_MARKER.format(field="계약명"))
        + "<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList>"
        "<hp:p><hp:run><hp:t>셀</hp:t></hp:run></hp:p>"
        "</hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>"
        + "<hp:unknownThing/>"
    )
    snapshot = observed_artifact_snapshot(
        _package({"section0": inner, "header0": _para("머리말")})
    )
    offenders = [
        path
        for path in _key_paths(snapshot)
        if "preview" in path.lower() or "projection" in path.lower()
    ]
    assert not offenders, f"Projection 어휘 누출: {offenders}"
