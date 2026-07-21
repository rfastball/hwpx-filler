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
from hwpxfiller.core.text_registry import TextTemplateRegistry
from hwpxfiller.webapp.draft_session import TargetFontSetting
from hwpxfiller.webapp.screen_draft import DraftController
from hwpxfiller.webapp.screen_txt import TxtController


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
                "data_key", "has_data", "selected_count", "target_font", "filter", "table", "card"):
        assert key in snap, f"세션 키 {key} 누락 — 팩토리 계약 파손"
    # 같은 사실을 두 번 선언하지 않는다 — 표면 분기는 has_job 하나가 진다.
    assert "session_ready" not in snap


def test_initial_lists_templates(tmp_path):
    ctrl, _jobs, _ = _controller(tmp_path)
    assert ctrl.initial()["templates"] == ["착수계"]


# ------------------------------------------------------------------ 목록 ↔ 세션 비간섭
def test_select_job_does_not_destroy_volatile_session(tmp_path):
    """목록 선택은 **화면 전환**이지 세션 파괴가 아니다 — 눌렀다 돌아오면 원문이 그대로.

    저장 세션 복원은 슬라이스 5 몫이고, 그전까지 선택은 강조만 한다. 여기서 세션을 리셋하면
    붙여넣던 원문·데이터·큐 진행이 클릭 한 번에 조용히 사라진다(복구 불가 — 앱 밖 기억).
    """
    ctrl, jobs, _ = _controller(tmp_path)
    _save(jobs, "기안A", "C:/t/a.txt")
    ctrl.dispatch("set_template_text", {"text": "붙여넣은 원문 {{공고명}}"})
    ctrl.dispatch("select_job", {"name": "기안A"})
    assert ctrl.snapshot()["has_job"] is True
    ctrl.dispatch("select_job", {"name": ""})       # 미선택으로 복귀 = 휘발 세션
    snap = ctrl.snapshot()
    assert snap["has_job"] is False
    assert snap["template_text"] == "붙여넣은 원문 {{공고명}}"


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
