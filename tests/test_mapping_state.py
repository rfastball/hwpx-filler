"""매핑 행 상태 모델 테스트 — Qt 불필요(헤드리스).

핵심 회귀는 **명시성 게이트**: 자동 초안이 채워져 있어도 사람이 전 행을 확정하기
전에는 ``is_complete()`` 가 False 여야 한다. 이 게이트가 기능의 존재 이유다.

엄격한 1:1: 한 템플릿 필드는 정확히 한 소스 키(``source``)에서 값을 취한다 —
N→1 결합·구분자(sep)는 없다.
"""

from __future__ import annotations

import json

import pytest
from datetime import datetime
from pathlib import Path

from hwpxfiller.domain.mapping import FieldMapping, MappingProfile, apply_transform
from hwpxfiller.external.mapping_store import load_mapping_profile, save_mapping_profile
from hwpxfiller.domain.schema import FieldSpec, TemplateSchema
from hwpxfiller.data.nara import NaraStdDataSource
from hwpxfiller.gui.mapping_state import (
    ROW_STATUS_LABEL,
    MappingModel,
    RowState,
    default_transform_for,
    pairing_preview,
)

#: 고정 기준 시각 — 「오늘 날짜」 단언은 시계를 고정해야 결정론적이다.
_TODAY_NOW = datetime(2026, 6, 15, 18, 4)

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
def test_from_suggestions_shapes_every_row_but_confirms_nothing():
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
    assert rows["개찰일시"].type == "date"
    assert rows["추정가격"].type == "amount"
    assert rows["공고명"].type == "text"
    assert rows["입찰공고번호"].type == "text"
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
    assert not MappingModel().is_complete()


def test_editing_a_confirmed_row_resets_confirmation():
    """확정 후 소스/유형/상수를 바꾸면 재확정 필요."""
    model = _model()
    _confirm_every_row(model)
    model.set_source(0, "bidNtceOrd")
    assert not model.rows[0].confirmed
    model.set_confirmed(0)
    model.set_type(0, "text")
    assert not model.rows[0].confirmed
    model.set_confirmed(0)
    model.set_const(0, "고정값")
    assert not model.rows[0].confirmed


# ----------------------------- 활성 소스 변화 = 칩-라이브 계약(결정 12·13)
# 신판 관문 = apply_active_sources(전집합 재계산) — 구 ignore_source(헤더별 무차별 해제)의 대체:
# 시스템 소유 행은 라이브 재제안(조용), 사람 소유 행은 소스가 꺼지면 R4 시끄러운 강등.
def _pum_model(sources: "list[str]", field: str = "품명") -> MappingModel:
    """단일 필드 + 주어진 소스 어휘의 소형 모델(재제안 경합 시연용).

    ``field`` 가 인자인 이유(#908): 2 음절 필드는 접미가 붙는 순간 길이비가 무너져
    (``품명`` ↔ ``세부품명`` = 2*2/(2+4) = 0.6667) 제안 임계 아래로 떨어진다. 차선
    후보가 **실제로 서야** 하는 테스트는 어간이 긴 필드로 세운다.
    """
    schema = TemplateSchema(fields=[FieldSpec(field, "text", 1, False)])
    return MappingModel.from_suggestions(schema, sources)


def test_apply_active_sources_resuggests_system_rows_live():
    """시스템 소유 행(미확정·미접촉)은 활성 헤더가 바뀌면 최선으로 라이브 재제안된다(결정 12).

    '계약금액'은 활성에 '계약금액'이 있으면 그것(정확), 끄면 '계약_금액'(언더스코어
    표기 변형, 0.8889)으로 다시 선다 — 강등이 아니라 조용한 재제안(반환 빈 목록).

    차선을 표기 변형으로 두는 것이 #908 이후의 계약이다: 의미 축이 다른 근접쌍은
    임계 아래라 재제안 후보가 되지 못한다(그 자리는 빈 채로 남아 사람이 고른다).
    """
    model = _pum_model(["계약금액", "계약_금액"], field="계약금액")
    assert model.rows[0].source == "계약금액"                # 초기 최선(정확)
    assert model.apply_active_sources(["계약_금액"]) == []    # 시스템 행 = 조용(R4 아님)
    assert model.rows[0].source == "계약_금액"               # 활성 따라 재제안
    model.apply_active_sources(["계약금액", "계약_금액"])
    assert model.rows[0].source == "계약금액"                # 복귀


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


