"""「기안」 화면 컨트롤러(#148) — 조회 경계 · 라우터 공유 · 휘발 세션 병합.

「작업」(HWPX)의 대칭 화면이라 저장 기계는 하나(``JobRegistry``)이고 매체는 선언하지 않고
``template_path`` 접미사에서 유도한다(R-info 3부 결정 4·13). 슬라이스 3a 에서 우 상세가
휘발 세션 4존이 되면서 목록 컨트롤러와 세션 믹스인이 **한 라우터**를 공유한다 — 그 합류점의
계약(누가 무엇을 소유하고, 무엇이 서로를 건드리지 않는가)을 여기서 못박는다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.core.dataset_pool import DatasetPoolRegistry
from hwpxfiller.core.job import Job, JobRegistry
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.core.text_registry import TextTemplateRegistry
from hwpxfiller.gui.selection_state import SelectionModel
from hwpxfiller.gui.txt_queue import TxtQueueModel
from hwpxfiller.webapp.draft_session import TargetFontSetting
from hwpxfiller.webapp.screen_draft import DraftController
from hwpxfiller.webapp.screen_txt import TxtController


def _arm_queue(ctrl, selected: int = 2, copied: int = 1) -> None:
    """저장 세션에 데이터·큐 진행을 심어 무장 상태를 만든다(0<copied<selected = queue_partial).

    실 데이터 파일 없이 링1 모델을 직접 세워 T3 무장을 재현한다 — 저장 세션의 진행이 전환·귀환에
    사라지는지(리뷰 5a P1) 확인하는 데 필요한 최소 상태."""
    ctrl.selection = SelectionModel(selected)
    ctrl.queue = TxtQueueModel(ctrl.selection)
    for i in range(copied):
        ctrl.queue.copy(i)


def _controller(tmp_path: Path, **kw) -> "tuple[DraftController, JobRegistry, list]":
    (tmp_path / "착수계.txt").write_text("제목: {{공고명}}", encoding="utf-8")
    jobs = JobRegistry(tmp_path / "jobs")
    pushes: list = []
    ctrl = DraftController(
        jobs,
        lambda s, snap: pushes.append((s, snap)),
        TextTemplateRegistry(tmp_path),
        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
        **kw,
    )
    return ctrl, jobs, pushes


def _save(jobs: JobRegistry, name: str, template: str) -> None:
    jobs.save(Job(name=name, template_path=template))


def _save_real(tmp_path: Path, jobs: JobRegistry, name: str, filename: str,
               content: str, mappings: "tuple[FieldMapping, ...]" = ()) -> str:
    """실 파일을 가진 TXT 저장 기안 — 복원(_restore_from_job)이 원문을 실제로 읽는다.

    복원은 실패 원자적이라 fake 경로로는 세션이 서지 않는다(파일 부재 = OSError). 복원 계약을
    확인하려면 진짜 템플릿 파일과 매핑 프로파일이 있어야 한다."""
    path = tmp_path / filename
    path.write_text(content, encoding="utf-8")
    jobs.save(Job(name=name, template_path=str(path),
                  mapping=MappingProfile(name=name, mappings=list(mappings))))
    return str(path)


# ------------------------------------------------------------------ 조회 경계(결정 13 · 1층)
def test_lists_only_txt_media_jobs(tmp_path):
    """좌 목록은 TXT 작업만 본다 — 매체는 저장 필드가 아니라 경로 접미사에서 유도(결정 4)."""
    ctrl, jobs, _ = _controller(tmp_path)
    _save(jobs, "기안A", "C:/t/a.txt")
    _save(jobs, "문서B", "C:/t/b.hwpx")
    _save(jobs, "저작중C", "")  # 미링크 = 매체 미상 → 「작업」 몫(여기 나오면 안 된다)
    names = [r["name"] for r in ctrl.snapshot()["job_rows"]]
    assert names == ["기안A"], f"조회 경계 파손: {names!r}"


# ------------------------------------------------------------------ 스냅샷 병합
def test_snapshot_merges_list_and_session_keys(tmp_path):
    """스냅샷 = 목록 키 + 세션 조각. 세션 키 이름은 「기안문 채우기」와 **문자 그대로 같다**
    (draft.js 가 datazone.js·segview.js 를 그대로 소비 — 이름이 갈라지면 재사용이 깨진다)."""
    ctrl, _jobs, _ = _controller(tmp_path)
    snap = ctrl.snapshot()
    for key in ("job_rows", "job_sections", "job_flat", "job_group_names", "job_name", "has_job"):
        assert key in snap, f"목록 키 {key} 누락"
    for key in ("template_name", "template_text", "tokens", "record_count", "data_source_label",
                "data_key", "has_data", "selected_count", "target_font", "filter", "table", "card",
                "mode", "source_readonly", "bound_job", "source_dirty"):
        assert key in snap, f"세션 키 {key} 누락 — 팩토리 계약 파손"
    # 같은 사실을 두 번 선언하지 않는다 — 표면 분기(has_job·mode·source_readonly)는 모두
    # _bound_job 한 필드에서 유도한다(session_ready 같은 별도 플래그 금지).
    assert "session_ready" not in snap
    assert snap["mode"] == "volatile" and snap["source_readonly"] is False and snap["bound_job"] == ""


def test_initial_lists_templates(tmp_path):
    ctrl, _jobs, _ = _controller(tmp_path)
    assert ctrl.initial()["templates"] == ["착수계"]


# ------------------------------------------------------------ 두 세션 병존(슬라이스 5a)
def test_two_sessions_coexist_select_restores_and_return_preserves_volatile(tmp_path):
    """저장 기안 선택 = 그 Job 에서 복원(저장 모드), 「이번 세션」 귀환 = 붙여넣던 휘발 그대로.

    두 세션 병존(소실 0): 붙여넣다 저장 기안을 골라 저장-세션을 세워도 휘발 세션은 스태시돼
    살아 있고, 빈 이름으로 돌아오면 붙여넣던 원문·진행이 복구된다. 저장-세션은 Job 원문을
    싣고 읽기 전용이다(정의가 조용히 갈라지지 않게, 결정 7)."""
    ctrl, jobs, _ = _controller(tmp_path)
    _save_real(tmp_path, jobs, "착수계 기안", "job_a.txt", "저장 원문 {{공고명}}")
    ctrl.dispatch("set_template_text", {"text": "붙여넣은 원문 {{공고명}}"})
    ctrl.dispatch("select_job", {"name": "착수계 기안"})
    saved = ctrl.snapshot()
    assert saved["has_job"] is True and saved["mode"] == "saved"
    assert saved["source_readonly"] is True and saved["bound_job"] == "착수계 기안"
    assert saved["template_text"] == "저장 원문 {{공고명}}"  # Job 원문으로 복원
    ctrl.dispatch("select_job", {"name": ""})       # 「이번 세션」 = 휘발 귀환
    vol = ctrl.snapshot()
    assert vol["has_job"] is False and vol["mode"] == "volatile"
    assert vol["source_readonly"] is False and vol["bound_job"] == ""
    assert vol["template_text"] == "붙여넣은 원문 {{공고명}}"  # 붙여넣던 세션 그대로


def test_restore_applies_profile_confirmed(tmp_path):
    """저장 기안 복원은 매핑을 사람 소유 확정으로 되살린다(apply_profile confirm=True, 결정 12).

    프로파일은 과거 사람 확정 산출물이라 확정본으로 도착한다 — 라이브 재제안이 덮지 못하고,
    확정 열이 체크된 채 뜬다(저장 모드에서 열이 보인다)."""
    ctrl, jobs, _ = _controller(tmp_path)
    _save_real(tmp_path, jobs, "확정 기안", "job_c.txt", "제목: {{공고명}}",
               mappings=(FieldMapping(template_field="공고명", source="공고명", type="text"),))
    ctrl.dispatch("select_job", {"name": "확정 기안"})
    snap = ctrl.snapshot()
    tok = next(t for t in snap["tokens"] if t["name"] == "공고명")
    assert tok["confirmed"] is True, "복원한 매핑이 확정본으로 도착하지 않았습니다(결정 12)."
    assert tok["source"] == "공고명"


def test_switching_saved_jobs_keeps_stashed_volatile(tmp_path):
    """저장 기안 A→B 전환은 휘발을 다시 스태시하지 않는다 — 스태시한 휘발은 계속 산다.

    저장-세션은 Job 에서 결정적으로 재구성되니 잃을 게 없다(재스태시 불필요). 두 저장 기안을
    오가도 처음 얼려 둔 붙여넣기 세션이 그대로 있어, 마침내 「이번 세션」으로 돌아오면 복구된다."""
    ctrl, jobs, _ = _controller(tmp_path)
    _save_real(tmp_path, jobs, "기안A", "job_a.txt", "A 원문 {{공고명}}")
    _save_real(tmp_path, jobs, "기안B", "job_b.txt", "B 원문 {{공고명}}")
    ctrl.dispatch("set_template_text", {"text": "붙여넣기 {{공고명}}"})
    ctrl.dispatch("select_job", {"name": "기안A"})
    ctrl.dispatch("select_job", {"name": "기안B"})
    assert ctrl.snapshot()["template_text"] == "B 원문 {{공고명}}"
    ctrl.dispatch("select_job", {"name": ""})
    assert ctrl.snapshot()["template_text"] == "붙여넣기 {{공고명}}"


def test_bound_job_deleted_returns_to_volatile(tmp_path):
    """결속 중인 저장 기안이 삭제되면 휘발 세션으로 복귀한다 — 사라진 정의가 저장 모드로 뜨지 않게."""
    ctrl, jobs, _ = _controller(tmp_path)
    _save_real(tmp_path, jobs, "기안A", "job_a.txt", "A 원문 {{공고명}}")
    ctrl.dispatch("set_template_text", {"text": "붙여넣기 {{공고명}}"})
    ctrl.dispatch("select_job", {"name": "기안A"})
    ctrl.dispatch("delete_job", {"name": "기안A", "confirm": True})
    snap = ctrl.snapshot()
    assert snap["has_job"] is False and snap["mode"] == "volatile"
    assert snap["template_text"] == "붙여넣기 {{공고명}}"  # 스태시한 휘발 복원


def test_deleting_bound_session_with_progress_restates_loss(tmp_path):
    """결속 중인 저장 기안을 삭제하면 세션 진행 소실도 재진술한다(리뷰 5a 2R P1, screen_job 동형).

    삭제는 정의(템플릿 연결·매핑)만 아니라 결속 세션의 데이터·선택·큐 진행도 없앤다 — Job 에
    저장되지 않아 복원 불가다. 무확인 응답에 ``open_session`` 과 무장 수치(_guard_state)를 실어
    표면이 파괴 전모를 한 모달로 말하게 한다(confirm-or-alarm)."""
    ctrl, jobs, _ = _controller(tmp_path)
    _save_real(tmp_path, jobs, "기안A", "job_a.txt", "A {{공고명}}")
    ctrl.dispatch("select_job", {"name": "기안A"})
    _arm_queue(ctrl, selected=2, copied=1)             # 1/2 복사 = queue_partial → armed
    res = ctrl.dispatch("delete_job", {"name": "기안A"})
    assert res["needs_confirm"] is True
    assert res["open_session"] is True, "결속 세션 삭제가 open_session 을 빠뜨렸습니다(조용한 소실)."
    assert res["armed"] is True and res["copied_count"] == 1
    assert ctrl.snapshot()["bound_job"] == "기안A"      # 확인 전 = 안 지움


def test_deleting_unbound_job_reports_no_session_loss(tmp_path):
    """결속 아닌 기안 삭제는 세션 무영향 — 정의 삭제만 재진술하고 진행 수치를 부풀리지 않는다.

    현 세션은 다른 기안(또는 휘발)에 물려 있는데도 open_session/armed 를 실으면 지우지도 않을
    진행을 잃는다고 거짓 경고한다(over-warn 도 confirm-or-alarm 위반)."""
    ctrl, jobs, _ = _controller(tmp_path)
    _save_real(tmp_path, jobs, "기안A", "job_a.txt", "A {{공고명}}")
    _save_real(tmp_path, jobs, "기안B", "job_b.txt", "B {{공고명}}")
    ctrl.dispatch("select_job", {"name": "기안A"})
    _arm_queue(ctrl, selected=2, copied=1)             # 기안A 세션에 진행이 있어도
    res = ctrl.dispatch("delete_job", {"name": "기안B"})  # 결속 아닌 기안B 삭제는 무영향
    assert res["needs_confirm"] is True and res["open_session"] is False
    assert "armed" not in res, "결속 아닌 삭제가 무관한 세션 무장 수치를 실었습니다(거짓 경고)."


def test_leaving_saved_session_with_progress_needs_confirm(tmp_path):
    """저장 세션(진행 있음)에서 다른 기안으로 전환 = 확인 왕복(리뷰 5a P1) — 진행은 Job 에 없어 사라진다.

    저장 세션의 데이터·큐 진행은 Job 에 저장되지 않아 전환 시 재구성으로 소실된다(휘발과 달리
    스태시 보존 대상 아님). 무장이면 파괴를 재진술하고, 확인해야 넘어간다(T3 동형)."""
    ctrl, jobs, _ = _controller(tmp_path)
    _save_real(tmp_path, jobs, "기안A", "job_a.txt", "A {{공고명}}")
    _save_real(tmp_path, jobs, "기안B", "job_b.txt", "B {{공고명}}")
    ctrl.dispatch("select_job", {"name": "기안A"})
    _arm_queue(ctrl, selected=2, copied=1)             # 1/2 복사 = queue_partial → armed
    res = ctrl.dispatch("select_job", {"name": "기안B"})
    assert res["needs_confirm"] is True and res["copied_count"] == 1
    assert ctrl.snapshot()["bound_job"] == "기안A"      # 확인 전 = 안 떠남
    ctrl.dispatch("select_job", {"name": "기안B", "confirm": True})
    assert ctrl.snapshot()["bound_job"] == "기안B"


def test_leaving_saved_session_to_volatile_also_guarded(tmp_path):
    """「이번 세션」 귀환도 같은 손실 경로다 — 저장 세션 진행이 있으면 확인한다(리뷰 5a P1)."""
    ctrl, jobs, _ = _controller(tmp_path)
    _save_real(tmp_path, jobs, "기안A", "job_a.txt", "A {{공고명}}")
    ctrl.dispatch("select_job", {"name": "기안A"})
    _arm_queue(ctrl, selected=2, copied=1)
    res = ctrl.dispatch("select_job", {"name": ""})
    assert res["needs_confirm"] is True
    assert ctrl.snapshot()["has_job"] is True           # 확인 전 = 안 떠남


def test_leaving_volatile_session_is_not_guarded(tmp_path):
    """휘발 세션 전환은 가드하지 않는다 — 스태시로 보존되니 잃을 게 없다(가드는 저장 세션 전용)."""
    ctrl, jobs, _ = _controller(tmp_path)
    _save_real(tmp_path, jobs, "기안A", "job_a.txt", "A {{공고명}}")
    ctrl.dispatch("set_template_text", {"text": "붙여넣기 {{공고명}}"})
    _arm_queue(ctrl, selected=2, copied=1)              # 휘발에도 진행이 있지만
    res = ctrl.dispatch("select_job", {"name": "기안A"})  # 곧바로 복원(확인 없음 — 스태시 보존)
    assert res is None and ctrl.snapshot()["bound_job"] == "기안A"


def test_restore_missing_template_is_atomic_and_loud(tmp_path):
    """템플릿 파일이 사라진 저장 기안 선택은 상태를 바꾸지 않고 시끄럽게 재진술한다(원자성).

    복원은 실패 가능한 파일 읽기를 먼저 끝낸 뒤에야 세션을 교체한다 — 파일 부재면 스태시한
    휘발 세션이 반쪽으로 오염되지 않고, 붙여넣던 원문이 그대로 남는다(confirm-or-alarm)."""
    ctrl, jobs, _ = _controller(tmp_path)
    _save(jobs, "유령 기안", "C:/없는/파일.txt")  # 실 파일 없음
    ctrl.dispatch("set_template_text", {"text": "살아남을 원문 {{공고명}}"})
    res = ctrl.dispatch("select_job", {"name": "유령 기안"})
    assert res and res.get("ok") is False, "부재 템플릿 복원이 조용히 성공했습니다(confirm-or-alarm 위반)."
    snap = ctrl.snapshot()
    assert snap["has_job"] is False and snap["mode"] == "volatile"
    assert snap["template_text"] == "살아남을 원문 {{공고명}}"


# ------------------------------------------------------ 「사본으로 편집」 포크(슬라이스 5b)
def test_fork_to_volatile_unbinds_and_makes_editable(tmp_path):
    """「사본으로 편집」 = 저장→휘발 분기: Job 결속을 끊고 원문 편집 가능, 값·매핑은 승계.

    저장된 기안은 건드리지 않고 이 세션만 사본으로 가른다 — 원문 읽기 전용이 풀리고 수정됨
    표지가 뜨며, 결속·값은 그대로다(사본이지 새 세션이 아니다)."""
    ctrl, jobs, _ = _controller(tmp_path)
    _save_real(tmp_path, jobs, "기안A", "job_a.txt", "저장 원문 {{공고명}}",
               mappings=(FieldMapping(template_field="공고명", source="공고명", type="text"),))
    ctrl.dispatch("select_job", {"name": "기안A"})
    assert ctrl.snapshot()["source_readonly"] is True
    ctrl.dispatch("fork_to_volatile", {})
    snap = ctrl.snapshot()
    assert snap["has_job"] is False and snap["mode"] == "volatile"
    assert snap["source_readonly"] is False and snap["source_dirty"] is True
    assert snap["bound_job"] == ""
    assert snap["template_text"] == "저장 원문 {{공고명}}"       # 원문 승계
    tok = next(t for t in snap["tokens"] if t["name"] == "공고명")
    assert tok["source"] == "공고명"                            # 결속(값) 승계


def test_edit_source_blocked_in_saved_mode_then_allowed_after_fork(tmp_path):
    """저장 원문은 읽기 전용 — edit_source 가 무시된다(백엔드 방어). 포크 후엔 편집이 먹는다.

    표면 textarea readonly 로 이미 막지만, 백엔드도 조용한 정의 분기를 막는다(저장 정의가
    라이브 편집으로 갈라지지 않게). 사본으로 가른 뒤에야 원문이 바뀐다."""
    ctrl, jobs, _ = _controller(tmp_path)
    _save_real(tmp_path, jobs, "기안A", "job_a.txt", "저장 원문 {{공고명}}")
    ctrl.dispatch("select_job", {"name": "기안A"})
    ctrl.dispatch("edit_source", {"text": "몰래 바꾼 원문 {{공고명}}"})   # 읽기 전용 — 무시
    assert ctrl.snapshot()["template_text"] == "저장 원문 {{공고명}}"
    ctrl.dispatch("fork_to_volatile", {})
    ctrl.dispatch("edit_source", {"text": "사본에서 고친 원문 {{담당}}"})
    snap = ctrl.snapshot()
    assert snap["template_text"] == "사본에서 고친 원문 {{담당}}"
    assert snap["source_dirty"] is True


def test_fork_displacing_armed_stash_needs_confirm(tmp_path):
    """포크가 무장한 이전 휘발 세션을 밀어내면 확인 왕복한다(리뷰 5b 2R P1 — 조용한 소실 금지).

    붙여넣던 휘발 세션에 선택·큐 진행을 심고(무장), 저장 기안을 골라 스태시한 뒤 포크하면 —
    사본이 유일 휘발이 되어 스태시를 대체한다(단일 슬롯). 그 진행은 Job 에 없어 복구 불가라
    포크는 needs_confirm 으로 되묻고, 확인 전에는 아직 저장 모드(포크 미완)다."""
    ctrl, jobs, _ = _controller(tmp_path)
    _save_real(tmp_path, jobs, "기안A", "job_a.txt", "저장 원문 {{공고명}}")
    ctrl.dispatch("set_template_text", {"text": "붙여넣던 원문 {{공고명}}"})
    _arm_queue(ctrl, selected=2, copied=1)             # 붙여넣던 휘발에 복구 불가 진행
    ctrl.dispatch("select_job", {"name": "기안A"})       # 무장 휘발이 스태시됨
    res = ctrl.dispatch("fork_to_volatile", {})
    assert res and res["needs_confirm"] is True and res["kind"] == "fork_displaces_stash"
    assert res["copied_count"] == 1
    assert ctrl.snapshot()["mode"] == "saved"           # 확인 전 = 포크 안 됨
    ctrl.dispatch("fork_to_volatile", {"confirm": True})
    assert ctrl.snapshot()["mode"] == "volatile"


def test_fork_clears_stash_so_next_select_does_not_orphan_copy(tmp_path):
    """포크는 스태시를 비워, 뒤이은 저장 선택이 사본을 밀려난 세션 위로 덮어 지우지 않게 한다.

    포크 후엔 사본이 유일 휘발이다 — 다른 저장 기안을 골랐다 「이번 세션」으로 돌아오면 (밀려난
    옛 세션이 아니라) 이 사본이 복구돼야 한다(스태시 슬롯이 사본으로 새로 채워짐)."""
    ctrl, jobs, _ = _controller(tmp_path)
    _save_real(tmp_path, jobs, "기안A", "job_a.txt", "A 저장 원문 {{공고명}}")
    _save_real(tmp_path, jobs, "기안B", "job_b.txt", "B 저장 원문 {{공고명}}")
    ctrl.dispatch("set_template_text", {"text": "밀려날 붙여넣기 {{공고명}}"})
    ctrl.dispatch("select_job", {"name": "기안A"})       # 붙여넣기 세션 스태시
    ctrl.dispatch("fork_to_volatile", {})               # 미무장 스태시 → 확인 없이 포크(스태시 비움)
    ctrl.dispatch("edit_source", {"text": "사본에서 고친 원문 {{공고명}}"})
    ctrl.dispatch("select_job", {"name": "기안B"})       # 사본이 새로 스태시
    ctrl.dispatch("select_job", {"name": ""})           # 「이번 세션」 = 사본 복구(옛 세션 아님)
    assert ctrl.snapshot()["template_text"] == "사본에서 고친 원문 {{공고명}}"


def test_fork_displacing_unarmed_stash_is_silent(tmp_path):
    """미무장 이전 휘발(붙여넣기 텍스트만)은 확인 없이 포크한다 — 텍스트는 복구 가능(과경보 금지).

    새 기안 가드와 같은 문턱: 복구 불가 진행(선택·큐)만 되묻고, 재입력 가능한 원문 텍스트
    손실로는 사용자를 막지 않는다(over-warn 도 confirm-or-alarm 위반)."""
    ctrl, jobs, _ = _controller(tmp_path)
    _save_real(tmp_path, jobs, "기안A", "job_a.txt", "저장 원문 {{공고명}}")
    ctrl.dispatch("set_template_text", {"text": "붙여넣기만 {{공고명}}"})  # 무장 아님
    ctrl.dispatch("select_job", {"name": "기안A"})
    res = ctrl.dispatch("fork_to_volatile", {})
    assert res is None and ctrl.snapshot()["mode"] == "volatile"


def test_source_dirty_false_for_clean_sources(tmp_path):
    """수정됨 표지는 깨끗한 원문(첫 템플릿·새 붙여넣기)엔 뜨지 않는다 — 라이브러리에서 갈라졌을 때만."""
    ctrl, _jobs, _ = _controller(tmp_path)
    assert ctrl.snapshot()["source_dirty"] is False           # 첫 템플릿(라이브러리)
    ctrl.dispatch("set_template_text", {"text": "붙여넣기 {{공고명}}"})
    assert ctrl.snapshot()["source_dirty"] is False           # 새 붙여넣기 = 깨끗한 시작


def test_fork_is_noop_when_already_volatile(tmp_path):
    """휘발 세션에서 포크는 무동작 — 가를 저장 정의가 없다(수정됨으로 오염되지 않는다)."""
    ctrl, _jobs, _ = _controller(tmp_path)
    ctrl.dispatch("set_template_text", {"text": "붙여넣기 {{공고명}}"})
    ctrl.dispatch("fork_to_volatile", {})
    snap = ctrl.snapshot()
    assert snap["mode"] == "volatile" and snap["source_dirty"] is False


# ------------------------------------------------------------------ 공유 라우터(슬라이스 3a)
def test_router_is_shared_between_list_and_session_actions(tmp_path):
    """목록 액션과 세션 액션이 한 라우터를 탄다(MRO) — 미지 액션은 시끄럽게."""
    ctrl, jobs, pushes = _controller(tmp_path)
    _save(jobs, "기안A", "C:/t/a.txt")
    ctrl.dispatch("toggle_group", {"group": ""})     # 목록 계열
    ctrl.dispatch("set_target_font", {"font": "malgun"})  # 세션 계열
    assert len(pushes) == 2 and {s for s, _ in pushes} == {"draft"}


def test_confirm_roundtrip_skips_push(tmp_path):
    """확인 왕복(needs_confirm)은 변이가 없으므로 재렌더도 없다 — RC-02 동형."""
    ctrl, jobs, pushes = _controller(tmp_path)
    _save(jobs, "기안A", "C:/t/a.txt")
    res = ctrl.dispatch("delete_job", {"name": "기안A"})
    assert res["needs_confirm"] is True and pushes == []
    ctrl.dispatch("delete_job", {"name": "기안A", "confirm": True})
    assert pushes and ctrl.snapshot()["job_rows"] == []


def test_query_actions_skip_push(tmp_path):
    """무변이 질의(guard_state)는 push 를 생략한다 — 세션 믹스인 규약 승계."""
    ctrl, _jobs, pushes = _controller(tmp_path)
    assert ctrl.dispatch("guard_state", {})["armed"] is False
    assert pushes == []


def test_unknown_action_is_loud(tmp_path):
    ctrl, _jobs, _ = _controller(tmp_path)
    with pytest.raises(ValueError, match="기안 화면"):
        ctrl.dispatch("nope", {})


# ------------------------------------------------------------------ 전역 글꼴 선언(코덱스 P2)
def test_target_font_setting_is_shared_across_surfaces(tmp_path):
    """대상 글꼴 선언은 **앱 전역**이라 두 기안 표면이 한 실체를 본다.

    회귀 원본(코덱스 리뷰 P2): 컨트롤러마다 사본을 캐시하면 한쪽에서 바꾼 선언이 다른 쪽에
    **재부팅까지 도달하지 않는다** — 저장은 됐는데 그 화면의 콤보·미리보기 글꼴·비례폭 정렬
    린트는 옛 값으로 판정한다(선언과 실제가 갈라지는 지배 결함류).
    """
    shared = TargetFontSetting()
    ctrl, _jobs, _ = _controller(tmp_path, target_font=shared)
    txt = TxtController(TextTemplateRegistry(tmp_path), lambda s, snap: None,
                        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
                        target_font=shared)
    assert ctrl.snapshot()["target_font"] == txt.snapshot()["target_font"] == "gulimche"
    txt.dispatch("set_target_font", {"font": "malgun"})   # 구 화면에서 선언 변경
    assert ctrl.snapshot()["target_font"] == "malgun", "다른 기안 표면에 선언이 도달하지 않았습니다."
    # 비례폭 판정(정렬 린트의 근거)도 같은 값을 따라간다 — 문안만 갈라지는 일이 없게.
    assert ctrl.snapshot()["card"]["lint"]["proportional"] is True


def test_target_font_sharing_comes_only_from_injection(tmp_path):
    """공유는 **주입으로만** 일어난다 — 미주입이면 독립 인스턴스(테스트·단독 구동 불변).

    모듈 전역 캐시로 풀지 않은 이유가 이것이다: 전역이면 테스트 사이로 값이 새어 실행 순서에
    묶인 위양성이 생긴다. 공유해야 할 곳(앱)이 명시적으로 하나를 건네는 형태로 둔다.
    """
    a, _j, _p = _controller(tmp_path)
    b, _j2, _p2 = _controller(tmp_path)
    assert a._font is not b._font
    shared = TargetFontSetting()
    c, _j3, _p3 = _controller(tmp_path, target_font=shared)
    d, _j4, _p4 = _controller(tmp_path, target_font=shared)
    assert c._font is d._font is shared
