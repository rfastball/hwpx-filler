"""「작업」 화면 컨트롤러 계약 가드 — pywebview/Qt 불필요(헤드리스).

패널 4존이 소비하는 링1 배선(부록 A-1)을 창 없이 되읽는다: 좌 목록 → 작업 선택 → 데이터 겨눔
→ 미입력 강제 확인 게이트(ADR-E) → 덮어쓰기 재진술(RC-02) → 생성 end-to-end.
JobController가 링1 계약을 위임해 소비하는지 못박는다.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from hwpxfiller.core.job import Job, JobRegistry, rules_fingerprints
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.gui.review_state import review_requirement
from hwpxfiller.gui.run_state import RunViewModel
from hwpxfiller.gui.selection_state import SelectionModel
from hwpxfiller.webapp.screen_job import JobController
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage

MULTI_SHEET = Path(__file__).resolve().parents[0] / "fixtures" / "multi_sheet.xlsx"


def _write_template(path, fields) -> None:
    body = "".join(
        f'<hp:run><hp:ctrl><hp:fieldBegin name="{name}"/></hp:ctrl></hp:run>'
        f'<hp:run><hp:t>{{{{{name}}}}}</hp:t></hp:run>'
        '<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>'
        for name in fields
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p>'
        + body + '</hp:p></hs:sec>'
    ).encode()
    HwpxPackage(entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": xml}).save(str(path))


def _registry(tmp_path, *, reviewed: bool = True) -> JobRegistry:
    """공용 픽스처 — 기본은 **이미 한 번 완주한** 작업이다(재작성 F5).

    검토 요구(§13-3)는 새 작업의 게이트를 닫으므로, 그것을 겨누지 않는 테스트(빈 값 ack·
    선택 게이트·필터…)까지 전부 검토 문맥을 지고 가면 무엇을 재는 테스트인지 흐려진다.
    검토 요구 자체는 ``reviewed=False`` 로 여는 전용 테스트가 잰다.
    """
    template = tmp_path / "t.hwpx"
    _write_template(template, ["공고명", "추정가격"])
    reg = JobRegistry(tmp_path / "jobs")
    job = Job(
        name="공고서",
        template_path=str(template),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source="bidNtceNm"),
            FieldMapping(template_field="추정가격", source="presmptPrce"),
        ]),
        filename_pattern="doc-{{seq:001}}",
    )
    if reviewed:
        # 기준선만 세운다 — `last_run_at` 은 건드리지 않는다: 실행 이력은 순위·완주 스탬프
        # 테스트가 각자 겨누는 축이라, 픽스처가 미리 찍으면 그 테스트들이 재는 것이 바뀐다.
        job.reviewed_rules = rules_fingerprints(job)
    reg.save(job)
    return reg


def _controller(tmp_path, *, reviewed: bool = True):
    pushes: list = []
    ctrl = JobController(
        _registry(tmp_path, reviewed=reviewed), lambda s, snap: pushes.append((s, snap))
    )
    return ctrl, pushes


def _data_csv(tmp_path) -> str:
    # rec0 은 추정가격 빈값(→ '미입력'), rec1 은 채움 — 강제 확인 게이트를 태운다.
    csv = tmp_path / "d.csv"
    csv.write_text("bidNtceNm,presmptPrce\n전산장비,\n사무비품,2000000\n", encoding="utf-8")
    return str(csv)


def _mount_all(ctrl, path, *, sheet=None) -> None:
    """마운트 + 전체 선택 — 데이터-우선 전이(§18.2: 마운트 직후 선택 0건) 이후, 전체
    레코드를 대상으로 하던 기존 시나리오는 명시적 set_all 로 같은 전제를 복원한다."""
    ctrl.load_data_path(path, sheet=sheet)
    ctrl.dispatch("set_all", {})


# ---------------------------------------------------------------- 스냅샷 골격
def test_initial_has_no_active_work_and_loud_gate(tmp_path):
    ctrl, _ = _controller(tmp_path)
    snap = ctrl.initial()
    assert snap["has_job"] is False
    # 좌 목록 4키는 표면과 함께 사망했다(F2 PR-B, 지도 §10.9 판정 F) — 아무도 그리지 않는
    # 페이로드가 남으면 다음 세션이 그걸 근거로 목록을 되살린다. 저장된 작업의 전역 목록은
    # 「문서 작업」 소관이고, 이 화면은 데이터가 준비된 뒤의 **후보**만 낸다.
    for dead in ("job_rows", "job_sections", "job_flat", "job_group_names"):
        assert dead not in snap, f"죽은 좌 목록 키가 스냅샷에 남았습니다: {dead}"
    # 데이터-우선 도입 순서(§18.2) — 첫 할 일은 데이터 선택이다.
    assert snap["gate"]["enabled"] is False and "데이터 파일" in snap["gate"]["text"]
    # 데이터 미준비 = 후보 계산 자체를 안 한다(§18.1) — 4구획 전부 빈 골격.
    assert snap["candidates"] == {
        "top": [], "more": 0, "needs_count": 0, "suggested": "",
    }
    # 문서 탐색도 미계산 골격(§18.1) — 탭·검색어는 세션 기본값을 그대로 재진술한다.
    assert snap["browse"]["rows"] == [] and snap["browse"]["available_count"] == 0


def test_select_job_sets_session_identity(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["has_job"] is True and snap["job_name"] == "공고서"
    # 저장 폴더 기본값 = 템플릿 폴더/Results(실행 화면 동형).
    assert snap["out_dir"].endswith("Results")


def test_select_job_then_data_populates_records_and_badges(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    snap = ctrl.snapshot()
    assert snap["has_data"] is True and snap["record_count"] == 2
    assert snap["selected_count"] == 0  # 마운트 직후 선택 0건(§18.2 — 구 전체선택 개정)
    assert snap["template_path"].endswith("t.hwpx")  # 추적성 로케이트용 전체 경로(#53-B)
    ctrl.dispatch("set_all", {})
    snap = ctrl.snapshot()
    assert snap["selected_count"] == 2
    # 본문 존 거울 행(비-drift 필드) — 이름·상태·값 병기.
    states = {s["name"]: s["state"] for s in snap["mirror"]}
    assert states["공고명"] == "filled"
    assert states["추정가격"] == "missing"  # rec0 빈값 → 미입력


def test_prework_gate_counts_only_available_candidates(tmp_path):
    """후보가 전부 needs_action 이면 "선택하세요"는 이행 불가능한 지시다(#302 리뷰 P2)
    — 게이트는 available 존재로만 선택을 권하고, 없으면 없다고 말한다."""
    ctrl, _ = _controller(tmp_path)
    csv = tmp_path / "other.csv"
    csv.write_text("엉뚱한열" + chr(10) + "값" + chr(10), encoding="utf-8")
    ctrl.load_data_path(str(csv))                       # '공고서' 필수 소스가 없는 데이터
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})
    snap = ctrl.snapshot()
    cands = snap["candidates"]
    assert cands["top"] == [] and cands["needs_count"] == 1        # 수치로 남는다
    # 확인 필요 **목록**은 문서 탐색 탭이 소유한다(슬라이스 3 이사).
    ctrl.dispatch("browse_tab", {"tab": "needs_action"})
    assert [r["name"] for r in ctrl.snapshot()["browse"]["rows"]] == ["공고서"]
    assert "사용할 수 있는 문서 작업이 없습니다" in snap["gate"]["text"]


def test_job_selection_reconciles_filter_kinds_unless_defined(tmp_path):
    """무작업 마운트 필터는 스니핑 유형 — 작업 선택이 매핑 힌트로 재조정한다(#302 리뷰 P2).
    단 정의가 있는 필터는 그대로(사용자 확정 > 유형 힌트 — 술어 조용한 소실 금지)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_data_csv(tmp_path))            # 무작업 마운트 = 스니핑만
    assert ctrl.filter is not None
    assert ctrl.filter.kind("presmptPrce") == "amount"  # 수치 값 → 스니핑 판정
    ctrl.dispatch("select_job", {"name": "공고서"})     # 정의 없음 → 힌트 반영 재생성
    assert ctrl.filter.kind("presmptPrce") == "text"    # 매핑 확정 유형(text) 우선
    # 정의가 있으면 재생성하지 않는다 — 술어·유형 그대로 생존.
    ctrl2, _ = _controller(tmp_path)
    ctrl2.load_data_path(_data_csv(tmp_path))
    ctrl2.dispatch("filter_search", {"text": "전산"})
    kinds_before = {c: ctrl2.filter.kind(c) for c in ctrl2.filter.columns}
    ctrl2.dispatch("select_job", {"name": "공고서"})
    assert ctrl2.filter.is_active()                     # 정의 생존
    assert {c: ctrl2.filter.kind(c) for c in ctrl2.filter.columns} == kinds_before


def test_generation_in_flight_blocks_switch_and_remount(tmp_path):
    """생성 진행 중 작업 전환·데이터 교체는 시끄럽게 거부된다(#302 리뷰 P1) — vm 교체가
    진행 중 배치의 검증·계획과 경합해 남의 작업으로 생성될 수 있다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    assert ctrl._generation_lock.acquire(blocking=False)
    try:
        with pytest.raises(ValueError, match="생성이 진행 중"):
            ctrl.dispatch("select_job", {"name": ""})
        with pytest.raises(ValueError, match="생성이 진행 중"):
            ctrl.load_data_path(_data_csv(tmp_path))
    finally:
        ctrl._generation_lock.release()


def test_generate_locked_never_rereads_live_vm():
    """_generate_locked 는 캡처한 run_vm 만 소비한다(#302 리뷰 P1) — 생성 중 전환이
    self.vm 을 갈아끼워도 이 런의 검증·계획·완주 기록이 남의 작업으로 새지 않는다."""
    import inspect

    src = inspect.getsource(JobController._generate_locked)
    assert "self.vm." not in src, "_generate_locked 가 라이브 vm 을 재참조합니다(P1 재유입)."
    assert "run_vm." in src


# --------------------------------------- data-first 첫 슬라이스 성공 기준(계획 §5)
def test_data_first_flow_end_to_end(tmp_path):
    """데이터 마운트(무작업) → 행 선택 → 후보 → 명시 선택 → 게이트 → 실제 HWPX 생성 1회.

    봉합 계획 §5 성공 기준의 자동판 — master 생성 엔진을 그대로 쓰면서 data-first
    메인 흐름이 실제 문서 1건을 완주한다. 각 단계의 스냅샷 재진술도 함께 되읽는다.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_data_csv(tmp_path))                      # 작업 없이 마운트
    snap = ctrl.snapshot()
    assert snap["has_job"] is False and snap["has_data"] is True
    assert snap["selected_count"] == 0                            # §18.2 초기 0건
    ctrl.dispatch("toggle_record", {"index": 1, "value": True})   # 채움 완결 행 선택
    cands = ctrl.snapshot()["candidates"]
    assert [c["name"] for c in cands["top"]] == ["공고서"] and cands["needs_count"] == 0
    ctrl.dispatch("select_job", {"name": "공고서"})               # 명시 선택(§18.3 자동 아님)
    snap = ctrl.snapshot()
    assert snap["has_job"] is True and snap["selected_count"] == 1  # 선택 생존(§18.2)
    assert snap["gate"]["enabled"] is True                          # 권위 판정 = RunViewModel
    res = ctrl.generate()
    assert res["ok"] is True and res["succeeded"] == 1 and res["failed"] == 0
    assert (Path(snap["out_dir"]) / "doc-001.hwpx").exists()      # 실물 산출


# ------------------- 메인 후보 순위·추천·즐겨찾기 (슬라이스 2, §18.5·§19.3·§18.3 개정)
def _extra_job(ctrl, name: str, *, favorited_at: str = "", last_run_at: str = "",
               sources=("bidNtceNm", "presmptPrce")) -> None:
    """같은 템플릿을 쓰는 추가 hwpx 작업 저장(순위 표본용)."""
    base = ctrl.registry.load("공고서")
    ctrl.registry.save(Job(
        name=name,
        template_path=base.template_path,
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source=sources[0]),
            FieldMapping(template_field="추정가격", source=sources[1]),
        ]),
        filename_pattern="doc-{{seq:001}}",
        favorited_at=favorited_at,
        last_run_at=last_run_at,
    ))


def test_candidate_top_is_ranked_and_capped_with_honest_overflow(tmp_path):
    """메인은 상위 5건만 그리되 잘린 나머지를 **수치로 고지**한다(조용한 절단 금지).

    전체 목록 표면(문서 탐색)은 슬라이스 3 소관이라 지금은 "외 N건"까지가 정직한 최대치다.
    """
    ctrl, _ = _controller(tmp_path)
    _extra_job(ctrl, "즐겨", favorited_at="2026-07-20T09:00:00")
    _extra_job(ctrl, "최근", last_run_at="2026-07-25T09:00:00")
    for i in range(4):
        _extra_job(ctrl, f"미사용{i}")
    ctrl.load_data_path(_data_csv(tmp_path))
    cands = ctrl.snapshot()["candidates"]
    assert [c["name"] for c in cands["top"]] == [
        "즐겨", "최근", "공고서", "미사용0", "미사용1",
    ]
    assert [c["tier"] for c in cands["top"][:3]] == ["favorite", "recent", "unused"]
    assert cands["top"][0]["favorited"] is True
    assert cands["top"][1]["last_run_at"] == "2026-07-25T09:00:00"
    assert cands["more"] == 2                     # 미사용2·미사용3 — 수치로 남는다


def test_needs_action_moves_to_the_document_browser_tab(tmp_path):
    """확인 필요 목록은 문서 탐색 탭이 소유한다(슬라이스 3 이사) — 후보 줄엔 수치만.

    구획이 이사할 때 의무도 함께 간다(삭제는 의무를 상속한다): 막힌 이유(없는 열)는
    새 표면에서 계속 말해야 한다.
    """
    ctrl, _ = _controller(tmp_path)
    _extra_job(ctrl, "확인나", sources=("없는열", "presmptPrce"))
    _extra_job(ctrl, "확인가", sources=("bidNtceNm", "다른없는열"))
    ctrl.load_data_path(_data_csv(tmp_path))
    snap = ctrl.snapshot()
    assert snap["candidates"]["needs_count"] == 2                 # 후보 줄 = 수치
    assert snap["browse"]["needs_count"] == 2                     # 탭 라벨도 같은 수치

    ctrl.dispatch("browse_tab", {"tab": "needs_action"})
    rows = ctrl.snapshot()["browse"]["rows"]
    assert [r["name"] for r in rows] == ["확인가", "확인나"]      # 이름순
    assert rows[0]["missing"] == ["다른없는열"]                   # 막힌 이유 승계


def test_browse_search_keeps_tab_counts_and_survives_tab_switch(tmp_path):
    """검색어는 탭 전환에서 살고(§18.6), 탭 건수는 검색 중에도 데이터에 대한 사실로 남는다."""
    ctrl, _ = _controller(tmp_path)
    _extra_job(ctrl, "계약서")
    _extra_job(ctrl, "확인필요건", sources=("없는열", "presmptPrce"))
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.dispatch("browse_query", {"text": "계약"})
    snap = ctrl.snapshot()["browse"]
    assert [r["name"] for r in snap["rows"]] == ["계약서"]
    assert snap["available_count"] == 2 and snap["filtered_out"] == 1
    ctrl.dispatch("browse_tab", {"tab": "needs_action"})
    after = ctrl.snapshot()["browse"]
    assert after["query"] == "계약"                    # 검색어 생존(계약 명문)
    assert after["rows"] == [] and after["needs_count"] == 1  # 그 탭엔 일치 0건


def test_single_candidate_is_suggested_but_never_auto_selected(tmp_path):
    """§18.3 개정(F-02) — 유일 후보는 추천 표지만 받고 활성 작업은 사용자 클릭으로만 바뀐다."""
    ctrl, _ = _controller(tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))                        # 항목 선택까지 마친 상태
    snap = ctrl.snapshot()
    assert snap["candidates"]["suggested"] == "공고서"
    assert snap["candidates"]["top"][0]["suggested"] is True
    assert snap["has_job"] is False and snap["job_name"] == ""   # 자동 선택 없음
    assert "문서 작업을 선택하세요" in snap["gate"]["text"]        # 게이트도 사용자에게 넘긴다
    ctrl.dispatch("select_job", {"name": "공고서"})
    after = ctrl.snapshot()["candidates"]
    assert after["suggested"] == "" and after["top"][0]["suggested"] is False


def test_two_candidates_get_no_suggestion(tmp_path):
    """2개 이상이면 1위를 밀지 않는다 — 순위는 이력의 관측이지 이 데이터의 권위가 아니다."""
    ctrl, _ = _controller(tmp_path)
    _extra_job(ctrl, "다른작업", favorited_at="2026-07-20T09:00:00")
    ctrl.load_data_path(_data_csv(tmp_path))
    assert ctrl.snapshot()["candidates"]["suggested"] == ""


def test_toggle_favorite_persists_and_reorders_without_touching_session(tmp_path):
    """즐겨찾기는 정렬 메타만 바꾼다(§18.5) — 활성 작업·데이터·선택·게이트 불변."""
    ctrl, _ = _controller(tmp_path)
    _extra_job(ctrl, "가나다")
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("select_job", {"name": "공고서"})
    before = ctrl.snapshot()
    assert [c["name"] for c in before["candidates"]["top"]] == ["가나다", "공고서"]

    assert ctrl.dispatch("toggle_favorite", {"name": "공고서", "value": True})["ok"] is True
    after = ctrl.snapshot()
    assert [c["name"] for c in after["candidates"]["top"]] == ["공고서", "가나다"]
    assert ctrl.registry.load("공고서").favorited_at != ""         # 영속
    assert after["job_name"] == "공고서" and after["has_job"] is True
    assert after["selected_count"] == before["selected_count"]
    assert after["gate"] == before["gate"]

    assert ctrl.dispatch("toggle_favorite", {"name": "공고서", "value": False})["ok"] is True
    assert ctrl.registry.load("공고서").favorited_at == ""
    assert [c["name"] for c in ctrl.snapshot()["candidates"]["top"]] == ["가나다", "공고서"]


def test_rapid_favorites_within_one_second_keep_newest_first(tmp_path):
    """1초 안의 연속 즐겨찾기도 최신순을 지킨다(리뷰 1R P2 — 초 절단이면 동률→이름순 추락).

    연속 클릭은 이 표면의 정상 사용이다: 두 번째로 누른 별이 위로 오지 않으면
    "즐겨찾기 최신순"(§18.5)이 문안만 남고 거짓이 된다.
    """
    ctrl, _ = _controller(tmp_path)
    _extra_job(ctrl, "가나다")                                  # 이름순은 '가나다' 가 앞
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.dispatch("toggle_favorite", {"name": "가나다", "value": True})
    ctrl.dispatch("toggle_favorite", {"name": "공고서", "value": True})   # 같은 초 안
    first = ctrl.registry.load("가나다").favorited_at
    second = ctrl.registry.load("공고서").favorited_at
    assert first != second, f"같은 시각으로 찍혀 동률입니다: {first!r}"
    assert [c["name"] for c in ctrl.snapshot()["candidates"]["top"]] == ["공고서", "가나다"]


def test_overflow_job_can_be_promoted_and_left_list_carries_the_flag(tmp_path):
    """순위 밖 작업도 즐겨찾기로 승격된다(리뷰 2R P2 — 카드 별은 상위 5장뿐).

    도달성은 **절단되지 않는 표면**(좌 목록 ⋮ 메뉴)이 지고, 그 메뉴 문안의 근거인
    ``favorited`` 표지는 좌 목록 행이 싣는다. 승격 뒤 후보 상위권에 실제로 올라온다.
    """
    ctrl, _ = _controller(tmp_path)
    for i in range(6):
        _extra_job(ctrl, f"작업{i}", last_run_at=f"2026-07-2{i}T09:00:00")
    ctrl.load_data_path(_data_csv(tmp_path))
    cands = ctrl.snapshot()["candidates"]
    assert cands["more"] >= 1
    hidden = [j.name for j in ctrl.registry.list_jobs()
              if j.name not in {c["name"] for c in cands["top"]}]
    target = hidden[0]                                       # 순위 밖 = 카드에 별이 없다

    assert ctrl.dispatch("toggle_favorite", {"name": target, "value": True})["ok"] is True
    snap = ctrl.snapshot()
    assert snap["candidates"]["top"][0]["name"] == target     # 승격돼 1순위
    # 좌 목록 사망(F2 PR-B) 뒤 별 상태를 싣는 유일 표면은 후보 카드다 — 승격된 카드가
    # 지정 상태를 함께 말해야 다시 눌러 해제할 수 있다(순위 밖 승격 도달성의 되돌림).
    assert snap["candidates"]["top"][0]["favorited"] is True


def test_toggle_favorite_on_vanished_job_is_restated_not_silent(tmp_path):
    """다른 화면에서 사라진 작업의 별은 조용히 삼키지 않는다(목록은 다음 스냅샷이 갱신)."""
    ctrl, _ = _controller(tmp_path)
    res = ctrl.dispatch("toggle_favorite", {"name": "없는작업", "value": True})
    assert res["ok"] is False and "즐겨찾기를 바꾸지 못했습니다" in res["error"]


