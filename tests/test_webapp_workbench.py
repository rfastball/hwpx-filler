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
from hwpxfiller.webapp.action_registry import validate_dispatch
from hwpxfiller.webapp.draft_session import TargetFontSetting
from hwpxfiller.webapp.screen_workbench import WorkbenchController


def _send(ctrl: WorkbenchController, action: str, payload: "dict | None" = None):
    """**실 브리지와 같은 입구**로 보낸다 — 스키마 검증을 먼저 지나고 dispatch 한다.

    1R 의 검출 실패가 여기서 났다: 테스트가 `ctrl.dispatch(...)` 를 직접 불러
    :func:`validate_dispatch` **아래**로 진입하는 바람에, 실 브리지에서는 스키마가 거절하는
    페이로드로 저장이 통과했다(미등록 키 `confirm_drift`). 판정과 기대가 같은 층에서 만나면
    그 층이 통째로 틀려도 둘이 나란히 틀린다 — 그래서 이 스위트의 모든 발신은 이 관문을 쓴다.
    """
    checked = validate_dispatch(ctrl.name, action, payload or {})
    return ctrl.dispatch(action, checked)


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


def _save(ctrl: WorkbenchController) -> dict:
    """확인 왕복 1회를 그대로 밟는다 — 문안을 받아 **그대로** 되돌려 보낸다(실 클라이언트 판)."""
    first = _send(ctrl, "save_rules", {})
    if not first.get("needs_confirm"):
        return first
    return _send(ctrl, "save_rules",
                 {"confirm": True, "confirmed_text": first["confirm_text"]})


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
        _send(ctrl, "step", {"delta": 1})


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
    _send(ctrl, "set_source", {"name": "수신", "col": "사업명"})
    _send(ctrl, "set_confirmed", {"name": "수신", "value": True})
    d = ctrl.snapshot()["dirty"]
    assert d["count"] == 1 and d["fields"][0]["name"] == "수신"
    # 디스크는 아직 그대로다 — 미저장이라는 말이 참이어야 한다.
    assert reg.load("발주요청_기안").mapping.mappings[0].source == "부서"


def test_unconfirmed_edits_block_saving_but_still_count_as_losable(tmp_path):
    """확정하지 않은 편집은 저장을 막되 **가드에는 잡힌다** — 버려지면 사라지기 때문이다."""
    ctrl, _, _ = _open(tmp_path)
    _send(ctrl, "set_map_value", {"name": "수신", "text": "직접 쓴 값"})
    snap = ctrl.snapshot()
    assert snap["save_block"] and snap["can_save"] is False
    assert snap["dirty"]["pending"] is True
    assert any("확정하지 않은" in line for line in snap["guard"]["lines"])


# ------------------------------------------------------------------ 저장 왕복
def test_save_lists_every_dirty_field_before_it_commits(tmp_path):
    """§11 — 영구 저장 확인에는 **모든 dirty 필드를 나열**한다."""
    ctrl, _, _ = _open(tmp_path)
    _send(ctrl, "set_source", {"name": "수신", "col": "사업명"})
    _send(ctrl, "set_confirmed", {"name": "수신", "value": True})
    first = _send(ctrl, "save_rules", {})
    assert first["needs_confirm"] is True and first["ok"] is False
    # §11 — 확인 문안이 dirty 필드를 **전부** 나열한다. 문안 자체가 확인의 정체이므로
    # 불리언이 아니라 이 문자열이 되돌아와야 저장이 성사된다.
    assert "수신" in first["confirm_text"]
    assert "이미 복사한 항목은 다시 확인이 필요해집니다." in first["confirm_text"]
    # 문안이 다르면(= 사용자가 확인한 상황이 아니면) 성사되지 않는다.
    stale = _send(ctrl, "save_rules", {"confirm": True, "confirmed_text": "딴 문안"})
    assert stale["needs_confirm"] is True and stale["ok"] is False


