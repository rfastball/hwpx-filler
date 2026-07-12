"""매핑 행 상태 모델 테스트 — Qt 불필요(헤드리스).

핵심 회귀는 **명시성 게이트**: 자동 초안이 채워져 있어도 사람이 전 행을 확정하기
전에는 ``is_complete()`` 가 False 여야 한다. 이 게이트가 기능의 존재 이유다.
"""

from __future__ import annotations

import json
from pathlib import Path

from hwpxfiller.core.mapping import FieldMapping, MappingProfile, apply_transform
from hwpxfiller.core.schema import FieldSpec, TemplateSchema
from hwpxfiller.data.nara import NaraStdDataSource
from hwpxfiller.gui.mapping_state import MappingModel, RowState

FIXTURES = Path(__file__).parent / "fixtures"

# 어휘는 이제 소스가 소유한다(코어 아님) — V1 승격 후 새 출처.
NARA_ALIASES = NaraStdDataSource.field_labels()


def _nara_record() -> dict:
    """실 라이브 응답 픽스처의 첫 레코드(envelope response.body.items[0])."""
    env = json.loads((FIXTURES / "nara_std_response.json").read_text(encoding="utf-8"))
    return env["response"]["body"]["items"][0]


def _schema() -> TemplateSchema:
    """매칭 4필드 + 미매칭 1필드의 소형 스키마(문서 등장 순서)."""
    return TemplateSchema(
        fields=[
            FieldSpec("입찰공고번호", "number", 1, False, "공고번호:"),
            FieldSpec("공고명", "text", 1, False),
            FieldSpec("추정가격", "amount", 1, True),
            FieldSpec("개찰일시", "date", 1, True),
            FieldSpec("존재하지않는들판xyz", "text", 1, False),
        ]
    )


def _model() -> MappingModel:
    return MappingModel.from_suggestions(_schema(), list(NARA_ALIASES), NARA_ALIASES)


# ------------------------------------------------------------ from_suggestions
def test_from_suggestions_creates_row_for_every_field_in_document_order():
    """미매칭 필드 포함 전 필드에 행 생성 — 문서 순서 유지."""
    model = _model()
    assert [r.template_field for r in model.rows] == [
        "입찰공고번호", "공고명", "추정가격", "개찰일시", "존재하지않는들판xyz",
    ]
    rows = {r.template_field: r for r in model.rows}
    assert rows["입찰공고번호"].sources == ["bidNtceNo"]
    assert rows["공고명"].sources == ["bidNtceNm"]
    assert rows["추정가격"].sources == ["presmptPrce"]
    # 미매칭 필드도 빈 행으로 존재(제안 없음 → 점수 0).
    assert rows["존재하지않는들판xyz"].sources == []
    assert rows["존재하지않는들판xyz"].suggestion_score == 0.0
    # 제안 행은 신뢰도 점수를 갖는다(뷰 툴팁용).
    assert rows["입찰공고번호"].suggestion_score > 0.6


def test_from_suggestions_default_transform_follows_inferred_type():
    """date→datetime, amount→amount, 그 외→join."""
    rows = {r.template_field: r for r in _model().rows}
    assert rows["개찰일시"].transform == "datetime"
    assert rows["추정가격"].transform == "amount"
    assert rows["공고명"].transform == "join"
    assert rows["입찰공고번호"].transform == "join"  # number 도 join


def test_from_suggestions_all_rows_start_unconfirmed():
    """초안이 채워져 있어도 확정은 사람 몫 — 전 행 confirmed=False 시작."""
    model = _model()
    assert all(not r.confirmed for r in model.rows)
    assert not model.is_complete()


# --------------------------------------------------------- 명시성 게이트 회귀
def test_is_complete_requires_every_single_row_confirmed():
    """한 행이라도 미확정이면 False, 전부 확정해야 True."""
    model = _model()
    for i in range(len(model.rows) - 1):
        model.set_confirmed(i)
    assert not model.is_complete()  # 마지막 1행이 미확정
    model.set_confirmed(len(model.rows) - 1)  # 비움 확정도 확정이다
    assert model.is_complete()


