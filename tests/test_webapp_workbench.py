"""TXT 검토·복사 작업대(v6 S7 · 계약 §11) — 헤드리스 컨트롤러 계약. 재작성 F6 PR-A.

여기서 보는 것은 **작업대가 소유한 판정**이다: 고정 사본 불변식(§13-13) · 미저장 변경의
어휘(override 아님) · 저장 왕복(판본·다시 확인 필요) · 복사 전진 · 이탈 가드 열거.
큐 자체 회귀는 ``test_txt_queue``, 카드 렌더 통로는 ``test_txt_card``, 진입 자격은
``test_webapp_job`` 소관 — 여기는 결선만 본다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from hwpxfiller.core.job import Job, JobRegistry
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.webapp.draft_session import TargetFontSetting
from hwpxfiller.webapp.screen_workbench import WorkbenchController


def _job(tmp_path: Path, *, name: str = "발주요청_기안") -> Job:
    tpl = tmp_path / "발주요청_기안.txt"
    tpl.write_text("수신: {{수신}}\n건명: {{건명}}", encoding="utf-8")
    return Job(
        name=name,
        template_path=str(tpl),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="수신", source="부서"),
            FieldMapping(template_field="건명", source="사업명"),
        ]),
    )


def _rows() -> "list[tuple[int, dict]]":
    return [
        (2, {"부서": "회계과", "사업명": "복사기 임차"}),
        (0, {"부서": "총무과", "사업명": "책상 구매"}),
    ]


def _ctrl(tmp_path: Path) -> "tuple[WorkbenchController, JobRegistry, list]":
    reg = JobRegistry(tmp_path / "jobs")
    pushes: list = []
    ctrl = WorkbenchController(
        reg, lambda s, snap: pushes.append((s, snap)),
        target_font=TargetFontSetting(),
    )
    return ctrl, reg, pushes


def _open(tmp_path: Path):
    ctrl, reg, pushes = _ctrl(tmp_path)
    job = _job(tmp_path)
    reg.save(job)
    ctrl.open(reg.load(job.name), _rows())
    return ctrl, reg, pushes


# ------------------------------------------------------------------ 세션 수명
def test_no_session_is_the_boot_default_and_the_screen_knows_it(tmp_path):
    """세션 없음이 부팅 기본값이다 — 라우팅만으로 문맥 없는 작업대가 서지 않게(F7 선례)."""
    ctrl, _, _ = _ctrl(tmp_path)
    snap = ctrl.snapshot()
    assert snap["open"] is False and snap["card"] is None and snap["rows"] == []
    with pytest.raises(ValueError):
        ctrl.dispatch("step", {"delta": 1})


def test_open_takes_a_frozen_copy_that_outside_changes_cannot_touch(tmp_path):
    """§13-13 — 진입 시 사본을 뜬다. 바깥 레코드를 고쳐도 세션의 순서·값이 안 바뀐다."""
    ctrl, reg, _ = _ctrl(tmp_path)
    job = _job(tmp_path)
    reg.save(job)
    rows = _rows()
    ctrl.open(reg.load(job.name), rows)
    rows[0][1]["부서"] = "바뀐과"          # 바깥에서 원본을 고친다
    rows.append((9, {"부서": "새 행", "사업명": "새 사업"}))
    snap = ctrl.snapshot()
    assert snap["total"] == 2             # 사본이라 새 행이 들어오지 않는다
    assert "회계과" in "".join(s["text"] for s in snap["card"]["segments"])


def test_entry_order_is_the_display_order_it_was_given(tmp_path):
    """표시순 투영 그대로 — 작업대가 순서를 다시 정하지 않는다(§18.10 수용 7)."""
    ctrl, _, _ = _open(tmp_path)
    assert ctrl.source_rows == [3, 1]     # 1-based 원본 행 번호(표시순 그대로)
    assert ctrl.snapshot()["card"]["source_row"] == 3


def test_template_read_failure_leaves_the_previous_state_untouched(tmp_path):
    """실패 원자성 — 템플릿을 못 읽으면 반쪽 세션으로 화면이 서지 않는다."""
    ctrl, reg, _ = _open(tmp_path)
    broken = Job(name="깨진기안", template_path=str(tmp_path / "없는파일.txt"))
    with pytest.raises(OSError):
        ctrl.open(broken, _rows())
    assert ctrl.job_name == "발주요청_기안" and ctrl.is_open


# --------------------------------------------------- 좌 pane = 미저장 변경(override 아님)
def test_editing_a_binding_is_an_unsaved_change_not_an_override(tmp_path):
    """편집은 저장 전까지 **미저장 변경**이다 — 착지점은 「기본 규칙으로 저장」 하나(판정 H).

    v6 배지 「이번 작업에만 적용 중」이 말할 상태가 없다는 것이 이 단언의 요지다: 저장하지
    않은 변경은 세션이 끝나면 사라지고, 저장하면 **기본 규칙**이 된다. 그 사이에 「이번
    생성에만 듣는 규칙」이라는 제3의 상태가 없다.
    """
    ctrl, reg, _ = _open(tmp_path)
    assert ctrl.snapshot()["dirty"] == {"count": 0, "fields": [], "pending": False}
    ctrl.dispatch("set_source", {"index": 0, "source": "사업명"})
    ctrl.dispatch("set_confirmed", {"index": 0, "value": True})
    d = ctrl.snapshot()["dirty"]
    assert d["count"] == 1 and d["fields"][0]["name"] == "수신"
    # 디스크는 아직 그대로다 — 미저장이라는 말이 참이어야 한다.
    assert reg.load("발주요청_기안").mapping.mappings[0].source == "부서"


def test_unconfirmed_edits_block_saving_but_still_count_as_losable(tmp_path):
    """확정하지 않은 편집은 저장을 막되 **가드에는 잡힌다** — 버려지면 사라지기 때문이다."""
    ctrl, _, _ = _open(tmp_path)
    ctrl.dispatch("set_map_value", {"index": 0, "value": "직접 쓴 값"})
    snap = ctrl.snapshot()
    assert snap["save_block"] and snap["can_save"] is False
    assert snap["dirty"]["pending"] is True
    assert any("확정하지 않은" in line for line in snap["guard"]["lines"])


# ------------------------------------------------------------------ 저장 왕복
def test_save_lists_every_dirty_field_before_it_commits(tmp_path):
    """§11 — 영구 저장 확인에는 **모든 dirty 필드를 나열**한다."""
    ctrl, _, _ = _open(tmp_path)
    ctrl.dispatch("set_source", {"index": 0, "source": "사업명"})
    ctrl.dispatch("set_confirmed", {"index": 0, "value": True})
    first = ctrl.dispatch("save_rules", {})
    assert first["needs_confirm"] is True and first["fields"] == ["수신"]


def test_save_bumps_the_binding_revision_and_keeps_the_work_point(tmp_path):
    """저장 뒤 재검증하고 **같은 작업점**으로 돌아온다(§11) — 판본은 저장이 정산한다."""
    ctrl, reg, _ = _open(tmp_path)
    ctrl.dispatch("step", {"delta": 1})
    before_point = ctrl.queue.current
    before_rev = reg.load("발주요청_기안").binding_revision
    ctrl.dispatch("set_source", {"index": 0, "source": "사업명"})
    ctrl.dispatch("set_confirmed", {"index": 0, "value": True})
    res = ctrl.dispatch("save_rules", {"confirm": True})
    assert res["ok"] and res["binding_revision"] == before_rev + 1
    assert ctrl.queue.current == before_point
    snap = ctrl.snapshot()
    assert snap["dirty"]["count"] == 0            # 저장분이 새 기준선이 됐다
    assert snap["revision"]["binding"] == before_rev + 1


def test_saving_marks_already_copied_records_for_recheck(tmp_path):
    """이미 복사한 레코드는 **다시 확인 필요**가 된다(§11 마지막 줄).

    큐 진행(무엇을 붙여넣었는가)은 지우지 않는다 — 갈린 것은 「확인했는가」다.
    """
    ctrl, _, _ = _open(tmp_path)
    text, report = ctrl.render()
    ctrl.note_copied(report)
    assert ctrl.snapshot()["card"]["review_state"] == "copied"
    ctrl.dispatch("set_source", {"index": 0, "source": "사업명"})
    ctrl.dispatch("set_confirmed", {"index": 0, "value": True})
    ctrl.dispatch("save_rules", {"confirm": True})
    assert ctrl.snapshot()["card"]["review_state"] == "recheck"
    assert ctrl.snapshot()["copied_count"] == 1   # 복사 이력은 그대로
    # 지금 규칙으로 다시 복사하면 재확인이 해소된다.
    ctrl.note_copied(ctrl.render()[1])
    assert ctrl.snapshot()["card"]["review_state"] == "copied"


def test_save_preserves_fields_this_screen_does_not_edit(tmp_path):
    """잠금 안에서 디스크를 다시 읽고 **매핑만** 얹는다 — 그룹·이력은 최신값을 승계한다."""
    ctrl, reg, _ = _open(tmp_path)
    ctrl.dispatch("set_source", {"index": 0, "source": "사업명"})
    ctrl.dispatch("set_confirmed", {"index": 0, "value": True})
    # 세션이 열려 있는 사이 다른 표면이 그룹·완주 스탬프를 바꾼다.
    reg.mutate("발주요청_기안", lambda j: setattr(j, "group", "조달"))
    reg.stamp_last_run("발주요청_기안", "2026-07-28T10:00:00")
    res = ctrl.dispatch("save_rules", {"confirm": True})
    assert res["ok"]
    saved = reg.load("발주요청_기안")
    assert saved.group == "조달" and saved.last_run_at == "2026-07-28T10:00:00"
    assert saved.mapping.mappings[0].source == "사업명"


def test_save_refuses_silently_overwriting_an_externally_changed_work(tmp_path):
    """열어 둔 사이 규칙이 갈렸으면 조용히 덮지 않고 확인을 **다시** 받는다."""
    ctrl, reg, _ = _open(tmp_path)
    ctrl.dispatch("set_source", {"index": 0, "source": "사업명"})
    ctrl.dispatch("set_confirmed", {"index": 0, "value": True})
    reg.mutate(
        "발주요청_기안",
        lambda j: setattr(j, "mapping", MappingProfile(mappings=[
            FieldMapping(template_field="수신", source="다른열"),
            FieldMapping(template_field="건명", source="사업명"),
        ])),
    )
    blocked = ctrl.dispatch("save_rules", {"confirm": True})
    assert blocked["needs_confirm"] is True and blocked["drift"] is True
    assert reg.load("발주요청_기안").mapping.mappings[0].source == "다른열"  # 안 덮었다
    ok = ctrl.dispatch("save_rules", {"confirm": True, "confirm_drift": True})
    assert ok["ok"] and reg.load("발주요청_기안").mapping.mappings[0].source == "사업명"


# ------------------------------------------------------------------ 복사·전진
def test_copy_keeps_the_work_point_unless_advance_is_on(tmp_path):
    """복사해도 작업점은 그 카드에 머문다(조용한 이동 금지) — 전진은 opt-in."""
    ctrl, _, _ = _open(tmp_path)
    start = ctrl.queue.current
    ctrl.note_copied(ctrl.render()[1])
    assert ctrl.queue.current == start
    ctrl.dispatch("toggle_advance", {"value": True})
    ctrl.note_copied(ctrl.render()[1])
    assert ctrl.queue.current != start


def test_card_and_clipboard_take_the_same_path(tmp_path):
    """카드 세그먼트 이어붙임 = 클립보드 텍스트(결정 17 — 링1 공유 통로)."""
    ctrl, _, _ = _open(tmp_path)
    text, _ = ctrl.render()
    assert text == "".join(s["text"] for s in ctrl.snapshot()["card"]["segments"])
    ctrl.dispatch("set_fullwidth", {"value": True})
    text2, _ = ctrl.render()
    assert text2 == "".join(s["text"] for s in ctrl.snapshot()["card"]["segments"])


def test_raw_view_shows_tokens_without_filling_them(tmp_path):
    """원문 보기(§11) — 토큰을 채우지 않는다. 미지 보기 값은 fail-closed."""
    ctrl, _, _ = _open(tmp_path)
    ctrl.dispatch("set_view", {"view": "raw"})
    raw = "".join(s["text"] for s in ctrl.snapshot()["card"]["segments"])
    assert "{{수신}}" in raw and "회계과" not in raw
    with pytest.raises(ValueError):
        ctrl.dispatch("set_view", {"view": "엉뚱"})


def test_copy_gate_excludes_declared_blanks(tmp_path):
    """확정-비움은 복사 전 확인에서 빠진다(결정 12) — 렌더에는 그대로 보인다."""
    ctrl, _, _ = _ctrl(tmp_path)
    reg = JobRegistry(tmp_path / "jobs")
    job = _job(tmp_path)
    reg.save(job)
    ctrl.registry = reg
    ctrl.open(reg.load(job.name), [(0, {"부서": "총무과", "사업명": ""})])
    assert ctrl.dispatch("copy_precheck", {})["empty_fields"] == ["건명"]
    idx = [r["name"] for r in ctrl.snapshot()["rows"]].index("건명")
    # 결속을 **둔 채** 확정하는 것은 선언이 아니다 — 그 빈 값은 그 행의 사실이라 남는다.
    ctrl.dispatch("set_confirmed", {"index": idx, "value": True})
    assert ctrl.dispatch("copy_precheck", {})["empty_fields"] == ["건명"]
    # 결속을 풀고 확정해야 「비운다」 선언이 된다(결정 12).
    ctrl.dispatch("set_source", {"index": idx, "source": ""})
    ctrl.dispatch("set_confirmed", {"index": idx, "value": True})
    assert ctrl.snapshot()["rows"][idx]["blank_declared"] is True
    assert ctrl.dispatch("copy_precheck", {})["empty_fields"] == []


def test_queue_degenerates_for_a_single_record(tmp_path):
    """1건이면 순회할 곳이 없어 큐 장치가 숨는다(승계 — 「기안」 결정 8)."""
    ctrl, reg, _ = _ctrl(tmp_path)
    job = _job(tmp_path)
    reg.save(job)
    ctrl.open(reg.load(job.name), [(0, {"부서": "총무과", "사업명": "책상"})])
    assert ctrl.snapshot()["card"]["queue_degenerate"] is True


# ------------------------------------------------------------------ 이탈 가드
def test_leave_guard_enumerates_only_what_actually_disappears(tmp_path):
    """가드 문안은 실제로 사라지는 집합과 일치한다(과경고 = 거짓말)."""
    ctrl, _, _ = _open(tmp_path)
    assert ctrl.leave_guard() == {"armed": False, "lines": []}
    ctrl.note_copied(ctrl.render()[1])                      # 2건 중 1건 복사
    lines = ctrl.leave_guard()["lines"]
    assert any("복사 진행 1/2" in line for line in lines)
    ctrl.dispatch("set_source", {"index": 0, "source": "사업명"})
    ctrl.dispatch("set_confirmed", {"index": 0, "value": True})
    lines = ctrl.leave_guard()["lines"]
    assert any("수신" in line and "저장하지 않은" in line for line in lines)


def test_all_copied_is_not_a_loss(tmp_path):
    """전건 복사는 잃을 진행이 없다 — 끝난 세션을 붙잡지 않는다."""
    ctrl, _, _ = _open(tmp_path)
    ctrl.dispatch("toggle_advance", {"value": True})
    ctrl.note_copied(ctrl.render()[1])
    ctrl.note_copied(ctrl.render()[1])
    assert ctrl.leave_guard()["armed"] is False


def test_close_clears_the_session(tmp_path):
    ctrl, _, _ = _open(tmp_path)
    ctrl.dispatch("close", {})
    assert ctrl.snapshot()["open"] is False and ctrl.can_copy() is False


def test_unknown_action_is_loud(tmp_path):
    ctrl, _, _ = _open(tmp_path)
    with pytest.raises(ValueError):
        ctrl.dispatch("없는액션", {})


# ---------------------------------------------- 복사 완료 = 최근 사용 (§19.4, 판정 I)
def test_first_copy_records_recent_use_once_per_session(tmp_path):
    """§19.4 — "한 레코드라도 복사 완료"가 최근 사용을 기록한다. 진입만으로는 아니다."""
    ctrl, reg, _ = _open(tmp_path)
    assert reg.load("발주요청_기안").last_run_at == ""      # 진입만으로는 기록하지 않는다
    ctrl.note_copied(ctrl.render()[1])
    first = reg.load("발주요청_기안").last_run_at
    assert first, "복사 완료가 최근 사용을 기록하지 않았습니다."
    # 세션당 1회 — 두 번째 복사는 같은 사실을 다시 쓰지 않는다(durable 쓰기 증식 금지).
    ctrl.dispatch("toggle_advance", {"value": True})
    ctrl.note_copied(ctrl.render()[1])
    assert reg.load("발주요청_기안").last_run_at == first


def test_copy_does_not_write_a_review_baseline(tmp_path):
    """TXT 는 검토 요구 축을 지지 않으므로 그 기준선을 찍지 않는다(판정 J 의 따름정리).

    짓지 않은 축에 「검토했다」를 기록하는 것은 하지 않은 검토를 기록하는 것이다 —
    조용한 누락보다 나쁘다.
    """
    ctrl, reg, _ = _open(tmp_path)
    ctrl.note_copied(ctrl.render()[1])
    assert reg.load("발주요청_기안").reviewed_rules == {}


def test_stamp_failure_is_reported_not_swallowed(tmp_path, monkeypatch):
    """복사는 이미 일어났다 — 스탬프 실패를 예외로 올려 완료 노트를 날리지도, 조용히
    넘기지도 않는다(confirm-or-alarm: 사유를 완료 노트에 병기)."""
    ctrl, reg, _ = _open(tmp_path)

    def boom(*a, **k):
        raise OSError("디스크에 쓸 수 없습니다")

    monkeypatch.setattr(reg, "stamp_last_run", boom)
    ctrl.note_copied(ctrl.render()[1])
    last = ctrl.snapshot()["card"]["last_copy"]
    assert "디스크" in last["stamp_error"]
    assert ctrl.snapshot()["copied_count"] == 1   # 복사 자체는 성사됐다


def test_the_two_media_share_the_field_but_not_the_predicate(tmp_path):
    """같은 `Job.last_run_at` 을 쓰되 **찍는 사건이 다르다**(§19.2 — 의미 있는 결과 행동).

    그 사실을 표면 문안이 갈라 말하는지는 `test_work_mode` 가 잰다. 여기서는 저장처가
    하나라는 것과, TXT 경로가 hwpx 의 완주 술어를 빌리지 않는다는 것만 못박는다.
    """
    from hwpxfiller.gui.work_mode import WORK_MODE_TEXT, last_use_label

    ctrl, reg, _ = _open(tmp_path)
    ctrl.note_copied(ctrl.render()[1])
    job = reg.load("발주요청_기안")
    assert last_use_label(WORK_MODE_TEXT, job.last_run_at).startswith("마지막 복사")
