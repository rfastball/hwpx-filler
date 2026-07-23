"""홈(대시보드) 컨트롤러 계약 가드 — pywebview/Qt 불필요(헤드리스).

에픽 #20 마지막 페이로드 화면(허브) 이관의 회귀 심. 링1 HomeViewModel 을 그대로 임포트한
컨트롤러가 KPI·작업 카드 성형·컴파일 배지 레벨·작업 브라우저(group-by/facet)·빈 상태·txt 트랙
스냅샷을 창 없이 낸다. 허브 이동(run 겨눔·화면 전환)은 링2(웹)라 여기서 다루지 않는다.
"""
from __future__ import annotations

import pytest

from hwpxfiller.core.dataset_pool import DatasetPoolRegistry
from hwpxfiller.core.job import Job, JobRegistry
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.core.text_registry import TextTemplateRegistry
from hwpxfiller.webapp.screen_home import HomeController


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


def _controller(tmp_path) -> "tuple[HomeController, list]":
    pushes: list = []
    ctrl = HomeController(_reg(tmp_path), _text_reg(tmp_path),
                          lambda s, snap: pushes.append((s, snap)),
                          pool_registry=_pool(tmp_path))
    return ctrl, pushes


def test_initial_kpis_and_txt_rows(tmp_path):
    ctrl, _ = _controller(tmp_path)
    snap = ctrl.initial()
    assert snap["is_empty"] is False
    assert snap["kpi"]["job_count"] == 2
    assert snap["kpi"]["missing_template_count"] == 1  # /none/t.hwpx 부재
    assert snap["kpi"]["txt_template_count"] == 1
    assert snap["txt_rows"] == [{"name": "온나라_기안", "field_count": 2}]


def test_kpi_snapshot_carries_pool_corruption(tmp_path):
    """홈 KPI 스냅샷 — 데이터 풀 손상 수가 웹까지 실린다(#45, 0 위장 금지).

    VM(kpi.pool_corrupted)은 세는데 스냅샷 dict 이 누락하면 confirm-or-alarm 이
    링1에서 끊긴다 — 웹 타일이 렌더할 값 자체가 없다.
    """
    ctrl, _ = _controller(tmp_path)
    assert ctrl.snapshot()["kpi"]["pool_corrupted"] == 0    # 손상 없으면 0(거짓 경보 없음)
    # 연결된 풀 디렉터리에 손상 파일이 생기면 다음 스냅샷이 살아있는 재계수로 잡는다.
    pool_dir = tmp_path / "datasets"
    pool_dir.mkdir()
    (pool_dir / ("깨진" + DatasetPoolRegistry.SUFFIX)).write_text("{ not json", encoding="utf-8")
    assert ctrl.snapshot()["kpi"]["pool_corrupted"] == 1


def test_empty_registry_is_loudly_empty(tmp_path):
    pushes: list = []
    ctrl = HomeController(JobRegistry(tmp_path / "j"), TextTemplateRegistry(tmp_path / "t"),
                          lambda s, snap: pushes.append((s, snap)),
                          pool_registry=_pool(tmp_path))
    snap = ctrl.initial()
    assert snap["is_empty"] is True
    assert snap["kpi"]["job_count"] == 0
    assert snap["grouped_rows"] and snap["grouped_rows"][0]["rows"] == []


def test_card_serialization_badge_level_and_runnable(tmp_path):
    ctrl, _ = _controller(tmp_path)
    # 태그가 있으나 group-by 렌즈가 그 축을 발견하지 않으면 flat(단일 버킷).
    ctrl.dispatch("set_group_by", {"axis": ""})
    rows = {r["name"]: r for r in ctrl.snapshot()["grouped_rows"][0]["rows"]}
    g = rows["공고서"]
    assert g["template_missing"] is True
    assert g["badge_level"] == "danger"   # 부재 → 시끄러운 danger(never silent ✅)
    assert g["runnable"] is False         # danger 는 실행 진입 불가
    assert g["meta_line"].startswith("템플릿 t.hwpx")


def test_group_by_and_facet_filter(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("set_group_by", {"axis": "금액구간"})
    snap = ctrl.snapshot()
    assert snap["group_by"] == "금액구간"
    labels = {sec["value"]: sec["count"] for sec in snap["grouped_rows"]}
    assert labels == {"1억미만": 1, "10억이상": 1}   # 두 그룹으로 분할

    # group-by 축이 섹션이면 facet 은 그 축을 빼고 노출(여기선 다른 축 없음).
    assert all(fa["axis"] != "금액구간" for fa in snap["facets"])


def test_delete_job_updates_snapshot(tmp_path):
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("delete_job", {"name": "낙찰"})
    snap = ctrl.snapshot()
    assert snap["kpi"]["job_count"] == 1
    names = [r["name"] for sec in snap["grouped_rows"] for r in sec["rows"]]
    assert names == ["공고서"]
    # dispatch 가 삭제 후 관측 푸시를 냈다.
    assert any(s == "home" for s, _snap in pushes)


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


def test_continue_runs_sorted_recent_first(tmp_path):
    ctrl, _ = _controller(tmp_path)
    runs = ctrl.snapshot()["continue_runs"]
    assert [r["name"] for r in runs] == ["공고서", "낙찰"]  # 2026-07-09 > 2026-06-30


def test_unknown_home_action_is_loud(tmp_path):
    ctrl, _ = _controller(tmp_path)
    with pytest.raises(ValueError, match="알 수 없는 home 액션"):
        ctrl.dispatch("frobnicate", {})


# ============================================================ #26 홈 조치
def test_set_tags_replaces_and_refreshes_axes(tmp_path):
    """태그 통째 교체 저장(#2·D14) — 저장 후 axes/facets 즉시 재발견 + 카드 프리필 노출."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("set_tags", {"name": "공고서", "tags": {"물품": "의약품"}})
    snap = ctrl.snapshot()
    assert "물품" in snap["axes"]                        # 새 축 재발견
    row = next(r for sec in snap["grouped_rows"] for r in sec["rows"] if r["name"] == "공고서")
    assert row["tags"] == {"물품": "의약품"}             # 교체(기존 금액구간 소거) + 프리필 노출
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


def _corrupt_file(tmp_path) -> "tuple[HomeController, str]":
    """레지스트리에 손상 .job.json 을 심고 컨트롤러와 그 경로를 돌려준다."""
    bad = tmp_path / "jobs" / "깨진작업.job.json"
    bad.write_text("{ 이건 json 아님", encoding="utf-8")
    pushes: list = []
    ctrl = HomeController(JobRegistry(tmp_path / "jobs"), _text_reg(tmp_path),
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
def test_home_relink_template_commits_and_refreshes(tmp_path):
    """홈 카드 재연결 — run 과 공유하는 게이트로 커밋 후 KPI/카드가 최신화된다(#67)."""
    from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage

    ctrl, _ = _controller(tmp_path)
    assert ctrl.snapshot()["kpi"]["missing_template_count"] == 1  # /none/t.hwpx 부재
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
    assert snap["kpi"]["missing_template_count"] == 0      # 카드/KPI 최신화(refresh)


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
    names = [
        r["name"] for sec in pushes[-1][1]["grouped_rows"] for r in sec["rows"]
    ]
    assert "공고서 (복사본)" in names


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