def test_is_complete_false_on_empty_model():
    assert not MappingModel().is_complete()


def test_editing_a_confirmed_row_resets_confirmation():
    """확정 후 소스/변환/구분자/상수를 바꾸면 재확정 필요."""
    model = _model()
    model.confirm_all()
    model.set_sources(0, ["bidNtceNo", "bidNtceOrd"])
    assert not model.rows[0].confirmed
    model.set_confirmed(0)
    model.set_transform(0, "join")
    assert not model.rows[0].confirmed
    model.set_confirmed(0)
    model.set_sep(0, "-")
    assert not model.rows[0].confirmed
    model.set_confirmed(0)
    model.set_const(0, "고정값")
    assert not model.rows[0].confirmed


def test_emits_any_value_false_when_all_rows_blank_confirmed():
    """RC-08 회귀: 전부 비움 확정은 is_complete 통과 + mappings 비지 않음 — 그래도
    실제 값은 하나도 방출하지 않으므로 '전부 비움' 저장 가드 질의는 False 다."""
    model = MappingModel(rows=[RowState("공고명"), RowState("비고")])
    model.confirm_all()
    assert model.is_complete()
    assert model.to_profile().mappings          # blank 도 영속화(L1) — 옛 술어의 함정
    assert not model.to_profile().template_fields()
    assert not model.emits_any_value()


def test_emits_any_value_true_when_any_confirmed_row_has_content():
    """소스 행 또는 상수 행이 하나라도 확정되면 값이 방출된다 — 가드 통과."""
    model = MappingModel(rows=[RowState("공고명"), RowState("비고")])
    model.set_sources(0, ["bidNtceNm"])
    model.confirm_all()
    assert model.emits_any_value()
    const_model = MappingModel(rows=[RowState("계약방법", transform="const", const="수의계약")])
    const_model.set_confirmed(0)
    assert const_model.emits_any_value()


def test_emits_any_value_ignores_unconfirmed_content():
    """미확정 행은 to_profile 에서 제외되므로 내용이 있어도 방출로 세지 않는다."""
    model = MappingModel(rows=[RowState("공고명", sources=["bidNtceNm"])])
    assert not model.emits_any_value()


def test_confirm_all_and_unconfirm_all():
    model = _model()
    model.confirm_all()
    assert model.is_complete()
    model.unconfirm_all()
    assert not model.is_complete()
    assert all(not r.confirmed for r in model.rows)


# --------------------------------------------------- 대량 확정 게이트(UD-05, 링1)
def test_confirm_content_rows_leaves_unmatched_blank_rows_unconfirmed():
    """'모두 확정'의 내용-행 단계: 내용 있는 행만 확정, 미매칭 빈 행은 미확정 유지."""
    model = _model()  # 4 매칭(내용) + 1 미매칭(빈) 행
    n = model.confirm_content_rows()
    assert n == 4                       # 내용 있는 4행만 새로 확정
    assert not model.is_complete()      # 미매칭 빈 행이 남아 게이트 닫힘
    rows = {r.template_field: r for r in model.rows}
    assert rows["입찰공고번호"].confirmed
    assert not rows["존재하지않는들판xyz"].confirmed
    # 재호출은 이미 확정된 행을 다시 세지 않는다(증분 반환).
    assert model.confirm_content_rows() == 0


def test_unconfirmed_blank_fields_lists_only_empty_unconfirmed_rows():
    model = _model()
    assert model.unconfirmed_blank_fields() == ["존재하지않는들판xyz"]
    # 내용 있는 행을 비움 확정 후보로 오해하지 않는다.
    model.confirm_content_rows()
    assert model.unconfirmed_blank_fields() == ["존재하지않는들판xyz"]


