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

import pytest

from hwpxfiller.core.text_registry import TextTemplateRegistry
from hwpxfiller.core.text_render import FULLWIDTH_SPACE
from hwpxfiller.gui.selection_state import SelectionModel
from hwpxfiller.gui.txt_queue import TxtQueueModel
from hwpxfiller.webapp.screen_txt import TxtController


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


# ------------------------------------------------------------------ 작업점 카드(PR-3)

def test_card_preview_without_data(tmp_path):
    """데이터 미겨눔 + 템플릿 = **가상 길이-1 카드**(결정 14) — 「빠른 기안」 최단 경로.

    데이터를 안 물려도 붙여넣은 원문을 직접 입력값으로 채워 복사할 수 있어야 한다. 카드는
    빈 레코드로 템플릿을 미리 보여주고(세그먼트 literal+missing), 작업점(index)은 None 이되
    카드는 실재한다(has_current). 큐가 없어 색인 지도는 비고 퇴화한다(큐 장치 숨김 신호).
    """
    ctrl, _ = _controller(tmp_path)
    card = ctrl.snapshot()["card"]
    assert card["has_current"] is True and card["index"] is None
    assert card["queue_degenerate"] is True
    assert card["index_map"] == [] and card["is_complete"] is False
    kinds = {seg["kind"] for seg in card["segments"]}
    assert kinds == {"literal", "missing"}  # 채움·빈 값 없음(아직 직접 입력 전)


def _copy(ctrl):
    """app.py copy_clipboard 브리지 경로 대역 — 작업점 카드 렌더 리포트로 note_copied 호출."""
    _, report = ctrl.render()
    ctrl.note_copied(report)


def test_preview_record_when_selection_empty(tmp_path):
    """전체 해제 = 작업점 없음이지만 카드는 행 0 을 미리 보여준다(거짓 '항목 없음' 경보 차단, 리뷰 F1).

    빈 레코드로 그리면 실재하는 열까지 전부 missing 으로 칠해 confirm-or-alarm 을 위반한다 —
    프리뷰=행 0 실상태로 복원(복사 게이트는 프리뷰가 아니라 has_current 가 진다).
    """
    ctrl, pushes = _controller(tmp_path)  # 템플릿: 제목:{{공고명}} 금액:{{추정가격}}
    ctrl.load_data_path(_csv(tmp_path))   # 3행(공고명·추정가격 다 채움)
    ctrl.dispatch("set_none", {})
    snap = pushes[-1][1]
    card = snap["card"]
    assert card["has_current"] is False and card["index"] is None  # 작업점 없음(복사 게이트)
    # 하지만 프리뷰=행 0 실상태라 실재 열이 '항목 없음'으로 거짓 경보되지 않는다.
    assert {t["name"]: t["state"] for t in snap["tokens"]} == {"공고명": "fill", "추정가격": "fill"}
    assert card["missing_fields"] == [] and card["empty_fields"] == []


def test_can_copy_gates_on_work_point(tmp_path):
    """복사 가능 = 작업점 실재 **또는 가상 카드**(결정 14) — 빈 문자열 오염만 막는다.

    무데이터라도 템플릿이 있으면 직접 입력값으로 복사할 수 있다(가상 카드). 브리지가 막는
    것은 이제 **나갈 것이 없는 경우**(원문도 데이터도 없음)와, 데이터가 있는데 선택 0(작업점
    부재)뿐이다 — 미채움 토큰이 나가는 것은 복사 전 빈칸 게이트(copy_precheck)가 잡는다.
    """
    ctrl, _ = _controller(tmp_path)
    assert ctrl.can_copy() is True            # 무데이터라도 템플릿 = 가상 카드(결정 14)
    ctrl.dispatch("set_template_text", {"text": ""})  # 원문 비우면 나갈 것이 없다
    assert ctrl.can_copy() is False
    ctrl.load_data_path(_csv(tmp_path))
    assert ctrl.can_copy() is True
    ctrl.dispatch("set_none", {})
    assert ctrl.can_copy() is False           # 데이터 있는데 선택 0 = 작업점 없음(가상 아님)


def test_copy_precheck_reports_gaps_of_the_card_that_will_be_copied(tmp_path):
    """빈칸 게이트 질의(#125 · 결정 16 · A-3-28) — 복사 **전에** 결손 집합을 확정한다.

    같은 :meth:`render` 통로를 타므로 게이트가 본 집합과 실제 클립보드로 나갈 텍스트가
    갈라지지 않는다. 작업점이 이동하면 보고 대상도 그 카드로 따라간다(딴 카드의 결손을
    근거로 확인을 받으면 그 확인은 거짓이다).
    """
    ctrl, _ = _controller(tmp_path)  # 템플릿: 제목:{{공고명}} 금액:{{추정가격}}
    gapped = tmp_path / "gap.csv"
    gapped.write_text("공고명,추정가격\n전산장비,1000\n사무비품,\n", encoding="utf-8")
    ctrl.load_data_path(str(gapped))
    first = ctrl.dispatch("copy_precheck", {})
    assert first["can_copy"] is True and first["row"] == 0
    assert first["missing_fields"] == [] and first["empty_fields"] == []  # 0행은 전량 채움
    ctrl.dispatch("step", {"delta": 1})                    # 작업점 → 1행(추정가격 빈칸)
    second = ctrl.dispatch("copy_precheck", {})
    assert second["row"] == 1 and second["empty_fields"] == ["추정가격"]
    ctrl.dispatch("set_none", {})                          # 작업점 소실
    assert ctrl.dispatch("copy_precheck", {})["can_copy"] is False