def test_demotion_fully_resets_type_and_const():
    """R4 강등 = 완전 리셋(리뷰 반영) — 유형·상수가 남으면 강등 행이 시스템 소유가 된 뒤
    다음 재제안이 소스를 얹어 '제안 표시 ≠ 옛 상수 방출' 하이브리드가 된다(revert_to_auto
    R1 과 같은 근거 — 강등 경로만 부분 리셋일 이유가 없다)."""
    # 차선이 실제로 다시 서야 하는 테스트라 어간이 긴 필드 + 표기 변형으로 세운다(#908).
    model = _pum_model(["계약금액", "계약_금액"], field="계약금액")
    model.set_source(0, "계약금액")
    # 상수 + 소스 기억이 함께 사는 자리는 `set_manual`(직접 입력) 하나다 — U6-C 이후
    # `set_type("const")` 은 소스를 비운다(표시와 출력이 갈리지 않게).
    model.set_manual(0, "X")
    demoted = model.apply_active_sources(["계약_금액"])     # '계약금액' 끔 → 사람 소유 강등
    assert demoted == ["계약금액"]
    row = model.rows[0]
    assert row.source == "" and row.const == "" and row.type != "const"  # 완전 리셋
    model.apply_active_sources(["계약_금액"])               # 다음 활성 변화 — 시스템 소유 재제안
    assert model.rows[0].source == "계약_금액"
    assert model.rows[0].to_mapping().const == ""           # 옛 상수 방출 없음(하이브리드 봉쇄)


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


def test_carry_profile_skips_contentless_touched_rows():
    """내용 없는 touched 미확정 행(비움 선언도 아님)은 이월하지 않는다(리뷰 반영).

    담으면 apply_profile 이 touched 를 재날인해 그 필드가 새 데이터에서 영구히 라이브
    재제안 제외(조용한 동결)된다 — 시스템 소유로 낙착시켜 자동 제안을 다시 받게 한다.
    비움 **확정**(blank 선언)은 확정이라 계속 담는다(의도적 비움의 영속, L1)."""
    schema = TemplateSchema(fields=[
        FieldSpec("품명", "text", 1, False),
        FieldSpec("비고", "text", 1, False),
    ])
    model = MappingModel.from_suggestions(schema, ["품명"])
    model.set_source(0, "품명")
    model.set_source(0, "")                                # 사람이 비움(미확정) — 내용 없음
    assert model.rows[0].touched and not model.rows[0].has_content()
    model.rows[1].confirmed = True                         # 비움 확정(blank 선언) — 담는다
    carried = model.carry_profile().mappings
    assert [m.template_field for m in carried] == ["비고"]  # 내용 없는 touched 는 제외
    assert carried[0].is_blank                             # blank 선언으로 영속


def test_confirmed_rows_via_apply_active_sources_still_clear_matching():
    """구 ignore_source 계약 승계 확인: 확정 행의 소스를 끄면 그 행만 해제·이름 반환, 나머지 불변."""
    model = _model()
    _confirm_every_row(model)                                    # 전 행 확정(사람 소유)
    active = [s for s in list(NARA_ALIASES) if s != "bidNtceNo"]  # bidNtceNo 만 끔
    demoted = model.apply_active_sources(active)
    assert demoted == ["입찰공고번호"]                      # 그 소스 쓰던 확정 행만 강등
    rows = {r.template_field: r for r in model.rows}
    assert rows["공고명"].source == "bidNtceNm" and rows["공고명"].confirmed is True
    assert rows["추정가격"].source == "presmptPrce" and rows["추정가격"].confirmed is True


def test_emits_any_value_counts_only_confirmed_content():
    """비움 확정·미확정 내용은 빼고 확정된 소스·상수만 방출로 센다."""
    blank = MappingModel(rows=[RowState("공고명"), RowState("비고")])
    _confirm_every_row(blank)
    assert blank.is_complete() and blank.to_profile().mappings
    assert not blank.to_profile().template_fields()
    assert not blank.emits_any_value()

    source = MappingModel(rows=[RowState("공고명"), RowState("비고")])
    source.set_source(0, "bidNtceNm")
    _confirm_every_row(source)
    assert source.emits_any_value()
    const_model = MappingModel(rows=[RowState("계약방법", type="const", const="수의계약")])
    const_model.set_confirmed(0)
    assert const_model.emits_any_value()
    unconfirmed = MappingModel(rows=[RowState("공고명", source="bidNtceNm")])
    assert not unconfirmed.emits_any_value()


def test_row_confirmation_and_unconfirm_all():
    model = _model()
    _confirm_every_row(model)
    assert model.is_complete()
    model.unconfirm_all()
    assert not model.is_complete()
    assert all(not r.confirmed for r in model.rows)


# ------------------------------------------------- 행 상태 4태·일괄 승격(U6-C #977)
def _confirm_every_row(model) -> None:
    """전 행 확정 — 표면이 실제로 밟는 경로(내용 행은 배지, 빈 행은 「비워 둠」)의 축약.

    구 `MappingModel.confirm_all()`(무차별 확정)은 U6-C 에서 퇴역했다: 제품에 그 동사가
    없는데 테스트에만 남기면 테스트가 없는 경로로 상태를 만든다.
    """
    for index, row in enumerate(model.rows):
        if row.has_content():
            model.set_confirmed(index)
        else:
            model.set_blank(index)


