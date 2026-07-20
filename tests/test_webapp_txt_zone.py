"""txt 데이터 존(전-선언 큐 선택) 컨트롤러 가드 — 블록 3·4, 슬라이스 6 PR-2b(헤드리스).

TxtController 가 :class:`~hwpxfiller.webapp.data_zone.DataZoneMixin`(작업 화면과 공유)을
소비해 행 선택·필터 디스패치와 스냅샷(``filter``/``table``)을 얻고, 큐 상태는 링1
:class:`~hwpxfiller.gui.txt_queue.TxtQueueModel` 이 소유하는지(재구현 금지)를 창 없이
확인한다. 큐 자체 회귀는 ``test_txt_queue``, 필터 판정은 ``test_filter_state`` 소관 —
여기는 **결선**(리셋 경로·reconcile·스냅샷 계약·직전 필터 슬롯 수명)만 본다.
표면 렌더 되읽기는 실앱 게이트(``test_web_selftest_gate``)의 txt 존 프로브 몫.
"""
from __future__ import annotations

from pathlib import Path

from hwpxfiller.core.text_registry import TextTemplateRegistry
from hwpxfiller.webapp.screens import TxtController


def _controller(tmp_path: Path) -> "tuple[TxtController, list]":
    (tmp_path / "샘플기안.txt").write_text(
        "제목: {{공고명}}\n금액: {{추정가격}}", encoding="utf-8"
    )
    pushes: list = []
    ctrl = TxtController(TextTemplateRegistry(tmp_path), lambda s, snap: pushes.append((s, snap)))
    return ctrl, pushes


def _csv(tmp_path: Path, name: str = "d.csv") -> str:
    p = tmp_path / name
    p.write_text(
        "공고명,추정가격\n전산장비 구매,1000\n비품 구매,2000\n용역 계약,3000\n",
        encoding="utf-8",
    )
    return str(p)


# ------------------------------------------------------------------ 스냅샷 계약

def test_zone_empty_before_data(tmp_path):
    """데이터 미겨눔 = 빈 골격(datazone.js 가 분기 없이 그리는 계약) — 없는 걸 있는 척 안 함."""
    ctrl, _ = _controller(tmp_path)
    snap = ctrl.snapshot()
    assert snap["has_data"] is False
    assert snap["selected_count"] == 0
    assert snap["filter"]["active"] is False and snap["filter"]["columns"] == []
    assert snap["table"] == {
        "columns": [], "rows": [], "visible_count": 0, "hidden_selected": [],
    }


def test_load_defaults_to_all_selected_queue(tmp_path):
    """데이터 겨눔 = 전체 선택(작업 화면 문법 대칭) + 큐 표지(대기 순번·작업점=첫 미처리).

    선택 = 복사용 렌더링 큐의 전-선언(결정 16) — 선두 「큐」 열 소재(qpos/copied/current)가
    링1 큐 모델의 사영으로 스냅샷에 실린다.
    """
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    snap = pushes[-1][1]
    assert snap["has_data"] is True
    assert snap["record_count"] == 3 and snap["selected_count"] == 3
    rows = snap["table"]["rows"]
    assert [r["index"] for r in rows] == [0, 1, 2]
    # qpos = 미처리 큐 순번(링1 진실 — 표면은 큐 순서로 그리는 상태 색인(PR-3)에서 소비).
    assert [r["qpos"] for r in rows] == [1, 2, 3]
    assert [r["copied"] for r in rows] == [False, False, False]
    assert [r["current"] for r in rows] == [True, False, False]  # 작업점 = 첫 미처리
    assert snap["table"]["columns"] == ["공고명", "추정가격"]


def test_queue_copied_marker_projected(tmp_path):
    """처리 후미(복사됨) 표지 — 링1 큐 상태가 그대로 사영된다(복사 동사 표면은 다음 PR).

    복사분은 미처리 큐에서 빠지고(qpos=None) 「복사됨」 표지로, 작업점은 머문다(결정 16
    조용한 작업점 이동 금지 — 큐 모델 계약의 스냅샷 판).
    """
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    ctrl.queue.copy(0)
    ctrl.dispatch("step", {"delta": 0})  # 재푸시 유도(무해 액션)
    rows = pushes[-1][1]["table"]["rows"]
    assert rows[0]["copied"] is True and rows[0]["qpos"] is None
    assert rows[0]["current"] is True  # 복사해도 작업점은 그 카드에 머문다
    assert rows[1]["qpos"] == 1  # 미처리 큐 선두로 승격


