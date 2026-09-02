"""작업 저장 게이트(링1) 헤드리스 테스트 — RC-28.

에디터 ``accept()`` 의 술어(매핑 확정·이름·패턴·전부 비움·덮어쓰기 확인 필요)와
확인 문구 성형을 Qt 없이 검증한다 — RC-08 류의 dead guard 가 위젯 사각에서
시그널 없이 썩지 않게 한다.
"""

from __future__ import annotations

from hwpxfiller.gui.job_editor_state import (
    JOB_NAME_SEPARATOR,
    derive_job_name,
    needs_overwrite_confirm,
    overwrite_confirm_text,
    validate_save,
)
from hwpxfiller.gui.mapping_state import MappingModel, RowState


#: 이 세션이 선 데이터 결속의 경로(#932 U4-C S2-3) — 저장 게이트가 요구하는 값이다.
#: 실재하는 파일일 필요는 없다: 술어는 「연결이 있는가」 하나이고 읽기는 이 층의 일이
#: 아니다(:func:`~hwpxfiller.domain.job.has_data_binding` 과 같은 축).
BOUND = "D:/데이터/공고목록.xlsx"


def _model(*rows: RowState) -> MappingModel:
    return MappingModel(rows=list(rows))


def _content_row(name: str = "공고명", confirmed: bool = True) -> RowState:
    return RowState(template_field=name, source="bidNtceNm", confirmed=confirmed)


def _blank_row(name: str = "비고") -> RowState:
    return RowState(template_field=name, confirmed=True)  # 의도적 비움 확정


# ------------------------------------------------------------------ validate_save
def test_validate_save_blocks_when_model_missing():
    verdict = validate_save(None, "작업1", "doc-{{ID}}", data_path=BOUND)
    assert not verdict.ok
    assert "확정" in verdict.block_reason
    assert verdict.profile is None


def test_validate_save_blocks_when_not_all_confirmed():
    model = _model(_content_row(), _content_row("추정가격", confirmed=False))
    verdict = validate_save(model, "작업1", "doc-{{ID}}", data_path=BOUND)
    assert not verdict.ok
    assert "모든 매핑 행" in verdict.block_reason


def test_validate_save_blocks_on_empty_name():
    verdict = validate_save(_model(_content_row()), "", "doc-{{ID}}", data_path=BOUND)
    assert not verdict.ok
    assert "이름" in verdict.block_reason


def test_validate_save_blocks_on_empty_pattern():
    """RC-20 — 빈 패턴을 화면에 없던 값으로 조용히 폴백하지 않는다."""
    verdict = validate_save(_model(_content_row()), "작업1", "", data_path=BOUND)
    assert not verdict.ok
    assert "패턴" in verdict.block_reason


def test_validate_save_pattern_gate_is_media_aware():
    """F6 PR-B — TXT 작업은 파일을 만들지 않아 파일 이름 축이 없다(§3.2): 패턴 게이트가
    서지 않는다. 없는 규칙의 차단 문구는 고칠 표면이 없는 문구다. 그 외 게이트는 동일."""
    assert validate_save(_model(_content_row()), "작업1", "", media="txt", data_path=BOUND).ok
    assert "이름" in validate_save(_model(_content_row()), "", "", media="txt", data_path=BOUND).block_reason
    assert "전부 비움" in validate_save(_model(_blank_row()), "작업1", "", media="txt", data_path=BOUND).block_reason


def test_validate_save_blocks_all_blank_job():
    """RC-08 회귀 — 전부 비움 확정 작업은 emits_any_value 질의로 시끄럽게 차단."""
    verdict = validate_save(
        _model(_blank_row("갑"), _blank_row("을")), "작업1", "doc-{{ID}}", data_path=BOUND
    )
    assert not verdict.ok
    assert "전부 비움" in verdict.block_reason


def test_validate_save_passes_with_profile():
    verdict = validate_save(_model(_content_row(), _blank_row()), "작업1", "doc-{{공고명}}", data_path=BOUND)
    assert verdict.ok and verdict.block_reason == ""
    assert verdict.profile is not None
    assert verdict.profile.name == "작업1"
    # 확정 2행(값 1 + 명시 blank 1) 전부 프로파일로 영속화(L1).
    assert len(verdict.profile.mappings) == 2