# ------------------------------------------- 표시순 투영(§18.10·§2, 충돌 B 확정)
def test_display_order_newest_first_and_execution_follows_projection(tmp_path):
    """표 순서 = sourceDesc(최신 행 먼저), 실행 입력 = 표시순 투영(WYSIWYG).

    {{seq}} 순번·동명 꼬리표가 화면 위→아래 순서를 그대로 따른다 — 같은 선택이라도
    표시 순서가 바뀌면 파일명이 달라진다(인지·수용된 확정, 봉합 지도 §2). 완화 의무 =
    파일명 미리보기가 같은 투영을 보여준다(보이는 것=생성되는 것).
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    rows = ctrl.snapshot()["records"]
    assert [r["index"] for r in rows] == [1, 0]          # 최신(마지막 원본 행)이 먼저
    assert rows[0]["name"] == "doc-001.hwpx"             # 실행 1번 = 화면 1번(최신 행)
    assert rows[1]["name"] == "doc-002.hwpx"


def test_filtered_table_rows_follow_display_order(tmp_path):
    """필터 가시 행도 같은 표시순 투영을 쓴다 — 표와 실행이 다른 순서를 말하지 않는다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    csv = tmp_path / "three.csv"
    csv.write_text(
        "bidNtceNm,presmptPrce" + chr(10)
        + "전산장비A,1" + chr(10) + "사무비품,2" + chr(10) + "전산장비B,3" + chr(10),
        encoding="utf-8",
    )
    ctrl.load_data_path(str(csv))
    ctrl.dispatch("filter_search", {"text": "전산"})
    table = ctrl.snapshot()["table"]
    assert [r["index"] for r in table["rows"]] == [2, 0]  # 가시 집합도 최신 먼저


# ------------------------------------------------------ 식별 요약 링1 소비
def test_record_summary_consumes_ring1_identity_not_keyed_temp(tmp_path):
    """식별 요약은 링1 ``identity_summary``를 소비하고 원본 값만 병기한다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    summaries = [r["summary"] for r in ctrl.snapshot()["records"]]
    assert all("bidNtceNm" not in s for s in summaries)  # 임시 판의 키 접두 폐기(값만 병기)
    # display_for: rec0 은 presmptPrce 빈값이라 마커로 자리 보존(매달린 구분자 아님), rec1 은
    # 두 값 병기. 인지층 = 왼쪽 2열. 목록 순서 = 표시순(sourceDesc, §18.10 — 최신 행 먼저).
    assert summaries == ["사무비품 · 2000000", "전산장비 · (빈칸)"]


def test_filename_token_mode_back_resolves_and_excludes_non_carriers(tmp_path):
    """파일명이 나르는 템플릿 필드를 매핑 ``source``(원본 열)로 역해소(결정 37 토큰 모드).

    파일명 토큰은 **매핑 후** 네임스페이스(``공고명``)인데 식별 요약은 **원본 열**(``bidNtceNm``)
    을 본다 — 역해소가 없으면 토큰 모드가 엉뚱한 네임스페이스로 오발한다(confirm-or-alarm).
    세 배제 가드를 모두 태운다: ``const``(리터럴, source 무의존)·``blank``·부재 source.
    """
    template = tmp_path / "t.hwpx"
    _write_template(template, ["공고명", "상수", "빈칸", "유령"])
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(
        name="공고서",
        template_path=str(template),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source="bidNtceNm"),          # text·present → 포함
            FieldMapping(template_field="상수", source="dmndInsttNm", type="const", const="고정"),  # const → 배제
            FieldMapping(template_field="빈칸", source="ntceInsttNm", type="blank"),  # blank → 배제
            FieldMapping(template_field="유령", source="does_not_exist"),        # 부재 source → 배제
        ]),
        # 네 템플릿 필드를 모두 파일명이 요구(가드가 없으면 넷 다 토큰 모드로 샘).
        filename_pattern="{{공고명}}-{{상수}}-{{빈칸}}-{{유령}}-{{seq:001}}",
    ))
    csv = tmp_path / "d.csv"
    csv.write_text(
        "bidNtceNm,presmptPrce,dmndInsttNm,ntceInsttNm\n전산장비,,조달청,조달청\n사무비품,2000000,경찰청,경찰청\n",
        encoding="utf-8",
    )
    ctrl = JobController(reg, lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, str(csv))
    # text·present 인 공고명(→bidNtceNm)만 나르는 열. const·blank·부재 source 는 배제.
    assert ctrl._filename_source_columns() == ["bidNtceNm"]


# ---------------------------------------------------------------- 게이트·생성(링1 계약)
def test_missing_gate_blocks_generate_until_acked(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))

    snap = ctrl.snapshot()
    assert snap["gate"]["enabled"] is False and "빈 값" in snap["gate"]["text"]

    # 생성 시도도 방어적으로 차단(worker/API 우회 방지).
    res = ctrl.generate()
    assert res["ok"] is False and "빈 값" in res["error"]

    # 배지 클릭 = 직접 확인 → 게이트 열림.
    ctrl.dispatch("ack_field", {"field": "추정가격"})
    assert ctrl.snapshot()["gate"]["enabled"] is True


def test_generate_writes_documents_and_marks_missing(tmp_path):
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    out = tmp_path / "out"
    ctrl.set_output_folder(str(out))
    ctrl.dispatch("ack_field", {"field": "추정가격"})

    res = ctrl.generate()
    assert res["ok"] is True
    assert res["succeeded"] == 2 and res["failed"] == 0
    assert "빈 값 표시 필드" in res["summary"]  # 낙관 서사 해소
    made = sorted(p.name for p in out.glob("*.hwpx"))
    assert made == ["doc-001.hwpx", "doc-002.hwpx"]
    # 진행 델타가 최소 1회 푸시됐다(진행바 갱신 계약).
    assert any(isinstance(snap, dict) and "progress" in snap for _s, snap in pushes)


def test_generate_cancel_keeps_completed_and_restates_unstarted(tmp_path, monkeypatch):
    import hwpxfiller.webapp.screen_job as sj

    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})

    class _Done:
        ok = True
        output_path = "doc-001.hwpx"
        error = ""
        notes = []

    class _Cancelled:
        total = 2
        succeeded = 1
        failed = 1
        results = [_Done()]
        cancelled = True
        attempted = 1

    def fake_batch(*args, **kwargs):
        ctrl.dispatch("cancel_generation", {})
        assert kwargs["cancelled"]() is True
        return _Cancelled()

    monkeypatch.setattr(sj, "generate_batch", fake_batch)
    result = ctrl.generate()
    assert result["cancelled"] is True
    assert result["attempted"] == 1 and result["unstarted"] == 1
    assert result["failed"] == 0
    assert "완료된 문서는 그대로 유지" in result["summary"]
    assert ctrl.registry.load("공고서").last_run_at == ""


def test_generate_rejects_concurrent_entry(tmp_path):
    """생성 잠금이 잡힌 동안 두 번째 실행은 파일 작업 전에 시끄럽게 거부한다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    assert ctrl._generation_lock.acquire(blocking=False)
    try:
        result = ctrl.generate()
    finally:
        ctrl._generation_lock.release()
    assert result == {
        "ok": False,
        "error": "이미 문서를 생성하고 있습니다.",
        "level": "warn",
    }


def test_generation_stamps_last_run_at(tmp_path):
    """완주 = 역사(#129) — 생성이 작업에 실행 시각을 영속해야 홈 이력·KPI 가 산다."""
    ctrl, _ = _controller(tmp_path)
    assert ctrl.registry.load("공고서").last_run_at == ""      # 선조건: 미실행
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})

    res = ctrl.generate()
    assert res["ok"] is True and res["level"] == "ok"
    stamped = ctrl.registry.load("공고서").last_run_at
    # 소비처(home_state·screen_library)가 fromisoformat 파싱 + 원시 문자열 정렬로 쓴다.
    assert datetime.fromisoformat(stamped)
    assert len(stamped) == len("2026-07-21T09:00:00")           # 초 단위 고정폭 = 정렬 가능
    assert ctrl.vm.job.last_run_at == stamped                   # 인메모리 사본도 동행


def test_generation_stamp_does_not_clobber_disk_edits(tmp_path):
    """스탬프는 단일 필드 뮤테이션 — 세션이 든 옛 사본으로 디스크 최신 편집을 되돌리지 않는다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})
    # 세션이 열린 사이 다른 표면(에디터)이 같은 작업을 편집·저장했다.
    edited = ctrl.registry.load("공고서")
    edited.filename_pattern = "edited-{{seq:001}}"
    ctrl.registry.save(edited, allow_overwrite=True)

    assert ctrl.generate()["ok"] is True
    after = ctrl.registry.load("공고서")
    assert after.filename_pattern == "edited-{{seq:001}}"       # 디스크 편집 보존
    assert after.last_run_at != ""                              # 그리고 스탬프도 남는다


def test_stamp_goes_to_the_job_the_run_started_on(tmp_path, monkeypatch):
    """생성 중 작업 전환은 **시끄럽게 거부**되고(#302 리뷰 P1 — 구 관용 계약의 개정),
    역사는 그 런의 작업에 적히며 세션은 그대로다.

    브리지가 별도 스레드라 배치 도중 전환 dispatch 가 도달할 수 있다 — 구 계약은 전환을
    허용하고 캡처로 스탬프만 방어했지만, 검증·계획도 라이브 vm 을 볼 수 있어 남의 작업
    생성으로 샐 수 있었다. 이제 가드(시끄러운 거부)+캡처(이중 방어)를 함께 고정한다.
    """
    import hwpxfiller.webapp.screen_job as sj

    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _second_job(ctrl, tmp_path)                       # 전환 시도 대상(공고서2) 등록
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})

    real_batch = sj.generate_batch

    def _switch_midflight(*a, **k):
        result = real_batch(*a, **k)
        with pytest.raises(ValueError, match="생성이 진행 중"):   # 전환은 loud 거부
            ctrl.dispatch("select_job", {"name": "공고서2"})
        return result

    monkeypatch.setattr(sj, "generate_batch", _switch_midflight)
    assert ctrl.generate()["ok"] is True
    assert ctrl.registry.load("공고서").last_run_at != ""   # 실제로 돈 작업에 역사
    assert ctrl.registry.load("공고서2").last_run_at == ""  # 없던 실행을 지어내지 않는다
    assert ctrl.vm is not None and ctrl.vm.job.name == "공고서"  # 세션 불변(거부됐으니)


def test_stamp_uses_the_serialized_registry_path(tmp_path, monkeypatch):
    """스탬프는 레지스트리의 잠긴 경로로만 써서 직렬화 이탈을 막는다(#129).

    load→save 를 여기서 다시 손으로 엮으면 잠금 밖이라 에디터 저장과 lost update 가 난다
    (둘 중 늦게 착지한 저장이 상대 변경을 통째로 되돌린다). 그 회귀는 결과값으로는 잘 안
    드러나므로 경로 자체를 못박는다.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})

    calls: list = []
    real = ctrl.registry.stamp_last_run

    def spy(name, when, **kw):
        calls.append((name, when))
        return real(name, when, **kw)

    monkeypatch.setattr(ctrl.registry, "stamp_last_run", spy)
    assert ctrl.generate()["ok"] is True
    assert [n for n, _ in calls] == ["공고서"]


def test_stamp_failure_is_loud_not_silent(tmp_path, monkeypatch):
    """기록 실패를 삼키지 않는다(confirm-or-alarm) — 문서는 남기고 사유를 완료 요약에 병기."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    out = tmp_path / "out"
    ctrl.set_output_folder(str(out))
    ctrl.dispatch("ack_field", {"field": "추정가격"})

    def _boom(job, **kwargs):
        raise OSError("디스크 쓰기 거부")

    monkeypatch.setattr(ctrl.registry, "save", _boom)
    res = ctrl.generate()
    assert res["ok"] is True and res["succeeded"] == 2          # 생성 자체는 완주
    assert sorted(p.name for p in out.glob("*.hwpx")) == ["doc-001.hwpx", "doc-002.hwpx"]
    assert "실행 기록 저장에 실패했습니다" in res["summary"]
    assert "디스크 쓰기 거부" in res["summary"]                  # 사유 재진술
    assert res["level"] == "danger"                             # 조용한 초록 금지


def test_partial_failure_does_not_stamp_last_run_at(tmp_path, monkeypatch):
    """부분 실패는 완주가 아니다 — 무장 해제와 스탬프가 같은 술어를 공유한다(#129)."""
    import hwpxfiller.webapp.screen_job as sj

    class _FakeResult:
        ok = False
        output_path = "x.hwpx"
        error = "boom"

    class _FakeBatch:
        succeeded, failed, total = 1, 1, 2
        results = [_FakeResult()]

    monkeypatch.setattr(sj, "generate_batch", lambda *a, **k: _FakeBatch())
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})

    assert ctrl.generate()["failed"] == 1
    assert ctrl.registry.load("공고서").last_run_at == ""       # 미완주 = 역사 없음


def test_overwrite_confirm_flow(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})
    assert ctrl.generate()["ok"] is True  # 최초 생성

    # 같은 폴더 재생성 → 조용한 덮어쓰기 금지: 수치 합성 재진술 요구(총량·파괴분·신규분).
    res = ctrl.generate()
    assert res["ok"] is False and res.get("needs_overwrite") is True
    assert res["total"] == 2 and res["overwrite_count"] == 2 and res["new_count"] == 0
    assert len(res["conflict_names"]) == 2 and res["conflict_more"] == 0
    # 확인 후 재호출 → 생성.
    assert ctrl.generate(confirm_overwrite=True)["ok"] is True


# ---------------------------------------------- 본문 존 거울
def _mirror_job(tmp_path) -> JobRegistry:
    """거울 케이스용 작업 — 채움(text)·미입력(amount, rec0 빈값)·의도적 빈칸 3필드."""
    template = tmp_path / "t.hwpx"
    _write_template(template, ["공고명", "추정가격", "비고"])
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(
        name="공고서", template_path=str(template),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source="bidNtceNm"),
            FieldMapping(template_field="추정가격", source="presmptPrce", type="amount"),
            FieldMapping(template_field="비고", type="blank"),
        ]),
        filename_pattern="doc-{{seq:001}}",
    ))
    return reg