def test_row_status_is_a_closed_set_of_four():
    """`status()` 는 확인 축 × 내용 축 × 소유 축에서 닫힌 4태를 낸다 — 판정의 단일 출처."""
    model = _model()  # 4 매칭(내용, 미접촉) + 1 미매칭(빈) 행
    rows = {r.template_field: r for r in model.rows}
    assert rows["입찰공고번호"].status() == "suggested"      # 내용 있음 + 시스템 소유
    assert rows["존재하지않는들판xyz"].status() == "needs_source"  # 채울 것이 없다
    model.set_source(model.index_of("입찰공고번호"), "bidNtceNo")  # 사람이 직접 골랐다
    assert rows["입찰공고번호"].status() == "edited"
    model.set_confirmed(model.index_of("입찰공고번호"))
    assert rows["입찰공고번호"].status() == "confirmed"
    # 데이터 미연결(구 `schemaonly`)도 별도 상태가 아니다 — 요구하는 것이 같다.
    lonely = MappingModel(rows=[RowState("공고명")])
    assert lonely.is_schema_only() and lonely.rows[0].status() == "needs_source"
    assert {ROW_STATUS_LABEL[k] for k in
            ("suggested", "edited", "confirmed", "needs_source")} == {"제안", "확인 필요", "확인"}


def test_confirm_suggested_promotes_only_system_owned_content_rows():
    """일괄 승격은 **자동 제안만** 건드린다 — 사람이 손댄 행·열 필요 행은 그대로 남는다."""
    model = _model()  # 4 매칭(제안) + 1 미매칭
    model.set_source(model.index_of("공고명"), "bidNtceNm")   # 사람이 손댐 → edited
    assert model.suggested_count() == 3
    assert model.needs_confirm_count() == 2                  # edited 1 + needs_source 1
    assert model.suggested_count() + model.needs_confirm_count() + \
        model.confirmed_count() == len(model.rows)

    assert model.confirm_suggested() == 3
    assert not model.is_complete(), "일괄 승격이 명시성 게이트를 우회하면 안 된다"
    rows = {r.template_field: r for r in model.rows}
    assert rows["공고명"].status() == "edited", "사람이 손댄 행을 대신 확정했다"
    assert rows["존재하지않는들판xyz"].status() == "needs_source"
    assert model.confirm_suggested() == 0, "재호출은 승격할 것이 없다"

    # 남은 둘을 사람이 직접 답하면 그때 게이트가 열린다.
    model.set_confirmed(model.index_of("공고명"))
    model.set_blank(model.index_of("존재하지않는들판xyz"))
    assert model.is_complete() and model.needs_confirm_count() == 0


def test_set_blank_declares_intentional_emptiness():
    """행별 「비워 둠」 = 구 `confirm_fields` 비움 승격과 **같은 결과**(blank 선언 영속)."""
    model = _model()
    index = model.index_of("존재하지않는들판xyz")
    model.set_blank(index)
    assert model.rows[index].status() == "confirmed"
    assert model.declared_blank_fields() == ["존재하지않는들판xyz"]
    _confirm_every_row(model)
    blank = [m for m in model.to_profile().mappings
             if m.template_field == "존재하지않는들판xyz"][0]
    assert blank.is_blank

    # 결속·상수를 든 행도 비울 수 있다 — 그때 값의 출처가 함께 걷힌다.
    bound = MappingModel(rows=[RowState("금액", source="amount", type="amount")])
    bound.set_blank(0)
    assert bound.rows[0].source == "" and bound.rows[0].is_empty_confirmed()

    # 특수 유형 둘은 추정 기본형으로 되돌아간다(리뷰 5). `today` 를 남기면 「비워 둠」이
    # 오늘 날짜를 찍고, `const` 를 남기면 채우지 않는 행이 「고정값 n」 pill 에 세어지고
    # 확인을 푼 순간 데이터 열 칸이 「고정값…」으로 되살아난다.
    for kind in ("today", "const"):
        row = MappingModel(rows=[RowState("작성일", type=kind, const="x")])
        row.set_blank(0)
        assert row.rows[0].type not in ("today", "const"), kind
        assert row.rows[0].const == "" and row.rows[0].is_empty_confirmed()


def test_set_blank_is_a_human_edit_so_resuggestion_cannot_undo_it():
    """「비워 둠」은 사람의 편집이다(리뷰 3) — ``touched`` 를 안 세우면 확인을 푼 순간
    시스템 소유로 돌아가 라이브 재제안·일괄 승격이 그 선언을 조용히 덮는다."""
    model = _pum_model(["품명", "세부품명"])
    model.set_blank(0)
    assert model.rows[0].touched is True and model.rows[0].is_human_owned()

    model.set_confirmed(0, False)                       # 「모두 해제」 뒤
    assert model.rows[0].is_human_owned(), "확인을 풀자 시스템 소유로 돌아갔다"
    model.apply_active_sources(["품명", "세부품명"])      # 데이터 재마운트의 재동기화
    assert model.rows[0].source == "", "재제안이 사람의 비움 선언을 덮었다"
    assert model.confirm_suggested() == 0, "일괄 승격이 사람 소유 행을 건드렸다"


