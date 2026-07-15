"""diff 웹 컨트롤러(:class:`hwpxdiff.webapp.screen_diff.DiffController`) 헤드리스 계약.

브리지가 웹으로 미는 snapshot 이 뷰(diff.js)가 기대는 형태인지, 그리고 엔진(diff_files)의
결과를 왜곡 없이 실어 나르는지 못박는다(RC-17: 표면 간 렌더 동등성). 워커 스레드·세대 토큰·
최근 저장·에러 경로도 함께 가드한다. webview 비의존이라 창 없이 구동된다.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from hwpxdiff.diff import KIND_COLORS, KIND_LABELS, diff_files
from hwpxdiff.webapp.screen_diff import DiffController

CORPUS = Path(__file__).parent / "corpus" / "real"
OLD = str(CORPUS / "spec_revision_2025.hwpx")
NEW = str(CORPUS / "spec_revision_2026.hwpx")


def _controller(tmp_path: Path):
    """수집 sink + 임시 최근 저장(홈 오염 방지)로 컨트롤러 구성. (컨트롤러, pushes) 반환."""
    pushes: list = []
    ctrl = DiffController(lambda s, snap: pushes.append(snap), recent_path=tmp_path / "recent.json")
    return ctrl, pushes


def _wait_pushed(pushes, timeout=15.0):
    """마지막 *push* 가 종결 상태가 될 때까지 대기 — _status 는 push 직전에 바뀌므로
    push 목록(뷰가 실제로 받는 것)을 기준으로 본다(경합 방지)."""
    deadline = time.time() + timeout
    while (not pushes or pushes[-1]["status"] not in ("done", "error")) and time.time() < deadline:
        time.sleep(0.02)
    return pushes[-1]["status"] if pushes else None


# --------------------------------------------------------------- 스냅샷 계약
def test_snapshot_contract_matches_engine(tmp_path):
    """compare_sync 후 마지막 snapshot 이 diff_files 결과를 그대로 실어 나른다."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_old_path(OLD)
    ctrl.load_new_path(NEW)
    r = ctrl.compare_sync()
    assert r["ok"] is True and r["status"] == "done"

    expected = diff_files(OLD, NEW)
    snap = pushes[-1]
    assert snap["has_result"] is True and snap["status"] == "done"
    assert snap["old_label"] == "spec_revision_2025.hwpx"
    assert snap["new_label"] == "spec_revision_2026.hwpx"
    # 요약 카운트 = 엔진 요약(4종).
    for k in ("added", "removed", "changed", "renumber"):
        assert snap["summary"][k] == expected.summary.get(k, 0)
    assert snap["change_count"] == len(expected.changes)
    # 변경 그룹 == 엔진 change_groups(길이·seq 앵커).
    assert len(snap["groups"]) == len(expected.change_groups)
    assert snap["groups"][0]["seq"] == expected.change_groups[0].seqs[0]
    # 전문 rows 는 equal 을 포함해 change_count 보다 많다(뷰 맥락 보존).
    assert len(snap["rows"]) > snap["change_count"]
    # changed/renumber 행은 낱말 op 를 싣는다(인라인 강조 데이터).
    changed = [row for row in snap["rows"] if row["kind"] in ("changed", "renumber")]
    assert changed and all("ops" in row for row in changed)
    op = changed[0]["ops"][0]
    assert set(op) == {"op", "old", "new"}
    # 앵커: 변경 행 seq 는 element id 표적.
    assert any(row["seq"] is not None for row in snap["rows"])


def test_snapshot_carries_core_colors_labels(tmp_path):
    """RC-17: 색/라벨은 core(KIND_*) 단일 출처 값을 그대로 전달(하드코딩 금지)."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_old_path(OLD)
    ctrl.load_new_path(NEW)
    ctrl.compare_sync()
    snap = pushes[-1]
    assert snap["kind_colors"] == KIND_COLORS
    assert snap["kind_labels"] == KIND_LABELS


def test_no_changes_message_when_identical(tmp_path):
    """동일 판본: change_count 0 + 확정 문장(NO_CHANGES_MESSAGE) — 조용한 빈 화면 아님."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_old_path(OLD)
    ctrl.load_new_path(OLD)  # 같은 파일 ↔ 자기 자신
    ctrl.compare_sync()
    snap = pushes[-1]
    assert snap["has_result"] is True
    assert snap["change_count"] == 0
    assert snap["no_changes_message"]  # 비어있지 않은 카피


# --------------------------------------------------------------- 가드/에러
def test_compare_requires_both_paths(tmp_path):
    """구·신 미선택이면 시끄럽게 거부(confirm-or-alarm) — 워커 안 띄운다."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_old_path(OLD)
    r = ctrl.compare()  # 신판 없음
    assert r == {"ok": False, "error": "구판·신판을 모두 선택하세요."}


def test_compare_error_surfaces(tmp_path):
    """엔진 실패(존재하지 않는 파일)는 error 상태로 시끄럽게 표면화."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_old_path(str(CORPUS / "does_not_exist.hwpx"))
    ctrl.load_new_path(NEW)
    ctrl.compare_sync()
    snap = pushes[-1]
    assert snap["status"] == "error" and snap["error"]
    assert snap["has_result"] is False


def test_stale_generation_dropped(tmp_path):
    """세대 토큰: 낡은 워커 결과는 폐기된다(사용자가 재비교 시 stale 화면 방지)."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_old_path(OLD)
    ctrl.load_new_path(NEW)
    ctrl._gen = 5  # 현재 세대
    before = len(pushes)
    ctrl._run_compare(3)  # 낡은 세대로 직접 구동
    assert ctrl._result is None  # 결과 반영 안 됨
    assert len(pushes) == before  # push 도 없음


# --------------------------------------------------------------- 비동기 워커
def test_async_compare_pushes_running_then_done(tmp_path):
    """compare(): 즉시 running push 후 워커 완료 시 done push(#6 비동기 모델)."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_old_path(OLD)
    ctrl.load_new_path(NEW)
    r = ctrl.compare()
    assert r == {"ok": True, "status": "running"}
    assert pushes[-1]["status"] == "running"  # 즉시 스피너 상태
    assert _wait_pushed(pushes) == "done"
    assert pushes[-1]["status"] == "done" and pushes[-1]["has_result"]


# --------------------------------------------------------------- 최근 저장
def test_recent_persisted_and_reported(tmp_path):
    """성공한 비교 쌍이 최근 목록(JSON)에 남고 snapshot.recent 로 재노출된다."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_old_path(OLD)
    ctrl.load_new_path(NEW)
    ctrl.compare_sync()
    recent = pushes[-1]["recent"]
    assert recent and recent[0]["old_label"] == "spec_revision_2025.hwpx"
    assert (tmp_path / "recent.json").exists()

    # select_recent 로 쌍을 다시 겨눈다(순수 데이터 액션).
    ctrl2, pushes2 = _controller(tmp_path)  # 같은 저장 공유
    ctrl2.dispatch("select_recent", {"old": OLD, "new": NEW})
    assert ctrl2._old == OLD and ctrl2._new == NEW
    assert pushes2[-1]["can_compare"] is True


def test_unknown_action_rejected(tmp_path):
    """미지 액션은 조용히 무시하지 않고 시끄럽게 거부(P5 규약)."""
    ctrl, _ = _controller(tmp_path)
    with pytest.raises(ValueError):
        ctrl.dispatch("nope", {})
