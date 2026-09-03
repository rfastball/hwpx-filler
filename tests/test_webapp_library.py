"""「문서 작업」(전역 라이브러리) 컨트롤러 계약 가드 — pywebview/Qt 불필요(헤드리스).

재작성 F2 PR-A 에서 홈 컨트롤러를 승계했다(지도 §10.8). 링1 HomeViewModel 을 그대로
임포트한 컨트롤러가 보기 4종·작업 방식 필터·검색·태그 facet·그룹 구획과 접힘·상세(건강 전
원인·필드 연결)·손상 격리 스냅샷을 창 없이 낸다. 화면 이동(겨눔·전환)은 링2(웹)라 여기서
다루지 않는다.
"""
from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path

import pytest

from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.domain.job import Job
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.external.template_root import TemplateRoot
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.external.text_registry import TextTemplateRegistry
from hwpxfiller.external.hwpx_package_io import write_hwpx_package
from hwpxfiller.webapp.screen_library import (
    UNBOUND_FIRST_ROW_REASON,
    LibraryController,
)
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage


def _pool(tmp_path) -> DatasetPoolRegistry:
    """빈 풀 레지스트리 — 미주입 시 실사용자 홈 디렉터리로 새는 걸 막는다(밀폐)."""
    return DatasetPoolRegistry(tmp_path / "datasets")


def _reg(tmp_path) -> JobRegistry:
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(
        name="공고서",
        template_path="/none/t.hwpx",  # 존재 안 함 → template_missing(danger 배지)
        mapping=MappingProfile(mappings=[FieldMapping(template_field="공고명", source="bidNtceNm")]),
        filename_pattern="공고-{{ID}}",
        last_run_at="2026-07-09T15:42:00",
        tags={"금액구간": "1억미만"},
        # 결속된 작업(U4 §2.4) — 목록·상세가 데이터 축을 말하는지 재는 표본.
        data_path="/data/월별.xlsx", data_sheet="낙찰현황",
    ))
    reg.save(Job(
        name="낙찰", template_path="", filename_pattern="낙찰-{{ID}}",
        # 결속 없는 구판 작업 — U4-C 마이그레이션이 목록에서 보여야 하는 상태다.
        last_run_at="2026-06-30T11:08:00", tags={"금액구간": "10억이상"},
    ))
    return reg


def _text_reg(tmp_path) -> TextTemplateRegistry:
    d = tmp_path / "txt"
    d.mkdir()
    (d / "온나라_기안.txt").write_text("제목: {{공고명}} 담당 {{담당자}}", encoding="utf-8")
    return TextTemplateRegistry(d)


def _detail_deps(tmp_path) -> dict:
    """상세 연결 존(U6-F #980)이 요구하는 주입 한 벌 — 서식 폴더 권위·전역 저장 폴더·시계.

    **필수 주입**이라 폴백이 없다(#570 규율): 화면이 자기 홀더를 세우면 루트·저장 폴더의
    제2 정본이 된다. 시험은 그 셋을 밀폐값으로 고정한다.
    """
    return {
        "template_root": TemplateRoot(default_root=tmp_path / "templates"),
        "clock": lambda: datetime(2026, 9, 2, 10, 0, 0),
        "first_row_runner": lambda work: work(),
    }


def _controller(tmp_path, *, registry=None, runner=None)         -> "tuple[LibraryController, list]":
    """헤드리스 컨트롤러 + 푸시 수집 리스트.

    ``runner`` 는 첫 행 읽기의 **실행 자리**다(U6-F #980). 기본은 즉시 실행이라 이 파일의
    옛 단언들이 그대로 결정론이고, 두 번째 푸시를 관측하는 시험만 지연 러너를 넣는다 —
    제품은 워커 스레드이고 갈리는 것은 「어디서 도는가」 하나다.
    """
    pushes: list = []
    ctrl = LibraryController(registry or _reg(tmp_path), _text_reg(tmp_path),
                          lambda s, snap: pushes.append((s, snap)),
                          engine=make_hwpx_engine(),
                          pool_registry=_pool(tmp_path),
                          generation_lock=threading.Lock(),
                          template_root=TemplateRoot(default_root=tmp_path / "templates"),
                          clock=lambda: datetime(2026, 9, 2, 10, 0, 0),
                          first_row_runner=runner or (lambda work: work()))
    return ctrl, pushes


def _rows(snap) -> "dict[str, dict]":
    return {r["name"]: r for sec in snap["sections"] for r in sec["rows"]}


def test_initial_snapshot_serializes_the_ring1_contract(tmp_path):
    """개수 타일(#239 결정 8)은 승계하지 않고, **조치가 필요한 조건**만 경보로 싣는다."""
    ctrl, _ = _controller(tmp_path)
    snap = ctrl.initial()
    assert snap["is_empty"] is False
    assert snap["view"] == "all" and snap["mode"] == "all" and snap["query"] == ""
    assert snap["alerts"]["missing_template_count"] == 1  # /none/t.hwpx 부재
    # 죽은 홈 요약 표면은 스냅샷에서도 사라졌다 — 렌더 안 하는 값을 나르지 않는다.
    for dead in ("kpi", "txt_rows", "continue_runs", "grouped_rows", "axes", "group_by"):
        assert dead not in snap, f"죽은 홈 스냅샷 키가 남아 있습니다: {dead}"
    assert snap["counts"] == {"all": 2, "recent": 2, "favorites": 0, "needsAction": 2}
    rows = _rows(snap)
    assert set(rows) == {"공고서", "낙찰"}
    assert rows["공고서"]["health"] == {
        "severity": 3, "text": "템플릿 파일을 찾을 수 없습니다.",
    }
    assert rows["공고서"]["badge_level"] == "danger"
    assert rows["공고서"]["runnable"] is False
    assert rows["공고서"]["mode_label"] == "HWPX 문서 생성"
    assert rows["낙찰"]["media"] == "hwpx"


def test_alerts_carry_pool_corruption(tmp_path):
    """데이터 풀 손상 수가 웹까지 실린다(#45, 0 위장 금지).

    VM(kpi.pool_corrupted)은 세는데 스냅샷 dict 이 누락하면 confirm-or-alarm 이
    링1에서 끊긴다 — 웹이 렌더할 값 자체가 없다.
    """
    ctrl, _ = _controller(tmp_path)
    assert ctrl.snapshot()["alerts"]["pool_corrupted"] == 0  # 손상 없으면 0(거짓 경보 없음)
    # 연결된 풀 디렉터리에 손상 파일이 생기면 다음 스냅샷이 살아있는 재계수로 잡는다.
    pool_dir = tmp_path / "datasets"
    pool_dir.mkdir()
    (pool_dir / ("깨진" + DatasetPoolRegistry.SUFFIX)).write_text("{ not json", encoding="utf-8")
    assert ctrl.snapshot()["alerts"]["pool_corrupted"] == 1


def test_empty_registry_is_loudly_empty(tmp_path):
    pushes: list = []
    ctrl = LibraryController(JobRegistry(tmp_path / "j"), TextTemplateRegistry(tmp_path / "t"),
                          lambda s, snap: pushes.append((s, snap)),
                          engine=make_hwpx_engine(),
                          pool_registry=_pool(tmp_path),
                          generation_lock=threading.Lock(),
                          **_detail_deps(tmp_path))
    snap = ctrl.initial()
    assert snap["is_empty"] is True
    assert snap["counts"]["all"] == 0
    assert snap["sections"] and snap["sections"][0]["rows"] == []


