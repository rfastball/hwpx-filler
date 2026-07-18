"""작업 에디터 화면 컨트롤러 계약 가드 — pywebview/Qt 불필요(헤드리스).

에픽 #20 화면 #15·#16 이관의 회귀 심. 4단계 마법사 게이트(스키마·PARTIAL·매핑 확정·저장)를
링1 VM 그대로 구동해 창 없이 확인한다. 실 HWPX 픽스처(COMPILED·PARTIAL)로 게이트 분기를 탄다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.core.job import JobRegistry
from hwpxfiller.webapp.screen_editor import EditorController

REPO = Path(__file__).resolve().parents[1]
TPL_COMPILED = REPO / "tests" / "corpus" / "scenario" / "templates" / "구매요청서.hwpx"
TPL_PARTIAL = REPO / "tests" / "fixtures" / "template_v1.hwpx"
MULTI_SHEET = REPO / "tests" / "fixtures" / "multi_sheet.xlsx"


def _controller(tmp_path: Path) -> "tuple[EditorController, list]":
    pushes: list = []
    reg = JobRegistry(tmp_path / "jobs")
    ctrl = EditorController(reg, lambda s, snap: pushes.append((s, snap)))
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
    with pytest.raises(ValueError, match="게이트 미통과"):
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
    """템플릿→(데이터 건너뜀)→매핑(상수 1행+비움 확정)→저장 end-to-end."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.dispatch("goto_step", {"step": 1})
    ctrl.dispatch("skip_data", {})
    snap = ctrl.snapshot()
    assert snap["step"] == 2 and len(snap["rows"]) == 10 and snap["schema_only"] is True

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
    ctrl.dispatch("goto_step", {"step": 3})
    ctrl.dispatch("set_name", {"name": "테스트작업"})
    ctrl.dispatch("set_pattern", {"pattern": "문서-{{ID}}"})
    res = ctrl.dispatch("save", {})
    assert res["ok"] is True and res["saved_name"] == "테스트작업"
    assert JobRegistry(tmp_path / "jobs").exists("테스트작업")


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

    # 같은 이름 재저장 → 덮어쓰기 확인 요구(조용한 덮어쓰기 금지).
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
    assert ctrl.dispatch("save", {"confirm_overwrite": True})["ok"] is True


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
    assert ctrl.dispatch("save", {"confirm_overwrite": True})["ok"] is True
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
    ctrl.dispatch("goto_step", {"step": 3})
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
    )
    return ctrl, pushes


