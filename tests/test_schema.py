"""템플릿 스키마 추출 테스트 — SYNTHETIC 정밀 검증 + 실제 코퍼스 충실도.

SYNTHETIC 조각은 최소 HWPX 패키지(mimetype + section0.xml)로 감싸 ``extract_schema``
공개 경로를 그대로 태운다(``content_xml_names`` 순회 포함).
"""

from __future__ import annotations

import json
from pathlib import Path

from hwpxfiller.core.engine import HwpxEngine
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.core.schema import FieldSpec, _infer_type, extract_schema

HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
HS = "http://www.hancom.co.kr/hwpml/2011/section"

CORPUS = Path(__file__).parent / "corpus" / "real"


def _pkg(section_inner: str) -> HwpxPackage:
    """``<hs:sec>...</hs:sec>`` 로 감싼 섹션 조각을 담은 최소 HWPX 패키지."""
    sec = (
        f'<hs:sec xmlns:hs="{HS}" xmlns:hp="{HP}">{section_inner}</hs:sec>'
    ).encode("utf-8")
    pkg = HwpxPackage()
    pkg.entries[MIMETYPE_NAME] = MIMETYPE_VALUE
    pkg.stored.add(MIMETYPE_NAME)
    pkg.entries["Contents/section0.xml"] = sec
    return pkg


def _field(section_inner: str, name: str) -> "FieldSpec | None":
    schema = extract_schema(_pkg(section_inner))
    for f in schema.fields:
        if f.name == name:
            return f
    return None


# --------------------------------------------------------------- 빈 누름틀 포착
def test_empty_field_captured():
    """값 없는 빈 누름틀도 스키마에 잡힌다 — Paragraph.fields(값 있는 필드만)와의 핵심 차이.

    템플릿의 placeholder 는 대개 비어 있으므로, 이걸 놓치면 스키마가 쓸모없어진다.
    """
    xml = """
    <hp:p>
      <hp:run><hp:ctrl><hp:fieldBegin name="계약명"/></hp:ctrl></hp:run>
      <hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>
    </hp:p>
    """
    schema = extract_schema(_pkg(xml))
    assert schema.field_names() == ["계약명"]
    assert schema.fields[0].occurrences == 1
    assert schema.fields[0].context == ""  # 텍스트 없는 빈 필드


def test_braced_field_name_normalized():
    """``name="{{X}}"`` 형태 누름틀 이름은 중괄호를 벗겨 잡는다."""
    xml = '<hp:p><hp:run><hp:ctrl><hp:fieldBegin name="{{공고명}}"/></hp:ctrl></hp:run></hp:p>'
    schema = extract_schema(_pkg(xml))
    assert schema.field_names() == ["공고명"]


# ------------------------------------------------------------------ 타입 추론
def test_infer_type_unit():
    """이름 기반 타입 추론 규칙 — 우선순위(전화 > 번호) 포함."""
    assert _infer_type("납품기한") == "date"
    assert _infer_type("입찰개시일시") == "date"
    assert _infer_type("하자담보기간") == "date"
    assert _infer_type("사업예산") == "amount"
    assert _infer_type("추정가격") == "amount"
    assert _infer_type("수량") == "number"
    assert _infer_type("입찰공고번호") == "number"
    # 전화(phone) 규칙이 번호(number) 보다 앞서 이긴다.
    assert _infer_type("담당자 전화번호") == "phone"
    assert _infer_type("수요기관") == "text"


def test_inferred_type_flows_into_spec():
    xml = '<hp:p><hp:run><hp:ctrl><hp:fieldBegin name="사업예산"/></hp:ctrl></hp:run></hp:p>'
    spec = _field(xml, "사업예산")
    assert spec is not None and spec.inferred_type == "amount"


# ------------------------------------------------------------ 라벨 문맥 포착
def test_context_label_captured():
    """필드를 품은 문단 텍스트가 라벨 힌트(context)로 잡힌다."""
    xml = """
    <hp:p>
      <hp:run><hp:t>계약명: </hp:t></hp:run>
      <hp:run><hp:ctrl><hp:fieldBegin name="계약명"/></hp:ctrl></hp:run>
      <hp:run><hp:t>정보시스템 구축</hp:t></hp:run>
      <hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>
    </hp:p>
    """
    spec = _field(xml, "계약명")
    assert spec is not None
    assert spec.context == "계약명: 정보시스템 구축"


# --------------------------------------------------------- 등장 횟수 병합
def test_occurrences_merged_across_paragraphs():
    """같은 필드가 여러 번 등장하면 FieldSpec 하나로 병합되고 occurrences 가 센다."""
    xml = """
    <hp:p><hp:run><hp:ctrl><hp:fieldBegin name="계약명"/></hp:ctrl></hp:run></hp:p>
    <hp:p><hp:run><hp:ctrl><hp:fieldBegin name="계약명"/></hp:ctrl></hp:run></hp:p>
    """
    schema = extract_schema(_pkg(xml))
    assert schema.field_names() == ["계약명"]
    assert schema.fields[0].occurrences == 2