def test_mirror_value_display_filled_sample_missing_blank(tmp_path):
    """거울 행 = 필드별 값 집계(재구현 아님, mapped_records 소비). 상태별 값·표시형 병기."""
    ctrl = JobController(_mirror_job(tmp_path), lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    m = {r["name"]: r for r in ctrl.snapshot()["mirror"]}
    # 공고명: 선택 2행 값이 달라 표본 명시 병기(S10) — 표본 = 표시순 첫 행(최신 행) 값.
    assert m["공고명"]["state"] == "filled"
    assert m["공고명"]["value"] == "사무비품 (표본 · 외 1개 값)"
    assert m["공고명"]["formatted"] is False
    # 추정가격: rec0 빈값 → missing, 값 = 빈 행수 재진술(낙관 서사 해소), amount → 표시형.
    assert m["추정가격"]["state"] == "missing"
    assert "선택 2행 중 1행" in m["추정가격"]["value"]
    assert m["추정가격"]["formatted"] is True
    # 비고: 의도적 빈칸 표지.
    assert m["비고"]["state"] == "blank" and m["비고"]["value"] == "(비움 확정)"


def test_mirror_filled_same_value_is_not_labeled_sample(tmp_path):
    """선택 N>1 이라도 값이 다 같으면 표본 라벨 없이 그냥 값(허위 '행마다 다름' 금지)."""
    ctrl = JobController(_mirror_job(tmp_path), lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    csv = tmp_path / "same.csv"
    csv.write_text("bidNtceNm,presmptPrce\n동일공고,100\n동일공고,200\n", encoding="utf-8")
    _mount_all(ctrl, str(csv))
    m = {r["name"]: r for r in ctrl.snapshot()["mirror"]}
    assert m["공고명"]["value"] == "동일공고"  # 표본 라벨 없음


def test_mirror_sample_counts_distinct_values_not_rows(tmp_path):
    """표본 병기 '외 K개 값'은 서로 다른 값 수로 센다 — 대부분 같고 하나만 달라도 과장 없음."""
    ctrl = JobController(_mirror_job(tmp_path), lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    csv = tmp_path / "mostly_same.csv"
    # 4행 '전산장비' + 1행 '사무비품' → 서로 다른 값은 2종(외 1개), 행 수(5)로 세면 과장(외 4).
    csv.write_text(
        "bidNtceNm,presmptPrce\n전산장비,1\n전산장비,2\n전산장비,3\n전산장비,4\n사무비품,5\n",
        encoding="utf-8",
    )
    _mount_all(ctrl, str(csv))
    m = {r["name"]: r for r in ctrl.snapshot()["mirror"]}
    # 표본 = 표시순 첫 행(최신 행='사무비품') 값, '외 K'는 서로 다른 값 수(2종-1=1).
    assert m["공고명"]["value"] == "사무비품 (표본 · 외 1개 값)"  # 행 수 아님(외 4행 금지)


def test_mirror_empty_when_no_selection(tmp_path):
    """선택 0 = 생성될 문서 없음 → 거울 행 없음(빈 값을 '채움'으로 오도하지 않는다)."""
    ctrl = JobController(_mirror_job(tmp_path), lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("set_none", {})
    snap = ctrl.snapshot()
    assert snap["mirror"] == [] and snap["drift"] == []


def test_mirror_drift_split_into_blocking_list(tmp_path):
    """drift(구조 불일치) 필드는 거울 표에서 빠져 별도 drift 목록으로 — 차단 배너 분리(결정 36)."""
    template = tmp_path / "t.hwpx"
    _write_template(template, ["공고명", "유령"])  # 유령 = 템플릿 전용(매핑 미커버) → drift
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(
        name="공고서", template_path=str(template),
        mapping=MappingProfile(mappings=[FieldMapping(template_field="공고명", source="bidNtceNm")]),
        filename_pattern="doc-{{seq:001}}",
    ))
    ctrl = JobController(reg, lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    snap = ctrl.snapshot()
    assert snap["drift"] == ["유령"]
    assert [r["name"] for r in snap["mirror"]] == ["공고명"]  # drift 필드는 표에서 제외


def test_snapshot_carries_unresolved_name_tokens_for_banner(tmp_path):
    """미해소 파일명 토큰이 스냅샷에 실린다(#128) — 거울 자리 차단 배너의 재료.

    종전엔 이 danger 가 게이트 캡션 한 줄로만 살아서, 거울은 전 행 「채움」으로 건강해
    보이고 재진술 블록은 danger 라 말없이 사라졌다(신호 없는 차단). 게이트 문안과 같은
    사실이므로 산출은 run_state 단일 출처를 그대로 싣는다.
    """
    template = tmp_path / "t.hwpx"
    _write_template(template, ["공고명"])
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(
        name="공고서", template_path=str(template),
        mapping=MappingProfile(mappings=[FieldMapping(template_field="공고명", source="bidNtceNm")]),
        filename_pattern="doc-{{미해소}}",
    ))
    ctrl = JobController(reg, lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    snap = ctrl.snapshot()
    assert snap["name_tokens"] == ["미해소"]
    assert snap["gate"]["level"] == "danger" and snap["gate"]["enabled"] is False
    # 거울 표는 여전히 「채움」으로 건강하다 — 그래서 배너가 없으면 신호가 사라진다.
    assert [r["state"] for r in snap["mirror"]] == ["filled"]
    ctrl.dispatch("select_job", {"name": ""})           # 미겨눔 골격도 키를 갖춘다
    assert ctrl.snapshot()["name_tokens"] == []


def test_name_token_banner_yields_to_template_read_error(tmp_path):
    """게이트 서열을 거울이 재유도하지 않는다(리뷰 F2) — 템플릿을 못 읽으면 그쪽이 이긴다.

    토큰 미해소는 템플릿 상태와 무관하게 참이라, 사실만 보고 배너를 그리면 게이트는
    "구조를 읽을 수 없다"고 막는데 거울은 "파일명을 고치라"고 말한다 — 사용자를 엉뚱한
    수리로 보낸다(#128 이 없앤 어긋남의 반대 방향 재발).
    """
    template = tmp_path / "t.hwpx"
    _write_template(template, ["공고명"])
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(
        name="공고서", template_path=str(template),
        mapping=MappingProfile(mappings=[FieldMapping(template_field="공고명", source="bidNtceNm")]),
        filename_pattern="doc-{{미해소}}",
    ))
    ctrl = JobController(reg, lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    assert ctrl.snapshot()["name_tokens"] == ["미해소"]     # 정상 지형에선 토큰이 이긴다
    template.write_bytes(b"not a zip")                      # 템플릿 손상 → 구조 재읽기 실패
    snap = ctrl.snapshot()
    assert snap["gate"]["level"] == "danger" and "읽을 수 없어" in snap["gate"]["text"]
    assert snap["name_tokens"] == [], (
        "템플릿을 못 읽는데 거울이 파일명 토큰 배너를 세웁니다 — 게이트와 다른 수리를 지시."
    )


def test_select_none_closes_record_gate(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})
    assert ctrl.snapshot()["gate"]["enabled"] is True
    ctrl.dispatch("set_none", {})
    snap = ctrl.snapshot()
    assert snap["selected_count"] == 0
    assert snap["gate"]["enabled"] is False and "생성할 문서" in snap["gate"]["text"]


def test_deselect_job_returns_to_empty_panel(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.dispatch("select_job", {"name": ""})  # 선택 해제
    snap = ctrl.snapshot()
    assert snap["has_job"] is False and snap["job_name"] == ""


def test_refresh_invalidates_session_when_job_deleted(tmp_path):
    """master-detail 불변식: 선택된 작업이 다른 화면에서 삭제돼 레지스트리에서 사라지면
    refresh 가 세션을 무효화한다 — 존재하지 않는 작업의 라이브 세션이 활성 생성 버튼과 함께
    남아 유령 작업에서 생성되는 것을 막는다."""
    reg = _registry(tmp_path)
    ctrl = JobController(reg, lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    assert ctrl.snapshot()["has_job"] is True

    reg.delete("공고서")  # 다른 화면이 삭제(그 화면으로 가려면 작업 화면 이탈 → 복귀 시 refresh)
    result = ctrl.dispatch("refresh", {})
    assert result == {
        "notice": "'공고서' 작업이 다른 화면에서 삭제되어 열어 둔 실행 세션을 닫았습니다."
    }
    snap = ctrl.snapshot()
    assert snap["has_job"] is False and snap["job_name"] == ""
    # 유령 작업 생성 시도도 loud 차단(세션 무효화 후).
    res = ctrl.generate()
    assert res["ok"] is False


def test_refresh_keeps_session_when_job_still_present(tmp_path):
    """refresh 가 멀쩡한 세션을 건드리지 않는다 — 무효화는 삭제/개명된 작업에만(과잉 리셋 방지)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    assert ctrl.dispatch("refresh", {}) is None
    snap = ctrl.snapshot()
    assert snap["has_job"] is True and snap["job_name"] == "공고서"
    assert snap["record_count"] == 2  # 데이터 겨눔도 보존


def test_unknown_action_is_loud(tmp_path):
    ctrl, _ = _controller(tmp_path)
    with pytest.raises(ValueError, match="알 수 없는 작업 화면 액션"):
        ctrl.dispatch("frobnicate", {})


def test_generate_without_job_is_loud_not_silent(tmp_path):
    ctrl, _ = _controller(tmp_path)
    res = ctrl.generate()
    assert res["ok"] is False and "작업" in res["error"]


# ---------------------------------------------------------------- #87 구조 가드(링1 위임)
def test_panel_delegates_to_ring1_view_models(tmp_path):
    """#87: 패널이 링1 VM 을 **소유·위임**한다 — 재구현이 아니라 임포트한 VM 인스턴스.

    작업 선택 시 세션의 결정 상태가 RunViewModel/SelectionModel 그 자체여야 한다(별도
    스냅샷 클래스로 우회 재구현하지 않는다). 정적 임포트·무재구현 가드는 test_architecture.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    assert isinstance(ctrl.vm, RunViewModel)
    assert isinstance(ctrl.selection, SelectionModel)


# ---------------------------------------------------------------- #26 #6 — 2소스(등록 데이터)
from hwpxfiller.core.dataset_pool import DatasetPoolItem, DatasetPoolRegistry


def _pool_controller(tmp_path):
    pool = DatasetPoolRegistry(tmp_path / "pool")
    pushes: list = []
    ctrl = JobController(
        _registry(tmp_path), lambda s, snap: pushes.append((s, snap)),
        pool_registry=pool,
    )
    return ctrl, pool


def test_load_pool_targets_excel_reference(tmp_path):
    """등록 데이터 겨눔 성공 — 실행 시점 재읽기(싱크) + 소스 병기 라벨 + 선택 초기화."""
    ctrl, pool = _pool_controller(tmp_path)
    pool.save(DatasetPoolItem(name="7월공고", kind="excel", opts={"path": _data_csv(tmp_path)}))
    ctrl.dispatch("select_job", {"name": "공고서"})
    res = ctrl.dispatch("load_pool", {"name": "7월공고"})
    assert res["ok"] is True and res["label"] == "등록 데이터: 7월공고"
    snap = ctrl.snapshot()
    assert snap["data_source_label"] == "등록 데이터: 7월공고"
    assert snap["record_count"] == 2


def test_load_pool_without_job_mounts_session_data(tmp_path):
    """데이터-우선(§18.2): 작업 미선택에도 풀 겨눔이 세션에 마운트된다 — 구 「작업 먼저」
    전제의 개정. 마운트 직후 선택 0건 + 후보(§18.4) + prework 게이트가 다음 할 일을 말한다."""
    ctrl, pool = _pool_controller(tmp_path)
    pool.save(DatasetPoolItem(name="7월공고", kind="excel", opts={"path": _data_csv(tmp_path)}))
    res = ctrl.dispatch("load_pool", {"name": "7월공고"})
    assert res["ok"] is True
    snap = ctrl.snapshot()
    assert snap["has_job"] is False and snap["has_data"] is True
    assert snap["record_count"] == 2 and snap["selected_count"] == 0
    # 후보 = 현재 데이터 fields 로 판정(§18.4) — '공고서'는 필수 소스가 전부 있어 available.
    assert [c["name"] for c in snap["candidates"]["top"]] == ["공고서"]
    assert snap["gate"]["enabled"] is False and "항목을 선택" in snap["gate"]["text"]
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})
    assert "문서 작업" in ctrl.snapshot()["gate"]["text"]  # 다음 할 일 = 작업 선택


# --------------------------------------- 기본 데이터셋 자동 조준(#53-A, A-1-11)
# 성공은 ok로 재진술하고 실패는 warn과 미겨눔으로 남기는 조용한 폴백 금지 계약을 가드한다.
def _job_with_default(ctrl, pool, tmp_path, ref, *, register=True):
    """'공고서' 작업에 기본 데이터셋 참조를 붙여 재저장. register=True 면 동명 CSV 풀 항목 등록."""
    job = ctrl.registry.load("공고서")
    job.default_dataset_ref = ref
    ctrl.registry.save(job, allow_overwrite=True)
    if register:
        pool.save(DatasetPoolItem(name=ref, kind="excel", opts={"path": _data_csv(tmp_path)}))


def test_select_job_auto_aims_default_dataset(tmp_path):
    """기본 데이터셋 참조가 있으면 작업 선택 시 실행 시점에 다시 읽어 자동 조준(#53-A)."""
    ctrl, pool = _pool_controller(tmp_path)
    _job_with_default(ctrl, pool, tmp_path, "7월공고")
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["has_data"] is True and snap["record_count"] == 2      # 자동 재읽기(싱크)
    assert snap["data_source_label"] == "등록 데이터: 7월공고"
    assert snap["selected_count"] == 0                                  # 겨눔 = 선택 0건(§18.2)
    assert snap["data_notice"]["level"] == "ok" and "자동" in snap["data_notice"]["text"]


def test_auto_aim_does_not_clobber_mounted_session_data(tmp_path):
    """세션에 이미 마운트된 데이터가 있으면 기본 참조 자동 조준을 건너뛴다 — 참조가
    사용자의 현재 데이터를 조용히 덮으면 §18.2(성공 전 현재 runtime 미파기) 위반이다."""
    ctrl, pool = _pool_controller(tmp_path)
    _job_with_default(ctrl, pool, tmp_path, "7월공고")
    other = tmp_path / "직접.csv"
    other.write_text("bidNtceNm,presmptPrce\n수동데이터,900\n", encoding="utf-8")
    ctrl.load_data_path(str(other))                      # 작업 미선택 상태의 수동 마운트
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["data_label"] == "직접.csv"              # 마운트 데이터 생존(자동 조준 생략)
    assert snap["record_count"] == 1 and snap["selected_count"] == 1
    assert snap["data_notice"] is None                   # 조준 재진술 없음 = 실제로 안 했다


def test_select_job_dead_default_ref_is_loud_no_silent_fallback(tmp_path):
    """죽은 기본 참조는 조용한 폴백 금지 — 미겨눔 + 원인·복구 동선(다시 연결)을 재진술(#53-A)."""
    ctrl, pool = _pool_controller(tmp_path)
    _job_with_default(ctrl, pool, tmp_path, "없는참조", register=False)
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["has_data"] is False                       # 자동 겨눔 실패 = 미겨눔(폴백 없음)
    assert snap["data_source_label"] == ""
    assert snap["data_notice"]["level"] == "warn"
    assert "없는참조" in snap["data_notice"]["text"] and "다시 연결" in snap["data_notice"]["text"]


def test_auto_aim_nara_ref_is_frozen_warn(tmp_path):
    """기본 참조가 나라 항목이면 자동 조준도 동결 거절 warn — 공유 관문 문구 그대로(#53-A)."""
    ctrl, pool = _pool_controller(tmp_path)
    pool.save(DatasetPoolItem(
        name="나라기본", kind="nara", opts={"bgn_dt": "202607010000", "end_dt": "202607080000"}))
    _job_with_default(ctrl, pool, tmp_path, "나라기본", register=False)
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["has_data"] is False and snap["data_notice"]["level"] == "warn"
    assert "지원되지 않습니다" in snap["data_notice"]["text"]


def test_auto_aim_ambiguous_sheet_ref_is_warn(tmp_path):
    """기본 참조가 시트 미지정 다중시트면 자동 조준도 조용한 첫 시트 대신 warn 거절(#33·#53-A)."""
    ctrl, pool = _pool_controller(tmp_path)
    pool.save(DatasetPoolItem(name="모호기본", kind="excel", opts={"path": str(MULTI_SHEET)}))
    _job_with_default(ctrl, pool, tmp_path, "모호기본", register=False)
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["has_data"] is False and snap["data_notice"]["level"] == "warn"
    assert "시트" in snap["data_notice"]["text"]


def test_manual_data_clears_auto_aim_notice(tmp_path):
    """자동 조준 후 사용자가 직접 데이터를 겨누면 자동 조준 재진술이 소거된다(임시 데이터=기본 불변)."""
    ctrl, pool = _pool_controller(tmp_path)
    _job_with_default(ctrl, pool, tmp_path, "7월공고")
    ctrl.dispatch("select_job", {"name": "공고서"})
    assert ctrl.snapshot()["data_notice"] is not None
    _mount_all(ctrl, _data_csv(tmp_path))               # 수동 파일 겨눔
    snap = ctrl.snapshot()
    assert snap["data_notice"] is None
    assert snap["data_source_label"].startswith("파일:")
    assert ctrl.registry.load("공고서").default_dataset_ref == "7월공고"  # 임시 override, 기본 불변


# --------------------------------------------- 템플릿 다시 연결(#67, A-1-2 계열)
# 경로 재진술·드리프트 병기·읽기불가 하드차단·선택 작업 stale VM 재적재를 가드한다.
def test_relink_template_needs_confirm_restates_paths(tmp_path):
    """1차 호출 = 기존→새 경로 재진술 확인 요구. 구조 동일이면 드리프트 문구 없음(#67)."""
    ctrl, _ = _controller(tmp_path)
    new_tpl = tmp_path / "moved.hwpx"
    _write_template(new_tpl, ["공고명", "추정가격"])       # 같은 구조 — 드리프트 0
    res = ctrl.dispatch("relink_template", {"name": "공고서", "path": str(new_tpl)})
    assert res["ok"] is True and res["needs_confirm"] is True
    assert "t.hwpx" in res["confirm_text"] and "moved.hwpx" in res["confirm_text"]  # 양경로 재진술
    assert "구조가" not in res["confirm_text"]             # 무드리프트 = 소음 금지
    assert ctrl.registry.load("공고서").template_path.endswith("t.hwpx")  # 확인 전 durable 불변


def test_relink_template_drift_restated_in_confirm(tmp_path):
    """새 파일 구조가 확정 매핑과 다르면 확인 문구에 드리프트 상세+생성 차단 경고 병기(#67)."""
    ctrl, _ = _controller(tmp_path)
    new_tpl = tmp_path / "changed.hwpx"
    _write_template(new_tpl, ["공고명", "낙찰자"])         # 추정가격 소멸 + 낙찰자 유입
    res = ctrl.dispatch("relink_template", {"name": "공고서", "path": str(new_tpl)})
    assert res["needs_confirm"] is True and "구조가" in res["confirm_text"]
    assert "낙찰자" in res["confirm_text"] and "추정가격" in res["confirm_text"]  # describe() 단일 출처
    assert "생성이 차단됩니다" in res["confirm_text"]      # 기존 게이트 백스톱 재진술


def test_relink_template_unreadable_is_blocked(tmp_path):
    """읽을 수 없는 파일은 확인으로도 템플릿이 될 수 없다 — 하드 차단 + JSON 불변(#67)."""
    ctrl, _ = _controller(tmp_path)
    res = ctrl.dispatch(
        "relink_template",
        {"name": "공고서", "path": str(tmp_path / "없는파일.hwpx"), "confirm": True})
    assert res["ok"] is False and "새 템플릿을 읽을 수 없습니다" in res["error"]
    assert ctrl.registry.load("공고서").template_path.endswith("t.hwpx")


def test_relink_selected_job_reloads_vm_and_restates(tmp_path):
    """지금 선택된 작업을 재연결하면 stale VM 을 재적재하고 상태 초기화를 재진술한다(#67)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))               # 데이터 겨눔(재적재로 초기화될 상태)
    new_tpl = tmp_path / "moved.hwpx"
    _write_template(new_tpl, ["공고명", "추정가격"])
    res = ctrl.dispatch(
        "relink_template", {"name": "공고서", "path": str(new_tpl), "confirm": True})
    assert res["relinked"] is True
    assert "다시 불러왔으니" in res["restated"]             # 조용한 상태 소실 금지(재적재 재진술)
    assert ctrl.vm.job.template_path == str(new_tpl)       # VM 재구성


# ------------------------------------------------ confirm-or-alarm 생성 계약
def test_load_data_honors_confirmed_sheet(tmp_path):
    """다중 시트 확정 게이트(#33) — load_data_path(sheet=) 가 확정 시트를 관통.

    작업 선택 후 낙찰현황(3건)을 확정하면 첫 시트(공고목록 2건)가 아니라 그 시트가 실린다 —
    조용한 첫 시트 강등이 아니라 확정값 반영(test_webapp_bridge 의 job 컨트롤러측 대응물).
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, str(MULTI_SHEET), sheet="낙찰현황")
    snap = ctrl.snapshot()
    assert snap["data_label"] == "multi_sheet.xlsx"
    assert snap["has_data"] is True and snap["record_count"] == 3


def test_record_names_follow_selection_not_invented(tmp_path):
    """미선택 행 이름은 지어내지 않는다(F33) — {{seq}}·충돌 접미사는 선택 집합에
    따라 달라지므로 선택 변경 시 남은 행 이름이 생성 결과대로 재계산된다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("toggle_record", {"index": 0, "value": False})
    rows = ctrl.snapshot()["records"]  # 표시순: rows[0]=원본 rec1(최신), rows[1]=원본 rec0
    assert rows[1]["name"] == "" and rows[1]["selected"] is False   # 미선택 = 이름 없음
    # 남은 1건만 생성하면 그 파일이 doc-001 — 미리보기도 같은 사실을 말한다.
    assert rows[0]["name"] == "doc-001.hwpx" and rows[0]["selected"] is True


def test_generate_uses_previewed_name_timestamp(tmp_path):
    """미리보기가 보여준 시각 = 생성 파일명 시각(RC-02 표시=확인=생성).

    시·분·초 date 토큰 패턴에서 미리보기 스냅샷과 생성 클릭 사이 시계가 흘러도, generate 는
    마지막 미리보기(``_names_now``)의 시각을 재사용해 화면이 보여준 실파일명 그대로 생성한다.
    """
    ctrl, _ = _controller(tmp_path)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "doc-{{date:HHmmSS}}-{{seq}}"
    ctrl.registry.save(job, allow_overwrite=True)
    _rereview(ctrl)   # 파일명 규칙 변경의 검토 요구는 이 테스트의 대상이 아니다
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    out = tmp_path / "out"
    ctrl.set_output_folder(str(out))
    ctrl.dispatch("ack_field", {"field": "추정가격"})

    # 스냅샷 미리보기가 시각을 캡처 → 이후 시계 전진을 결정적으로 모사(주입) → 생성이 캡처값 재사용.
    assert ctrl.snapshot()["records"][0]["name"].startswith("doc-")
    ctrl._names_now = datetime(2026, 1, 2, 3, 4, 5)
    res = ctrl.generate()
    assert res["ok"] is True
    made = sorted(p.name for p in out.glob("*.hwpx"))
    assert made and all(n.startswith("doc-030405-") for n in made)  # 주입 시각 그대로


def test_snapshot_reports_template_missing_only_when_file_gone(tmp_path):
    """template_missing 은 파일이 실제로 없을 때만 True(F30) — 웹이 이 플래그로
    「템플릿 다시 연결」 복구 동선을 조건부 노출한다(Python 층 실행 — JS 렌더 가드와 별개)."""
    ctrl, _ = _controller(tmp_path)
    snap = ctrl.initial()
    assert snap["template_missing"] is False               # 미선택 = 버튼 표면 자체가 없음
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["template_missing"] is False               # 정상 = 복구 동선 숨김
    Path(snap["template_path"]).unlink()                    # 템플릿 파일 소실 재현
    assert ctrl.snapshot()["template_missing"] is True      # 부재 = 복구 동선 노출


def test_unresolved_pattern_gate_surfaces_in_snapshot(tmp_path):
    """미해소 파일명 토큰 작업 = 스냅샷 게이트 danger 차단 + 생성 백스톱(F34)."""
    ctrl, _ = _controller(tmp_path)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "공고서-{{ID}}"                 # 101 워크스루 실증 지뢰(데이터에 ID 없음)
    ctrl.registry.save(job, allow_overwrite=True)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    snap = ctrl.snapshot()
    assert snap["gate"]["enabled"] is False and snap["gate"]["level"] == "danger"
    assert "{{ID}}" in snap["gate"]["text"]
    res = ctrl.generate()
    assert res["ok"] is False and "{{ID}}" in res["error"]  # 생성 백스톱도 리터럴 방지


# ------------------------------------------------- 필터 배선
def _session(tmp_path):
    """작업 선택 + 데이터 겨눔까지 마친 컨트롤러 — 필터 계약 테스트 공용."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    return ctrl, pushes


def test_filter_lifecycle_data_scoped(tmp_path):
    """필터 = 데이터 스코프(§18.10, 결정 24 개정): 데이터 겨눔에 생성, **작업 전환·해제에
    생존**(데이터-우선 — 필터는 가시성만이라 작업과 무관), 데이터 교체에 재생성."""
    ctrl, _ = _session(tmp_path)
    assert ctrl.filter is not None
    # 매핑 확정 유형(text)이 힌트로 우선한다 — 수치 열이어도 사용자 확정 존중.
    snap = ctrl.snapshot()
    kinds = {c["name"]: c["kind"] for c in snap["filter"]["columns"]}
    assert kinds == {"bidNtceNm": "text", "presmptPrce": "text"}
    ctrl.dispatch("filter_search", {"text": "전산"})
    assert ctrl.filter.is_active()
    ctrl.dispatch("select_job", {"name": ""})  # 작업 해제 — 데이터 존은 그대로(§18.2)
    assert ctrl.filter is not None and ctrl.filter.is_active()
    assert ctrl.snapshot()["filter"]["active"] is True
    # 데이터 교체 = 필터 재생성(열 지형이 바뀐다 — 결정 24의 존속 부분).
    other = tmp_path / "e.csv"
    other.write_text("다른열\n값\n", encoding="utf-8")
    ctrl.load_data_path(str(other))
    assert ctrl.filter is not None and not ctrl.filter.is_active()


def test_filter_search_shapes_table_and_chips(tmp_path):
    """전열 검색 → 재현 OR 그룹: 가시 행·가지·칩·셀 세그먼트가 스냅샷으로 온다."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("filter_search", {"text": "전산"})
    snap = ctrl.snapshot()
    t = snap["table"]
    assert t["columns"] == [
        {"name": "bidNtceNm", "kind": "text"},
        {"name": "presmptPrce", "kind": "text"},
    ]
    assert t["visible_count"] == 1 and [r["index"] for r in t["rows"]] == [0]
    assert snap["filter"]["branches"] == ["bidNtceNm"]
    assert any("전산" in c for c in snap["filter"]["chips"])
    # 셀 = 하이라이트 세그먼트(파이썬이 잘라 조각으로 — 인덱스 무전달, jamo 계약).
    # 파이썬 층에선 튜플, json.dumps 가 배열로 직렬화한다.
    cells = t["rows"][0]["cells"]
    assert cells[0] == [("전산", True), ("장비", False)]
    assert cells[1] == []  # 빈 셀 = 빈 세그먼트


def test_set_all_is_additive_over_matches(tmp_path):
    """「전체 선택」 = 매치 전체 가산(결정 4·26) — 필터 밖 기존 선택은 유지(관통, 결정 3)."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("filter_search", {"text": "전산"})   # 매치 = 0행뿐
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("toggle_record", {"index": 1, "value": True})  # 필터 밖 행 직접 선택
    ctrl.dispatch("set_all", {})                        # 매치(0행) 가산
    snap = ctrl.snapshot()
    assert snap["selected_count"] == 2                  # 1행 선택이 지워지지 않았다
    # 필터 밖 선택 = 스트립 소재(결정 3 — 상시 가시).
    assert [r["index"] for r in snap["table"]["hidden_selected"]] == [1]


def test_select_range_propagates_anchor_state(tmp_path):
    """Shift 범위 = 앵커 상태 전파(결정 2) — 선택도 해제도 범위로."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("select_range", {"indices": [0, 1], "value": True})
    assert ctrl.snapshot()["selected_count"] == 2
    ctrl.dispatch("select_range", {"indices": [1], "value": False})
    assert ctrl.snapshot()["selected_count"] == 1


def test_restate_origin_by_set_comparison(tmp_path):
    """선택 유래 = 집합 비교 무상태 판정: 매치 전체=정의-유래, 이탈=직접+수치 병기(S4)."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("filter_search", {"text": "전산"})
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("set_all", {})
    r = ctrl.snapshot()["restate"]
    assert r["origin"] == "definition" and r["filter_active"] is True
    assert r["in_def"] == 1 and r["extra"] == 0
    ctrl.dispatch("toggle_record", {"index": 1, "value": True})  # 정의 밖 가산 → 혼합
    r = ctrl.snapshot()["restate"]
    assert r["origin"] == "manual" and r["in_def"] == 1 and r["extra"] == 1
    assert set(r["sample"]) <= {0, 1} and len(r["sample"]) <= 3


def test_filter_range_on_amount_column_and_inline_error(tmp_path):
    """범위 조건 배선 — 매핑 amount 확정 열, 오독 피연산자는 인라인 오류 dict(비폭발)."""
    template = tmp_path / "t2.hwpx"
    _write_template(template, ["공고명", "추정가격"])
    reg = JobRegistry(tmp_path / "jobs2")
    reg.save(Job(
        name="금액작업", template_path=str(template),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source="bidNtceNm"),
            FieldMapping(template_field="추정가격", source="presmptPrce", type="amount"),
        ]),
        filename_pattern="doc-{{seq:001}}",
    ))
    ctrl = JobController(reg, lambda s, snap: None)
    ctrl.dispatch("select_job", {"name": "금액작업"})
    _mount_all(ctrl, _data_csv(tmp_path))
    kinds = {c["name"]: c["kind"] for c in ctrl.snapshot()["filter"]["columns"]}
    assert kinds["presmptPrce"] == "amount"              # 매핑 확정 유형 힌트
    res = ctrl.dispatch("filter_col_range", {
        "column": "presmptPrce", "first": {"op": "ge", "operand": "1억"}})
    assert res["ok"] is False and "읽을 수 없습니다" in res["error"]
    res = ctrl.dispatch("filter_col_range", {
        "column": "presmptPrce", "first": {"op": "ge", "operand": "1000000"}})
    assert res["ok"] is True
    assert ctrl.snapshot()["table"]["visible_count"] == 1  # 2000000 행만
    # 빈 첫 절 = 조건 해제.
    res = ctrl.dispatch("filter_col_range", {"column": "presmptPrce", "first": None})
    assert res["ok"] is True and ctrl.snapshot()["table"]["visible_count"] == 2