def test_set_display_sets_type_and_format_in_one_transition():
    """(유형, 표시형)은 한 전이다(리뷰 1) — 두 발이면 그 사이에 표시형이 사라진 상태가 산다."""
    model = MappingModel(rows=[RowState("계약일", spec=FieldSpec("계약일", "text", 1, False))])
    model.set_source(0, "체결일")
    model.set_display(0, "date", "kor")
    assert model.rows[0].type == "date" and model.rows[0].fmt == "kor"
    assert model.rows[0].source == "체결일", "열 결속은 유형 축과 무관하다"
    assert model.rows[0].confirmed is False and model.rows[0].touched is True

    # 특수 유형은 열에서 값을 받지 않으므로 소스를 함께 비운다(`set_type` 과 같은 짝 규칙).
    model.set_display(0, "today", "")
    assert model.rows[0].source == "" and model.rows[0].fmt == ""
    # const 를 떠나면 상수도 함께 걷힌다(옛 리터럴 방출 봉쇄).
    model.set_display(0, "const", "")
    model.set_const(0, "일금")
    model.set_display(0, "text", "phone")
    assert model.rows[0].const == "" and model.rows[0].fmt == "phone"

    with pytest.raises(ValueError, match="지원하지 않는 유형"):
        model.set_display(0, "없는유형", "")


def test_special_types_and_column_binding_do_not_coexist():
    """열을 고르면 특수 유형이 풀리고, 특수 유형을 고르면 열이 풀린다(표시 ≠ 출력 금지)."""
    model = MappingModel(rows=[RowState("금액", spec=FieldSpec("금액", "amount", 1, False))])
    model.set_type(0, "const")
    model.set_const(0, "일금")
    assert model.rows[0].source == ""
    model.set_source(0, "amount")
    assert model.rows[0].type == "amount", "const 가 남으면 산출물에 옛 상수가 박힌다"
    assert model.rows[0].const == "" and model.rows[0].source == "amount"

    model.set_type(0, "today")
    assert model.rows[0].source == "", "today 는 소스를 보지 않는다"
    model.set_source(0, "amount")
    assert model.rows[0].type == "amount" and model.rows[0].source == "amount"


def test_unused_source_fields_are_the_columns_no_row_aims_at():
    """표 바닥 한 줄이 잇는 정보 — 열 선별(#49)이 퇴역하고 남은 유일한 질문."""
    model = MappingModel(
        rows=[RowState("업체", source="업체명"), RowState("담당자")],
        source_fields=["업체명", "금액", "비고"],
    )
    assert model.unused_source_fields() == ["금액", "비고"]
    model.set_source(1, "비고")
    assert model.unused_source_fields() == ["금액"]


def test_const_count_sees_hand_written_values():
    model = MappingModel(rows=[RowState("가"), RowState("나"), RowState("다")])
    model.set_type(0, "const")
    model.set_type(1, "const")
    assert model.const_count() == 2


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


def test_today_row_has_content_without_source_or_const():
    """U4-E1 #939 회귀: today 는 소스·상수 없이 **언제나** 값을 방출한다.

    has_content 를 소스 유무로 재면 확정 시 to_profile 이 blank 로 강등해 값이 통째
    소실된다(조용한 값 소실) — 그 강등이 일어나지 않음을 저장 산출물로 확인한다.
    """
    model = MappingModel(rows=[RowState("작성일", type="today", fmt="%Y-%m-%d")])
    row = model.rows[0]
    assert row.has_content()
    model.set_confirmed(0)
    assert not row.is_empty_confirmed()
    assert model.emits_any_value()
    profile = model.to_profile()
    assert profile.blank_fields() == []
    assert profile.template_fields() == ["작성일"]
    assert profile.mappings[0].type == "today"
    assert profile.apply({}, now=_TODAY_NOW) == {"작성일": "2026-06-15"}


def test_today_preview_matches_apply_transform_wysiwyg():
    """미리보기 값 = apply_transform(같은 now) — 링1 preview 도 WYSIWYG 계약을 진다."""
    model = MappingModel(rows=[
        RowState("작성일", type="today", fmt="kor"),
        RowState("추정가격", source="presmptPrce", type="amount"),
    ])
    out = model.preview({"presmptPrce": "21326800"}, now=_TODAY_NOW)
    assert out["작성일"] == apply_transform("today", fmt="kor", now=_TODAY_NOW)
    assert out["작성일"] == "2026년 6월 15일 18:04"
    assert model.preview_empties({"presmptPrce": "21326800"}, now=_TODAY_NOW) == []
    assert model.preview_counts({"presmptPrce": "21326800"}, now=_TODAY_NOW) == (2, 0, 0)


