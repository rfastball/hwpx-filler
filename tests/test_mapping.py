"""매핑 계층 테스트 — 단일 소스 값 유형·자동제안·프로파일 저장/적용 + 실 API 레코드 통합.

소스 필드명은 실제 나라장터 표준 응답 키(bidNtceNo·opengDate·opengTm·presmptPrce)를
쓴다 — 매핑 설계를 실데이터 형태에 근거해 검증한다. 엄격한 1:1: 한 필드는 한 소스 키.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hwpxfiller.core.engine import HwpxEngine
from hwpxfiller.core.mapping import (
    TYPES,
    FieldMapping,
    MappingProfile,
    apply_transform,
    suggest_mappings,
)
from hwpxfiller.data.nara import NaraStdDataSource
from hwpxcore.package import HwpxPackage

FIXTURES = Path(__file__).parent / "fixtures"
CORPUS = Path(__file__).parent / "corpus" / "real"

# 어휘는 이제 소스가 소유한다(코어 아님) — V1 승격 후 새 출처.
NARA_ALIASES = NaraStdDataSource.field_labels()


def _nara_record() -> dict:
    """실 라이브 응답 픽스처의 첫 레코드(envelope response.body.items[0])."""
    env = json.loads((FIXTURES / "nara_std_response.json").read_text(encoding="utf-8"))
    return env["response"]["body"]["items"][0]


# ------------------------------------------------------------------ 값 유형
def test_transform_date_renders_standard_default():
    """단일 날짜 값 → 공문서 표준 날짜(기본 표시형)."""
    assert apply_transform("date", "2026-06-15") == "2026. 6. 15."


def test_transform_date_time_only_value():
    """시각 단독값도 date 유형·시각 서식으로 렌더된다(N→1 결합 제거의 대체)."""
    assert apply_transform("date", "1400", fmt="%H:%M") == "14:00"
    assert apply_transform("date", "18:00", fmt="%H:%M") == "18:00"


def test_transform_amount_formats_number():
    assert apply_transform("amount", "21326800") == "21,326,800원"


def test_transform_text_and_const():
    assert apply_transform("text", "가나") == "가나"
    assert apply_transform("const", const="수의계약") == "수의계약"


def test_transform_amount_graceful_on_nonnumeric():
    assert apply_transform("amount", "미정") == "미정"


def test_apply_transform_raises_on_unknown_kind():
    """RC-10 회귀: 미지 유형의 조용한 폴백 금지 — 서식 미적용 값 무경고 주입 차단."""
    with pytest.raises(ValueError, match="amonut"):
        apply_transform("amonut", "123456789", fmt="{:,}")


def test_apply_transform_known_kinds_and_blank():
    """지원 유형(+내부 blank)은 단일값 기반으로 동작. blank 는 언제나 빈 값."""
    assert apply_transform("text", "가나") == "가나"
    assert apply_transform("blank", "무시") == ""


# ------------------------------------------------------------- FieldMapping.value
def test_field_mapping_reads_single_source():
    rec = _nara_record()
    assert FieldMapping("추정가격", "presmptPrce", type="amount").value_for(rec) == "65,454,545원"
    assert FieldMapping("개찰일", "opengDate", type="date").value_for(rec) == "2026. 6. 15."
    assert FieldMapping("개찰시각", "opengTm", type="date", fmt="%H:%M").value_for(rec) == "18:00"


def test_field_mapping_defaults_to_text():
    assert FieldMapping("공고명", "bidNtceNo").type == "text"


# ------------------------------------------------------------------ 자동 제안
def test_suggest_matches_exact_aliases():
    """영문 소스 키라도 alias 사전 경유 퍼지로 명확한 필드는 자동 제안된다."""
    template = ["입찰공고번호", "공고명", "추정가격"]
    source_keys = list(NARA_ALIASES)
    sugg = {m.template_field: m.source for m in suggest_mappings(template, source_keys, NARA_ALIASES)}
    assert sugg["입찰공고번호"] == "bidNtceNo"
    assert sugg["공고명"] == "bidNtceNm"
    assert sugg["추정가격"] == "presmptPrce"


def test_suggest_respects_threshold():
    """유사도가 임계 미만이면 제안하지 않는다(잘못 꽂지 않음 — 사람 확정 대기)."""
    sugg = suggest_mappings(["존재하지않는들판xyz"], list(NARA_ALIASES), NARA_ALIASES, threshold=0.6)
    assert sugg == []


def test_suggest_is_one_to_one_text_draft():
    """제안은 1:1 초안이며 유형은 기본 text — 서식 필요 필드는 사람이 date/amount 로."""
    sugg = suggest_mappings(["입찰개시일시"], list(NARA_ALIASES), NARA_ALIASES)
    assert len(sugg) == 1
    assert sugg[0].source == "bidBeginDate"
    assert sugg[0].type == "text"


def test_suggest_without_source_vocabulary_matches_raw_keys():
    """어휘 없는 소스(Excel/CSV — 헤더가 이미 사람 라벨)는 원 키에 직접 퍼지 매칭한다.

    나라장터 어휘가 모든 소스에 강요되지 않음을 못박는다(V1 GUI 기본 alias 제거):
    한글 헤더 소스는 aliases 없이도 초안이 잡히고, 영문 코드 소스는 aliases 없이는
    한글 필드와 안 맞아 초안이 없다(코어는 어휘를 몰래 얹지 않는다).
    """
    # 한글 헤더 Excel 소스 — aliases 없이 직접 매칭.
    sugg = suggest_mappings(["공고명", "추정가격"], ["공고명", "추정가격", "비고"])
    pairs = {m.template_field: m.source for m in sugg}
    assert pairs == {"공고명": "공고명", "추정가격": "추정가격"}
    # 영문 코드 소스 — 나라 어휘를 강요하지 않으면 한글 필드와 안 맞아 초안 없음.
    assert suggest_mappings(["공고명"], ["bidNtceNm"]) == []


# ------------------------------------------------------------- 프로파일 저장/적용
def test_profile_apply_produces_template_dict():
    rec = _nara_record()
    profile = MappingProfile(
        name="나라장터표준→입찰공고",
        mappings=[
            FieldMapping("입찰공고번호", "bidNtceNo"),
            FieldMapping("계약방법", "cntrctCnclsMthdNm"),
            FieldMapping("추정가격", "presmptPrce", type="amount"),
            FieldMapping("개찰일", "opengDate", type="date"),
            FieldMapping("개찰시각", "opengTm", type="date", fmt="%H:%M"),
        ],
    )
    out = profile.apply(rec)
    assert out["입찰공고번호"] == "R26BK01561738"
    assert out["계약방법"] == "제한경쟁"
    assert out["추정가격"] == "65,454,545원"
    assert out["개찰일"] == "2026. 6. 15."
    assert out["개찰시각"] == "18:00"


def test_profile_save_load_roundtrip(tmp_path):
    profile = MappingProfile(
        name="p",
        mappings=[FieldMapping("추정가격", "presmptPrce", type="amount", fmt="{:,}")],
    )
    path = tmp_path / "profile.json"
    profile.save(path)
    loaded = MappingProfile.load(path)
    assert loaded.name == "p"
    m = loaded.mappings[0]
    assert m.template_field == "추정가격"
    assert m.source == "presmptPrce"
    assert m.type == "amount"
    assert m.fmt == "{:,}"


def test_explicit_blank_is_covered_but_not_emitted_and_roundtrips(tmp_path):
    profile = MappingProfile(mappings=[
        FieldMapping("공고명", "bidNtceNm"),
        FieldMapping("비고", type="blank"),
    ])
    assert profile.template_fields() == ["공고명"]
    assert profile.mapped_fields() == ["공고명"]
    assert profile.blank_fields() == ["비고"]
    assert profile.cover_fields() == ["공고명", "비고"]
    assert profile.apply({"bidNtceNm": "입찰"}) == {"공고명": "입찰"}

    path = tmp_path / "blank.json"
    profile.save(path)
    loaded = MappingProfile.load(path)
    assert loaded.blank_fields() == ["비고"]
    assert loaded.apply({"bidNtceNm": "입찰"}) == {"공고명": "입찰"}


def test_mapped_and_blank_duplicate_is_reported_as_conflict():
    profile = MappingProfile(mappings=[
        FieldMapping("공고명", "name"),
        FieldMapping("공고명", type="blank"),
    ])
    assert profile.coverage_conflicts() == ["공고명"]


def test_from_dict_rejects_unknown_type():
    """RC-10 회귀: 직렬화 경계(from_dict)가 오타·버전 스큐 type 을 시끄럽게 거부."""
    with pytest.raises(ValueError, match="amonut"):
        FieldMapping.from_dict({"template_field": "추정가격", "type": "amonut"})


def test_from_dict_accepts_all_supported_types_and_blank():
    """지원 유형 전부 + 내부 마커 blank 는 종전대로 로드된다."""
    for t in (*TYPES, "blank"):
        assert FieldMapping.from_dict({"template_field": "f", "type": t}).type == t


def test_to_dict_from_dict_roundtrip_lossless():
    m = FieldMapping("추정가격", "presmptPrce", type="amount", const="", fmt="{:,}")
    back = FieldMapping.from_dict(m.to_dict())
    assert (back.template_field, back.source, back.type, back.const, back.fmt) == (
        "추정가격", "presmptPrce", "amount", "", "{:,}",
    )


def test_profile_load_rejects_unknown_type(tmp_path):
    """손 편집된 매핑 파일의 미지 type 은 로드 시점에 ValueError — 조용한 주입 금지."""
    path = tmp_path / "typo.json"
    path.write_text(json.dumps({"name": "t", "mappings": [{
        "template_field": "추정가격", "source": "presmptPrce", "type": "amonut",
    }]}, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="지원하지 않는 유형"):
        MappingProfile.load(path)


def test_missing_type_defaults_to_text_not_blank():
    """type 생략은 값 매핑 text literal 이며 blank 선언이 아니다."""
    loaded = MappingProfile.from_dict({"mappings": [{
        "template_field": "비고", "source": ""
    }]})
    assert loaded.mappings[0].type == "text"
    assert not loaded.mappings[0].is_blank
    assert loaded.blank_fields() == []
    assert loaded.apply({}) == {"비고": ""}


# ------------------------------------------------- 통합: API 레코드 → 실 템플릿 채우기
def test_end_to_end_api_record_fills_real_template(tmp_path):
    """나라장터 레코드 → 프로파일 → 실제 입찰공고 템플릿 생성. 값이 주입된다."""
    template = str(CORPUS / "bid_notice_limited_under100m.hwpx")
    rec = _nara_record()
    profile = MappingProfile(
        mappings=[
            FieldMapping("입찰공고번호", "bidNtceNo"),
            FieldMapping("공고명", "bidNtceNm"),
            FieldMapping("계약방법", "cntrctCnclsMthdNm"),
            FieldMapping("추정가격", "presmptPrce", type="amount"),
            FieldMapping("개찰일시", "opengDate", type="date"),
        ]
    )
    data = profile.apply(rec)
    out = tmp_path / "generated.hwpx"
    result = HwpxEngine().generate(template, data, str(out))

    assert result.ok
    assert {"입찰공고번호", "공고명", "추정가격", "개찰일시"} <= result.applied
    # 생성물에 변환된 값이 실제로 들어갔는지 바이트로 확인.
    pkg = HwpxPackage.open(str(out))
    text = b"".join(pkg.entries[n] for n in pkg.content_xml_names()).decode("utf-8")
    assert "R26BK01561738" in text
    assert "65,454,545원" in text
    assert "2026. 6. 15." in text
