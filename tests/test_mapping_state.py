"""매핑 행 상태 모델 테스트 — Qt 불필요(헤드리스).

핵심 회귀는 **명시성 게이트**: 자동 초안이 채워져 있어도 사람이 전 행을 확정하기
전에는 ``is_complete()`` 가 False 여야 한다. 이 게이트가 기능의 존재 이유다.

엄격한 1:1: 한 템플릿 필드는 정확히 한 소스 키(``source``)에서 값을 취한다 —
N→1 결합·구분자(sep)는 없다.
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
    assert rows["입찰공고번호"].source == "bidNtceNo"
    assert rows["공고명"].source == "bidNtceNm"
    assert rows["추정가격"].source == "presmptPrce"
    # 미매칭 필드도 빈 행으로 존재(제안 없음 → 점수 0).
    assert rows["존재하지않는들판xyz"].source == ""
    assert rows["존재하지않는들판xyz"].suggestion_score == 0.0
    # 제안 행은 신뢰도 점수를 갖는다(뷰 툴팁용).
    assert rows["입찰공고번호"].suggestion_score > 0.6


def test_from_suggestions_default_type_follows_inferred_type():
    """date→date, amount→amount, 그 외→text."""
    rows = {r.template_field: r for r in _model().rows}
    assert rows["개찰일시"].type == "date"
    assert rows["추정가격"].type == "amount"
    assert rows["공고명"].type == "text"
    assert rows["입찰공고번호"].type == "text"  # number 도 text


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
    """확정 후 소스/유형/상수를 바꾸면 재확정 필요."""
    model = _model()
    model.confirm_all()
    model.set_source(0, "bidNtceOrd")
    assert not model.rows[0].confirmed
    model.set_confirmed(0)
    model.set_type(0, "text")
    assert not model.rows[0].confirmed
    model.set_confirmed(0)
    model.set_const(0, "고정값")
    assert not model.rows[0].confirmed


# ----------------------------- 구판 ignore_source(한시 존치 — 재배선 PR 에서 제거)
# 기존 에디터 표면(_apply_active)이 아직 소비하는 구판 경로의 거동 보존 가드.
def test_ignore_source_clears_only_matching_rows_and_forces_recheck():
    """소스 헤더 미사용 전환 → 그 소스를 쓰던 행만 해제(source='', confirmed=False),
    다른 매핑·확정은 불변. 반환은 영향 필드 이름(재진술 근거)."""
    model = _model()
    model.confirm_all()  # 전 행 확정
    affected = model.ignore_source("bidNtceNo")
    assert affected == ["입찰공고번호"]
    rows = {r.template_field: r for r in model.rows}
    assert rows["입찰공고번호"].source == "" and rows["입찰공고번호"].confirmed is False
    # 다른 행의 소스·확정은 그대로.
    assert rows["공고명"].source == "bidNtceNm" and rows["공고명"].confirmed is True
    assert rows["추정가격"].source == "presmptPrce" and rows["추정가격"].confirmed is True


def test_ignore_source_absent_is_noop():
    """아무 행도 안 쓰는 소스 미사용은 무영향(빈 반환·확정 불변)."""
    model = _model()
    model.confirm_all()
    assert model.ignore_source("존재안함zzz") == []
    assert all(r.confirmed for r in model.rows)


def test_ignore_source_empty_string_is_noop():
    """빈 소스("")는 무시 — const·blank·미매칭 행이 모두 source=='' 라 무더기 해제 방지(리뷰 #62)."""
    model = MappingModel(rows=[
        RowState("계약방법", type="const", const="수의계약", confirmed=True),  # source=""
        RowState("비고", confirmed=True),                                      # 미매칭 빈 행
        RowState("공고명", source="bidNtceNm", confirmed=True),
    ])
    assert model.ignore_source("") == []                 # 아무 행도 안 건드림
    assert all(r.confirmed for r in model.rows)          # 전 행 확정 불변
    assert model.rows[0].const == "수의계약"             # const 보존


# ----------------------------- 활성 소스 변화 = 칩-라이브 계약(결정 12·13)
# 신판 관문 = apply_active_sources(전집합 재계산) — 구 ignore_source(헤더별 무차별 해제)의 대체:
# 시스템 소유 행은 라이브 재제안(조용), 사람 소유 행은 소스가 꺼지면 R4 시끄러운 강등.
def _pum_model(sources: "list[str]") -> MappingModel:
    """'품명' 단일 필드 + 주어진 소스 어휘의 소형 모델(재제안 경합 시연용)."""
    schema = TemplateSchema(fields=[FieldSpec("품명", "text", 1, False)])
    return MappingModel.from_suggestions(schema, sources)


def test_apply_active_sources_resuggests_system_rows_live():
    """시스템 소유 행(미확정·미접촉)은 활성 헤더가 바뀌면 최선으로 라이브 재제안된다(결정 12).

    '품명'은 활성에 '품명'이 있으면 그것(정확), 끄면 '세부품명'(부분일치)으로 다시 선다 —
    강등이 아니라 조용한 재제안(반환 빈 목록)."""
    model = _pum_model(["품명", "세부품명"])
    assert model.rows[0].source == "품명"                  # 초기 최선(정확)
    assert model.apply_active_sources(["세부품명"]) == []   # 시스템 행 = 조용(R4 아님)
    assert model.rows[0].source == "세부품명"              # 활성 따라 재제안
    model.apply_active_sources(["품명", "세부품명"])
    assert model.rows[0].source == "품명"                  # 복귀


def test_apply_active_sources_r4_loud_demotes_human_owned_to_empty():
    """사람 소유(수동/확정) 행의 소스가 비활성이 되면 시끄러운 강등(R4) — 이름 반환 + **빈 소스**.

    강등 행을 재제안으로 채우면(다른 그럴싸한 열) 사용자가 재확정 시 원래와 다른 열로 조용히
    치환된다(리뷰 R3) — 비운 채 남겨 의식적 재선택을 강제한다(구 ignore_source 안전 거동)."""
    model = _pum_model(["품명", "세부품명"])
    model.set_source(0, "품명")                             # 수동 지정 = 사람 소유(touched)
    assert model.rows[0].touched is True
    demoted = model.apply_active_sources(["세부품명"])       # '품명' 끔 → 사람 소유가 소스 잃음
    assert demoted == ["품명"]                              # R4 시끄러운 강등(이름 재진술)
    assert model.rows[0].touched is False                  # 강등 → 시스템 소유로
    assert model.rows[0].source == ""                      # **비운 채**(재제안 치환 아님, R3)


def test_apply_active_sources_keeps_human_owned_on_active_source():
    """활성 소스를 쓰는 사람 소유 행은 그대로 둔다 — 칩 토글이 못 덮는다(결정 12)."""
    model = _pum_model(["품명", "세부품명"])
    model.set_source(0, "품명")
    model.rows[0].confirmed = True                         # 확정 = 사람 소유
    demoted = model.apply_active_sources(["품명"])          # '세부품명'만 끔(품명 행과 무관)
    assert demoted == []                                   # 강등 없음
    assert model.rows[0].source == "품명" and model.rows[0].confirmed is True


def test_revert_to_auto_full_reset_then_resuggest_single_row():
    """자동 되돌리기 = 그 행 **완전** 리셋(소스·유형·상수·표시형) + **단일 행** 재제안(리뷰 R1·R4).

    소스만 풀면 옛 type=const 가 남아 '제안' 표시인데 옛 상수를 방출하는 하이브리드가 된다
    (R1) — 갓 제안된 행과 동형이어야 한다. 재제안은 그 행만(전집합 아님, R4)."""
    model = _pum_model(["품명", "세부품명"])
    model.set_type(0, "const")                             # 사람이 상수 유형으로
    model.set_const(0, "고정문구")
    assert model.rows[0].touched is True and model.rows[0].type == "const"
    model.revert_to_auto(0)
    assert model.rows[0].touched is False
    assert model.rows[0].type == "text" and model.rows[0].const == ""   # 완전 리셋(R1)
    model.resuggest_row(0, ["품명", "세부품명"])            # 컨트롤러가 하는 단일 행 재제안(R4)
    assert model.rows[0].source == "품명"                  # 자동 최선


def test_resuggest_row_leaves_unrelated_stale_rows_untouched():
    """단일 행 재제안(revert 경로)은 무관한 stale 사람 소유 행을 강등하지 않는다(리뷰 R4).

    행 X 가 비활성 소스를 겨눈 채(touched, '데이터에 없음') 남아 있어도, 다른 행 Y 되돌리기가
    행 X 를 건드리면 안 된다 — 전집합 apply_active_sources 를 쓰면 X 가 조용히 강등됐다."""
    schema = TemplateSchema(fields=[
        FieldSpec("품명", "text", 1, False),
        FieldSpec("규격", "text", 1, False),
    ])
    model = MappingModel.from_suggestions(schema, ["품명", "규격"])
    model.set_source(0, "없는열")                           # 행 0 = 비활성 소스 겨눔(touched, stale)
    model.set_source(1, "규격")                             # 행 1 = 수동(touched)
    model.revert_to_auto(1)
    model.resuggest_row(1, ["품명", "규격"])                # 행 1만 되돌리기·재제안
    assert model.rows[0].source == "없는열" and model.rows[0].touched is True  # 행 0 불변(강등 없음)
    assert model.rows[1].source == "규격"                  # 행 1 재제안


def test_carry_profile_includes_touched_unconfirmed_rows():
    """carry_profile 은 확정 + touched 미확정 수동 편집을 담는다(리뷰 F2) — 미접촉 제안은 제외."""
    schema = TemplateSchema(fields=[
        FieldSpec("품명", "text", 1, False),
        FieldSpec("수량", "number", 1, False),
        FieldSpec("규격", "text", 1, False),
    ])
    model = MappingModel.from_suggestions(schema, ["품명", "수량", "규격"])
    model.set_source(1, "수량")                             # 수동 미확정(touched, 사람 소유)
    model.rows[0].confirmed = True                         # 확정(사람 소유)
    # 규격은 미접촉 제안(시스템 소유) → carry 제외(새 데이터 기준 재제안돼야 함).
    carried = {m.template_field for m in model.carry_profile().mappings}
    assert carried == {"품명", "수량"}


def test_confirm_all_via_apply_active_sources_still_clears_matching(tmp_path=None):
    """구 ignore_source 계약 승계 확인: 확정 행의 소스를 끄면 그 행만 해제·이름 반환, 나머지 불변."""
    model = _model()
    model.confirm_all()                                    # 전 행 확정(사람 소유)
    active = [s for s in list(NARA_ALIASES) if s != "bidNtceNo"]  # bidNtceNo 만 끔
    demoted = model.apply_active_sources(active)
    assert demoted == ["입찰공고번호"]                      # 그 소스 쓰던 확정 행만 강등
    rows = {r.template_field: r for r in model.rows}
    assert rows["공고명"].source == "bidNtceNm" and rows["공고명"].confirmed is True
    assert rows["추정가격"].source == "presmptPrce" and rows["추정가격"].confirmed is True


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
    model.set_source(0, "bidNtceNm")
    model.confirm_all()
    assert model.emits_any_value()
    const_model = MappingModel(rows=[RowState("계약방법", type="const", const="수의계약")])
    const_model.set_confirmed(0)
    assert const_model.emits_any_value()


def test_emits_any_value_ignores_unconfirmed_content():
    """미확정 행은 to_profile 에서 제외되므로 내용이 있어도 방출로 세지 않는다."""
    model = MappingModel(rows=[RowState("공고명", source="bidNtceNm")])
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


def test_to_profile_includes_confirmed_const_row_without_source():
    """소스 없이 상수만 있는 확정 행도 내용 있는 매핑이다."""
    model = MappingModel(rows=[RowState("계약방법", type="const", const="수의계약")])
    model.set_confirmed(0)
    profile = model.to_profile()
    assert profile.template_fields() == ["계약방법"]
    assert profile.apply({}) == {"계약방법": "수의계약"}


def test_apply_profile_restores_explicit_blank_and_roundtrips():
    profile = MappingProfile(mappings=[FieldMapping("비고", "malformed", type="blank")])
    model = MappingModel(rows=[RowState("비고")])
    assert model.apply_profile(profile) == 1
    row = model.rows[0]
    assert row.confirmed and row.is_empty_confirmed()
    assert row.source == "" and row.type == "text"
    restored = model.to_profile()
    assert restored.blank_fields() == ["비고"]
    assert restored.apply({}) == {}


def test_blank_is_internal_marker_not_selectable_type():
    from hwpxfiller.core.mapping import TYPES

    assert "blank" not in TYPES


def test_from_profile_malformed_blank_does_not_leak_source_vocabulary():
    profile = MappingProfile(mappings=[
        FieldMapping("공고명", "name"),
        FieldMapping("비고", "ghost_source", type="blank"),
    ])
    model = MappingModel.from_profile(profile)
    assert model.source_fields == ["name"]
    blank = {r.template_field: r for r in model.rows}["비고"]
    assert blank.source == "" and blank.type == "text" and blank.is_empty_confirmed()


# --------------------------------------------------------------------- preview
def test_preview_amount_and_date_match_apply_transform():
    """미리보기 값은 apply_transform 과 정확히 일치해야 한다(WYSIWYG). 단일 소스."""
    model = MappingModel(
        rows=[
            RowState("추정가격", source="presmptPrce", type="amount"),
            RowState("개찰시각", source="opengTm", type="date", fmt="%H:%M"),
        ]
    )
    record = {"presmptPrce": "21326800", "opengTm": "18:00"}
    out = model.preview(record)
    assert out["추정가격"] == apply_transform("amount", "21326800") == "21,326,800원"
    assert out["개찰시각"] == apply_transform("date", "18:00", fmt="%H:%M") == "18:00"


def test_display_format_choice_changes_preview():
    """같은 amount 라도 표시형 코드(fmt)에 따라 보일 형태가 달라진다(Excel 셀서식 격)."""
    model = MappingModel(rows=[RowState("추정가격", source="presmptPrce", type="amount")])
    rec = {"presmptPrce": "21326800"}
    assert model.preview(rec)["추정가격"] == "21,326,800원"  # 기본(빈 코드)
    model.set_fmt(0, "{:,}")
    assert model.preview(rec)["추정가격"] == "21,326,800"    # 숫자만
    # 표시형 편집은 확정을 해제한다(사람 눈 재확인).
    model.set_confirmed(0)
    model.set_fmt(0, "")
    assert not model.rows[0].confirmed


def test_date_custom_code_format():
    model = MappingModel(rows=[RowState("개찰일시", source="d", type="date", fmt="%Y-%m-%d")])
    assert model.preview({"d": "2026-6-5"})["개찰일시"] == "2026-06-05"


def test_phone_mask_via_text_type():
    """평문(text) 유형 + 마스크 표시형 — 전화번호 자릿수 그룹."""
    model = MappingModel(rows=[RowState("연락처", source="tel", type="text", fmt="phone")])
    assert model.preview({"tel": "01012345678"})["연락처"] == "010-1234-5678"


def test_changing_type_resets_format_code():
    """유형을 바꾸면 이전 표시형 코드는 무효 → 기본으로 리셋."""
    model = MappingModel(rows=[RowState("x", source="a", type="amount", fmt="{:,}")])
    model.set_type(0, "date")
    assert model.rows[0].fmt == ""


def test_profile_roundtrip_preserves_format(tmp_path):
    """저장→로드가 표시형 코드(fmt)를 보존한다(구 프로파일 호환: 없으면 기본)."""
    model = MappingModel(rows=[RowState("추정가격", source="presmptPrce", type="amount", fmt="{:,}")])
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
            RowState("공고명", source="bidNtceNm"),      # 값 있음
            RowState("추정가격", source="presmptPrce"),  # 이 레코드엔 값 없음
        ]
    )
    empties = model.preview_empties({"bidNtceNm": "테스트 공고"})
    assert empties == ["추정가격"]