def test_filter_panel_query_returns_options_and_state(tmp_path):
    """열 패널 질의 — 현 조건 + 값 목록((빈값)="" 일급, 말미)."""
    ctrl, _ = _session(tmp_path)
    res = ctrl.dispatch("filter_panel", {"column": "presmptPrce"})
    assert res["kind"] == "text" and res["checked"] is None and res["range"] is None
    assert res["options"] == ["2000000", ""]             # 빈 셀 = 정식 값, 말미
    ctrl.dispatch("filter_col_values", {"column": "presmptPrce", "values": [""]})
    res = ctrl.dispatch("filter_panel", {"column": "presmptPrce"})
    assert res["checked"] == [""]
    assert ctrl.snapshot()["table"]["visible_count"] == 1  # 빈값 행(0행)만


def test_filter_actions_without_data_are_loud(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    with pytest.raises(ValueError, match="데이터를 먼저"):
        ctrl.dispatch("filter_search", {"text": "x"})


def test_set_all_reports_added_count_for_dead_button_honesty(tmp_path):
    """「전체 선택」 반환 added — 전멸 필터의 무동작(0)을 표면이 알린다(리뷰 #9)."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("set_none", {})
    assert ctrl.dispatch("set_all", {}) == {"added": 2}      # 필터 없음 = 전체
    ctrl.dispatch("filter_search", {"text": "존재하지않는말"})  # 전멸
    assert ctrl.dispatch("set_all", {}) == {"added": 0}      # 무동작 정직 보고
    ctrl.dispatch("filter_search", {"text": "전산"})
    ctrl.dispatch("set_none", {})
    assert ctrl.dispatch("set_all", {}) == {"added": 1}      # 매치만 가산


def test_table_cell_preserves_falsy_values(tmp_path):
    """셀 텍스트 = cell_text 단일 출처(리뷰 #8) — 0 이 빈칸으로 붕괴하지 않는다."""
    ctrl, _ = _session(tmp_path)
    ctrl.vm.records[1]["presmptPrce"] = 0                    # 풀(JSON) 유래 수치형 재현
    snap = ctrl.snapshot()
    row1 = next(r for r in snap["table"]["rows"] if r["index"] == 1)
    assert row1["cells"][1] == [("0", False)]                # 필터가 보는 그대로 표면도


# ------------------------------------------------- 세션 가드(결정 26·27)
def _data_csv3(tmp_path) -> str:
    """3행 코퍼스 — 2행 판에선 '정의 밖 가산'이 곧 전체 선택(비무장)이 되어 무장 케이스를
    못 가른다(가드 술어의 전체=1클릭 재현 절과 겹침)."""
    csv = tmp_path / "d3.csv"
    csv.write_text(
        "bidNtceNm,presmptPrce\n전산장비,1000\n사무비품,2000000\n책상,500\n",
        encoding="utf-8",
    )
    return str(csv)


def _second_job(ctrl, tmp_path):
    """가드 전환 테스트용 두 번째 작업 — 같은 템플릿 재사용."""
    job = ctrl.registry.load("공고서")
    ctrl.registry.save(Job(
        name="공고서2", template_path=job.template_path, mapping=job.mapping,
        filename_pattern=job.filename_pattern,
    ))


def test_session_guard_for_cross_screen_query(tmp_path):
    """#268 리뷰 — 홈 삭제 가드 조회(session_guard_for): 이 화면이 무장 세션으로 겨눈
    작업명에만 가드 수치(+screen)를 내고, 비무장·타 작업·빈 이름은 None(홈 즉시 삭제)."""
    ctrl, _ = _session(tmp_path)
    assert ctrl.session_guard_for(ctrl.job_name) is None      # 비무장(전체 선택) = None
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})
    g = ctrl.session_guard_for(ctrl.job_name)
    assert g is not None and g["screen"] == "job" and g["armed"] is True
    assert g["sel_count"] == 1
    assert ctrl.session_guard_for("다른작업") is None
    assert ctrl.session_guard_for("") is None


def test_guard_armed_by_set_comparison(tmp_path):
    """무장 술어(결정 27) — 전체/빈/정의-유래/완주 집합은 비무장, 수작업 열거만 무장."""
    ctrl, _ = _session(tmp_path)
    _mount_all(ctrl, _data_csv3(tmp_path))
    assert ctrl.snapshot()["guard"]["armed"] is False       # 초기 전체 선택 = 1클릭 재현
    ctrl.dispatch("set_none", {})
    assert ctrl.snapshot()["guard"]["armed"] is False       # 빈 선택 = 지킬 것 없음
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})
    g = ctrl.snapshot()["guard"]
    assert g["armed"] is True and g["sel_count"] == 1       # 필터 없는 부분 선택 = 수작업
    # 정의-유래(매치 전체)는 정의줄이 재현을 담보 — 비무장.
    ctrl.dispatch("filter_search", {"text": "전산"})
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("set_all", {})
    g = ctrl.snapshot()["guard"]
    assert g["armed"] is False and g["filter_active"] is True and g["filter_parts"] == 1
    # 정의 이탈(밖 행 가산) = 무장 + 수치 병기 소재.
    ctrl.dispatch("toggle_record", {"index": 1, "value": True})
    g = ctrl.snapshot()["guard"]
    assert g["armed"] is True and g["in_def"] == 1 and g["extra"] == 1


def test_guard_disarmed_by_generation_completion(tmp_path):
    """완료 이벤트 = 무장 해제(결정 27) — 내역은 완료 존이 담보. 재편집 시 재무장."""
    ctrl, _ = _session(tmp_path)
    _mount_all(ctrl, _data_csv3(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("toggle_record", {"index": 1, "value": True})  # 수작업 1행(빈칸 없는 행)
    assert ctrl.snapshot()["guard"]["armed"] is True
    res = ctrl.generate()
    assert res["ok"] is True
    assert ctrl.snapshot()["guard"]["armed"] is False       # 완주 집합과 일치 = 해제
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})  # 완주 밖 재편집 = 재무장
    assert ctrl.snapshot()["guard"]["armed"] is True


def test_job_switch_preserves_session_data_and_selection(tmp_path):
    """작업 전환 = 보존(§18.2, 구 T1 스위치 가드의 재정의 승계): 무장 선택이어도 확인
    없이 즉시 전환한다 — 파괴가 없으니 물을 것도 없다(가드 문안=실제 상실 집합 규율).
    전환이 잃는 것은 실행 증거뿐(§19.10)이고 게이트 재검증이 그것을 강제한다."""
    ctrl, _ = _session(tmp_path)
    _second_job(ctrl, tmp_path)
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})  # 구 계약 기준 '무장' 선택
    assert ctrl.dispatch("select_job", {"name": "공고서2"}) is None  # 즉시 전환(무확인)
    snap = ctrl.snapshot()
    assert snap["job_name"] == "공고서2"
    assert snap["has_data"] is True and snap["record_count"] == 2    # 데이터 생존
    assert snap["selected_count"] == 1                               # 선택 생존
    assert [r["index"] for r in snap["records"] if r["selected"]] == [0]
    ctrl.dispatch("select_job", {"name": ""})                        # 해제도 데이터 존 보존
    snap = ctrl.snapshot()
    assert snap["has_job"] is False and snap["has_data"] is True
    assert snap["selected_count"] == 1


def test_guard_free_paths_do_not_block(tmp_path):
    """비무장 전환·같은 작업 재선택·레지스트리 소실 무효화는 가드에 안 걸린다."""
    ctrl, _ = _session(tmp_path)
    _second_job(ctrl, tmp_path)
    assert ctrl.dispatch("select_job", {"name": "공고서2"}) is None  # 비무장 = 즉시 전환
    assert ctrl.snapshot()["job_name"] == "공고서2"
    # 소실 무효화(C6) — 무장 상태여도 유령 세션으로 좌초시키지 않는다(confirm 승계).
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})
    ctrl.registry.delete("공고서2")
    ctrl.dispatch("refresh", {})
    assert ctrl.snapshot()["has_job"] is False


def test_guard_state_query_is_live_and_pushless(tmp_path):
    """guard_state = 실시간 무변이 질의(리뷰 #4·#8) — 판정은 항상 Python 이 지금 내린다.

    스냅샷 캐시(LAST.guard)는 generate(디스패치 밖, 무푸시) 뒤 stale — 표면 사전 확인이
    이 질의를 소비해 거짓 모달/무확인 통과 양방향 오판을 막는다. 질의는 push 도 없다.
    """
    ctrl, pushes = _session(tmp_path)
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})
    before = len(pushes)
    g = ctrl.dispatch("guard_state", {})
    assert g["armed"] is True and g["sel_count"] == 1
    assert len(pushes) == before                       # 무변이 질의 = push 생략


def test_guard_state_counts_acks_without_arming_on_them(tmp_path):
    """빈 값 확인은 **열거 성분이지 무장 성분이 아니다**(재작성 F1, 지도 §10.7.3).

    데이터 전환은 ``set_acquired`` 로 ack 를 재평가(=소거)하므로 문안이 그 손실을 말해야
    한다 — 그래서 수치를 싣는다. 반대로 ack 만으로 무장시키지는 않는다: 확인이 사라지면
    게이트가 다시 닫히는 안전 방향이라, 확인 왕복을 물리면 과경고다(결정 27 기준).
    """
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("set_none", {})
    assert ctrl.dispatch("guard_state", {})["ack_count"] == 0
    # 미입력 필드를 확인해도 무장하지 않는다(선택이 비어 있으므로).
    field = ctrl.snapshot()["mirror"]
    ctrl.vm.acknowledge("없는필드")  # 이름 무관 — 확인 집합의 크기만 센다
    g = ctrl.dispatch("guard_state", {})
    assert g["ack_count"] == 1 and g["armed"] is False, (g, field)
    # 실제로 데이터 전환이 확인을 지운다 — 열거가 거짓이 아님을 같은 테스트가 증명한다.
    other = tmp_path / "ack.csv"
    other.write_text("다른열\n값\n", encoding="utf-8")
    ctrl.load_data_path(str(other))
    assert ctrl.dispatch("guard_state", {})["ack_count"] == 0


def test_needs_confirm_does_not_push(tmp_path):
    """가드 차단 왕복은 무변이 — 동일 스냅샷 전량 재계산·재렌더를 얹지 않는다(리뷰 #8).

    구 표본이던 switch_job 가드는 데이터-우선 보존으로 죽었고(§18.2), 그다음 표본이던
    작업 삭제는 좌 목록과 함께 이 채널에서 걷혔다(F2 PR-B) — 살아 있는 needs_confirm 경로
    (그룹 병합 승격)로 같은 dispatch 불변식을 가드한다.
    """
    ctrl, pushes = _session(tmp_path)
    reg = ctrl.registry
    reg.save(Job(name="둘째"))
    reg.set_group("공고서", "입찰")
    reg.set_group("둘째", "수의")
    before = len(pushes)
    res = ctrl.dispatch("rename_group", {"name": "수의", "new": "입찰"})
    assert res["needs_confirm"] is True
    assert len(pushes) == before                       # 차단 = 상태 그대로 = push 생략


def test_partial_failure_keeps_guard_armed(tmp_path, monkeypatch):
    """부분 실패 런은 완주가 아니다(리뷰 #1) — 실패분 재시도 선택을 무확인 파괴에서 지킨다."""
    import hwpxfiller.webapp.screen_job as sj

    class _FakeResult:
        def __init__(self):
            self.ok = False
            self.output_path = "x.hwpx"
            self.error = "boom"  # describe_result_error 는 문자열 계약

    class _FakeBatch:
        succeeded, failed, total = 0, 1, 1
        results = [_FakeResult()]

    monkeypatch.setattr(sj, "generate_batch", lambda *a, **k: _FakeBatch())
    ctrl, _ = _session(tmp_path)
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("toggle_record", {"index": 1, "value": True})  # 수작업 1행
    res = ctrl.generate()
    assert res["ok"] is True and res["failed"] == 1
    assert ctrl.dispatch("guard_state", {})["armed"] is True     # 무장 유지(재시도 보호)


# ------------------------------------------- 건 연속성(직전 필터 재적용, 결정 28)
def test_reapply_slot_written_on_session_death_and_source_gated(tmp_path):
    """슬롯 = 정의 가진 세션이 죽을 때 덮어씀 · 소스 일치 게이트(다른 소스엔 미제공)."""
    ctrl, _ = _session(tmp_path)
    csv1 = _data_csv(tmp_path)
    ctrl.dispatch("filter_search", {"text": "전산"})
    assert ctrl.snapshot()["filter"]["reapply_available"] is False  # 아직 산 세션
    _mount_all(ctrl, _data_csv3(tmp_path))               # 데이터 교체 = 옛 정의 슬롯행
    snap = ctrl.snapshot()
    assert snap["filter"]["active"] is False                # 새 세션 필터는 백지
    assert snap["filter"]["reapply_available"] is False     # 소스 다름(d.csv≠d3.csv) — 게이트
    _mount_all(ctrl, csv1)                               # 같은 소스로 복귀
    assert ctrl.snapshot()["filter"]["reapply_available"] is True


def test_reapply_restores_definition_only_two_click_split(tmp_path):
    """재적용 = 정의(보기)만 복원 — 선택 불변(전체 선택과 2클릭 분리, 결정 28)."""
    ctrl, _ = _session(tmp_path)
    csv1 = _data_csv(tmp_path)
    ctrl.dispatch("filter_search", {"text": "전산"})
    _mount_all(ctrl, _data_csv3(tmp_path))               # 죽음 → 슬롯
    _mount_all(ctrl, csv1)                               # 같은 소스 재겨눔
    ctrl.dispatch("set_none", {})
    before_sel = ctrl.snapshot()["selected_count"]
    res = ctrl.dispatch("filter_reapply", {})
    assert res["ok"] is True and res["dropped"] == []
    snap = ctrl.snapshot()
    assert snap["filter"]["active"] is True
    assert snap["table"]["visible_count"] == 1              # 「전산」 재적용 — 보기 좁힘
    assert snap["selected_count"] == before_sel             # 선택은 그대로(2클릭 분리)


def test_reapply_full_drop_refused_without_touching_current(tmp_path):
    """전탈락 = 거부 + 이유(결정 28 백스톱, 외부 편집 edge) — 현 정의를 건드리지 않는다.

    열 결손은 같은 경로(소스 일치)인데 파일이 밖에서 편집돼 열 지형이 바뀐 경우에만
    생긴다(정본 명시 edge) — 다른 파일이면 소스 게이트가 애초에 재적용을 안 준다.
    """
    ctrl, _ = _session(tmp_path)
    csv1 = _data_csv(tmp_path)
    ctrl.dispatch("filter_col_values", {"column": "bidNtceNm", "values": ["전산장비"]})
    other = tmp_path / "other.csv"
    other.write_text("colA,colB\nx,y\n", encoding="utf-8")
    _mount_all(ctrl, str(other))                         # 죽음 → 슬롯(csv1 열 조건만)
    Path(csv1).write_text("colA,colB\nx,y\n", encoding="utf-8")  # 외부 편집 — 열 전면 교체
    _mount_all(ctrl, csv1)                               # 같은 경로 재겨눔 → 소스 일치
    assert ctrl.snapshot()["filter"]["reapply_available"] is True
    res = ctrl.dispatch("filter_reapply", {})
    assert res["ok"] is False and "하나도 남지 않아" in res["error"]
    assert ctrl.snapshot()["filter"]["active"] is False     # 부분 설치 없음(현 정의 무변이)


def test_reapply_without_slot_is_loud(tmp_path):
    ctrl, _ = _session(tmp_path)
    with pytest.raises(ValueError, match="직전 필터가 없습니다"):
        ctrl.dispatch("filter_reapply", {})


def test_reapply_gated_off_while_current_filter_is_live(tmp_path):
    """게이트 3연언의 '현 필터 빈 상태'(#127) — 조건을 세워 둔 위에는 재적용을 제공하지 않는다.

    제공했다면 클릭 한 번이 현 정의를 **확인 없이 원자 교체**한다(파괴 경로). 표면이 어긋나
    직접 호출되더라도 백엔드가 사유를 구분해 시끄럽게 거부한다.
    """
    ctrl, _ = _session(tmp_path)
    csv1 = _data_csv(tmp_path)
    ctrl.dispatch("filter_search", {"text": "전산"})
    _mount_all(ctrl, _data_csv3(tmp_path))               # 죽음 → 슬롯
    _mount_all(ctrl, csv1)                               # 같은 소스 복귀 = 슬롯·소스 연언 충족
    assert ctrl.snapshot()["filter"]["reapply_available"] is True   # 백지 상태에선 제공
    ctrl.dispatch("filter_col_values", {"column": "bidNtceNm", "values": ["사무비품"]})
    assert ctrl.snapshot()["filter"]["reapply_available"] is False  # 정의가 서면 회수
    with pytest.raises(ValueError, match="필터를 지운 뒤에"):
        ctrl.dispatch("filter_reapply", {})
    snap = ctrl.snapshot()
    assert snap["filter"]["active"] is True and snap["table"]["visible_count"] == 1
    ctrl.dispatch("filter_clear", {})                       # 지우면 복원 어포던스가 돌아온다
    assert ctrl.snapshot()["filter"]["reapply_available"] is True


def test_reapply_hint_describes_the_dying_session_not_the_incoming_data(tmp_path):
    """정의줄은 **죽는 세션의 데이터**로 지어야 한다(리뷰 F1) — 겨눔 경로가 레코드를 먼저
    갈아치우므로, 스태시 시점에 새로 지으면 남의 데이터에 대고 옛 정의를 묘사하게 된다.

    증상: 새 소스에 매치가 없으면 describe 가 「매치 없음」으로 떨어져, 원 소스로 돌아왔을 때
    버튼이 "매치 없음"이라는 거짓을 업고 뜬다(그 소스에선 멀쩡히 매치되는 정의인데도).
    """
    ctrl, _ = _session(tmp_path)
    csv1 = _data_csv(tmp_path)
    ctrl.dispatch("filter_search", {"text": "전산"})
    alive = ctrl.snapshot()["filter"]["definition"]
    assert "전산" in alive and "매치 없음" not in alive
    other = tmp_path / "other.csv"                       # 열도 값도 다른 소스(매치 0)
    other.write_text("colA,colB\nx,y\n", encoding="utf-8")
    _mount_all(ctrl, str(other))                      # 죽음 → 슬롯(레코드는 이미 교체됨)
    _mount_all(ctrl, csv1)                            # 원 소스 복귀
    hint = ctrl.snapshot()["filter"]["reapply_hint"]
    assert hint == alive, f"슬롯 문안이 죽는 세션이 아니라 새 데이터로 지어졌습니다: {hint!r}"


def test_reapply_hint_carries_definition_to_be_installed(tmp_path):
    """버튼이 설치할 정의를 업는다(#127 조치 2 — 목업 칩 문법 승계).

    어포던스가 회수되면 문안도 함께 내려간다(죽은 힌트가 남으면 그 자체가 거짓 진술).
    """
    ctrl, _ = _session(tmp_path)
    csv1 = _data_csv(tmp_path)
    ctrl.dispatch("filter_search", {"text": "전산"})
    _mount_all(ctrl, _data_csv3(tmp_path))               # 죽음 → 슬롯(정의줄 동반)
    assert ctrl.snapshot()["filter"]["reapply_hint"] == ""  # 소스 불일치 = 문안도 없음
    _mount_all(ctrl, csv1)
    hint = ctrl.snapshot()["filter"]["reapply_hint"]
    assert "전산" in hint, hint
    ctrl.dispatch("filter_search", {"text": "사무"})         # 정의가 서면 어포던스·문안 회수
    assert ctrl.snapshot()["filter"]["reapply_hint"] == ""


