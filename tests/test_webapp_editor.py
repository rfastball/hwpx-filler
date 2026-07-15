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


def test_save_blocks_when_model_schema_mismatches_template(tmp_path):
    """방어층: 모델이 현재 스키마와 어긋나면(혼합) 저장을 시끄럽게 차단(#25 항목4)."""
    ctrl, _ = _controller(tmp_path)
    _build_complete_session(ctrl, "작업A")               # 모델 = COMPILED 스키마
    # new_job_session 을 우회해 low-level 로 스키마만 교체(구버그 경로 재현) → 모델은 A 그대로.
    ctrl.load_template_path(str(TPL_PARTIAL))
    res = ctrl.dispatch("save", {})
    assert res["ok"] is False and "일치하지 않습니다" in res["block_reason"]