def test_preview_empties_excludes_intentionally_empty_rows():
    """내용 없는 행(의도적 비움)은 빈값 신고 대상이 아니다."""
    model = MappingModel(
        rows=[
            RowState("공고명", source="bidNtceNm"),  # 값 없음 → 신고
            RowState("여백"),                          # 내용 자체 없음 → 제외
        ]
    )
    assert model.preview_empties({}) == ["공고명"]


def test_preview_counts_three_states_sum_to_total():
    """UD-27 — (채움, 빈 값, 미매핑)의 합이 언제나 전체 행 수와 일치."""
    model = MappingModel(
        rows=[
            RowState("공고명", source="bidNtceNm"),     # 값 있음 → 채움
            RowState("추정가격", source="presmptPrce"),  # 이 레코드엔 값 없음 → 빈 값
            RowState("여백"),                            # 내용 없음 → 미매핑
            RowState("비고"),                            # 내용 없음 → 미매핑
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
    # 사람이 개찰일시 소스를 확정하고 추정가격도 확정.
    model.set_source(rows["개찰일시"], "opengDate")
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
    assert frows["개찰일시"].source == "opengDate"
    assert frows["개찰일시"].type == "date"
    assert frows["추정가격"].confirmed
    # 프로파일에 없는 필드는 미확정 유지 — 게이트는 여전히 닫혀 있다.
    assert not frows["공고명"].confirmed
    assert not fresh.is_complete()


def test_apply_profile_require_source_skips_confirm_for_missing_column():
    """require_source: 현재 소스 어휘에 없는 컬럼을 겨눈 행은 확정 도착하지 않는다(#26 #7).

    데이터를 바꿔 이전 확정을 되살릴 때, 사라진 컬럼을 겨눈 행이 조용히 확정으로 남아
    저장 게이트를 통과하고 빈 값 문서를 찍는 함정을 봉쇄한다 — 그런 행은 미확정으로 남는다.
    """
    profile = MappingProfile(mappings=[
        FieldMapping("공고명", source="bidNtceNm"),
        FieldMapping("추정가격", source="presmptPrce"),  # 어휘에 없는 소스
    ])
    model = MappingModel(
        rows=[RowState("공고명"), RowState("추정가격")],
        source_fields=["bidNtceNm"],  # '추정가격'이 겨눌 presmptPrce 는 없음
    )
    applied = model.apply_profile(profile, require_source=True)
    rows = {r.template_field: r for r in model.rows}
    assert rows["공고명"].confirmed              # 어휘에 있는 소스 → 확정
    assert not rows["추정가격"].confirmed         # 어휘에 없는 소스 → 미확정(재검토 강제)
    assert rows["추정가격"].source == "presmptPrce"  # 값은 복원(loud 표면화용)
    assert applied == 1                          # 확정 도착 1개만
    assert not model.is_complete()               # 저장 게이트 닫힘
    # 기본(require_source=False)은 종전대로 일치 행 전부 확정.
    model2 = MappingModel(
        rows=[RowState("공고명"), RowState("추정가격")], source_fields=["bidNtceNm"])
    assert model2.apply_profile(profile) == 2


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
    assert rows["입찰공고번호"].source == "bidNtceNo"
    assert rows["공고명"].source == "bidNtceNm"
    assert rows["추정가격"].source == "presmptPrce"
    # 초안 그대로 확정하면 실레코드 값이 나온다.
    model.confirm_all()
    out = model.to_profile().apply(record)
    assert out["입찰공고번호"] == "R26BK01561738"
    assert out["추정가격"] == "65,454,545원"