def test_reapply_source_key_distinguishes_sheets(tmp_path):
    """소스 키 = 경로+시트(리뷰 #0) — 같은 워크북의 다른 시트는 다른 소스다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, str(MULTI_SHEET), sheet="공고목록")
    ctrl.dispatch("filter_search", {"text": "물"})           # 정의 있는 세션
    _mount_all(ctrl, str(MULTI_SHEET), sheet="낙찰현황")  # 같은 파일·다른 시트
    assert ctrl.snapshot()["filter"]["reapply_available"] is False  # 교차 재사용 차단
    _mount_all(ctrl, str(MULTI_SHEET), sheet="공고목록")  # 같은 시트 복귀
    # 무정의 세션(낙찰현황)의 죽음은 슬롯을 보존한다 — 공고목록 정의가 제 시트에 제공.
    assert ctrl.snapshot()["filter"]["reapply_available"] is True


def test_reapply_source_key_normalizes_path_spelling(tmp_path):
    """경로 표기 변형(대소문자)에도 같은 실파일이면 소스 일치(리뷰 #8 — 조용한 강등 방지)."""
    ctrl, _ = _session(tmp_path)
    csv1 = _data_csv(tmp_path)
    ctrl.dispatch("filter_search", {"text": "전산"})
    _mount_all(ctrl, _data_csv3(tmp_path))               # 죽음 → 슬롯(csv1 키)
    _mount_all(ctrl, csv1.upper())                       # 같은 파일, 표기만 다름(Windows)
    assert ctrl.snapshot()["filter"]["reapply_available"] is True


def test_reapply_pool_key_includes_reference_identity(tmp_path):
    """풀 소스 키 = 이름+참조 정체(리뷰 #6) — 같은 이름 재등록(다른 파일)은 다른 소스."""
    ctrl, pool = _pool_controller(tmp_path)
    pool.save(DatasetPoolItem(name="7월공고", kind="excel", opts={"path": _data_csv(tmp_path)}))
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.dispatch("load_pool", {"name": "7월공고"})
    ctrl.dispatch("filter_search", {"text": "전산"})
    # 같은 이름으로 다른 파일 재등록(참조 교체) 후 재겨눔 — 이름만 같은 다른 소스.
    pool.save(DatasetPoolItem(name="7월공고", kind="excel",
                              opts={"path": _data_csv3(tmp_path)}), allow_overwrite=True)
    ctrl.dispatch("load_pool", {"name": "7월공고"})          # 죽음 → 슬롯(옛 참조 키)
    assert ctrl.snapshot()["filter"]["reapply_available"] is False


def test_reapply_abandons_pruning_when_branches_all_lost(tmp_path):
    """가지 소실 시 프루닝 복원 포기(리뷰 #2) — 거짓 「매치 없음」 빈 화면을 만들지 않는다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    both = tmp_path / "both.csv"
    both.write_text("bidNtceNm,memo\n전산장비,전산비고\n사무비품,일반\n", encoding="utf-8")
    _mount_all(ctrl, str(both))
    ctrl.dispatch("filter_search", {"text": "전산"})         # 가지 = bidNtceNm·memo
    ctrl.dispatch("filter_prune", {"column": "bidNtceNm"})   # 가지 하나 쳐냄(memo 잔존)
    _mount_all(ctrl, _data_csv(tmp_path))                 # 죽음 → 슬롯
    # 외부 편집: memo 열 소실 — 프루닝 대상(bidNtceNm)만 남는 지형.
    both.write_text("bidNtceNm\n전산장비\n사무비품\n", encoding="utf-8")
    _mount_all(ctrl, str(both))
    res = ctrl.dispatch("filter_reapply", {})
    assert res["ok"] is True
    assert any("복원하지 못했습니다" in d for d in res["dropped"])  # 포기 고지
    snap = ctrl.snapshot()
    assert snap["table"]["visible_count"] == 1               # 매치가 산다(거짓 전멸 아님)
    assert snap["filter"]["branches"] == ["bidNtceNm"]       # 가지 부활


# ------------------------------------ 관리 동사(표면은 라이브러리, 소유는 이 컨트롤러)
# 좌 목록 사망(F2 PR-B, 지도 §10.9)으로 구획·접힘·복제·삭제·복원 테스트는 여기서 걷혔다:
# `toggle_group`·`clone_job`·`delete_job`·`undo_delete_job` 은 라이브러리 채널이 소유하고
# (tests/test_webapp_library.py 가 판정), 여기 남는 넷은 **열린 세션의 정체와 결속**된 것들
# (개명·그룹 이동/개명/해산)이라 라이브러리가 교차 화면 dispatch 로 부른다(§10.8 판정 F).
def test_rename_job_follows_open_session(tmp_path):
    # 이름 변경은 비파괴 — 열린 세션의 정체(job_name·헤더)가 새 이름을 추종한다.
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    res = ctrl.dispatch("rename_job", {"name": "공고서", "new": " 개명 공고서 "})
    assert res == {"ok": True}
    snap = ctrl.snapshot()
    assert snap["job_name"] == "개명 공고서" and snap["has_job"] is True
    assert ctrl.registry.exists("개명 공고서") and not ctrl.registry.exists("공고서")


def test_rename_job_collision_and_empty_are_restated(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.registry.save(Job(name="둘째"))
    res = ctrl.dispatch("rename_job", {"name": "공고서", "new": "둘째"})
    assert res["ok"] is False and "사용 중" in res["error"]
    res = ctrl.dispatch("rename_job", {"name": "공고서", "new": "  "})
    assert res["ok"] is False and "비어" in res["error"]
    assert ctrl.registry.exists("공고서")  # 실패 무손상


def test_set_group_moves_and_clears(tmp_path):
    """그룹 이동은 라이브러리 상세가 부르고 판정은 여기가 낸다 — 관측은 레지스트리다
    (구획 스냅샷은 좌 목록과 함께 사망, F2 PR-B)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("set_group", {"name": "공고서", "group": "입찰"})
    assert ctrl.registry.groups() == ["입찰"]
    ctrl.dispatch("set_group", {"name": "공고서", "group": ""})  # 해제 = 그룹 없음
    assert ctrl.registry.groups() == []


def test_rename_group_merge_needs_confirm_roundtrip(tmp_path):
    ctrl, _ = _controller(tmp_path)
    reg = ctrl.registry
    reg.save(Job(name="둘째"))
    reg.set_group("공고서", "입찰")
    reg.set_group("둘째", "수의")
    res = ctrl.dispatch("rename_group", {"name": "수의", "new": "입찰"})
    assert res["needs_confirm"] is True and res["kind"] == "merge_group"
    assert res["count"] == 1 and res["target_count"] == 1  # 병합 수치 재진술
    assert set(reg.groups()) == {"수의", "입찰"}  # 무변이
    res2 = ctrl.dispatch("rename_group", {"name": "수의", "new": "입찰", "confirm": True})
    assert res2["ok"] is True and reg.groups() == ["입찰"]


def test_rename_group_carries_collapse_state(tmp_path):
    """접힘의 **표면**은 라이브러리로 갔지만(§10.8 판정 F) 그룹을 개명하는 동사는 여기가
    소유하므로 영속 키의 승계도 여기가 진다 — 이름만 바뀐 같은 그룹은 접힌 채로 남는다.
    관측 지점이 스냅샷에서 영속 키로 내려온 것은 좌 목록 사망의 정산분이다(F2 PR-B)."""
    from hwpxfiller.webapp.settings import load_job_collapsed_groups, save_job_collapsed_groups

    ctrl, _ = _controller(tmp_path)
    ctrl.registry.set_group("공고서", "입찰")
    save_job_collapsed_groups(["입찰"])                    # 라이브러리에서 접어 둔 상태
    ctrl.dispatch("rename_group", {"name": "입찰", "new": "2026 입찰"})
    assert load_job_collapsed_groups() == ["2026 입찰"]     # 접힘 승계(유령 옛 이름 없음)


def test_disband_group_confirm_roundtrip(tmp_path):
    from hwpxfiller.webapp.settings import save_job_collapsed_groups

    ctrl, _ = _controller(tmp_path)
    ctrl.registry.set_group("공고서", "입찰")
    save_job_collapsed_groups(["입찰"])                    # 라이브러리에서 접어 둔 상태
    res = ctrl.dispatch("disband_group", {"name": "입찰"})
    assert res["needs_confirm"] is True and res["count"] == 1
    assert ctrl.registry.groups() == ["입찰"]  # 무확인 = 무변이
    res2 = ctrl.dispatch("disband_group", {"name": "입찰", "confirm": True})
    assert res2["ok"] is True and ctrl.registry.groups() == []
    # 사라진 그룹의 접힘 잔재는 걷는다 — 같은 이름 재생성 시 유령 접힘 방지.
    from hwpxfiller.webapp.settings import load_job_collapsed_groups
    assert "입찰" not in load_job_collapsed_groups()


# ---------------- 실 공개 writer × 스탬프 동시성(#129) ----------------
# 아래 세 테스트는 화면이 실제로 부르는 공개 writer 경로를 그대로 쓴다.
def _pause_stamp(monkeypatch):
    """스탬프 저장을 잠금 안에서 한 번 멈춰 세우는 장치 — (진입 이벤트, 해제 이벤트)."""
    import threading

    entered, release = threading.Event(), threading.Event()
    real_save = Job.save
    fired = {"once": False}

    def slow_save(self, path):
        if not fired["once"] and self.last_run_at:   # 스탬프 저장만 붙잡는다
            fired["once"] = True
            entered.set()
            release.wait(3)
        return real_save(self, path)

    monkeypatch.setattr(Job, "save", slow_save)
    return entered, release


def _home_vm(registry):
    from hwpxfiller.gui.home_state import HomeViewModel

    return HomeViewModel(registry, None, None)


def test_public_delete_during_stamp_does_not_resurrect_the_job(tmp_path, monkeypatch):
    """삭제 도중 스탬프가 끼어도 지운 작업이 되살아나지 않는다(리뷰 3R P1).

    잠금 밖 삭제라면: ①스탬프가 A 를 읽고 ②삭제가 파일을 지우고 성공을 반환하고 ③스탬프가
    사본을 저장해 **A 가 부활**한다. "지웠다"고 말한 뒤 되살아나는 것은 조용한 소실의 거울상이다.
    """
    import threading

    ctrl, _ = _controller(tmp_path)
    reg = ctrl.registry
    vm = _home_vm(reg)
    entered, release = _pause_stamp(monkeypatch)

    stamper = threading.Thread(target=lambda: reg.stamp_last_run("공고서", "2026-07-21T09:00:00"))
    stamper.start()
    assert entered.wait(3)

    done = threading.Event()

    def delete_job():
        vm.delete("공고서")      # 홈 카드 「삭제」가 타는 실제 경로
        done.set()

    deleter = threading.Thread(target=delete_job)
    deleter.start()
    assert not done.wait(0.2), "삭제가 스탬프의 임계구역 안으로 끼어들었습니다."
    release.set()
    stamper.join(3)
    deleter.join(3)
    assert not reg.exists("공고서"), "지운 작업이 스탬프 저장으로 되살아났습니다."


def test_public_set_tags_during_stamp_keeps_both_changes(tmp_path, monkeypatch):
    """태그 편집과 스탬프가 겹쳐도 둘 다 남는다 — 늦은 저장이 상대를 되돌리지 않는다."""
    import threading

    ctrl, _ = _controller(tmp_path)
    reg = ctrl.registry
    vm = _home_vm(reg)
    entered, release = _pause_stamp(monkeypatch)

    stamper = threading.Thread(target=lambda: reg.stamp_last_run("공고서", "2026-07-21T09:00:00"))
    stamper.start()
    assert entered.wait(3)
    tagger = threading.Thread(target=lambda: vm.set_tags("공고서", {"부서": "계약"}))
    tagger.start()
    release.set()
    stamper.join(3)
    tagger.join(3)

    saved = reg.load("공고서")
    assert saved.last_run_at == "2026-07-21T09:00:00"   # 태그 저장이 시각을 지우지 않았다
    assert saved.tags == {"부서": "계약"}                # 스탬프가 태그를 되돌리지 않았다


def test_public_relink_during_stamp_keeps_both_changes(tmp_path, monkeypatch):
    """템플릿 재연결과 스탬프가 겹쳐도 둘 다 남는다(확인 왕복이 있어 창이 특히 넓은 경로)."""
    import threading

    from hwpxfiller.webapp.screens import relink_job_template

    ctrl, _ = _controller(tmp_path)
    reg = ctrl.registry
    new_template = tmp_path / "새서식.hwpx"
    _write_template(new_template, ["공고명", "추정가격"])
    entered, release = _pause_stamp(monkeypatch)

    stamper = threading.Thread(target=lambda: reg.stamp_last_run("공고서", "2026-07-21T09:00:00"))
    stamper.start()
    assert entered.wait(3)
    linker = threading.Thread(
        target=lambda: relink_job_template(reg, "공고서", str(new_template), confirm=True)
    )
    linker.start()
    release.set()
    stamper.join(3)
    linker.join(3)

    saved = reg.load("공고서")
    assert saved.last_run_at == "2026-07-21T09:00:00"
    assert saved.template_path == str(new_template)


def test_disband_group_restates_actual_count_when_it_drifted(tmp_path):
    """확인 시점 건수와 실제 이동 건수가 갈라지면 조용히 넘기지 않는다(#149).

    확인 문안은 잠금 밖 사전 카운트로 만들어진다 — 사용자가 모달을 읽는 사이 다른 표면이
    작업을 옮기면 "N건" 이 실제와 어긋난다. 이동은 파괴가 아니라 재확인까지 올리지 않되,
    결과 재진술이 **어긋남을 말해야** 확인한 내용과 실제가 갈라진 채 넘어가지 않는다.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.registry.set_group("공고서", "입찰")
    res = ctrl.dispatch("disband_group", {"name": "입찰"})
    assert res["count"] == 1
    ctrl.registry.save(Job(name="늦게합류", group="입찰"), allow_overwrite=True)  # 확인 왕복 사이 합류
    res2 = ctrl.dispatch("disband_group", {"name": "입찰", "confirm": True, "seen": res["count"]})
    assert res2["ok"] is True and res2["count"] == 2  # 실제 이동은 잠금 안에서 센 값
    assert "확인 시점 1건" in res2["drift_note"]


def test_disband_group_says_nothing_when_count_held(tmp_path):
    """어긋나지 않았으면 고지는 침묵 — 매번 붙는 문구는 신호가 아니라 소음이다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.registry.set_group("공고서", "입찰")
    res = ctrl.dispatch("disband_group", {"name": "입찰"})
    res2 = ctrl.dispatch("disband_group", {"name": "입찰", "confirm": True, "seen": res["count"]})
    assert res2["drift_note"] == ""


def test_rename_group_merge_restates_actual_count_when_it_drifted(tmp_path):
    """병합도 같은 고지를 진다(#149) — 두 표면이 같은 술어를 써야 어긋남이 한쪽만 새지 않는다."""
    ctrl, _ = _controller(tmp_path)
    reg = ctrl.registry
    reg.save(Job(name="둘째"))
    reg.set_group("공고서", "입찰")
    reg.set_group("둘째", "수의")
    res = ctrl.dispatch("rename_group", {"name": "수의", "new": "입찰"})
    assert res["count"] == 1
    reg.save(Job(name="늦게합류", group="수의"), allow_overwrite=True)
    res2 = ctrl.dispatch(
        "rename_group", {"name": "수의", "new": "입찰", "confirm": True, "seen": res["count"]}
    )
    assert res2["ok"] is True and res2["count"] == 2
    assert "확인 시점 1건" in res2["drift_note"]


def test_describe_fill_note_names_field_and_kinds():
    """완화 노트 문안(#154) — 필드·제거 종류를 명명하고 미지 종류는 원문 관통."""
    from hwpxfiller.core.fields import FillNote
    from hwpxfiller.gui.result_errors import describe_fill_note

    stripped = describe_fill_note(
        FillNote("계약명", "inline_stripped", ("markpenBegin", "markpenEnd"))
    )
    assert "계약명" in stripped
    assert "markpenBegin, markpenEnd" in stripped
    assert "제거" in stripped

    synth = describe_fill_note(FillNote("공고번호", "slot_synthesized"))
    assert "공고번호" in synth and "빈 누름틀" in synth

    unknown = describe_fill_note(FillNote("X", "future_kind"))
    assert "future_kind" in unknown  # 조용한 누락 금지


def test_generate_surfaces_fill_notes(tmp_path):
    """완화 노트(#154)는 잡 완료 표면에 실린다 — CLI 만 알던 비대칭 해소(리뷰 F1)."""
    ctrl, _ = _controller(tmp_path)
    # 리그 템플릿을 마커 낀 값 런으로 재작성 — 채움이 inline_stripped 를 낳는다.
    sec = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p>'
        '<hp:run><hp:ctrl><hp:fieldBegin name="공고명"/></hp:ctrl></hp:run>'
        "<hp:run><hp:t>{{공고명}}<hp:markpenBegin/>X</hp:t></hp:run>"
        '<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>'
        '<hp:run><hp:ctrl><hp:fieldBegin name="추정가격"/></hp:ctrl></hp:run>'
        "<hp:run><hp:t>{{추정가격}}</hp:t></hp:run>"
        '<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>'
        "</hp:p></hs:sec>"
    ).encode()
    HwpxPackage(
        entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": sec}
    ).save(str(tmp_path / "t.hwpx"))

    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})

    res = ctrl.generate()
    assert res["ok"] is True
    # 템플릿 구조 속성 — 레코드 2건이어도 1회, 문안은 describe_fill_note 공유.
    assert len(res["fill_notes"]) == 1
    assert "markpenBegin" in res["fill_notes"][0]
    assert "채움 주의 1건" in res["summary"]


# ================================= 「문서 만들기에서 사용」 3분기(§19.8) + preferredWorkId
def _incompatible_reg(tmp_path) -> JobRegistry:
    """기본 픽스처에 **이 데이터로는 못 도는** 작업 하나를 더한다(소스 열 부재)."""
    reg = _registry(tmp_path)
    template = tmp_path / "t2.hwpx"
    _write_template(template, ["계약명"])
    reg.save(Job(
        name="계약서",
        template_path=str(template),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="계약명", source="없는열"),
        ]),
        filename_pattern="c-{{seq:001}}",
    ))
    return reg


def test_prefer_work_promotes_when_the_data_is_ready_and_compatible(tmp_path):
    """§19.8 1분기 — 명시 선택과 같다. 데이터·선택은 세션 소유라 **생존**한다."""
    ctrl, _ = _controller(tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))
    before = ctrl.selection.selected_count()
    res = ctrl.dispatch("prefer_work", {"name": "공고서"})
    assert res == {"promoted": True, "name": "공고서"}
    assert ctrl.job_name == "공고서"
    assert ctrl.preferred_work == ""              # 지금 이뤄졌으니 보관하지 않는다
    assert ctrl.selection.selected_count() == before  # RecordRangeState 생존


def test_prefer_work_stores_and_promotes_at_mount_when_no_data_yet(tmp_path):
    """§19.8 3분기 — 데이터가 없으면 보관하고, 마운트 시 §18.3 1행이 승격한다.

    슬2가 규칙만 박제하고 비워 뒀던 seam 이 여기서 처음 소비된다. 승격은 **조용하지 않다** —
    사용자가 방금 낸 의도가 이제 발화했다는 사실을 데이터 재진술로 말한다.
    """
    ctrl, _ = _controller(tmp_path)
    res = ctrl.dispatch("prefer_work", {"name": "공고서"})
    assert res == {"stored": True, "reason": "no_data", "name": "공고서"}
    assert ctrl.job_name == "" and ctrl.preferred_work == "공고서"

    ctrl.load_data_path(_data_csv(tmp_path))
    assert ctrl.job_name == "공고서"
    assert ctrl.preferred_work == ""              # 1회 소비
    snap = ctrl.snapshot()
    assert "공고서" in snap["data_notice"]["text"] and snap["data_notice"]["level"] == "ok"


def test_prefer_work_opens_a_work_that_carries_its_own_default_data(tmp_path):
    """판정 I(F2 PR-B) — 기본 데이터 참조를 가진 작업은 무데이터 상태에서도 **열린다**.

    좌 목록이 살아 있을 땐 목록 클릭이 `select_job` 을 태워 #53-A 자동 조준이 발화했다.
    목록이 죽은 뒤 무데이터 상태에서 작업을 겨눌 표면은 「문서 작업」의 이 동사뿐이므로,
    여기서 보관만 하면 기본 데이터 자동 연결이 **도달 불가능**해진다(기능 소실). 자동
    교체가 아니라 빈 자리의 첫 마운트라 §19.8 의 금지에도 걸리지 않고, 결과는 재진술된다.
    """
    ctrl, pool = _pool_controller(tmp_path)
    _job_with_default(ctrl, pool, tmp_path, "7월공고")

    res = ctrl.dispatch("prefer_work", {"name": "공고서"})
    assert res == {"promoted": True, "name": "공고서", "reason": "default_data"}
    assert ctrl.job_name == "공고서" and ctrl.preferred_work == ""   # 보관하지 않고 소비
    snap = ctrl.snapshot()
    assert snap["has_data"] is True, "기본 데이터 참조가 자동 조준되지 않았습니다(#53-A 소실)."
    assert snap["data_source_label"] == "등록 데이터: 7월공고"
    assert "자동으로 연결" in snap["data_notice"]["text"], "자동 연결이 조용히 일어났습니다."


def test_prefer_work_keeps_the_active_work_and_says_so(tmp_path):
    """§18.3 2행 — 이미 열린 작업은 밀어내지 않는다. 대신 못 바꿨다는 사실을 말한다.

    조용히 아무 일도 안 일어나면 사용자는 자기가 누른 버튼이 무엇을 했는지 알 수 없다.
    """
    ctrl, _ = _controller(_p := tmp_path)
    ctrl.dispatch("prefer_work", {"name": "공고서"})
    ctrl.dispatch("select_job", {"name": "공고서"})   # 명시 선택 = 보관분 소비
    assert ctrl.preferred_work == ""
    ctrl.preferred_work = "공고서"                     # 활성이 있는 채로 보관분이 남은 상태
    ctrl.load_data_path(_data_csv(_p))
    snap = ctrl.snapshot()
    assert ctrl.job_name == "공고서"
    assert "이미 열려" in snap["data_notice"]["text"]
    assert snap["data_notice"]["level"] == "warn"


