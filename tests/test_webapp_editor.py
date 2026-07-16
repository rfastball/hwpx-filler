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


def test_save_blocks_when_model_schema_mismatches_template(tmp_path):
    """방어층: 모델이 현재 스키마와 어긋나면(혼합) 저장을 시끄럽게 차단(#25 항목4)."""
    ctrl, _ = _controller(tmp_path)
    _build_complete_session(ctrl, "작업A")               # 모델 = COMPILED 스키마
    # new_job_session 을 우회해 low-level 로 스키마만 교체(구버그 경로 재현) → 모델은 A 그대로.
    ctrl.load_template_path(str(TPL_PARTIAL))
    res = ctrl.dispatch("save", {})
    assert res["ok"] is False and "일치하지 않습니다" in res["block_reason"]


# ============================================================ #26 패리티 회수
# 편집 모드(#1)·매핑 프로파일(#5)·선언 데이터 자동등록(#3)의 헤드리스 계약.
from hwpxfiller.core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry
from hwpxfiller.core.job import Job
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.core.mapping_base import MappingBaseRegistry


def _controller26(tmp_path: Path):
    """레지스트리 3종(작업·베이스·풀)을 tmp 로 격리 주입한 컨트롤러."""
    pushes: list = []
    ctrl = EditorController(
        JobRegistry(tmp_path / "jobs"),
        lambda s, snap: pushes.append((s, snap)),
        base_registry=MappingBaseRegistry(tmp_path / "bases"),
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


def test_ensure_model_preserves_confirmations_across_data_change(tmp_path):
    """데이터 교체가 확정 매핑을 조용히 초안으로 갈아치우지 않는다(보존 + notice)."""
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
    assert snap["is_complete"] is True                   # 확정 보존(소실 없음)
    assert snap["rows"][0]["const"] == "보존값"
    assert snap["notice"] and "유지했습니다" in snap["notice"]["text"]


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


# ------------------------------------------------------- 매핑 프로파일(#5)
def test_profile_save_apply_list_delete_roundtrip(tmp_path):
    ctrl, _ = _controller26(tmp_path)
    _build_complete_session(ctrl, "프로작업")
    r = ctrl.dispatch("profile_save", {"name": "표준매핑"})
    assert r["ok"] is True and r["rows"] == 10

    assert ctrl.dispatch("save", {})["ok"] is True        # 작업 저장 → 계보 기록
    reg = JobRegistry(tmp_path / "jobs")
    assert reg.load("프로작업").base_mapping_name == "표준매핑"

    lst = ctrl.dispatch("profile_list", {})
    assert lst["bases"][0]["name"] == "표준매핑"
    assert lst["bases"][0]["job_refs"] == 1               # 참조 작업 수(전파 경고 근거)

    # 새 세션에 적용 → 전 행 확정 도착.
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.dispatch("skip_data", {})
    r2 = ctrl.dispatch("profile_apply", {"name": "표준매핑"})
    assert r2["ok"] is True and r2["applied"] == 10 and r2["dropped"] == []
    snap = ctrl.snapshot()
    assert snap["is_complete"] is True and snap["base_name"] == "표준매핑"

    # 동명 재저장 → 참조 수와 함께 확인 승격.
    r3 = ctrl.dispatch("profile_save", {"name": "표준매핑"})
    assert r3.get("needs_confirm") is True and "1개" in r3["confirm_text"]
    assert ctrl.dispatch("profile_save", {"name": "표준매핑", "confirm": True})["ok"] is True

    # 삭제 라운드트립(참조 재진술 → 확정).
    d1 = ctrl.dispatch("profile_delete", {"name": "표준매핑"})
    assert d1.get("needs_confirm") is True
    assert ctrl.dispatch("profile_delete", {"name": "표준매핑", "confirm": True})["ok"] is True
    assert ctrl.dispatch("profile_list", {})["bases"] == []


def test_profile_save_requires_confirmed_rows(tmp_path):
    ctrl, _ = _controller26(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.dispatch("skip_data", {})                        # 모델 생성, 전 행 미확정
    res = ctrl.dispatch("profile_save", {"name": "빈베이스"})
    assert res["ok"] is False and "확정" in res["error"]


def test_profile_apply_missing_is_loud(tmp_path):
    ctrl, _ = _controller26(tmp_path)
    ctrl.load_template_path(str(TPL_COMPILED))
    ctrl.dispatch("skip_data", {})
    res = ctrl.dispatch("profile_apply", {"name": "없는베이스"})
    assert res["ok"] is False and "불러올 수 없습니다" in res["error"]