def test_copy_precheck_flags_unresolved_tokens_as_missing(tmp_path):
    """데이터에 없는 토큰은 '항목 없음'으로 선다 — 이게 확인 없이 나가던 그 집합(#125)."""
    ctrl, _ = _controller(tmp_path)
    other = tmp_path / "other.csv"
    other.write_text("공고명\n전산장비\n", encoding="utf-8")  # 추정가격 열 자체가 없음
    ctrl.load_data_path(str(other))
    pre = ctrl.dispatch("copy_precheck", {})
    assert pre["missing_fields"] == ["추정가격"]
    text, _report = ctrl.render()
    assert "{{추정가격}}" in text  # 게이트가 막지 않으면 이 원문이 그대로 클립보드로 간다


def test_copy_precheck_is_a_query(tmp_path):
    """게이트 질의는 무변이 — 확인을 받기도 전에 큐가 전진하면 그것이 조용한 파괴다."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    before = len(pushes)
    ctrl.dispatch("copy_precheck", {})
    assert len(pushes) == before                      # 푸시 없음(is_query)
    assert ctrl.queue.copied_count() == 0             # 큐 진행 불변
    assert ctrl.snapshot()["card"]["index"] == 0      # 작업점 불변


def test_new_draft_guard_arms_on_partial_queue(tmp_path):
    """#126 면제 철회 — 「＋ 새 기안」이 소비하는 T3 술어가 큐 부분 진행에서 무장한다.

    데이터 교체 가드와 **같은** ``guard_state`` 다(두 파괴 경로가 한 술어를 공유). 완주는
    완료 이벤트라 무장 해제 — 다 복사한 큐를 새로 시작하는 건 버리는 노동이 없다.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))               # 3행 전체 선택
    assert ctrl.dispatch("guard_state", {})["queue_partial"] is False
    ctrl.dispatch("toggle_advance", {"value": True})  # 복사 후 다음 미처리로(전진 opt-in)
    _copy(ctrl)                                       # 1/3 복사 = 부분 진행
    g = ctrl.dispatch("guard_state", {})
    assert g["queue_partial"] is True and g["armed"] is True and g["copied_count"] == 1
    _copy(ctrl)
    _copy(ctrl)                                       # 완주
    assert ctrl.dispatch("guard_state", {})["queue_partial"] is False


def test_copy_marks_current_and_stays(tmp_path):
    """복사(note_copied) = 작업점을 처리 후미로(멱등), **작업점은 그 카드에 머문다**(결정 16).

    복사 후 전진은 opt-in(기본 꺼짐) — 넘어가기가 사용자의 사실상 붙여넣기 서명이라.
    """
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))          # 3행, 작업점 = 행 0
    _copy(ctrl)
    card = pushes[-1][1]["card"]
    assert card["index"] == 0 and card["is_copied"] is True   # 작업점 머묾 + 복사됨
    assert card["copied_count"] == 1 and card["uncopied_count"] == 2
    imap = card["index_map"]
    assert [d["state"] for d in imap] == ["uncopied", "uncopied", "current"]  # 복사분 후미
    # 완료 노트 = 스냅샷 구동(card.last_copy) — 복사한 행 명시(전량 채움이라 미충족 없음).
    assert card["last_copy"] == {"row": 0, "missing_fields": [], "empty_fields": []}


def test_copy_note_names_row_and_reports_gaps(tmp_path):
    """미충족 포함 복사 = last_copy 가 그 행·리포트를 실어 온다(빈칸 게이트 재진술)."""
    csv = tmp_path / "gap.csv"
    csv.write_text("공고명,추정가격\n전산장비,\n비품,2000\n", encoding="utf-8")  # 행0 추정가격 빈 값
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_data_path(str(csv))
    _copy(ctrl)                                  # 행 0(추정가격 빈 값) 복사
    lc = pushes[-1][1]["card"]["last_copy"]
    assert lc["row"] == 0 and lc["empty_fields"] == ["추정가격"]
    # 어떤 변이 동작이든 완료 노트를 걷는다(카드가 바뀌므로 모순 방지, 리뷰 F1).
    ctrl.dispatch("step", {"delta": 1})
    assert pushes[-1][1]["card"]["last_copy"] is None