def test_default_transform_never_infers_today():
    """추론은 today 를 내지 않는다 — 시스템 토큰은 사람이 명시로만 고른다."""
    for inferred in ("date", "amount", "text", "number", "phone", ""):
        assert default_transform_for(inferred) != "today"


def test_blank_is_internal_marker_not_selectable_type():
    from hwpxfiller.domain.mapping import TYPES

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
            RowState("개찰일", source="date", type="date", fmt="%Y-%m-%d"),
            RowState("연락처", source="tel", type="text", fmt="phone"),
        ]
    )
    record = {
        "presmptPrce": "21326800", "opengTm": "18:00",
        "date": "2026-6-5", "tel": "01012345678",
    }
    out = model.preview(record)
    assert out["추정가격"] == apply_transform("amount", "21326800") == "21,326,800원"
    assert out["개찰시각"] == apply_transform("date", "18:00", fmt="%H:%M") == "18:00"
    assert out["개찰일"] == "2026-06-05"
    assert out["연락처"] == "010-1234-5678"


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
    model.set_fmt(0, "{:,}")
    model.set_type(0, "date")
    assert model.rows[0].fmt == ""


def test_profile_roundtrip_preserves_format(tmp_path):
    """저장→로드가 표시형 코드(fmt)를 보존한다(구 프로파일 호환: 없으면 기본)."""
    model = MappingModel(rows=[RowState("추정가격", source="presmptPrce", type="amount", fmt="{:,}")])
    model.set_confirmed(0)
    path = tmp_path / "p.json"
    save_mapping_profile(model.to_profile(), path)
    loaded = load_mapping_profile(path)
    assert loaded.mappings[0].fmt == "{:,}"
    assert loaded.apply({"presmptPrce": "21326800"})["추정가격"] == "21,326,800"


def test_preview_covers_unmapped_rows_as_empty():
    model = _model()
    out = model.preview(_nara_record())
    assert out["존재하지않는들판xyz"] == ""
    assert out["입찰공고번호"] == "R26BK01561738"


# --------------------------------------------------------------- preview_empties
def test_preview_counts_partition_filled_empty_and_unmapped_rows():
    model = MappingModel(
        rows=[
            RowState("공고명", source="bidNtceNm"),
            RowState("추정가격", source="presmptPrce"),
            RowState("여백"),
            RowState("비고"),
        ]
    )
    record = {"bidNtceNm": "테스트 공고"}
    assert model.preview_empties(record) == ["추정가격"]
    filled, empty_n, unmapped = model.preview_counts(record)
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
    save_mapping_profile(model.to_profile("나라장터표준"), path)

    fresh = _model()
    assert not fresh.is_complete()
    applied = fresh.apply_profile(load_mapping_profile(path))
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
    _confirm_every_row(model)
    out = model.to_profile().apply(record)
    assert out["입찰공고번호"] == "R26BK01561738"
    assert out["추정가격"] == "65,454,545원"


def test_apply_active_sources_vocabulary_scopes_demotion_to_known_headers():
    """vocabulary 를 주면 강등은 어휘 안 소스로 한정(PR-3 리뷰 F1) — 어휘 밖 소스를 겨눈
    이월 stale 사람 소유 행(뷰가 「데이터에 없음」으로 이미 시끄러움)은 무관한 칩 조작에
    소실되지 않는다. 어휘 안 소스는 종전대로 R4 강등."""
    schema = TemplateSchema(fields=[
        FieldSpec("품명", "text", 1, False),
        FieldSpec("규격", "text", 1, False),
    ])
    model = MappingModel.from_suggestions(schema, ["품명", "규격"])
    model.set_source(0, "없는열")                           # 이월 stale(어휘 밖) 사람 소유
    model.set_source(1, "규격")                             # 어휘 안 사람 소유
    demoted = model.apply_active_sources(["품명"], vocabulary=["품명", "규격"])
    assert demoted == ["규격"]                              # 실제로 끈 헤더의 행만 강등
    assert model.rows[0].source == "없는열"                 # stale 은 불건드림(이월 값 보존)
    assert model.rows[0].touched is True