def test_prefer_work_does_not_activate_an_incompatible_work(tmp_path):
    """§19.8 2분기 — 실행할 수 없는 작업을 활성으로 세우지 않는다(게이트가 닫힌 채 '만들 참').

    표면은 반환 사유로 「확인 필요」 탭에 데려간다 — 판정은 여기(Python)가 낸다.
    """
    pushes: list = []
    ctrl = JobController(_incompatible_reg(tmp_path), lambda s, snap: pushes.append((s, snap)))
    _mount_all(ctrl, _data_csv(tmp_path))
    res = ctrl.dispatch("prefer_work", {"name": "계약서"})
    assert res == {"stored": True, "reason": "incompatible", "name": "계약서"}
    assert ctrl.job_name == ""                    # 활성 불변 — 조용한 승격 없음
    assert ctrl.preferred_work == "계약서"


def test_stored_preference_that_stays_incompatible_is_restated_not_swallowed(tmp_path):
    """보관분이 새 데이터에서도 못 도는 경우 — 사유를 재진술하고 보관분을 비운다.

    들고 있으면 사용자가 잊은 의도가 다음 마운트에서 조용히 발화한다(지연된 조용한 추측).
    """
    pushes: list = []
    ctrl = JobController(_incompatible_reg(tmp_path), lambda s, snap: pushes.append((s, snap)))
    ctrl.dispatch("prefer_work", {"name": "계약서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    snap = ctrl.snapshot()
    assert ctrl.job_name == "" and ctrl.preferred_work == ""
    assert "실행할 수 없습니다" in snap["data_notice"]["text"]
    assert snap["data_notice"]["level"] == "warn"


def test_stored_preference_pointing_at_a_deleted_work_is_loud(tmp_path):
    """그사이 삭제·개명된 작업을 겨눈 보관분은 유령을 열지 않고 사실을 말한다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("prefer_work", {"name": "공고서"})
    ctrl.registry.delete("공고서")
    ctrl.load_data_path(_data_csv(tmp_path))
    snap = ctrl.snapshot()
    assert ctrl.job_name == "" and ctrl.preferred_work == ""
    assert "더는 없습니다" in snap["data_notice"]["text"]


def test_prefer_work_rejects_unknown_names_loudly(tmp_path):
    ctrl, _ = _controller(tmp_path)
    with pytest.raises(ValueError, match="찾을 수 없습니다"):
        ctrl.dispatch("prefer_work", {"name": "없는작업"})
    with pytest.raises(ValueError, match="비어 있습니다"):
        ctrl.dispatch("prefer_work", {"name": "  "})


# ---------------------------------------- 결과 3태 + 부분 실패 표면(F4, 지도 §10.10)
def _fake_batch(oks, *, errors=(), cancelled=False, total=None):
    """``oks`` 순서대로 성공/실패인 배치 대역 — ``errors`` 는 실패분 사유(순서대로)."""
    errs = list(errors)

    class _R:
        def __init__(self, ok, name):
            self.ok, self.output_path, self.notes = ok, name, []
            self.error = "" if ok else (errs.pop(0) if errs else "boom")

    results = [_R(ok, f"doc-{i:03}.hwpx") for i, ok in enumerate(oks, 1)]

    class _B:
        pass

    b = _B()
    b.results = results
    b.succeeded = sum(1 for r in results if r.ok)
    b.total = len(oks) if total is None else total
    b.failed = b.total - b.succeeded
    b.cancelled = cancelled
    b.attempted = len(results)
    return b


def _run_with(monkeypatch, ctrl, batch):
    import hwpxfiller.webapp.screen_job as sj
    monkeypatch.setattr(sj, "generate_batch", lambda *a, **k: batch)
    return ctrl.generate()


def _result_session(tmp_path):
    """빈 값 게이트를 태우지 않는 3행 세션 — 결과 3태 계약은 게이트 통과 이후가 무대다."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv3(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    return ctrl, pushes


def test_result_three_states_are_python_judged(tmp_path, monkeypatch):
    """3태는 성공/전체의 함수다(§10.10 판정 A) — 불변식 §13-10(일부 성공≠전체 성공)."""
    from hwpxfiller.webapp.screen_job import _run_status, _run_title

    assert _run_status(2, 2) == "completed"
    assert _run_status(1, 2) == "partiallyCompleted"
    assert _run_status(0, 2) == "failed"
    # 취소는 네 번째 태가 아니라 부분의 변종 — 태는 그대로, 제목이 중단을 먼저 말한다.
    assert _run_title("partiallyCompleted", True, 1, 0).startswith("생성을 중단했습니다")
    assert "1개 성공" in _run_title("partiallyCompleted", False, 1, 1)
    # 첫 레코드 전에 멈춘 런: 성공 0·실패 0이다. 성공 수만 보면 failed 가 되어 "중단
    # 했습니다"라는 제목 옆에서 태가 없던 실패를 지어낸다(1R P2).
    assert _run_status(0, 3, True) == "partiallyCompleted"


def test_partial_run_reports_partial_state_and_failed_rows(tmp_path, monkeypatch):
    """부분 실패 = `partiallyCompleted` + 실패 행 구조화(§10.10 판정 E)."""
    ctrl, _ = _result_session(tmp_path)
    res = _run_with(monkeypatch, ctrl, _fake_batch(
        [True, False], errors=["[WinError 32] 다른 프로세스가 파일을 사용 중"],
    ))
    assert res["status"] == "partiallyCompleted"
    assert res["title"] == "1개 성공 · 1개 실패"
    row = res["failures"][0]
    assert row["filename"] == "doc-002.hwpx"
    assert row["index"] in {0, 1}                 # 원본 index(선택 재사용의 입력)
    assert row["identity"]                        # 식별 요약 = 표 「문서」 열과 같은 판정
    assert row["known"] is True                   # 아는 원인 — 미연결 표지 금지
    assert "원문:" in row["reason"]                # 증거 무손실


def test_unknown_cause_keeps_the_undiagnosed_boundary(tmp_path, monkeypatch):
    """모르는 원인은 아는 척하지 않는다 — 계약 §10.3 「원인 진단 미연결」(판정 B)."""
    from hwpxfiller.gui.result_errors import classify_result_error

    assert classify_result_error("[WinError 5] 액세스가 거부되었습니다")[1] is True
    text, known = classify_result_error("알 수 없는 무엇")
    assert known is False and text == "알 수 없는 무엇"   # 원문 관통(조용한 재작성 금지)

    ctrl, _ = _result_session(tmp_path)
    res = _run_with(monkeypatch, ctrl, _fake_batch([False], errors=["설명 없는 오류"]))
    assert res["status"] == "failed"
    assert res["failures"][0]["known"] is False


def test_batch_exception_lands_in_the_result_zone(tmp_path, monkeypatch):
    """배치가 시작조차 못 한 실패도 결과 구획에 선다(§10.10 판정 C) — 백스톱으로 새지 않는다."""
    import hwpxfiller.webapp.screen_job as sj

    def _boom(*a, **k):
        raise ValueError("템플릿 구조가 확정 매핑과 달라 생성을 차단했습니다 — 필드 없음")

    monkeypatch.setattr(sj, "generate_batch", _boom)
    ctrl, _ = _result_session(tmp_path)
    res = ctrl.generate()
    assert res["ok"] is True and res["status"] == "failed"   # 거절이 아니라 실패
    assert res["stage"] == "생성 시작 전"                     # 실패 단계(계약 §10.3)
    assert "템플릿 구조" in res["message"]                    # 받은 메시지 원문
    assert res["succeeded"] == 0 and res["failed"] == res["total"] > 0


def test_select_failed_replaces_selection_and_does_not_generate(tmp_path, monkeypatch):
    """「실패한 N건만 선택」 = 선택 교체뿐(§10.10 판정 F) — 2클릭 분리."""
    ctrl, _ = _result_session(tmp_path)
    res = _run_with(monkeypatch, ctrl, _fake_batch([True, False]))
    failed_index = res["failures"][0]["index"]
    calls: list = []
    import hwpxfiller.webapp.screen_job as sj
    monkeypatch.setattr(sj, "generate_batch", lambda *a, **k: calls.append(1))

    out = ctrl.dispatch("select_failed", {})
    assert out == {"selected": 1}
    assert calls == []                                        # 생성은 하지 않는다
    snap = ctrl.snapshot()
    assert snap["selected_count"] == 1
    assert [r["index"] for r in snap["records"] if r["selected"]] == [failed_index]


def test_failed_indices_die_with_their_data_and_work(tmp_path, monkeypatch):
    """실패 index 는 이 레코드 집합·이 작업에서만 뜻이 있다 — 경계를 지나면 무동작이 정직하다."""
    ctrl, _ = _result_session(tmp_path)
    _run_with(monkeypatch, ctrl, _fake_batch([True, False]))
    assert ctrl.dispatch("select_failed", {})["selected"] == 1
    other = tmp_path / "other.csv"
    other.write_text("bidNtceNm,presmptPrce\n다른행,1\n", encoding="utf-8")
    ctrl.load_data_path(str(other))                            # 데이터 교체
    assert ctrl.dispatch("select_failed", {})["selected"] == 0  # 남의 행을 고르지 않는다

    _mount_all(ctrl, _data_csv(tmp_path))
    _run_with(monkeypatch, ctrl, _fake_batch([True, False]))
    ctrl.dispatch("select_job", {"name": "공고서", "confirm": True})  # 작업 전환
    assert ctrl.dispatch("select_failed", {})["selected"] == 0


def test_cancel_before_first_record_is_not_a_failure(tmp_path, monkeypatch):
    """중단은 성공 수와 무관하게 부분이다(1R P2) — 실패한 시도가 없는데 실패 태를 달지 않는다."""
    ctrl, _ = _result_session(tmp_path)
    res = _run_with(monkeypatch, ctrl, _fake_batch([], cancelled=True, total=3))
    assert res["status"] == "partiallyCompleted" and res["cancelled"] is True
    assert res["succeeded"] == 0 and res["failed"] == 0 and res["unstarted"] == 3
    assert res["failed_selectable"] == 0          # 다시 만들 '실패분'은 없다(미착수는 실패가 아니다)


def test_batch_exception_keeps_the_recovery_action_reachable(tmp_path, monkeypatch):
    """행이 0개라도 복구 대상은 전량이다(1R P2) — 표면이 「실패한 N건만 선택」을 숨기지 않게."""
    import hwpxfiller.webapp.screen_job as sj

    def _boom(*a, **k):
        raise OSError("[WinError 5] 액세스가 거부되었습니다")

    monkeypatch.setattr(sj, "generate_batch", _boom)
    ctrl, _ = _result_session(tmp_path)
    res = ctrl.generate()
    assert res["failures"] == []                   # 시도가 없었으므로 행별 사유를 지어내지 않는다
    assert res["failed_selectable"] == res["total"] > 0
    # 그사이 선택을 바꿔도 대상 집합을 되찾는다 — 이것이 행 대신 수치로 노출을 정하는 이유.
    ctrl.dispatch("set_none", {})
    assert ctrl.dispatch("select_failed", {})["selected"] == res["failed_selectable"]


def test_failed_job_switch_keeps_the_recovery_target(tmp_path, monkeypatch):
    """전환이 **성사되지 않으면** 실패 목록도 그대로다(2R P2).

    `registry.load` 가 실패하면 세션은 그대로인데(vm·job_name 불변) 목록만 비면, 화면에
    남아 있는 「실패한 N건만 선택」이 0건을 돌려주는 유령 행동이 된다.
    """
    ctrl, _ = _result_session(tmp_path)
    _run_with(monkeypatch, ctrl, _fake_batch([True, False]))
    assert ctrl.dispatch("select_failed", {})["selected"] == 1
    with pytest.raises(OSError):                         # 사라진·읽을 수 없는 작업
        ctrl.dispatch("select_job", {"name": "없는작업", "confirm": True})
    assert ctrl.job_name == "공고서"                      # 세션 불변
    assert ctrl.dispatch("select_failed", {})["selected"] == 1   # 복구 대상도 불변
    # 전환이 실제로 성사되면 그때 비운다(다른 작업의 실패를 고르지 않는다).
    ctrl.registry.save(Job(name="둘째"))
    ctrl.dispatch("select_job", {"name": "둘째", "confirm": True})
    assert ctrl.dispatch("select_failed", {})["selected"] == 0


def test_run_owner_lives_in_session_state_and_follows_renames(tmp_path, monkeypatch):
    """직전 런의 주체는 **세션 상태**가 소유하고 정체 변화를 따라간다(3R P2 근본 조치).

    결과 payload(한 번 찍고 안 변하는 값)에 주체를 넣으면 이름 변경을 못 따라가 같은
    작업이 남처럼 보인다 — 표면이 쓰는 두 값을 같은 출처(스냅샷)에서 낸다.
    """
    ctrl, _ = _result_session(tmp_path)
    _run_with(monkeypatch, ctrl, _fake_batch([True, False]))
    snap = ctrl.snapshot()
    assert snap["last_run_job"] == snap["job_name"] == "공고서"   # 그 런의 작업이 열려 있다

    ctrl.dispatch("rename_job", {"name": "공고서", "new": "공고서(수정)"})
    snap = ctrl.snapshot()
    assert snap["last_run_job"] == snap["job_name"] == "공고서(수정)"  # 같은 전이에서 추종
    assert ctrl.dispatch("select_failed", {})["selected"] == 1        # 복구 대상도 유효

    import hwpxfiller.webapp.screen_job as sj

    def _boom(*a, **k):
        raise OSError("[WinError 5] 액세스가 거부되었습니다")

    monkeypatch.setattr(sj, "generate_batch", _boom)
    ctrl.generate()
    assert ctrl.snapshot()["last_run_job"] == "공고서(수정)"          # 실패 경로도 같은 모양

    ctrl.registry.save(Job(name="둘째"))
    ctrl.dispatch("select_job", {"name": "둘째", "confirm": True})
    snap = ctrl.snapshot()
    assert snap["last_run_job"] == "공고서(수정)" != snap["job_name"]  # 남의 세계임을 말한다


def test_run_pushes_a_snapshot_so_the_surface_can_judge(tmp_path, monkeypatch):
    """`generate` 는 dispatch 밖이라 자동 push 가 없다 — 런이 바꾼 값을 표면이 못 본다(3R P2)."""
    ctrl, pushes = _result_session(tmp_path)
    before = len(pushes)
    _run_with(monkeypatch, ctrl, _fake_batch([True, False]))
    assert len(pushes) > before
    assert pushes[-1][1]["last_run_job"] == "공고서"


def test_cancelled_run_stays_a_partial_state(tmp_path, monkeypatch):
    """취소 런은 부분 태 + warn 채널을 유지한다(#278 리뷰가 세운 색 계약과 같은 걸음)."""
    ctrl, _ = _result_session(tmp_path)
    res = _run_with(monkeypatch, ctrl, _fake_batch([True], cancelled=True, total=2))
    assert res["status"] == "partiallyCompleted" and res["cancelled"] is True
    assert res["level"] == "warn" and res["unstarted"] == 1
    assert res["title"].startswith("생성을 중단했습니다")


# ------------------------------------- 전체 표시순서 축(재작성 F3, 지도 §10.11.1 4계약면)
def _order_session(tmp_path):
    """3행 세션 — 축은 데이터의 성질이라 작업 선택 없이도 산다(스냅샷이 값을 낸다)."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv3(tmp_path))
    return ctrl, pushes


def _axis(snap) -> "dict[str, list]":
    """한 스냅샷이 말하는 순서 4벌 — 전부 같은 축이어야 한다."""
    return {
        "records": [r["index"] for r in snap["records"]],
        "table": [r["index"] for r in snap["table"]["rows"]],
        "strip": [r["index"] for r in snap["table"]["hidden_selected"]],
        "sample": list(snap["restate"]["sample"]),
    }


def test_view_order_is_an_exact_reverse_with_no_ties(tmp_path):
    """정밀도 면: 정렬 키가 정수 ordinal 이라 동률이 없고 두 값은 정확한 역이다."""
    ctrl, _ = _order_session(tmp_path)
    desc = _axis(ctrl.snapshot())["records"]
    ctrl.dispatch("set_view_order", {"value": "sourceAsc"})
    asc = _axis(ctrl.snapshot())["records"]
    assert desc == [2, 1, 0] and asc == [0, 1, 2]
    assert asc == list(reversed(desc))


def test_every_order_consumer_shares_the_one_axis(tmp_path):
    """도달성 면: 표·필터 밖 스트립·실행 입력·파일 이름 계획이 한 훅을 소비한다.

    스트립이 원본 순서로 남으면 "보이는 것 = 만들어지는 것"이 거기서만 깨진다(판정 H).
    """
    ctrl, _ = _order_session(tmp_path)
    ctrl.dispatch("filter_search", {"text": "책상"})  # 선택은 관통 — 2행이 필터 밖으로
    for value, expect in (("sourceDesc", [1, 0]), ("sourceAsc", [0, 1])):
        ctrl.dispatch("set_view_order", {"value": value})
        snap = ctrl.snapshot()
        seen = _axis(snap)
        assert seen["strip"] == expect, f"{value}: 스트립이 표와 다른 축을 말합니다"
        assert ctrl._indices() == ([2, 1, 0] if value == "sourceDesc" else [0, 1, 2])
        # 파일 이름은 실행 입력 순서를 따라 발급된다({{seq:001}}) — 표의 「문서」 열이 증거.
        names = {r["index"]: r["name"] for r in snap["records"]}
        assert names[ctrl._indices()[0]].startswith("doc-001")


def test_view_order_change_moves_no_row_in_or_out(tmp_path):
    """축은 투영이고 선택은 집합 — 순서를 바꿔도 같은 행이 남는다."""
    ctrl, _ = _order_session(tmp_path)
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("toggle_record", {"index": 1, "value": True})
    before = ctrl.selection.selected_indices()
    ctrl.dispatch("set_view_order", {"value": "sourceAsc"})
    assert ctrl.selection.selected_indices() == before


def test_new_snapshot_returns_to_the_default_axis(tmp_path):
    """상태 주체 면 ①: 축은 데이터 귀속이라 새 스냅샷이 기본값으로 되돌린다(불변식 §18.11-13)."""
    ctrl, _ = _order_session(tmp_path)
    ctrl.dispatch("set_view_order", {"value": "sourceAsc"})
    ctrl.load_data_path(_data_csv(tmp_path))
    snap = ctrl.snapshot()
    assert snap["view_order"] == "sourceDesc"
    assert snap["selected_count"] == 0  # 같은 seam 이 선택 0건도 이행한다(§18.2)


def test_view_order_is_not_persisted_across_sessions(tmp_path):
    """상태 주체 면 ②: 개인화 설정으로 승격하지 않는다 — 새 세션은 기본값에서 시작한다.

    순서가 파일 이름의 함수라(§2 충돌 B) 지난 데이터의 순서를 물고 오면 이름이 조용히 갈린다.
    """
    ctrl, _ = _order_session(tmp_path)
    ctrl.dispatch("set_view_order", {"value": "sourceAsc"})
    fresh = JobController(_registry(tmp_path), lambda s, snap: None)
    assert fresh.initial()["view_order"] == "sourceDesc"


def test_selecting_a_work_does_not_touch_the_axis(tmp_path):
    """불변식 §18.11-23 — 문서 작업 선택은 `RecordRangeState` 를 바꾸지 않는다."""
    ctrl, _ = _order_session(tmp_path)
    ctrl.dispatch("set_view_order", {"value": "sourceAsc"})
    ctrl.dispatch("select_job", {"name": "공고서"})
    assert ctrl.snapshot()["view_order"] == "sourceAsc"


def test_unknown_view_order_is_refused_loudly(tmp_path):
    """confirm-or-alarm: 미지 값은 조용한 기본값 강등이 아니라 거절이다."""
    ctrl, _ = _order_session(tmp_path)
    with pytest.raises(ValueError):
        ctrl.dispatch("set_view_order", {"value": "alphabetical"})
    assert ctrl.snapshot()["view_order"] == "sourceDesc"


def test_order_note_claims_the_filename_link_only_when_it_is_true(tmp_path):
    """판정 I: 상시 절은 언제나 참, 순번 절은 규칙이 `{{seq}}` 를 쓸 때만 붙는다."""
    ctrl, _ = _order_session(tmp_path)
    assert "보이는 순서대로" in ctrl.snapshot()["order_note"]
    assert "순번" in ctrl.snapshot()["order_note"]  # 픽스처 규칙 = doc-{{seq:001}}
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "{{bidNtceNm}}"
    ctrl.registry.save(job)
    ctrl.dispatch("select_job", {"name": "공고서"})
    note = ctrl.snapshot()["order_note"]
    assert "보이는 순서대로" in note and "순번" not in note


# ------------------------- 전문 범위 편집기 초안(재작성 F3, 지도 §10.11 판정 A·B·D·F·J)
def _draft_session(tmp_path):
    """3행 + 작업 선택 + 저장 폴더 — 초안이 게이트·거울과 갈리는지 보려면 실행 세션이 필요하다."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv3(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    return ctrl, pushes


def test_range_draft_edits_do_not_touch_the_committed_range(tmp_path):
    """불변식 §18.11-21 — 초안은 적용 전 메인 범위·실행 입력·게이트를 바꾸지 않는다."""
    ctrl, _ = _draft_session(tmp_path)
    before_gate = ctrl.snapshot()["gate"]["text"]
    ctrl.dispatch("range_draft_open", {})
    ctrl.dispatch("set_none", {})                     # 초안에서 전부 해제
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})
    snap = ctrl.snapshot()
    # 커밋 = 3건 그대로 · 실행 입력도 그대로 · 게이트 문안 불변
    assert ctrl.selection.selected_count() == 3 and snap["selected_count"] == 3
    assert ctrl._indices() == [2, 1, 0]
    assert snap["gate"]["text"] == before_gate
    # 초안 = 1건, 표는 초안을 그린다(판정 D 경계표 1행)
    assert snap["range_draft"] == {
        "open": True, "dirty": True, "sel_count": 1,
        "selected_only": False, "view_order": "sourceDesc",
    }
    assert [r["index"] for r in snap["table"]["rows"] if r["selected"]] == [0]