def test_copy_with_advance_moves_to_next_uncopied(tmp_path):
    """복사 후 전진 켜짐 = 작업점이 다음 미처리로(↓ 서명) — 큐를 걷는 감각.

    전진해도 완료 노트(last_copy.row)는 **복사한 행**을 못박는다(카드는 다음 행, 리뷰 F2).
    """
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    ctrl.dispatch("toggle_advance", {"value": True})
    _copy(ctrl)                                  # 행 0 복사 → 전진
    card = pushes[-1][1]["card"]
    assert card["index"] == 1 and card["is_copied"] is False   # 카드는 다음 미처리로 전진
    assert card["copied_count"] == 1 and card["position"] == 1  # 작업점 = 남은 첫 미처리
    assert card["last_copy"]["row"] == 0                        # 노트는 복사한 행(0)을 명시


def test_gap_predicate_matches_render_segments_for_zero(tmp_path):
    """빈칸 지도·토큰 술어 = render_segments 와 **동일**(리뷰 F4) — 값 0(falsy 비-None)은 채움.

    종전 ``str(v or "").strip()==""`` 은 0·False 를 빈칸으로 오판해, 값 0 인 행이 상태 색인엔
    빨강 빈칸 점인데 카드는 '0' 을 채움으로 렌더하는 모순을 냈다. 단일 술어로 봉합.
    """
    ctrl, _ = _controller(tmp_path)  # 템플릿 = 제목:{{공고명}} 금액:{{추정가격}}
    ctrl.vm.set_acquired(object(), [{"공고명": "전산장비", "추정가격": 0}])
    ctrl.selection = SelectionModel(1)
    ctrl.queue = TxtQueueModel(ctrl.selection)
    ctrl._rebuild_mapping()  # #148 슬라이스 3b — 데이터 열에 맞추기 결속(load_data_path 가 하는 일)
    snap = ctrl.snapshot()
    card = snap["card"]
    assert card["index_map"][0]["has_gap"] is False   # 0 = 채움(0원 렌더), 빈칸 지도 빨강 아님
    assert card["missing_fields"] == [] and card["empty_fields"] == []
    assert {t["name"]: t["state"] for t in snap["tokens"]} == {"공고명": "fill", "추정가격": "fill"}
    assert "0" in "".join(seg["text"] for seg in card["segments"])  # 카드 렌더도 0 을 채움으로


def test_copy_all_reaches_completion(tmp_path):
    """전부 복사 = 완주(미처리 소진) — 상태 색인이 완주를 진술."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    ctrl.dispatch("toggle_advance", {"value": True})
    for _ in range(3):
        _copy(ctrl)
    card = pushes[-1][1]["card"]
    assert card["is_complete"] is True and card["copied_count"] == 3 and card["uncopied_count"] == 0


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


# ------------------------- 대상 글꼴 선언·정렬 린트·T3 가드(블록 3 결정 17 · 블록 4 결정 26·27)

def _aligned_controller(tmp_path: Path, template: str) -> "tuple[TxtController, list]":
    """정렬 런이 있는 템플릿 + 격리된 설정 홈 — 글꼴/린트 회귀의 공용 지그."""
    (tmp_path / "정렬기안.txt").write_text(template, encoding="utf-8")
    pushes: list = []
    ctrl = TxtController(TextTemplateRegistry(tmp_path), lambda s, snap: pushes.append((s, snap)))
    return ctrl, pushes


def test_target_font_defaults_and_persists(tmp_path, monkeypatch):
    """대상 글꼴 선언은 **전역 영속**(설정 파일) — 새 컨트롤러가 그 값으로 태어난다(결정 17)."""
    home = tmp_path / "home"
    monkeypatch.setenv("HWPXFILLER_HOME", str(home))
    ctrl, pushes = _controller(tmp_path)
    assert ctrl.snapshot()["target_font"] == "gulimche"  # 고정폭 기본(첫 화면 경보 없음)
    ctrl.dispatch("set_target_font", {"font": "malgun"})
    assert pushes[-1][1]["target_font"] == "malgun"
    fresh, _ = _controller(tmp_path)
    assert fresh.snapshot()["target_font"] == "malgun"  # 컨트롤러보다 오래 산다


def test_target_font_rejects_unknown_value_loudly(tmp_path, monkeypatch):
    """열거형 밖 값은 조용히 무시하지 않는다 — 상태도 불변(confirm-or-alarm)."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    ctrl, _ = _controller(tmp_path)
    with pytest.raises(ValueError):
        ctrl.dispatch("set_target_font", {"font": "궁서체"})
    assert ctrl.snapshot()["target_font"] == "gulimche"


