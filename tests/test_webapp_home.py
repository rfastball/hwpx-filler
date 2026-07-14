"""홈(대시보드) 컨트롤러 계약 가드 — pywebview/Qt 불필요(헤드리스).

에픽 #20 마지막 페이로드 화면(허브) 이관의 회귀 심. 링1 HomeViewModel 을 그대로 임포트한
컨트롤러가 KPI·작업 카드 성형·컴파일 배지 레벨·작업 브라우저(group-by/facet)·빈 상태·txt 트랙
스냅샷을 창 없이 낸다. 허브 이동(run 겨눔·화면 전환)은 링2(웹)라 여기서 다루지 않는다.
"""
from __future__ import annotations

import pytest

from hwpxfiller.core.job import Job, JobRegistry
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.core.text_registry import TextTemplateRegistry
from hwpxfiller.webapp.screen_home import HomeController


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
                          lambda s, snap: pushes.append((s, snap)))
    return ctrl, pushes


def test_initial_kpis_and_txt_rows(tmp_path):
    ctrl, _ = _controller(tmp_path)
    snap = ctrl.initial()
    assert snap["is_empty"] is False
    assert snap["kpi"]["job_count"] == 2
    assert snap["kpi"]["missing_template_count"] == 1  # /none/t.hwpx 부재
    assert snap["kpi"]["txt_template_count"] == 1
    assert snap["txt_rows"] == [{"name": "온나라_기안", "field_count": 2}]


def test_empty_registry_is_loudly_empty(tmp_path):
    pushes: list = []
    ctrl = HomeController(JobRegistry(tmp_path / "j"), TextTemplateRegistry(tmp_path / "t"),
                          lambda s, snap: pushes.append((s, snap)))
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


def test_continue_runs_sorted_recent_first(tmp_path):
    ctrl, _ = _controller(tmp_path)
    runs = ctrl.snapshot()["continue_runs"]
    assert [r["name"] for r in runs] == ["공고서", "낙찰"]  # 2026-07-09 > 2026-06-30


def test_unknown_home_action_is_loud(tmp_path):
    ctrl, _ = _controller(tmp_path)
    with pytest.raises(ValueError, match="알 수 없는 home 액션"):
        ctrl.dispatch("frobnicate", {})