def test_save_bumps_the_binding_revision_and_keeps_the_work_point(tmp_path):
    """저장 뒤 재검증하고 **같은 작업점**으로 돌아온다(§11) — 판본은 저장이 정산한다."""
    ctrl, reg, _ = _open(tmp_path)
    _send(ctrl, "step", {"delta": 1})
    before_point = ctrl.queue.current
    before_rev = reg.load("발주요청_기안").binding_revision
    _send(ctrl, "set_source", {"name": "수신", "col": "사업명"})
    _send(ctrl, "set_confirmed", {"name": "수신", "value": True})
    res = _save(ctrl)
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
    _send(ctrl, "set_source", {"name": "수신", "col": "사업명"})
    _send(ctrl, "set_confirmed", {"name": "수신", "value": True})
    _save(ctrl)
    assert ctrl.snapshot()["card"]["review_state"] == "recheck"
    assert ctrl.snapshot()["copied_count"] == 1   # 복사 이력은 그대로
    # 지금 규칙으로 다시 복사하면 재확인이 해소된다.
    ctrl.note_copied(ctrl.render()[1])
    assert ctrl.snapshot()["card"]["review_state"] == "copied"


def test_save_preserves_fields_this_screen_does_not_edit(tmp_path):
    """잠금 안에서 디스크를 다시 읽고 **매핑만** 얹는다 — 그룹·이력은 최신값을 승계한다."""
    ctrl, reg, _ = _open(tmp_path)
    _send(ctrl, "set_source", {"name": "수신", "col": "사업명"})
    _send(ctrl, "set_confirmed", {"name": "수신", "value": True})
    # 세션이 열려 있는 사이 다른 표면이 그룹·완주 스탬프를 바꾼다.
    reg.mutate("발주요청_기안", lambda j: setattr(j, "group", "조달"))
    reg.stamp_last_run("발주요청_기안", "2026-07-28T10:00:00")
    res = _save(ctrl)
    assert res["ok"]
    saved = reg.load("발주요청_기안")
    assert saved.group == "조달" and saved.last_run_at == "2026-07-28T10:00:00"
    assert saved.mapping.mappings[0].source == "사업명"


def test_save_refuses_silently_overwriting_an_externally_changed_work(tmp_path):
    """열어 둔 사이 규칙이 갈렸으면 조용히 덮지 않고 확인을 **다시** 받는다."""
    ctrl, reg, _ = _open(tmp_path)
    _send(ctrl, "set_source", {"name": "수신", "col": "사업명"})
    _send(ctrl, "set_confirmed", {"name": "수신", "value": True})
    before_text = _send(ctrl, "save_rules", {})["confirm_text"]   # 드리프트 **전** 문안
    reg.mutate(
        "발주요청_기안",
        lambda j: setattr(j, "mapping", MappingProfile(mappings=[
            FieldMapping(template_field="수신", source="다른열"),
            FieldMapping(template_field="건명", source="사업명"),
        ])),
    )
    # 사용자가 **드리프트 전** 문안으로 확인해 두었다면 그 확인은 이 상황의 것이 아니다.
    blocked = _send(ctrl, "save_rules", {"confirm": True, "confirmed_text": before_text})
    assert blocked["needs_confirm"] is True and blocked["ok"] is False
    assert "다른 곳에서 바뀌었습니다" in blocked["confirm_text"]
    assert reg.load("발주요청_기안").mapping.mappings[0].source == "다른열"  # 안 덮었다
    # 새 문안(외부 변경 버전을 못박은)으로 다시 확인해야 성사된다.
    ok = _send(ctrl, "save_rules",
               {"confirm": True, "confirmed_text": blocked["confirm_text"]})
    assert ok["ok"] and reg.load("발주요청_기안").mapping.mappings[0].source == "사업명"