def test_sections_are_always_one_headless_flat_partition(tmp_path):
    """목록은 **언제나 헤더 없는 평면 하나**다(U4 §2-30).

    구획을 만들던 축은 사용자 group 하나였고 그 표면이 걷혔다. 저장된 group 값이 남아
    있어도 구획을 만들지 않는다 — 이름을 바꾸거나 해산할 동사가 없는 헤더는 「복구 동사
    없는 표면」이다. 판정 자체는 링1 에 동결로 살아 있다(`test_home_state`).
    """
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="가", template_path="", group="조달"))
    reg.save(Job(name="나", template_path=""))
    ctrl = LibraryController(reg, _text_reg(tmp_path), lambda s, snap: None,
                          engine=make_hwpx_engine(),
                          pool_registry=_pool(tmp_path),
                          generation_lock=threading.Lock(),
                          **_detail_deps(tmp_path))
    secs = ctrl.snapshot()["sections"]
    assert [(s["value"], s["count"], s["headed"], s["collapsed"]) for s in secs] == [
        ("", 2, False, False),
    ]
    assert [r["name"] for r in secs[0]["rows"]] == ["가", "나"]
    assert reg.load("가").group == "조달"          # durable 값은 동결로 남는다
    assert "group" not in secs[0]["rows"][0]        # 표면은 그것을 싣지 않는다
    # 그룹·태그·facet 동사는 전부 이 채널에서 사라졌다.
    for action, payload in (
        ("toggle_group", {"group": "조달"}),
        ("set_tags", {"name": "가", "tags": {}}),
        ("toggle_facet", {"axis": "금액구간", "value": "1억미만"}),
        ("clear_facets", {}),
        ("set_group_by", {"axis": "금액구간"}),
    ):
        with pytest.raises(ValueError, match="알 수 없는 library 액션"):
            ctrl.dispatch(action, payload)


def test_delete_job_clears_selected_detail_and_pushes_snapshot(tmp_path):
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("select_work", {"name": "낙찰"})
    assert ctrl.snapshot()["detail"]["name"] == "낙찰"
    ctrl.dispatch("delete_job", {"name": "낙찰"})
    snap = ctrl.snapshot()
    assert snap["counts"]["all"] == 1
    assert list(_rows(snap)) == ["공고서"]
    assert snap["selected"] == "" and snap["detail"] is None
    # dispatch 가 삭제 후 관측 푸시를 냈다.
    assert any(s == "library" for s, _snap in pushes)


def test_app_wires_library_session_guards_to_job(tmp_path, monkeypatch):
    """#268 리뷰 배선 가드 — WebFrontend 가 라이브러리 삭제 가드에 「문서 만들기」 화면의
    ``session_guard_for`` 를 실제로 꽂는다(가드 로직만 있고 배선이 빠지면 무의미).

    「기안」 가드는 화면 사망(F6 PR-B)과 함께 걷혔다 — 작업대는 몰입 표면이라 라이브러리와
    동시에 보이지 않고, 진입 자체가 「문서 만들기」 세션을 지난다(app.py 배선 주석과 쌍).
    """
    from hwpxfiller.webapp import app as app_mod

    monkeypatch.setattr(app_mod, "default_jobs_dir", lambda: tmp_path / "jobs")
    frontend = app_mod.WebFrontend()
    library = frontend.controllers["library"]
    assert library.session_guards == [
        frontend.controllers["job"].session_guard_for,
    ]
    # 무장 아닌 상태에선 어떤 가드도 발화하지 않는다(즉시 통과 성질 보존).
    assert all(guard("아무거나") is None for guard in library.session_guards)


def test_delete_job_consults_cross_screen_armed_sessions(tmp_path):
    """#268 리뷰 — 라이브러리 삭제는 작업·기안 화면의 무장 세션을 먼저 묻는다: 세션의 선택·진행은
    파일 복원으로도 못 돌아오는 소실이라, 무확인 즉시 삭제는 그 화면 복귀 시 무확인 세션
    소거로 이어진다. 무장이면 needs_confirm(무변이), confirm 재호출로만 통과."""
    ctrl, _ = _controller(tmp_path)
    ctrl.session_guards = [
        lambda name: {"screen": "job", "armed": True, "sel_count": 2}
        if name == "낙찰" else None
    ]
    res = ctrl.dispatch("delete_job", {"name": "낙찰"})
    assert res["needs_confirm"] is True and res["open_session"] is True
    assert res["screen"] == "job"
    assert ctrl._job_registry.exists("낙찰")  # 무변이 재진술
    confirmed = ctrl.dispatch("delete_job", {"name": "낙찰", "confirm": True})
    assert confirmed == {"ok": True, "undo": True, "name": "낙찰"}
    assert not ctrl._job_registry.exists("낙찰")
    # 무관 작업(가드 None)은 사전 확인 없이 휴지통 관용에 맡긴다.
    res2 = ctrl.dispatch("delete_job", {"name": "공고서"})
    assert res2["undo"] is True


def test_delete_job_can_restore_last_slot(tmp_path):
    ctrl, _ = _controller(tmp_path)
    assert ctrl.dispatch("undo_delete_job", {}) == {
        "ok": False, "error": "복원할 최근 작업이 없습니다."
    }
    result = ctrl.dispatch("delete_job", {"name": "낙찰"})
    assert result == {"ok": True, "undo": True, "name": "낙찰"}
    assert not ctrl._job_registry.exists("낙찰")
    restored = ctrl.dispatch("undo_delete_job", {})
    assert restored == {"ok": True, "name": "낙찰"}
    assert ctrl._job_registry.exists("낙찰")


def test_unknown_library_action_is_loud(tmp_path):
    ctrl, _ = _controller(tmp_path)
    with pytest.raises(ValueError, match="알 수 없는 library 액션"):
        ctrl.dispatch("frobnicate", {})


def _corrupt_file(tmp_path) -> "tuple[LibraryController, str]":
    """레지스트리에 손상 .job.json 을 심고 컨트롤러와 그 경로를 돌려준다."""
    bad = tmp_path / "jobs" / "깨진작업.job.json"
    bad.write_text("{ 이건 json 아님", encoding="utf-8")
    pushes: list = []
    ctrl = LibraryController(JobRegistry(tmp_path / "jobs"), _text_reg(tmp_path),
                          lambda s, snap: pushes.append((s, snap)),
                          engine=make_hwpx_engine(),
                          pool_registry=_pool(tmp_path),
                          generation_lock=threading.Lock(),
                          **_detail_deps(tmp_path))
    rows = ctrl.snapshot()["corrupt_rows"]
    assert len(rows) == 1 and rows[0]["path"]            # 경로가 조치용으로 노출된다(#8)
    return ctrl, rows[0]["path"]


def test_delete_corrupt_confirm_roundtrip(tmp_path):
    """손상 파일 삭제(#8) — 1차=재진술, 2차 확정=삭제·목록 갱신(조용한 삭제 금지)."""
    (tmp_path / "jobs").mkdir()
    ctrl, path = _corrupt_file(tmp_path)
    res = ctrl.dispatch("delete_corrupt", {"path": path})
    assert res["needs_confirm"] is True and "복구 불가" in res["confirm_text"]
    assert ctrl.snapshot()["corrupt_rows"]               # 아직 안 지워짐
    res2 = ctrl.dispatch("delete_corrupt", {"path": path, "confirm": True})
    assert res2["ok"] is True
    assert ctrl.snapshot()["corrupt_rows"] == []         # 해소 + 갱신