# ------------------------------------------------------------------ 선택·reconcile

def test_toggle_reconciles_queue(tmp_path):
    """행 해제 = 큐 완전 이탈(복사 이력 포함), 재선택 = 새 미처리 후미(copied ⊆ selected).

    dispatch 공통 후처리 reconcile 이 큐를 재봉합한다 — 블록 4 결정 26 자가복구 문법의
    큐 판. 작업점도 선택 지형을 따라 정규화된다.
    """
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    ctrl.queue.copy(0)
    ctrl.dispatch("toggle_record", {"index": 0, "value": False})
    rows = pushes[-1][1]["table"]["rows"]
    assert rows[0]["selected"] is False and rows[0]["copied"] is False
    assert rows[0]["qpos"] is None
    assert rows[1]["current"] is True  # 작업점 정규화 = 남은 첫 미처리
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})
    rows = pushes[-1][1]["table"]["rows"]
    assert rows[0]["copied"] is False  # 재선택 = 새 미처리(복사 이력 소멸)
    assert rows[0]["qpos"] == 3        # 미처리 후미 편입


def test_select_range_and_set_none(tmp_path):
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    ctrl.dispatch("set_none", {})
    assert pushes[-1][1]["selected_count"] == 0
    ctrl.dispatch("select_range", {"indices": [0, 1], "value": True})
    snap = pushes[-1][1]
    assert snap["selected_count"] == 2
    assert [r["qpos"] for r in snap["table"]["rows"]] == [1, 2, None]


# ------------------------------------------------------------------ 필터 결선

def test_filter_search_segments_and_strip(tmp_path):
    """전열 검색 — 가시 행 축소 + 하이라이트 세그먼트(Python 절단) + 필터 밖 선택 스트립.

    선택은 필터를 관통한다(결정 3): 매치 밖 선택 행은 ``hidden_selected`` 로 상시 진술되고,
    스트립 소재도 같은 선두 열 dict(큐 표지 포함)를 공유한다.
    """
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    ctrl.dispatch("filter_search", {"text": "전산"})
    snap = pushes[-1][1]
    t = snap["table"]
    assert t["visible_count"] == 1 and t["rows"][0]["index"] == 0
    assert ["전산", True] in [list(seg) for seg in t["rows"][0]["cells"][0]]
    hidden = t["hidden_selected"]
    assert [r["index"] for r in hidden] == [1, 2]  # 선택 관통 — 원본 순서
    assert hidden[0]["qpos"] == 2  # 스트립 소재도 큐 표지 공유
    assert snap["filter"]["active"] is True
    assert "전산" in snap["filter"]["definition"]


def test_set_all_is_additive_over_matches(tmp_path):
    """필터 활성 「전체 선택」 = 매치 가산(결정 4·26) — 전멸 필터 무동작은 added=0 재진술."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("filter_search", {"text": "전산"})
    res = ctrl.dispatch("set_all", {})
    assert res == {"added": 1}
    assert pushes[-1][1]["selected_count"] == 1
    res = ctrl.dispatch("set_all", {})  # 이미 전부 선택 = 무동작 정직 재진술
    assert res == {"added": 0}


def test_filter_panel_is_query_without_push(tmp_path):
    """filter_panel 은 무변이 질의 — push 생략(작업 화면 dispatch 규약 승계)."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    before = len(pushes)
    res = ctrl.dispatch("filter_panel", {"column": "공고명"})
    assert res["column"] == "공고명" and "전산장비 구매" in res["options"]
    assert len(pushes) == before, "무변이 질의가 push 를 유발했습니다(is_query 규약 위반)"


# ------------------------------------------------------------------ 리셋·직전 필터 슬롯