def test_confirm_fields_promotes_named_blanks_and_completes_gate():
    """이름으로 재진술·확인된 미매칭 빈 필드만 확정 → 전 행 확정 시 게이트 개방."""
    model = _model()
    model.confirm_content_rows()
    blanks = model.unconfirmed_blank_fields()
    assert model.confirm_fields(blanks) == 1
    assert model.is_complete()
    # 존재하지 않는 이름은 무시(우발 확정 없음).
    assert model.confirm_fields(["없는필드"]) == 0


def test_confirmed_count_tracks_confirmations():
    model = _model()
    assert model.confirmed_count() == 0
    model.confirm_content_rows()
    assert model.confirmed_count() == 4


# ------------------------------------------------------------------ to_profile
def test_to_profile_includes_confirmed_rows_and_persists_blank_intent():
    """미확정 행은 제외하고 비움 확정 행은 명시적 blank 선언으로 저장."""
    model = _model()
    rows = {r.template_field: i for i, r in enumerate(model.rows)}
    model.set_confirmed(rows["입찰공고번호"])       # 확정 + 소스 있음 → 포함
    model.set_confirmed(rows["존재하지않는들판xyz"])  # 비움 확정 → blank 선언
    # 공고명·추정가격·개찰일시는 초안이 있어도 미확정 → 제외
    profile = model.to_profile("p")
    assert profile.name == "p"
    assert profile.template_fields() == ["입찰공고번호"]
    assert profile.blank_fields() == ["존재하지않는들판xyz"]
    assert profile.cover_fields() == ["입찰공고번호", "존재하지않는들판xyz"]
    assert profile.apply(_nara_record()) == {"입찰공고번호": "R26BK01561738"}


def test_to_profile_includes_confirmed_const_row_without_sources():
    """소스 없이 상수만 있는 확정 행도 내용 있는 매핑이다."""
    model = MappingModel(rows=[RowState("계약방법", transform="const", const="수의계약")])
    model.set_confirmed(0)
    profile = model.to_profile()
    assert profile.template_fields() == ["계약방법"]
    assert profile.apply({}) == {"계약방법": "수의계약"}


def test_apply_profile_restores_explicit_blank_and_roundtrips():
    profile = MappingProfile(mappings=[FieldMapping("비고", ["malformed"], transform="blank")])
    model = MappingModel(rows=[RowState("비고")])
    assert model.apply_profile(profile) == 1
    row = model.rows[0]
    assert row.confirmed and row.is_empty_confirmed()
    assert row.sources == [] and row.transform == "join"
    restored = model.to_profile()
    assert restored.blank_fields() == ["비고"]
    assert restored.apply({}) == {}


def test_blank_is_internal_marker_not_selectable_transform():
    from hwpxfiller.core.mapping import TRANSFORMS

    assert "blank" not in TRANSFORMS


def test_from_profile_malformed_blank_does_not_leak_source_vocabulary():
    profile = MappingProfile(mappings=[
        FieldMapping("공고명", ["name"]),
        FieldMapping("비고", ["ghost_source"], transform="blank"),
    ])
    model = MappingModel.from_profile(profile)
    assert model.source_fields == ["name"]
    blank = {r.template_field: r for r in model.rows}["비고"]
    assert blank.sources == [] and blank.transform == "join" and blank.is_empty_confirmed()


# --------------------------------------------------------------------- preview
def test_preview_amount_and_datetime_match_apply_transform():
    """미리보기 값은 apply_transform 과 정확히 일치해야 한다(WYSIWYG)."""
    model = MappingModel(
        rows=[
            RowState("추정가격", sources=["presmptPrce"], transform="amount"),
            RowState("개찰일시", sources=["opengDate", "opengTm"], transform="datetime"),
        ]
    )
    record = {"presmptPrce": "21326800", "opengDate": "2026-06-15", "opengTm": "18:00"}
    out = model.preview(record)
    assert out["추정가격"] == apply_transform("amount", ["21326800"]) == "21,326,800원"
    assert (
        out["개찰일시"]
        == apply_transform("datetime", ["2026-06-15", "18:00"])
        == "2026년 6월 15일 18:00"
    )