# ------------------------------------------------------------------ 복사·전진
def test_copy_keeps_the_work_point_unless_advance_is_on(tmp_path):
    """복사해도 작업점은 그 카드에 머문다(조용한 이동 금지) — 전진은 opt-in."""
    ctrl, _, _ = _open(tmp_path)
    start = ctrl.queue.current
    ctrl.note_copied(ctrl.render()[1])
    assert ctrl.queue.current == start
    _send(ctrl, "toggle_advance", {"value": True})
    ctrl.note_copied(ctrl.render()[1])
    assert ctrl.queue.current != start


def test_card_and_clipboard_take_the_same_path(tmp_path):
    """카드 세그먼트 이어붙임 = 클립보드 텍스트(결정 17 — 링1 공유 통로)."""
    ctrl, _, _ = _open(tmp_path)
    text, _ = ctrl.render()
    assert text == "".join(s["text"] for s in ctrl.snapshot()["card"]["segments"])
    _send(ctrl, "set_fullwidth", {"value": True})
    text2, _ = ctrl.render()
    assert text2 == "".join(s["text"] for s in ctrl.snapshot()["card"]["segments"])


def test_raw_view_shows_tokens_without_filling_them(tmp_path):
    """원문 보기(§11) — 토큰을 채우지 않는다. 미지 보기 값은 fail-closed."""
    ctrl, _, _ = _open(tmp_path)
    _send(ctrl, "set_view", {"view": "raw"})
    raw = "".join(s["text"] for s in ctrl.snapshot()["card"]["segments"])
    assert "{{수신}}" in raw and "회계과" not in raw
    with pytest.raises(ValueError):
        _send(ctrl, "set_view", {"view": "엉뚱"})


def test_copy_gate_excludes_declared_blanks(tmp_path):
    """확정-비움은 복사 전 확인에서 빠진다(결정 12) — 렌더에는 그대로 보인다."""
    ctrl, _, _ = _ctrl(tmp_path)
    reg = JobRegistry(tmp_path / "jobs")
    job = _job(tmp_path)
    reg.save(job)
    ctrl.registry = reg
    ctrl.open(reg.load(job.name), [(0, {"부서": "총무과", "사업명": ""})])
    assert _send(ctrl, "copy_precheck", {})["empty_fields"] == ["건명"]
    # 결속을 **둔 채** 확정하는 것은 선언이 아니다 — 그 빈 값은 그 행의 사실이라 남는다.
    _send(ctrl, "set_confirmed", {"name": "건명", "value": True})
    assert _send(ctrl, "copy_precheck", {})["empty_fields"] == ["건명"]
    # 결속을 풀고 확정해야 「비운다」 선언이 된다(결정 12).
    _send(ctrl, "set_source", {"name": "건명", "col": ""})
    _send(ctrl, "set_confirmed", {"name": "건명", "value": True})
    idx = [r["name"] for r in ctrl.snapshot()["rows"]].index("건명")
    assert ctrl.snapshot()["rows"][idx]["blank_declared"] is True
    assert _send(ctrl, "copy_precheck", {})["empty_fields"] == []


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
    _send(ctrl, "set_source", {"name": "수신", "col": "사업명"})
    _send(ctrl, "set_confirmed", {"name": "수신", "value": True})
    lines = ctrl.leave_guard()["lines"]
    assert any("수신" in line and "저장하지 않은" in line for line in lines)


def test_all_copied_is_not_a_loss(tmp_path):
    """전건 복사는 잃을 진행이 없다 — 끝난 세션을 붙잡지 않는다."""
    ctrl, _, _ = _open(tmp_path)
    _send(ctrl, "toggle_advance", {"value": True})
    ctrl.note_copied(ctrl.render()[1])
    ctrl.note_copied(ctrl.render()[1])
    assert ctrl.leave_guard()["armed"] is False


def test_close_clears_the_session(tmp_path):
    ctrl, _, _ = _open(tmp_path)
    _send(ctrl, "close", {})
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
    _send(ctrl, "toggle_advance", {"value": True})
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