def test_lint_is_declaration_conditional(tmp_path, monkeypatch):
    """린트는 **비례폭 선언에서만** 발화 — 고정폭에서 연속 공백은 정당한 저작이라 침묵."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    ctrl, _ = _aligned_controller(tmp_path, "건    명: {{공고명}}")
    ctrl.dispatch("select_template", {"name": "정렬기안"})
    ctrl.load_data_path(_csv(tmp_path))
    lint = ctrl.snapshot()["card"]["lint"]
    assert lint["space_run"] is True and lint["proportional"] is False
    assert lint["active"] is False  # 굴림체 선언 = 경보 없음
    ctrl.dispatch("set_target_font", {"font": "malgun"})
    lint = ctrl.snapshot()["card"]["lint"]
    assert lint["proportional"] is True and lint["active"] is True and lint["applied"] is False


def test_lint_silent_without_space_run(tmp_path, monkeypatch):
    """비례폭 선언이어도 정렬 런이 없으면 침묵 — 조건 두 개가 모두 서야 발화."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    ctrl, _ = _controller(tmp_path)  # 샘플기안엔 연속 공백이 없다
    ctrl.load_data_path(_csv(tmp_path))
    ctrl.dispatch("set_target_font", {"font": "malgun"})
    assert ctrl.snapshot()["card"]["lint"]["active"] is False


def test_fullwidth_applies_to_card_and_clipboard_alike(tmp_path, monkeypatch):
    """치환은 카드와 클립보드를 **같은 통로**로 지난다 — 보이는 것이 복사되는 것.

    템플릿 원본은 불변(세션 렌더 옵션) — 이름 있는 템플릿이 조용히 강등되지 않는다.
    """
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    ctrl, _ = _aligned_controller(tmp_path, "건    명: {{공고명}}")
    ctrl.dispatch("select_template", {"name": "정렬기안"})
    ctrl.load_data_path(_csv(tmp_path))
    ctrl.dispatch("set_target_font", {"font": "malgun"})
    ctrl.dispatch("set_fullwidth", {"value": True})
    snap = ctrl.snapshot()
    card_text = "".join(s["text"] for s in snap["card"]["segments"])
    clip, _report = ctrl.render()
    assert card_text == clip
    assert FULLWIDTH_SPACE in clip and "  " not in clip
    assert snap["template_text"] == "건    명: {{공고명}}"  # 원본 불변
    assert snap["template_name"] == "정렬기안"              # 강등 없음
    assert snap["card"]["lint"] == {
        "proportional": True, "space_run": True, "applied": True, "active": True,
    }
    ctrl.dispatch("set_fullwidth", {"value": False})       # 되돌리기는 항상 열려 있다
    assert FULLWIDTH_SPACE not in ctrl.render()[0]


def test_fullwidth_dies_with_session_but_font_survives(tmp_path, monkeypatch):
    """치환 = 이번 원문의 조치(세션 휘발) · 글꼴 선언 = 사용자 환경 사실(전역 영속)."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    ctrl, _ = _aligned_controller(tmp_path, "건    명: {{공고명}}")
    ctrl.dispatch("select_template", {"name": "정렬기안"})
    ctrl.dispatch("set_target_font", {"font": "malgun"})
    ctrl.dispatch("set_fullwidth", {"value": True})
    ctrl.dispatch("new_draft", {})
    snap = ctrl.snapshot()
    assert snap["card"]["lint"]["applied"] is False
    assert snap["target_font"] == "malgun"


def test_t3_guard_arms_on_partial_queue_progress(tmp_path):
    """T3(결정 26·27): 큐 부분 진행 = 무장. 완주는 완료 이벤트라 무장 해제."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))          # 3행 전체 선택 = 1클릭 재현 가능
    assert ctrl.dispatch("guard_state", {})["armed"] is False
    ctrl.note_copied(ctrl.render()[1])           # 1/3 복사 — 어디까지 붙여넣었는지는 앱 밖 기억
    g = ctrl.dispatch("guard_state", {})
    assert g["armed"] is True and g["queue_partial"] is True
    assert (g["copied_count"], g["sel_count"]) == (1, 3)
    for _ in range(2):                           # 완주까지 마저 복사
        ctrl.queue.set_current(None)
        ctrl.note_copied(ctrl.render()[1])
    g = ctrl.dispatch("guard_state", {})
    assert g["copied_count"] == 3
    assert g["queue_partial"] is False and g["armed"] is False


def test_t3_guard_arms_on_handmade_selection(tmp_path):
    """선택 성분(작업 화면과 공유 술어)도 txt 에서 선다 — 복사 0건이어도 수작업 열거는 무장."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    ctrl.dispatch("toggle_record", {"index": 2, "value": False})  # 필터 없는 부분 선택
    g = ctrl.dispatch("guard_state", {})
    assert g["armed"] is True and g["queue_partial"] is False
    assert g["sel_count"] == 2 and g["filter_active"] is False


def test_guard_state_is_pushless_query(tmp_path):
    """무변이 질의 — 재렌더 낭비도, 직전 복사 확정의 조용한 소거도 없다(작업 화면 규약 승계)."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    ctrl.note_copied(ctrl.render()[1])
    before = len(pushes)
    ctrl.dispatch("guard_state", {})
    assert len(pushes) == before
    assert pushes[-1][1]["card"]["last_copy"] is not None