def test_range_draft_apply_commits_atomically(tmp_path):
    """적용 = 선택·필터·표시순서를 한 번에 커밋으로 옮긴다(§18.10 한 그릇)."""
    ctrl, _ = _draft_session(tmp_path)
    ctrl.dispatch("range_draft_open", {})
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("toggle_record", {"index": 2, "value": True})
    ctrl.dispatch("filter_search", {"text": "책상"})
    ctrl.dispatch("set_view_order", {"value": "sourceAsc"})
    assert ctrl.view_order == "sourceDesc"           # 축도 초안이 덮는다(판정 B)
    assert ctrl.dispatch("range_draft_apply", {}) == {"ok": True}
    snap = ctrl.snapshot()
    assert ctrl.selection.selected_indices() == [2]
    assert ctrl.view_order == "sourceAsc" and snap["view_order"] == "sourceAsc"
    assert ctrl.filter is not None and ctrl.filter.search_text == "책상"
    assert snap["range_draft"]["open"] is False


def test_range_draft_cancel_discards_only_the_draft(tmp_path):
    """수용 기준 5(§18.10) — 취소는 메인 범위와 실행 증거를 바꾸지 않는다."""
    ctrl, _ = _draft_session(tmp_path)
    before = (ctrl.selection.selected_indices(), ctrl.view_order, ctrl.filter.export_state())
    ctrl.dispatch("range_draft_open", {})
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("filter_search", {"text": "없는값"})
    ctrl.dispatch("set_view_order", {"value": "sourceAsc"})
    ctrl.dispatch("range_draft_cancel", {})
    assert (ctrl.selection.selected_indices(), ctrl.view_order,
            ctrl.filter.export_state()) == before
    assert ctrl.range_draft is None


def test_range_draft_open_is_idempotent(tmp_path):
    """왕복 지연 중 두 번 눌린 출구가 편집을 조용히 되돌리지 않는다(재복제 금지)."""
    ctrl, _ = _draft_session(tmp_path)
    ctrl.dispatch("range_draft_open", {})
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("range_draft_open", {})
    assert ctrl.snapshot()["range_draft"]["sel_count"] == 0


def test_range_draft_dirty_is_the_event_not_the_value(tmp_path):
    """이탈 가드 무장 조건(판정 F) — 열자마자는 깨끗하고, 되돌리면 다시 깨끗하다."""
    ctrl, _ = _draft_session(tmp_path)
    ctrl.dispatch("range_draft_open", {})
    assert ctrl.snapshot()["range_draft"]["dirty"] is False
    ctrl.dispatch("toggle_record", {"index": 1, "value": False})
    assert ctrl.snapshot()["range_draft"]["dirty"] is True
    ctrl.dispatch("toggle_record", {"index": 1, "value": True})
    assert ctrl.snapshot()["range_draft"]["dirty"] is False


def test_stale_draft_is_refused_instead_of_committing_someone_elses_rows(tmp_path):
    """세대 불일치 적용은 거절한다 — 죽은 스냅샷의 index 는 남의 행이다(§10.11.2 실패 면)."""
    ctrl, _ = _draft_session(tmp_path)
    ctrl.dispatch("range_draft_open", {})
    ctrl.dispatch("set_none", {})
    draft = ctrl.range_draft
    ctrl.load_data_path(_data_csv(tmp_path))     # 새 스냅샷 = 초안 폐기 + 세대 증가(판정 J)
    assert ctrl.range_draft is None
    ctrl.range_draft = draft                     # 초안이 살아남는 경로를 가정한 백스톱
    with pytest.raises(ValueError, match="데이터가 바뀌"):
        ctrl.dispatch("range_draft_apply", {})
    assert ctrl.selection.selected_count() == 0  # 마운트 직후 상태 그대로 — 커밋 안 됨


def test_new_data_discards_the_open_draft(tmp_path):
    """판정 J — 데이터 전환은 축을 되돌리고 초안을 버린다."""
    ctrl, _ = _draft_session(tmp_path)
    ctrl.dispatch("range_draft_open", {})
    ctrl.dispatch("set_view_order", {"value": "sourceAsc"})
    ctrl.load_data_path(_data_csv(tmp_path))
    snap = ctrl.snapshot()
    assert snap["range_draft"]["open"] is False and snap["view_order"] == "sourceDesc"


def test_generation_is_refused_while_the_draft_is_open(tmp_path):
    """전역 잠금(§10.11.2 계약면 2) — 보고 있는 범위와 만들어지는 범위가 갈리지 않는다."""
    ctrl, _ = _draft_session(tmp_path)
    ctrl.dispatch("range_draft_open", {})
    res = ctrl.generate()
    assert res["ok"] is False and "범위 편집기" in res["error"]


def test_draft_cannot_open_during_generation(tmp_path):
    ctrl, _ = _draft_session(tmp_path)
    ctrl._generation_lock.acquire()
    try:
        with pytest.raises(ValueError, match="생성이 진행 중"):
            ctrl.dispatch("range_draft_open", {})
    finally:
        ctrl._generation_lock.release()


def test_selected_only_swaps_visibility_without_touching_judgment(tmp_path):
    """「선택된 항목만 보기」는 보기 상태다 — 필터 정의도, 유래 판정도 그대로다."""
    ctrl, _ = _draft_session(tmp_path)
    ctrl.dispatch("range_draft_open", {})
    ctrl.dispatch("filter_search", {"text": "책상"})   # 가시 1행, 선택은 3행 관통
    snap = ctrl.snapshot()
    assert [r["index"] for r in snap["table"]["rows"]] == [2]
    assert snap["restate"]["origin"] == "manual" and snap["restate"]["extra"] == 2
    ctrl.dispatch("set_selected_only", {"value": True})
    snap = ctrl.snapshot()
    assert [r["index"] for r in snap["table"]["rows"]] == [2, 1, 0]   # 선택 전부, 표시순
    assert snap["filter"]["active"] is True and snap["filter"]["search"] == "책상"
    assert snap["restate"]["origin"] == "manual", "보기 상태가 유래 판정을 물들였습니다"
    assert snap["table"]["hidden_selected"] == []
    # 적용해도 보기 상태는 따라가지 않는다(판정 B 예외) — 메인엔 그 토글이 없다.
    ctrl.dispatch("range_draft_apply", {})
    assert ctrl.snapshot()["range_draft"]["selected_only"] is False


def test_draft_table_previews_the_names_the_draft_would_produce(tmp_path):
    """판정 D 세부 — 편집기 안에서 축을 바꾸면 「문서」 열 이름이 즉시 따라온다(판정 I 완화)."""
    ctrl, _ = _draft_session(tmp_path)
    first_desc = ctrl.snapshot()["records"][0]
    assert first_desc["index"] == 2 and first_desc["name"].startswith("doc-001")
    ctrl.dispatch("range_draft_open", {})
    ctrl.dispatch("set_view_order", {"value": "sourceAsc"})
    rows = ctrl.snapshot()["records"]
    assert rows[0]["index"] == 0 and rows[0]["name"].startswith("doc-001")
    # 커밋된 실행 입력은 그대로 — 미리보기는 "적용하면 이렇게 된다"이지 실행 예약이 아니다.
    assert ctrl._indices() == [2, 1, 0]


def test_draft_does_not_leak_into_the_session_guard_or_filter_slot(tmp_path):
    """세션 가드·직전 필터 슬롯은 커밋된 세션의 것이다(판정 D 경계표 2행)."""
    ctrl, _ = _draft_session(tmp_path)
    ctrl.dispatch("range_draft_open", {})
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})
    ctrl.dispatch("filter_search", {"text": "책상"})
    guard = ctrl.snapshot()["guard"]
    # 커밋은 여전히 전체 선택(1클릭 재현) = 비무장. 초안의 수작업 선택이 새면 무장한다.
    assert guard["armed"] is False and guard["sel_count"] == 3
    assert guard["filter_active"] is False, "초안 필터가 세션 가드로 샜습니다."
    assert ctrl._filter_desc == "", "초안 정의가 직전 필터 슬롯 소재로 샜습니다."


def test_selection_key_is_committed_only_so_a_draft_cannot_stale_a_result(tmp_path):
    """리뷰 1R P1 — 완료 결과의 세션 판정은 **커밋된** 실행 입력의 지문만 본다.

    표는 초안을 그리므로(판정 D) 표의 선택 표지로 지문을 만들면 적용도 안 한 편집이 결과를
    「직전 실행」으로 강등시키고, 취소해도 되돌아오지 않는다.
    """
    ctrl, _ = _draft_session(tmp_path)
    before = ctrl.snapshot()["selection_key"]
    ctrl.dispatch("range_draft_open", {})
    ctrl.dispatch("set_none", {})
    snap = ctrl.snapshot()
    assert snap["selection_key"] == before, "초안 편집이 세션 지문을 움직였습니다."
    assert [r["index"] for r in snap["records"] if r["selected"]] == [], (
        "표는 초안을 그려야 합니다(경계표 1행) — 지문만 커밋이다."
    )
    ctrl.dispatch("range_draft_cancel", {})
    assert ctrl.snapshot()["selection_key"] == before


def test_selection_key_follows_the_display_axis(tmp_path):
    """표시순서가 바뀌면 같은 선택도 다른 실행 입력이다(파일 이름이 실제로 달라진다)."""
    ctrl, _ = _draft_session(tmp_path)
    desc = ctrl.snapshot()["selection_key"]
    ctrl.dispatch("set_view_order", {"value": "sourceAsc"})
    assert ctrl.snapshot()["selection_key"] != desc


def test_failed_selection_is_refused_while_a_draft_is_open(tmp_path):
    """결과 구획의 선택 교체는 **커밋** 대상 동사라 초안 아래에서 돌지 않는다(F3)."""
    ctrl, _ = _draft_session(tmp_path)
    ctrl._last_failed = [0]
    ctrl.dispatch("range_draft_open", {})
    with pytest.raises(ValueError, match="범위 편집기"):
        ctrl.dispatch("select_failed", {})
    ctrl.dispatch("range_draft_cancel", {})
    assert ctrl.dispatch("select_failed", {}) == {"selected": 1}


def test_zone_count_follows_the_draft_while_gate_input_stays_committed(tmp_path):
    """리뷰 3R P2 — 표 머리 수치는 표가 그리는 세계의 것이고, 게이트 소재는 커밋이다."""
    ctrl, _ = _draft_session(tmp_path)
    ctrl.dispatch("range_draft_open", {})
    ctrl.dispatch("set_none", {})
    snap = ctrl.snapshot()
    assert snap["zone_selected_count"] == 0, "표 머리가 초안을 따르지 않습니다."
    assert snap["selected_count"] == 3, "게이트 소재가 초안에 물들었습니다."
    ctrl.dispatch("range_draft_cancel", {})
    snap = ctrl.snapshot()
    assert snap["zone_selected_count"] == snap["selected_count"] == 3


# 초안이 열렸을 때 **초안을 따라 움직이는** 스냅샷 키의 정본 목록(지도 §10.11.3 판정 D 경계표).
# 여기 없는 키가 초안 편집에 흔들리면 커밋 세계를 소비하는 판정 하나가 조용히 초안에
# 물든 것이고, 여기 있는 키가 안 흔들리면 편집기가 자기 편집을 안 그리는 것이다.
_DRAFT_FACING_SNAPSHOT_KEYS = {
    "records",              # 표 행(선택 표지·실 파일 이름 미리보기)
    "table",                # 표 페이로드(가시 행·필터 밖 스트립)
    "filter",               # 필터 정의·칩(초안이 편집 중인 정의)
    "restate",              # 선택 유래 재진술(존 소유)
    "range_draft",          # 초안 자신(열림·dirty·수치·보기 상태)
    "zone_selected_count",  # 표 머리 「선택 N/M」 — 표가 그리는 세계의 수치
    # 경계 **자신의 정체**(리뷰 4R): 어느 세계를 편집 중인지의 세대. 내용이 아니라 좌표라
    # 여기 든다 — 세계가 갈릴 때 오르는 것이 이 값의 일이다(단조 증가라 취소해도 안 되돌아온다).
    "zone_epoch",
}


def test_draft_touches_exactly_the_keys_the_boundary_table_names(tmp_path):
    """판정 D 경계표의 **구조 가드** — 새 키가 어느 세계에 속하는지 여기서 선언되게 한다.

    리뷰 1R·2R·3R 이 전부 이 경계의 누수였다(세션 지문·표 머리 수치·늦은 발신). 표를
    문서로만 두면 다음 키가 또 조용히 커밋 세계를 물들인다 — 목록에 없는 키가 초안에
    흔들리면 실패한다(``_SESSION_ATTRS`` 구조 가드 선례).
    """
    ctrl, _ = _draft_session(tmp_path)
    before = ctrl.snapshot()
    ctrl.dispatch("range_draft_open", {})
    ctrl.dispatch("set_none", {})                      # 선택
    ctrl.dispatch("toggle_record", {"index": 1, "value": True})
    ctrl.dispatch("filter_search", {"text": "책상"})    # 필터
    ctrl.dispatch("set_view_order", {"value": "sourceAsc"})  # 축
    after = ctrl.snapshot()
    moved = {k for k in before if before[k] != after.get(k)}
    assert moved == _DRAFT_FACING_SNAPSHOT_KEYS, (
        "초안이 움직인 키가 경계표와 다릅니다 — 커밋 세계로 샜거나(추가) "
        f"편집이 안 그려집니다(누락): 추가={sorted(moved - _DRAFT_FACING_SNAPSHOT_KEYS)}, "
        f"누락={sorted(_DRAFT_FACING_SNAPSHOT_KEYS - moved)}"
    )
    # 취소하면 전부 제자리 — 초안은 아무것도 커밋에 남기지 않는다(불변식 §18.11-21).
    # 예외는 세대뿐이다: 단조 증가가 곧 "버린 세계로는 못 돌아간다"는 보장이라 되돌리면 안 된다.
    ctrl.dispatch("range_draft_cancel", {})
    restored = ctrl.snapshot()
    assert {k for k in before if before[k] != restored.get(k)} == {"zone_epoch"}
    assert restored["zone_epoch"] > before["zone_epoch"]


def test_zone_edit_from_a_dead_world_is_not_applied(tmp_path):
    """리뷰 4R P1 — 느린 출구 뒤에 줄 선 편집이 커밋 범위에 착지하지 않는다.

    세대는 웹이 **보고 있던 세계**의 좌표다. 취소·적용·데이터 교체는 전부 명시 행동이라,
    그 뒤에 도착한 옛 세계의 편집을 지금 세계에 적용하는 쪽이 조용한 파괴다.
    """
    ctrl, _ = _draft_session(tmp_path)
    ctrl.dispatch("range_draft_open", {})
    stale = ctrl.snapshot()["zone_epoch"]          # 초안 세계의 세대
    ctrl.dispatch("range_draft_cancel", {})        # 출구 — 세대가 오른다
    before = ctrl.selection.selected_indices()
    res = ctrl.dispatch("set_none", {"epoch": stale})
    assert res == {"stale": True, "epoch": ctrl.zone_epoch}
    assert ctrl.selection.selected_indices() == before, "죽은 세계의 편집이 커밋에 착지했습니다."
    # 축도 같은 자격이다 — 버린 세계의 순서가 생성 순서를 정하지 않는다.
    assert ctrl.dispatch("set_view_order", {"value": "sourceAsc", "epoch": stale})["stale"]
    assert ctrl.view_order == "sourceDesc"
    # 지금 세계의 편집은 통과한다(세대 검사가 정상 편집을 막지 않는다).
    ctrl.dispatch("set_none", {"epoch": ctrl.zone_epoch})
    assert ctrl.selection.selected_count() == 0


def test_zone_epoch_check_skips_callers_that_do_not_know_worlds(tmp_path):
    """세대를 안 싣는 발신은 무검사 통과 — 존을 공유하는 「기안」 화면의 정답이다."""
    ctrl, _ = _draft_session(tmp_path)
    ctrl.dispatch("set_none", {})
    assert ctrl.selection.selected_count() == 0


def test_new_data_invalidates_in_flight_zone_edits(tmp_path):
    """데이터 교체도 세계를 가른다 — 옛 스냅샷 좌표의 편집이 새 데이터에 착지하지 않는다."""
    ctrl, _ = _draft_session(tmp_path)
    stale = ctrl.snapshot()["zone_epoch"]
    ctrl.load_data_path(_data_csv(tmp_path))
    assert ctrl.dispatch("toggle_record", {"index": 0, "value": True, "epoch": stale})["stale"]
    assert ctrl.selection.selected_count() == 0


# ------------------------- 검토 요구와 승인(재작성 F5, 지도 §10.12 판정 B·F·I·N)
def _rereview(ctrl, name: str = "공고서") -> None:
    """이 작업을 「방금 완주한 것」으로 만든다(재작성 F5).

    규칙을 바꾸면 검토 요구가 서는 것이 계약이다(§13-3). 그것을 겨누지 않는 테스트가
    픽스처의 규칙을 손보면 그 요구에 먼저 걸려 무엇을 재는 테스트인지 흐려진다.
    """
    job = ctrl.registry.load(name)
    job.reviewed_rules = rules_fingerprints(job)
    ctrl.registry.save(job, allow_overwrite=True)


def _unreviewed_session(tmp_path):
    """검토 기준선이 없는 작업 + 데이터 + 저장 폴더 — 게이트가 검토에서 막히는 상태."""
    ctrl, pushes = _controller(tmp_path, reviewed=False)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})  # 빈 값 게이트는 먼저 통과시킨다
    return ctrl, pushes


def test_new_job_is_blocked_until_the_result_is_reviewed(tmp_path):
    """§13-3 — 새 문서 작업은 결과 확인 전 실행을 차단한다."""
    ctrl, _ = _unreviewed_session(tmp_path)
    gate = ctrl.snapshot()["gate"]
    assert gate["enabled"] is False and gate["level"] == "warn"
    assert "아직 한 번도 문서를 만들지 않은" in gate["text"]


def test_approval_opens_the_gate_and_survives_a_push_round_trip(tmp_path):
    ctrl, _ = _unreviewed_session(tmp_path)
    req, unmet = ctrl._review()
    assert unmet is not None
    ctrl.review.approve(req, ctrl._review_scope_key())
    assert ctrl.snapshot()["gate"]["enabled"] is True


def test_selection_change_reinstates_a_selection_bound_approval(tmp_path):
    """판정 I — 새 작업의 증거는 이 배치의 것이라 선택이 바뀌면 다시 확인해야 한다."""
    ctrl, _ = _unreviewed_session(tmp_path)
    req, _ = ctrl._review()
    ctrl.review.approve(req, ctrl._review_scope_key())
    assert ctrl.snapshot()["gate"]["enabled"] is True
    ctrl.dispatch("toggle_record", {"index": 0, "value": False})
    assert ctrl.snapshot()["gate"]["enabled"] is False


def test_display_order_change_reinstates_the_approval(tmp_path):
    """선택 집합이 같아도 순서가 바뀌면 파일 이름이 달라진다(§2 충돌 B) — 같은 실행
    입력이 아니므로 승인이 승계되지 않는다."""
    ctrl, _ = _unreviewed_session(tmp_path)
    req, _ = ctrl._review()
    ctrl.review.approve(req, ctrl._review_scope_key())
    ctrl.dispatch("set_view_order", {"value": "sourceAsc"})
    assert ctrl.snapshot()["gate"]["enabled"] is False


def test_a_completed_run_stamps_the_baseline_so_the_repeat_run_is_quiet(tmp_path):
    """§13-2 — 정상 반복 실행에서 미리보기는 선택이다. 완주가 그 자격을 만든다."""
    ctrl, _ = _unreviewed_session(tmp_path)
    req, _ = ctrl._review()
    ctrl.review.approve(req, ctrl._review_scope_key())
    ctrl.generate()
    assert ctrl.registry.load("공고서").reviewed_rules  # 완주 스탬프가 기준선을 세웠다
    ctrl.review.clear()                                 # 재시작과 같은 상태(승인은 미영속)
    assert ctrl.snapshot()["gate"]["enabled"] is True


def test_an_old_job_without_a_baseline_does_not_claim_it_never_ran(tmp_path):
    """판정 N — 수백 번 실행한 작업에 「아직 한 번도 만들지 않았습니다」는 거짓말이다."""
    ctrl, _ = _controller(tmp_path, reviewed=False)
    ctrl.registry.stamp_last_run("공고서", "2026-07-01T09:00:00")
    ctrl.registry.mutate("공고서", lambda j: setattr(j, "reviewed_rules", {}))  # 구 버전 작업
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})
    text = ctrl.snapshot()["gate"]["text"]
    assert "확인할 수 없습니다" in text and "한 번도" not in text


def test_switching_jobs_does_not_carry_an_approval(tmp_path):
    """승인은 규칙 지문에 결속돼 남의 작업에 닿지 않는다."""
    ctrl, _ = _unreviewed_session(tmp_path)
    req, _ = ctrl._review()
    ctrl.review.approve(req, ctrl._review_scope_key())
    other = ctrl.registry.load("공고서")
    other.name = "다른공고서"
    other.filename_pattern = "다른-{{seq:001}}"
    ctrl.registry.save(other)
    ctrl.dispatch("select_job", {"name": "다른공고서"})
    assert ctrl.snapshot()["gate"]["enabled"] is False


