"""매핑 계층 테스트 — 단일 소스 값 유형·자동제안·프로파일 저장/적용 + 실 API 레코드 통합.

소스 필드명은 실제 나라장터 표준 응답 키(bidNtceNo·opengDate·opengTm·presmptPrce)를
쓴다 — 매핑 설계를 실데이터 형태에 근거해 검증한다. 엄격한 1:1: 한 필드는 한 소스 키.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.domain.lint import similarity
from hwpxfiller.domain.format_engine import presets
from hwpxfiller.domain.mapping import (
    SOURCE_CARRIER_TYPES,
    SUGGEST_THRESHOLD,
    TYPES,
    FieldMapping,
    MappingProfile,
    apply_transform,
    suggest_mappings,
)
from hwpxfiller.data.nara import NaraStdDataSource
from hwpxfiller.external.hwpx_package_io import read_hwpx_package
from hwpxfiller.external.mapping_store import load_mapping_profile, save_mapping_profile

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


# ------------------------------------------------------ 오늘 날짜(today, U4-E1 #939)
_FIXED_NOW = datetime(2026, 6, 15, 18, 4)


def test_today_reuses_every_date_preset_losslessly():
    """판정 1: today 는 date 서식 어휘·프리셋 9개를 **그대로** 재사용한다.

    직렬화(``%Y-%m-%d %H:%M``)를 ``parse_dt`` 가 연·월·일·시·분 전부 되읽으므로 date 와
    같은 코드가 같은 결과를 낸다 — 새 서식 표를 만들 근거가 없다는 것이 이 단언이다.
    """
    assert [code for _, code in presets("today")] == [
        code for _, code in presets("date")
    ]
    for _, code in presets("today"):
        assert apply_transform("today", fmt=code, now=_FIXED_NOW) == apply_transform(
            "date", "2026-06-15 18:04", fmt=code
        )


def test_today_preset_values_are_pinned():
    """대표 프리셋의 실제 산출 — 어휘 재사용이 '같은 값'을 뜻함을 값으로 못박는다."""
    assert apply_transform("today", now=_FIXED_NOW) == "2026. 6. 15. 18:04"
    assert apply_transform("today", fmt="y2", now=_FIXED_NOW) == "'26.6.15. 18:04"
    assert apply_transform("today", fmt="kor", now=_FIXED_NOW) == "2026년 6월 15일 18:04"
    assert apply_transform("today", fmt="%Y-%m-%d", now=_FIXED_NOW) == "2026-06-15"
    assert apply_transform("today", fmt="%H:%M", now=_FIXED_NOW) == "18:04"


def test_today_ignores_source_value_and_const():
    """today 는 데이터 열도 고정값도 읽지 않는다 — 값의 출처는 실행 시각 하나다."""
    assert apply_transform(
        "today", value="2001-01-01", const="무시", now=_FIXED_NOW
    ) == "2026. 6. 15. 18:04"


def test_today_falls_back_to_run_clock_when_now_omitted():
    """now 미지정 폴백은 **지금**이다(direct_plan 의 'now=None 은 생성 시각' 선례)."""
    assert apply_transform("today", fmt="%Y-%m-%d") == datetime.now().strftime("%Y-%m-%d")


def test_today_is_not_a_source_carrier():
    """판정 2 짝: today 는 원본 열을 나르지 않는다 — 파일명 식별 요약 토큰 모드가
    빈 source 를 '이 열을 나른다'로 오분류하면 구별 열이 침묵 배제된다."""
    assert "today" not in SOURCE_CARRIER_TYPES
    assert "const" not in SOURCE_CARRIER_TYPES
    assert set(SOURCE_CARRIER_TYPES) == {"text", "date", "amount"}


def test_today_field_mapping_and_profile_share_one_now():
    """value_for·apply·apply_all 이 같은 now 를 관통한다(RC-02: 한 배치 = 한 시각)."""
    m = FieldMapping("작성일", type="today", fmt="%Y-%m-%d %H:%M")
    assert m.value_for({}, now=_FIXED_NOW) == "2026-06-15 18:04"
    profile = MappingProfile(mappings=[m, FieldMapping("공고명", "bidNtceNm")])
    assert profile.apply({"bidNtceNm": "입찰"}, now=_FIXED_NOW) == {
        "작성일": "2026-06-15 18:04", "공고명": "입찰",
    }
    out = profile.apply_all([{}, {}], now=_FIXED_NOW)
    assert [r["작성일"] for r in out] == ["2026-06-15 18:04"] * 2


def test_today_roundtrips_through_serialization():
    """직렬화 왕복 — 손 편집 경계 검증(from_dict)이 today 를 정상 유형으로 받는다."""
    m = FieldMapping("작성일", type="today", fmt="kor")
    back = FieldMapping.from_dict(m.to_dict())
    assert (back.type, back.fmt, back.source, back.const) == ("today", "kor", "", "")


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


# ------------------------------------------------------ 임계 캘리브레이션(#908)
# 여기가 :data:`SUGGEST_THRESHOLD` 의 **반증 코퍼스 정본**이다. 임계를 만지려는 사람은
# 두 집합을 먼저 본다: 위험 근접쌍(공유 접두 · 의미 축 상이)은 반드시 죽고, 정당한
# 표기 변형(띄어쓰기 · 앞뒤 공백 · 언더스코어 · 괄호 단위)은 반드시 산다.
#
# ``similarity`` = 공백 제거 후 ``SequenceMatcher.ratio()`` = 2*M/T (M=매칭 문자 수,
# T=두 문자열 길이 합). 아래 주석의 산술이 각 수치의 유도다.

# 죽어야 하는 쌍 — 앞머리를 공유하지만 가리키는 것이 다르다. 보증금 자리의 계약금액,
# 금액 자리의 방법처럼 그럴듯해서 더 위험하다(일괄 확정에 실린다).
RISKY_NEAR_PAIRS = [
    # 계약/금 3자 공통, 2*3/(5+4) = 0.6667 — #908 을 낸 원 결함. 이 집합의 최대값이다.
    ("계약보증금", "계약금액", 2 / 3),
    # 입찰/금 3자 공통, 2*3/(5+4) = 0.6667 — 같은 결함류(보증금 ↔ 금액 축).
    ("입찰보증금", "입찰금액", 2 / 3),
    # 공고+명/일, 2*2/(3+3) = 0.6667 — 이름 ↔ 날짜 축.
    ("공고명", "공고일", 2 / 3),
    # 금액 2자 공통, 2*2/(3+3) = 0.6667 — 선금 ↔ 잔금(정반대 뜻).
    ("선금액", "잔금액", 2 / 3),
    # 계약+대자 4자 공통, 2*4/(5+5) = 0.8 이 아니라 '계약'+'자' = 2*3/10 = 0.6.
    ("계약상대자", "계약담당자", 0.6),
    # 납품 2자 공통, 2*2/(4+4) = 0.5 — 기한 ↔ 장소.
    ("납품기한", "납품장소", 0.5),
    # 계약 2자 공통, 2*2/(4+4) = 0.5 — 일자 ↔ 금액.
    ("계약일자", "계약금액", 0.5),
]

# 살아야 하는 쌍 — 같은 것을 다르게 적었을 뿐이다.
LEGITIMATE_NOTATION_PAIRS = [
    # 공백은 similarity 가 먼저 지운다 → 정규화 후 동일 → 1.0.
    ("공고 번호", "공고번호", 1.0),
    ("계약 상대자", "계약상대자", 1.0),
    ("  계약금액  ", "계약금액", 1.0),
    ("\t수요기관\n", "수요기관", 1.0),
    # 언더스코어는 공백이 아니라 남는다: '계약금액' 4자 매칭, 2*4/(5+4) = 0.8889.
    ("계약_금액", "계약금액", 8 / 9),
    ("공고_번호", "공고번호", 8 / 9),
    # 괄호 단위 — 이 집합의 **최소값**이 임계의 상한을 정한다.
    # '추정가격(원)' = 7자, 매칭 4자 → 2*4/(7+4) = 0.7273.
    ("추정가격(원)", "추정가격", 8 / 11),
    ("계약금액(원)", "계약금액", 8 / 11),
    ("납품기한(일)", "납품기한", 8 / 11),
    ("추정가격[원]", "추정가격", 8 / 11),
    # 공백 낀 단위도 공백 제거 후 위와 동형.
    ("계약금액 (원)", "계약금액", 8 / 11),
    # 어간이 길수록 단위 주석의 비중이 줄어 점수가 오른다: 2*5/(8+5) = 0.7692.
    ("계약보증금(원)", "계약보증금", 10 / 13),
]


@pytest.mark.parametrize("a,b,expected", RISKY_NEAR_PAIRS)
def test_risky_near_pairs_score_below_the_suggest_threshold(a, b, expected):
    """의미 축이 다른 공유-접두 쌍은 임계 아래에 있어 제안되지 않는다(#908).

    수치를 먼저 못박아 임계가 아니라 ``similarity`` 가 바뀌어도 빨강이 나게 한다.
    """
    assert similarity(a, b) == pytest.approx(expected)
    assert similarity(a, b) < SUGGEST_THRESHOLD
    assert suggest_mappings([a], [b]) == []


@pytest.mark.parametrize("a,b,expected", LEGITIMATE_NOTATION_PAIRS)
def test_legitimate_notation_variants_survive_the_suggest_threshold(a, b, expected):
    """띄어쓰기·앞뒤 공백·언더스코어·괄호 단위는 같은 것의 다른 표기라 계속 제안된다."""
    assert similarity(a, b) == pytest.approx(expected)
    assert similarity(a, b) >= SUGGEST_THRESHOLD
    sugg = suggest_mappings([a], [b])
    assert [(m.template_field, m.source) for m in sugg] == [(a, b)]


def test_suggest_threshold_sits_in_the_gap_between_the_two_corpora():
    """임계는 두 코퍼스 **사이**에 있다 — 이 간극이 사라지면 임계로는 못 가른다.

    0.6667(위험 최대) < 0.7(임계) <= 0.7273(정당 최소). 어느 쪽 코퍼스에 새 쌍을
    더하다 간극이 닫히면 여기가 먼저 빨강이 되어, 수치를 완화해 결함을 다시 들이는
    대신 매칭 설계를 다시 보게 만든다.
    """
    riskiest = max(similarity(a, b) for a, b, _ in RISKY_NEAR_PAIRS)
    tamest = min(similarity(a, b) for a, b, _ in LEGITIMATE_NOTATION_PAIRS)
    assert riskiest == pytest.approx(2 / 3)
    assert tamest == pytest.approx(8 / 11)
    assert riskiest < SUGGEST_THRESHOLD <= tamest


def test_threshold_is_a_declared_constant_not_a_literal_default():
    """호출측이 옛 0.6 을 되살리지 못하게 기본값이 상수에 묶여 있다."""
    assert SUGGEST_THRESHOLD == 0.7
    assert suggest_mappings(["계약보증금"], ["계약금액"]) == []
    # 명시로 완화하면 옛 결함이 그대로 재현된다 — 임계가 실제로 이 쌍을 가른다는 증거.
    revived = suggest_mappings(["계약보증금"], ["계약금액"], threshold=0.6)
    assert [m.source for m in revived] == ["계약금액"]


def test_parenthetical_gloss_is_a_documented_limit_not_a_threshold_choice():
    """어간만큼 긴 괄호 주석은 **어떤 임계로도** 위험 근접쌍과 안 갈린다(설계 한계).

    길이비 인공물이라 정당한 변형인데도 위험쌍과 같은 구간에 겹친다. 옛 0.6 에서
    살아 있던 건 우연이고, 그때조차 더 높은 오답이 앞섰다. 지금은 제안이 없어 행이
    비고 사람이 채우거나 비움 확정한다 — 조용히 틀리는 대신 시끄럽게 빈다.
    """
    gloss = similarity("계약상대자(업체명)", "계약상대자")
    riskiest = max(similarity(a, b) for a, b, _ in RISKY_NEAR_PAIRS)
    assert gloss == pytest.approx(2 / 3)  # 2*5/(10+5)
    assert gloss <= riskiest  # 겹친다 = 분리 불가
    assert suggest_mappings(["계약상대자"], ["계약상대자(업체명)"]) == []


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
    save_mapping_profile(profile, path)
    loaded = load_mapping_profile(path)
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
    save_mapping_profile(profile, path)
    loaded = load_mapping_profile(path)
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
        load_mapping_profile(path)


def test_provenance_roundtrip_and_backward_compat():
    """작성 출처 provenance(#53-C) — 왕복 보존 + 구 JSON(키 부재)은 기본값 {}. 순수 메타라
    apply/실행 계약과 무관(실행은 여전히 mappings 만 소비)."""
    profile = MappingProfile(
        name="p",
        mappings=[FieldMapping("공고명", "bidNtceNm")],
        provenance={"template": "공고서.hwpx", "authored_at": "2026-07-17T10:00:00"},
    )
    back = MappingProfile.from_dict(profile.to_dict())
    assert back.provenance == {"template": "공고서.hwpx", "authored_at": "2026-07-17T10:00:00"}
    # 순수 메타 — 값 방출은 mappings 만으로 결정(provenance 무영향).
    assert back.apply({"bidNtceNm": "x"}) == {"공고명": "x"}

    old = {"name": "p", "mappings": []}  # provenance 필드 도입 전 JSON
    assert MappingProfile.from_dict(old).provenance == {}
    assert MappingProfile().provenance == {}


def test_provenance_rejects_corrupt_type():
    """provenance 가 dict 아니거나 축·값이 비문자열이면 loud raise(조용한 오염 금지)."""
    base = MappingProfile(name="p").to_dict()
    with pytest.raises(ValueError, match="provenance"):
        MappingProfile.from_dict({**base, "provenance": ["x"]})
    with pytest.raises(ValueError, match="문자열"):
        MappingProfile.from_dict({**base, "provenance": {"template": 5}})


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
    result = make_hwpx_engine().generate(template, data, str(out))

    assert result.ok
    assert {"입찰공고번호", "공고명", "추정가격", "개찰일시"} <= result.applied
    # 생성물에 변환된 값이 실제로 들어갔는지 바이트로 확인.
    pkg = read_hwpx_package(out)
    text = b"".join(pkg.entries[n] for n in pkg.content_xml_names()).decode("utf-8")
    assert "R26BK01561738" in text
    assert "65,454,545원" in text
    assert "2026. 6. 15." in text