# ------------------------------------------------- #148 슬라이스 3b: 「기안」 맞추기(스키마 없이)
def test_from_field_names_exact_autobinds_and_infers_type():
    """정확 일치 열만 자동 결속(결정 30)하고, 결속 열은 값 스니핑 유형이 이름 추론을 이긴다(결정 5).

    스키마 없이 토큰 이름 목록만으로 세운다 — txt 트랙엔 TemplateSchema 가 없다(모델은 이미
    schema-불가지). 근사(비정확)는 붙지 않고 suggestions 로 넘어간다."""
    m = MappingModel.from_field_names(
        ["계약명", "계약금액", "완료일자"],
        source_fields=["계약명", "계약금액", "착수예정일"],
        col_kinds={"계약명": "text", "계약금액": "amount", "착수예정일": "date"},
    )
    by = {r.template_field: r for r in m.rows}
    assert by["계약명"].source == "계약명" and by["계약명"].type == "text"      # 정확 결속
    assert by["계약금액"].source == "계약금액" and by["계약금액"].type == "amount"  # 값 스니핑 우선(결정 5)
    # 완료일자: 근사 미결속(착수예정일과 정확 불일치) → 이름 휴리스틱(「일자」→date)이 유형을 정함.
    assert by["완료일자"].source == "" and by["완료일자"].type == "date"


def test_from_field_names_suggestions_are_approximate_only():
    """근사 제안 = 무결속 자리의 ≥0.6 후보(원클릭 대상, 자동 적용 안 함). 이미 쓰는 열은 제외."""
    m = MappingModel.from_field_names(
        ["착수일"], source_fields=["착수예정일"], col_kinds={"착수예정일": "date"}
    )
    assert m.suggestions() == {"착수일": "착수예정일"}   # 근사(≥0.6) 제안으로만


def test_live_profile_applies_all_content_rows_not_just_confirmed():
    """휘발 렌더 = 확정 게이트 무관, 내용 있는(결속·상수) 전 행. 무결속은 빠져 토큰이 missing."""
    m = MappingModel.from_field_names(["명", "인"], source_fields=["명"])
    m.set_manual(m.index_of("인"), "김민수")            # 상수(man)
    prof = m.live_profile()
    out = prof.apply({"명": "통학차량"})
    assert out == {"명": "통학차량", "인": "김민수"}      # 결속 auto + 상수 man
    # 무결속 자리는 프로파일에 없다 → render_segments 가 missing({{}} 빨강)으로 남긴다.
    m2 = MappingModel.from_field_names(["명", "빈자리"], source_fields=["명"])
    assert "빈자리" not in m2.live_profile().apply({"명": "x"})


def test_live_profile_renders_confirmed_blank_as_empty_not_missing():
    """확정-비움(#148 슬라이스 4, 결정 12) — 확정+무내용은 blank 방출(키 유지 → 〈빈 값〉).

    미확정 무내용은 프로파일에서 빠져 missing({{}} 빨강)으로 남지만, 사람이 「비운다」고
    확정한 자리는 빈 값으로 **담겨** render_segments 가 blank(empty)로 표지한다 — 렌더는
    데이터-빈값과 같고 게이트 제외만 declared_blank_fields 가 가른다. type='blank' 이 아니라
    빈 text 로 담아야 MappingProfile.apply 의 is_blank 드롭에 키가 사라지지 않는다."""
    m = MappingModel.from_field_names(["명", "비고"], source_fields=["명"])
    out_before = m.live_profile().apply({"명": "값"})
    assert "비고" not in out_before                      # 미확정 무내용 → 빠짐(missing)
    m.set_confirmed(m.index_of("비고"), True)             # 「비운다」 확정
    out_after = m.live_profile().apply({"명": "값"})
    assert out_after["비고"] == ""                        # 확정-비움 → 키 유지·빈 값(blank)


def test_has_content_const_ignores_remembered_source():
    """const(man) 행의 내용 판정은 리터럴 기준 — 기억된 소스는 되돌리기용이지 출력이 아니다(Codex F2).

    결속 값을 비우면 소스를 기억한 채 빈 상수가 되는데, 소스를 내용으로 세면 값을 비우고
    확정해도 확정-비움으로 인식되지 않아 게이트가 계속 묻는다."""
    m = MappingModel.from_field_names(["명"], source_fields=["명"], col_kinds={"명": "text"})
    m.set_manual(m.index_of("명"), "")                # 결속 값 비움 → const="" (소스 「명」 기억)
    row = m.rows[m.index_of("명")]
    assert row.type == "const" and row.source == "명" and row.const == ""
    assert row.has_content() is False                # 빈 상수는 내용 아님(소스 기억 무관)
    m.set_confirmed(m.index_of("명"), True)
    assert row.is_empty_confirmed() is True           # 확정-비움으로 인식
    # 값 있는 상수는 여전히 내용이다(회귀 방지).
    m.set_manual(m.index_of("명"), "김민수")
    assert row.has_content() is True