# ------------------------------------------------------------ 편집 모드(#1)
def test_load_job_restores_edit_session(tmp_path):
    """저장 작업 → load_job: 이름·패턴·확정 매핑·단계가 복원되고 원점이 기록된다."""
    ctrl, _ = _controller26(tmp_path)
    assert _save_named(ctrl, "원본작업")["ok"] is True   # 저장 후 세션 리셋

    ctrl.load_job("원본작업")
    snap = ctrl.snapshot()
    assert snap["step"] == 2                             # 매핑 확정 단계로 착지
    assert snap["name"] == "원본작업"
    assert snap["editing_origin"] == "원본작업"
    assert snap["is_complete"] is True                   # 1 const + 9 blank 전부 확정 복원
    assert snap["rows"][0]["type"] == "const" and snap["rows"][0]["const"] == "v"
    assert snap["notice"] and "편집 모드" in snap["notice"]["text"]


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
    ctrl.dispatch("goto_step", {"step": 1})              # 뒤로
    ctrl.dispatch("goto_step", {"step": 2})              # 다시 매핑 진입(_ensure_model 경유)
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
    """
    ctrl, _ = _controller26(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.dispatch("skip_data", {})
    ctrl.dispatch("set_type", {"index": 0, "type": "const"})
    ctrl.dispatch("set_const", {"index": 0, "const": "보존값"})
    r = ctrl.dispatch("confirm_all", {})
    ctrl.dispatch("confirm_blanks", {"fields": r["blanks"]})
    assert ctrl.snapshot()["is_complete"] is True

    ctrl.dispatch("goto_step", {"step": 1})              # 데이터 단계로 회귀
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    ctrl.dispatch("goto_step", {"step": 2})              # 키 변경 → 재생성 경로
    snap = ctrl.snapshot()
    assert snap["rows"][0]["const"] == "보존값"          # 값 이월(조용한 소실 없음)
    assert snap["rows"][0]["type"] == "const"
    assert all(row["confirmed"] is False for row in snap["rows"])  # 확정 전원 해제
    assert snap["is_complete"] is False                  # 재확정 없이는 저장 게이트 미통과
    assert snap["notice"] and "미확정" in snap["notice"]["text"]
    assert "다시 확정" in snap["notice"]["text"]         # 재확정 필요를 loud 재진술


# ------------------------------------------------------- 선언 데이터 자동등록(#3)
def _complete_with_data(ctrl, name: str) -> None:
    """데이터(다중시트 확정) 연결 세션을 저장 직전까지 구성."""
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    ctrl.dispatch("goto_step", {"step": 2})
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
    """데이터 로드 = 전원 활성. 선택 항목만 사용 → 나머지 일괄 미사용, 카운트 재진술."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    snap = ctrl.snapshot()
    assert snap["source_fields"] == ["업체명", "낙찰금액", "계약일"]       # 전체 헤더 불변
    assert snap["active_source_fields"] == ["업체명", "낙찰금액", "계약일"]  # 기본 전원 활성
    assert snap["active_count"] == 3 and snap["ignored_count"] == 0

    ctrl.dispatch("use_only_selected", {"fields": ["업체명"]})
    snap = ctrl.snapshot()
    assert snap["active_source_fields"] == ["업체명"]                    # 활성만 후보(원 순서)
    assert snap["ignored_source_fields"] == ["낙찰금액", "계약일"]
    assert snap["active_count"] == 1 and snap["ignored_count"] == 2
    assert snap["notice"] and "사용 헤더 1개 · 미사용 2개" in snap["notice"]["text"]


def test_ignoring_mapped_header_clears_row_and_restates(tmp_path):
    """이미 매핑된 헤더를 미사용 전환 → 그 행만 source=''·confirmed=False, warn 재진술.
    다른 매핑·원본 데이터는 불변."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    ctrl.dispatch("goto_step", {"step": 2})              # 매핑 진입 → 모델 생성
    ctrl.dispatch("set_source", {"index": 0, "source": "낙찰금액"})
    ctrl.dispatch("set_source", {"index": 1, "source": "업체명"})
    ctrl.dispatch("set_confirmed", {"index": 0, "confirmed": True})
    ctrl.dispatch("set_confirmed", {"index": 1, "confirmed": True})

    ctrl.dispatch("use_only_selected", {"fields": ["업체명", "계약일"]})  # 낙찰금액 미사용
    snap = ctrl.snapshot()
    assert snap["rows"][0]["source"] == "" and snap["rows"][0]["confirmed"] is False
    assert snap["rows"][1]["source"] == "업체명" and snap["rows"][1]["confirmed"] is True
    assert "낙찰금액" not in snap["active_source_fields"]
    assert snap["notice"]["level"] == "warn" and "재확정" in snap["notice"]["text"]


def test_reactivate_and_use_all_headers(tmp_path):
    """미사용 헤더 개별 재활성 + 모두 사용 일괄 복원."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    ctrl.dispatch("use_only_selected", {"fields": ["업체명"]})
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
    ctrl.dispatch("use_only_selected", {"fields": ["업체명"]})
    assert ctrl.snapshot()["ignored_count"] == 2
    ctrl.load_data_path(str(MULTI_SHEET))                             # 첫 시트(공고목록)=새 헤더
    snap = ctrl.snapshot()
    assert snap["source_fields"] == ["공고명", "추정가격"]
    assert snap["ignored_count"] == 0 and snap["active_source_fields"] == ["공고명", "추정가격"]