def test_validate_save_blocks_a_filename_token_nothing_can_fill():
    """U4 계열4-4 — 미해소 파일명 토큰은 **저장 시점**에 막는다.

    실행 화면까지 미루면 「고칠 자리는 편집기인데 지적은 문서 만들기에서」가 돼 수정
    동선이 갈린다. 이 검사는 데이터가 필요 없는 작업 정의 수준 계약이라 여기서 답할 수 있다.
    """
    verdict = validate_save(_model(_content_row(), _blank_row()), "작업1", "doc-{{ID}}", data_path=BOUND)
    assert not verdict.ok
    assert "{{ID}}" in verdict.block_reason
    assert verdict.blocked_field == "pattern"      # 고칠 칸을 함께 말한다(U2 §2.4)
    assert verdict.profile is None


def test_a_blank_declared_field_cannot_carry_a_filename_token():
    """명시 비움 필드는 출력 dict 에서 빠져 토큰이 리터럴로 남는다 — 그래서 미해소다."""
    verdict = validate_save(_model(_content_row(), _blank_row()), "작업1", "doc-{{비고}}", data_path=BOUND)
    assert not verdict.ok
    assert "{{비고}}" in verdict.block_reason


def test_txt_media_has_no_filename_axis_so_the_token_gate_is_silent():
    """TXT 작업은 파일을 만들지 않아 파일 이름 축이 없다(§3.2) — 없는 규칙을 요구하지 않는다."""
    verdict = validate_save(
        _model(_content_row(), _blank_row()), "작업1", "doc-{{ID}}", media="txt", data_path=BOUND
    )
    assert verdict.ok


def test_blocked_field_names_the_input_to_fix():
    """차단은 **고칠 칸**을 함께 말한다(U2 §2.4) — "입력하세요"만으로는 지시가 절반이다.

    표면이 차단 문구를 파싱해 어느 칸인지 알아내면 문안을 고칠 때마다 조준이 조용히
    깨진다. 판정이 이름을 내고 표면은 그것을 겨눈다.

    칸을 겨눌 수 없는 차단(미확정·스키마 불일치·전부 비움)은 **빈 문자열**이다 — 없는
    칸을 겨눈 척하지 않는다. 그것들은 표 전체가 대상이라 지목할 입력이 없다.
    """
    assert validate_save(_model(_content_row()), "", "doc-{{ID}}", data_path=BOUND).blocked_field == "name"
    assert validate_save(_model(_content_row()), "작업1", "", data_path=BOUND).blocked_field == "pattern"
    # TXT 는 파일 이름 축이 없어 패턴 차단 자체가 없다 — 겨눌 칸도 없다.
    assert validate_save(_model(_content_row()), "작업1", "", media="txt", data_path=BOUND).ok
    for verdict in (
        validate_save(_model(_content_row(confirmed=False)), "작업1", "doc-{{ID}}", data_path=BOUND),
        validate_save(_model(_blank_row()), "작업1", "doc-{{ID}}", data_path=BOUND),
    ):
        assert not verdict.ok and verdict.blocked_field == ""


def test_validate_save_blocks_until_data_is_connected():
    """데이터 결속은 저장 게이트다(#932 U4-C S2-3) — 「데이터 없이 진행」의 사망과 한 짝.

    작업이 데이터 참조를 durable 로 들게 된 이상(U4 §2.4), 결속 없는 저장은 실행할 수 없는
    작업을 만든다. 차단은 고칠 자리(데이터 관문)를 함께 말한다.
    """
    verdict = validate_save(_model(_content_row()), "작업1", "doc-{{공고명}}", data_path="")
    assert not verdict.ok
    assert "데이터를 연결" in verdict.block_reason
    assert verdict.blocked_field == "data"
    assert verdict.profile is None
    # TXT 도 예외가 아니다 — 파일 이름 축은 없어도 채울 값의 출처는 있어야 한다.
    assert not validate_save(
        _model(_content_row()), "작업1", "", media="txt", data_path=""
    ).ok