def test_work_point_number_follows_the_frozen_order_not_the_queue(tmp_path):
    """작업점 「N / M」은 **고정 사본의 자리**다(§13-13) — 복사해도 다시 매겨지지 않는다.

    실앱 한 바퀴가 잡은 결함의 회귀다: `TxtQueueModel.position_of` 는 *미처리 큐* 안의
    1-기반 순번이라 ①표면이 +1 하면 진입부터 「2 / 3」으로 어긋나고 ②복사할 때마다 번호가
    다시 매겨지며 복사한 카드는 None 이 된다. 화면 부제가 「선택 당시 표시순서로 고정된
    항목」이라고 말하므로 사람이 읽는 숫자도 그 고정 순서를 따라야 참이다.
    """
    ctrl, reg, _ = _ctrl(tmp_path)
    job = _job(tmp_path)
    reg.save(job)
    ctrl.open(reg.load(job.name), [
        (2, {"부서": "가", "사업명": "ㄱ"}),
        (1, {"부서": "나", "사업명": "ㄴ"}),
        (0, {"부서": "다", "사업명": "ㄷ"}),
    ])
    assert ctrl.snapshot()["card"]["position"] == 0        # 진입 = 첫 항목
    _send(ctrl, "step", {"delta": 1})
    assert ctrl.snapshot()["card"]["position"] == 1
    # 복사해도 그 카드의 자리는 그대로다(큐 후미 이동은 순회 순서의 일이지 번호의 일이 아니다).
    ctrl.note_copied(ctrl.render()[1])
    assert ctrl.snapshot()["card"]["position"] == 1
    assert ctrl.snapshot()["card"]["review_state"] == "copied"
    # 첫 항목으로 되돌아가도 자리는 고정 순서 그대로다.
    _send(ctrl, "set_current", {"index": 0})
    assert ctrl.snapshot()["card"]["position"] == 0


# ------------------------------------------------ 2R — 파생 vs 래치 (P1·P2 가족)
def test_navigation_bounds_follow_the_queue_not_the_frozen_ordinal(tmp_path):
    """이동 경계는 **큐 순서**의 질문이다(2R P1) — 표시 서수로 답하면 갇힌다.

    복사하면 그 카드가 큐 후미로 간다(결정 16). 고정 자리는 그대로인데 순회상의 앞뒤는
    달라지므로, 한 값으로 두 질문에 답하면 그중 하나는 반드시 틀린다: 실제로 복사 직후
    「다음」은 눌리지만 아무 일도 안 했고 「이전」은 비활성이라 그 카드에 갇혔다.
    """
    ctrl, reg, _ = _ctrl(tmp_path)
    job = _job(tmp_path)
    reg.save(job)
    ctrl.open(reg.load(job.name), [
        (0, {"부서": "가", "사업명": "ㄱ"}),
        (1, {"부서": "나", "사업명": "ㄴ"}),
        (2, {"부서": "다", "사업명": "ㄷ"}),
    ])
    card = ctrl.snapshot()["card"]
    assert (card["can_prev"], card["can_next"]) == (False, True)   # 큐 머리
    ctrl.note_copied(ctrl.render()[1])                             # 복사 = 후미로 이동
    card = ctrl.snapshot()["card"]
    assert card["position"] == 0                                   # 표시 자리는 고정
    # 순회상으로는 **후미**다 — 다음은 없고 이전은 있다. 종전 판정과 정확히 반대였다.
    assert (card["can_prev"], card["can_next"]) == (True, False)
    ctrl.dispatch("step", {"delta": -1})
    assert ctrl.queue.current is not None and ctrl.queue.current != 0  # 실제로 빠져나온다


