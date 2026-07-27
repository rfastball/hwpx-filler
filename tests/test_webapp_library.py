"""「문서 작업」(전역 라이브러리) 컨트롤러 계약 가드 — pywebview/Qt 불필요(헤드리스).

재작성 F2 PR-A 에서 홈 컨트롤러를 승계했다(지도 §10.8). 링1 HomeViewModel 을 그대로
임포트한 컨트롤러가 보기 4종·작업 방식 필터·검색·태그 facet·그룹 구획과 접힘·상세(건강 전
원인·필드 연결)·손상 격리 스냅샷을 창 없이 낸다. 화면 이동(겨눔·전환)은 링2(웹)라 여기서
다루지 않는다.
"""
from __future__ import annotations

import pytest

from hwpxfiller.core.dataset_pool import DatasetPoolRegistry
from hwpxfiller.core.job import Job, JobRegistry
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.core.text_registry import TextTemplateRegistry
from hwpxfiller.webapp.screen_library import LibraryController


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
    ))
    reg.save(Job(
        name="낙찰", template_path="", filename_pattern="낙찰-{{ID}}",
        last_run_at="2026-06-30T11:08:00", tags={"금액구간": "10억이상"},
    ))
    return reg


def _text_reg(tmp_path) -> TextTemplateRegistry:
    d = tmp_path / "txt"
    d.mkdir()
    (d / "온나라_기안.txt").write_text("제목: {{공고명}} 담당 {{담당자}}", encoding="utf-8")
    return TextTemplateRegistry(d)


def _controller(tmp_path) -> "tuple[LibraryController, list]":
    pushes: list = []
    ctrl = LibraryController(_reg(tmp_path), _text_reg(tmp_path),
                          lambda s, snap: pushes.append((s, snap)),
                          pool_registry=_pool(tmp_path))
    return ctrl, pushes


def _rows(snap) -> "dict[str, dict]":
    return {r["name"]: r for sec in snap["sections"] for r in sec["rows"]}


def test_initial_snapshot_carries_axes_and_conditional_alerts(tmp_path):
    """개수 타일(#239 결정 8)은 승계하지 않고, **조치가 필요한 조건**만 경보로 싣는다."""
    ctrl, _ = _controller(tmp_path)
    snap = ctrl.initial()
    assert snap["is_empty"] is False
    assert snap["view"] == "all" and snap["mode"] == "all" and snap["query"] == ""
    assert snap["alerts"]["missing_template_count"] == 1  # /none/t.hwpx 부재
    # 죽은 홈 요약 표면은 스냅샷에서도 사라졌다 — 렌더 안 하는 값을 나르지 않는다.
    for dead in ("kpi", "txt_rows", "continue_runs", "grouped_rows", "axes", "group_by"):
        assert dead not in snap, f"죽은 홈 스냅샷 키가 남아 있습니다: {dead}"


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
                          pool_registry=_pool(tmp_path))
    snap = ctrl.initial()
    assert snap["is_empty"] is True
    assert snap["counts"]["all"] == 0
    assert snap["sections"] and snap["sections"][0]["rows"] == []


def test_row_serialization_badge_level_mode_and_runnable(tmp_path):
    ctrl, _ = _controller(tmp_path)
    g = _rows(ctrl.snapshot())["공고서"]
    assert g["template_missing"] is True
    assert g["badge_level"] == "danger"   # 부재 → 시끄러운 danger(never silent ✅)
    assert g["runnable"] is False         # danger 는 실행 진입 불가
    assert g["meta_line"].startswith("템플릿 t.hwpx")
    # §19.6 행 항목: 작업 방식 텍스트가 실린다 — 표면이 라벨을 다시 짓지 않는다.
    assert g["mode_label"] == "HWPX 문서 생성"


def test_group_sections_and_collapse_are_view_only(tmp_path):
    """「모든 작업」만 사용자 group 으로 구획하고, 접힘은 **보기**만 바꾼다.

    접었다고 건수·행이 빠지면 목록이 자기 사실을 배신한다(§19.6 "group 접힘은 보기만 바꾼다").
    """
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="가", template_path="", group="조달"))
    reg.save(Job(name="나", template_path=""))
    ctrl = LibraryController(reg, _text_reg(tmp_path), lambda s, snap: None,
                          pool_registry=_pool(tmp_path))
    secs = ctrl.snapshot()["sections"]
    assert [(s["label"], s["count"], s["headed"]) for s in secs] == [
        ("조달", 1, True), ("그룹 없음", 1, True),
    ]
    assert all(not s["collapsed"] for s in secs)
    ctrl.dispatch("toggle_group", {"group": "조달"})
    secs = {s["value"]: s for s in ctrl.snapshot()["sections"]}
    assert secs["조달"]["collapsed"] is True
    assert secs["조달"]["count"] == 1 and len(secs["조달"]["rows"]) == 1  # 행은 그대로
    # 태그 facet 은 살아 있고 group-by 렌즈 액션은 죽었다(지도 §10.8 판정 B).
    with pytest.raises(ValueError, match="알 수 없는 library 액션"):
        ctrl.dispatch("set_group_by", {"axis": "금액구간"})


