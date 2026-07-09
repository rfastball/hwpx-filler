"""매핑 행 상태 모델 테스트 — Qt 불필요(헤드리스).

핵심 회귀는 **명시성 게이트**: 자동 초안이 채워져 있어도 사람이 전 행을 확정하기
전에는 ``is_complete()`` 가 False 여야 한다. 이 게이트가 기능의 존재 이유다.
"""

from __future__ import annotations

import json
from pathlib import Path

from hwpxfiller.core.mapping import NARA_ALIASES, MappingProfile, apply_transform
from hwpxfiller.core.schema import FieldSpec, TemplateSchema
from hwpxfiller.gui.mapping_state import MappingModel, RowState

FIXTURES = Path(__file__).parent / "fixtures"


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


def test_confirm_all_and_unconfirm_all():
    model = _model()
    model.confirm_all()
    assert model.is_complete()
    model.unconfirm_all()
    assert not model.is_complete()
    assert all(not r.confirmed for r in model.rows)


# ------------------------------------------------------------------ to_profile
def test_to_profile_includes_only_confirmed_rows_with_content():
    """미확정 행(초안 존재해도)과 비움 확정 행은 프로파일에서 제외."""
    model = _model()
    rows = {r.template_field: i for i, r in enumerate(model.rows)}
    model.set_confirmed(rows["입찰공고번호"])       # 확정 + 소스 있음 → 포함
    model.set_confirmed(rows["존재하지않는들판xyz"])  # 비움 확정 → 제외
    # 공고명·추정가격·개찰일시는 초안이 있어도 미확정 → 제외
    profile = model.to_profile("p")
    assert profile.name == "p"
    assert profile.template_fields() == ["입찰공고번호"]


def test_to_profile_includes_confirmed_const_row_without_sources():
    """소스 없이 상수만 있는 확정 행도 내용 있는 매핑이다."""
    model = MappingModel(rows=[RowState("계약방법", transform="const", const="수의계약")])
    model.set_confirmed(0)
    profile = model.to_profile()
    assert profile.template_fields() == ["계약방법"]
    assert profile.apply({}) == {"계약방법": "수의계약"}


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