def test_display_format_choice_changes_preview():
    """같은 amount 라도 표시형 코드(fmt)에 따라 보일 형태가 달라진다(Excel 셀서식 격)."""
    model = MappingModel(rows=[RowState("추정가격", sources=["presmptPrce"], transform="amount")])
    rec = {"presmptPrce": "21326800"}
    assert model.preview(rec)["추정가격"] == "21,326,800원"  # 기본(빈 코드)
    model.set_fmt(0, "{:,}")
    assert model.preview(rec)["추정가격"] == "21,326,800"    # 숫자만
    # 표시형 편집은 확정을 해제한다(사람 눈 재확인).
    model.set_confirmed(0)
    model.set_fmt(0, "")
    assert not model.rows[0].confirmed


def test_datetime_custom_code_format():
    model = MappingModel(rows=[RowState("개찰일시", sources=["d"], transform="datetime", fmt="%Y-%m-%d")])
    assert model.preview({"d": "2026-6-5"})["개찰일시"] == "2026-06-05"


def test_phone_mask_via_join_transform():
    """평문(join) 변환 + 마스크 표시형 — 전화번호 자릿수 그룹."""
    model = MappingModel(rows=[RowState("연락처", sources=["tel"], transform="join", fmt="phone")])
    assert model.preview({"tel": "01012345678"})["연락처"] == "010-1234-5678"


def test_changing_transform_resets_format_code():
    """변환을 바꾸면 이전 표시형 코드는 무효 → 기본으로 리셋."""
    model = MappingModel(rows=[RowState("x", sources=["a"], transform="amount", fmt="{:,}")])
    model.set_transform(0, "datetime")
    assert model.rows[0].fmt == ""


def test_profile_roundtrip_preserves_format(tmp_path):
    """저장→로드가 표시형 코드(fmt)를 보존한다(구 프로파일 호환: 없으면 기본)."""
    model = MappingModel(rows=[RowState("추정가격", sources=["presmptPrce"], transform="amount", fmt="{:,}")])
    model.set_confirmed(0)
    path = tmp_path / "p.json"
    model.to_profile().save(path)
    loaded = MappingProfile.load(path)
    assert loaded.mappings[0].fmt == "{:,}"
    assert loaded.apply({"presmptPrce": "21326800"})["추정가격"] == "21,326,800"


def test_preview_covers_unmapped_rows_as_empty():
    model = _model()
    out = model.preview(_nara_record())
    assert out["존재하지않는들판xyz"] == ""
    assert out["입찰공고번호"] == "R26BK01561738"


# --------------------------------------------------------------- preview_empties
def test_preview_empties_flags_content_mapped_but_empty_for_record():
    """소스는 매핑됐으나 이 레코드에 그 키의 값이 없으면 빈값으로 신고."""
    model = MappingModel(
        rows=[
            RowState("공고명", sources=["bidNtceNm"]),      # 값 있음
            RowState("추정가격", sources=["presmptPrce"]),  # 이 레코드엔 값 없음
        ]
    )
    empties = model.preview_empties({"bidNtceNm": "테스트 공고"})
    assert empties == ["추정가격"]


def test_preview_empties_excludes_intentionally_empty_rows():
    """내용 없는 행(의도적 비움)은 빈값 신고 대상이 아니다."""
    model = MappingModel(
        rows=[
            RowState("공고명", sources=["bidNtceNm"]),  # 값 없음 → 신고
            RowState("여백"),                            # 내용 자체 없음 → 제외
        ]
    )
    assert model.preview_empties({}) == ["공고명"]