def test_validate_save_predicate_order_is_stable():
    """차단 사유 순서 고정: 미확정 → 데이터 → 이름 → 패턴 → 전부 비움.

    데이터 술어는 **템플릿 다음**이다: 템플릿이 필드를 정하고 그 필드를 채울 데이터가
    이어진다. 이름·파일명보다 앞에 서므로, 아무것도 안 채운 세션의 첫 지적은 데이터다.
    """
    unconfirmed = _model(_content_row(confirmed=False))
    assert "모든 매핑 행" in validate_save(unconfirmed, "", "", data_path="").block_reason
    all_blank = _model(_blank_row())
    assert "데이터를 연결" in validate_save(all_blank, "", "", data_path="").block_reason
    assert "이름" in validate_save(all_blank, "", "", data_path=BOUND).block_reason
    assert "패턴" in validate_save(all_blank, "작업1", "", data_path=BOUND).block_reason
    assert "전부 비움" in validate_save(all_blank, "작업1", "doc-{{ID}}", data_path=BOUND).block_reason


# ------------------------------------------------------- needs_overwrite_confirm
def test_overwrite_confirm_only_when_covering_another_job():
    # 새 작업이 기존 이름과 충돌 → 확인 필요.
    assert needs_overwrite_confirm("작업1", None, exists=True)
    # 새 이름(미존재) → 확인 불필요.
    assert not needs_overwrite_confirm("작업1", None, exists=False)
    # 편집 모드 자기 자신 갱신(이름 그대로) → 자명, 확인 없음.
    assert not needs_overwrite_confirm("작업1", "작업1", exists=True)
    # 편집 모드에서 이름을 바꿔 다른 기존 작업을 덮음 → 확인 필요.
    assert needs_overwrite_confirm("작업2", "작업1", exists=True)
    assert not needs_overwrite_confirm("작업2", "작업1", exists=False)


# --------------------------------------------------------- overwrite_confirm_text
def test_overwrite_confirm_text_restates_actual_victim():
    """RC-15 P6 — 확인 문구는 실제 파괴 대상을 재진술한다(slug 충돌·손상 구분)."""
    same = overwrite_confirm_text("작업1", "작업1")
    assert "작업 '작업1' 이(가) 이미 있습니다" in same

    slug = overwrite_confirm_text("예산/2026", "예산_2026")
    assert "예산/2026" in slug and "예산_2026" in slug  # 입력·파괴 대상 모두 재진술

    corrupt = overwrite_confirm_text("작업1", "")
    assert "손상" in corrupt  # 이름 불명을 추측하지 않고 그대로 고지


# --------- 근본 조치(리뷰 3R): durable Job 필드의 **분류 완전성** 구조 가드 ---------
#: 에디터 저장이 세션 값으로 **다시 짓는** 필드 — 곧 편집기가 소유하는 규칙·정체다.
#: (구 default_dataset_ref 의 **이름 축**은 #347(U2 §5.3 판정 D)에서 폐기된 채다. U4-C 가
#:  되들인 결속은 경로+시트+헤더 행 세 성분이고 아래에 분류돼 있다.)
_EDITOR_REBUILDS = {
    "version", "name", "template_path", "mapping", "filename_pattern",
    # 데이터 결속 성분(U4 §2.4 · #932 U4-C) — 「다시 짓는다」 갈래다. 보존으로
    # 선언하면 편집기가 결속을 바꿀 수 없고(그것이 지금 유일한 동선이다),
    # 레지스트리 파생으로 선언하면 저장이 사용자가 고른 데이터를 발명하게 된다.
    # 종류 축(``data_kind``)도 같은 한 벌이라 같은 갈래다 — 저장이 세션 값을 그대로 싣는다.
    "data_path", "data_sheet", "data_header_row", "data_kind",
}
#: 저장이 **되싣는** 비-편집 메타 — `_preserved_meta` 가 소유한다.
_EDITOR_PRESERVES = {
    "tags", "last_run_at", "group", "favorited_at", "reviewed_rules", "authority_id",
}
#: 레지스트리가 **계산해 쓰는** 파생 메타(재작성 F7) — 어느 편집 표면도 값을 싣지 않고
#: :func:`~hwpxfiller.domain.job.advance_revisions` 가 저장 잠금 안에서 정산한다. 세 번째
#: 갈래를 만든 이유: 이 셋을 '보존'으로 선언하면 편집 세션이 든 옛 판본이 디스크의 최신
#: 세대를 되돌리고, '다시 짓는다'로 선언하면 편집기가 판본을 발명하게 된다.
_REGISTRY_DERIVES = {"template_revision", "binding_revision", "previous_rules"}