def test_preview_drawer_projects_the_run_input_not_a_recomputation(tmp_path):
    """판정 A — 값·이름은 실행 입력과 **같은 산출**의 투영이다.

    한 건만 따로 계산하면 `{{seq}}` 가 1 로 고정되고 꼬리표가 사라져, 미리보기가 실행과
    다른 이름을 말한다(픽스처 패턴이 `doc-{{seq:001}}` 이라 자리마다 이름이 다르다).
    """
    ctrl, _ = _session(tmp_path)
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("preview_open", {})
    snap = ctrl.snapshot()
    p = snap["preview"]
    assert p["open"] is True and p["pos"] == 0 and p["total"] == 2
    assert p["filename"] == snap["records"][0]["name"] == "doc-001.hwpx"
    ctrl.dispatch("preview_move", {"delta": 1})
    p = ctrl.snapshot()["preview"]
    assert p["pos"] == 1 and p["filename"] == "doc-002.hwpx"


def test_preview_position_follows_the_display_order(tmp_path):
    """판정 M — 자리는 **표시순 서수**다. 원본 index 로 세면 「보이는 것 = 실행되는 것」이
    이 면에서만 깨진다."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("preview_open", {})
    first_desc = ctrl.snapshot()["preview"]["rows"]
    ctrl.dispatch("set_view_order", {"value": "sourceAsc"})
    assert ctrl.snapshot()["preview"]["rows"] != first_desc


def test_preview_move_stops_at_the_edges(tmp_path):
    """순환하지 않는다 — 마지막에서 첫 건으로 돌아가면 몇 번째인지가 끊긴다."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("preview_open", {})
    ctrl.dispatch("preview_move", {"delta": -1})
    assert ctrl.snapshot()["preview"]["pos"] == 0
    ctrl.dispatch("preview_move", {"delta": 5})
    assert ctrl.snapshot()["preview"]["pos"] == 1


def test_preview_opens_even_when_nothing_needs_review(tmp_path):
    """§13-2 — 정상 반복 실행에서 미리보기는 **선택**이지 금지가 아니다."""
    ctrl, _ = _session(tmp_path)
    assert ctrl.snapshot()["review"]["required"] is False
    ctrl.dispatch("preview_open", {})
    p = ctrl.snapshot()["preview"]
    assert p["open"] is True and p["can_approve"] is False  # 승인 버튼은 안 선다


def test_opening_the_preview_is_not_approval(tmp_path):
    """불변식 §13-4 — PreviewCreated 와 PreviewApproved 는 다른 사건이다."""
    ctrl, _ = _unreviewed_session(tmp_path)
    ctrl.dispatch("preview_open", {})
    assert ctrl.snapshot()["gate"]["enabled"] is False
    ctrl.dispatch("preview_approve", {})
    assert ctrl.snapshot()["gate"]["enabled"] is True


def test_approval_is_refused_outside_the_drawer(tmp_path):
    """승인은 증거를 본 사건이다 — 증거를 띄우지 않은 경로로 세우면 그 승인은 무엇에
    근거했는지 말할 수 없다(F-06 이 지목한 결함을 우리 손으로 재현하는 꼴)."""
    ctrl, _ = _unreviewed_session(tmp_path)
    with pytest.raises(ValueError, match="미리보기를 연 뒤"):
        ctrl.dispatch("preview_approve", {})


def test_approval_is_refused_when_nothing_needs_review(tmp_path):
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("preview_open", {})
    with pytest.raises(ValueError, match="확인이 필요한 변경이 없습니다"):
        ctrl.dispatch("preview_approve", {})


def test_preview_refuses_to_open_over_a_range_draft(tmp_path):
    """판정 H — 미리보기는 **커밋된** 실행 입력의 상이다. 초안 세계를 그리면 적용도 안 한
    편집을 승인하게 되고 그건 불변식 21 위반이다."""
    ctrl, _ = _draft_session(tmp_path)
    ctrl.dispatch("range_draft_open", {})
    with pytest.raises(ValueError, match="범위 편집"):
        ctrl.dispatch("preview_open", {})


def test_preview_refuses_to_open_with_no_selection(tmp_path):
    """§18.11-6 — 선택 0건에서는 미리보기에 진입하지 않고 첫 레코드로 대신하지 않는다."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("set_none", {})
    with pytest.raises(ValueError, match="최소 1건"):
        ctrl.dispatch("preview_open", {})
    assert ctrl.snapshot()["preview"]["can_open"] is False


def test_preview_survives_a_shrinking_selection_by_restating(tmp_path):
    """§10.12.1 실패 경로 — 면 안에서 재진술하고 **닫지 않는다**."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("preview_open", {})
    ctrl.dispatch("preview_move", {"delta": 1})
    ctrl.dispatch("set_none", {})
    p = ctrl.snapshot()["preview"]
    assert p["open"] is True and p["total"] == 0
    assert "선택한 문서가 없습니다" in p["empty_note"]


def test_switching_jobs_closes_the_preview(tmp_path):
    """열려 있던 면은 남의 작업의 값을 그린다 — 상태의 진실은 DOM 이 아니라 여기다."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("preview_open", {})
    ctrl.dispatch("select_job", {"name": ""})
    assert ctrl.snapshot()["preview"]["open"] is False


def test_preview_evidence_names_the_change_and_its_scale(tmp_path):
    """판정 D — before/after 는 짓지 않는다(원천이 없다). 현재 값 + 대상 + 영향 규모."""
    ctrl, _ = _controller(tmp_path, reviewed=True)
    job = ctrl.registry.load("공고서")
    job.mapping.mappings[0].source = "presmptPrce"   # 의미 연결 변경
    ctrl.registry.save(job, allow_overwrite=True)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("preview_open", {})
    ev = ctrl.snapshot()["preview"]["evidence"]
    assert ev["policy"] == "value_scope_summary"
    assert [r["name"] for r in ev["rows"]] == ["공고명"]
    assert "서로 다른 값" in ev["rows"][0]["note"] and "비는 문서 1건" in ev["rows"][0]["note"]


def test_filename_risk_evidence_reports_the_set_not_one_name(tmp_path):
    """C-01 — 대표 이름 한 건은 패턴 형태만 답한다. 집합 성질은 따로 세어 말한다."""
    ctrl, _ = _controller(tmp_path, reviewed=True)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "{{공고명}}"   # seq 를 뺀다 = 이름이 값에만 의존
    ctrl.registry.save(job, allow_overwrite=True)
    ctrl.dispatch("select_job", {"name": "공고서"})
    csv = tmp_path / "dup.csv"
    csv.write_text("bidNtceNm,presmptPrce\n같은이름,1\n같은이름,2\n", encoding="utf-8")
    _mount_all(ctrl, str(csv))
    ctrl.dispatch("preview_open", {})
    ev = ctrl.snapshot()["preview"]["evidence"]
    assert ev["policy"] == "name_set_summary"
    assert "꼬리표가 붙은 문서 1건" in ev["note"]


def test_scope_says_default_rules_without_hinting_at_overrides(tmp_path):
    """적용 범위는 「기본 규칙」 고정이다(F5 확정: override 는 F7) — 없는 기능을 암시하는
    문안은 미끼다."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("preview_open", {})
    scope = ctrl.snapshot()["preview"]["scope"]
    assert "기본 규칙" in scope and "이번 생성" not in scope


# ---------------- 리뷰 1R 조치의 영구 가드(P1×2·P2×1) ----------------
def test_generation_backstop_refuses_an_unapproved_run(tmp_path):
    """1R P1 — 게이트는 **스냅샷을 만들 때** 판정한다. 스냅샷을 안 거치는 경로(브리지
    `generate` 직접 호출·stale 프론트)가 승인 없이 생성을 내면 안 된다.

    미입력 게이트가 같은 이유로 백스톱을 두는 자리다: 버튼 비활성은 표면의 사실이지
    계약이 아니다.
    """
    ctrl, _ = _unreviewed_session(tmp_path)
    res = ctrl.generate()          # 화면을 거치지 않고 곧바로 호출
    assert res["ok"] is False and res["level"] == "warn"
    assert "미리보기" in res["error"]
    assert not list((tmp_path / "out").glob("*.hwpx")), "승인 없이 문서가 생성됐습니다."


def test_generation_backstop_catches_a_rule_change_after_the_gate_opened(tmp_path):
    """승인 뒤 규칙이 바뀌면(에디터 저장) 그 승인은 무효다 — 백스톱이 지금 다시 묻는다."""
    ctrl, _ = _unreviewed_session(tmp_path)
    req, _ = ctrl._review()
    ctrl.review.approve(req, ctrl._review_scope_key())
    assert ctrl.snapshot()["gate"]["enabled"] is True
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "다른-{{seq:001}}"
    ctrl.registry.save(job, allow_overwrite=True)
    ctrl.vm.job.filename_pattern = "다른-{{seq:001}}"   # 세션이 편집 결과를 받은 상태
    assert ctrl.generate()["ok"] is False


def test_completed_run_stamps_the_rules_it_used_not_the_disk(tmp_path):
    """1R P1 — 배치 중 착지한 에디터 저장이 **한 번도 실행된 적 없는 규칙**을 검토받은
    것으로 만들면 안 된다(조용한 승인). 런의 규칙을 찍으면 요구가 그대로 선다."""
    ctrl, _ = _unreviewed_session(tmp_path)
    req, _ = ctrl._review()
    ctrl.review.approve(req, ctrl._review_scope_key())
    ran_pattern = ctrl.vm.job.filename_pattern
    # 배치가 도는 사이 같은 프로세스의 에디터가 저장한 상황을 스탬프 직전에 재현한다.
    real_stamp = ctrl.registry.stamp_last_run

    def racing_stamp(name, when, **kw):
        edited = ctrl.registry.load(name)
        edited.filename_pattern = "에디터가-바꾼-{{seq:001}}"
        ctrl.registry.save(edited, allow_overwrite=True)
        return real_stamp(name, when, **kw)

    ctrl.registry.stamp_last_run = racing_stamp  # type: ignore[method-assign]
    assert ctrl.generate()["ok"] is True
    after = ctrl.registry.load("공고서")
    assert after.reviewed_rules["filename"] == ran_pattern, (
        "디스크의 새 규칙이 검토 없이 기준선이 됐습니다 — 조용한 승인입니다."
    )
    assert review_requirement(after).required


def test_preview_names_match_what_generation_will_write(tmp_path):
    """1R P2 — 확인된 빈칸은 문서에 **표식 문자열**로 들어간다. 파일명 패턴이 그 필드를
    참조하면 표식 없는 값으로 그린 미리보기는 **생성될 것과 다른 이름을 승인**시킨다.
    """
    ctrl, _ = _controller(tmp_path, reviewed=True)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "{{추정가격}}"    # 빈 값이 나는 필드를 이름이 참조한다
    ctrl.registry.save(job, allow_overwrite=True)
    _rereview(ctrl)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})
    ctrl.dispatch("preview_open", {})
    shown = ctrl.snapshot()["preview"]["filename"]
    assert ctrl.generate()["ok"] is True
    written = {p.name for p in (tmp_path / "out").glob("*.hwpx")}
    assert shown in written, f"미리보기 이름 {shown!r} 가 생성물 {written!r} 에 없습니다."


def test_the_marker_appears_only_when_generation_would_apply_it(tmp_path):
    """반대 방향의 같은 거짓말 — 아직 확인 안 된 빈 값이 있으면 생성은 3) 에 도달하지
    못하므로 표식도 없다. 조건을 느슨히 잡으면 실행되지도 않을 상태의 이름을 말한다."""
    ctrl, _ = _controller(tmp_path, reviewed=True)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "{{추정가격}}"
    ctrl.registry.save(job, allow_overwrite=True)
    _rereview(ctrl)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("preview_open", {})
    ctrl.dispatch("preview_move", {"delta": 1})   # 빈 값이 나는 레코드로 이동
    before = ctrl.snapshot()["preview"]["filename"]     # 미확인 = 표식 없음
    ctrl.dispatch("ack_field", {"field": "추정가격"})
    after = ctrl.snapshot()["preview"]["filename"]      # 확인 뒤 = 표식 적용
    assert "미입력" not in before and "미입력" in after


def test_the_mirror_still_counts_blanks_as_blank(tmp_path):
    """표식은 **파일 이름·미리보기 값**의 사실이고, 거울의 「N행에서 값이 비어 있습니다」는
    빈 값을 세는 진술이다. 표식을 채우면 언제나 0행이 되어 그 문안이 거짓이 된다 —
    두 면이 같은 사실을 다른 각도로 말하는 것이지 판정이 둘인 게 아니다."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("ack_field", {"field": "추정가격"})
    row = next(r for r in ctrl.snapshot()["mirror"] if r["name"] == "추정가격")
    assert "1행에서 값이 비어 있습니다" in row["value"]


# ---------------- 리뷰 2R 조치의 영구 가드(P1×1·P2×2) ----------------
def test_approval_does_not_survive_a_data_swap(tmp_path):
    """2R P1 — 데이터 A 에서 승인한 뒤 데이터 B 를 올리면 선택은 0건으로 리셋되지만
    세션의 승인 집합은 남는다. 같은 index 를 다시 고르는 순간 **같은 키가 재구성돼**
    B 의 값·이름을 한 번도 보지 않은 채 게이트가 열리면 안 된다.
    """
    ctrl, _ = _unreviewed_session(tmp_path)
    req, _ = ctrl._review()
    ctrl.review.approve(req, ctrl._review_scope_key())
    assert ctrl.snapshot()["gate"]["enabled"] is True

    other = tmp_path / "b.csv"
    other.write_text("bidNtceNm,presmptPrce\n다른공고,\n다른비품,3000000\n", encoding="utf-8")
    _mount_all(ctrl, str(other))          # 같은 열 지형·같은 행 수 = 같은 index 집합
    ctrl.dispatch("ack_field", {"field": "추정가격"})
    assert ctrl.snapshot()["gate"]["enabled"] is False, (
        "다른 데이터의 값을 보지 않은 채 승인이 재사용됐습니다."
    )
    assert ctrl.generate()["ok"] is False   # 백스톱도 같은 판정을 낸다


def test_approval_scope_key_is_separate_from_the_result_fingerprint(tmp_path):
    """두 값이 묻는 질문이 다르다: 결과 강등은 "지금 실행 입력의 것인가", 승인은 "무엇을
    보고 난 것인가". 한 문자열이 둘을 겸하면 한쪽 요구가 다른 쪽 의미를 조용히 바꾼다."""
    ctrl, _ = _session(tmp_path)
    before_sel, before_scope = ctrl._selection_key(), ctrl._review_scope_key()
    _mount_all(ctrl, _data_csv(tmp_path))   # 같은 파일 재마운트 = 같은 선택 지문
    assert ctrl._selection_key() == before_sel
    assert ctrl._review_scope_key() != before_scope, (
        "새 스냅샷인데 승인 범위 키가 그대로입니다 — 승인이 되살아납니다."
    )


def test_preview_and_table_agree_on_the_filename_timestamp(tmp_path):
    """2R P2 — 게이트 감사(refresh)와 표 「문서」 열이 각자 시각을 찍으면 `{{date:SS}}`
    가 초 경계를 넘는 순간 드로어가 승인시킨 이름과 생성물이 갈린다."""
    ctrl, _ = _controller(tmp_path, reviewed=True)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "doc-{{date:HHmmSS}}-{{seq}}"
    ctrl.registry.save(job, allow_overwrite=True)
    _rereview(ctrl)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("preview_open", {})
    snap = ctrl.snapshot()
    assert snap["preview"]["filename"] == snap["records"][0]["name"]


# ---------------- 리뷰 3R 조치의 영구 가드(P2×2) ----------------
def test_the_approved_filename_survives_the_pushes_between_approval_and_generation(tmp_path):
    """3R P2 — 시각은 **승인의 일부**다.

    정상 흐름에서 승인 왕복과 면 닫기가 각각 push 를 부른다. 그 사이 `{{date:SS}}` 가 초
    경계를 넘으면 생성이 사용자가 승인하지 않은 이름을 쓴다 — 승인 키는 여전히 유효한
    채로. 누군가 그 값에 기대고 있는 동안(면이 열려 있거나 승인이 서 있는 동안) 얼린다.
    """
    ctrl, _ = _controller(tmp_path, reviewed=False)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "doc-{{date:HHmmSS}}-{{seq}}"
    ctrl.registry.save(job, allow_overwrite=True)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})

    ctrl.dispatch("preview_open", {})
    approved_name = ctrl.snapshot()["preview"]["filename"]
    frozen = ctrl._names_now
    ctrl.dispatch("preview_approve", {})          # push 1
    ctrl.dispatch("preview_close", {})            # push 2
    ctrl.snapshot()                               # 그 뒤의 임의 재렌더
    assert ctrl._names_now == frozen, "승인 뒤 파일 이름의 시각이 움직였습니다."
    assert ctrl.generate()["ok"] is True
    assert approved_name in {p.name for p in (tmp_path / "out").glob("*.hwpx")}


def test_the_timestamp_refreshes_when_nothing_depends_on_it(tmp_path):
    """반대 방향 — 아무도 안 기대면 새로 찍는다(오래 열어 둔 세션의 날짜가 늙지 않게)."""
    ctrl, _ = _session(tmp_path)
    ctrl.snapshot()
    first = ctrl._names_now
    ctrl._names_now = datetime(2020, 1, 1)       # 늙은 값을 심는다
    ctrl.snapshot()
    assert ctrl._names_now != datetime(2020, 1, 1) and first is not None


def test_an_optional_preview_pins_the_timestamp_until_generation(tmp_path):
    """5R P2 — 검토 요구가 없는 반복 실행에서도 미리보기는 열린다(§13-2). 생성 버튼을
    누르려면 면을 **닫아야** 하는데, 닫는 순간 시각이 풀리면 1초만 들여다봐도 화면이
    보여준 것과 다른 이름(그리고 다른 덮어쓰기 대상)이 만들어진다.
    """
    ctrl, _ = _session(tmp_path)
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("ack_field", {"field": "추정가격"})
    assert ctrl.snapshot()["review"]["required"] is False   # 요구 없는 반복 실행
    ctrl.dispatch("preview_open", {})
    ctrl.snapshot()
    frozen = ctrl._names_now
    ctrl.dispatch("preview_move", {"delta": 1})
    assert ctrl._names_now == frozen                        # 보는 동안 얼어 있다
    ctrl.dispatch("preview_close", {})
    ctrl.snapshot()
    assert ctrl._names_now == frozen, "면을 닫자 본 이름의 시각이 풀렸습니다."
    assert ctrl.generate()["ok"] is True
    ctrl.snapshot()
    assert ctrl._names_now != frozen, "생성이 소비한 뒤에도 시각이 붙들려 있습니다."


def test_the_pin_releases_when_the_run_input_changes(tmp_path):
    """핀은 **실행 입력이 그대로인 동안**만 유효하다 — 선택이 바뀌면 화면이 보여준
    이름도 이미 낡았으므로 새로 찍는 게 맞다(승인 정체와 같은 축)."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("preview_open", {})
    ctrl.snapshot()
    frozen = ctrl._names_now
    ctrl.dispatch("preview_close", {})
    ctrl.dispatch("toggle_record", {"index": 0, "value": False})
    ctrl.snapshot()
    assert ctrl._names_now != frozen


def test_approval_does_not_survive_acknowledging_blanks(tmp_path):
    """4R P2 — 확인 안 된 빈 값이 있는 상태로 승인하면 값은 비어 있고 이름은 표식 없이
    계산된다. 면을 닫고 빈 값을 확인하는 순간 실행 입력이 표식으로 바뀌는데, 규칙도 선택도
    안 바뀌었으니 승인은 그대로 유효하다 — 그러면 생성이 **한 번도 보여준 적 없는** 값과
    이름을 쓴다. 표식 상태를 승인 정체에 넣어 그 창을 닫는다.
    """
    ctrl, _ = _controller(tmp_path, reviewed=False)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "{{추정가격}}"     # 빈 값이 나는 필드를 이름이 참조한다
    ctrl.registry.save(job, allow_overwrite=True)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))

    ctrl.dispatch("preview_open", {})          # 빈 값 미확인 상태에서 미리보기
    ctrl.dispatch("preview_approve", {})
    ctrl.dispatch("ack_field", {"field": "추정가격"})   # 실행 입력이 표식으로 바뀐다
    assert ctrl.snapshot()["gate"]["enabled"] is False, (
        "표식이 붙어 값·이름이 달라졌는데 옛 승인이 그대로 유효합니다."
    )
    assert ctrl.generate()["ok"] is False


def test_unacknowledging_blanks_restores_the_earlier_approval(tmp_path):
    """되돌리면 되살아난다 — 표식 상태는 정체의 일부이지 단조 무효화 신호가 아니다
    (같은 실행 입력으로 돌아왔으면 이미 확인한 것이 맞다)."""
    ctrl, _ = _controller(tmp_path, reviewed=False)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "{{추정가격}}"
    ctrl.registry.save(job, allow_overwrite=True)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    ctrl.dispatch("preview_open", {})
    ctrl.dispatch("preview_approve", {})
    ctrl.dispatch("ack_field", {"field": "추정가격"})
    assert ctrl.snapshot()["gate"]["enabled"] is False
    ctrl.dispatch("unack_field", {"field": "추정가격"})
    assert ctrl.snapshot()["gate"]["enabled"] is False   # 빈 값 게이트가 다시 닫는다
    assert ctrl._review()[1] is None, "같은 실행 입력인데 승인이 사라졌습니다."