# --------------------------------------------------------- 표 영역 / in_table
def test_field_in_table_flagged_and_region_reported():
    """표 셀 안 필드는 in_table=True 이고, 그 표가 반복 후보 영역으로 신고된다."""
    xml = """
    <hp:p><hp:run>
      <hp:tbl>
        <hp:tr>
          <hp:tc><hp:subList>
            <hp:p><hp:run><hp:t>품명</hp:t></hp:run></hp:p>
          </hp:subList></hp:tc>
          <hp:tc><hp:subList>
            <hp:p>
              <hp:run><hp:ctrl><hp:fieldBegin name="공급가액"/></hp:ctrl></hp:run>
              <hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>
            </hp:p>
          </hp:subList></hp:tc>
        </hp:tr>
      </hp:tbl>
    </hp:run></hp:p>
    """
    schema = extract_schema(_pkg(xml))
    spec = next(f for f in schema.fields if f.name == "공급가액")
    assert spec.in_table is True
    assert spec.inferred_type == "amount"
    assert len(schema.table_regions) == 1
    reg = schema.table_regions[0]
    assert reg.rows == 1 and reg.cols == 2
    assert reg.field_names == ["공급가액"]


def test_empty_table_not_reported_as_region():
    """필드가 없는 표는 반복 영역으로 신고하지 않는다(잡음 억제)."""
    xml = """
    <hp:p><hp:run>
      <hp:tbl><hp:tr><hp:tc><hp:subList>
        <hp:p><hp:run><hp:t>그냥 표 셀</hp:t></hp:run></hp:p>
      </hp:subList></hp:tc></hp:tr></hp:tbl>
    </hp:run></hp:p>
    """
    schema = extract_schema(_pkg(xml))
    assert schema.table_regions == []


def test_nested_table_field_attributed_to_inner_table():
    """중첩 표 안 필드는 바깥이 아니라 가장 가까운(안쪽) 표에 귀속된다."""
    xml = """
    <hp:p><hp:run>
      <hp:tbl>
        <hp:tr><hp:tc><hp:subList>
          <hp:p><hp:run>
            <hp:tbl>
              <hp:tr>
                <hp:tc><hp:subList>
                  <hp:p><hp:run><hp:ctrl><hp:fieldBegin name="단가"/></hp:ctrl></hp:run></hp:p>
                </hp:subList></hp:tc>
              </hp:tr>
            </hp:tbl>
          </hp:run></hp:p>
        </hp:subList></hp:tc></hp:tr>
      </hp:tbl>
    </hp:run></hp:p>
    """
    schema = extract_schema(_pkg(xml))
    # 필드 담은 표는 안쪽 하나뿐(바깥 표는 필드 없어 미신고).
    assert len(schema.table_regions) == 1
    assert schema.table_regions[0].field_names == ["단가"]
    assert next(f for f in schema.fields if f.name == "단가").in_table is True


# ------------------------------------------------------ 미치환 {{}} 잔존 탐지
def test_stray_tokens_detected_and_real_fields_excluded():
    """본문 평문의 미치환 ``{{X}}`` 는 신고하되, 실제 누름틀 이름은 제외한다."""
    xml = """
    <hp:p>
      <hp:run><hp:t>미치환 {{누락토큰}} 그리고 </hp:t></hp:run>
      <hp:run><hp:ctrl><hp:fieldBegin name="계약명"/></hp:ctrl></hp:run>
      <hp:run><hp:t>{{계약명}}</hp:t></hp:run>
      <hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>
    </hp:p>
    """
    schema = extract_schema(_pkg(xml))
    assert schema.stray_tokens == ["누락토큰"]  # 계약명은 실제 필드라 제외


# --------------------------------------------------------- 랜덤 ID 누출 없음
def test_no_random_ids_in_output():
    """to_dict() 직렬화에 랜덤 ID 계열 속성이 전혀 남지 않는다."""
    xml = """
    <hp:p id="3121190098" paraPrIDRef="7">
      <hp:run charPrIDRef="99">
        <hp:ctrl><hp:fieldBegin id="2073595120" fieldid="627272811" name="금액"/></hp:ctrl>
      </hp:run>
      <hp:run><hp:t>1,000,000원</hp:t></hp:run>
      <hp:run><hp:ctrl><hp:fieldEnd instId="55"/></hp:ctrl></hp:run>
    </hp:p>
    """
    dumped = json.dumps(extract_schema(_pkg(xml)).to_dict(), ensure_ascii=False)
    for noise in ("3121190098", "2073595120", "627272811", "charPrIDRef", "instId"):
        assert noise not in dumped, f"랜덤 ID 누출: {noise}"


# ------------------------------------------------------------- 실제 코퍼스 충실도
def test_corpus_schema_matches_required_fields():
    """실제 입찰공고 템플릿: 스키마 필드 집합이 엔진 required_fields 와 일치한다."""
    path = CORPUS / "bid_notice_limited_under100m.hwpx"
    schema = extract_schema(str(path))
    required = HwpxEngine().required_fields(str(path))
    assert set(schema.field_names()) == set(required)
    assert schema.unhandled == {}  # 미처리 구조 없음


def test_corpus_type_inference_and_table_region():
    """실제 코퍼스에서 대표 필드 타입과 표 영역(담당자 그룹)이 기대대로 잡힌다."""
    path = CORPUS / "bid_notice_limited_under100m.hwpx"
    schema = extract_schema(str(path))
    by_name = {f.name: f for f in schema.fields}
    assert by_name["사업예산"].inferred_type == "amount"
    assert by_name["납품기한"].inferred_type == "date"
    assert by_name["입찰개시일시"].inferred_type == "date"
    assert by_name["담당자 전화번호"].inferred_type == "phone"
    assert by_name["수량"].inferred_type == "number"
    # 담당 정보는 표 안에 있다 — 반복 영역으로 신고되고 in_table 로 표시된다.
    assert by_name["담당자"].in_table is True
    assert any("담당자" in reg.field_names for reg in schema.table_regions)