def test_declared_blank_fields_only_confirmed_empty():
    """declared_blank_fields = 확정+무내용만 — 내용 있는 확정 행·미확정 빈 행은 빠진다."""
    m = MappingModel.from_field_names(["명", "비고", "인"], source_fields=["명"])
    m.set_confirmed(m.index_of("명"), True)               # 결속 내용 있음 → 확정-비움 아님
    m.set_confirmed(m.index_of("비고"), True)             # 무내용 확정 → 확정-비움
    # 인: 미확정 무내용 → 확정-비움 아님(그 행의 사실이지 선언 아님)
    assert m.declared_blank_fields() == ["비고"]
    # 확정-비움에 값을 채우면(내용 생김) 선언이 풀린다 — set_manual 이 confirmed 도 해제.
    m.set_manual(m.index_of("비고"), "값")
    assert m.declared_blank_fields() == []


def test_set_manual_then_revert_binding_round_trip():
    """결속 값 고치면 상수(man)로 강등하되 소스를 기억하고, 되돌리기로 결속(auto) 복귀(사용자 결정)."""
    m = MappingModel.from_field_names(["명"], source_fields=["명"], col_kinds={"명": "text"})
    i = m.index_of("명")
    m.set_manual(i, "손으로 고침")
    row = m.rows[i]
    assert row.type == "const" and row.const == "손으로 고침" and row.source == "명"  # 소스 기억
    assert m.revert_binding(i) is True
    assert row.type == "text" and row.const == "" and row.source == "명"           # auto 복귀
    # 소스 기억이 없으면(순수 수기) 되돌릴 게 없다.
    m2 = MappingModel.from_field_names(["명"], source_fields=[])
    m2.set_manual(0, "값")
    assert m2.revert_binding(0) is False


def test_bind_column_clears_const_and_unbind_resets():
    """열 결속은 상수를 지워 결속 값이 다시 살고, 해제는 시스템 소유로 낙착(재제안 대기)."""
    m = MappingModel.from_field_names(["명"], source_fields=["갑", "을"], col_kinds={"을": "amount"})
    m.set_manual(0, "수기")
    m.bind_column(0, "을", "amount")
    assert m.rows[0].source == "을" and m.rows[0].type == "amount" and m.rows[0].const == ""
    m.unbind(0)
    assert m.rows[0].source == "" and m.rows[0].is_system_owned()   # 재제안 대기(값 동결 없음)


# ------------------------------------------------ 고르기 연결 카드 미리보기(U6-B #976)
def test_pairing_preview_splits_exactly_like_suggest_mappings():
    """카드의 「자동 연결 n」은 2단계가 실제로 세울 제안 수와 **정의상** 같아야 한다.

    수치를 따로 지으면 1단계가 약속한 것과 2단계가 보여 주는 것이 갈린다 — 그래서 같은
    순수 함수(:func:`~hwpxfiller.domain.mapping.suggest_mappings`)를 읽기 전용으로 한 번
    돌려 세기만 한다. 그 동일성을 여기서 기계로 대조한다.
    """
    from hwpxfiller.domain.mapping import suggest_mappings

    fields = [f.name for f in _schema().fields]
    sources = list(NARA_ALIASES)
    auto, confirm = pairing_preview(fields, sources)
    suggested = {m.template_field for m in suggest_mappings(fields, sources)}
    assert auto == len(suggested)
    assert auto + confirm == len(fields)
    # 이 스키마의 마지막 필드는 어느 소스와도 안 맞는다 — 확인 필요가 최소 1건이다.
    assert confirm >= 1
    assert "존재하지않는들판xyz" not in suggested


def test_pairing_preview_is_all_confirm_without_sources():
    """소스가 없으면 제안이 설 수 없다 — 전부 확인 필요다(빈 자동 연결을 지어내지 않는다)."""
    fields = [f.name for f in _schema().fields]
    assert pairing_preview(fields, []) == (0, len(fields))
    assert pairing_preview([], ["아무거나"]) == (0, 0)


# ── 행 투영(U6-F #980) — 편집기 2단계와 「문서 작업」 상세가 공유하는 순수 함수 ──────────

def _projection_rows() -> "list[RowState]":
    """네 갈래 한 벌 — 열 결속 · 값이 빈 열 · 오늘 날짜 · 아무것도 없는 행."""
    return [
        RowState(template_field="계약명", source="사업명", confirmed=True, touched=True),
        RowState(template_field="금액", source="빈열", type="amount", confirmed=True,
                 touched=True),
        RowState(template_field="작성일", type="today", confirmed=True, touched=True),
        RowState(template_field="담당자"),
    ]