def test_preview_counts_three_states_sum_to_total():
    """UD-27 — (채움, 빈 값, 미매핑)의 합이 언제나 전체 행 수와 일치."""
    model = MappingModel(
        rows=[
            RowState("공고명", sources=["bidNtceNm"]),   # 값 있음 → 채움
            RowState("추정가격", sources=["presmptPrce"]),  # 이 레코드엔 값 없음 → 빈 값
            RowState("여백"),                             # 내용 없음 → 미매핑
            RowState("비고"),                             # 내용 없음 → 미매핑
        ]
    )
    filled, empty_n, unmapped = model.preview_counts({"bidNtceNm": "테스트 공고"})
    assert (filled, empty_n, unmapped) == (1, 1, 2)
    assert filled + empty_n + unmapped == len(model.rows)  # 어떤 필드도 무집계 아님


def test_is_schema_only_true_only_when_no_source_fields():
    """UD-28 — 연결된 데이터 소스 필드가 0개면 스키마온리(데이터 미연결) 세션이다.

    뷰가 빈 행 빨강 '미매칭'을 중립으로 강등하는 근거(링1, Qt 비의존). 데이터가
    연결된 세션(source_fields 有)에선 False 라야 미매칭 빨강이 살아 있다.
    """
    schema_only = MappingModel(
        rows=[RowState("공고명"), RowState("추정가격")], source_fields=[]
    )
    assert schema_only.is_schema_only() is True

    connected = MappingModel(
        rows=[RowState("공고명")], source_fields=["bidNtceNm"]
    )
    assert connected.is_schema_only() is False


# --------------------------------------------------------------- apply_profile
def test_apply_profile_roundtrip_restores_confirmed_state(tmp_path):
    """저장 → 로드 라운드트립: 일치 행은 값 복원 + 확정 도착, 나머지는 미확정 유지."""
    model = _model()
    rows = {r.template_field: i for i, r in enumerate(model.rows)}
    # 사람이 개찰일시에 시각 소스를 덧붙이고(N→1) 두 행을 확정.
    model.set_sources(rows["개찰일시"], ["opengDate", "opengTm"])
    model.set_confirmed(rows["개찰일시"])
    model.set_confirmed(rows["추정가격"])
    path = tmp_path / "profile.json"
    model.to_profile("나라장터표준").save(path)

    fresh = _model()
    assert not fresh.is_complete()
    applied = fresh.apply_profile(MappingProfile.load(path))
    assert applied == 2
    frows = {r.template_field: r for r in fresh.rows}
    assert frows["개찰일시"].confirmed
    assert frows["개찰일시"].sources == ["opengDate", "opengTm"]
    assert frows["개찰일시"].transform == "datetime"
    assert frows["추정가격"].confirmed
    # 프로파일에 없는 필드는 미확정 유지 — 게이트는 여전히 닫혀 있다.
    assert not frows["공고명"].confirmed
    assert not fresh.is_complete()


# ------------------------------------------------- 실 픽스처: 영문키→한글 초안
def test_real_fixture_record_keys_produce_korean_field_drafts():
    """실 나라장터 레코드 키 + NARA_ALIASES 로 한글 템플릿 필드 초안이 잡힌다."""
    schema = TemplateSchema(
        fields=[
            FieldSpec("입찰공고번호", "number", 1, False),
            FieldSpec("공고명", "text", 1, False),
            FieldSpec("추정가격", "amount", 1, False),
        ]
    )
    record = _nara_record()
    model = MappingModel.from_suggestions(schema, sorted(record), NARA_ALIASES)
    rows = {r.template_field: r for r in model.rows}
    assert rows["입찰공고번호"].sources == ["bidNtceNo"]
    assert rows["공고명"].sources == ["bidNtceNm"]
    assert rows["추정가격"].sources == ["presmptPrce"]
    # 초안 그대로 확정하면 실레코드 값이 나온다.
    model.confirm_all()
    out = model.to_profile().apply(record)
    assert out["입찰공고번호"] == "R26BK01561738"
    assert out["추정가격"] == "65,454,545원"