def test_empty_selection_is_loud_and_preserves_mappings(tmp_path):
    """전부 미사용은 시끄럽게 거부(리뷰 #62 🔴) — 되돌릴 수 없는 매핑 전멸을 사전 차단.

    빈 선택(use_only_selected [])·마지막 헤더까지 끄는 토글 둘 다 같은 종착지라
    가드를 _apply_active 에 두어 두 경로 모두 막고, 확정 매핑을 보존한다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    ctrl.dispatch("goto_step", {"step": 2})
    ctrl.dispatch("set_source", {"index": 0, "source": "낙찰금액"})
    ctrl.dispatch("set_confirmed", {"index": 0, "confirmed": True})

    with pytest.raises(ValueError, match="하나 이상"):
        ctrl.dispatch("use_only_selected", {"fields": []})            # 전부 미사용 거부
    # 매핑·활성 상태 불변(파괴 없음).
    snap = ctrl.snapshot()
    assert snap["rows"][0]["source"] == "낙찰금액" and snap["rows"][0]["confirmed"] is True
    assert snap["ignored_count"] == 0

    # 마지막 남은 헤더를 토글로 끄는 경로도 같은 가드에 막힌다.
    ctrl.dispatch("use_only_selected", {"fields": ["낙찰금액"]})
    with pytest.raises(ValueError, match="하나 이상"):
        ctrl.dispatch("toggle_source_active", {"field": "낙찰금액"})


def test_load_job_reedit_starts_all_active(tmp_path):
    """재편집 진입 = 활성 헤더가 저장 매핑에서 파생(#49 핵심 주장) — 미사용 0.

    실제 소스 매핑을 저작해 저장한 뒤 재로드하면 source_fields 가 저장 매핑의 소스 키로
    복원되고(profile_source_vocabulary) 전원 활성이다 — durable ignored 없이도 '매핑이
    곧 기억'이 성립함을 못박는다."""
    ctrl, _ = _controller26(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    ctrl.dispatch("goto_step", {"step": 2})
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
    assert ctrl.snapshot()["default_dataset"] is None      # step 2 — 미계산(비용 가드)
    ctrl.dispatch("goto_step", {"step": 3})
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
    ctrl.dispatch("goto_step", {"step": 3})
    d = ctrl.snapshot()["default_dataset"]
    assert d["status"] == "dead" and d["path"].endswith("이동됨.xlsx")

    corrupted = next((tmp_path / "pool").glob("*.dataset.json"))
    corrupted.write_text("{깨진 JSON", encoding="utf-8")   # 항목 손상(corrupt)
    ctrl.load_job("끊김표시")
    ctrl.dispatch("goto_step", {"step": 3})
    d = ctrl.snapshot()["default_dataset"]
    assert d == {"name": "multi_sheet", "status": "corrupt", "path": ""}

    corrupted.unlink()                                     # 항목 자체 소멸(missing)
    ctrl.load_job("끊김표시")
    ctrl.dispatch("goto_step", {"step": 3})
    d = ctrl.snapshot()["default_dataset"]
    assert d == {"name": "multi_sheet", "status": "missing", "path": ""}


def test_default_dataset_none_when_fresh_data_or_no_ref(tmp_path):
    """이번 세션이 데이터를 골랐거나 참조가 없으면 None — 자동등록 블록과 이중 서사 금지(#67)."""
    ctrl, _ = _controller26(tmp_path)
    _complete_with_data(ctrl, "이중서사금지")
    ctrl.dispatch("goto_step", {"step": 3})
    assert ctrl.snapshot()["default_dataset"] is None      # data_path 有 → 자동등록 블록 몫

    ctrl2, _ = _controller26(tmp_path)
    _save_named(ctrl2, "무참조작업")                        # 데이터 없이 저장 = ref ""
    ctrl2.load_job("무참조작업")
    ctrl2.dispatch("goto_step", {"step": 3})
    assert ctrl2.snapshot()["default_dataset"] is None