def test_lint_row_survives_switch_to_fixed_width(tmp_path, monkeypatch):
    """치환이 걸린 채 고정폭으로 되돌려도 린트 줄은 선다(리뷰 F1) — 조용한 변환 금지.

    줄이 사라지면 전각 공백이 계속 클립보드로 나가는데 사용자는 통보도, 되돌릴 손잡이도
    잃는다(confirm-or-alarm 위반). 경보(치환 전)만 선언-조건부다.
    """
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    ctrl, _ = _aligned_controller(tmp_path, "건    명: {{공고명}}")
    ctrl.dispatch("select_template", {"name": "정렬기안"})
    ctrl.dispatch("set_target_font", {"font": "malgun"})
    ctrl.dispatch("set_fullwidth", {"value": True})
    ctrl.dispatch("set_target_font", {"font": "gulimche"})
    lint = ctrl.snapshot()["card"]["lint"]
    assert lint["applied"] is True and lint["proportional"] is False
    assert lint["active"] is True, "치환이 걸렸는데 되돌릴 줄이 사라졌습니다(리뷰 F1)."
    assert FULLWIDTH_SPACE in ctrl.render()[0]  # 변환은 유지 — 몰래 되돌리지도 않는다


def test_fullwidth_dies_on_template_change(tmp_path, monkeypatch):
    """치환 결정은 그 원문 것 — 템플릿 교체·붙여넣기에 승계되지 않는다(리뷰 F2).

    승계되면 새 템플릿의 의도된 정렬이 동의 없이 변환되고, 런이 없는 템플릿에선 린트가
    「치환했습니다」를 거짓 주장한다.
    """
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    (tmp_path / "둘째기안.txt").write_text("항  목: {{공고명}}", encoding="utf-8")
    ctrl, _ = _aligned_controller(tmp_path, "건    명: {{공고명}}")
    ctrl.dispatch("select_template", {"name": "정렬기안"})
    ctrl.dispatch("set_target_font", {"font": "malgun"})
    ctrl.dispatch("set_fullwidth", {"value": True})
    ctrl.dispatch("select_template", {"name": "둘째기안"})
    assert ctrl.snapshot()["card"]["lint"]["applied"] is False
    ctrl.dispatch("set_fullwidth", {"value": True})
    ctrl.dispatch("set_template_text", {"text": "붙여넣은  원문"})
    assert ctrl.snapshot()["card"]["lint"]["applied"] is False


def test_lint_ignores_runs_inside_data_values(tmp_path, monkeypatch):
    """값 안의 연속 공백은 경보 대상이 아니다(리뷰 F3) — 복사 데이터는 원본과 글자 단위 동일."""
    monkeypatch.setenv("HWPXFILLER_HOME", str(tmp_path / "home"))
    csv = tmp_path / "spec.csv"
    csv.write_text("공고명,추정가격\n규격 12  345,1000\n", encoding="utf-8")
    ctrl, _ = _controller(tmp_path)  # 템플릿(샘플기안)엔 정렬 런이 없다
    ctrl.load_data_path(str(csv))
    ctrl.dispatch("set_target_font", {"font": "malgun"})
    assert ctrl.snapshot()["card"]["lint"]["space_run"] is False
    assert "규격 12  345" in ctrl.render()[0]


# ---------------------------------------------- #148 슬라이스 3b: 맞추기 표(결속·제안·표시형·소유권)
def _tok(snap, name):
    return next(t for t in snap["tokens"] if t["name"] == name)


def test_map_exact_autobind_and_snapshot_shape(tmp_path):
    """데이터 겨눔 = 정확 일치 열 자동 결속(auto)·값 스니핑 유형 + 결속 후보·프리셋 스냅샷.

    템플릿 토큰(공고명·추정가격)이 CSV 열과 정확히 같아 자동 결속되고, 「지금 행의 값」은 큐
    작업점(행 0)의 값을 서식해 보인다(추정가격 amount → 천단위)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    snap = ctrl.snapshot()
    assert snap["columns"] == ["공고명", "추정가격"]     # 결속 드롭다운 후보
    assert "amount" in snap["fmt_options"] and "text" in snap["fmt_options"]
    g, p = _tok(snap, "공고명"), _tok(snap, "추정가격")
    assert g["own"] == "auto" and g["source"] == "공고명" and g["state"] == "fill"
    assert g["value"] == "전산장비 구매"                 # 작업점(행 0) 값
    assert p["own"] == "auto" and p["fmt_kind"] == "amount" and p["value"] == "1,000원"


def test_seam_preview_follows_queue_current(tmp_path):
    """이음매 = 레코드→매핑→값 사전 — 「지금 행의 값」이 큐 작업점을 따라 행마다 바뀐다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    assert _tok(ctrl.snapshot(), "공고명")["value"] == "전산장비 구매"   # 행 0
    ctrl.dispatch("step", {"delta": 1})
    assert _tok(ctrl.snapshot(), "공고명")["value"] == "비품 구매"       # 행 1