def test_row_projection_matches_what_the_editor_snapshot_used_to_build():
    """투영이 링1 로 올라와도 편집기 스냅샷의 키·값은 그대로다(회귀 대조).

    이 표를 읽기 전용으로 한 번 더 세우려는 표면이 자기 사본을 만들 수밖에 없던 것이
    #966 이 걷은 사슬의 뿌리였다 — 투영이 하나이므로 두 표면이 다른 말을 할 자리가 없다.
    """
    from hwpxfiller.gui.mapping_state import row_projection

    rows = _projection_rows()
    record = {"사업명": "청사 냉난방 교체", "빈열": ""}
    projections = [
        row_projection(r, record, index=i, source_fields=["사업명", "빈열"],
                       has_records=True, now=_TODAY_NOW)
        for i, r in enumerate(rows)
    ]
    assert [p["template_field"] for p in projections] == ["계약명", "금액", "작성일", "담당자"]
    assert [p["preview_kind"] for p in projections] == ["value", "missing", "value", "none"]
    # 빈 값은 빈칸으로 새지 않는다 — 생성이 실제로 박는 표식이 그대로 온다.
    assert projections[1]["preview"] == "〘미입력·금액〙"
    assert projections[2]["preview"] == "2026. 6. 15. 18:04"   # today 기본 표시형
    assert [p["row_state"] for p in projections] == [
        "confirmed", "confirmed", "confirmed", "needs_source"]
    assert [p["state_label"] for p in projections] == [
        ROW_STATUS_LABEL["confirmed"]] * 3 + [ROW_STATUS_LABEL["needs_source"]]
    assert projections[0]["source_value"] == "col:사업명"
    assert projections[2]["source_value"] == "sp:today"
    # 「데이터에 없음」은 실 헤더를 알 때만 선다.
    gone = row_projection(rows[0], record, index=0, source_fields=["다른열"],
                          has_records=True, now=_TODAY_NOW)
    assert gone["source_missing_label"] == "사업명 (데이터에 없음)"


def test_row_projection_states_pending_and_error_instead_of_faking_a_record():
    """첫 행을 아직 못 읽었으면 그렇게 말한다 — 빈 레코드로 흉내 내지 않는다(U6-F 함정 3).

    ``record={}`` 로 미읽음을 흉내 내면 미입력 표식이 찍혀 「산출물이 담을 것」과 「아직
    모름」이 한 글자로 접힌다. 사유는 호출자가 존 수준에서 싣고 행은 상태만 낸다.
    """
    from hwpxfiller.gui.mapping_state import PENDING_PREVIEW_MARK, row_projection

    row = _projection_rows()[0]
    pending = row_projection(row, {}, index=0, source_fields=["사업명"], has_records=False,
                             now=_TODAY_NOW, first_row_state="pending")
    assert pending["preview_kind"] == "pending"
    assert pending["preview"] == PENDING_PREVIEW_MARK
    assert pending["preview_error"] is False and pending["preview_empty"] is False
    # 나머지 축(결속·상태·표시형)은 저장본만으로 그려지므로 pending 에서도 그대로 산다.
    assert pending["row_state"] == "confirmed" and pending["source_value"] == "col:사업명"

    failed = row_projection(row, {}, index=0, source_fields=["사업명"], has_records=False,
                            now=_TODAY_NOW, first_row_state="error")
    assert failed["preview_kind"] == "error" and failed["preview"] == ""

    with pytest.raises(ValueError, match="알 수 없는 첫 행 상태"):
        row_projection(row, {}, index=0, source_fields=[], has_records=False,
                       now=_TODAY_NOW, first_row_state="loaded")


def test_read_only_cell_labels_come_from_the_ring1_vocabulary():
    """읽기 전용 표의 두 칸 문안은 링1 조회다 — 웹이 특수 항목 표를 한 벌 더 들지 않는다."""
    from hwpxfiller.gui.mapping_state import (
        PENDING_PREVIEW_MARK,
        display_cell_label,
        row_projection,
        source_cell_label,
    )

    rows = _projection_rows() + [
        RowState(template_field="비고", type="const", const="해당 없음", confirmed=True),
        RowState(template_field="여백", confirmed=True),          # 비움 확정
    ]
    projections = [
        row_projection(r, {"사업명": "값"}, index=i, source_fields=["사업명", "빈열"],
                       has_records=True, now=_TODAY_NOW)
        for i, r in enumerate(rows)
    ]
    assert [source_cell_label(p) for p in projections] == [
        "사업명", "빈열", "오늘 날짜", "열을 고르세요", "고정값… 해당 없음", "비워 둠",
    ]
    # 표시형은 고른 항목의 라벨이고, 프리셋이 없는 고정값 행은 빈 칸 마커다.
    assert display_cell_label(projections[0]) == "원문"
    assert display_cell_label(projections[4]) == PENDING_PREVIEW_MARK


def test_name_token_values_feed_both_filename_previews():
    """파일 이름 토큰 재료는 한 자리다 — 내용 있는 행만, 실패는 빈 문자열."""
    model = MappingModel(rows=_projection_rows())
    values = model.name_token_values({"사업명": "청사 냉난방 교체", "빈열": ""},
                                     now=_TODAY_NOW)
    assert values == {
        "계약명": "청사 냉난방 교체", "금액": "", "작성일": "2026. 6. 15. 18:04",
    }