def test_every_durable_job_field_is_classified_by_the_editor_save():
    """durable Job 필드는 저장이 **다시 짓거나 보존하거나 계산하거나** 셋 중 하나여야 한다.

    같은 결함이 두 번 났다: 그룹이 조용히 초기화되던 자리(슬라이스 2)와 검토 기준선이
    비워지던 자리(재작성 F5 3R). 두 번이면 목록이 아니라 **규율**이 문제다 — 새 durable
    필드를 더할 때 어느 쪽인지 **선언하지 않으면** 여기서 걸린다. 선언을 강제하면 다음
    누락은 사람이 아니라 게이트가 잡는다.
    """
    from dataclasses import fields as dataclass_fields

    from hwpxfiller.domain.job import Job
    from hwpxfiller.webapp.screen_editor import _EMPTY_PRESERVED, _preserved_meta

    durable = {f.name for f in dataclass_fields(Job)}
    classified = _EDITOR_REBUILDS | _EDITOR_PRESERVES | _REGISTRY_DERIVES
    assert durable == classified, (
        "durable Job 필드가 분류되지 않았습니다 — 저장이 다시 짓는지(_EDITOR_REBUILDS) "
        "보존하는지(_EDITOR_PRESERVES + _preserved_meta) 레지스트리가 계산하는지"
        "(_REGISTRY_DERIVES) 선언하세요: "
        f"미분류={sorted(durable - classified)}, 유령={sorted(classified - durable)}"
    )
    # 세 갈래는 배타적이다 — 한 필드가 두 갈래에 들면 어느 쪽이 이기는지가 코드 순서에
    # 달리고, 그 순서는 리팩터링에 조용히 뒤집힌다.
    assert not (_EDITOR_REBUILDS & _EDITOR_PRESERVES)
    assert not (_REGISTRY_DERIVES & (_EDITOR_REBUILDS | _EDITOR_PRESERVES))
    # 선언과 실물이 갈리지 않게: 보존 목록의 두 표현(빈 기본값·추출기)이 같은 키를 든다.
    assert set(_EMPTY_PRESERVED) == _EDITOR_PRESERVES
    assert set(_preserved_meta(Job(name="x"))) == _EDITOR_PRESERVES


# ─────────────────────────────────────────────── 이름 기본값 도출(U6-D #978)
def test_derive_job_name_joins_both_names_with_the_middle_dot() -> None:
    """구분자는 가운뎃점이다 — em dash 는 문장 안 전면 금지(COPY_STYLE_GUIDE §3-1).

    라벨 문형과 이름 문형이 같은 글자를 두 뜻으로 쓰면 그 규칙이 자리마다 예외를 갖는다.
    """
    assert derive_job_name("공고서", "2026 하반기 계약") == "공고서 · 2026 하반기 계약"
    assert JOB_NAME_SEPARATOR == " · "


def test_derive_job_name_never_fills_the_missing_half() -> None:
    """한쪽만 있으면 그것 하나 — 없는 절반을 자리표시자로 채우면 저장본에 그대로 굳는다."""
    assert derive_job_name("공고서", "") == "공고서"
    assert derive_job_name("", "2026 하반기 계약") == "2026 하반기 계약"
    assert derive_job_name("", "") == ""


def test_derive_job_name_trims_so_a_blank_half_is_really_blank() -> None:
    """공백만 든 이름은 이름이 아니다 — 안 다듬으면 「 · 데이터」 같은 앞이 빈 이름이 선다."""
    assert derive_job_name("   ", "대장") == "대장"
    assert derive_job_name(" 공고서 ", " 대장 ") == "공고서 · 대장"