def test_editing_a_mapping_marks_copied_records_for_recheck_at_once(tmp_path):
    """복사 상태는 **파생**이다(2R P2) — 카드가 바뀌는 순간 배지도 바뀐다.

    종전에는 저장 **사건**이 재확인 집합을 칠했다. 그러면 「복사 → 편집(카드 즉시 변함)
    → 아직 저장 안 함」 구간에서 배지가 「복사 완료」로 남아, 사용자가 다시 복사해야 할
    행을 건너뛴다 — 화면이 보여 주는 문장과 배지가 서로 다른 말을 하는 창이다.
    """
    ctrl, _, _ = _open(tmp_path)
    ctrl.note_copied(ctrl.render()[1])
    assert ctrl.snapshot()["card"]["review_state"] == "copied"
    _send(ctrl, "set_map_value", {"name": "수신", "text": "손으로 바꾼 값"})
    assert ctrl.snapshot()["card"]["review_state"] == "recheck"     # 저장 **전에** 이미
    # 지금 규칙으로 다시 복사하면 해소된다(별도 무효화 코드 없이 파생이 답한다).
    ctrl.note_copied(ctrl.render()[1])
    assert ctrl.snapshot()["card"]["review_state"] == "copied"


def test_toggling_fullwidth_also_invalidates_a_copied_card(tmp_path):
    """전각 치환도 **복사되는 문자열**을 바꾼다 — 규칙 지문이 그 사실을 담아야 참이다."""
    ctrl, _, _ = _open(tmp_path)
    ctrl.note_copied(ctrl.render()[1])
    _send(ctrl, "set_fullwidth", {"value": True})
    assert ctrl.snapshot()["card"]["review_state"] == "recheck"


def test_saving_alone_does_not_repaint_the_review_state(tmp_path):
    """저장은 규칙을 **영속**시킬 뿐 바꾸지 않는다 — 같은 상태에 판정 주체를 둘로 두지 않는다."""
    ctrl, _, _ = _open(tmp_path)
    _send(ctrl, "set_source", {"name": "수신", "col": "사업명"})
    _send(ctrl, "set_confirmed", {"name": "수신", "value": True})
    ctrl.note_copied(ctrl.render()[1])          # 편집 **뒤에** 복사 = 지금 규칙의 산출물
    assert ctrl.snapshot()["card"]["review_state"] == "copied"
    _save(ctrl)
    assert ctrl.snapshot()["card"]["review_state"] == "copied"   # 저장이 뒤집지 않는다


# ------------------------------------------------ 3R — 확인 대상 = 복사 대상 (P1)
def test_copy_is_bound_to_the_card_that_was_prechecked(tmp_path):
    """사전확인과 실제 쓰기를 **토큰으로 묶는다**(3R P1) — 잠금이 아니라 결속으로.

    복사를 빠르게 두 번 누르면 둘 다 **같은 카드**로 사전확인을 통과하는데, 첫 복사가
    (자동 전진으로) 작업점을 옮기면 두 번째는 **확인하지 않은 카드**를 클립보드에 쓴다.
    이동도 같은 틈을 만든다. 토큰이 그 카드의 정체(작업점 + 지금 규칙)라 그사이 무엇이든
    바뀌면 대조에서 걸린다 — `confirmed_text` 와 같은 규율이다.
    """
    ctrl, _, _ = _open(tmp_path)
    stale_token = _send(ctrl, "copy_precheck", {})["token"]
    assert stale_token and stale_token == ctrl.copy_token()

    _send(ctrl, "step", {"delta": 1})                 # 확인 뒤 작업점이 움직였다
    assert ctrl.copy_token() != stale_token

    # 규칙이 바뀌어도 같은 카드가 아니다 — 보여 준 문장이 달라졌기 때문이다.
    fresh = _send(ctrl, "copy_precheck", {})["token"]
    _send(ctrl, "set_map_value", {"name": "수신", "text": "손으로 바꾼 값"})
    assert ctrl.copy_token() != fresh