def test_set_map_value_demotes_to_manual_constant(tmp_path):
    """값 직접 입력(set_map_value) = 상수(man) — 전 행 공통이고 결속 소스는 기억(되돌리기용)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    ctrl.dispatch("set_map_value", {"name": "공고명", "text": "고정 제목"})
    g = _tok(ctrl.snapshot(), "공고명")
    assert g["own"] == "man" and g["value"] == "고정 제목" and g["can_revert"] is True
    ctrl.dispatch("step", {"delta": 1})                  # 다른 행으로 이동해도
    assert _tok(ctrl.snapshot(), "공고명")["value"] == "고정 제목"  # 상수라 그대로


def test_revert_map_restores_binding(tmp_path):
    """되돌리기(revert_map) = 상수 강등을 원 결속 열로 복귀(막다른 강등 금지)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    ctrl.dispatch("set_map_value", {"name": "공고명", "text": "고정"})
    ctrl.dispatch("revert_map", {"name": "공고명"})
    g = _tok(ctrl.snapshot(), "공고명")
    assert g["own"] == "auto" and g["source"] == "공고명" and g["value"] == "전산장비 구매"


def test_set_source_unbind_then_rebind(tmp_path):
    """드롭다운 (직접 입력) = 해제(무결속·missing), 열 선택 = 재결속(auto)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    ctrl.dispatch("set_source", {"name": "공고명", "col": ""})       # 해제
    g = _tok(ctrl.snapshot(), "공고명")
    assert g["own"] == "" and g["source"] == "" and g["state"] == "missing"
    ctrl.dispatch("set_source", {"name": "공고명", "col": "추정가격"})  # 다른 열로 재결속
    assert _tok(ctrl.snapshot(), "공고명")["source"] == "추정가격"


def test_set_source_overwrite_confirm_gate(tmp_path):
    """수기 값 있는 자리에 열 결속 = 재진술 확인 게이트(값 소실 사전 확인) — 확인 후 허용."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    ctrl.dispatch("set_map_value", {"name": "공고명", "text": "수기값"})
    r = ctrl.dispatch("set_source", {"name": "공고명", "col": "공고명"})  # 덮어쓰기 확인 요구
    assert isinstance(r, dict) and "수기값" in r.get("confirm", "")
    assert _tok(ctrl.snapshot(), "공고명")["own"] == "man"            # 아직 안 바뀜
    ctrl.dispatch("set_source", {"name": "공고명", "col": "공고명", "confirm": True})
    assert _tok(ctrl.snapshot(), "공고명")["own"] == "auto"           # 확인 후 결속


def test_edit_source_retokenizes_and_preserves_manual(tmp_path):
    """원문 라이브 편집(edit_source) = 토큰 재구성 + 사람 소유(수기 값) 승계 + _NO_PUSH 반환.

    새 토큰이 생기고, 이미 손댄 수기 값은 살아남는다(재구성이 조용히 버리지 않는다)."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    ctrl.dispatch("set_map_value", {"name": "공고명", "text": "수기"})
    n_before = len(pushes)
    snap = ctrl.dispatch("edit_source", {"text": "제목: {{공고명}} 신규: {{신규토큰}}"})
    assert len(pushes) == n_before                       # _NO_PUSH — 반환으로만 온다
    names = {t["name"] for t in snap["tokens"]}
    assert names == {"공고명", "신규토큰"}                 # 재토큰화(추정가격 사라지고 신규토큰)
    assert _tok(snap, "공고명")["value"] == "수기"         # 수기 값 승계
    assert _tok(snap, "신규토큰")["state"] == "missing"    # 새 자리는 무결속


def test_unknown_map_column_is_loud(tmp_path):
    """데이터에 없는 열 결속은 조용히 무시하지 않고 시끄럽게 거부한다(confirm-or-alarm)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    with pytest.raises(ValueError):
        ctrl.dispatch("set_source", {"name": "공고명", "col": "없는열"})


def test_rebuild_drops_remembered_source_absent_in_new_data(tmp_path):
    """Codex F3 — 상수(man)의 기억된 결속 소스는 새 데이터에 살아 있을 때만 승계한다.

    결속 값을 고쳐 만든 상수는 데이터가 바뀌어도 값은 유지하되, 그 열이 새 데이터에 없으면
    소스 기억을 비운다 — 안 그러면 「되돌리기」가 없는 열로 결속을 되살려 전 레코드에 빈 값을
    내면서 소유권은 auto 라 보고하는 계약 거짓말이 된다(can_revert=type==const∧source 라 정합)."""
    ctrl, _ = _controller(tmp_path)  # 템플릿: 제목:{{공고명}} 금액:{{추정가격}}
    ctrl.load_data_path(_csv(tmp_path))                    # 공고명 자동 결속
    ctrl.dispatch("set_map_value", {"name": "공고명", "text": "고정 제목"})  # man(소스 기억)
    assert _tok(ctrl.snapshot(), "공고명")["can_revert"] is True
    other = tmp_path / "other.csv"
    other.write_text("업체명,추정가격\n대한산업,1000\n", encoding="utf-8")  # 공고명 열 없음
    ctrl.load_data_path(str(other))
    g = _tok(ctrl.snapshot(), "공고명")
    assert g["own"] == "man" and g["value"] == "고정 제목"  # 상수 값은 유지(데이터 무관)
    assert g["can_revert"] is False                        # 죽은 소스 기억은 비웠다(되돌리기 사라짐)


