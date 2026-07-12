"""매핑 계층 테스트 — 변환·자동제안·프로파일 저장/적용 + 실 API 레코드 통합.

소스 필드명은 실제 나라장터 표준 응답 키(bidNtceNo·bidBeginDate+bidBeginTm·presmptPrce)
를 쓴다 — 매핑 설계를 실데이터 형태에 근거해 검증한다.
"""

from __future__ import annotations

import json
from pathlib import Path

from hwpxfiller.core.engine import HwpxEngine
from hwpxfiller.core.mapping import (
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


# ------------------------------------------------------------------ 변환
def test_transform_datetime_composes_date_and_time():
    """N→1 합성: 날짜+시각 두 소스 키 → 한글 일시 문자열."""
    assert apply_transform("datetime", ["2017-01-04", "09:00"]) == "2017년 1월 4일 09:00"


def test_transform_amount_formats_number():
    assert apply_transform("amount", ["21326800"]) == "21,326,800원"


def test_transform_join_and_const():
    assert apply_transform("join", ["가", "나"], sep="-") == "가-나"
    assert apply_transform("const", [], const="수의계약") == "수의계약"


def test_transform_amount_graceful_on_nonnumeric():
    assert apply_transform("amount", ["미정"]) == "미정"


# ------------------------------------------------------------- FieldMapping.value
def test_field_mapping_composes_from_record():
    rec = _nara_record()
    fm = FieldMapping("개찰일시", ["opengDate", "opengTm"], transform="datetime")
    assert fm.value_for(rec) == "2026년 6월 15일 18:00"


# ------------------------------------------------------------------ 자동 제안
def test_suggest_matches_exact_aliases():
    """영문 소스 키라도 alias 사전 경유 퍼지로 명확한 필드는 자동 제안된다."""
    template = ["입찰공고번호", "공고명", "추정가격"]
    source_keys = list(NARA_ALIASES)
    sugg = {m.template_field: m.sources[0] for m in suggest_mappings(template, source_keys, NARA_ALIASES)}
    assert sugg["입찰공고번호"] == "bidNtceNo"
    assert sugg["공고명"] == "bidNtceNm"
    assert sugg["추정가격"] == "presmptPrce"


def test_suggest_respects_threshold():
    """유사도가 임계 미만이면 제안하지 않는다(잘못 꽂지 않음 — 사람 확정 대기)."""
    sugg = suggest_mappings(["존재하지않는들판xyz"], list(NARA_ALIASES), NARA_ALIASES, threshold=0.6)
    assert sugg == []


def test_suggest_is_one_to_one_draft():
    """제안은 1:1 초안 — 일시 같은 N→1 합성은 사람이 두 번째 소스를 덧붙인다."""
    sugg = suggest_mappings(["입찰개시일시"], list(NARA_ALIASES), NARA_ALIASES)
    # 날짜 쪽으로 1:1 제안(시각은 사람이 추가).
    assert len(sugg) == 1 and sugg[0].sources == ["bidBeginDate"]


def test_suggest_without_source_vocabulary_matches_raw_keys():
    """어휘 없는 소스(Excel/CSV — 헤더가 이미 사람 라벨)는 원 키에 직접 퍼지 매칭한다.

    나라장터 어휘가 모든 소스에 강요되지 않음을 못박는다(V1 GUI 기본 alias 제거):
    한글 헤더 소스는 aliases 없이도 초안이 잡히고, 영문 코드 소스는 aliases 없이는
    한글 필드와 안 맞아 초안이 없다(코어는 어휘를 몰래 얹지 않는다).
    """
    # 한글 헤더 Excel 소스 — aliases 없이 직접 매칭.
    sugg = suggest_mappings(["공고명", "추정가격"], ["공고명", "추정가격", "비고"])
    pairs = {m.template_field: m.sources[0] for m in sugg}
    assert pairs == {"공고명": "공고명", "추정가격": "추정가격"}
    # 영문 코드 소스 — 나라 어휘를 강요하지 않으면 한글 필드와 안 맞아 초안 없음.
    assert suggest_mappings(["공고명"], ["bidNtceNm"]) == []


# ------------------------------------------------------------- 프로파일 저장/적용
def test_profile_apply_produces_template_dict():
    rec = _nara_record()
    profile = MappingProfile(
        name="나라장터표준→입찰공고",
        mappings=[
            FieldMapping("입찰공고번호", ["bidNtceNo"]),
            FieldMapping("계약방법", ["cntrctCnclsMthdNm"]),
            FieldMapping("추정가격", ["presmptPrce"], transform="amount"),
            FieldMapping("개찰일시", ["opengDate", "opengTm"], transform="datetime"),
        ],
    )
    out = profile.apply(rec)
    assert out["입찰공고번호"] == "R26BK01561738"
    assert out["계약방법"] == "제한경쟁"
    assert out["추정가격"] == "65,454,545원"
    assert out["개찰일시"] == "2026년 6월 15일 18:00"


def test_profile_save_load_roundtrip(tmp_path):
    profile = MappingProfile(
        name="p", mappings=[FieldMapping("개찰일시", ["opengDate", "opengTm"], transform="datetime")]
    )
    path = tmp_path / "profile.json"
    profile.save(path)
    loaded = MappingProfile.load(path)
    assert loaded.name == "p"
    assert loaded.mappings[0].template_field == "개찰일시"
    assert loaded.mappings[0].sources == ["opengDate", "opengTm"]
    assert loaded.mappings[0].transform == "datetime"


# ------------------------------------------------- 통합: API 레코드 → 실 템플릿 채우기
def test_end_to_end_api_record_fills_real_template(tmp_path):
    """나라장터 레코드 → 프로파일 → 실제 입찰공고 템플릿 생성. 값이 주입된다."""
    template = str(CORPUS / "bid_notice_limited_under100m.hwpx")
    rec = _nara_record()
    profile = MappingProfile(
        mappings=[
            FieldMapping("입찰공고번호", ["bidNtceNo"]),
            FieldMapping("공고명", ["bidNtceNm"]),
            FieldMapping("계약방법", ["cntrctCnclsMthdNm"]),
            FieldMapping("추정가격", ["presmptPrce"], transform="amount"),
            FieldMapping("개찰일시", ["opengDate", "opengTm"], transform="datetime"),
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
    assert "2026년 6월 15일 18:00" in text