def test_data_reload_resets_zone(tmp_path):
    """데이터 교체 = 전체 선택·새 큐·필터 재생성(결정 24) — 이전 세션 선언의 오발 차단."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    ctrl.dispatch("filter_search", {"text": "전산"})
    ctrl.dispatch("toggle_record", {"index": 1, "value": False})
    other = tmp_path / "e.csv"
    other.write_text("공고명,추정가격\n새 공고,10\n", encoding="utf-8")
    ctrl.load_data_path(str(other))
    snap = pushes[-1][1]
    assert snap["selected_count"] == snap["record_count"] == 1
    assert snap["filter"]["active"] is False
    assert snap["table"]["rows"][0]["current"] is True and snap["table"]["rows"][0]["qpos"] == 1


def test_reapply_slot_survives_source_roundtrip(tmp_path):
    """직전 필터 슬롯(결정 28) — 소스 일치 게이트: 다른 소스에선 숨고, 같은 소스로
    돌아오면 제공·복원된다(정의만 — 선택 불변)."""
    ctrl, pushes = _controller(tmp_path)
    src_a = _csv(tmp_path)
    ctrl.load_data_path(src_a)
    ctrl.dispatch("filter_search", {"text": "전산"})
    other = tmp_path / "e.csv"
    other.write_text("공고명,추정가격\n새 공고,10\n", encoding="utf-8")
    ctrl.load_data_path(str(other))  # 세션 죽음 → 슬롯 스태시
    assert pushes[-1][1]["filter"]["reapply_available"] is False  # 소스 불일치 = 숨김
    ctrl.load_data_path(src_a)
    assert pushes[-1][1]["filter"]["reapply_available"] is True
    res = ctrl.dispatch("filter_reapply", {})
    assert res["ok"] is True
    snap = pushes[-1][1]
    assert snap["filter"]["search"] == "전산" and snap["table"]["visible_count"] == 1
    assert snap["selected_count"] == 3  # 정의(보기)만 복원 — 선택 불변(2클릭 분리)


def test_snapshot_exposes_source_identity_key(tmp_path):
    """``data_key`` = 소스 **정체**(정규화 경로+시트) — 표시 라벨과 달리 동명 파일을 가른다(리뷰).

    표면의 세션 리셋(Shift 앵커·디바운스·존 고지)이 이 키에 겨눈다: basename 뿐인 라벨로는
    ``folder1/명단.xlsx``→``folder2/명단.xlsx`` 전환이 같은 세션으로 보여 stale 앵커가 살아남는다.
    """
    ctrl, pushes = _controller(tmp_path)
    a_dir, b_dir = tmp_path / "폴더1", tmp_path / "폴더2"
    a_dir.mkdir()
    b_dir.mkdir()
    same_name = "명단.csv"
    key_of = []
    for d in (a_dir, b_dir):
        p = d / same_name
        p.write_text("공고명,추정가격\n전산장비 구매,1000\n", encoding="utf-8")
        ctrl.load_data_path(str(p))
        snap = pushes[-1][1]
        assert snap["data_source_label"] == f"파일: {same_name}"  # 라벨은 동일(basename)
        key_of.append(snap["data_key"])
    assert key_of[0] != key_of[1], (
        f"동명 다른 폴더의 data_key 가 같습니다 — 표면 세션 리셋이 발화하지 않습니다: {key_of!r}"
    )


def test_new_draft_kills_zone_but_keeps_slot(tmp_path):
    """「새 기안」 = 존(선택·큐·필터) 세션 휘발, 직전 필터 슬롯은 컨트롤러 수명(직전성).

    세션이 죽을 때 활성 정의를 스태시하므로, 같은 데이터를 다시 겨누면 재적용이 선다.
    """
    ctrl, pushes = _controller(tmp_path)
    src = _csv(tmp_path)
    ctrl.load_data_path(src)
    ctrl.dispatch("filter_search", {"text": "전산"})
    ctrl.dispatch("new_draft", {})
    snap = pushes[-1][1]
    assert snap["has_data"] is False and snap["selected_count"] == 0
    assert snap["filter"]["active"] is False
    ctrl.load_data_path(src)
    assert pushes[-1][1]["filter"]["reapply_available"] is True
