"""작업 에디터 화면 컨트롤러 계약 가드 — pywebview/Qt 불필요(헤드리스).

에픽 #20 화면 #15·#16 이관의 회귀 심. 3단계 마법사 게이트(스키마·PARTIAL·매핑 확정·저장)를
링1 VM 그대로 구동해 창 없이 확인한다(R-flow 슬라이스 5 블록 2 — 데이터 선택이 매핑 단계
관문으로 접힘: 템플릿 0 → 매핑 1 → 저장 2). 실 HWPX 픽스처(COMPILED·PARTIAL)로 게이트 분기를 탄다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.core.job import JobRegistry
from hwpxfiller.gui.template_manager_state import TemplateManagerViewModel
from hwpxfiller.webapp.screen_editor import EditorController
from hwpxfiller.webapp.template_groups import TemplateGroupModel

REPO = Path(__file__).resolve().parents[1]
TPL_COMPILED = REPO / "tests" / "corpus" / "scenario" / "templates" / "구매요청서.hwpx"
TPL_PARTIAL = REPO / "tests" / "fixtures" / "template_v1.hwpx"
MULTI_SHEET = REPO / "tests" / "fixtures" / "multi_sheet.xlsx"


def _controller(tmp_path: Path) -> "tuple[EditorController, list]":
    pushes: list = []
    reg = JobRegistry(tmp_path / "jobs")
    # 빈 라이브러리 VM 주입 — 기본(표준 라이브러리 지연 생성)이 실 사용자 폴더를 스캔하면
    # 테스트가 개발 머신 상태에 좌우된다(PR-4 리뷰 F5: 격리·결정성).
    ctrl = EditorController(
        reg, lambda s, snap: pushes.append((s, snap)),
        template_library=TemplateManagerViewModel(paths=[]),
    )
    return ctrl, pushes


def test_compiled_template_opens_advance_gate(tmp_path):
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    snap = pushes[-1][1]
    assert snap["field_count"] == 10
    assert snap["gate"] is None and not snap["raw_block"]
    assert ctrl.can_advance(0) is True  # COMPILED → 진행 가능


def test_snapshot_exposes_structured_fields(tmp_path):
    """1단계 구조화 표(#16 98DDFE96) — 스냅샷이 필드별 명세를 실어야 한다.

    나열식 요약(schema_summary)은 헤더로 존치하되, 표 렌더가 소비할 fields 배열이
    필드 수만큼·정해진 키로 있어야 한다. 템플릿 로드 전엔 빈 배열.
    """
    ctrl, pushes = _controller(tmp_path)
    assert ctrl.snapshot()["fields"] == []  # 스키마 없으면 빈 배열
    ctrl.load_template_path(str(TPL_COMPILED))
    snap = pushes[-1][1]
    fields = snap["fields"]
    assert isinstance(fields, list) and len(fields) == snap["field_count"]
    assert snap["schema_summary"]  # 헤더 요약은 존치
    for f in fields:
        assert set(f) >= {"name", "inferred_type", "in_table", "occurrences", "context"}
        assert isinstance(f["name"], str) and f["name"]
        assert isinstance(f["in_table"], bool)


def test_snapshot_exposes_sample_rows_projected_and_capped(tmp_path):
    """2단계 데이터 미리보기(#16) — 스냅샷이 source_fields 순서로 투영한 샘플 행을 싣는다.

    데이터 로드 전엔 빈 배열, 로드 후엔 record_count 를 넘지 않는 소량(≤_SAMPLE_ROWS)의
    문자열 셀 행. 각 행 폭은 컬럼 수와 일치(투영 정합).
    """
    from hwpxfiller.webapp.screen_editor import _SAMPLE_ROWS

    ctrl, pushes = _controller(tmp_path)
    assert ctrl.snapshot()["sample_rows"] == []  # 데이터 없으면 빈 배열
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    snap = pushes[-1][1]
    cols = snap["source_fields"]
    sample = snap["sample_rows"]
    assert 0 < len(sample) <= min(snap["record_count"], _SAMPLE_ROWS)
    for row in sample:
        assert len(row) == len(cols)  # source_fields 순서로 정확히 투영
        assert all(isinstance(c, str) for c in row)  # 렌더 esc 안전 위해 문자열


def test_partial_template_blocks_until_acked(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_PARTIAL))
    assert ctrl.can_advance(0) is False  # PARTIAL → 게이트 닫힘
    gate = ctrl.snapshot()["gate"]
    assert gate and gate["unmet"] and not gate["acked"]
    # 게이트 미통과 상태에서 전진 요청은 시끄럽게 거부(confirm-or-alarm).
    with pytest.raises(ValueError, match="조건을 아직 채우지 못해"):
        ctrl.dispatch("goto_step", {"step": 1})
    ctrl.dispatch("ack_gate", {})
    assert ctrl.can_advance(0) is True
    assert ctrl.snapshot()["gate"]["acked"] is True


def test_load_data_honors_confirmed_sheet(tmp_path):
    """다중 시트 확정 게이트(#33) — load_data_path(sheet=) 가 확정 시트를 관통 로드.

    첫 시트(공고목록)가 아닌 낙찰현황을 확정하면 그 시트의 필드·레코드가 온다 —
    조용한 첫 시트 강등이 아니라 확정값이 반영됨을 못박는다.
    """
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    snap = pushes[-1][1]
    assert snap["source_fields"] == ["업체명", "낙찰금액", "계약일"]
    assert snap["record_count"] == 3
    # 대조군: 시트 미지정(None)은 첫 시트(공고목록) — 브리지가 모호할 때만 확정을 요구하므로
    # 컨트롤러 계약 자체는 None=첫/유일 시트로 유지된다.
    ctrl2, pushes2 = _controller(tmp_path)
    ctrl2.load_data_path(str(MULTI_SHEET))
    assert pushes2[-1][1]["source_fields"] == ["공고명", "추정가격"]


def test_full_new_job_flow_schema_only_const(tmp_path):
    """템플릿→매핑(관문 데이터 없이 진행, 상수 1행+비움 확정)→저장 end-to-end."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.dispatch("goto_step", {"step": 1})   # 매핑 진입(모델 초안 생성)
    ctrl.dispatch("skip_data", {})            # 관문 옵트아웃 — 데이터 없이 진행
    snap = ctrl.snapshot()
    assert snap["step"] == 1 and len(snap["rows"]) == 10 and snap["schema_only"] is True

    # 0행에 고정값 부여(내용 생성).
    ctrl.dispatch("set_type", {"index": 0, "type": "const"})
    ctrl.dispatch("set_const", {"index": 0, "const": "테스트값"})
    assert ctrl.snapshot()["rows"][0]["has_content"] is True

    # 모두 확정 → 내용 행 즉시 확정, 나머지는 비움 승격 후보로 반환(이름게이트).
    result = ctrl.dispatch("confirm_all", {})
    assert len(result["blanks"]) == 9
    assert ctrl.snapshot()["is_complete"] is False  # 비움 미확정
    ctrl.dispatch("confirm_blanks", {"fields": result["blanks"]})
    assert ctrl.snapshot()["is_complete"] is True

    # 저장.
    ctrl.dispatch("goto_step", {"step": 2})
    ctrl.dispatch("set_name", {"name": "테스트작업"})
    ctrl.dispatch("set_pattern", {"pattern": "문서-{{ID}}"})
    res = ctrl.dispatch("save", {})
    assert res["ok"] is True and res["saved_name"] == "테스트작업"
    assert JobRegistry(tmp_path / "jobs").exists("테스트작업")


def test_unconfirm_all_restores_exact_previous_confirmed_set(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.dispatch("goto_step", {"step": 1})
    ctrl.dispatch("skip_data", {})
    ctrl.dispatch("set_confirmed", {"index": 1, "confirmed": True})
    ctrl.dispatch("set_confirmed", {"index": 4, "confirmed": True})
    result = ctrl.dispatch("unconfirm_all", {})
    assert result == {"undo_count": 2}
    assert ctrl.snapshot()["unconfirm_undo_count"] == 2
    restored = ctrl.dispatch("restore_confirmed", {})
    assert restored == {"restored": 2}
    rows = ctrl.snapshot()["rows"]
    assert [i for i, row in enumerate(rows) if row["confirmed"]] == [1, 4]
    assert ctrl.snapshot()["unconfirm_undo_count"] == 0


def test_gateway_data_pick_rebuilds_mapping_in_place(tmp_path):
    """3단계 접기(블록 2 결정 11·12): 매핑 진입 후 관문에서 데이터를 고르면 매핑표가 그
    자리에서 다시 선다 — 컬럼·자동 제안 반영, 스키마온리 탈출, 전환 없음(라이브 순서 가드).

    헬퍼(_complete_with_data)는 데이터를 먼저 로드하고 진입하지만, 실 UX 는 진입 후 관문에서
    겨눔한다 — 그때 load_data_path 가 모델 존재를 보고 _ensure_model 로 재구성해야 한다.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.dispatch("goto_step", {"step": 1})              # 매핑 진입(데이터 전 — 스키마온리 모델)
    snap = ctrl.snapshot()
    assert snap["step"] == 1 and snap["schema_only"] is True
    assert snap["source_fields"] == [] and snap["rows"]  # 템플릿 필드는 이미 표에

    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")  # 관문에서 데이터 겨눔 → in-place 재구성
    snap = ctrl.snapshot()
    assert snap["step"] == 1                              # 여전히 매핑(단계 전환 없음)
    assert snap["schema_only"] is False                  # 데이터 반영 — 스키마온리 탈출
    assert snap["source_fields"] == ["업체명", "낙찰금액", "계약일"]
    assert snap["active_source_fields"] == ["업체명", "낙찰금액", "계약일"]  # 소스 후보 채워짐


def test_same_file_different_sheet_repick_demotes_confirmed(tmp_path):
    """3단계 접기 리뷰 F1 — 정체 키에 시트 포함: 같은 workbook 의 다른 시트로 관문 재겨눔할 때
    헤더명이 같아도 확정 매핑이 조용히 살아남지 않는다(조용한 게이트 우회 차단).

    두 시트의 헤더명이 같고(업체명·금액) 데이터만 다르면, data_sheet 를 키에서 빼면
    source_fields 불변→키 불변→_ensure_model 조기 반환→확정 유지→이전 시트 기준 저장·실행되는
    조용한 우회가 된다(슬라이스 4 '정체 키 성분 누락' 교훈). 시트를 키 성분으로 넣어 재구성·강등.
    """
    from openpyxl import Workbook

    xlsx = tmp_path / "twin_headers.xlsx"
    wb = Workbook()
    a = wb.active
    a.title = "1월"
    a.append(["업체명", "금액"])
    a.append(["갑상사", "100"])
    b = wb.create_sheet("2월")
    b.append(["업체명", "금액"])        # 동일 헤더명, 다른 데이터
    b.append(["을상사", "999"])
    wb.save(xlsx)

    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(xlsx), sheet="1월")
    ctrl.dispatch("goto_step", {"step": 1})            # 매핑 진입(1월 데이터)
    ctrl.dispatch("set_source", {"index": 0, "source": "금액"})
    r = ctrl.dispatch("confirm_all", {})
    ctrl.dispatch("confirm_blanks", {"fields": r["blanks"]})
    assert ctrl.snapshot()["is_complete"] is True

    ctrl.load_data_path(str(xlsx), sheet="2월")         # 같은 파일 다른 시트로 관문 재겨눔
    snap = ctrl.snapshot()
    assert snap["is_complete"] is False                # 확정이 조용히 살아남지 않음(재구성)
    assert all(row["confirmed"] is False for row in snap["rows"])
    assert snap["notice"] and "다시 확정" in snap["notice"]["text"]


def test_save_gate_blocks_incomplete_and_unnamed(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.dispatch("skip_data", {})
    # 미확정 매핑 → 저장 차단(구체 사유 재진술).
    res = ctrl.dispatch("save", {})
    assert res["ok"] is False and "확정" in res["block_reason"]
    # 전부 비움 확정(내용 0) → 이름 있어도 '채울 값 없음' 차단.
    ctrl.dispatch("confirm_all", {})
    blanks = ctrl.snapshot()  # confirm_all 이 content 0 → 모두 blanks
    ctrl.dispatch("confirm_blanks", {"fields": [r["template_field"] for r in blanks["rows"]]})
    ctrl.dispatch("set_name", {"name": "빈작업"})
    ctrl.dispatch("set_pattern", {"pattern": "x-{{ID}}"})
    res = ctrl.dispatch("save", {})
    assert res["ok"] is False and "비움" in res["block_reason"]


def test_overwrite_confirm_flow(tmp_path):
    ctrl, _ = _controller(tmp_path)
    # 첫 저장.
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.dispatch("skip_data", {})
    ctrl.dispatch("set_type", {"index": 0, "type": "const"})
    ctrl.dispatch("set_const", {"index": 0, "const": "v"})
    r = ctrl.dispatch("confirm_all", {})
    ctrl.dispatch("confirm_blanks", {"fields": r["blanks"]})
    ctrl.dispatch("set_name", {"name": "중복작업"})
    ctrl.dispatch("set_pattern", {"pattern": "p-{{ID}}"})
    assert ctrl.dispatch("save", {})["ok"] is True

    # **새 세션**에서 같은 이름 저장 → 덮어쓰기 확인 요구(조용한 덮어쓰기 금지).
    # 저장 착지가 편집 세션이 된 뒤(PR-2 리뷰 F2)로는 같은 세션의 같은 이름 재저장은
    # 자기-갱신(확인 불요)이 맞다 — 충돌 시나리오는 새 세션으로 재현한다.
    ctrl.dispatch("new_session", {})
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.dispatch("skip_data", {})
    ctrl.dispatch("set_type", {"index": 0, "type": "const"})
    ctrl.dispatch("set_const", {"index": 0, "const": "v2"})
    r = ctrl.dispatch("confirm_all", {})
    ctrl.dispatch("confirm_blanks", {"fields": r["blanks"]})
    ctrl.dispatch("set_name", {"name": "중복작업"})
    ctrl.dispatch("set_pattern", {"pattern": "p-{{ID}}"})
    res = ctrl.dispatch("save", {})
    assert res["ok"] is False and res.get("needs_overwrite") is True
    assert "덮어" in res["overwrite_text"]
    # 확인 후 재호출 → 저장.
    assert ctrl.dispatch(
        "save", {"confirm_overwrite": True, "confirmed_overwrite_text": res["overwrite_text"]}
    )["ok"] is True


def _save_named(ctrl: EditorController, name: str) -> dict:
    """이름 하나로 새 작업을 저장하는 최소 흐름(테스트 헬퍼)."""
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.dispatch("skip_data", {})
    ctrl.dispatch("set_type", {"index": 0, "type": "const"})
    ctrl.dispatch("set_const", {"index": 0, "const": "v"})
    r = ctrl.dispatch("confirm_all", {})
    ctrl.dispatch("confirm_blanks", {"fields": r["blanks"]})
    ctrl.dispatch("set_name", {"name": name})
    ctrl.dispatch("set_pattern", {"pattern": "p-{{ID}}"})
    return ctrl.dispatch("save", {})


def test_slug_collision_different_name_restates_victim_then_saves(tmp_path):
    """다른 이름이 같은 slug 로 충돌하면 victim 을 재진술 확인하고, 확정 시 저장된다(#1).

    core 가드가 확정 저장 경로에서 allow_overwrite=True 로 통과하는지까지 검증 —
    확인했는데 JobSlugCollisionError 로 터지면 흐름이 깨진다.
    """
    ctrl, _ = _controller(tmp_path)
    assert _save_named(ctrl, "예산/2026")["ok"] is True

    res = _save_named(ctrl, "예산_2026")  # slug 동일 → 충돌
    assert res["ok"] is False and res.get("needs_overwrite") is True
    # 입력 이름·victim 이름이 모두 재진술된다(거짓 확인 방지).
    assert "예산_2026" in res["overwrite_text"] and "예산/2026" in res["overwrite_text"]
    # 확정 → allow_overwrite 로 core 가드 통과, 저장 성공(크래시 없음).
    assert ctrl.dispatch(
        "save", {"confirm_overwrite": True, "confirmed_overwrite_text": res["overwrite_text"]}
    )["ok"] is True
    assert JobRegistry(tmp_path / "jobs").exists("예산_2026")


def test_unknown_editor_action_is_loud(tmp_path):
    ctrl, _ = _controller(tmp_path)
    with pytest.raises(ValueError, match="알 수 없는 editor 액션"):
        ctrl.dispatch("frobnicate", {})


# ------------------------------------------------------------ #25 세션 혼합 방지
def _build_complete_session(ctrl, name: str) -> None:
    """COMPILED 템플릿으로 저장 가능한 완결 세션 구성(저장 직전까지) — 혼합 테스트 준비."""
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.dispatch("skip_data", {})
    ctrl.dispatch("set_type", {"index": 0, "type": "const"})
    ctrl.dispatch("set_const", {"index": 0, "const": "v"})
    r = ctrl.dispatch("confirm_all", {})
    ctrl.dispatch("confirm_blanks", {"fields": r["blanks"]})
    ctrl.dispatch("goto_step", {"step": 2})
    ctrl.dispatch("set_name", {"name": name})
    ctrl.dispatch("set_pattern", {"pattern": "p-{{ID}}"})


def test_has_unsaved_work_tracks_session_lifecycle(tmp_path):
    ctrl, _ = _controller(tmp_path)
    assert ctrl.has_unsaved_work() is False              # 갓 초기화 — 버릴 것 없음
    ctrl.load_template_path(str(TPL_COMPILED))
    assert ctrl.has_unsaved_work() is False              # 템플릿만 로드 — 아직 세션 아님
    ctrl.dispatch("skip_data", {})                       # 매핑 모델 생성 → 진행 중 세션
    assert ctrl.has_unsaved_work() is True
    assert ctrl.snapshot()["has_unsaved_work"] is True   # 스냅샷에도 노출(웹 확인 판단용)


def test_new_job_session_atomically_clears_prior_session(tmp_path):
    """템플릿 A 진행 세션 → new_job_session(B) 는 이름·데이터·매핑·단계를 원자 초기화(#25)."""
    ctrl, _ = _controller(tmp_path)
    _build_complete_session(ctrl, "작업A")
    assert ctrl.snapshot()["is_complete"] is True and ctrl.has_unsaved_work() is True

    ctrl.new_job_session(str(TPL_PARTIAL))               # 다른 템플릿으로 새 세션
    snap = ctrl.snapshot()
    assert snap["step"] == 0                             # 단계 초기화
    assert snap["name"] == ""                            # 이름 소거(A 잔존 없음)
    assert snap["rows"] == [] and snap["is_complete"] is False  # 구 매핑 모델 폐기
    assert snap["data_path"] == ""                       # 데이터 소거


def test_new_job_session_prevents_mixed_save(tmp_path):
    """A 완결 세션 후 저장 전 B 진입 → 저장 시 구 모델이 없어 시끄럽게 차단(혼합 오저장 불가)."""
    ctrl, _ = _controller(tmp_path)
    _build_complete_session(ctrl, "작업A")
    ctrl.new_job_session(str(TPL_COMPILED))              # 저장 없이 새 세션(같은 템플릿이어도 초기화)
    res = ctrl.dispatch("save", {})
    assert res["ok"] is False and "확정" in res["block_reason"]  # 모델 리셋 → 미확정 차단


def test_new_session_action_resets_prior_session(tmp_path):
    """홈 「＋ 새 작업」의 new_session 액션 — 진행 세션 전량 초기화(F10).

    종전 홈 버튼은 bare nav 라 직전 세션(이름·데이터·매핑·단계)이 그대로 복원돼
    라벨 '새'가 사실상 '이전 작성 계속'이었다. 초기화 뒤엔 미저장 판정도 소거된다
    (방금 저장 직후처럼 — 다음 「새 작업」이 불필요한 확인을 띄우지 않게).
    """
    from hwpxfiller.core.job import DEFAULT_FILENAME_PATTERN

    ctrl, pushes = _controller(tmp_path)
    _build_complete_session(ctrl, "작업A")
    assert ctrl.has_unsaved_work() is True
    ctrl.dispatch("new_session", {})
    snap = pushes[-1][1]                                 # dispatch 말미 자동 푸시
    assert ctrl.has_unsaved_work() is False
    assert snap["step"] == 0 and snap["name"] == ""
    assert snap["rows"] == [] and snap["data_path"] == ""
    assert snap["pattern"] == DEFAULT_FILENAME_PATTERN   # 패턴도 기본으로 복원


def test_discard_session_cancels_new_wizard_but_rejects_saved_edit(tmp_path):
    """신규 마법사 취소는 휘발 상태를 실제 폐기하고, 저장 작업 편집에는 오용되지 않는다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.dispatch("goto_step", {"step": 1})
    assert ctrl.has_unsaved_work() is True
    ctrl.dispatch("discard_session", {})
    snap = ctrl.snapshot()
    assert snap["step"] == 0 and ctrl.template_path == "" and ctrl.model is None
    assert ctrl.has_unsaved_work() is False

    # 편집 모드는 별도 비파괴 복귀 계약(T2)을 쓰며 신규 취소 액션으로 닫을 수 없다.
    ctrl._editing_origin = "저장작업"
    with pytest.raises(ValueError, match="저장된 작업 편집"):
        ctrl.dispatch("discard_session", {})


# --------------------------------------------------- #16 1·2단계 구조화 렌더 가드
_EDITOR_JS = REPO / "web" / "js" / "screens" / "editor.js"


def test_editor_renders_structured_field_and_data_tables():
    """1·2단계가 나열식 텍스트가 아니라 구조화 표로 렌더돼야 한다(#16 98DDFE96).

    나열식 `.fields-line` 은 제거되고, 1단계는 `schema-fields` 표·2단계는 `data-preview`
    표로 승격. 빈 셀은 ADR-B 대로 "(빈 값)"으로 시끄럽게 표기한다. 실 렌더 되읽기는
    selftest 게이트가 하고, 여기선 마크업 배선의 존재/부재를 정적으로 가드한다.
    """
    src = _EDITOR_JS.read_text(encoding="utf-8")
    assert "fields-line" not in src, "나열식 .fields-line 이 남아 있습니다 — 구조화 표로 교체(#16)."
    assert 'class="schema-fields"' in src, "1단계 필드 구조화 표(schema-fields)가 없습니다(#16)."
    assert 'class="data-preview"' in src, "2단계 데이터 미리보기 표(data-preview)가 없습니다(#16)."
    assert "(빈 값)" in src, "2단계 빈 셀의 시끄러운 표기가 없습니다 — ADR-B 위반(#16)."


def test_save_blocks_when_model_schema_mismatches_template(tmp_path):
    """방어층: 모델이 현재 스키마와 어긋나면(혼합) 저장을 시끄럽게 차단(#25 항목4)."""
    ctrl, _ = _controller(tmp_path)
    _build_complete_session(ctrl, "작업A")               # 모델 = COMPILED 스키마
    # new_job_session 을 우회해 low-level 로 스키마만 교체(구버그 경로 재현) → 모델은 A 그대로.
    ctrl.load_template_path(str(TPL_PARTIAL))
    res = ctrl.dispatch("save", {})
    assert res["ok"] is False and "일치하지 않습니다" in res["block_reason"]


# ============================================================ #26 패리티 회수
# 편집 모드(#1)·선언 데이터 자동등록(#3)의 헤드리스 계약.
from hwpxfiller.core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry
from hwpxfiller.core.job import Job
from hwpxfiller.core.mapping import FieldMapping, MappingProfile


def _controller26(tmp_path: Path):
    """레지스트리(작업·풀)를 tmp 로 격리 주입한 컨트롤러."""
    pushes: list = []
    ctrl = EditorController(
        JobRegistry(tmp_path / "jobs"),
        lambda s, snap: pushes.append((s, snap)),
        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
        template_library=TemplateManagerViewModel(paths=[]),
    )
    return ctrl, pushes


# ------------------------------------------------------------ 편집 모드(#1)
def test_load_job_restores_edit_session(tmp_path):
    """저장 작업 → load_job: 이름·패턴·확정 매핑·단계가 복원되고 원점이 기록된다."""
    ctrl, _ = _controller26(tmp_path)
    assert _save_named(ctrl, "원본작업")["ok"] is True   # 저장 후 세션 리셋

    ctrl.load_job("원본작업")
    snap = ctrl.snapshot()
    assert snap["step"] == 1                             # 매핑 확정 단계로 착지(3단계 접기)
    assert snap["name"] == "원본작업"
    assert snap["editing_origin"] == "원본작업"
    assert snap["is_complete"] is True                   # 1 const + 9 blank 전부 확정 복원
    assert snap["rows"][0]["type"] == "const" and snap["rows"][0]["const"] == "v"
    assert snap["notice"] and "편집합니다" in snap["notice"]["text"]


def test_new_session_action_clears_edit_mode(tmp_path):
    """편집 모드 중 「＋ 새 작업」(new_session) — 편집 원점·복원 notice 까지 소거(F10).

    남으면 새 세션 저장이 '원본작업' 자기-갱신으로 오판되거나 편집 배너가 거짓으로 남는다.
    """
    ctrl, pushes = _controller26(tmp_path)
    _save_named(ctrl, "원본작업")
    ctrl.load_job("원본작업")
    assert ctrl.snapshot()["editing_origin"] == "원본작업"
    ctrl.dispatch("new_session", {})
    snap = pushes[-1][1]
    assert snap["editing_origin"] == "" and snap["name"] == ""
    assert snap["notice"] is None                        # 편집 모드 배너 소거
    assert ctrl.has_unsaved_work() is False


def test_load_job_model_survives_step_navigation(tmp_path):
    """_model_key 함정 봉쇄 — 복원 직후 단계를 오가도 확정 매핑이 초안으로 대체되지 않는다."""
    ctrl, _ = _controller26(tmp_path)
    _save_named(ctrl, "이동작업")
    ctrl.load_job("이동작업")
    ctrl.dispatch("goto_step", {"step": 2})              # 저장 단계로
    ctrl.dispatch("goto_step", {"step": 1})              # 다시 매핑 진입(_ensure_model 경유)
    snap = ctrl.snapshot()
    assert snap["is_complete"] is True                   # 확정 유지(재생성 아님)
    assert snap["rows"][0]["const"] == "v"


def test_load_job_missing_template_is_loud(tmp_path):
    """템플릿 파일이 사라진 작업의 편집 열기는 조용히 반쯤 열리지 않고 시끄럽게 거절."""
    ctrl, _ = _controller26(tmp_path)
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="유실", template_path=str(tmp_path / "없는파일.hwpx")))
    with pytest.raises(ValueError, match="찾을 수 없습니다"):
        ctrl.load_job("유실")


def test_load_job_template_drift_is_restated(tmp_path):
    """저장 매핑에 있으나 현 스키마에 없는 필드는 조용히 누락되지 않고 notice 로 재진술."""
    ctrl, _ = _controller26(tmp_path)
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(
        name="드리프트",
        template_path=str(TPL_COMPILED),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="유령필드", source="", type="const", const="x"),
        ]),
    ))
    ctrl.load_job("드리프트")
    snap = ctrl.snapshot()
    assert snap["notice"]["level"] == "warn"
    assert "유령필드" in snap["notice"]["text"]          # 제외 필드 이름 재진술
    assert snap["is_complete"] is False                  # 새 스키마 필드는 미확정(사람 확정 필요)


def test_edit_save_self_update_skips_overwrite_and_preserves_meta(tmp_path):
    """편집 원점 그대로 재저장 = 자기-갱신(확인 불요) + 태그·마지막 실행 메타 보존."""
    ctrl, _ = _controller26(tmp_path)
    _save_named(ctrl, "메타작업")
    reg = JobRegistry(tmp_path / "jobs")
    job = reg.load("메타작업")
    job.tags = {"물품": "의약품"}
    job.last_run_at = "2026-07-01T09:00:00"
    reg.save(job, allow_overwrite=True)

    ctrl.load_job("메타작업")
    res = ctrl.dispatch("save", {})                      # 같은 이름 재저장
    assert res["ok"] is True                             # needs_overwrite 없이 통과(자기-갱신)
    saved = reg.load("메타작업")
    assert saved.tags == {"물품": "의약품"}              # 태그 조용한 소실 없음
    assert saved.last_run_at == "2026-07-01T09:00:00"


def test_edit_save_holds_the_registry_write_lock(tmp_path):
    """저장의 재읽기~쓰기 구간이 **레지스트리 공유 잠금 안**에 있다(#129 리뷰 2R P1).

    보존 값(태그·last_run_at)을 읽은 뒤 저장까지 사이에 생성 스레드의 스탬프가 끼면, 여기서
    만든 Job 이 방금 찍힌 시각을 낡은 값으로 되돌린다. 저장 한 번만 원자적인 것으로는 못 막아
    구간 전체가 잠겨야 하므로, 저장 시점에 잠금이 **다른 스레드에서 잡히지 않는지**로 되읽는다.
    """
    import threading

    ctrl, _ = _controller26(tmp_path)
    _save_named(ctrl, "잠금작업")
    ctrl.load_job("잠금작업")
    seen: "list[bool]" = []
    real_save = ctrl.registry.save

    def spy(job, **kw):
        got = [None]

        def probe():  # 다른 스레드에서 비차단 획득 시도 — 잠겨 있으면 실패해야 한다
            lock = ctrl.registry.write_lock()
            got[0] = lock.acquire(blocking=False)
            if got[0]:
                lock.release()

        t = threading.Thread(target=probe)
        t.start()
        t.join(3)
        seen.append(bool(got[0]))
        return real_save(job, **kw)

    ctrl.registry.save = spy  # type: ignore[method-assign]
    assert ctrl.dispatch("save", {})["ok"] is True
    assert seen and not any(seen), "저장 구간이 쓰기 잠금 밖입니다 — lost update 회귀."


def test_edit_save_renamed_still_confirms_overwrite(tmp_path):
    """편집 중 이름을 다른 기존 작업으로 바꾸면 평소처럼 덮어쓰기 확인을 요구."""
    ctrl, _ = _controller26(tmp_path)
    _save_named(ctrl, "작업일")
    _save_named(ctrl, "작업이")
    ctrl.load_job("작업일")
    ctrl.dispatch("set_name", {"name": "작업이"})        # 다른 작업을 겨냥
    res = ctrl.dispatch("save", {})
    assert res["ok"] is False and res.get("needs_overwrite") is True


def test_ensure_model_carries_values_but_requires_reconfirm_on_data_change(tmp_path):
    """데이터 교체 시 값(소스·유형·서식)은 제안으로 이월하되 확정은 전원 해제(r3 C1).

    이전 확정을 확정 상태 그대로 되살리면 같은 이름 컬럼('금액' 등)이 의미가 다른 새
    데이터에서 사람 검토 없이 ``is_complete`` 를 통과해 저장·실행까지 흐른다 — 구
    불변식 '키 변경 시 전원 미확정 초안'을 복원하고 notice 로 재확정 필요를 재진술한다.

    3단계 접기(블록 2): 데이터 교체는 매핑 단계 관문에서 일어나 **그 자리에서** 모델을
    다시 세운다(load_data_path 가 모델 존재 시 _ensure_model 호출) — 단계 왕복 없이 in-place.
    """
    ctrl, _ = _controller26(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.dispatch("skip_data", {})                       # 매핑 진입(데이터 없이, 모델 생성)
    ctrl.dispatch("set_type", {"index": 0, "type": "const"})
    ctrl.dispatch("set_const", {"index": 0, "const": "보존값"})
    r = ctrl.dispatch("confirm_all", {})
    ctrl.dispatch("confirm_blanks", {"fields": r["blanks"]})
    assert ctrl.snapshot()["is_complete"] is True

    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")  # 관문에서 데이터 겨눔 → in-place 재생성
    snap = ctrl.snapshot()
    assert snap["rows"][0]["const"] == "보존값"          # 값 이월(조용한 소실 없음)
    assert snap["rows"][0]["type"] == "const"
    assert all(row["confirmed"] is False for row in snap["rows"])  # 확정 전원 해제
    assert snap["is_complete"] is False                  # 재확정 없이는 저장 게이트 미통과
    assert snap["notice"] and "다시 확정" in snap["notice"]["text"]
    assert "다시 확정" in snap["notice"]["text"]         # 재확정 필요를 loud 재진술


# ------------------------------------------------------- 선언 데이터 자동등록(#3)
def _complete_with_data(ctrl, name: str) -> None:
    """데이터(다중시트 확정) 연결 세션을 저장 직전까지 구성."""
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    ctrl.dispatch("goto_step", {"step": 1})   # 매핑 진입(데이터 겨눔 상태 — 3단계 접기)
    ctrl.dispatch("set_type", {"index": 0, "type": "const"})
    ctrl.dispatch("set_const", {"index": 0, "const": "v"})
    r = ctrl.dispatch("confirm_all", {})
    ctrl.dispatch("confirm_blanks", {"fields": r["blanks"]})
    ctrl.dispatch("set_name", {"name": name})
    ctrl.dispatch("set_pattern", {"pattern": "p-{{ID}}"})


def test_save_autoregisters_declared_dataset_with_sheet(tmp_path):
    """저장 시 선언 데이터가 참조(경로+확정 시트)로 자동등록된다 — 행·내용 없음."""
    ctrl, _ = _controller26(tmp_path)
    _complete_with_data(ctrl, "데이터작업")
    assert ctrl.snapshot()["dataset_name"] == "multi_sheet"   # 기본 이름 = 파일 스템
    res = ctrl.dispatch("save", {})
    assert res["ok"] is True and res["dataset_registered"] == "multi_sheet"
    item = DatasetPoolRegistry(tmp_path / "pool").load("multi_sheet")
    assert item.kind == "excel" and item.is_active
    assert item.opts["path"] == str(MULTI_SHEET)
    assert item.opts["sheet"] == "낙찰현황"                   # 확정 시트 동봉(모호 참조 방지)
    assert "records" not in item.opts                         # 행 미저장 불변식


def test_save_without_data_registers_nothing(tmp_path):
    ctrl, _ = _controller26(tmp_path)
    res = _save_named(ctrl, "무데이터")
    assert res["ok"] is True and res["dataset_registered"] == ""
    assert DatasetPoolRegistry(tmp_path / "pool").list_items() == []


def test_save_dataset_same_name_requires_confirm(tmp_path):
    """동명 기존 등록 데이터는 조용한 opts 덮어쓰기가 아니라 확인 승격(기존 참조 재진술)."""
    pool = DatasetPoolRegistry(tmp_path / "pool")
    pool.save(DatasetPoolItem(name="multi_sheet", kind="excel", opts={"path": "old.xlsx"}))
    ctrl, _ = _controller26(tmp_path)
    _complete_with_data(ctrl, "충돌작업")
    res = ctrl.dispatch("save", {})
    assert res["ok"] is False and res.get("needs_dataset_confirm") is True
    assert "old.xlsx" in res["dataset_text"]                  # 기존 참조 재진술(거짓 확인 방지)
    assert not JobRegistry(tmp_path / "jobs").exists("충돌작업")  # 반저장 없음(선차단)
    res2 = ctrl.dispatch("save", {"confirm_dataset": True})
    assert res2["ok"] is True
    assert pool.load("multi_sheet").opts["path"] == str(MULTI_SHEET)


def test_save_dataset_confirm_does_not_resurrect_concurrently_deleted_item(tmp_path):
    """자동등록 확인 중 삭제된 참조는 작업 저장이나 데이터셋 재생성 없이 다시 판정한다."""
    pool = DatasetPoolRegistry(tmp_path / "pool")
    pool.save(DatasetPoolItem(name="multi_sheet", kind="excel", opts={"path": "old.xlsx"}))
    ctrl, _ = _controller26(tmp_path)
    _complete_with_data(ctrl, "삭제경합작업")
    first = ctrl.dispatch("save", {})
    assert first.get("needs_dataset_confirm") is True

    DatasetPoolRegistry(pool.directory).delete("multi_sheet")
    second = ctrl.dispatch("save", {"confirm_dataset": True})

    assert second["ok"] is False and "삭제" in second["dataset_error"]
    assert not pool.exists("multi_sheet")
    assert not JobRegistry(tmp_path / "jobs").exists("삭제경합작업")


def test_save_dataset_slug_collision_demands_rename(tmp_path):
    """다른 이름·같은 slug 는 덮어쓰기 경로 없이 이름 변경만 안내(소유 항목 보호)."""
    pool = DatasetPoolRegistry(tmp_path / "pool")
    pool.save(DatasetPoolItem(name="multi/sheet", kind="excel", opts={"path": "x.xlsx"}))
    ctrl, _ = _controller26(tmp_path)
    _complete_with_data(ctrl, "슬러그작업")
    res = ctrl.dispatch("save", {})
    assert res["ok"] is False and "같은 파일" in res["dataset_error"]
    assert not JobRegistry(tmp_path / "jobs").exists("슬러그작업")
    # 이름을 바꾸면 통과.
    ctrl.dispatch("set_dataset_name", {"name": "낙찰데이터"})
    res2 = ctrl.dispatch("save", {})
    assert res2["ok"] is True and res2["dataset_registered"] == "낙찰데이터"


# ------------------------------------------------------- 매핑 프로파일 제거(F22)
def test_profile_actions_are_gone_loudly(tmp_path):
    """구 매핑 프로파일 액션(_do_profile_*)은 미지 액션으로 시끄럽게 거절된다(F22).

    작업이 매핑을 자족 저장·복원하므로 별도 프로파일 저장 개념은 제거 — 재사용은
    「작업 복제」(홈 clone_job)로 수렴한다. 조용한 no-op 잔존이 아니라 표면째 소멸.
    """
    ctrl, _ = _controller26(tmp_path)
    for action in ("profile_list", "profile_apply", "profile_save", "profile_delete"):
        with pytest.raises(ValueError, match="알 수 없는 editor 액션"):
            ctrl.dispatch(action, {"name": "x"})


def test_old_job_json_with_base_mapping_name_still_loads(tmp_path):
    """구 JSON 의 base_mapping_name(제거된 J3 계보 메타)은 미지 키로 무시된다 — 하위호환."""
    ctrl, _ = _controller26(tmp_path)
    assert _save_named(ctrl, "구식작업")["ok"] is True
    reg = JobRegistry(tmp_path / "jobs")
    path = reg.path_for("구식작업")
    import json as _json
    payload = _json.loads(path.read_text(encoding="utf-8"))
    payload["base_mapping_name"] = "지워진베이스"          # 구버전이 남긴 키 시뮬레이션
    path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    job = reg.load("구식작업")                              # loud raise 없이 로드
    assert job.name == "구식작업"
    assert "base_mapping_name" not in job.to_dict()         # 재저장 시 키 소멸


def test_edit_save_preserves_concurrent_home_tag_edit(tmp_path):
    """편집 세션이 열린 사이 홈에서 단 태그를, 에디터 저장이 stale 스냅샷으로 되돌리지 않는다(#26 #2·#5).

    load_job 시점 태그 스냅샷이 아니라 저장 직전 디스크 상태를 재읽어 보존해야 한다.
    """
    ctrl, _ = _controller26(tmp_path)
    _save_named(ctrl, "태그작업")
    ctrl.load_job("태그작업")                       # 에디터가 빈 태그 스냅샷을 뜬다
    # 편집 세션이 열린 사이 홈 태그 편집(같은 레지스트리 디스크 갱신)을 시뮬레이션.
    reg = JobRegistry(tmp_path / "jobs")
    job = reg.load("태그작업")
    job.tags = {"물품": "의약품"}
    reg.save(job, allow_overwrite=True)

    assert ctrl.dispatch("save", {})["ok"] is True   # 아직 열린 편집 세션 저장
    assert reg.load("태그작업").tags == {"물품": "의약품"}   # 조용한 소실 없음


def test_autoregister_preserves_archived_status_and_note(tmp_path):
    """자동등록이 기존 보관 데이터셋을 조용히 재활성화하거나 메모를 지우지 않는다(#26 #6).

    확인 문구는 참조 덮어쓰기만 재진술하므로, 상태·메모는 건드리지 않는 것이 문구와 일치한다.
    """
    pool = DatasetPoolRegistry(tmp_path / "pool")
    prior = DatasetPoolItem(
        name="multi_sheet", kind="excel", opts={"path": "old.xlsx"}, note="계약 종료분")
    prior.archive()
    pool.save(prior)

    ctrl, _ = _controller26(tmp_path)
    _complete_with_data(ctrl, "재사용작업")           # dataset_name 기본 = multi_sheet(스템)
    res = ctrl.dispatch("save", {"confirm_dataset": True})   # 동명 → 확인 승격 확정
    assert res["ok"] is True and res["dataset_registered"] == "multi_sheet"

    item = pool.load("multi_sheet")
    assert item.status == "archived"                  # 재활성화 없음(수명 상태 보존)
    assert item.note == "계약 종료분"                  # 메모 보존
    assert item.opts["path"] == str(MULTI_SHEET)      # 참조(opts)만 갱신
    assert item.opts["sheet"] == "낙찰현황"


# ------------------------------------------------- 작성 출처 provenance(#53-C)
def test_save_stamps_provenance_on_mapping(tmp_path):
    """저장 시 매핑에 작성 출처 지문(템플릿·데이터·스키마·시각)이 새겨진다(#53-C)."""
    ctrl, _ = _controller26(tmp_path)
    _complete_with_data(ctrl, "출처작업")
    ctrl.dispatch("save", {})
    prov = JobRegistry(tmp_path / "jobs").load("출처작업").mapping.provenance
    assert prov["template"].endswith(".hwpx")
    assert prov["dataset"] == "multi_sheet"
    assert prov["template_fields"]                    # 템플릿 스키마 지문
    assert prov["authored_at"] and prov["updated_at"]  # 작성/갱신 시각
    # 순수 메타 — 실행 계약(source_keys)과 별개 축.
    assert isinstance(prov, dict)


def test_edit_save_preserves_authored_at_updates_updated_at(tmp_path):
    """편집 재저장은 최초 작성시각(authored_at)을 보존하고 updated_at 만 갱신한다(#53-C)."""
    ctrl, _ = _controller26(tmp_path)
    _complete_with_data(ctrl, "출처편집")
    ctrl.dispatch("save", {})
    first = JobRegistry(tmp_path / "jobs").load("출처편집").mapping.provenance
    authored = first["authored_at"]

    ctrl.load_job("출처편집")
    assert ctrl.snapshot()["provenance"]["template"].endswith(".hwpx")  # 편집 모드 표시
    ctrl.dispatch("set_pattern", {"pattern": "새-{{ID}}"})
    ctrl.dispatch("save", {"confirm_overwrite": True})
    second = JobRegistry(tmp_path / "jobs").load("출처편집").mapping.provenance
    assert second["authored_at"] == authored          # 최초 작성시각 보존


def test_new_session_has_no_provenance(tmp_path):
    """저장 전(신규 세션)엔 표시할 작성 출처가 없다."""
    ctrl, _ = _controller26(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    assert ctrl.snapshot()["provenance"] is None


# ------------------------------------------- 기본 데이터셋 연결(#53-A)
def test_save_with_data_links_default_dataset_ref(tmp_path):
    """데이터를 골라 저장하면 자동등록 이름이 작업의 기본 데이터셋 참조로 연결된다(#53-A)."""
    ctrl, _ = _controller26(tmp_path)
    _complete_with_data(ctrl, "연결작업")             # dataset_name 기본 = multi_sheet(스템)
    res = ctrl.dispatch("save", {})
    assert res["ok"] is True and res["dataset_registered"] == "multi_sheet"
    job = JobRegistry(tmp_path / "jobs").load("연결작업")
    assert job.default_dataset_ref == "multi_sheet"   # 자동등록 이름과 연결


def test_save_without_data_leaves_default_ref_empty(tmp_path):
    """데이터 없이 저장한 작업은 기본 데이터셋 참조가 비어 있다(현행 수동 선택 유지)."""
    ctrl, _ = _controller26(tmp_path)
    _save_named(ctrl, "무데이터작업")
    assert JobRegistry(tmp_path / "jobs").load("무데이터작업").default_dataset_ref == ""


def test_edit_save_without_new_data_preserves_default_ref(tmp_path):
    """편집 저장 시 데이터를 새로 안 고르면 기존 기본 데이터셋 참조가 보존된다(#53-A).

    데이터를 다시 로드하지 않으므로 data_path 는 비어 있다 — 그때 참조를 "" 로 덮으면
    편집 한 번에 기본 데이터 연결이 조용히 소실된다(태그·이력 보존 선례와 동형)."""
    ctrl, _ = _controller26(tmp_path)
    _complete_with_data(ctrl, "편집대상")
    ctrl.dispatch("save", {})
    assert JobRegistry(tmp_path / "jobs").load("편집대상").default_dataset_ref == "multi_sheet"

    ctrl.load_job("편집대상")                          # 데이터 없이 편집 세션 복원
    ctrl.dispatch("set_pattern", {"pattern": "새패턴-{{ID}}"})
    res = ctrl.dispatch("save", {"confirm_overwrite": True})
    assert res["ok"] is True
    job = JobRegistry(tmp_path / "jobs").load("편집대상")
    assert job.default_dataset_ref == "multi_sheet"   # 편집 저장에도 보존
    assert job.filename_pattern == "새패턴-{{ID}}"


def test_save_links_ref_even_when_dataset_register_fails(tmp_path):
    """등록 실패(반저장)해도 작업의 기본 데이터 참조는 저장되고, 실패 문구가 연결 완성
    경로를 안내한다(#53-A 리뷰) — 참조 이름이 안정적이라 그 이름으로 수동 등록하면 링크 완성."""
    ctrl, _ = _controller26(tmp_path)
    _complete_with_data(ctrl, "등록실패작업")

    def _boom(*a, **k):
        raise OSError("디스크 꽉 참")
    ctrl.pool_registry.save = _boom                    # 데이터셋 등록만 실패시킴

    res = ctrl.dispatch("save", {})
    assert res["ok"] is True                           # 작업 저장 자체는 성공(반저장)
    assert "기본 데이터로 연결" in res["dataset_register_error"]
    # 참조는 저장됨 — 사용자가 같은 이름으로 등록하면 연결이 완성된다.
    assert JobRegistry(tmp_path / "jobs").load("등록실패작업").default_dataset_ref == "multi_sheet"


# ------------------------------------------------- 사용할 헤더 선택(#49)
def test_header_selection_defaults_all_active_then_narrows(tmp_path):
    """데이터 로드 = 전원 활성. 칩을 하나씩 끄면(즉시 토글) 나머지만 활성, 카운트 재진술(결정 13)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    snap = ctrl.snapshot()
    assert snap["source_fields"] == ["업체명", "낙찰금액", "계약일"]       # 전체 헤더 불변
    assert snap["active_source_fields"] == ["업체명", "낙찰금액", "계약일"]  # 기본 전원 활성
    assert snap["active_count"] == 3 and snap["ignored_count"] == 0

    ctrl.dispatch("toggle_source_active", {"field": "낙찰금액"})          # 칩 즉시 토글 off
    ctrl.dispatch("toggle_source_active", {"field": "계약일"})
    snap = ctrl.snapshot()
    assert snap["active_source_fields"] == ["업체명"]                    # 활성만 후보(원 순서)
    assert snap["ignored_source_fields"] == ["낙찰금액", "계약일"]
    assert snap["active_count"] == 1 and snap["ignored_count"] == 2
    assert snap["notice"] and "사용 데이터 열 1개 · 미사용 2개" in snap["notice"]["text"]


def test_ignoring_mapped_header_r4_demotes_human_owned_and_restates(tmp_path):
    """사람 소유(확정) 행의 소스 헤더를 끄면 R4 시끄러운 강등 — 확정 해제·이름 재진술(결정 12).
    활성 소스를 쓰는 다른 사람 소유 행은 그대로. 원본 데이터는 불변."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    ctrl.dispatch("goto_step", {"step": 1})              # 매핑 진입 → 모델 생성(3단계 접기)
    ctrl.dispatch("set_source", {"index": 0, "source": "낙찰금액"})
    ctrl.dispatch("set_source", {"index": 1, "source": "업체명"})
    ctrl.dispatch("set_confirmed", {"index": 0, "confirmed": True})
    ctrl.dispatch("set_confirmed", {"index": 1, "confirmed": True})

    ctrl.dispatch("toggle_source_active", {"field": "낙찰금액"})          # 낙찰금액 칩 off
    snap = ctrl.snapshot()
    # 행 0(낙찰금액 사용, 확정)은 R4 강등 — 확정 해제·시스템 소유로(touched=False).
    assert snap["rows"][0]["source"] == "" and snap["rows"][0]["confirmed"] is False
    assert snap["rows"][0]["touched"] is False
    # 행 1(업체명, 활성)은 사람 소유 그대로.
    assert snap["rows"][1]["source"] == "업체명" and snap["rows"][1]["confirmed"] is True
    assert "낙찰금액" not in snap["active_source_fields"]
    assert snap["notice"]["level"] == "warn" and "재확정" in snap["notice"]["text"]


def test_reactivate_and_use_all_headers(tmp_path):
    """미사용 헤더 개별 재활성 + 전체 사용 일괄 복원(즉시 토글)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    ctrl.dispatch("toggle_source_active", {"field": "낙찰금액"})
    ctrl.dispatch("toggle_source_active", {"field": "계약일"})
    assert ctrl.snapshot()["ignored_source_fields"] == ["낙찰금액", "계약일"]

    ctrl.dispatch("toggle_source_active", {"field": "낙찰금액"})       # 개별 재활성
    snap = ctrl.snapshot()
    assert "낙찰금액" in snap["active_source_fields"]
    assert "낙찰금액" not in snap["ignored_source_fields"]

    ctrl.dispatch("use_all_headers", {})                              # 일괄 복원
    assert ctrl.snapshot()["ignored_count"] == 0


def test_new_data_resets_ignored_headers(tmp_path):
    """새 데이터 로드 = 새 헤더 어휘 → 이전 미사용 선택이 조용히 남지 않는다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    ctrl.dispatch("toggle_source_active", {"field": "낙찰금액"})
    ctrl.dispatch("toggle_source_active", {"field": "계약일"})
    assert ctrl.snapshot()["ignored_count"] == 2
    ctrl.load_data_path(str(MULTI_SHEET))                             # 첫 시트(공고목록)=새 헤더
    snap = ctrl.snapshot()
    assert snap["source_fields"] == ["공고명", "추정가격"]
    assert snap["ignored_count"] == 0 and snap["active_source_fields"] == ["공고명", "추정가격"]


def test_use_none_blocks_on_confirmed_but_allows_when_clean(tmp_path):
    """전체 미사용(결정 13 개정) — 확정 있으면 차단(파괴 방지), 없으면 허용 + 미사용 구역 펼침.

    구 '전부 미사용 무조건 거부'(#62)를 결정 13 이 개정: 되돌릴 수 없는 **확정** 파괴만
    사전 차단하고, 확정이 없으면 '고른다→매핑한다'의 출발점으로 허용한다. 마지막 헤더를
    토글로 끄는 개별 경로는 여전히 '하나 이상'."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    ctrl.dispatch("goto_step", {"step": 1})
    ctrl.dispatch("set_source", {"index": 0, "source": "낙찰금액"})
    ctrl.dispatch("set_confirmed", {"index": 0, "confirmed": True})

    # 확정 존재 → 전체 미사용 차단(파괴 방지).
    with pytest.raises(ValueError, match="확정한 매핑이 있어"):
        ctrl.dispatch("use_none", {})
    snap = ctrl.snapshot()
    assert snap["rows"][0]["source"] == "낙찰금액" and snap["rows"][0]["confirmed"] is True
    assert snap["ignored_count"] == 0                                # 파괴 없음

    # 마지막 남은 헤더를 토글로 끄는 개별 경로는 '하나 이상'으로 차단.
    ctrl.dispatch("toggle_source_active", {"field": "업체명"})
    ctrl.dispatch("toggle_source_active", {"field": "계약일"})       # 활성=[낙찰금액]
    with pytest.raises(ValueError, match="하나 이상"):
        ctrl.dispatch("toggle_source_active", {"field": "낙찰금액"})

    # 확정 해제 후엔 전체 미사용 허용 + 미사용 구역 펼침(고르는 흐름 시작점).
    ctrl.dispatch("set_confirmed", {"index": 0, "confirmed": False})
    ctrl.dispatch("use_none", {})
    snap = ctrl.snapshot()
    assert snap["active_count"] == 0 and snap["ignored_count"] == 3
    assert snap["ignored_expanded"] is True


def test_load_job_reedit_starts_all_active(tmp_path):
    """재편집 진입 = 활성 헤더가 저장 매핑에서 파생(#49 핵심 주장) — 미사용 0.

    실제 소스 매핑을 저작해 저장한 뒤 재로드하면 source_fields 가 저장 매핑의 소스 키로
    복원되고(profile_source_vocabulary) 전원 활성이다 — durable ignored 없이도 '매핑이
    곧 기억'이 성립함을 못박는다."""
    ctrl, _ = _controller26(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    ctrl.dispatch("goto_step", {"step": 1})
    ctrl.dispatch("set_source", {"index": 0, "source": "낙찰금액"})   # 실 소스 매핑
    ctrl.dispatch("set_confirmed", {"index": 0, "confirmed": True})
    r = ctrl.dispatch("confirm_all", {})
    ctrl.dispatch("confirm_blanks", {"fields": r["blanks"]})
    ctrl.dispatch("set_name", {"name": "재편집대상"})
    ctrl.dispatch("set_pattern", {"pattern": "p-{{ID}}"})
    assert ctrl.dispatch("save", {})["ok"] is True

    ctrl.load_job("재편집대상")
    snap = ctrl.snapshot()
    assert "낙찰금액" in snap["source_fields"]            # 저장 매핑 소스로 어휘 복원
    assert snap["ignored_count"] == 0                    # 전원 활성(미사용 0)
    assert snap["active_source_fields"] == snap["source_fields"]


# ------------------------------------------- 기본 데이터 연결 상태(#67)
def test_default_dataset_linked_shown_at_save_step(tmp_path):
    """재편집 4단계 — 복원 참조가 살아 있으면 (연결됨) + 로케이트 경로 노출(#67)."""
    ctrl, _ = _controller26(tmp_path)
    _complete_with_data(ctrl, "연결표시")
    ctrl.dispatch("save", {})
    ctrl.load_job("연결표시")                              # 데이터 없이 편집 세션 복원
    assert ctrl.snapshot()["default_dataset"] is None      # step 1(매핑) — 미계산(비용 가드)
    ctrl.dispatch("goto_step", {"step": 2})
    d = ctrl.snapshot()["default_dataset"]
    assert d == {"name": "multi_sheet", "status": "linked", "path": str(MULTI_SHEET)}


def test_default_dataset_dead_corrupt_missing_are_restated(tmp_path):
    """파일 이동(dead)·항목 JSON 손상(corrupt)·항목 삭제(missing)를 각각 정직하게
    재진술한다(#67) — 손상을 '삭제됨'으로 합치면 데이터 관리 화면(손상 격리 표시)과
    다른 조치를 안내하게 된다(PR #70 리뷰)."""
    ctrl, _ = _controller26(tmp_path)
    _complete_with_data(ctrl, "끊김표시")
    ctrl.dispatch("save", {})

    pool = ctrl.pool_registry
    item = pool.load("multi_sheet")
    item.opts = {"path": str(tmp_path / "이동됨.xlsx"), "sheet": "낙찰현황"}
    pool.save(item, allow_overwrite=True)                  # 파일만 죽음(dead)
    ctrl.load_job("끊김표시")
    ctrl.dispatch("goto_step", {"step": 2})
    d = ctrl.snapshot()["default_dataset"]
    assert d["status"] == "dead" and d["path"].endswith("이동됨.xlsx")

    corrupted = next((tmp_path / "pool").glob("*.dataset.json"))
    corrupted.write_text("{깨진 JSON", encoding="utf-8")   # 항목 손상(corrupt)
    ctrl.load_job("끊김표시")
    ctrl.dispatch("goto_step", {"step": 2})
    d = ctrl.snapshot()["default_dataset"]
    assert d == {"name": "multi_sheet", "status": "corrupt", "path": ""}

    corrupted.unlink()                                     # 항목 자체 소멸(missing)
    ctrl.load_job("끊김표시")
    ctrl.dispatch("goto_step", {"step": 2})
    d = ctrl.snapshot()["default_dataset"]
    assert d == {"name": "multi_sheet", "status": "missing", "path": ""}


def test_default_dataset_none_when_fresh_data_or_no_ref(tmp_path):
    """이번 세션이 데이터를 골랐거나 참조가 없으면 None — 자동등록 블록과 이중 서사 금지(#67)."""
    ctrl, _ = _controller26(tmp_path)
    _complete_with_data(ctrl, "이중서사금지")
    ctrl.dispatch("goto_step", {"step": 2})
    assert ctrl.snapshot()["default_dataset"] is None      # data_path 有 → 자동등록 블록 몫

    ctrl2, _ = _controller26(tmp_path)
    _save_named(ctrl2, "무참조작업")                        # 데이터 없이 저장 = ref ""
    ctrl2.load_job("무참조작업")
    ctrl2.dispatch("goto_step", {"step": 2})
    assert ctrl2.snapshot()["default_dataset"] is None


# ------------------------------------------------ 에디터 흡수(블록 2 개정, 결정 39~41)
def test_skip_data_requires_template_gate(tmp_path):
    """관문 옵트아웃(skip_data)도 템플릿 게이트 선통과(PR#105 리뷰 F2).

    step 0 shortcut 은 goto_step(1) 과 달리 게이트를 안 거치므로, PARTIAL(미해결 토큰
    미확인) 템플릿을 이 액션이 매핑으로 밀어 넣어 게이트를 우회할 수 있다 — 시끄럽게 차단."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_PARTIAL))            # PARTIAL → 게이트 닫힘
    with pytest.raises(ValueError, match="미해결 토큰"):
        ctrl.dispatch("skip_data", {})
    ctrl.dispatch("ack_gate", {})                        # 명시 확인 후엔 통과
    ctrl.dispatch("skip_data", {})
    assert ctrl.step == 1


def test_goto_step_free_movement_when_editing(tmp_path):
    """편집(탭) = 자유 이동(결정 41) — 매핑을 되물러도(미확정) 탭 이동이 막히지 않는다.

    편집은 저장된 작업 복원이라 의존이 전부 충족된 상태 — 같은 3분류를 탭으로 자유 이동한다.
    탭 이동은 보기 이동일 뿐이고 무결성은 저장 게이트(_do_save)가 저장점에서 계속 지킨다.
    신규 초안(편집 원점 없음)은 대조군 — 전진 게이트가 그대로 살아 있다."""
    ctrl, _ = _controller26(tmp_path)
    assert _save_named(ctrl, "자유이동")["ok"] is True
    ctrl.load_job("자유이동")
    ctrl.dispatch("set_confirmed", {"index": 0, "confirmed": False})  # 의존 되무름(미확정)
    ctrl.dispatch("goto_step", {"step": 2})              # 편집: 게이트 없이 저장 탭으로
    assert ctrl.step == 2
    ctrl.dispatch("goto_step", {"step": 0})              # 자유 복귀
    assert ctrl.step == 0
    ctrl2, _ = _controller(tmp_path / "new")             # 대조군: 신규 마법사
    ctrl2.load_template_path(str(TPL_COMPILED))
    ctrl2.dispatch("goto_step", {"step": 1})             # 0→1 은 스키마 有로 통과
    with pytest.raises(ValueError, match="조건을 아직 채우지 못해"):
        ctrl2.dispatch("goto_step", {"step": 2})         # 매핑 미확정 → 저장 전진 차단


# ---------------------------------------- PR-2 고효율 리뷰 반영(파괴 경로·클린 세션·판정 위치)
def test_save_lands_in_edit_session_of_saved_job(tmp_path):
    """저장 착지 = 방금 저장한 작업의 편집 세션(리뷰 F2 — 빈 마법사 방치·성공 표지 증발 봉합).

    결정 40(저장 제자리)·41(전환점=저장: 초안은 저장으로 작업이 되고 이후 편집은 탭)의 이행.
    성공 재진술은 push 경합에 안 걸리는 notice(ok) 채널로 온다."""
    ctrl, _ = _controller26(tmp_path)
    res = _save_named(ctrl, "착지작업")
    assert res["ok"] is True
    snap = ctrl.snapshot()
    assert snap["editing_origin"] == "착지작업"          # 빈 마법사가 아니라 저장본 위
    assert snap["step"] == 1 and snap["is_complete"] is True
    assert snap["notice"] and "저장했습니다" in snap["notice"]["text"]
    assert snap["notice"]["level"] == "ok"
    assert ctrl.has_unsaved_work() is False              # 클린 착지 — 직후 전환 헛확인 금지


def test_edit_save_preserves_current_tab(tmp_path):
    """편집 저장은 현재 탭을 유지하고 최종 상태만 한 번 렌더한다."""
    ctrl, pushes = _controller26(tmp_path)
    assert _save_named(ctrl, "탭유지작업")["ok"] is True
    ctrl.dispatch("goto_step", {"step": 2})             # 작업 저장 탭에서 저장
    before = len(pushes)

    assert ctrl.dispatch("save", {})["ok"] is True

    snap = ctrl.snapshot()
    assert snap["step"] == 2
    assert pushes[-1][1]["step"] == 2                   # 웹에 전달된 최종 활성 탭도 동일
    assert len(pushes) == before + 1                     # 중간 재로드 렌더 없이 최종 push 1회


def test_load_job_marks_session_clean_until_edited(tmp_path):
    """편집 복원 직후는 클린(디스크 저장본과 동일) — 손대기 전 전환·새 작업이 "저장하지 않은
    세션" 헛확인을 띄우지 않는다(리뷰). 변이 액션 하나로 다시 미저장이 된다."""
    ctrl, _ = _controller26(tmp_path)
    _save_named(ctrl, "클린작업")
    ctrl.load_job("클린작업")
    assert ctrl.has_unsaved_work() is False              # 복원 직후 = 버릴 것 없음
    ctrl.dispatch("set_confirmed", {"index": 0, "confirmed": False})
    assert ctrl.has_unsaved_work() is True               # 변이 → 미저장


def test_skip_data_is_noop_in_dataless_edit_session(tmp_path):
    """비울 참조가 없으면 어휘·모델 보존(리뷰 F3) — 편집 복원 세션(데이터 무)에서 「데이터
    없이 진행」 클릭이 저장-매핑 어휘를 지워 전 행을 "(데이터에 없음)" 강등하던 결함."""
    ctrl, _ = _controller26(tmp_path)
    _save_named(ctrl, "무데이터편집")
    ctrl.load_job("무데이터편집")
    before = ctrl.snapshot()
    ctrl.dispatch("skip_data", {})
    after = ctrl.snapshot()
    assert after["source_fields"] == before["source_fields"]      # 어휘 보존
    assert after["is_complete"] is True                           # 확정 복원 행 무강등
    assert after["step"] == 1


def test_skip_data_allowed_in_partial_edit_session(tmp_path):
    """편집 세션(매핑에 정당히 착지)에선 PARTIAL 게이트가 skip_data 를 막지 않는다(리뷰 F6).

    게이트 확인은 세션 국소라 load_job 이 미확인으로 복원한다 — step 0 shortcut 우회 차단
    (리뷰 F2)은 step 0 에만 적용하고, 매핑 관문의 클릭은 통과한다."""
    ctrl, _ = _controller26(tmp_path)
    ctrl.load_template_path(str(TPL_PARTIAL))
    ctrl.dispatch("ack_gate", {})
    ctrl.dispatch("skip_data", {})
    ctrl.dispatch("set_type", {"index": 0, "type": "const"})
    ctrl.dispatch("set_const", {"index": 0, "const": "v"})
    r = ctrl.dispatch("confirm_all", {})
    ctrl.dispatch("confirm_blanks", {"fields": r["blanks"]})
    ctrl.dispatch("set_name", {"name": "부분템플릿작업"})
    assert ctrl.dispatch("save", {})["ok"] is True       # 저장 착지 = 편집 세션(게이트 미확인 복원)
    assert ctrl.snapshot()["gate"]["acked"] is False
    ctrl.dispatch("skip_data", {})                       # step 1 — 게이트 없이 통과(무예외)
    assert ctrl.step == 1


def test_skip_data_detach_restores_mapping_vocabulary(tmp_path):
    """편집 세션에서 데이터 분리는 빈 어휘가 아니라 현재 매핑이 참조하는 소스 어휘로 복귀
    (리뷰 F3 — load_job 초기 상태와 동형, "(데이터에 없음)" 오표시 금지)."""
    ctrl, _ = _controller26(tmp_path)
    _save_named(ctrl, "분리작업")                        # 착지 = 편집 세션
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    ctrl.dispatch("set_source", {"index": 0, "source": "업체명"})
    ctrl.dispatch("skip_data", {})                       # 분리(detach)
    snap = ctrl.snapshot()
    assert snap["data_path"] == "" and snap["record_count"] == 0
    assert "업체명" in snap["source_fields"]             # 매핑 참조 어휘로 복귀(빈 어휘 아님)
    assert snap["rows"][0]["source"] == "업체명"          # 이월 + 드롭다운 정상 후보


def test_mapping_reset_stakes_judged_by_python_now(tmp_path):
    """관문 파괴 확인의 근거 수치는 Python 이 지금 판정(리뷰 F7 — stale LAST 우회 차단).

    수치 = 이월 대상(확정 + 내용 있는 touched) — _ensure_model carry 와 같은 집합이라
    확인 문안("값은 이월")과 실제 이월이 어긋나지 않는다(리뷰 F1)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    assert ctrl.dispatch("mapping_reset_stakes", {})["human"] == 0     # 모델 전
    ctrl.dispatch("skip_data", {})
    assert ctrl.dispatch("mapping_reset_stakes", {})["human"] == 0     # 미접촉 제안뿐
    ctrl.dispatch("set_type", {"index": 0, "type": "const"})
    ctrl.dispatch("set_const", {"index": 0, "const": "v"})
    stakes = ctrl.dispatch("mapping_reset_stakes", {})
    assert stakes["human"] == 1                                        # 내용 있는 수동
    # 소스 없는 수동 const 행은 use_none 강등 대상이 아니다 — 문안=파괴 집합(리뷰 F4).
    assert stakes["manual_unconfirmed"] == 0
    assert stakes["confirmed"] == 0                                    # use_none 선차단 근거(F5)
    r = ctrl.dispatch("confirm_all", {})
    ctrl.dispatch("confirm_blanks", {"fields": r["blanks"]})
    stakes = ctrl.dispatch("mapping_reset_stakes", {})
    assert stakes["human"] == ctrl.snapshot()["field_count"]           # 전 행 확정(비움 포함)
    assert stakes["manual_unconfirmed"] == 0                           # 확정 = 미확정 수동 아님
    assert stakes["confirmed"] == ctrl.snapshot()["field_count"]       # 선차단 수치(F5)


def test_ensure_model_carries_touched_unconfirmed_rows(tmp_path):
    """관문 재겨눔이 미확정 수동 편집을 이월한다(리뷰 F1 — carry_profile 실배선).

    확정-전용 이월(to_profile)은 "값은 이월된다"는 확인 문안과 달리 직접 고른 상수를
    조용히 버렸다 — 확정 0·수동 1 세션에서 데이터를 겨눠도 값이 남아야 한다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.dispatch("skip_data", {})
    ctrl.dispatch("set_type", {"index": 0, "type": "const"})
    ctrl.dispatch("set_const", {"index": 0, "const": "수동값"})        # touched·미확정
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")            # 관문 겨눔 = 재초안
    row0 = ctrl.snapshot()["rows"][0]
    assert row0["type"] == "const" and row0["const"] == "수동값"       # 값 이월(소실 금지)
    assert row0["confirmed"] is False                                  # 재검토 강제는 유지


def test_gateway_repick_preserves_touched_unconfirmed_edits(tmp_path):
    """칩-라이브 리뷰 F2 정본(컨트롤러 end-to-end) — 미확정 **수동** 편집(touched)은 관문
    데이터 재겨눔에도 조용히 소실되지 않는다.

    carry_profile 이 확정뿐 아니라 touched 미확정 행도 이월(confirm=False)한다 — 값은 살고
    전 행 미확정으로 재검토를 강제(결정 12 '수동=사람 소유'). 구 to_profile(확정-only)이면
    이 수동 편집은 재초안에서 조용히 사라졌다(F2). 미접촉 제안은 반대로 새 데이터 재제안."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    ctrl.dispatch("goto_step", {"step": 1})
    ctrl.dispatch("set_source", {"index": 0, "source": "낙찰금액"})   # 수동(touched)·미확정
    snap = ctrl.snapshot()
    assert snap["rows"][0]["touched"] is True and snap["rows"][0]["confirmed"] is False

    ctrl.load_data_path(str(MULTI_SHEET))                            # 관문에서 첫 시트로 재겨눔
    snap = ctrl.snapshot()
    assert snap["rows"][0]["source"] == "낙찰금액"                   # 수동 편집 이월(F2 — 소실 아님)
    assert snap["rows"][0]["touched"] is True                       # 사람 소유 유지
    assert snap["rows"][0]["confirmed"] is False                    # 재검토 강제(전 행 미확정)


def test_revert_source_resets_single_row_and_resuggests(tmp_path):
    """↩(자동 제안 복귀, 결정 12) — 그 행만 완전 리셋 후 단일 행 재제안(리뷰 R4).

    무관한 stale 사람 소유 행(비활성 소스 겨눔)은 건드리지 않는다 — 전집합 재계산이면
    조용히 강등됐다. 센티넬 소스값이 아니라 전용 액션이라 동명 실열과도 안 충돌한다(R5)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    ctrl.dispatch("goto_step", {"step": 1})
    ctrl.dispatch("set_source", {"index": 0, "source": "계약일"})     # 수동 오지정(touched)
    ctrl.dispatch("set_source", {"index": 1, "source": "없는열"})     # 무관 stale 사람 소유
    ctrl.dispatch("revert_source", {"index": 0})
    snap = ctrl.snapshot()
    assert snap["rows"][0]["touched"] is False                       # 시스템 소유 복귀
    assert snap["rows"][1]["source"] == "없는열"                     # 무관 행 불건드림(R4)
    assert snap["rows"][1]["touched"] is True


def test_chip_toggle_leaves_carried_stale_rows_untouched(tmp_path):
    """무관한 칩 조작이 이월 stale 행(현재 데이터에 없는 소스)을 강등하지 않는다(PR-3 리뷰 F1).

    관문 재겨눔이 carry 로 살린 「데이터에 없음」 행은 칩과 무관 — 전집합 강등이면 칩 토글
    한 번에 이월 값이 소실되고 통지는 끈 적 없는 헤더를 지목했다(오귀속)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    ctrl.dispatch("goto_step", {"step": 1})
    ctrl.dispatch("set_source", {"index": 0, "source": "낙찰금액"})   # 수동
    ctrl.load_data_path(str(MULTI_SHEET))                            # 첫 시트 재겨눔 — carry
    assert ctrl.snapshot()["rows"][0]["source"] == "낙찰금액"         # stale 이월(「데이터에 없음」)
    ctrl.dispatch("toggle_source_active", {"field": "추정가격"})      # 무관 칩 끔
    snap = ctrl.snapshot()
    assert snap["rows"][0]["source"] == "낙찰금액"                    # 이월 값 생존(F1)
    assert snap["rows"][0]["touched"] is True
    assert "낙찰금액" not in (snap["notice"]["text"] if snap["notice"] else "")  # 오귀속 통지 없음


def test_revert_source_refuses_confirmed_rows(tmp_path):
    """↩ 는 확정 행을 거부한다(PR-3 리뷰 F2) — 확정도 touched 라 무가드면 오클릭 한 번에
    확정이 조용히 풀리고 다른 열로 치환된다. 확정 해제(체크박스)가 의식적 1단계."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    ctrl.dispatch("goto_step", {"step": 1})
    ctrl.dispatch("set_source", {"index": 0, "source": "낙찰금액"})
    ctrl.dispatch("set_confirmed", {"index": 0, "confirmed": True})
    with pytest.raises(ValueError, match="확정을 먼저 해제"):
        ctrl.dispatch("revert_source", {"index": 0})
    assert ctrl.snapshot()["rows"][0]["confirmed"] is True            # 무파괴


def test_same_file_repick_after_use_none_revives_suggestions(tmp_path):
    """use_none 뒤 같은 파일 재겨눔(키 불변) — 관문 재동기화로 제안이 되살아난다(PR-3 리뷰 F3).

    load_data_path 가 칩 상태만 전원 활성으로 리셋하고 모델 키가 그대로면 재초안이 없어,
    「후보 없음」 죽은 제안이 조용히 남았다 — 키 불변이면 apply_active_sources 재동기화."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(MULTI_SHEET))                             # 공고목록: 공고명·추정가격 매치
    ctrl.dispatch("goto_step", {"step": 1})
    assert any(r["source"] for r in ctrl.snapshot()["rows"])          # 자동 제안 존재(전제)
    ctrl.dispatch("use_none", {})                                     # 확정 0 — 허용
    assert all(not r["source"] for r in ctrl.snapshot()["rows"])      # 전원 후보 없음
    ctrl.load_data_path(str(MULTI_SHEET))                             # 같은 파일·시트 재겨눔(키 불변)
    snap = ctrl.snapshot()
    assert snap["active_count"] == 2
    assert any(r["source"] for r in snap["rows"])                     # 제안 부활(죽은 표면 아님)


def test_toggle_clears_ignored_expanded_hint(tmp_path):
    """개별 토글은 '전체 미사용' 펼침 힌트를 걷는다(PR-3 리뷰 F7) — 몇 步 전 행동의 stale
    상태가 이후 접힘 렌더를 계속 강제하지 않는다(수동 펼침 보존은 뷰 foldOpen 소관)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    ctrl.dispatch("goto_step", {"step": 1})
    ctrl.dispatch("use_none", {})
    assert ctrl.snapshot()["ignored_expanded"] is True
    ctrl.dispatch("toggle_source_active", {"field": "업체명"})        # 다시 사용(개별)
    assert ctrl.snapshot()["ignored_expanded"] is False


# ---------------------------------- 신규 1단계 = 템플릿 라이브러리(R-info 2부 접합, PR-4)
def _controller_lib(tmp_path, paths=None, lib_dir=None):
    pushes: list = []
    vm = (TemplateManagerViewModel(lib_dir) if lib_dir is not None
          else TemplateManagerViewModel(paths=paths or []))
    ctrl = EditorController(
        JobRegistry(tmp_path / "jobs"),
        lambda s, snap: pushes.append((s, snap)),
        template_library=vm,
    )
    return ctrl, pushes


def _lib_items(snap):
    """1단계 피커의 그룹 구획을 평평화한 아이템(#108 슬라이스 3 — library 는 {sections,flat})."""
    return [it for sec in snap["library"]["sections"] for it in sec["items"]]


def test_snapshot_exposes_library_on_template_stage(tmp_path):
    """템플릿 분류(0)의 스냅샷은 라이브러리를 **그룹 구획**으로 싣는다(#108 슬라이스 3 — 관리
    화면과 같은 조직, 선택 전용). 그룹 0개면 flat. 다른 단계는 빈 구획(스캔 비용을 매핑 편집
    push 에 지불하지 않는다)."""
    ctrl, _ = _controller_lib(tmp_path, paths=[TPL_COMPILED, TPL_PARTIAL])
    snap = ctrl.snapshot()
    names = [t["name"] for t in _lib_items(snap)]
    assert TPL_COMPILED.name in names and TPL_PARTIAL.name in names
    assert snap["library"]["flat"] is True  # 그룹 0개 = 퇴화 평면
    assert all(set(t) >= {"name", "path", "badge_label", "badge_level", "current", "detail"}
               for t in _lib_items(snap))
    ctrl.dispatch("use_library_template", {"path": str(TPL_COMPILED)})
    snap = ctrl.snapshot()
    assert snap["template_name"] == TPL_COMPILED.name                  # 선택 = 새 세션 로드
    assert [t["current"] for t in _lib_items(snap)] == [True, False]   # 현 선택 표지
    ctrl.dispatch("goto_step", {"step": 1})
    assert ctrl.snapshot()["library"] == {"sections": [], "flat": True}  # 매핑 단계는 빈 구획


def test_library_picker_shares_groups_and_collapse_with_management(tmp_path):
    """1단계 피커가 관리 화면과 **같은 hwpx 그룹 모델**을 소비 — 지정·접힘이 두 표면에 함께
    반영된다(결정 6, 단일 실체). 토글은 뷰 상태라 세션을 더럽히지 않는다."""
    groups = TemplateGroupModel("hwpx")
    # 명시 경로 라이브러리는 library_dir 이 None → 키=파일명(rel_key 폴백).
    groups.set_group(TPL_COMPILED.name, "계약")
    pushes: list = []
    ctrl = EditorController(
        JobRegistry(tmp_path / "jobs"),
        lambda s, snap: pushes.append((s, snap)),
        template_library=TemplateManagerViewModel(paths=[TPL_COMPILED, TPL_PARTIAL]),
        template_groups=groups,
    )
    lib = ctrl.snapshot()["library"]
    assert lib["flat"] is False
    by = {sec["group"]: sec for sec in lib["sections"]}
    assert [it["name"] for it in by["계약"]["items"]] == [TPL_COMPILED.name]
    assert TPL_PARTIAL.name in [it["name"] for it in by[""]["items"]]  # 미지정 = 「그룹 없음」
    # 접힘 토글 = 공유 모델 경유 → 같은 모델이 접힌 채(관리 화면도 접혀 보인다) · 세션 불변.
    ctrl.dispatch("toggle_library_group", {"group": "계약"})
    assert groups.is_collapsed("계약")
    assert {s["group"]: s for s in ctrl.snapshot()["library"]["sections"]}["계약"]["collapsed"] is True
    assert ctrl.has_unsaved_work() is False


def test_editor_picker_reflects_shared_vm_refresh_without_stale_cache(tmp_path):
    """#137·#138 리뷰 F8 — 관리 화면 가져오기(공유 VM refresh)가 에디터 피커에 즉시 반영된다
    (별도 행 캐시 발산 제거 — 공유 VM rows() 직독)."""
    import shutil

    lib = tmp_path / "lib"
    lib.mkdir()
    vm = TemplateManagerViewModel(library_dir=lib)  # 빈 라이브러리로 시작
    ctrl = EditorController(
        JobRegistry(tmp_path / "jobs"), lambda s, snap: None, template_library=vm
    )
    assert _lib_items(ctrl.snapshot()) == []
    shutil.copy2(TPL_COMPILED, lib / "새서식.hwpx")  # 관리 화면 가져오기 시뮬레이션
    vm.refresh()
    assert "새서식.hwpx" in {it["name"] for it in _lib_items(ctrl.snapshot())}


def test_editor_picker_does_not_reconcile_away_offscreen_group(tmp_path):
    """#138 리뷰 F11 — 에디터 피커는 reconcile 하지 않는다. 에디터 VM 에 아직 없는 파일의
    그룹 지정을 (부분/필터된) 목록으로 지우면 안 된다(위생은 관리 화면 소관)."""
    groups = TemplateGroupModel("hwpx")
    groups.set_group("아직없는.hwpx", "입찰")  # 에디터 VM 밖 파일
    ctrl = EditorController(
        JobRegistry(tmp_path / "jobs"), lambda s, snap: None,
        template_library=TemplateManagerViewModel(paths=[TPL_COMPILED]),  # 그 파일 없음
        template_groups=groups,
    )
    ctrl.snapshot()  # step 0 = 피커 build_sections(reconcile 없음)
    assert TemplateGroupModel("hwpx").group_of("아직없는.hwpx") == "입찰"  # 지정 생존


def test_use_library_template_rejects_paths_outside_library(tmp_path):
    """라이브러리 밖 경로는 loud 거부(백엔드 화이트리스트) — 웹이 임의 경로를 실어도 생
    파일 직접 로드 경로가 부활하지 않는다(2부: 가져오기=복사가 유일한 바깥 입구)."""
    ctrl, _ = _controller_lib(tmp_path, paths=[TPL_PARTIAL])
    with pytest.raises(ValueError, match="라이브러리에 없는"):
        ctrl.dispatch("use_library_template", {"path": str(TPL_COMPILED)})


def test_import_template_copies_into_library_and_starts_session(tmp_path):
    """가져오기 = 복사(2부: 앱 소유 루트) — 사본으로 세션이 서고, 이름 충돌은 조용히 덮지
    않고 접미로 회피 + notice 재진술한다."""
    lib = tmp_path / "lib"
    lib.mkdir()
    ctrl, _ = _controller_lib(tmp_path, lib_dir=lib)
    name = ctrl.import_template(str(TPL_COMPILED))
    assert name == TPL_COMPILED.name and (lib / name).exists()         # 복사본 생성
    assert ctrl.template_path == str(lib / name)                       # 세션 = 사본(원본 아님)
    name2 = ctrl.import_template(str(TPL_COMPILED))                    # 같은 이름 재가져오기
    assert name2 != name and (lib / name2).exists()                    # 접미 회피(조용한 덮기 금지)
    assert "충돌" in ctrl.snapshot()["notice"]["text"]


def test_pattern_preview_uses_real_renderer_on_save_stage(tmp_path):
    """F26 — 저장 분류의 파일명 라이브 예시는 실제 생성기(make_output_filename)와 같은
    함수로 만든 표본 1행(seq=1) 렌더다(예시 ≠ 산출물의 조용한 어긋남 금지)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.dispatch("skip_data", {})
    ctrl.dispatch("set_type", {"index": 0, "type": "const"})
    ctrl.dispatch("set_const", {"index": 0, "const": "수기값"})
    field = ctrl.snapshot()["rows"][0]["template_field"]
    r = ctrl.dispatch("confirm_all", {})
    ctrl.dispatch("confirm_blanks", {"fields": r["blanks"]})
    ctrl.dispatch("goto_step", {"step": 2})
    ctrl.dispatch("set_pattern", {"pattern": f"x-{{{{{field}}}}}-{{{{seq:001}}}}"})
    assert ctrl.snapshot()["pattern_preview"] == "x-수기값-001.hwpx"
    ctrl.dispatch("goto_step", {"step": 1})
    assert ctrl.snapshot()["pattern_preview"] == ""                    # 저장 분류 밖은 미계산


def test_import_template_rejects_broken_file_without_residue(tmp_path):
    """가져오기 선검증·무잔재(PR-4 리뷰 F3) — 손상 파일은 복사 전에 loud 거부되고, 앱 소유
    라이브러리에 오류 사본이 영구히 남지 않는다(인앱 삭제 어포던스가 없는 잔재 금지)."""
    lib = tmp_path / "lib"
    lib.mkdir()
    junk = tmp_path / "junk.hwpx"
    junk.write_bytes(b"this is not a hwpx zip")
    ctrl, _ = _controller_lib(tmp_path, lib_dir=lib)
    import zipfile
    with pytest.raises((ValueError, OSError, zipfile.BadZipFile)):     # 손상 = 복사 전 loud
        ctrl.import_template(str(junk))
    assert list(lib.iterdir()) == []                                   # 무잔재


def test_use_library_rejection_refreshes_stale_list(tmp_path):
    """화이트리스트 거절은 갱신된 목록을 먼저 push 한다(PR-4 리뷰 F7) — 외부 삭제된 파일의
    stale 행이 화면에 남아 같은 클릭을 반복하게 만드는 무행동 안내 금지."""
    lib = tmp_path / "lib"
    lib.mkdir()
    ghost = lib / "유령.hwpx"
    ghost.write_bytes(TPL_COMPILED.read_bytes())
    ctrl, pushes = _controller_lib(tmp_path, lib_dir=lib)
    assert [t["name"] for t in _lib_items(ctrl.snapshot())] == ["유령.hwpx"]
    ghost.unlink()                                                     # 외부 삭제
    with pytest.raises(ValueError, match="라이브러리에 없는"):
        ctrl.dispatch("use_library_template", {"path": str(ghost)})
    assert _lib_items(pushes[-1][1]) == []                             # 거절 전 push 로 걷힘


# ------------------------------------------------- 덮어쓰기 확인의 잠금·문안 대조(#149)
def test_overwrite_confirm_requires_the_text_the_user_actually_read(tmp_path):
    """확인 플래그만으로는 덮지 않는다 — **본 문안**을 함께 되돌려야 통과한다(#149).

    무엇을 보고 확정했는지 모르면 그 확인이 지금 상태에 대한 것인지 알 수 없다. 덮어쓰기는
    되돌릴 수 없으므로, 검증할 수 없는 확인은 통과가 아니라 재확인(fail-closed)이다.
    """
    ctrl, _ = _controller26(tmp_path)
    _save_named(ctrl, "작업일")
    _save_named(ctrl, "작업이")
    ctrl.load_job("작업일")
    ctrl.dispatch("set_name", {"name": "작업이"})
    res = ctrl.dispatch("save", {})
    assert res["needs_overwrite"] is True
    again = ctrl.dispatch("save", {"confirm_overwrite": True})       # 문안 없이 확정
    assert again["ok"] is False and again["needs_overwrite"] is True
    ok = ctrl.dispatch(
        "save",
        {"confirm_overwrite": True, "confirmed_overwrite_text": res["overwrite_text"]},
    )
    assert ok["ok"] is True


def test_overwrite_confirm_reasks_when_the_situation_changed_under_the_modal(tmp_path):
    """모달을 읽는 사이 상태가 바뀌면 새 문안으로 **다시 묻는다**(#149).

    사용자는 '작업이를 덮는다'를 확정했는데 그 사이 원본이 바뀌면, 확정은 더 이상 지금
    일어날 일에 대한 확인이 아니다 — 확인한 내용과 실제 집합이 갈라지는 자리.
    """
    ctrl, _ = _controller26(tmp_path)
    _save_named(ctrl, "원본작업")
    ctrl.load_job("원본작업")
    ctrl.dispatch("set_pattern", {"pattern": "새-{{ID}}"})
    assert ctrl.dispatch("save", {})["ok"] is True                   # 무드리프트 자기-갱신

    ctrl.load_job("원본작업")
    reg = JobRegistry(tmp_path / "jobs")
    job = reg.load("원본작업")
    job.filename_pattern = "외부-{{ID}}"                              # 편집 사이 외부 변경
    reg.save(job, allow_overwrite=True)
    res = ctrl.dispatch("save", {})
    assert res["needs_overwrite"] is True and "외부" in res["overwrite_text"]

    # 확정 왕복 중 원본이 통째로 사라진다 → 덮을 것이 없으니 그냥 저장(묻지 않는다).
    reg.path_for("원본작업").unlink()
    ok = ctrl.dispatch(
        "save",
        {"confirm_overwrite": True, "confirmed_overwrite_text": res["overwrite_text"]},
    )
    assert ok["ok"] is True


def test_overwrite_gate_is_judged_inside_the_write_lock(tmp_path):
    """게이트 판정이 **쓰기 잠금 안**이다(#149) — 판정과 실행 사이 창을 없앤다.

    잠금 밖 선판정은 판정 후 저장까지 사이에 디스크가 바뀔 수 있어, 확인 없이 외부 변경을
    덮거나 읽은 문안과 다른 자리를 덮는다. 판정 시점에 잠금이 다른 스레드에서 잡히지
    않는지로 되읽는다(저장 구간 잠금 테스트와 동형).
    """
    import threading

    ctrl, _ = _controller26(tmp_path)
    _save_named(ctrl, "게이트작업")
    ctrl.load_job("게이트작업")
    held: "list[bool]" = []
    real_gate = ctrl._overwrite_gate

    def spy() -> str:
        got = [None]

        def probe() -> None:
            lock = ctrl.registry.write_lock()
            got[0] = lock.acquire(blocking=False)
            if got[0]:
                lock.release()

        t = threading.Thread(target=probe)
        t.start()
        t.join(3)
        held.append(not got[0])
        return real_gate()

    ctrl._overwrite_gate = spy  # type: ignore[method-assign]
    assert ctrl.dispatch("save", {})["ok"] is True
    assert held and all(held), "덮어쓰기 게이트가 쓰기 잠금 밖입니다 — 판정·실행 창 회귀."