# ---------------------------------------------- 매핑 그릇: 유형·확정·확정-비움(#148 슬라이스 4)
def test_snapshot_exposes_type_options_and_confirmed_flags(tmp_path):
    """맞추기 스냅샷 = 유형 후보(값-운반 유형) + 행별 확정·확정-비움 표지(그릇 계약)."""
    ctrl, _ = _controller(tmp_path)
    snap = ctrl.snapshot()
    assert [o["code"] for o in snap["type_options"]] == ["text", "date", "amount"]  # const 없음(결정 12·14)
    for t in snap["tokens"]:
        assert "confirmed" in t and "blank_declared" in t


def test_set_map_type_overrides_sniffed_type(tmp_path):
    """유형 정정(set_map_type, 결정 12) — 사람이 값 스니핑을 이긴다(표시형 리셋·값 재서식)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))                     # 추정가격 = amount 스니핑(천단위)
    assert _tok(ctrl.snapshot(), "추정가격")["value"] == "1,000원"
    ctrl.dispatch("set_map_type", {"name": "추정가격", "type": "text"})  # 사람이 text 로 정정
    p = _tok(ctrl.snapshot(), "추정가격")
    assert p["fmt_kind"] == "text" and p["value"] == "1000"  # 유형 바뀌고 값이 text 서식


def test_set_map_type_unknown_is_loud(tmp_path):
    """미지 유형은 조용히 무시하지 않고 시끄럽게 거부한다(열거형 검증 — confirm-or-alarm)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    with pytest.raises(ValueError):
        ctrl.dispatch("set_map_type", {"name": "공고명", "type": "없는유형"})


def test_set_confirmed_toggles_row(tmp_path):
    """행별 확정 토글(set_confirmed) — 스냅샷 confirmed 되읽기."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    assert _tok(ctrl.snapshot(), "공고명")["confirmed"] is False
    ctrl.dispatch("set_confirmed", {"name": "공고명", "value": True})
    assert _tok(ctrl.snapshot(), "공고명")["confirmed"] is True


def test_confirmed_blank_renders_blank_and_excluded_from_gate(tmp_path):
    """확정-비움(결정 12) — 확정+무결속 토큰은 blank(〈빈 값〉)로 렌더되고 빈칸 게이트에서 빠진다.

    데이터가 비어 생긴 blank(선언 아님)는 게이트에 **남아** 두 무결속 상태를 가른다."""
    ctrl, _ = _controller(tmp_path)
    gapped = tmp_path / "g.csv"
    gapped.write_text("공고명,추정가격\n전산장비,\n", encoding="utf-8")  # 추정가격 빈값
    ctrl.load_data_path(str(gapped))
    ctrl.dispatch("set_template_text",
                  {"text": "제목:{{공고명}} 금액:{{추정가격}} 비고:{{비고}}"})
    pre0 = ctrl.dispatch("copy_precheck", {})
    assert "비고" in pre0["missing_fields"] and "추정가격" in pre0["empty_fields"]  # 확정 전
    ctrl.dispatch("set_confirmed", {"name": "비고", "value": True})               # 「비운다」 확정
    snap = ctrl.snapshot()
    assert _tok(snap, "비고")["blank_declared"] is True
    assert _tok(snap, "비고")["state"] == "blank"          # missing → blank(〈빈 값〉)
    pre1 = ctrl.dispatch("copy_precheck", {})
    assert "비고" not in pre1["missing_fields"] and "비고" not in pre1["empty_fields"]  # 게이트서 빠짐
    assert "추정가격" in pre1["empty_fields"]              # 데이터-빈값은 남는다(그 행의 사실)
    assert "비고" not in snap["card"]["empty_fields"]      # 카드 게이트 집합도 뺀다(단일 판정)


def test_confirmed_blank_excluded_from_completion_note(tmp_path):
    """확정-비움은 완료 노트의 「빈 값」에서도 빠진다 — 선언한 비움은 경고가 아니다(게이트와 같은 판정)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    ctrl.dispatch("set_template_text", {"text": "제목:{{공고명}} 비고:{{비고}}"})
    ctrl.dispatch("set_confirmed", {"name": "비고", "value": True})
    _copy(ctrl)
    lc = ctrl.snapshot()["card"]["last_copy"]
    assert lc is not None
    assert "비고" not in lc["empty_fields"] and "비고" not in lc["missing_fields"]