def test_stale_copy_writes_nothing_and_says_so(tmp_path):
    """어긋난 토큰은 **조용한 무동작이 아니라** stale 재진술 — 큐도 스탬프도 움직이지 않는다."""
    from hwpxfiller.webapp.app import WebFrontend

    ctrl, reg, _ = _open(tmp_path)
    frontend = object.__new__(WebFrontend)
    frontend.controllers = {"workbench": ctrl}

    res = frontend.copy_clipboard("workbench", "그사이-바뀐-토큰")
    assert res["copied"] is False and res["stale"] is True
    assert ctrl.snapshot()["copied_count"] == 0        # 큐 불변
    assert reg.load("발주요청_기안").last_run_at == ""  # 최근 사용도 안 찍힌다


# ------------------------------------------- 4R — 백엔드 seam 에 소비자가 있는가 (P2)
def test_copy_note_carries_the_stamp_failure(tmp_path, monkeypatch):
    """복사는 됐는데 **최근 사용 기록이 실패**했으면 완료 노트가 그 사실을 나른다(4R P2).

    백엔드가 일부러 남긴 사유를 표면이 안 읽으면 무조건 성공 문안이 뜨고 이력은 조용히
    빠진다 — 조용한 누락은 이 저장소에서 가장 비싼 부류다. 여기서는 **스냅샷에 실렸는지**를
    잰다(문안 조립은 표면 몫이고 DOM 계약이 그 소비를 따로 센다).
    """
    ctrl, reg, _ = _open(tmp_path)

    def boom(*a, **k):
        raise OSError("디스크에 쓸 수 없습니다")

    monkeypatch.setattr(reg, "stamp_last_run", boom)
    ctrl.note_copied(ctrl.render()[1])
    assert "디스크" in ctrl.snapshot()["card"]["last_copy"]["stamp_error"]


def test_queue_index_map_lets_the_user_jump_to_a_known_row(tmp_path):
    """순차 이동만으로는 아는 행에 못 간다 — 큐 색인이 그 자리를 연다(4R P2).

    자리 라벨은 **원본 행 번호**다: 고정 사본의 정체를 사람이 아는 이름으로 말해야
    「그 행으로 가겠다」가 성립한다.
    """
    ctrl, _, _ = _open(tmp_path)
    imap = ctrl.snapshot()["card"]["index_map"]
    assert [d["row"] for d in imap] == [3, 1]          # 표시순 그대로, 원본 행 번호
    assert imap[0]["state"] == "current"
    _send(ctrl, "set_current", {"index": imap[1]["index"]})
    assert ctrl.snapshot()["card"]["source_row"] == 1
    # 복사·재확인 상태도 색인이 함께 말한다(점 하나가 두 사실을 나른다).
    ctrl.note_copied(ctrl.render()[1])
    _send(ctrl, "set_map_value", {"name": "수신", "text": "고침"})
    marked = [d for d in ctrl.snapshot()["card"]["index_map"] if d["recheck"]]
    assert len(marked) == 1 and marked[0]["row"] == 1


# ---------------------------------- 5R — 정체를 묶어도 시간을 안 묶으면 창이 남는다
def test_overlapping_copies_cannot_write_an_unprechecked_card(tmp_path):
    """복사 거래는 **원자**다 — 대조·렌더·쓰기·전진이 한 임계구역 안이다(5R P1).

    3R 은 확인 대상과 복사 대상을 토큰으로 **묶었지만** 그 사이를 잠그지 않았다: 브리지가
    네 걸음을 밟는 동안 두 호출이 겹치면 둘 다 같은 토큰으로 통과하고, 앞선 호출이 자동
    전진으로 작업점을 옮긴 뒤 뒤선 호출이 *새* 카드를 복사한다. 여기서는 그 시나리오를
    **쓰기 콜백 안에서 끼어들어** 재현한다 — 잠금이 없으면 두 번째가 통과한다.
    """
    import threading

    ctrl, _, _ = _open(tmp_path)
    _send(ctrl, "toggle_advance", {"value": True})
    token = _send(ctrl, "copy_precheck", {})["token"]
    written: "list[str]" = []
    second: "list[dict]" = []
    inside, release = threading.Event(), threading.Event()

    def slow_write(text: str) -> None:
        """첫 쓰기가 **진행 중**인 지점을 붙든다 — 겹침이 실제로 겹치게."""
        written.append(text)
        inside.set()
        release.wait(2.0)

    def overlapping() -> None:
        inside.wait(2.0)                     # 첫 호출이 쓰기 한복판일 때 들어간다
        second.append(ctrl.copy_to(token, written.append))
        release.set()

    # 브리지 호출은 스레드별이라 복사가 **실제로** 겹친다 — 그 조건을 그대로 만든다.
    worker = threading.Thread(target=overlapping)
    worker.start()
    first = ctrl.copy_to(token, slow_write)
    worker.join(3.0)
    assert first["copied"] is True
    assert second and second[0]["copied"] is False, "겹친 복사가 통과했습니다(원자성 없음)"
    assert len(written) == 1, f"확인하지 않은 카드가 클립보드로 나갔습니다: {written}"