def test_tag_facets_stay_as_a_narrowing_axis(tmp_path):
    """렌즈 은퇴 뒤에도 태그로 좁히기는 계속 가능하다(§9.4 승계 의무 ①)."""
    ctrl, _ = _controller(tmp_path)
    assert {fa["axis"] for fa in ctrl.snapshot()["facets"]} == {"금액구간"}
    ctrl.dispatch("toggle_facet", {"axis": "금액구간", "value": "1억미만"})
    assert set(_rows(ctrl.snapshot())) == {"공고서"}
    ctrl.dispatch("clear_facets", {})
    assert set(_rows(ctrl.snapshot())) == {"공고서", "낙찰"}


def test_delete_job_updates_snapshot(tmp_path):
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("delete_job", {"name": "낙찰"})
    snap = ctrl.snapshot()
    assert snap["counts"]["all"] == 1
    assert list(_rows(snap)) == ["공고서"]
    # dispatch 가 삭제 후 관측 푸시를 냈다.
    assert any(s == "library" for s, _snap in pushes)


def test_deleting_the_selected_row_clears_the_detail(tmp_path):
    """사라진 행을 겨눈 채로 두지 않는다 — 유령 상세는 조용한 거짓말이다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_work", {"name": "낙찰"})
    assert ctrl.snapshot()["detail"]["name"] == "낙찰"
    ctrl.dispatch("delete_job", {"name": "낙찰"})
    snap = ctrl.snapshot()
    assert snap["selected"] == "" and snap["detail"] is None


def test_app_wires_library_session_guards_to_job_and_draft(tmp_path, monkeypatch):
    """#268 리뷰 배선 가드 — WebFrontend 가 라이브러리 삭제 가드에 작업·기안 화면의
    ``session_guard_for`` 를 실제로 꽂는다(가드 로직만 있고 배선이 빠지면 무의미)."""
    from hwpxfiller.webapp import app as app_mod

    monkeypatch.setattr(app_mod, "default_jobs_dir", lambda: tmp_path / "jobs")
    frontend = app_mod.WebFrontend(tmp_path / "txt")
    library = frontend.controllers["library"]
    assert library.session_guards == [
        frontend.controllers["job"].session_guard_for,
        frontend.controllers["draft"].session_guard_for,
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


# ============================================================ #26 관리 조치
def test_set_tags_replaces_and_refreshes_axes(tmp_path):
    """태그 통째 교체 저장(#2·D14) — 저장 후 axes/facets 즉시 재발견 + 카드 프리필 노출."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("set_tags", {"name": "공고서", "tags": {"물품": "의약품"}})
    snap = ctrl.snapshot()
    assert "물품" in {fa["axis"] for fa in snap["facets"]}     # 새 축 재발견
    assert _rows(snap)["공고서"]["tags"] == {"물품": "의약품"}  # 교체 + 프리필 노출
    # durable 확인 — 레지스트리에 실제 저장됐다.
    assert JobRegistry(tmp_path / "jobs").load("공고서").tags == {"물품": "의약품"}


def test_set_tags_empty_clears_all(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("set_tags", {"name": "공고서", "tags": {}})
    assert JobRegistry(tmp_path / "jobs").load("공고서").tags == {}


def test_set_tags_rejects_malformed_loudly(tmp_path):
    ctrl, _ = _controller(tmp_path)
    with pytest.raises(ValueError, match="문자열"):
        ctrl.dispatch("set_tags", {"name": "공고서", "tags": {"축": 3}})
    with pytest.raises(ValueError, match="문자열"):
        ctrl.dispatch("set_tags", {"name": "공고서", "tags": {"": "값"}})
    # 공백 변형 중복 축 — 조용한 last-wins 로 값 하나가 증발하지 않고 loud 거절.
    with pytest.raises(ValueError, match="중복된 태그 축"):
        ctrl.dispatch("set_tags", {"name": "공고서", "tags": {"지역": "본청", " 지역": "대전"}})
    # 실패해도 기존 태그는 무손상.
    assert JobRegistry(tmp_path / "jobs").load("공고서").tags == {"금액구간": "1억미만"}


def _corrupt_file(tmp_path) -> "tuple[LibraryController, str]":
    """레지스트리에 손상 .job.json 을 심고 컨트롤러와 그 경로를 돌려준다."""
    bad = tmp_path / "jobs" / "깨진작업.job.json"
    bad.write_text("{ 이건 json 아님", encoding="utf-8")
    pushes: list = []
    ctrl = LibraryController(JobRegistry(tmp_path / "jobs"), _text_reg(tmp_path),
                          lambda s, snap: pushes.append((s, snap)),
                          pool_registry=_pool(tmp_path))
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
    HwpxPackage(entries={MIMETYPE_NAME: MIMETYPE_VALUE,
                         "Contents/section0.xml": xml}).save(str(tpl))

    res = ctrl.dispatch("relink_template", {"name": "공고서", "path": str(tpl)})
    assert res["needs_confirm"] is True                    # 1차 = 재진술 확인
    res = ctrl.dispatch(
        "relink_template", {"name": "공고서", "path": str(tpl), "confirm": True})
    assert res["relinked"] is True and res["restated"]
    snap = ctrl.snapshot()
    assert snap["alerts"]["missing_template_count"] == 0   # 행·경보 최신화(refresh)


# ------------------------------------------------------- 작업 복제(F22)
def test_clone_job_creates_unique_copy_without_history(tmp_path):
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


def test_clone_job_dedupes_copy_names(tmp_path):
    """반복 복제 = '(복사본)' → '(복사본 2)' → '(복사본 3)' 유일 이름 연쇄."""
    ctrl, _ = _controller(tmp_path)
    assert ctrl.dispatch("clone_job", {"name": "공고서"})["cloned"] == "공고서 (복사본)"
    assert ctrl.dispatch("clone_job", {"name": "공고서"})["cloned"] == "공고서 (복사본 2)"
    assert ctrl.dispatch("clone_job", {"name": "공고서"})["cloned"] == "공고서 (복사본 3)"


def test_clone_missing_job_is_loud(tmp_path):
    """원본 부재 복제는 조용한 무반응 대신 오류 dict 재진술(웹이 alert)."""
    ctrl, _ = _controller(tmp_path)
    res = ctrl.dispatch("clone_job", {"name": "없는작업"})
    assert res["ok"] is False and "복제할 수 없습니다" in res["error"]


# ------------------------------------------------- 전역 라이브러리 축·상세(§19.6·§19.7)
def test_snapshot_carries_views_counts_and_health(tmp_path):
    """스냅샷은 보기·방식·검색과 그 투영을 싣는다 — 판정·문구는 전부 링1 소비."""
    ctrl, _ = _controller(tmp_path)
    snap = ctrl.initial()
    assert snap["counts"]["all"] == 2 and snap["counts"]["recent"] == 2
    assert snap["counts"]["favorites"] == 0 and snap["counts"]["needsAction"] == 2
    rows = _rows(snap)
    assert set(rows) == {"공고서", "낙찰"}
    # 건강은 (심각도, 문구) 쌍이다 — 경고(2)와 차단(3)을 소비자가 구분할 수 있어야 한다.
    assert rows["공고서"]["health"] == {
        "severity": 3, "text": "템플릿 파일을 찾을 수 없습니다.",
    }
    # 페이로드 매체는 필터가 쓰는 정규화 값이다(미연결 = hwpx) — 표시와 판정이 갈라지지 않게.
    assert rows["낙찰"]["media"] == "hwpx"   # template_path 빈 값(미연결)


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
    """0건 화면의 상주 출구 — 네 절단자(보기·방식·검색·태그)를 한 번에 걷는다(§8.4 도달성)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("set_view", {"view": "favorites"})
    ctrl.dispatch("set_mode", {"mode": "txt"})
    ctrl.dispatch("set_query", {"text": "없는이름"})
    ctrl.dispatch("toggle_facet", {"axis": "금액구간", "value": "1억미만"})
    assert _rows(ctrl.snapshot()) == {}
    ctrl.dispatch("clear_filters", {})
    snap = ctrl.snapshot()
    assert (snap["view"], snap["mode"], snap["query"]) == ("all", "all", "")
    assert not any(v["active"] for fa in snap["facets"] for v in fa["values"])
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


def test_detail_carries_every_health_cause_and_saved_bindings(tmp_path):
    """§19.7 "상세에서 모든 실제 원인" + §19.6 「필드 연결」 표는 **저장된 항목 키**.

    현재 데이터는 「문서 만들기」 세션 소유라 라이브러리가 원본 열 이름을 쓰지 않는다
    (지도 §10.8 판정 C). 판본 열은 F7 까지 만들지 않는다(판정 D).
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_work", {"name": "공고서"})
    d = ctrl.snapshot()["detail"]
    assert d["name"] == "공고서" and d["mode_label"] == "HWPX 문서 생성"
    causes = [c["text"] for c in d["health_causes"]]
    # 목록 배지는 최고 심각도 1건이지만 상세는 두 계보를 함께 본다.
    assert "템플릿 파일을 찾을 수 없습니다." in causes
    assert "파일명 패턴의 토큰을 채우지 못합니다." in causes
    assert [b["source_label"] for b in d["bindings"]] == ["bidNtceNm"]
    assert d["filename_pattern"] == "공고-{{ID}}"      # HWPX 는 파일 이름 규칙
    assert d["run_note"] == ""                          # TXT 만 실행 방식 문구
    assert "revision" not in d                          # 판본은 F7 — 빈 자리도 두지 않는다


def test_detail_is_none_when_nothing_is_selected(tmp_path):
    ctrl, _ = _controller(tmp_path)
    assert ctrl.snapshot()["detail"] is None
    ctrl.dispatch("select_work", {"name": "공고서"})
    assert ctrl.snapshot()["detail"] is not None
    ctrl.dispatch("select_work", {"name": ""})          # 선택 해제
    assert ctrl.snapshot()["detail"] is None