def test_confirmed_blank_clears_when_value_typed(tmp_path):
    """확정-비움에 값을 채우면 선언이 풀린다 — 내용이 생겨 확정-비움이 아니게 되고 게이트로 복귀."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    ctrl.dispatch("set_template_text", {"text": "제목:{{공고명}} 비고:{{비고}}"})
    ctrl.dispatch("set_confirmed", {"name": "비고", "value": True})
    assert _tok(ctrl.snapshot(), "비고")["blank_declared"] is True
    ctrl.dispatch("set_map_value", {"name": "비고", "text": "특이사항"})  # 직접 입력 = 상수
    b = _tok(ctrl.snapshot(), "비고")
    assert b["blank_declared"] is False and b["own"] == "man" and b["value"] == "특이사항"


def test_confirmed_blank_survives_template_edit(tmp_path):
    """확정-비움은 무관한 템플릿 편집에 살아남는다(Codex F1) — _rebuild_mapping 이 confirmed 를
    조용히 버리면 선언이 증발하고 토큰이 missing 으로 게이트에 재진입한다(confirm-or-alarm 위반)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    ctrl.dispatch("set_template_text", {"text": "제목:{{공고명}} 비고:{{비고}}"})
    ctrl.dispatch("set_confirmed", {"name": "비고", "value": True})
    ctrl.dispatch("edit_source", {"text": "제목:{{공고명}} 비고:{{비고}} 신규:{{신규}}"})  # 무관한 토큰 추가
    b = _tok(ctrl.snapshot(), "비고")
    assert b["blank_declared"] is True and b["state"] == "blank"  # 선언 보존(증발 안 함)
    assert "비고" not in ctrl.dispatch("copy_precheck", {})["missing_fields"]  # 게이트 재진입 안 함


def test_confirmed_blank_survives_data_reload_and_overrides_autobind(tmp_path):
    """확정-비움은 데이터 새로고침에 살아남고, 새 데이터의 정확 일치 자동 결속까지 덮는다(Codex F1).

    사람의 「비운다」가 시스템 재제안을 이긴다(결정 12) — 비고 열이 새로 생겨도 자동 결속하지 않는다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))
    ctrl.dispatch("set_template_text", {"text": "제목:{{공고명}} 비고:{{비고}}"})
    ctrl.dispatch("set_confirmed", {"name": "비고", "value": True})
    withcol = tmp_path / "w.csv"
    withcol.write_text("공고명,비고\n전산장비,자동결속후보\n", encoding="utf-8")  # 비고 열 존재
    ctrl.load_data_path(str(withcol))
    b = _tok(ctrl.snapshot(), "비고")
    assert b["blank_declared"] is True and b["source"] == ""  # 선언 보존 + 자동 결속 안 됨


def test_dead_bound_confirmed_drops_to_gate_not_silent_blank(tmp_path):
    """확정된 결속 행의 열이 새 데이터에서 사라지면 확정-비움으로 조용히 승격하지 않는다(결정 12).

    죽은 결속과 「비운다」 선언은 다른 사실이다 — 값 복구 불가라 시스템 소유(missing)로 떨어뜨려
    게이트가 잡게 하고 사람 재검토를 강제한다(조용한 blank 승격 금지)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))                    # 공고명 자동 결속
    ctrl.dispatch("set_confirmed", {"name": "공고명", "value": True})  # 결속 행 확정(내용 있음)
    other = tmp_path / "o.csv"
    other.write_text("추정가격\n1000\n", encoding="utf-8")  # 공고명 열 사라짐
    ctrl.load_data_path(str(other))
    g = _tok(ctrl.snapshot(), "공고명")
    assert g["blank_declared"] is False and g["state"] == "missing"  # 게이트에 남는다(조용한 승격 아님)


def test_emptied_bound_const_becomes_declared_blank_when_confirmed(tmp_path):
    """결속 값을 비우고 확정하면 확정-비움으로 인식된다(Codex F2) — 기억된 소스는 const 의
    내용이 아니라 되돌리기용이다. 게이트가 계속 묻지 않는다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_csv(tmp_path))                    # 공고명 자동 결속
    ctrl.dispatch("set_map_value", {"name": "공고명", "text": ""})  # 결속 값 비움 → const="" (소스 기억)
    g = _tok(ctrl.snapshot(), "공고명")
    assert g["can_revert"] is True and g["blank_declared"] is False  # 소스 기억·아직 미확정
    ctrl.dispatch("set_confirmed", {"name": "공고명", "value": True})
    g2 = _tok(ctrl.snapshot(), "공고명")
    assert g2["blank_declared"] is True                    # 확정+빈 상수 = 확정-비움
    assert "공고명" not in ctrl.dispatch("copy_precheck", {})["empty_fields"]  # 게이트서 빠짐