def test_corrupt_actions_reject_foreign_paths(tmp_path):
    """조치 경로는 손상 목록 화이트리스트만 — 웹 페이로드의 임의 경로 삭제 봉쇄."""
    (tmp_path / "jobs").mkdir()
    ctrl, _path = _corrupt_file(tmp_path)
    victim = tmp_path / "무관파일.txt"
    victim.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="목록에 없는"):
        ctrl.dispatch("delete_corrupt", {"path": str(victim), "confirm": True})
    assert victim.exists()                               # 무손상


# ------------------------------------------------- 템플릿 다시 연결(#67)
def test_relink_template_commits_and_refreshes(tmp_path):
    """상세 재연결 — 「문서 만들기」와 공유하는 게이트로 커밋 후 경보·행이 최신화된다(#67)."""
    from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
    from hwpxfiller.external.hwpx_package_io import write_hwpx_package

    ctrl, _ = _controller(tmp_path)
    assert ctrl.snapshot()["alerts"]["missing_template_count"] == 1  # /none/t.hwpx 부재
    tpl = tmp_path / "새템플릿.hwpx"
    body = (
        '<hp:run><hp:ctrl><hp:fieldBegin name="공고명"/></hp:ctrl></hp:run>'
        '<hp:run><hp:t>{{공고명}}</hp:t></hp:run>'
        '<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>'
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p>'
        + body + '</hp:p></hs:sec>'
    ).encode()
    write_hwpx_package(
        tpl,
        HwpxPackage(entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": xml}),
    )

    res = ctrl.dispatch("relink_template", {"name": "공고서", "path": str(tpl)})
    assert res["needs_confirm"] is True                    # 1차 = 재진술 확인
    res = ctrl.dispatch(
        "relink_template", {"name": "공고서", "path": str(tpl), "confirm": True})
    assert res["relinked"] is True and res["restated"]
    snap = ctrl.snapshot()
    assert snap["alerts"]["missing_template_count"] == 0   # 행·경보 최신화(refresh)


def test_relink_cross_media_is_rejected_through_the_library_too(tmp_path):
    """교차 매체 재연결은 이 화면 경유로도 거절된다(§10.16 판정 C).

    게이트는 공유 확정 게이트(`relink_job_template`) 한 곳이다 — 둘째 호출면(라이브러리
    디스패처)이 게이트를 우회하지 않는 것을 가드한다(교차-단위 계약 단일 출처).
    """
    ctrl, _ = _controller(tmp_path)
    txt = tmp_path / "기안.txt"
    txt.write_text("공고: {{공고명}}", encoding="utf-8")
    res = ctrl.dispatch(
        "relink_template", {"name": "공고서", "path": str(txt), "confirm": True})
    assert res["ok"] is False and "삭제하고 새로 만드세요" in res["error"]
    assert ctrl.snapshot()["alerts"]["missing_template_count"] == 1  # durable 불변


# ------------------------------------------------------- 작업 복제(F22)
def test_clone_job_creates_unique_copies_without_history(tmp_path):
    """복제 = 매핑·패턴·태그·기본참조 계승 + 유일 이름 + 실행 이력 미계승(F22).

    공유 베이스 프로파일을 걷어낸 자리의 재사용 동선 — 새 카드 출현이 성공 신호라
    성공 배너 없이 스냅샷 갱신만 한다(정상은 조용히).
    """
    ctrl, pushes = _controller(tmp_path)
    res = ctrl.dispatch("clone_job", {"name": "공고서"})
    assert res["ok"] is True and res["cloned"] == "공고서 (복사본)"

    reg = JobRegistry(tmp_path / "jobs")
    copy = reg.load("공고서 (복사본)")
    original = reg.load("공고서")
    assert copy.mapping.to_dict() == original.mapping.to_dict()   # 매핑 계승
    assert copy.filename_pattern == original.filename_pattern
    assert copy.tags == original.tags
    assert copy.last_run_at == ""                                  # 이력 미계승(위조 금지)
    assert original.last_run_at == "2026-07-09T15:42:00"           # 원본 불변
    # dispatch 말미 푸시 스냅샷에 새 카드가 실린다(성공 배너 대신 목록 출현).
    assert "공고서 (복사본)" in _rows(pushes[-1][1])
    assert ctrl.dispatch("clone_job", {"name": "공고서"})["cloned"] == "공고서 (복사본 2)"
    assert ctrl.dispatch("clone_job", {"name": "공고서"})["cloned"] == "공고서 (복사본 3)"


def test_clone_missing_job_is_loud(tmp_path):
    """원본 부재 복제는 조용한 무반응 대신 오류 dict 재진술(웹이 alert)."""
    ctrl, _ = _controller(tmp_path)
    res = ctrl.dispatch("clone_job", {"name": "없는작업"})
    assert res["ok"] is False and "복제할 수 없습니다" in res["error"]


# ------------------------------------------------- 전역 라이브러리 축·상세(§19.6·§19.7)
def test_actions_switch_view_mode_and_query_independently(tmp_path):
    """보기·방식·검색은 서로 다른 축이라 하나를 바꿔도 나머지가 살아 있다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.vm.registry.set_favorite("낙찰", True, "2026-07-20T09:00:00")
    ctrl.dispatch("refresh", {})
    ctrl.dispatch("set_view", {"view": "favorites"})
    ctrl.dispatch("set_query", {"text": "낙찰"})
    snap = ctrl.snapshot()
    assert snap["view"] == "favorites" and snap["query"] == "낙찰"
    assert list(_rows(snap)) == ["낙찰"]

    ctrl.dispatch("set_mode", {"mode": "txt"})
    snap = ctrl.snapshot()
    assert snap["mode"] == "txt" and snap["view"] == "favorites"   # 축 독립
    assert snap["query"] == "낙찰"
    assert _rows(snap) == {}


def test_clear_filters_is_the_resident_exit_from_zero_results(tmp_path):
    """0건 화면의 상주 출구 — 세 절단자(보기·방식·검색)를 한 번에 걷는다(§8.4 도달성).

    넷째였던 태그 facet 은 U4 §2-30 에서 표면과 함께 사라졌다.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("set_view", {"view": "favorites"})
    ctrl.dispatch("set_mode", {"mode": "txt"})
    ctrl.dispatch("set_query", {"text": "없는이름"})
    assert _rows(ctrl.snapshot()) == {}
    ctrl.dispatch("clear_filters", {})
    snap = ctrl.snapshot()
    assert (snap["view"], snap["mode"], snap["query"]) == ("all", "all", "")
    assert "facets" not in snap
    assert set(_rows(snap)) == {"공고서", "낙찰"}


def test_favorite_toggle_takes_the_intended_state(tmp_path):
    """값은 표면이 보내는 **의도한 상태**다 — 백엔드가 뒤집으면 빠른 2연타가 서로를 되돌린다."""
    ctrl, _ = _controller(tmp_path)
    assert ctrl.dispatch("toggle_favorite", {"name": "낙찰", "value": True}) == {"ok": True}
    assert _rows(ctrl.snapshot())["낙찰"]["favorited"] is True
    ctrl.dispatch("toggle_favorite", {"name": "낙찰", "value": True})   # 멱등
    assert _rows(ctrl.snapshot())["낙찰"]["favorited"] is True
    res = ctrl.dispatch("toggle_favorite", {"name": "없는작업", "value": True})
    assert res["ok"] is False and "즐겨찾기를 바꾸지 못했습니다" in res["error"]


def test_list_rows_say_which_jobs_need_a_data_connection(tmp_path):
    """목록 행은 데이터 결속의 **유무**를 말한다(U4 §2.4 · #932 U4-C).

    행에 라벨까지 싣지 않는 이유는 행의 일이 「조치가 필요한가」이기 때문이다 — 템플릿
    축이 `template_missing` 한 비트로 말하는 것과 같은 결이고, 정체는 상세가 진다.

    이 비트가 없으면 U4-C 마이그레이션 상태는 **작업을 하나씩 눌러 봐야** 보인다:
    「문서 만들기」에서 골랐을 때의 통지가 유일한 표면이 된다. 목록이 먼저 말한다.
    """
    ctrl, _ = _controller(tmp_path)
    rows = {
        r["name"]: r
        for sec in ctrl.snapshot()["sections"] for r in sec["rows"]
    }
    assert rows["공고서"]["data_bound"] is True
    assert rows["낙찰"]["data_bound"] is False       # 결속 없는 구판 작업
    # 행은 라벨을 지지 않는다 — 정체를 두 자리가 말하면 한쪽이 늙는다.
    assert "data_label" not in rows["공고서"]


def test_detail_of_an_unbound_job_states_the_gap_instead_of_a_blank(tmp_path):
    """미결속 작업의 상세는 **빈칸이 아니라 사실**을 낸다.

    빈 라벨은 「아직 못 읽었다」와 구별되지 않는다 — 표면이 「연결 필요」를 그릴 수 있게
    유무를 따로 싣는다(문안·동사는 웹, 판정은 여기).
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_work", {"name": "낙찰"})
    d = ctrl.snapshot()["detail"]
    assert d["data_bound"] is False and d["data_label"] == "" and d["data_path"] == ""


def test_detail_carries_every_health_cause_and_never_the_old_binding_chain(tmp_path):
    """§19.7 "상세에서 모든 실제 원인" + 옛 `detail.bindings` 사슬은 되살아나지 않는다.

    **U6-F(#980)에서 뒤집은 단언**: 종전 이 시험은 「상세는 매핑 사본을 싣지 않는다」였다.
    #966 이 걷은 것은 정보가 아니라 **별도 라벨 사전을 든 payload 사슬**이었고, U6-F 가
    다시 세운 표는 편집기 2단계와 **같은 링1 투영**(`row_projection`)·같은 라벨 상수를
    두 번째 호스트가 소비하는 것이라 「같은 상태를 두 곳이 판정」이 아니다. 그래서 남는
    금지는 하나다 — 키 이름 `bindings` 는 되살리지 않는다(옛 사슬과 구별되지 않는다).
    TXT 「실행 방식」 문구는 그대로 걷혀 있고(부제가 이미 말한다), 판본 열은 F7 까지 만들지
    않는다(판정 D).
    """
    ctrl, _ = _controller(tmp_path)
    assert ctrl.snapshot()["detail"] is None
    ctrl.dispatch("select_work", {"name": "공고서"})
    d = ctrl.snapshot()["detail"]
    assert d["name"] == "공고서" and d["mode_label"] == "HWPX 문서 생성"
    causes = [c["text"] for c in d["health_causes"]]
    # 목록 배지는 최고 심각도 1건이지만 상세는 두 계보를 함께 본다.
    assert "템플릿 파일을 찾을 수 없습니다." in causes
    assert "파일명 패턴의 토큰을 채우지 못합니다." in causes
    assert "filename_pattern" not in d                  # 규칙은 계획 존으로 내려갔다
    # 걷힌 축은 빈 값이 아니라 **부재**다 — 빈 값을 남기면 표면이 자리를 다시 그리는 미끼다.
    assert "bindings" not in d                          # 옛 사슬의 키는 되살리지 않는다
    # 새 존은 이름이 다르고, 이 표본은 템플릿이 부재라 표를 그리지 않는다(카드만 남는다).
    assert d["pairing_detail"]["rows"] == []
    assert "run_note" not in d
    assert "last_run_display" not in d
    assert "revision" not in d                          # 판본은 F7 — 빈 자리도 두지 않는다
    # 템플릿 전체 경로(U2 §2.20, #342) — 상세 「열기」·「폴더에서 보기」가 겨눌 값. 경보
    # (템플릿 미연결)는 이 화면이 내는데 조작이 여기 없었다 — payload 한 칸이 그 선행이다.
    assert d["template_path"] == "/none/t.hwpx"
    # 데이터 축도 템플릿 옆에서 말한다(#932 U4-C) — 라벨 성형은 링0 단일 출처라
    # 표면이 basename·시트 표기를 짓지 않는다.
    assert d["data_bound"] is True
    assert d["data_label"] == "월별.xlsx · 낙찰현황"
    assert d["data_path"] == "/data/월별.xlsx"
    ctrl.dispatch("select_work", {"name": ""})          # 선택 해제
    assert ctrl.snapshot()["detail"] is None


def test_detail_survives_being_filtered_out_of_the_list(tmp_path):
    """리뷰 1R P1 의 백엔드 전제 — 상세는 걸러지지 않은 rows() 에서 성형된다.

    선택 행이 검색 밖으로 밀려나도 상세는 그대로 산다. 표면의 관리 동사가 여기서 정체를
    읽어야 하는 근거다(태그는 U4 §2-30 에서 상세에서도 걷혔다).
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_work", {"name": "공고서"})
    ctrl.dispatch("set_query", {"text": "낙찰"})       # 선택 행이 목록에서 사라진다
    snap = ctrl.snapshot()
    assert "공고서" not in _rows(snap)
    assert snap["detail"]["name"] == "공고서"
    assert "tags" not in snap["detail"]


def test_refresh_can_carry_the_selection_to_a_renamed_work(tmp_path):
    """리뷰 2R — 이름이 바뀐 작업의 선택을 승계한다. 없는 이름은 조용히 무시."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_work", {"name": "공고서"})
    ctrl._job_registry.rename("공고서", "공고서 v2")
    # 승계 없이 새로고침하면 선택이 옛 이름에 남아 상세가 닫힌다(회귀의 증상).
    ctrl.dispatch("refresh", {})
    assert ctrl.snapshot()["detail"] is None

    ctrl.dispatch("select_work", {"name": "공고서"})
    ctrl.dispatch("refresh", {"select": "공고서 v2"})
    snap = ctrl.snapshot()
    assert snap["selected"] == "공고서 v2" and snap["detail"]["name"] == "공고서 v2"

    # 경합으로 그사이 사라진 이름은 선택을 옮기지 않는다(유령을 겨누지 않는다).
    ctrl.dispatch("refresh", {"select": "없는작업"})
    assert ctrl.snapshot()["selected"] == "공고서 v2"


def test_txt_work_joins_the_document_picker(tmp_path):
    """F6 합류 — TXT 작업은 「문서 만들기」 후보에 **든다**(지도 §10.15 판정 B).

    이 테스트는 뒤집힌 것이다: F6 이전 판본은 "TXT 는 후보에서 배제된다"를 단언하면서
    「이 전제가 바뀌면 시끄럽게 알린다」고 적어 뒀고, 실제로 매체 국경을 걷자 울었다.
    남은 단언은 **합류 뒤에도 참이어야 하는 것**들이다: 방식은 라이브러리 필터에 그대로
    보이고(방식 필터의 존재 이유), 후보 판정은 hwpx 와 같은 술어를 탄다.
    """
    from hwpxfiller.gui.work_candidates import rank_available

    txt = tmp_path / "안내문.txt"
    txt.write_text("제목 {{공고명}}", encoding="utf-8")
    reg = _reg(tmp_path)
    reg.save(Job(name="기안문", template_path=str(txt),
                 mapping=MappingProfile(mappings=[
                     FieldMapping(template_field="공고명", source="bidNtceNm")])))
    ranked = {r.name: r for r in rank_available(reg.list_jobs(), ["bidNtceNm"])}
    assert "기안문" in ranked
    assert ranked["기안문"].mode == "text_review_copy"
    # 같은 술어: 필요한 열이 없으면 TXT 도 똑같이 후보에서 빠진다(available 만 순위에 든다).
    assert "기안문" not in {r.name for r in rank_available(reg.list_jobs(), ["다른열"])}

    # 라이브러리는 그 작업을 **보여준다**(방식 필터의 존재 이유).
    ctrl = LibraryController(reg, _text_reg(tmp_path), lambda s, snap: None,
                          engine=make_hwpx_engine(),
                          pool_registry=_pool(tmp_path),
                          generation_lock=threading.Lock(),
                          **_detail_deps(tmp_path))
    assert _rows(ctrl.snapshot())["기안문"]["media"] == "txt"


# ------------------------------------------------- 주 행동의 목적지(리뷰 3R 근본 조치)
def test_primary_action_never_sends_a_work_the_document_screen_cannot_take(tmp_path):
    """되풀이된 결함류의 구조 차단 — 「문서 만들기」는 **연결된 hwpx·txt** 만 받는다.

    표시용 정규화(`library_mode_of` 는 미연결을 hwpx 로 센다)에서 행동 경로를 파생하면
    `rank_available`(원시 매체)이 배제하는 작업을 그쪽으로 보내게 되고, 이어 여는 「확인
    필요」 탭에서도 배제돼 **빈 화면**에 착지한다. TXT(2R)와 미연결(3R)이 그 두 표본이었다.
    F6 PR-B: 「기안」 승계처(작업대)가 서면서 txt 도 `job` 으로 합쳐졌다 — 매체 분기는
    실행 버튼(판정 D)이 소유하고 목적지 분기는 소멸했다(§10.15.15 점검표 2행).
    """
    from hwpxfiller.gui.work_candidates import rank_available
    from hwpxfiller.webapp.screen_library import primary_action

    txt = tmp_path / "안내문.txt"
    txt.write_text("제목 {{공고명}}", encoding="utf-8")
    reg = JobRegistry(tmp_path / "jobs2")
    reg.save(Job(name="미연결", template_path=""))                     # 저작 중
    reg.save(Job(name="기안문", template_path=str(txt)))               # TXT
    reg.save(Job(name="미상", template_path=str(tmp_path / "x.doc")))  # 지원 안 하는 확장자
    ctrl = LibraryController(reg, _text_reg(tmp_path), lambda s, snap: None,
                          engine=make_hwpx_engine(),
                          pool_registry=_pool(tmp_path),
                          generation_lock=threading.Lock(),
                          **_detail_deps(tmp_path))
    rows = {r.name: r for r in ctrl.vm.rows()}
    targets = {n: primary_action(r)["target"] for n, r in rows.items()}
    assert targets == {"미연결": "editor", "기안문": "job", "미상": "editor"}
    # 라벨은 목적지와 **함께** 온다(표면이 짝을 다시 맞추면 또 갈린다).
    assert primary_action(rows["기안문"])["label"] == "문서 만들기에서 사용"
    assert primary_action(rows["미연결"])["hint"]                       # 왜 그쪽인지 말한다

    # 불변식: **목적지는 그 작업을 실제로 받을 수 있어야 한다.** `job` 으로 가는 것은
    # 후보 자격이 있어야 하고, 「편집기」로 가는 것들(미연결·미상)은 자격이 없어야 한다.
    fields = ["공고명"]
    ranked = {r.name for r in rank_available(reg.list_jobs(), fields)}
    for name, target in targets.items():
        if target == "job":
            assert name in ranked or rows[name].media == "hwpx"
        else:
            assert name not in ranked, f"{name} → {target}"


def test_detail_carries_the_primary_action(tmp_path):
    """상세 페이로드가 목적지·라벨을 싣는다 — 표면은 그것을 그대로 쓴다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_work", {"name": "공고서"})
    primary = ctrl.snapshot()["detail"]["primary"]
    assert primary["target"] == "job" and primary["label"] == "문서 만들기에서 사용"


# ── 상세 연결 존(U6-F #980 · §2.6) ─────────────────────────────────────────────
# #966 이 걷은 것은 **별도 라벨 사전을 든 payload 사슬**(`detail.bindings`)이었지 정보
# 자체가 아니었다. 여기서 재는 것은 그 사슬이 돌아오지 않았다는 사실이다: 행은 편집기와
# 같은 링1 투영이고 라벨도 그 한 자리에서 오며, 키 이름은 `pairing_detail` 이다.


def _hwpx_template(path, fields) -> None:
    """누름틀만 든 최소 HWPX — 변환이 끝난 템플릿의 형상."""
    body = "".join(
        f'<hp:run><hp:ctrl><hp:fieldBegin name="{n}"/></hp:ctrl></hp:run>'
        f'<hp:run><hp:t>{{{{{n}}}}}</hp:t></hp:run>'
        '<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>'
        for n in fields
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p>'
        + body + "</hp:p></hs:sec>"
    ).encode()
    write_hwpx_package(
        path,
        HwpxPackage(entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": xml}),
    )


def _bound_registry(tmp_path, *, fields=("공고번호", "사업명", "금액"), rows=2,
                    data_name="계약.csv", extra_mapping=(),
                    mapping_fields=None) -> "tuple[JobRegistry, str]":
    """템플릿·데이터가 실제로 서 있는 작업 하나 — 상세 존을 재는 표본."""
    tpl_dir = tmp_path / "templates"
    tpl_dir.mkdir(exist_ok=True)
    tpl = tpl_dir / "공고서.hwpx"
    _hwpx_template(tpl, list(fields))
    data = tmp_path / data_name
    header = ",".join(fields)
    body = "\n".join(
        ",".join(f"{f}-{i}" for f in fields) for i in range(1, rows + 1)
    )
    data.write_text(f"{header}\n{body}\n", encoding="utf-8-sig")
    reg = JobRegistry(tmp_path / "bound")
    reg.save(Job(
        name="공고서 작업", template_path=str(tpl),
        mapping=MappingProfile(mappings=[
            *(FieldMapping(template_field=f, source=f)
              for f in (fields if mapping_fields is None else mapping_fields)),
            *extra_mapping,
        ]),
        filename_pattern="공고-{{공고번호}}-{{seq:001}}",
        data_path=str(data), data_sheet="",
    ))
    return reg, str(data)


def test_pairing_detail_draws_the_card_table_and_plan_from_one_ring1_projection(tmp_path):
    """상세 하단은 연결 카드 + 읽기 전용 4열 표 + 계획 한 줄이다(U6-F #980 · §2.6).

    행은 편집기 2단계와 **같은 투영**(`row_projection`)이고 두 읽기 전용 칸의 문안도 링1
    조회다 — 웹이 라벨 표를 한 벌 더 들면 #966 이 걷은 사슬이 이름만 바꿔 돌아온다.
    """
    reg, _ = _bound_registry(tmp_path)
    ctrl, _ = _controller(tmp_path, registry=reg)
    ctrl.dispatch("select_work", {"name": "공고서 작업"})
    zone = ctrl.snapshot()["detail"]["pairing_detail"]

    card = zone["card"]
    assert card["template_name"] == "공고서"          # 루트 상대·확장자 없음(U6-A 규칙)
    assert card["data_name"] == "계약"                # 풀 미등록 → 확장자 없는 basename
    assert card["counted"] is True
    assert (card["template_field_count"], card["mapped_count"],
            card["unbound_count"], card["stale_count"]) == (3, 3, 0, 0)

    assert [r["template_field"] for r in zone["rows"]] == ["공고번호", "사업명", "금액"]
    assert [r["source_label"] for r in zone["rows"]] == ["공고번호", "사업명", "금액"]
    assert [r["display_label"] for r in zone["rows"]] == ["원문"] * 3
    assert zone["more_fields"] == []
    # 첫 행은 실제로 읽은 첫 레코드다(전량 읽기라 건수도 함께 온다).
    assert zone["first_row"] == {"state": "ready", "reason": "", "record_count": 2}
    assert [r["preview"] for r in zone["rows"]] == ["공고번호-1", "사업명-1", "금액-1"]
    assert all(r["preview_kind"] == "value" for r in zone["rows"])

    # 계획은 **실제 생성기와 같은 함수**가 만든 이름이다(예시가 산출물과 어긋나지 않는다).
    assert zone["plan"] == {
        "state": "ready", "pattern": "공고-{{공고번호}}-{{seq:001}}",
        "first_name": "공고-공고번호-1-001.hwpx", "count": 2}
    # 저장 폴더는 상세에 없다 — 전역 단일 값이라 설정 창이 소유한다(2026-09-03 재판정).
    assert "output_folder" not in zone


def test_pairing_detail_names_the_rows_the_frame_cannot_hold(tmp_path):
    """8행 + 「그 밖에」 이름 명시 — 스크롤로 조용히 감추지 않는다(동결 시안 장면 4)."""
    fields = [f"필드{i}" for i in range(1, 13)]
    reg, _ = _bound_registry(tmp_path, fields=tuple(fields))
    ctrl, _ = _controller(tmp_path, registry=reg)
    ctrl.dispatch("select_work", {"name": "공고서 작업"})
    zone = ctrl.snapshot()["detail"]["pairing_detail"]
    assert len(zone["rows"]) == 8
    assert zone["more_fields"] == fields[8:]
    assert zone["card"]["template_field_count"] == 12


def test_first_row_is_pending_until_the_worker_answers_then_the_whole_snapshot_repushes(tmp_path):
    """선택 직후엔 「아직 모름」, 읽기가 끝나면 **전체 스냅샷**을 다시 민다(U6-F §3).

    부분 dict 델타는 job 채널만 허용한다(런타임 reduce) — 여기서 미는 것은 언제나 온전한
    라이브러리 스냅샷이다.
    """
    reg, _ = _bound_registry(tmp_path)
    pending_work: list = []
    ctrl, pushes = _controller(tmp_path, registry=reg,
                               runner=lambda work: pending_work.append(work))
    ctrl.dispatch("select_work", {"name": "공고서 작업"})

    assert len(pushes) == 1
    zone = pushes[0][1]["detail"]["pairing_detail"]
    assert zone["first_row"] == {"state": "pending", "reason": "", "record_count": 0}
    assert [r["preview"] for r in zone["rows"]] == ["—", "—", "—"]
    assert all(r["preview_kind"] == "pending" for r in zone["rows"])
    # 아직 못 읽었어도 저장본만으로 그려지는 축은 이미 서 있다(빈 패널을 보이지 않는다).
    assert zone["card"]["mapped_count"] == 3
    assert zone["plan"] == {
        "state": "pending", "pattern": "공고-{{공고번호}}-{{seq:001}}",
        "first_name": "", "count": 0}

    pending_work.pop()()                                   # 워커가 끝난 순간
    assert len(pushes) == 2 and pushes[1][0] == "library"
    ready = pushes[1][1]["detail"]["pairing_detail"]
    assert ready["first_row"]["state"] == "ready"
    assert ready["rows"][0]["preview"] == "공고번호-1"
    # 전체 스냅샷이다 — 목록·필터 축이 함께 실려 온다(부분 dict 금지).
    assert set(pushes[1][1]) >= {"sections", "counts", "view", "detail"}


def test_a_late_first_row_read_lands_in_the_cache_but_never_on_another_selection(tmp_path):
    """늦게 끝난 읽기는 **상관 키 대조** 뒤에만 화면에 선다(`run_token` 규율 선례).

    그사이 다른 행을 골랐으면 결과는 캐시에만 들어가고, 그 행을 다시 고르는 순간 캐시
    히트로 즉시 선다 — 다시 읽지 않는다(러너가 한 번도 더 불리지 않는 것이 그 증거다).
    """
    reg, _ = _bound_registry(tmp_path)
    reg.save(Job(name="다른작업", template_path=""))
    started: list = []
    ctrl, pushes = _controller(tmp_path, registry=reg, runner=lambda w: started.append(w))
    ctrl.dispatch("select_work", {"name": "공고서 작업"})
    ctrl.dispatch("select_work", {"name": "다른작업"})       # 겨눔이 바뀐다
    before = len(pushes)

    started.pop()()                                          # 뒤늦게 끝난 앞 선택의 읽기
    assert len(pushes) == before, "다른 행을 겨눈 화면에 옛 답을 밀었다"

    ctrl.dispatch("select_work", {"name": "공고서 작업"})     # 다시 고르면 캐시 히트
    assert started == [], "캐시가 있는데 다시 읽었다"
    assert pushes[-1][1]["detail"]["pairing_detail"]["first_row"]["state"] == "ready"


def test_first_row_failure_states_the_reason_in_place(tmp_path):
    """읽기 실패는 조용한 빈칸이 아니라 사유다 — 건강 원인과는 **섞지 않는다**(§19.7)."""
    reg, data = _bound_registry(tmp_path)
    Path(data).unlink()
    ctrl, _ = _controller(tmp_path, registry=reg)
    ctrl.dispatch("select_work", {"name": "공고서 작업"})
    detail = ctrl.snapshot()["detail"]
    zone = detail["pairing_detail"]
    assert zone["first_row"]["state"] == "error"
    assert zone["first_row"]["reason"] == f"경로를 찾을 수 없음: {data}"
    assert all(r["preview_kind"] == "error" for r in zone["rows"])
    assert zone["plan"]["state"] == "error" and zone["plan"]["first_name"] == ""
    # 호환성·건강 축은 이 실패를 모른다(상세 판정과 분리 — §19.7 명문).
    assert all("찾을 수 없음" not in c["text"] for c in detail["health_causes"])


def test_an_unbound_job_says_why_the_first_row_is_empty(tmp_path):
    """결속이 없으면 첫 행 자리에 **사유**가 선다(빈칸은 「아직 못 읽었다」와 구별되지 않는다)."""
    reg, _ = _bound_registry(tmp_path)
    job = reg.load("공고서 작업")
    reg.save(Job(
        name=job.name, template_path=job.template_path, mapping=job.mapping,
        filename_pattern=job.filename_pattern,
    ))
    started: list = []
    ctrl, _ = _controller(tmp_path, registry=reg, runner=lambda w: started.append(w))
    ctrl.dispatch("select_work", {"name": "공고서 작업"})
    zone = ctrl.snapshot()["detail"]["pairing_detail"]
    assert zone["first_row"]["reason"] == UNBOUND_FIRST_ROW_REASON
    # 결속 유무는 상세가 이미 든 사실이다 — 카드가 사본을 만들지 않는다.
    assert ctrl.snapshot()["detail"]["data_bound"] is False
    assert started == [], "읽을 참조가 없는데 워커를 띄웠다"


def test_an_unreadable_template_keeps_the_card_but_draws_no_table(tmp_path):
    """정체(카드)는 남고 구조(표)는 서지 않는다 — 답하는 질문이 다르기 때문이다.

    카드가 정체를 **바꾸러 가는 동사**(재선택)를 들고 있어서, 템플릿이 사라진 갈래에서
    카드를 접으면 고치러 갈 길이 함께 접힌다. 반대로 표는 현재 템플릿과의 대칭차 없이는
    「확인 필요 k」를 말할 수 없으므로 빈 행 목록으로 서지 않고, 세지 않았다는 사실을
    `counted` 가 말한다(0 을 사실처럼 말하지 않는다).
    """
    ctrl, _ = _controller(tmp_path)                          # 기본 표본: 템플릿 부재·미연결
    for name, bound in (("공고서", True), ("낙찰", False)):
        ctrl.dispatch("select_work", {"name": name})
        zone = ctrl.snapshot()["detail"]["pairing_detail"]
        assert zone["rows"] == [] and zone["more_fields"] == []
        assert zone["first_row"] is None and zone["plan"] is None
        assert "output_folder" not in zone
        assert zone["card"]["counted"] is False
        assert zone["card"]["template_bound"] is bound       # 부재와 미연결은 다른 상태다
    assert ctrl.snapshot()["detail"]["pairing_detail"]["card"]["template_name"] == ""


def test_txt_work_has_no_file_plan(tmp_path):
    """TXT 복사 작업은 파일을 만들지 않는다 — 계획도 저장 폴더도 세우지 않는다.

    만들지 않을 파일의 이름과 저장 위치를 말하는 것이 곧 조용한 거짓말이다(§ 「저장 폴더 —
    전역 단일 값」의 표와 같은 판정). 표 자체는 선다: 결속과 첫 행은 TXT 에도 있다.
    """
    txt = tmp_path / "기안.txt"
    txt.write_text("제목: {{사업명}}", encoding="utf-8")
    data = tmp_path / "계약.csv"
    data.write_text("사업명\n청사 냉난방\n", encoding="utf-8-sig")
    reg = JobRegistry(tmp_path / "txtjobs")
    reg.save(Job(
        name="기안 작업", template_path=str(txt),
        mapping=MappingProfile(mappings=[FieldMapping("사업명", "사업명")]),
        data_path=str(data), data_sheet="",
    ))
    ctrl, _ = _controller(tmp_path, registry=reg)
    ctrl.dispatch("select_work", {"name": "기안 작업"})
    zone = ctrl.snapshot()["detail"]["pairing_detail"]
    assert zone["plan"] is None and "output_folder" not in zone
    assert zone["card"]["counted"] is False                  # hwpx 대칭차가 없는 갈래
    assert zone["rows"][0]["preview"] == "청사 냉난방"


def test_selecting_a_work_never_mounts_data_into_another_screen(tmp_path):
    """「선택 ≠ 착석」 불변(§19.6 서문)은 지연 읽기가 생겨도 그대로다.

    상세가 데이터를 읽는 것은 **표의 한 칸**을 채우려는 것이고, 그 읽기는 자기 캐시에만
    남는다. 이 컨트롤러는 다른 화면의 마운트 경로를 부르지 않고 자기 채널만 민다.
    """
    reg, _ = _bound_registry(tmp_path)
    ctrl, pushes = _controller(tmp_path, registry=reg)
    ctrl.dispatch("select_work", {"name": "공고서 작업"})
    assert {screen for screen, _ in pushes} == {"library"}
    source = Path("src/hwpxfiller/webapp/screen_library.py").read_text(encoding="utf-8")
    for mount in ("load_data_path(", "_adopt_datasource(", "new_work_handoff("):
        assert mount not in source, f"상세가 다른 화면의 마운트 경로를 재사용한다: {mount}"


def test_renaming_the_selected_work_restarts_the_first_row_read(tmp_path):
    """이름 변경의 착지(`refresh(select=…)`)도 겨눔을 바꾼다 — 읽기를 다시 건다.

    상관 키에 작업 이름이 들어 있으므로 개명 뒤에는 캐시가 미스다. 여기서 읽기를 다시 걸지
    않으면 그 상세는 영영 「아직 모름」에 머문다(사라진 데이터가 아니라 우리가 안 물은 것).
    """
    reg, _ = _bound_registry(tmp_path)
    ctrl, _ = _controller(tmp_path, registry=reg)
    ctrl.dispatch("select_work", {"name": "공고서 작업"})
    job = reg.load("공고서 작업")
    reg.save(Job(
        name="새 이름", template_path=job.template_path, mapping=job.mapping,
        filename_pattern=job.filename_pattern,
        data_path=job.data_path, data_sheet=job.data_sheet,
    ))
    ctrl.dispatch("refresh", {"select": "새 이름"})
    zone = ctrl.snapshot()["detail"]["pairing_detail"]
    assert zone["first_row"]["state"] == "ready"


# ── U6-F 리뷰 회수(#990) ───────────────────────────────────────────────────────

def test_table_and_card_speak_of_the_same_field_set(tmp_path):
    """표의 행은 **템플릿 누름틀**에서 서고 저장 매핑을 얹는다(리뷰 1 · 편집기와 같은 규칙).

    저장 프로파일만으로 행을 세우면 표가 카드와 다른 집합을 말한다: 매핑 안 된 템플릿
    필드(카드의 「확인 필요 k」)는 행이 아예 없고, 템플릿에서 사라진 옛 연결은 템플릿
    필드인 척 선다. 소멸분은 표 밖에서 **이름으로** 말한다.
    """
    reg, _ = _bound_registry(
        tmp_path, fields=("공고번호", "사업명", "금액"),
        # 저장 매핑은 셋 중 둘만 덮고, 대신 템플릿에 없는 옛 연결 하나를 든다.
        mapping_fields=("공고번호", "사업명"),
        extra_mapping=(FieldMapping(template_field="옛필드", source="사업명"),),
    )
    ctrl, _ = _controller(tmp_path, registry=reg)
    ctrl.dispatch("select_work", {"name": "공고서 작업"})
    zone = ctrl.snapshot()["detail"]["pairing_detail"]

    assert zone["rows_basis"] == "template"
    # 미커버 필드도 **행으로** 선다 — 클릭 한 번으로 편집기의 그 행에 갈 수 있어야 한다.
    assert [r["template_field"] for r in zone["rows"]] == ["공고번호", "사업명", "금액"]
    assert zone["rows"][2]["row_state"] == "needs_source"
    assert zone["rows"][2]["state_label"] == "확인 필요"
    assert zone["rows"][0]["row_state"] == "confirmed"
    # 표에 섞이지 않고 밖에서 이름을 말한다(숨기지 않는다).
    assert zone["stale_fields"] == ["옛필드"]
    assert "옛필드" not in [r["template_field"] for r in zone["rows"]]
    # 카드 수치와 표의 집합이 같은 사실을 말한다.
    card = zone["card"]
    assert (card["template_field_count"], card["mapped_count"],
            card["unbound_count"], card["stale_count"]) == (3, 2, 1, 1)


def test_an_unreadable_template_falls_back_to_the_saved_bindings_and_says_so(tmp_path):
    """템플릿을 못 읽으면 저장된 연결만 그리고 **그 사실을 명시**한다(리뷰 1·4·5).

    수치는 세지 않았다고 말한다 — `read_error` 갈래의 대칭차는 전부 비어 있어서, 그 위에
    카드를 세우면 「연결 n / n · 확인 필요 0」을 지어낸다.
    """
    reg, _ = _bound_registry(tmp_path)
    job = reg.load("공고서 작업")
    broken = tmp_path / "templates" / "깨진.hwpx"
    broken.write_bytes(b"not a zip")                  # 존재하지만 열 수 없다
    reg.save(Job(
        name=job.name, template_path=str(broken), mapping=job.mapping,
        filename_pattern=job.filename_pattern,
        data_path=job.data_path, data_sheet=job.data_sheet,
    ))
    ctrl, _ = _controller(tmp_path, registry=reg)
    ctrl.dispatch("select_work", {"name": "공고서 작업"})
    zone = ctrl.snapshot()["detail"]["pairing_detail"]
    assert zone["rows_basis"] == "profile"
    assert [r["template_field"] for r in zone["rows"]] == ["공고번호", "사업명", "금액"]
    assert zone["card"]["counted"] is False
    assert zone["card"]["template_field_count"] == 0


def test_the_read_starts_from_the_snapshot_not_from_one_action(tmp_path):
    """읽기 시작 판정은 **스냅샷 산출 하나**다(리뷰 2).

    핸들러마다 시작을 걸면 상태를 바꾸는 경로가 늘 때(다시 연결·복원·복제) 그 자리를 하나씩
    더 기억해야 한다. 여기서는 `select_work` 를 한 번도 쓰지 않고 겨눔만 세운다.
    """
    reg, _ = _bound_registry(tmp_path)
    ctrl, _ = _controller(tmp_path, registry=reg)
    ctrl.dispatch("refresh", {"select": "공고서 작업"})
    assert ctrl.snapshot()["detail"]["pairing_detail"]["first_row"]["state"] == "ready"


@pytest.mark.parametrize("verb", ["relink_template", "undo_delete_job", "clone_job"])
def test_state_changing_verbs_never_strand_the_panel_in_pending(tmp_path, verb):
    """다시 연결·복원·복제 뒤에도 첫 행이 채워진다 — 어느 경로든 다음 스냅샷이 알아챈다."""
    reg, _ = _bound_registry(tmp_path)
    ctrl, _ = _controller(tmp_path, registry=reg)
    ctrl.dispatch("select_work", {"name": "공고서 작업"})
    if verb == "relink_template":
        other = tmp_path / "templates" / "다른.hwpx"
        _hwpx_template(other, ["공고번호", "사업명", "금액"])
        ctrl.dispatch(verb, {"name": "공고서 작업", "path": str(other), "confirm": True})
        target = "공고서 작업"
    elif verb == "undo_delete_job":
        ctrl.dispatch("delete_job", {"name": "공고서 작업", "confirm": True})
        ctrl.dispatch(verb, {})
        ctrl.dispatch("refresh", {"select": "공고서 작업"})
        target = "공고서 작업"
    else:
        cloned = ctrl.dispatch(verb, {"name": "공고서 작업"})["cloned"]
        # 복제본은 **이름이 달라** 캐시가 차갑다 — 시작 판정이 선택 동사 밖에도 산다는 증거다.
        ctrl.dispatch("refresh", {"select": cloned})
        target = cloned
    zone = ctrl.snapshot()["detail"]["pairing_detail"]
    assert ctrl.snapshot()["detail"]["name"] == target
    assert zone["first_row"]["state"] == "ready", zone["first_row"]


def test_a_changed_data_file_is_read_again(tmp_path):
    """캐시 키의 **파일 지문**이 낡음을 구조적으로 막는다(리뷰 3b).

    참조가 그대로여도 사람이 엑셀을 고쳐 저장하면 첫 행이 달라진다 — 지문이 없으면 상세는
    앱을 다시 켤 때까지 옛 값을 말한다.
    """
    reg, data = _bound_registry(tmp_path)
    ctrl, _ = _controller(tmp_path, registry=reg)
    ctrl.dispatch("select_work", {"name": "공고서 작업"})
    assert ctrl.snapshot()["detail"]["pairing_detail"]["rows"][0]["preview"] == "공고번호-1"

    path = Path(data)
    path.write_text("공고번호,사업명,금액\n바뀐값,B,C\n", encoding="utf-8-sig")
    stamp = path.stat()
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000_000))
    assert ctrl.snapshot()["detail"]["pairing_detail"]["rows"][0]["preview"] == "바뀐값"


def test_a_failed_read_is_retried_on_the_next_explicit_selection(tmp_path):
    """실패는 캐시에 남되(스냅샷 무한 재시도 금지) 명시 선택이 그것을 걷는다(리뷰 3a)."""
    reg, data = _bound_registry(tmp_path)
    Path(data).unlink()
    reads: list = []
    ctrl, _ = _controller(tmp_path, registry=reg,
                          runner=lambda work: (reads.append(1), work()))
    ctrl.dispatch("select_work", {"name": "공고서 작업"})
    assert ctrl.snapshot()["detail"]["pairing_detail"]["first_row"]["state"] == "error"
    ctrl.snapshot(); ctrl.snapshot()
    assert len(reads) == 1, "스냅샷이 실패를 무한히 재시도한다"

    Path(data).write_text("공고번호,사업명,금액\n다시,B,C\n", encoding="utf-8-sig")
    ctrl.dispatch("select_work", {"name": "공고서 작업"})   # 사람이 다시 누른다 = 다시 읽어라
    assert ctrl.snapshot()["detail"]["pairing_detail"]["first_row"]["state"] == "ready"


def test_one_binding_is_never_read_by_two_workers_at_once(tmp_path):
    """진행 중 집합이 중복 기동을 막는다(리뷰 6) — 같은 작업 재선택·재렌더가 겹쳐 뜨지 않는다."""
    reg, _ = _bound_registry(tmp_path)
    started: list = []
    ctrl, _ = _controller(tmp_path, registry=reg, runner=lambda w: started.append(w))
    ctrl.dispatch("select_work", {"name": "공고서 작업"})
    ctrl.dispatch("select_work", {"name": "공고서 작업"})
    ctrl.snapshot()
    assert len(started) == 1, "같은 결속에 워커가 겹쳐 떴다"
    started.pop()()
    assert ctrl.snapshot()["detail"]["pairing_detail"]["first_row"]["state"] == "ready"


def test_the_zone_is_not_rebuilt_while_nothing_it_reads_has_changed(tmp_path):
    """검색 한 글자마다 전 행 투영·폴더 stat 을 다시 지불하지 않는다(리뷰 9).

    memo 의 안전 조건은 **키가 존의 재료를 빠짐없이 덮는가**이므로, 재료가 바뀌면 결과도
    바뀌는 쪽을 함께 잰다.
    """
    reg, _ = _bound_registry(tmp_path)
    ctrl, _ = _controller(tmp_path, registry=reg)
    ctrl.dispatch("select_work", {"name": "공고서 작업"})
    first = ctrl.snapshot()["detail"]["pairing_detail"]
    assert ctrl.snapshot()["detail"]["pairing_detail"] is first     # 재료 불변 = 같은 값
    ctrl.dispatch("set_query", {"text": "공"})
    assert ctrl.snapshot()["detail"]["pairing_detail"] is first

    job = reg.load("공고서 작업")
    reg.save(Job(
        name=job.name, template_path=job.template_path,
        mapping=MappingProfile(mappings=[FieldMapping("공고번호", "금액")]),
        filename_pattern=job.filename_pattern,
        data_path=job.data_path, data_sheet=job.data_sheet,
    ))
    ctrl.dispatch("refresh", {})
    rebuilt = ctrl.snapshot()["detail"]["pairing_detail"]
    assert rebuilt is not first
    assert rebuilt["rows"][0]["source"] == "금액"