def test_a_stale_token_never_reaches_the_clipboard(tmp_path):
    """어긋난 토큰은 쓰기 콜백을 **부르지 않는다** — 큐도 스탬프도 움직이지 않는다."""
    ctrl, reg, _ = _open(tmp_path)
    written: "list[str]" = []
    res = ctrl.copy_to("그사이-바뀐-토큰", written.append)
    assert res["copied"] is False and res["stale"] is True
    assert written == [] and ctrl.snapshot()["copied_count"] == 0
    assert reg.load("발주요청_기안").last_run_at == ""


def test_declaring_a_blank_changes_the_copied_text_and_the_badge(tmp_path):
    """확정은 **복사되는 문자열의 축**이기도 하다(5R P2).

    무결속·미확정 행은 `live_profile` 에서 빠져 토큰이 `{{이름}}` 그대로 복사되고, 확정하면
    확정-비움이 되어 빈 문자열이 된다. 2R 에서 "확정을 켜도 문장은 그대로"라고 단정한 것이
    틀렸다 — 계약(`live_profile` 문서)이 반대로 적고 있었다.
    """
    ctrl, _, _ = _open(tmp_path)
    _send(ctrl, "set_source", {"name": "건명", "col": ""})
    _send(ctrl, "set_confirmed", {"name": "건명", "value": False})
    before, _ = ctrl.render()
    assert "{{건명}}" in before                      # 미확정 = 토큰이 그대로 나간다
    ctrl.note_copied(ctrl.render()[1])
    assert ctrl.snapshot()["card"]["review_state"] == "copied"
    _send(ctrl, "set_confirmed", {"name": "건명", "value": True})
    after, _ = ctrl.render()
    assert "{{건명}}" not in after                   # 확정-비움 = 빈 문자열
    assert ctrl.snapshot()["card"]["review_state"] == "recheck"


def test_leave_guard_counts_records_waiting_for_re_copy(tmp_path):
    """**다시 확인 대기도 미완이다**(5R P2) — 전건 복사 뒤 규칙을 고쳐 저장한 세션.

    복사 진행도(전건이라) 미저장 변경도(저장했으므로) 없지만, 그 문서들은 지금 규칙의
    산출물이 아니다. 그 사실이 세션과 함께 조용히 사라지면 사용자는 낡은 문서를 붙여넣은
    채 끝난다.
    """
    ctrl, _, _ = _open(tmp_path)
    _send(ctrl, "toggle_advance", {"value": True})
    ctrl.note_copied(ctrl.render()[1])
    ctrl.note_copied(ctrl.render()[1])
    assert ctrl.leave_guard()["armed"] is False        # 전건 복사 = 잃을 진행 없음
    _send(ctrl, "set_source", {"name": "수신", "col": "사업명"})
    _send(ctrl, "set_confirmed", {"name": "수신", "value": True})
    _save(ctrl)
    guard = ctrl.leave_guard()
    assert guard["armed"] is True
    assert any("다시 확인" in line and "2건" in line for line in guard["lines"]), guard
