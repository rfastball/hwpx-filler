"""「작업」 화면 컨트롤러 계약 가드 — pywebview/Qt 불필요(헤드리스).

패널 4존이 소비하는 링1 배선(부록 A-1)을 창 없이 되읽는다: 좌 목록 → 작업 선택 → 데이터 겨눔
→ 빈 값 승인 게이트(blank_set — U2 §2.13, 구 필드축 ack 의 승계) → 덮어쓰기 재진술(RC-02)
→ 생성 end-to-end. JobController가 링1 계약을 위임해 소비하는지 못박는다.
"""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

import pytest

from hwpxfiller.core.job import Job, rules_fingerprints
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.core.text_registry import TextTemplateRegistry
from hwpxfiller.data.factory import source_for_path, source_from_pool_item
from hwpxfiller.webapp.screen_library import LibraryController
from hwpxfiller.core.mapping import FieldMapping, MappingProfile
from hwpxfiller.gui.review_state import review_requirement
from hwpxfiller.gui.run_state import RunViewModel
from hwpxfiller.gui.selection_state import SelectionModel
from hwpxfiller.gui.work_candidates import MAIN_TOP_N
from hwpxfiller.webapp.screen_job import JobController
# TargetFontSetting 은 「기안」 사망(F6 PR-B)으로 작업대 모듈이 승계(동일 클래스·영속 키).
from hwpxfiller.webapp.screen_workbench import TargetFontSetting, WorkbenchController
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


# JobController 는 factory 포트가 **필수 주입**(P2-16 — 조립은 Host 한 곳)이라
# 테스트 생성 지점마다 canonical concrete 한 벌을 명시로 관통시킨다.
_FACTORIES = {
    "file_source_factory": source_for_path,
    "pool_source_factory": source_from_pool_item,
}


def _deps(tmp_path, lock: "threading.Lock | None" = None):
    """구성 공통 주입 한 벌 — pool_registry(#570)·generation_lock(P2-24)은 폴백이
    제거돼 **명시 주입**한다. ``lock`` 은 화면 간 공유를 재는 테스트의 관통용."""
    return {
        **_FACTORIES,
        "pool_registry": DatasetPoolRegistry(tmp_path / "pool"),
        "generation_lock": lock if lock is not None else threading.Lock(),
    }


def _controller(tmp_path, *, reviewed: bool = True, file_source_factory=source_for_path):
    pushes: list = []
    ctrl = JobController(
        _registry(tmp_path, reviewed=reviewed), lambda s, snap: pushes.append((s, snap)),
        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
        generation_lock=threading.Lock(),
        file_source_factory=file_source_factory,
        pool_source_factory=source_from_pool_item,
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


def _approve_run(ctrl) -> None:
    """확인 면에서 승인한다 — 구 필드축 ack 게이트 통과의 승계 헬퍼(U2 §2.13).

    빈 값이 있으면 blank_set 검토 요구가 서므로(침묵 금지), 게이트를 열려면 확인 면을
    열어 승인해야 한다 — 표식 삽입 동의는 승인 1번이 겸한다.
    """
    ctrl.dispatch("preview_open", {})
    ctrl.dispatch("preview_approve", {})
    ctrl.dispatch("preview_close", {})


# ---------------------------------------------------------------- 스냅샷 골격
def test_initial_then_selection_and_mount_serialize_the_session(tmp_path):
    # 파일 마운트가 **주입된** factory 를 타는지 기록으로 봉인(P2-16) — concrete 만 넣으면
    # 컨트롤러가 다른 경로로 구체를 재선택하는 우회를 놓친다.
    factory_calls: list = []

    def recording_factory(path, *, sheet=None):
        factory_calls.append((path, sheet))
        return source_for_path(path, sheet=sheet)

    ctrl, _ = _controller(tmp_path, file_source_factory=recording_factory)
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
        "top": [], "sections": [], "more": 0, "needs_count": 0, "suggested": "",
        "txt_note": "",
    }
    # 문서 탐색도 미계산 골격(§18.1) — 탭·검색어는 세션 기본값을 그대로 재진술한다.
    assert snap["browse"]["rows"] == [] and snap["browse"]["available_count"] == 0
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["has_job"] is True and snap["job_name"] == "공고서"
    # 저장 폴더 기본값 = 템플릿 폴더/Results(실행 화면 동형).
    assert snap["out_dir"].endswith("Results")
    ctrl.load_data_path(_data_csv(tmp_path))
    assert factory_calls == [(_data_csv(tmp_path), None)]  # 주입 factory 경유 1회
    snap = ctrl.snapshot()
    assert snap["has_data"] is True and snap["record_count"] == 2
    assert snap["selected_count"] == 0  # 마운트 직후 선택 0건(§18.2 — 구 전체선택 개정)
    assert snap["template_path"].endswith("t.hwpx")  # 추적성 로케이트용 전체 경로(#53-B)
    ctrl.dispatch("set_all", {})
    snap = ctrl.snapshot()
    assert snap["selected_count"] == 2
    # 본문 존 = 표 없는 한 줄(U2 §2.13) — 값 표(mirror)는 죽고 빈 값 표지 재료만 남는다.
    assert "mirror" not in snap, "값을 말하는 거울 payload 가 부활했습니다(§2.13)."
    assert snap["blank_fields"] == ["추정가격"]  # rec0 빈값 → 빈 값 표지 지목


def test_data_mount_identity_changes_on_every_remount(tmp_path):
    """결과 처분(§2.18)의 데이터 성분은 **정체**이지 표시 라벨이 아니다(#363 리뷰 P2).

    `data_source_label` 은 「파일: <basename>」이라 세 경우가 전부 같은 문자열이 된다 —
    ①같은 basename 의 다른 파일 ②같은 통합문서의 다른 시트 ③같은 경로의 바뀐 내용.
    그 값으로 교체를 판정하면 결과가 **남의 데이터에 붙은 채** 초기화도 강등도 아닌
    상태로 남는다. 스냅샷은 마운트 세대(`data_mount`)를 실어 세 경우 모두 갈리게 한다.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})

    a = tmp_path / "a" / "d.csv"
    a.parent.mkdir()
    a.write_text("bidNtceNm,presmptPrce\n전산장비,1\n", encoding="utf-8")
    b = tmp_path / "b" / "d.csv"          # ① 같은 basename, 다른 경로
    b.parent.mkdir()
    b.write_text("bidNtceNm,presmptPrce\n사무비품,2\n", encoding="utf-8")

    ctrl.load_data_path(str(a))
    first = ctrl.snapshot()
    ctrl.load_data_path(str(b))
    second = ctrl.snapshot()
    assert first["data_source_label"] == second["data_source_label"], (
        "픽스처가 라벨 충돌을 재현하지 못했습니다 — 이 테스트가 재는 것이 사라집니다."
    )
    assert first["data_mount"] != second["data_mount"], (
        "같은 이름의 다른 파일이 같은 마운트 정체입니다 — 교체가 전환으로 안 읽힙니다."
    )

    # ③ 같은 경로의 바뀐 내용 — 경로·시트 정체는 그대로지만 레코드가 새것이다.
    b.write_text("bidNtceNm,presmptPrce\n전산장비,3\n계약건,4\n", encoding="utf-8")
    ctrl.load_data_path(str(b))
    third = ctrl.snapshot()
    assert third["data_mount"] != second["data_mount"], (
        "같은 경로 재읽기가 같은 마운트 정체입니다 — 새 레코드에 옛 결과가 붙습니다."
    )

    # ② 같은 통합문서의 다른 시트(다중 시트 픽스처) — 경로가 같아도 다른 데이터다.
    ctrl.load_data_path(str(MULTI_SHEET), sheet="공고목록")
    s1 = ctrl.snapshot()
    ctrl.load_data_path(str(MULTI_SHEET), sheet="낙찰현황")
    s2 = ctrl.snapshot()
    assert s1["data_source_label"] == s2["data_source_label"], (
        "픽스처가 시트 축의 라벨 충돌을 재현하지 못했습니다."
    )
    assert s1["data_mount"] != s2["data_mount"], (
        "같은 통합문서의 다른 시트가 같은 마운트 정체입니다."
    )

    # 반대 방향(과경고 금지): 마운트하지 않는 전이는 정체를 흔들지 않는다 — 흔들면
    # 선택·규칙 축의 강등 계약(판정 G)이 초기화로 덮인다.
    stable = ctrl.snapshot()["data_mount"]
    ctrl.dispatch("set_all", {})
    ctrl.dispatch("set_view_order", {"value": "sourceAsc"})
    ctrl.dispatch("select_job", {"name": "공고서"})
    assert ctrl.snapshot()["data_mount"] == stable, (
        "선택·축·작업 전환이 데이터 정체를 바꿉니다 — 강등이어야 할 축이 초기화됩니다."
    )


def test_exit_summary_leaks_no_count_and_invents_none(tmp_path):
    """퇴장 요약(§2.18)은 성공·실패·미착수를 **하나도 흘리지 않는다**(#363 리뷰 P2).

    이 문장은 결과 구획이 초기화된 뒤 남는 **유일한 흔적**이라 손실이 곧 은폐다. 구획
    제목(`_run_title`)은 반대로 일부러 짧다 — 취소 갈래가 실패 수를 접고 `failed` 태가
    수치를 통째로 생략하는데, 화면에서는 옆의 요약·실패 행이 그것을 말하기 때문이다.
    그래서 두 문장은 목적이 다른 **별개 합성기**이고 둘 다 Python 이 소유한다(층을 넘는
    재조립만 금지이지 같은 층의 두 문장은 `summary` 선례가 이미 있다).
    """
    from hwpxfiller.webapp.screen_job import _run_exit_summary, _run_title

    # ① 취소 + 실패 혼재 — 제목이 접는 실패 수가 여기서는 남는다(리뷰가 지목한 자리).
    mixed = _run_exit_summary("partiallyCompleted", True, 5, 1, 6, 6, 12)
    assert mixed == "중단 · 5개 성공 · 1개 실패 · 미착수 6건"
    assert "1개 실패" not in _run_title("partiallyCompleted", True, 5, 1), (
        "제목이 실패 수를 이미 말하면 이 합성기의 존재 이유가 사라집니다(전제 확인)."
    )
    # ② 레코드 처리 전 failed — 시도가 0 이라 성공/실패로 가르지 않는다. 그 페이로드는
    #    같은 레코드를 failed·unstarted 에 동시에 세므로 이어 붙이면 같은 건을 두 번 말한다.
    assert _run_exit_summary("failed", False, 0, 12, 12, 0, 12) == "생성 시작 전 실패 · 대상 12건"
    # ③ 첫 건 전 취소 — 완료 0 은 지어낸 성분이 아니라 「어디까지 됐나」의 답이다.
    assert _run_exit_summary("partiallyCompleted", True, 0, 0, 12, 0, 12) == "중단 · 0개 성공 · 미착수 12건"
    # ④ 정상 완주 · ⑤ 일부 실패 — 0 인 성분(실패·미착수)은 붙지 않는다.
    assert _run_exit_summary("completed", False, 12, 0, 0, 12, 12) == "12개 성공"
    assert _run_exit_summary("partiallyCompleted", False, 10, 2, 0, 12, 12) == "10개 성공 · 2개 실패"
    # 전건 실패(레코드는 시도됨) — 시작 전 실패와 다른 사실이라 다르게 말한다.
    assert _run_exit_summary("failed", False, 0, 3, 0, 3, 3) == "0개 성공 · 3개 실패"


def test_generate_result_carries_the_exit_summary(tmp_path):
    """생성 결과 payload 가 퇴장 요약을 싣는다 — 표면이 수치를 재조립하지 않는 전제.

    빈 값 없는 데이터를 쓴다 — 빈 값 게이트(확인이든 승인이든)는 이 테스트의 축이
    아니고, 그것을 태우면 무엇을 재는 테스트인지 흐려진다.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    clean = tmp_path / "clean.csv"
    clean.write_text("bidNtceNm,presmptPrce\n전산장비,1000\n사무비품,2000000\n", encoding="utf-8")
    _mount_all(ctrl, str(clean))
    ctrl.set_output_folder(str(tmp_path / "out"))
    res = ctrl.generate()
    assert res["ok"] is True
    assert res["exit_summary"] == "2개 성공", res["exit_summary"]


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


def test_every_durable_rule_writer_refuses_while_generating(tmp_path):
    """진행 중 런과 겹치는 **규칙 쓰기**는 표면을 가리지 않고 거절된다(9R P1).

    리뷰는 편집기 진입 하나를 지적했지만, 같은 부류의 자리가 셋이다 — 편집기 진입·「문서
    만들기」 재연결·라이브러리 재연결. 진행 중 배치는 옛 vm 을 고정해 뒀으므로 그 사이
    durable 규칙이 바뀌면 결과가 **디스크에 없는 세대**를 자기 근거로 댄다(§13-7).

    자물쇠가 화면 소유였던 것이 이 결함의 형태다: 라이브러리는 런을 돌리지 않아 자기
    자물쇠를 봐도 늘 열려 있었다. 그래서 앱이 **하나를 주입**하고 세 자리가 같은 것을 본다.
    """
    lock = threading.Lock()
    reg = JobRegistry(tmp_path / "jobs")
    job_ctrl = JobController(reg, lambda s, snap: None, **_deps(tmp_path, lock))
    lib_ctrl = LibraryController(
        reg, TextTemplateRegistry(tmp_path / "txt"), lambda s, snap: None,
        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
        generation_lock=lock,
    )
    assert lock.acquire(blocking=False)
    try:
        # ①편집기 진입 술어(app.open_job_in_editor 가 부르는 그 메서드) ②·③ 두 재연결
        with pytest.raises(ValueError, match="생성이 진행 중"):
            job_ctrl.raise_if_generating("편집기를 여세요")
        with pytest.raises(ValueError, match="생성이 진행 중"):
            job_ctrl.dispatch("relink_template", {"name": "공고서", "path": "x.hwpx"})
        with pytest.raises(ValueError, match="생성이 진행 중"):
            lib_ctrl.dispatch("relink_template", {"name": "공고서", "path": "x.hwpx"})
    finally:
        lock.release()


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


def test_candidate_cards_carry_template_identity_and_connection_state(tmp_path):
    """후보 카드의 템플릿 정체 + 「연결 상태」(U2 §4 판정 B·C·F, #342).

    죽은 「선택한 작업」 존의 승계 payload: 활성 카드 확장 부제(파일명)·⋮(전체 경로)가
    카드 자신의 값을 읽고, `template_missing` 경보는 카드 「연결 상태」 축으로 옮겨간다 —
    문안(`conn_label`)은 Python 이 정본으로 낸다(텍스트가 정본, 색은 강조). §18.4 는
    available 판정에 Template 읽기를 섞지 않지만(판정 F) 부재는 파일 존재 검사 하나라
    후보 축에서 이미 말한다 — 눌러본 뒤에 차단하는 것은 뒤늦은 경보다.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_data_csv(tmp_path))
    card = ctrl.snapshot()["candidates"]["top"][0]
    assert card["template_name"] == "t.hwpx"
    assert card["template_path"].endswith("t.hwpx")           # ⋮ 가 겨눌 전체 경로
    assert card["template_missing"] is False
    assert card["conn_label"] == ""                            # 정상은 조용히(F30 동형)

    Path(card["template_path"]).unlink()                       # 템플릿 파일 소실 재현
    after = ctrl.snapshot()["candidates"]["top"][0]
    assert after["template_missing"] is True                   # available 은 유지(§18.4)
    assert after["conn_label"] == "템플릿 없음"                # 경고 문안도 Python 정본


# 재연결 도달 불변식의 **조건 조합 순회**(#342 리뷰 3라운드 근본 조치).
#
# 세 라운드가 같은 결함류를 세 조건에서 각각 냈다(순위 슬라이스 밖 / ranked 밖 / 데이터
# 미마운트). 뿌리는 도달 보장을 **후보 구획**(데이터·호환성·슬라이스 셋에 걸린 투영)에
# 얹은 것이고, 조건을 하나씩 때우면 다음 조건에서 또 샌다. 그래서 시나리오를 쌓는 대신
# 불변식 하나를 세우고 그 조건 공간을 순회한다:
#
#   **활성 작업이 있고 템플릿이 부재면, 세션 스냅샷이 그 사실과 문안을 싣는다.**
#
# 그것이 곧 화면의 도달 보장이다 — 액션바(상수 높이 층)가 이 두 값만 읽어 「연결 상태」와
# 「템플릿 다시 연결…」을 세우고, 그 층엔 조건이 없다(실 selftest가 최종 배선을 되읽는다).
_REACH_CASES = [
    # (이름, 데이터, 다른 available 작업 수 — 활성의 순위 슬라이스 소속을 가른다)
    ("데이터 없음", None, 0),
    ("데이터 있음·슬라이스 안", "compatible", 0),
    ("데이터 있음·슬라이스 밖", "compatible", 6),
    ("데이터 있음·비적격(needs)", "incompatible", 0),
]


@pytest.mark.parametrize(
    ("label", "data_kind", "others"),
    [(c[0], c[1], c[2]) for c in _REACH_CASES],
    ids=[c[0] for c in _REACH_CASES],
)
def test_relink_stays_reachable_for_the_active_job_in_every_state(
    tmp_path, label, data_kind, others
):
    """불변식: 활성 작업 + 템플릿 부재 → 세션 축이 재연결 도달의 근거를 싣는다.

    데이터 유/무 × 호환성(적격·비적격) × 순위 슬라이스(안·밖) 어느 조합에서도 참이어야
    한다. 후보 구획(`candidates.top`)은 이 단언의 대상이 **아니다** — 그 구획은 조건에
    걸리는 투영이고, 도달 보장을 거기 얹은 것이 세 라운드 결함의 뿌리였다.
    """
    ctrl, _ = _controller(tmp_path)
    for i in range(others):                       # 최근 실행 계층 — 미사용 활성을 밀어낸다
        _extra_job(ctrl, f"작업{i}", last_run_at=f"2026-07-2{i}T09:00:00")
    if data_kind == "compatible":
        ctrl.load_data_path(_data_csv(tmp_path))
    elif data_kind == "incompatible":
        other = tmp_path / "other.csv"
        other.write_text("엉뚱한열" + chr(10) + "값" + chr(10), encoding="utf-8")
        ctrl.load_data_path(str(other))
    ctrl.dispatch("select_job", {"name": "공고서"})
    Path(ctrl.snapshot()["template_path"]).unlink()            # 템플릿 소실 재현

    snap = ctrl.snapshot()
    assert snap["has_job"] is True and snap["job_name"] == "공고서"
    assert snap["template_missing"] is True, (
        f"[{label}] 세션 축이 템플릿 부재를 말하지 않습니다 — 재연결 도달 보장 소멸."
    )
    assert snap["conn_label"] == "템플릿 없음", (
        f"[{label}] 연결 상태 문안이 비었습니다(텍스트가 정본, 판정 C)."
    )


def test_relink_reach_is_quiet_when_nothing_is_wrong(tmp_path):
    """불변식의 음성 대조 — 정상·미선택에서 그 축은 조용하다(거짓 경보 금지).

    부재만 말하는 축이라야 경보가 값을 갖는다. 작업 미선택 상태에서 빈 경로를 「템플릿
    없음」으로 부르면 화면이 **없는 작업의 부재**를 경보한다(#342 3R 에서 함께 고친
    술어 분기: 구 vm-None 가지는 빈 경로를 정상으로 봐 카드 판정과도 어긋났다).
    """
    ctrl, _ = _controller(tmp_path)
    assert ctrl.initial()["template_missing"] is False         # 미선택 = 물을 대상 없음
    assert ctrl.initial()["conn_label"] == ""
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["template_missing"] is False                   # 정상은 조용히(F30)
    assert snap["conn_label"] == ""


def test_blocked_axis_name_follows_the_gate_order_not_template_state(tmp_path):
    """막는 축의 이름은 **게이트 서열**이 낸다(#342 리뷰 P2 — 데이터 존 라벨 보존).

    `workbench_entry_gate` 의 서열은 데이터 → 행 → 템플릿이다. 템플릿이 부재여도 **선택
    0건이면 행 선택이 먼저**이므로 축 이름도 `no_rows` 여야 한다 — 표면은 이 이름 하나를
    읽어 「현재 데이터」를 지목한다. 종전엔 표면이 `template_missing` 을 직접 보고 무조건
    문서 선택기를 가리켜, 게이트가 낸 서열을 덮었다(같은 상태를 두 곳이 판정).
    """
    ctrl, _ = _controller(tmp_path)
    txt = tmp_path / "기안.txt"
    txt.write_text("{{공고명}}", encoding="utf-8")
    ctrl.registry.save(Job(name="기안작업", template_path=str(txt)))
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.dispatch("select_job", {"name": "기안작업"})
    txt.unlink()                                        # 템플릿 부재 + 선택 0건

    blocked = ctrl.snapshot()
    assert blocked["template_missing"] is True          # 부재는 부재대로 참이고
    assert blocked["gate"]["reason"] == "no_rows", (     # 그래도 먼저 할 일은 행 선택이다
        "템플릿 부재가 행 선택 안내의 축 이름을 덮었습니다(게이트 서열 무시)."
    )
    assert "처리할 항목을 선택하세요" in blocked["gate"]["text"]

    ctrl.dispatch("set_all", {})                        # 행을 고르면 그제야 템플릿 축
    after = ctrl.snapshot()
    assert after["gate"]["reason"] == "template_missing", after["gate"]
    assert "템플릿 파일을 찾을 수 없습니다" in after["gate"]["text"]


def test_prework_gate_names_the_axis_it_blocks_on(tmp_path):
    """작업 미선택 게이트도 축 이름을 낸다 — 표면 지목의 단일 출처(#342 리뷰 P2)."""
    ctrl, _ = _controller(tmp_path)
    assert ctrl.initial()["gate"]["reason"] == "no_data"
    ctrl.load_data_path(_data_csv(tmp_path))
    assert ctrl.snapshot()["gate"]["reason"] == "no_rows"
    ctrl.dispatch("set_all", {})
    assert ctrl.snapshot()["gate"]["reason"] == "no_job"


def test_active_job_out_of_slice_is_not_smuggled_into_the_candidate_list(tmp_path):
    """후보 구획은 **순위 그대로**다 — 도달 보장이 세션 축으로 갔으므로 덧붙이지 않는다.

    1R·2R 의 조건부 덧붙임(순위 밖 활성·ranked 밖 활성을 `top` 말미에 끼우기)은 근본
    조치로 잉여가 됐다. 되깎지 않으면 같은 사실을 두 곳이 보장하고, 「외 N건」 수치 보정
    같은 화해 코드가 그 위에 쌓인다(#338 잣대: 화해 코드를 남기지 않는다).
    """
    ctrl, _ = _controller(tmp_path)
    for i in range(6):
        _extra_job(ctrl, f"작업{i}", last_run_at=f"2026-07-2{i}T09:00:00")
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.dispatch("select_job", {"name": "공고서"})            # 활성 = 순위 7위(미사용)
    cands = ctrl.snapshot()["candidates"]
    assert len(cands["top"]) == MAIN_TOP_N                     # 슬라이스는 슬라이스다
    assert "공고서" not in [c["name"] for c in cands["top"]]
    assert cands["more"] == 2                                  # 잘린 수 = 보정 없는 산술


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
    ctrl = JobController(reg, lambda s, snap: None, **_deps(tmp_path))
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, str(csv))
    # text·present 인 공고명(→bidNtceNm)만 나르는 열. const·blank·부재 source 는 배제.
    assert ctrl._filename_source_columns() == ["bidNtceNm"]


# ---------------------------------------------------------------- 게이트·생성(링1 계약)
def test_blank_set_gate_blocks_generate_until_approved(tmp_path):
    """U2 §2.13 — 빈 값이 있으면 blank_set 검토 요구가 서고, 승인해야 생성이 열린다.

    구 필드축 ack(배지 클릭=확인)의 승계: 표식 삽입 동의는 확인 면의 승인 1번이 겸한다.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))

    snap = ctrl.snapshot()
    assert snap["gate"]["enabled"] is False and "빈 값" in snap["gate"]["text"]
    assert snap["gate"]["reason"] == "review_required"      # 어휘는 「승인」 하나(§2.10 승계)
    assert "추정가격" in snap["gate"]["text"]                # 어느 필드인지 지목한다

    # 생성 시도도 방어적으로 차단(worker/API 우회 방지).
    res = ctrl.generate()
    assert res["ok"] is False and "빈 값" in res["error"]

    # 확인 면 승인 → 게이트 열림.
    _approve_run(ctrl)
    assert ctrl.snapshot()["gate"]["enabled"] is True


def test_generate_writes_documents_and_marks_missing(tmp_path):
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    out = tmp_path / "out"
    ctrl.set_output_folder(str(out))
    _approve_run(ctrl)

    res = ctrl.generate()
    assert res["ok"] is True
    assert res["succeeded"] == 2 and res["failed"] == 0
    assert "빈 값 표시 필드" in res["summary"]  # 낙관 서사 해소
    made = sorted(p.name for p in out.glob("*.hwpx"))
    assert made == ["doc-001.hwpx", "doc-002.hwpx"]
    # 진행 델타가 최소 1회 푸시됐다(진행바 갱신 계약).
    assert any(isinstance(snap, dict) and "progress" in snap for _s, snap in pushes)


def test_generate_cancel_keeps_completed_and_restates_unstarted(tmp_path, monkeypatch):
    import hwpxfiller.application.generation as appgen

    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    _approve_run(ctrl)

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

    monkeypatch.setattr(appgen, "generate_batch", fake_batch)
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
        # 자물쇠 앞 거절도 **그 실행의 응답**이라 상관 토큰을 되돌린다(R4-03) — 표면이
        # "내가 기다리던 그 호출인가"를 물을 수 있어야 늦은 응답이 새 실행을 덮지 않는다.
        "run_token": "",
    }


def test_generation_stamps_last_run_at(tmp_path):
    """완주 = 역사(#129) — 생성이 작업에 실행 시각을 영속해야 홈 이력·KPI 가 산다."""
    ctrl, _ = _controller(tmp_path)
    assert ctrl.registry.load("공고서").last_run_at == ""      # 선조건: 미실행
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    _approve_run(ctrl)

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
    _approve_run(ctrl)
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
    import hwpxfiller.application.generation as appgen

    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _second_job(ctrl, tmp_path)                       # 전환 시도 대상(공고서2) 등록
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    _approve_run(ctrl)

    real_batch = appgen.generate_batch

    def _switch_midflight(*a, **k):
        result = real_batch(*a, **k)
        with pytest.raises(ValueError, match="생성이 진행 중"):   # 전환은 loud 거부
            ctrl.dispatch("select_job", {"name": "공고서2"})
        return result

    monkeypatch.setattr(appgen, "generate_batch", _switch_midflight)
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
    _approve_run(ctrl)

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
    _approve_run(ctrl)

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
    import hwpxfiller.application.generation as appgen

    class _FakeResult:
        ok = False
        output_path = "x.hwpx"
        error = "boom"

    class _FakeBatch:
        succeeded, failed, total = 1, 1, 2
        results = [_FakeResult()]

    monkeypatch.setattr(appgen, "generate_batch", lambda *a, **k: _FakeBatch())
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    _approve_run(ctrl)

    assert ctrl.generate()["failed"] == 1
    assert ctrl.registry.load("공고서").last_run_at == ""       # 미완주 = 역사 없음


def test_overwrite_confirm_flow(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    _approve_run(ctrl)
    assert ctrl.generate()["ok"] is True  # 최초 생성

    # 같은 폴더 재생성 → 조용한 덮어쓰기 금지: 수치 합성 재진술 요구(총량·파괴분·신규분).
    res = ctrl.generate()
    assert res["ok"] is False and res.get("needs_overwrite") is True
    assert res["total"] == 2 and res["overwrite_count"] == 2 and res["new_count"] == 0
    assert len(res["conflict_names"]) == 2 and res["conflict_more"] == 0
    # 확인 후 재호출 → 생성.
    assert ctrl.generate(confirm_overwrite=True)["ok"] is True


# ---------------------------------------------- 실행 상관 토큰(R4-03)
def test_generate_echoes_run_token_on_every_direct_branch(tmp_path):
    """토큰은 **모든** direct 갈래로 되돌아온다 — 갈래 하나가 빠지면 그 갈래에서만
    표면이 응답의 주인을 잃고, 그 창은 조용하다(늦은 응답이 새 실행을 덮는다)."""
    ctrl, _ = _controller(tmp_path)

    # ① 작업 미선택 거절
    assert ctrl.generate(run_token="t-1")["run_token"] == "t-1"

    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    _approve_run(ctrl)

    # ② 성공
    ok = ctrl.generate(run_token="t-2")
    assert ok["ok"] is True and ok["run_token"] == "t-2"

    # ③ 덮어쓰기 필요 — 이 갈래는 push 가 없어 direct 반환이 유일한 통로다.
    needs = ctrl.generate(run_token="t-3")
    assert needs.get("needs_overwrite") is True and needs["run_token"] == "t-3"

    # ④ 확인 재호출은 **같은 의도**라 같은 토큰을 다시 쓴다(새 op 가 아니다).
    committed = ctrl.generate(confirm_overwrite=True, run_token="t-3")
    assert committed["ok"] is True and committed["run_token"] == "t-3"


def test_a_rejected_second_call_does_not_relabel_the_running_one(tmp_path):
    """자물쇠에 **진** 호출이 이긴 런의 이름표를 갈아치우면 안 된다.

    종전에는 토큰을 자물쇠 **앞** 공유 필드에 실었다. 그래서 첫 런이 도는 중에 둘째가
    들어오면 둘째의 거절 응답이 나가기 **전에** 공유 필드가 둘째 것으로 바뀌고, 실제로
    도는 런의 진행 델타와 최종 응답이 남의 이름표를 달았다 — 표면은 그것을 남의 것으로
    폐기하므로 **문서는 만들어졌는데 사용자는 「이미 생성 중」만 본다**.

    자물쇠를 실제로 쥐고(첫 런을 흉내) 둘째를 부르는 것으로 그 창을 재현한다.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    _approve_run(ctrl)

    # 첫 런이 자물쇠를 쥔 상태 = 그 런이 세운 이름표(run 핸들)가 서 있는 상태.
    from hwpxfiller.application.generation import GenerationRun

    assert ctrl._generation_lock.acquire(blocking=False)
    ctrl._run = GenerationRun(token="run-first")
    try:
        rejected = ctrl.generate(run_token="run-second")
    finally:
        ctrl._generation_lock.release()

    # 거절 응답은 **자기** 토큰을 단다 — 그래야 둘째를 누른 표면이 자기 거절을 알아본다.
    assert rejected["ok"] is False and "이미" in rejected["error"]
    assert rejected["run_token"] == "run-second"
    # 그리고 도는 런의 이름표는 **그대로다**. 이 한 줄이 이 테스트의 이유다.
    assert ctrl._run is not None and ctrl._run.token == "run-first", (
        "진 호출이 이긴 런의 이름표를 갈아치웠습니다 — 그 런의 결과가 남의 것으로 폐기됩니다."
    )


def test_the_run_label_is_cleared_when_the_lock_is_released(tmp_path):
    """런이 끝나면 이름표를 비운다 — 남은 이름표는 어떤 런도 안 겨눈다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    _approve_run(ctrl)

    assert ctrl.generate(run_token="run-9")["ok"] is True
    assert ctrl._run is None


def test_progress_delta_carries_the_run_token(tmp_path):
    """진행 델타는 direct 반환과 다른 채널이라 payload 안에 주인이 있어야 한다."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    _approve_run(ctrl)
    ctrl.generate(run_token="run-42")

    deltas = [snap["progress"] for _s, snap in pushes
              if isinstance(snap, dict) and "progress" in snap]
    assert deltas, "진행 델타가 하나도 없다"
    assert all(d["run_token"] == "run-42" for d in deltas)
    assert all({"done", "total", "run_token"} == set(d) for d in deltas)


def test_run_token_is_opaque_to_python(tmp_path):
    """Python 은 토큰으로 아무 판정도 하지 않는다 — 생략·빈 문자열·이상한 값이 전부
    같은 판정을 내고 그대로 되돌아온다(해석하는 순간 실행 의미가 전송층으로 샌다)."""
    weird = "  \n<script> t/1 é  "
    for index, (token, expected) in enumerate(((None, ""), ("", ""), (weird, weird))):
        home = tmp_path / f"h{index}"
        home.mkdir()
        ctrl, _ = _controller(home)
        ctrl.dispatch("select_job", {"name": "공고서"})
        _mount_all(ctrl, _data_csv(home))
        ctrl.set_output_folder(str(home / "out"))
        _approve_run(ctrl)
        res = ctrl.generate() if token is None else ctrl.generate(run_token=token)
        assert res["ok"] is True
        assert res["run_token"] == expected


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


def test_blank_fields_exclude_declared_blanks_and_carry_no_values(tmp_path):
    """본문 존 재료(U2 §2.13) — 빈 값 필드 **이름**만 싣는다: 값 집계(표본·행수 재진술)는
    표와 함께 죽었고, 의도적 빈칸(blank 선언)은 빈 값이 아니다(매핑이 키를 제외한다)."""
    ctrl = JobController(_mirror_job(tmp_path), lambda s, snap: None, **_deps(tmp_path))
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    snap = ctrl.snapshot()
    assert snap["blank_fields"] == ["추정가격"]   # rec0 빈값 — 비고(blank 선언)는 안 든다
    assert "mirror" not in snap
    ctrl.dispatch("set_none", {})
    snap = ctrl.snapshot()
    assert snap["blank_fields"] == [] and snap["drift"] == []


def test_mirror_drift_split_into_blocking_list(tmp_path):
    """drift(구조 불일치) 필드는 차단 배너 목록으로 분리된다(결정 36) — 빈 값 축과 섞지 않는다."""
    template = tmp_path / "t.hwpx"
    _write_template(template, ["공고명", "유령"])  # 유령 = 템플릿 전용(매핑 미커버) → drift
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(
        name="공고서", template_path=str(template),
        mapping=MappingProfile(mappings=[FieldMapping(template_field="공고명", source="bidNtceNm")]),
        filename_pattern="doc-{{seq:001}}",
    ))
    ctrl = JobController(reg, lambda s, snap: None, **_deps(tmp_path))
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    snap = ctrl.snapshot()
    assert snap["drift"] == ["유령"]
    assert snap["blank_fields"] == []             # drift 필드는 빈 값 축이 아니다


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
    ctrl = JobController(reg, lambda s, snap: None, **_deps(tmp_path))
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    snap = ctrl.snapshot()
    assert snap["name_tokens"] == ["미해소"]
    assert snap["gate"]["level"] == "danger" and snap["gate"]["enabled"] is False
    # 빈 값 축은 건강하다 — 그래서 배너가 없으면 본문 존이 건강한 한 줄만 그린다(신호 소실).
    assert snap["blank_fields"] == []
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
    ctrl = JobController(reg, lambda s, snap: None, **_deps(tmp_path))
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
    _approve_run(ctrl)
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
    ctrl = JobController(reg, lambda s, snap: None, **_deps(tmp_path))
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


def test_refresh_reloads_rules_edited_in_the_editor_and_keeps_the_session(tmp_path):
    """편집기에서 저장한 규칙이 **열린 실행 세션에 도달한다**(4R P1).

    편집기가 자기 화면으로 나간 뒤(재작성 F7) 저장은 이 화면 밖에서 일어나고 `self.vm` 은
    선택 시점의 인메모리 사본이다 — 다시 읽지 않으면 방금 저장한 사람이 **옛 규칙으로
    미리보고 옛 규칙으로 생성한다**(영속·실행 경로가 화면 사이에서 갈리는 자리).
    세션(데이터·선택·저장 폴더)은 그대로 살아야 한다: 규칙만 갈아 끼운다.
    """
    ctrl, _ = _controller(tmp_path)
    reg = ctrl.registry
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    before = ctrl.snapshot()
    out_dir, records = ctrl.out_dir, before["record_count"]
    assert ctrl.vm.job.filename_pattern != "새규칙-{{공고명}}"

    job = reg.load("공고서")                      # 다른 화면(편집기)이 규칙을 바꿔 저장
    job.filename_pattern = "새규칙-{{공고명}}"
    reg.save(job, allow_overwrite=True)

    assert ctrl.dispatch("refresh", {}) is None    # 삭제가 아니므로 고지는 없다
    assert ctrl.vm.job.filename_pattern == "새규칙-{{공고명}}"   # 규칙은 새것
    snap = ctrl.snapshot()
    assert snap["has_job"] is True and snap["record_count"] == records   # 세션은 그대로
    assert ctrl.out_dir == out_dir


def test_reload_is_a_no_op_without_a_job_or_with_a_corrupt_file(tmp_path):
    """재적재는 **읽을 수 있을 때만** 한다 — 작업 미선택·손상 파일에서 조용히 세션을 깨지 않는다.

    손상은 다음 스냅샷의 건강 표면이 말한다(여기서 예외를 올리면 화면 전환마다 발화하는
    경로가 그 작업 하나 때문에 통째로 죽는다).
    """
    ctrl, _ = _controller(tmp_path)
    assert ctrl._reload_active_job() is False          # 작업 미선택 = 손댈 것이 없다

    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.registry.path_for("공고서").write_text("{ 깨진 JSON", encoding="utf-8")
    assert ctrl._reload_active_job() is False           # 못 읽으면 그대로 둔다
    assert ctrl.snapshot()["has_job"] is True           # 세션은 살아 있다


def test_snapshot_rules_key_changes_when_the_editor_changes_the_rules(tmp_path):
    """결과의 세션 지문에 **규칙**이 든다(6R P2).

    결과가 「지금 결과」로 남으려면 그것을 만든 규칙이 아직 그 규칙이어야 한다 — 편집기에서
    고치고 돌아오면 재적재가 규칙을 갈아 끼우는데, 지문에 규칙이 없으면 **다른 규칙으로 만든
    결과가 후속 행동(실패분 선택·파일 이름 수리)까지 열어 둔 채** 「지금」으로 남는다.
    """
    ctrl, _ = _controller(tmp_path)
    reg = ctrl.registry
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    before = ctrl.snapshot()["rules_key"]
    assert before

    job = reg.load("공고서")
    job.filename_pattern = "새규칙-{{공고명}}"
    reg.save(job, allow_overwrite=True)
    ctrl.dispatch("refresh", {})
    assert ctrl.snapshot()["rules_key"] != before      # 규칙이 갈리면 지문도 갈린다

    # 선택·데이터만 그대로면 지문도 그대로다(과잉 강등 금지 — 결과는 살아 있어야 한다).
    assert ctrl.snapshot()["rules_key"] == ctrl.snapshot()["rules_key"]


def test_reload_also_follows_revision_metadata_that_the_content_fingerprint_hides(tmp_path):
    """내용 지문이 같아도 **세대가 앞섰으면** 다시 읽는다(7R P2).

    `content_fingerprint` 는 판본 3필드를 일부러 뺀다(편집 세션에 거짓 파괴 확인을 띄우지
    않으려고) — 그래서 그것만으로는 "지금 것인가"를 답할 수 없다. 규칙이 A→B→A 로 돌아온
    저장은 내용이 같지만 세대는 앞서 있고, 그 상태로 실행하면 결과가 **디스크에 없는 세대**를
    자기 근거로 댄다(§13-7). 단 실행 입력이 그대로이므로 완주 담보는 걷지 않는다(과잉 리셋 금지).
    """
    ctrl, _ = _controller(tmp_path)
    reg = ctrl.registry
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl._last_generated = {0}                          # 완주 담보가 서 있는 상태

    job = reg.load("공고서")
    original = job.filename_pattern
    job.filename_pattern = "잠깐-{{공고명}}"             # A → B
    reg.save(job, allow_overwrite=True)
    job = reg.load("공고서")
    job.filename_pattern = original                      # B → A(내용은 처음과 같다)
    reg.save(job, allow_overwrite=True)
    disk = reg.load("공고서")
    assert disk.binding_revision == 3                    # 세대는 앞서 있다

    assert ctrl._reload_active_job() is True
    assert ctrl.vm.job.binding_revision == 3             # 실행이 대는 판본이 디스크와 같다
    assert ctrl._last_generated == {0}                   # 실행 입력은 그대로 → 담보 유지


def test_refresh_does_not_disturb_the_session_when_rules_are_unchanged(tmp_path):
    """지문이 같으면 아무것도 안 한다 — 이 경로는 화면 전환마다 발화한다(REFRESH_ON_NAV).

    무조건 재구성하면 평시 왕복이 실행 증거·미리보기 자리를 매번 되돌려, 아무 일도 없었는데
    게이트가 다시 닫히는 것처럼 보인다(과잉 리셋).
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    vm_before = ctrl.vm
    assert ctrl.dispatch("refresh", {}) is None
    assert ctrl.vm is vm_before                    # 같은 정체를 그대로 들고 있다


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
from hwpxfiller.domain.dataset_reference import DatasetReference
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.external.template_inspection import template_compile_status


def _pool_controller(tmp_path, *, pool_source_factory=source_from_pool_item):
    pool = DatasetPoolRegistry(tmp_path / "pool")
    pushes: list = []
    ctrl = JobController(
        _registry(tmp_path), lambda s, snap: pushes.append((s, snap)),
        pool_registry=pool,
        generation_lock=threading.Lock(),
        file_source_factory=source_for_path,
        pool_source_factory=pool_source_factory,
    )
    return ctrl, pool


def _pool_add(pool, name, opts, kind="excel"):
    """풀 항목 추가 → 슬롯 키 반환(§5.3 — 겨눔의 정체)."""
    return pool.add(DatasetReference(name=name, kind=kind, opts=opts))


def test_load_pool_targets_excel_reference(tmp_path):
    """등록 데이터 겨눔 성공 — 실행 시점 재읽기(싱크) + 소스 병기 라벨 + 선택 초기화."""
    # 풀 겨눔이 **주입된** factory 를 타는지 기록으로 봉인(P2-16 — 파일 마운트와 짝).
    factory_calls: list = []

    def recording_factory(item, *, secret_store=None, fetcher=None):
        factory_calls.append(item.kind)
        return source_from_pool_item(item, secret_store=secret_store, fetcher=fetcher)

    ctrl, pool = _pool_controller(tmp_path, pool_source_factory=recording_factory)
    key = _pool_add(pool, "7월공고", {"path": _data_csv(tmp_path)})
    ctrl.dispatch("select_job", {"name": "공고서"})
    res = ctrl.dispatch("load_pool", {"key": key})
    assert res["ok"] is True and res["label"] == "등록 데이터: 7월공고"
    assert factory_calls == ["excel"]  # 주입 factory 경유 1회
    snap = ctrl.snapshot()
    assert snap["data_source_label"] == "등록 데이터: 7월공고"
    assert snap["record_count"] == 2


def test_new_work_handoff_carries_the_reference_or_refuses_out_loud(tmp_path):
    """U2 §2.4·#349 리뷰 P1 — 「이 데이터로 새 작업」의 가부·참조는 **한 판정**이 낸다.

    세 마운트를 대조한다:

    - 파일 마운트 → 경로·시트 그대로 승계(종전 거동 무회귀).
    - 등록 데이터(엑셀 참조) → ``header_row`` 까지 **참조 전체** 승계. `_do_load_pool` 이
      `data_path` 에 남기는 것은 로케이트용 경로 하나뿐이라, 그것만 보면 사용자가 고른 것과
      다른 헤더로 마법사가 선다.
    - 등록 데이터(조립 파이프라인) → 파일로 다시 열 수 없으므로 **시끄럽게 거절**. 이 경우
      `data_path` 는 의도적으로 비어 있는데(kind != excel), 버튼은 `has_data` 로 서 있었다 —
      화면은 「누를 수 있다」, 백엔드는 「데이터가 없다」로 갈리던 자리다. 스냅샷이 가부와
      사유를 함께 실어 표면이 유추하지 않는다.
    """
    ctrl, pool = _pool_controller(tmp_path)
    ctrl.load_data_path(_data_csv(tmp_path))
    ref, blocked = ctrl.new_work_handoff()
    assert blocked == "" and ref["path"] == _data_csv(tmp_path)
    assert ref["sheet"] == "" and ref["header_row"] == 0
    assert ctrl.snapshot()["new_work"] == {"can": True, "reason": ""}

    xlsx = tmp_path / "머리2행.xlsx"
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "발주"
    ws.append(["2026년 발주 목록", "작성", "비고"])
    ws.append(["bidNtceNm", "presmptPrce", "부서"])
    ws.append(["전산장비", "1000", "총무과"])
    wb.save(xlsx)
    key = _pool_add(pool, "머리2행", {"path": str(xlsx), "sheet": "발주", "header_row": 2})
    assert ctrl.dispatch("load_pool", {"key": key})["ok"] is True
    ref, blocked = ctrl.new_work_handoff()
    assert blocked == ""
    assert ref == {"path": str(xlsx), "sheet": "발주", "header_row": 2}

    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_text("id,bidNtceNm\n1,전산장비\n", encoding="utf-8")
    b.write_text("id,presmptPrce\n1,1000\n", encoding="utf-8")
    pkey = _pool_add(pool, "6월 조립", {
        "sources": [
            {"kind": "excel", "opts": {"path": str(a)}},
            {"kind": "excel", "opts": {"path": str(b)}},
        ],
        "steps": [{"op": "merge", "source": 1, "on": "id", "how": "inner"}],
    }, kind="pipeline")
    assert ctrl.dispatch("load_pool", {"key": pkey})["ok"] is True
    snap = ctrl.snapshot()
    assert snap["has_data"] is True and snap["data_target"]["path"] == ""
    ref, blocked = ctrl.new_work_handoff()
    assert ref == {} and "파일 참조가 아니어서" in blocked
    assert snap["new_work"] == {"can": False, "reason": blocked}


def test_new_work_handoff_is_captured_at_mount_not_reread_from_the_slot(tmp_path):
    """#349 리뷰 2R — 「이 데이터」는 **화면이 보여 주는 그 데이터**여야 한다.

    풀 슬롯은 가변이다: 「다시 연결」은 참조만 갈아 끼우고 수명을 보존하는 정상 수명
    사건이고(#347), 그것이 일어나도 이 화면은 재마운트 전까지 **옛 참조로 읽은 레코드**를
    그대로 보여 준다. 승계가 그때 슬롯을 다시 읽으면 「표시는 A · 시작은 B」가 된다.

    단언은 경로 문자열 대조가 아니라 **불변식**으로 건다: 승계 참조로 소스를 열면 그 열이
    지금 마운트된 레코드의 열과 같아야 한다. 그래야 성분이 하나 더 늘어도(옵션 추가) 이
    테스트가 계속 진짜 질문을 묻는다.
    """
    from hwpxfiller.data.factory import source_for_path

    ctrl, pool = _pool_controller(tmp_path)
    a, b = tmp_path / "a.csv", tmp_path / "b.csv"
    a.write_text("bidNtceNm,presmptPrce\n전산장비,1000\n", encoding="utf-8")
    b.write_text("담당자,품목\n김주무관,의자\n", encoding="utf-8")
    key = _pool_add(pool, "7월공고", {"path": str(a)})
    assert ctrl.dispatch("load_pool", {"key": key})["ok"] is True
    mounted = list(ctrl.records[0].keys())

    # 같은 슬롯을 B 로 다시 연결 — **재마운트는 하지 않는다**(화면은 여전히 A 를 보여 준다).
    pool.mutate(key, lambda it: it.opts.update({"path": str(b)}))
    assert list(ctrl.records[0].keys()) == mounted        # 표시는 그대로 A

    ref, blocked = ctrl.new_work_handoff()
    assert blocked == ""
    ref_fields = source_for_path(ref["path"], sheet=ref["sheet"] or None).fields()
    assert ref_fields == mounted, (
        "승계가 슬롯을 다시 읽었습니다 — 표시는 A 인데 새 작업은 B 로 시작합니다."
    )
    # 재마운트하면 그때는 B 로 간다(재연결을 막는 조치가 아니다 — 정상 수명 사건).
    assert ctrl.dispatch("load_pool", {"key": key})["ok"] is True
    ref2, _ = ctrl.new_work_handoff()
    assert source_for_path(ref2["path"]).fields() == list(ctrl.records[0].keys())
    assert ref2["path"] != ref["path"]


def test_load_pool_without_job_mounts_session_data(tmp_path):
    """데이터-우선(§18.2): 작업 미선택에도 풀 겨눔이 세션에 마운트된다 — 구 「작업 먼저」
    전제의 개정. 마운트 직후 선택 0건 + 후보(§18.4) + prework 게이트가 다음 할 일을 말한다."""
    ctrl, pool = _pool_controller(tmp_path)
    key = _pool_add(pool, "7월공고", {"path": _data_csv(tmp_path)})
    res = ctrl.dispatch("load_pool", {"key": key})
    assert res["ok"] is True
    snap = ctrl.snapshot()
    assert snap["has_job"] is False and snap["has_data"] is True
    assert snap["record_count"] == 2 and snap["selected_count"] == 0
    # 후보 = 현재 데이터 fields 로 판정(§18.4) — '공고서'는 필수 소스가 전부 있어 available.
    assert [c["name"] for c in snap["candidates"]["top"]] == ["공고서"]
    assert snap["gate"]["enabled"] is False and "항목을 선택" in snap["gate"]["text"]
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})
    assert "문서 작업" in ctrl.snapshot()["gate"]["text"]  # 다음 할 일 = 작업 선택


# ------------------------- 작업↔데이터 결속의 사망(#53-A → #347, U2 §5.3 판정 D)
def test_select_job_does_not_mount_any_data(tmp_path):
    """작업 선택은 데이터를 세우지 않는다 — 구 기본 데이터셋 자동 조준(#53-A)은 폐기됐다.

    구 JSON 이 default_dataset_ref 를 들고 있고 동명 풀 항목이 실재해도, 선택은 결속을
    읽지 않는다(마이그레이션이 아니라 폐기 — 데이터↔작업 결속은 어느 방향으로도 다시
    들이지 않는다).
    """
    import json as _json

    ctrl, pool = _pool_controller(tmp_path)
    _pool_add(pool, "7월공고", {"path": _data_csv(tmp_path)})
    path = ctrl.registry.path_for("공고서")
    payload = _json.loads(path.read_text(encoding="utf-8"))
    payload["default_dataset_ref"] = "7월공고"          # 구버전이 남긴 결속 키
    path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["has_job"] is True
    assert snap["has_data"] is False                    # 자동 마운트 없음
    assert snap["data_source_label"] == ""
    assert snap["data_notice"] is None                  # 조준 재진술도 없다 — 판정 자체가 없다


def test_mounted_session_data_survives_job_selection(tmp_path):
    """세션 소유 마운트 데이터는 작업 선택에서 생존한다(§18.2) — §5.3 완화 ⑴의 근거."""
    ctrl, _pool = _pool_controller(tmp_path)
    other = tmp_path / "직접.csv"
    other.write_text("bidNtceNm,presmptPrce\n수동데이터,900\n", encoding="utf-8")
    ctrl.load_data_path(str(other))                      # 작업 미선택 상태의 수동 마운트
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["data_label"] == "직접.csv"              # 마운트 데이터 생존
    assert snap["record_count"] == 1 and snap["selected_count"] == 1
    assert snap["data_notice"] is None


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


def test_relink_first_link_of_unlinked_job_is_allowed(tmp_path):
    """미연결 작업의 첫 연결은 통과 — 아직 길을 고르지 않았다(§10.16 판정 C 1행).

    `require_hwpx` 의 「빈 경로 = 통과」와 같은 규율: 매체 게이트가 막는 것은 **길을 바꾸는
    것**이지 처음 고르는 것이 아니다. 확인 문안은 빈 기존 경로를 (비어 있음) 으로 재진술한다.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.registry.save(Job(name="저작중", template_path="",
                           mapping=MappingProfile(mappings=[])))
    new_tpl = tmp_path / "first.hwpx"
    _write_template(new_tpl, ["공고명"])
    res = ctrl.dispatch("relink_template", {"name": "저작중", "path": str(new_tpl)})
    assert res["ok"] is True and res["needs_confirm"] is True
    assert "(비어 있음)" in res["confirm_text"]
    res = ctrl.dispatch(
        "relink_template", {"name": "저작중", "path": str(new_tpl), "confirm": True})
    assert res["relinked"] is True
    assert ctrl.registry.load("저작중").template_path == str(new_tpl)


def test_relink_same_media_txt_recovery_works(tmp_path):
    """txt→txt 재연결은 합법 복구다 — hwpx 파서에 빠져 죽지 않는다(§10.16 판정 C 2행).

    종전엔 드리프트 프로브가 새 경로를 무조건 hwpx zip 으로 파싱해 같은 매체 복구가
    "읽을 수 없습니다"로 죽었다(잠복 결함 회귀 핀). 읽기 판정은 여는 계약과 같은 UTF-8 —
    비-UTF-8 파일은 확인으로도 템플릿이 될 수 없다(하드 차단 대칭). 토큰 0 파일도 같은
    차단이다(리뷰 2R P1): 에디터 픽은 `TXT_RAW_BLOCK` 으로 거절하는데 재연결만 통과하면
    작업대가 모든 레코드에 같은 원문을 복사한다 — 술어·문안 단일 출처(`screens`).
    """
    ctrl, _ = _controller(tmp_path)
    _txt_job(ctrl, tmp_path)
    moved = tmp_path / "이동된_기안.txt"
    moved.write_text("공고: {{공고명}}", encoding="utf-8")
    res = ctrl.dispatch("relink_template", {"name": "발주요청_기안", "path": str(moved)})
    assert res["ok"] is True and res["needs_confirm"] is True
    res = ctrl.dispatch(
        "relink_template", {"name": "발주요청_기안", "path": str(moved), "confirm": True})
    assert res["relinked"] is True
    assert ctrl.registry.load("발주요청_기안").template_path == str(moved)
    bad = tmp_path / "ansi_기안.txt"
    bad.write_bytes("공고: {{공고명}}".encode("cp949"))
    res = ctrl.dispatch(
        "relink_template", {"name": "발주요청_기안", "path": str(bad), "confirm": True})
    assert res["ok"] is False and "새 템플릿을 읽을 수 없습니다" in res["error"]
    assert ctrl.registry.load("발주요청_기안").template_path == str(moved)
    plain = tmp_path / "토큰없는_기안.txt"
    plain.write_text("토큰이 하나도 없는 본문", encoding="utf-8")
    res = ctrl.dispatch(
        "relink_template", {"name": "발주요청_기안", "path": str(plain), "confirm": True})
    assert res["ok"] is False and "{{토큰}}이 없는" in res["error"]
    assert ctrl.registry.load("발주요청_기안").template_path == str(moved)


def test_cross_media_relink_is_rejected_with_recreate_guidance(tmp_path):
    """매체 교차 재연결은 거절 — 문안이 삭제 후 재생성을 지목한다(§10.16 판정 C 3행).

    hwpx→txt 는 종전에도 프로브 오류로 못 갔지만 문안이 거짓말을 했고("읽을 수 없습니다"),
    txt→hwpx 는 조용히 **통과**하던 이력 위조 생존 경로다(`last_run_at` 의 뜻은 매체가
    정한다 — §19.4). 둘 다 confirm 으로 뚫리지 않고 durable 은 불변이다.
    """
    ctrl, _ = _controller(tmp_path)
    _txt_job(ctrl, tmp_path)
    res = ctrl.dispatch(
        "relink_template",
        {"name": "공고서", "path": str(tmp_path / "발주요청_기안.txt"), "confirm": True})
    assert res["ok"] is False
    assert "온나라 기안 TXT" in res["error"] and "삭제하고 새로 만드세요" in res["error"]
    assert ctrl.registry.load("공고서").template_path.endswith("t.hwpx")
    res = ctrl.dispatch(
        "relink_template",
        {"name": "발주요청_기안", "path": str(tmp_path / "t.hwpx"), "confirm": True})
    assert res["ok"] is False and "HWPX 템플릿을 연결할 수 없습니다" in res["error"]
    assert ctrl.registry.load("발주요청_기안").template_path.endswith(".txt")


def test_relink_unknown_media_is_rejected_but_recovers_broken_jobs(tmp_path):
    """새 매체 미상(.docx)은 fail-closed 거절, 미상 **구작업**의 연결은 복구로 통과(§10.16).

    거절이 없으면 relink 가 unsupported 작업을 제조하고, 통과가 없으면 손상 작업은 영구
    복구 불능이 된다 — 방향에 따라 답이 다른 이유를 게이트 3분기가 담는다. 복구는 **사용
    이력을 승계하지 않는다**(리뷰 5R P2): 미상 스탬프는 어느 매체의 술어로도 읽을 수 없어
    새 매체의 사건으로 재해석되면 위조다 — 고지 후 지우고, 즐겨찾기(방식 무관)는 남긴다.
    """
    ctrl, _ = _controller(tmp_path)
    docx = tmp_path / "낯선형식.docx"
    docx.write_text("x", encoding="utf-8")
    res = ctrl.dispatch(
        "relink_template", {"name": "공고서", "path": str(docx), "confirm": True})
    assert res["ok"] is False and "HWPX 또는 TXT 파일을 선택하세요" in res["error"]
    assert ctrl.registry.load("공고서").template_path.endswith("t.hwpx")
    ctrl.registry.save(Job(name="깨진작업", template_path=str(docx),
                           mapping=MappingProfile(mappings=[])))
    ctrl.registry.stamp_last_run("깨진작업", "2026-07-02T09:00:00")
    ctrl.registry.set_favorite("깨진작업", True, "2026-07-01T09:00:00")
    new_tpl = tmp_path / "복구.hwpx"
    _write_template(new_tpl, ["공고명"])
    res = ctrl.dispatch("relink_template", {"name": "깨진작업", "path": str(new_tpl)})
    assert res["ok"] is True and res["needs_confirm"] is True
    assert "최근 사용 기록은 함께 지워집니다" in res["confirm_text"]  # 조용한 삭제 금지
    res = ctrl.dispatch(
        "relink_template", {"name": "깨진작업", "path": str(new_tpl), "confirm": True})
    assert res["relinked"] is True
    saved = ctrl.registry.load("깨진작업")
    assert saved.last_run_at == ""                            # 미상 이력 미승계
    assert saved.favorited_at == "2026-07-01T09:00:00"        # 방식 무관 선호는 보존


def test_relink_media_gate_rechecks_inside_the_lock(tmp_path):
    """확인 왕복 사이에 매체가 정해졌으면 잠긴 커밋이 교차를 거절한다(리뷰 5R P2).

    게이트는 잠금 밖 사본을 보고, 확인 왕복은 사람 시간이다 — 미연결 작업에 HWPX·TXT 첫
    연결이 동시에 확인되면 둘 다 게이트를 지나고 두 번째 커밋이 교차 금지를 우회한다.
    stale 사본을 돌려주는 load 로 그 창을 재현해, 커밋 콜백의 재판정이 같은 문안으로
    거절하고 durable 이 불변임을 가드한다.
    """
    from hwpxfiller.webapp.screens import relink_job_template

    ctrl, _ = _controller(tmp_path)
    ctrl.registry.save(Job(name="경합작업", template_path="",
                           mapping=MappingProfile(mappings=[])))
    stale = ctrl.registry.load("경합작업")                     # 빈 경로 시점의 사본
    hwpx = tmp_path / "t.hwpx"
    ctrl.registry.mutate(                                      # 경쟁 relink 가 먼저 커밋
        "경합작업", lambda j: setattr(j, "template_path", str(hwpx)))

    class _StaleLoad:
        """게이트가 본 사본이 낡은 상황의 최소 재현 — load 만 stale, 커밋은 실물."""

        def __init__(self, real, stale_job):
            self._real, self._stale = real, stale_job

        def load(self, name):
            return self._stale

        def mutate(self, name, fn):
            return self._real.mutate(name, fn)

    txt = tmp_path / "경합.txt"
    txt.write_text("공고: {{공고명}}", encoding="utf-8")
    res = relink_job_template(
        _StaleLoad(ctrl.registry, stale), "경합작업", str(txt), confirm=True)
    assert res["ok"] is False and "삭제하고 새로 만드세요" in res["error"]
    assert ctrl.registry.load("경합작업").template_path == str(hwpx)  # durable 불변


# ------------------------------------------------ confirm-or-alarm 생성 계약
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
    _approve_run(ctrl)

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
        {"name": "bidNtceNm", "kind": "text", "visible": True},
        {"name": "presmptPrce", "kind": "text", "visible": True},
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
    ctrl = JobController(reg, lambda s, snap: None, **_deps(tmp_path))
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


# ------------------------------------------------- 사용자 열 선별(U2 §2.19, #341)
def test_hide_column_is_a_view_axis_only(tmp_path):
    """숨김은 **표시 축뿐**이다 — 플래그·표지 칩 소재가 서고 필터·검색은 그대로 참여한다.

    「숨겼으니 문서에 안 들어간다」로 읽히면 법적 효력 있는 문서가 조용히 틀린다. 그래서
    ①표시 여부는 링2 표면이 아니라 Python 판정(`table.columns[].visible`)이고 ②숨김이
    0개가 아니면 칩 소재(`hidden_columns`)가 상시 실리며 ③「전체 열 검색」은 숨긴 열도
    계속 매치한다(그 사실이 숨김 ≠ 제외의 증거).
    """
    ctrl, _ = _session(tmp_path)
    res = ctrl.dispatch("hide_column", {"column": "presmptPrce"})
    assert not (isinstance(res, dict) and res.get("stale"))
    t = ctrl.snapshot()["table"]
    assert [(c["name"], c["visible"]) for c in t["columns"]] == [
        ("bidNtceNm", True), ("presmptPrce", False),
    ]
    assert t["hidden_columns"] == ["presmptPrce"]
    assert all(len(r["cells"]) == 2 for r in t["rows"])   # 셀은 전 열 — ci 정렬 유지
    # 「전체 열 검색」은 숨긴 열도 계속 매치한다 — 매치 행이 남고 표지도 그대로 선다.
    ctrl.dispatch("filter_search", {"text": "2000000"})
    t = ctrl.snapshot()["table"]
    assert t["visible_count"] == 1
    assert t["hidden_columns"] == ["presmptPrce"]
    # 되돌리기는 칩 줄 관용구 하나 — 전체 해제.
    ctrl.dispatch("unhide_columns", {})
    t = ctrl.snapshot()["table"]
    assert t["hidden_columns"] == [] and all(c["visible"] for c in t["columns"])


def test_hidden_column_still_reaches_the_generated_document(tmp_path):
    """열을 숨긴 채 생성해도 **그 열의 값이 문서에 그대로 들어간다**(#341 최우선 계약)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    out = tmp_path / "out"
    ctrl.set_output_folder(str(out))
    _approve_run(ctrl)   # 빈 값 게이트는 승인이 진다(U2 §2.13 — 구 필드축 ack 의 승계)
    ctrl.dispatch("hide_column", {"column": "presmptPrce"})
    res = ctrl.generate()
    assert res["ok"] is True and res["succeeded"] == 2
    sections = [
        HwpxPackage.open(str(p)).entries["Contents/section0.xml"]
        for p in sorted(out.glob("*.hwpx"))
    ]
    assert any(b"2000000" in xml for xml in sections), (
        "숨긴 열의 값이 생성 문서에 채워지지 않았습니다 — 숨김이 생성 축을 침범했습니다."
    )


def test_hiding_is_inline_only_the_sheet_shows_every_column(tmp_path):
    """⤢ 시트(범위 초안)는 전 열이다(#271 유지) — 시트 패널에는 「숨기기」가 서지 않는다.

    적용 여부의 판정이 Python 한 곳이라(`_zone_hidden`·`_hide_allowed`) 인라인·시트·칩이
    각자 답을 갖지 않는다: 시트가 열리면 전 열 visible + 표지 0 + can_hide False, 닫으면
    세션 숨김이 그대로 되살아난다(시트 왕복이 선별을 지우지 않는다).
    """
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("hide_column", {"column": "presmptPrce"})
    ctrl.dispatch("range_draft_open", {})
    t = ctrl.snapshot()["table"]
    assert all(c["visible"] for c in t["columns"])         # 시트 = 전 열
    assert t["hidden_columns"] == []                       # 시트에는 표지도 서지 않는다
    assert ctrl.dispatch("filter_panel", {"column": "presmptPrce"})["can_hide"] is False
    with pytest.raises(ValueError, match="전체 열"):       # 오배선 호출도 시끄럽게
        ctrl.dispatch("hide_column", {"column": "bidNtceNm", "epoch": ctrl.zone_epoch})
    ctrl.dispatch("range_draft_cancel", {})
    t = ctrl.snapshot()["table"]
    assert t["hidden_columns"] == ["presmptPrce"]          # 인라인은 선별을 따른다
    assert ctrl.dispatch("filter_panel", {"column": "bidNtceNm"})["can_hide"] is True


def test_lead_identity_and_unknown_columns_cannot_be_hidden(tmp_path):
    """선두 식별 열(#271 스캔 앵커)은 데이터 열이 아니라 숨김 지형 밖 — 미지 이름은 loud."""
    ctrl, _ = _session(tmp_path)
    assert ctrl.filter is not None
    assert "문서" not in ctrl.filter.columns               # 선두 열은 열 지형에 없다(구조 배제)
    with pytest.raises(ValueError, match="숨길 수 없는 열"):
        ctrl.dispatch("hide_column", {"column": "문서"})
    with pytest.raises(ValueError, match="숨길 수 없는 열"):
        ctrl.dispatch("hide_column", {"column": "없는열"})


def test_column_hiding_dies_with_the_data_and_never_persists(tmp_path):
    """수명 = 세션 소유(필터와 같은 계층) — 데이터 교체에 소멸, durable 저장 0곳.

    작업 선택은 데이터 교체가 아니므로 선별이 생존한다(숨김은 데이터의 축이지 작업의
    축이 아니다). stale 세대의 늦은 숨김은 남의 세계의 편집이라 적용되지 않는다.
    """
    ctrl, _ = _session(tmp_path)
    old_epoch = ctrl.zone_epoch
    ctrl.dispatch("hide_column", {"column": "presmptPrce"})
    ctrl.dispatch("select_job", {"name": ""})              # 작업 해제 — 선별 생존
    assert ctrl.snapshot()["table"]["hidden_columns"] == ["presmptPrce"]
    other = tmp_path / "e.csv"
    other.write_text("presmptPrce,다른열\n1,값\n", encoding="utf-8")
    ctrl.load_data_path(str(other))                        # 데이터 교체 = 선별 소멸
    t = ctrl.snapshot()["table"]
    assert t["hidden_columns"] == [] and all(c["visible"] for c in t["columns"])
    # 죽은 세계의 늦은 숨김은 stale 재진술 — 새 데이터의 동명 열을 조용히 숨기지 않는다.
    res = ctrl.dispatch("hide_column", {"column": "presmptPrce", "epoch": old_epoch})
    assert res == {"stale": True, "epoch": ctrl.zone_epoch}
    assert ctrl.snapshot()["table"]["hidden_columns"] == []
    # durable 0곳 — 저장 작업(job JSON)에는 숨김이 어떤 형태로도 실리지 않는다.
    raw = "".join(
        p.read_text(encoding="utf-8") for p in (tmp_path / "jobs").rglob("*.json")
    )
    assert "hidden" not in raw and "숨김" not in raw


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


def test_guard_state_no_longer_enumerates_the_dead_ack_axis(tmp_path):
    """필드축 ack 폐기(U2 §2.13)의 상속 의무 — 가드가 존재하지 않는 손실을 말하지 않는다.

    구 ``ack_count`` 는 데이터 전환 손실 열거 성분이었는데(F1 §10.7.3), 확인이라는 상태
    자체가 사라졌으므로 성분이 남아 있으면 가드 문안이 없는 것을 잃는다고 말하게 된다.
    """
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("set_none", {})
    g = ctrl.dispatch("guard_state", {})
    assert "ack_count" not in g, "폐기된 ack 열거 성분이 가드에 남았습니다(§2.13)."
    assert g["armed"] is False


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
    import hwpxfiller.application.generation as appgen

    class _FakeResult:
        def __init__(self):
            self.ok = False
            self.output_path = "x.hwpx"
            self.error = "boom"  # describe_result_error 는 문자열 계약

    class _FakeBatch:
        succeeded, failed, total = 0, 1, 1
        results = [_FakeResult()]

    monkeypatch.setattr(appgen, "generate_batch", lambda *a, **k: _FakeBatch())
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
    """풀 소스 키 = 슬롯 키+참조 정체(리뷰 #6 · §5.3) — 다시 연결(다른 파일)은 다른 소스."""
    ctrl, pool = _pool_controller(tmp_path)
    key = pool.add(DatasetReference(
        name="7월공고", kind="excel", opts={"path": _data_csv(tmp_path)}))
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.dispatch("load_pool", {"key": key})
    ctrl.dispatch("filter_search", {"text": "전산"})
    # 같은 슬롯을 다른 파일로 다시 연결(참조 교체) 후 재겨눔 — 키만 같은 다른 소스.
    pool.mutate(key, lambda it: it.opts.update({"path": _data_csv3(tmp_path)}))
    ctrl.dispatch("load_pool", {"key": key})          # 죽음 → 슬롯(옛 참조 키)
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

    import hwpxfiller.external.job_store as job_store

    entered, release = threading.Event(), threading.Event()
    real_save = job_store.save_job
    fired = {"once": False}

    def slow_save(path, job):
        if not fired["once"] and job.last_run_at:    # 스탬프 저장만 붙잡는다
            fired["once"] = True
            entered.set()
            release.wait(3)
        return real_save(path, job)

    monkeypatch.setattr(job_store, "save_job", slow_save)
    return entered, release


def _home_vm(registry):
    from hwpxfiller.gui.home_state import HomeViewModel

    return HomeViewModel(
        registry, None, None,
        engine=make_hwpx_engine(), inspect_status=template_compile_status,
    )


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
    _approve_run(ctrl)

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


def test_prefer_work_without_data_always_stores_and_guides(tmp_path):
    """무데이터 「문서 만들기에서 사용」은 언제나 「보관 후 안내」 하나다(§5.3 판정 D).

    구 default_data 분기(작업의 기본 데이터 참조 자동 마운트 — F2 PR-B 판정 I)는 결속
    폐기와 함께 죽었다: 구 JSON 이 결속 키를 들고 있고 동명 풀 항목이 실재해도 데이터
    선택을 반드시 지난다. 마운트 시 _apply_preferred_work 가 보관분을 판정한다.
    """
    import json as _json

    ctrl, pool = _pool_controller(tmp_path)
    _pool_add(pool, "7월공고", {"path": _data_csv(tmp_path)})
    path = ctrl.registry.path_for("공고서")
    payload = _json.loads(path.read_text(encoding="utf-8"))
    payload["default_dataset_ref"] = "7월공고"          # 구버전이 남긴 결속 키
    path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    res = ctrl.dispatch("prefer_work", {"name": "공고서"})
    assert res == {"stored": True, "reason": "no_data", "name": "공고서"}
    assert ctrl.job_name == "" and ctrl.preferred_work == "공고서"  # 보관 — 자동 마운트 없음
    assert ctrl.snapshot()["has_data"] is False
    # 데이터를 명시로 고르면 보관분이 §18.3 1행으로 승격된다(요구는 세션당 1회 — 완화 ⑴).
    ctrl.load_data_path(_data_csv(tmp_path))
    assert ctrl.job_name == "공고서" and ctrl.preferred_work == ""


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
    ctrl = JobController(
        _incompatible_reg(tmp_path), lambda s, snap: pushes.append((s, snap)), **_deps(tmp_path)
    )
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
    ctrl = JobController(
        _incompatible_reg(tmp_path), lambda s, snap: pushes.append((s, snap)), **_deps(tmp_path)
    )
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
    import hwpxfiller.application.generation as appgen
    monkeypatch.setattr(appgen, "generate_batch", lambda *a, **k: batch)
    return ctrl.generate()


def _result_session(tmp_path):
    """빈 값 게이트를 태우지 않는 3행 세션 — 결과 3태 계약은 게이트 통과 이후가 무대다."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv3(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    return ctrl, pushes


def test_result_three_states_are_python_judged(tmp_path, monkeypatch):
    """3태는 성공/전체의 함수다(§10.10 판정 A) — 불변식 §13-10(일부 성공≠전체 성공).

    판정은 Application(:func:`~hwpxfiller.application.generation.run_status`)이 소유하고
    (P2-23) 문안(제목)은 종전대로 링2 가 조립한다 — old→new 책임 승계.
    """
    from hwpxfiller.application.generation import run_status
    from hwpxfiller.webapp.screen_job import _run_title

    assert run_status(2, 2) == "completed"
    assert run_status(1, 2) == "partiallyCompleted"
    assert run_status(0, 2) == "failed"
    # 취소는 네 번째 태가 아니라 부분의 변종 — 태는 그대로, 제목이 중단을 먼저 말한다.
    assert _run_title("partiallyCompleted", True, 1, 0).startswith("생성을 중단했습니다")
    assert "1개 성공" in _run_title("partiallyCompleted", False, 1, 1)
    # 첫 레코드 전에 멈춘 런: 성공 0·실패 0이다. 성공 수만 보면 failed 가 되어 "중단
    # 했습니다"라는 제목 옆에서 태가 없던 실패를 지어낸다(1R P2).
    assert run_status(0, 3, True) == "partiallyCompleted"


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
    import hwpxfiller.application.generation as appgen

    def _boom(*a, **k):
        raise ValueError("템플릿 구조가 확정 매핑과 달라 생성을 차단했습니다 — 필드 없음")

    monkeypatch.setattr(appgen, "generate_batch", _boom)
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
    import hwpxfiller.application.generation as appgen
    monkeypatch.setattr(appgen, "generate_batch", lambda *a, **k: calls.append(1))

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
    import hwpxfiller.application.generation as appgen

    def _boom(*a, **k):
        raise OSError("[WinError 5] 액세스가 거부되었습니다")

    monkeypatch.setattr(appgen, "generate_batch", _boom)
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

    import hwpxfiller.application.generation as appgen

    def _boom(*a, **k):
        raise OSError("[WinError 5] 액세스가 거부되었습니다")

    monkeypatch.setattr(appgen, "generate_batch", _boom)
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
    fresh = JobController(_registry(tmp_path), lambda s, snap: None, **_deps(tmp_path))
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
    """검토 기준선이 없는 작업 + 데이터 + 저장 폴더 — 게이트가 검토에서 막히는 상태.

    (구 「빈 값 ack 먼저 통과」 단계는 필드축 ack 폐기 — U2 §2.13 — 로 사라졌다: 빈 값은
    이제 같은 검토 요구의 성분이라 별도 선행 게이트가 없다.)
    """
    ctrl, pushes = _controller(tmp_path, reviewed=False)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.set_output_folder(str(tmp_path / "out"))
    return ctrl, pushes


def test_new_job_is_blocked_until_the_result_is_reviewed(tmp_path):
    """§13-3 — 새 문서 작업은 결과 확인 전 실행을 차단한다."""
    ctrl, _ = _unreviewed_session(tmp_path)
    gate = ctrl.snapshot()["gate"]
    assert gate["enabled"] is False and gate["level"] == "warn"
    assert "아직 한 번도 문서를 만들지 않은" in gate["text"]


def test_snapshot_carries_the_gate_reason_so_the_pill_can_say_approve(tmp_path):
    """스냅샷이 `gate.reason` 을 싣는다 — 표지 문안이 서열을 재유도하지 않게(리뷰 R1).

    어휘를 갈라 놓고(규칙축=「승인」, 필드축=「확인」) 상단 표지만 「확인 필요」로 두면 첫
    실행 화면에서 **같은 행동을 두 이름으로** 부른다. 표지가 옳게 말하려면 「무엇이 막고
    있는가」를 알아야 하는데 그 판정은 링1 이 이미 `reason` 으로 낸다 — 웹이 게이트 서열을
    다시 유도하지 않고 이 이름 하나만 읽는 것이 이 필드의 존재 이유다.
    """
    ctrl, _ = _unreviewed_session(tmp_path)
    assert ctrl.snapshot()["gate"]["reason"] == "review_required"
    req, _ = ctrl._review()
    ctrl.review.approve(req, ctrl._review_scope_key())
    gate = ctrl.snapshot()["gate"]
    assert gate["enabled"] is True and gate["reason"] == ""


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
    """§13-2 — 정상 반복 실행에서 미리보기는 선택이다. 완주가 그 자격을 만든다.

    빈 값 없는 데이터를 쓴다 — 빈 값이 있으면 blank_set(§2.13)이 반복 실행에도 서는
    것이 계약이라(침묵 금지), 「조용한 반복」의 전제가 데이터 축에서 갈린다.
    """
    ctrl, _ = _controller(tmp_path, reviewed=False)
    ctrl.dispatch("select_job", {"name": "공고서"})
    clean = tmp_path / "clean.csv"
    clean.write_text("bidNtceNm,presmptPrce\n전산장비,1000\n사무비품,2000000\n", encoding="utf-8")
    _mount_all(ctrl, str(clean))
    ctrl.set_output_folder(str(tmp_path / "out"))
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


def test_preview_blank_only_restricts_moves_to_blank_records(tmp_path):
    """「빈 값 있는 건만 보기」(U2 §2.13) — ‹ › 이동이 빈 값 있는 건 사이로만 간다.

    「12건 중 2건이 비었다」를 알아도 어느 2건인지 아무도 말하지 않아 전 건을 넘겨야
    했다 — 훑기 가속의 실제 기제는 표지가 아니라 이 한정이다(선례: 「실패한 건만 선택」).
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    csv = tmp_path / "mixed.csv"
    # 표시순(sourceDesc) = 원본 3·2·1·0. 빈 값(presmptPrce)은 원본 0·2 = 자리 1·3.
    csv.write_text("bidNtceNm,presmptPrce\nA,\nB,100\nC,\nD,200\n", encoding="utf-8")
    _mount_all(ctrl, str(csv))
    ctrl.dispatch("preview_open", {})
    p = ctrl.snapshot()["preview"]
    assert p["blank_count"] == 2 and p["blank_only"] is False
    ctrl.dispatch("preview_blank_only", {"value": True})
    p = ctrl.snapshot()["preview"]
    assert p["blank_only"] is True and p["pos"] == 1     # 대상 밖 자리 → 가장 가까운 빈 값 건
    ctrl.dispatch("preview_move", {"delta": 1})
    assert ctrl.snapshot()["preview"]["pos"] == 3        # 채움 건(자리 2)을 건너뛴다
    p = ctrl.snapshot()["preview"]
    assert p["can_next"] is False and p["can_prev"] is True  # 경계 = 그 건들의 처음·끝
    ctrl.dispatch("preview_move", {"delta": 1})
    assert ctrl.snapshot()["preview"]["pos"] == 3        # 경계에서 멈춘다(순환 없음)
    ctrl.dispatch("preview_move", {"delta": -1})
    assert ctrl.snapshot()["preview"]["pos"] == 1
    ctrl.dispatch("preview_blank_only", {"value": False})
    ctrl.dispatch("preview_move", {"delta": 1})
    assert ctrl.snapshot()["preview"]["pos"] == 2        # 끄면 이동이 전 건으로 돌아온다
    # 닫으면 보기 상태도 함께 놓는다(열림·자리와 같은 수명).
    ctrl.dispatch("preview_close", {})
    ctrl.dispatch("preview_open", {})
    assert ctrl.snapshot()["preview"]["blank_only"] is False


def test_preview_blank_only_refuses_when_no_record_is_blank(tmp_path):
    """빈 값 건이 0이면 켤 수 없다 — 무동작 토글 금지(표면도 0건이면 비활성이지만
    잠금은 상태가 진다)."""
    ctrl, _ = _clean_session(tmp_path)
    ctrl.dispatch("preview_open", {})
    with pytest.raises(ValueError, match="빈 값이 있는 문서가 없습니다"):
        ctrl.dispatch("preview_blank_only", {"value": True})
    assert ctrl.snapshot()["preview"]["blank_count"] == 0


def _clean_session(tmp_path):
    """검토 요구가 하나도 없는 세션 — 기준선 있음 + **빈 값 없는** 데이터(§2.13 뒤로는
    빈 값이 있으면 blank_set 요구가 서므로 「요구 없음」 픽스처는 데이터도 깨끗해야 한다)."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    clean = tmp_path / "clean.csv"
    clean.write_text("bidNtceNm,presmptPrce\n전산장비,1000\n사무비품,2000000\n", encoding="utf-8")
    _mount_all(ctrl, str(clean))
    return ctrl, pushes


def test_preview_opens_even_when_nothing_needs_review(tmp_path):
    """§13-2 — 정상 반복 실행에서 미리보기는 **선택**이지 금지가 아니다."""
    ctrl, _ = _clean_session(tmp_path)
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
    ctrl, _ = _clean_session(tmp_path)
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


def test_preview_has_no_scope_axis(tmp_path):
    """「적용 범위」 축은 없다(U2 §2.3) — 값이 하나뿐인 축은 없는 선택지의 암시다.

    이 자리는 원래 `runOverrides`(F7 PR-B)의 짝이었다. 그것이 §10.14 에서 기각·사망하고
    §10.15 판정 H 가 작업대의 대응 배지를 "말할 상태가 없다"며 죽였는데 드로어의 이 항목만
    살아남아 있었다 — 판정 일관성의 미이행분이다.

    **뒤집힌 선언이지 지운 테스트가 아니다.** 종전엔 "「기본 규칙」이라고만 말하고 「이번
    생성에만」을 암시하지 말라"를 지켰다. override 가 실제로 서면 그때 축이 돌아오는 것이
    맞고, 그때까지는 축의 부재가 계약이다.
    """
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("preview_open", {})
    preview = ctrl.snapshot()["preview"]
    assert "scope" not in preview, (
        "적용 범위 축이 재유입됐습니다 — runOverrides 없이 이 축을 세우면 "
        "고를 수 없는 선택지를 암시합니다."
    )


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
    _approve_run(ctrl)
    ctrl.dispatch("preview_open", {})
    shown = ctrl.snapshot()["preview"]["filename"]
    assert ctrl.generate()["ok"] is True
    written = {p.name for p in (tmp_path / "out").glob("*.hwpx")}
    assert shown in written, f"미리보기 이름 {shown!r} 가 생성물 {written!r} 에 없습니다."


def test_the_marker_appears_whenever_blanks_exist(tmp_path):
    """`_run_marker` 재정의(U2 §2.13) — 조건은 「빈 값이 있으면」 하나다.

    구 「확인 안 된 빈 값 = 표식 없음」 중간 상태는 ack 폐기와 함께 사라졌다: 생성·
    미리보기·승인 세 자리가 같은 술어를 쓰므로, 미리보기 이름에도 처음부터 표식이 선다
    — 승인이 곧 「이 표식이 박힌 이름·값」에 대한 동의가 된다.
    """
    ctrl, _ = _controller(tmp_path, reviewed=True)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "{{추정가격}}"
    ctrl.registry.save(job, allow_overwrite=True)
    _rereview(ctrl)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("preview_open", {})
    ctrl.dispatch("preview_move", {"delta": 1})   # 빈 값이 나는 레코드로 이동
    assert "미입력" in ctrl.snapshot()["preview"]["filename"]


def test_blank_fields_count_blanks_not_markers(tmp_path):
    """빈 값 표지·「빈 값 있는 건만 보기」는 표식 **없는** 판에서 센다 — 표식(생성 입력)을
    세면 언제나 0건이 되어 표지가 거짓이 된다. 두 판이 같은 사실을 다른 각도로 말한다."""
    ctrl, _ = _session(tmp_path)
    snap = ctrl.snapshot()
    assert snap["blank_fields"] == ["추정가격"]
    assert snap["preview"]["blank_count"] == 1     # 2건 중 1건이 빈 값


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

    빈 값이 없는 데이터를 쓴다 — 빈 값이 있으면 blank_set 요구(§2.13)가 서서 「요구 없는
    반복 실행」이라는 이 테스트의 전제가 성립하지 않는다.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    clean = tmp_path / "clean.csv"
    clean.write_text("bidNtceNm,presmptPrce\n전산장비,1000\n사무비품,2000000\n", encoding="utf-8")
    _mount_all(ctrl, str(clean))
    ctrl.set_output_folder(str(tmp_path / "out"))
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


def test_new_blanks_on_new_data_reinstate_the_gate(tmp_path):
    """침묵 금지(U2 §2.13 **최우선**) — 한 번 완주한 작업에 새 데이터를 올려 빈 값이
    새로 생기면 게이트가 선다.

    승인은 규칙 지문 기반이라 완주 뒤 영구히 조용해진다(판정 N). 빈 값 집합이 승인
    지문에 들지 않으면 다음 달 새 데이터의 빈 값이 **표식이 박힌 문서를 조용히 생성**한다
    — 생성 시점에 아무도 말하지 않고, 제출한 뒤에 아는 순서가 된다.
    """
    ctrl, _ = _controller(tmp_path)                       # 기준선 있는 작업(완주 자격)
    ctrl.dispatch("select_job", {"name": "공고서"})
    clean = tmp_path / "clean.csv"
    clean.write_text("bidNtceNm,presmptPrce\n전산장비,1000\n사무비품,2000000\n", encoding="utf-8")
    _mount_all(ctrl, str(clean))
    ctrl.set_output_folder(str(tmp_path / "out"))
    assert ctrl.snapshot()["gate"]["enabled"] is True     # 빈 값 없음 = 조용한 반복 실행
    assert ctrl.generate()["ok"] is True                  # 완주 — 기준선이 다시 선다

    _mount_all(ctrl, _data_csv(tmp_path))                 # 다음 달 데이터 — 빈 값 신규 발생
    snap = ctrl.snapshot()
    assert snap["gate"]["enabled"] is False, "새 빈 값인데 게이트가 서지 않습니다(조용한 표식 생성)."
    assert snap["gate"]["reason"] == "review_required" and "빈 값" in snap["gate"]["text"]
    res = ctrl.generate()                                 # 백스톱도 같은 판정
    assert res["ok"] is False and "빈 값" in res["error"]
    _approve_run(ctrl)                                    # 표식 삽입 동의 = 승인 1번
    assert ctrl.snapshot()["gate"]["enabled"] is True
    # 같은 폴더 재생성이라 덮어쓰기 확인(RC-02)이 먼저 선다 — 확인 뒤 생성이 열린다.
    assert ctrl.generate()["needs_overwrite"] is True
    assert ctrl.generate(confirm_overwrite=True)["ok"] is True


def test_review_scope_key_hashes_the_blank_field_set(tmp_path):
    """§2.13 조건 — 승인 지문의 표식 성분은 이진값(有/無)이 아니라 **빈 값 필드 집합의
    해시**다. 「담당자가 빈 데이터」에서 한 승인이 「개찰장소가 빈 데이터」에서도 유효하면
    한 번도 보지 않은 표식이 박힌 문서가 생긴다 — 집합이 갈리면 키가 갈려야 한다."""
    ctrl, _ = _session(tmp_path)
    k_none = ctrl._review_scope_key(blanks=[])
    k_a = ctrl._review_scope_key(blanks=["담당자"])
    k_b = ctrl._review_scope_key(blanks=["개찰장소"])
    k_ab = ctrl._review_scope_key(blanks=["담당자", "개찰장소"])
    assert len({k_none, k_a, k_b, k_ab}) == 4
    # 순서는 정체가 아니다 — 같은 집합이면 같은 키(정렬 정규화).
    assert ctrl._review_scope_key(blanks=["개찰장소", "담당자"]) == k_ab


# ------------------------------------------- TXT 합류와 작업대 진입 (재작성 F6 PR-A)
def _txt_job(ctrl, tmp_path, *, name: str = "발주요청_기안") -> None:
    """같은 데이터로 돌 수 있는 TXT 작업을 하나 저장한다(후보 판정은 hwpx 와 같은 술어)."""
    tpl = tmp_path / f"{name}.txt"
    tpl.write_text("공고: {{공고명}}", encoding="utf-8")
    ctrl.registry.save(Job(
        name=name, template_path=str(tpl),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source="bidNtceNm")]),
    ))


def test_txt_work_joins_the_candidates_with_its_mode(tmp_path):
    """TXT 는 hwpx 와 한 순위에서 겨루고 카드가 방식을 싣는다(§19.3 — 구획은 표면 몫)."""
    ctrl, _ = _controller(tmp_path)
    _txt_job(ctrl, tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))
    top = ctrl.snapshot()["candidates"]["top"]
    modes = {c["name"]: c["mode"] for c in top}
    assert modes == {"공고서": "hwpx_generate", "발주요청_기안": "text_review_copy"}


def test_selecting_a_txt_work_does_not_build_an_hwpx_run_view(tmp_path):
    """매체 파생 2분기(판정 D) — TXT 선택은 실행뷰를 세우지 않는다.

    `RunViewModel` 은 이 job 의 템플릿을 hwpx 로 파싱하므로(진입 가드가 loud 거부) 여기서
    갈라야 조회 경계가 새지 않는다. 그리고 **작업은 선택된 상태**다: `has_job` 이
    `vm is not None` 이 아니라 이름에서 오는 이유가 이것이다.
    """
    ctrl, _ = _controller(tmp_path)
    _txt_job(ctrl, tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("select_job", {"name": "발주요청_기안"})
    snap = ctrl.snapshot()
    assert ctrl.vm is None and ctrl.job_is_txt is True
    assert snap["has_job"] is True and snap["job_name"] == "발주요청_기안"
    assert snap["run_action"] == {"key": "workbench", "label": "검토·복사 시작 · 2건"}
    # 파일 이름 규칙 축은 이 매체에 **없다**(§3.2) — 빈 값이 "아직 안 정했다"가 아니다.
    assert snap["filename_pattern"] == ""
    # 검토 요구·미리보기 드로어는 배제 선언(판정 J) — 골격만 서고 열리지 않는다.
    assert snap["preview"]["can_open"] is False
    assert snap["review"]["required"] is False


def test_switching_back_to_an_hwpx_work_restores_the_run_view(tmp_path):
    """두 매체를 오가도 각자의 세계로 정확히 돌아온다(잔여 상태 누수 금지)."""
    ctrl, _ = _controller(tmp_path)
    _txt_job(ctrl, tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("select_job", {"name": "발주요청_기안"})
    ctrl.dispatch("select_job", {"name": "공고서"})
    assert ctrl.vm is not None and ctrl.job_is_txt is False
    assert ctrl.snapshot()["run_action"]["key"] == "generate"
    ctrl.dispatch("select_job", {"name": ""})
    assert ctrl.vm is None and ctrl.job_is_txt is False
    assert ctrl.snapshot()["has_job"] is False


def test_workbench_entry_refuses_without_a_selection(tmp_path):
    """선택 0건에서는 TXT 세션에 진입하지 않는다(§18.10 수용 6 — 첫 레코드를 대신 쓰지 않는다)."""
    ctrl, _ = _controller(tmp_path)
    _txt_job(ctrl, tmp_path)
    ctrl.load_data_path(_data_csv(tmp_path))       # 마운트 직후 선택 0건
    ctrl.dispatch("select_job", {"name": "발주요청_기안"})
    res = ctrl.dispatch("open_workbench", {})
    assert res["ok"] is False and "선택" in res["error"]


def test_workbench_entry_refuses_over_an_open_range_draft(tmp_path):
    """작업대는 **커밋된** 실행 입력의 사본을 뜬다(F5 판정 H 승계) — 초안 세계와 겹치지 않는다."""
    ctrl, _ = _controller(tmp_path)
    _txt_job(ctrl, tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("select_job", {"name": "발주요청_기안"})
    ctrl.dispatch("range_draft_open", {})
    res = ctrl.dispatch("open_workbench", {})
    assert res["ok"] is False and "범위" in res["error"]


def test_workbench_entry_hands_over_the_display_ordered_selection(tmp_path):
    """넘기는 것은 표시순 투영을 통과한 고정 사본이다(§18.11-24: 두 매체가 같은 것을 소비)."""
    ctrl, _ = _controller(tmp_path)
    _txt_job(ctrl, tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("select_job", {"name": "발주요청_기안"})
    wb = WorkbenchController(
        ctrl.registry, lambda s, snap: None, target_font=TargetFontSetting())
    ctrl.workbench_open = wb.open
    res = ctrl.dispatch("open_workbench", {})
    assert res["ok"] and res["count"] == 2
    # 표시순서 기본값은 sourceDesc(최신 행 먼저) — 작업대가 그 순서를 그대로 받는다.
    assert wb.source_rows == [2, 1] and wb.job_name == "발주요청_기안"


def test_hwpx_work_never_opens_the_workbench(tmp_path):
    """방식 국경은 진입에서도 fail-closed — 표면이 잘못 발신해도 조용히 열리지 않는다."""
    ctrl, _ = _controller(tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("select_job", {"name": "공고서"})
    res = ctrl.dispatch("open_workbench", {})
    assert res["ok"] is False


def test_candidate_sections_stand_only_when_both_modes_are_present(tmp_path):
    """§19.3 — 구획은 두 방식이 다 있을 때만. 판정은 Python 이 낸다(표면은 머리글만)."""
    ctrl, _ = _controller(tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))
    only_hwpx = ctrl.snapshot()["candidates"]["sections"]
    assert len(only_hwpx) == 1 and only_hwpx[0]["mode"] == "hwpx_generate"
    _txt_job(ctrl, tmp_path)
    both = ctrl.snapshot()["candidates"]["sections"]
    assert {s["mode"] for s in both} == {"hwpx_generate", "text_review_copy"}
    # 구획 순서는 순위의 함수다 — 전체 순위를 구획으로 자를 뿐 방식별 자리 보장은 없다.
    top_names = [c["name"] for c in ctrl.snapshot()["candidates"]["top"]]
    assert both[0]["names"][0] == top_names[0]


def test_candidate_card_carries_the_media_aware_recent_use_label(tmp_path):
    """§19.4 — 두 매체가 다른 술어를 쓴다는 사실을 카드 문안이 말한다."""
    ctrl, _ = _controller(tmp_path)
    _txt_job(ctrl, tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))
    labels = {c["name"]: c["last_run_label"] for c in ctrl.snapshot()["candidates"]["top"]}
    assert labels["공고서"] == "성공한 실행 없음"
    assert labels["발주요청_기안"] == "복사한 적 없음"


def test_browse_rows_section_inside_the_tab_not_across_it(tmp_path):
    """§19.5 — 탭이 primary classification 이고 방식은 탭 **안**에서만 구획한다."""
    ctrl, _ = _controller(tmp_path)
    _txt_job(ctrl, tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))
    b = ctrl.snapshot()["browse"]
    assert b["tab"] == "available"
    assert {s["mode"] for s in b["sections"]} == {"hwpx_generate", "text_review_copy"}
    assert all("mode_label" in r for r in b["rows"])


def test_review_and_preview_are_declared_out_of_scope_for_txt(tmp_path):
    """검토 요구·미리보기 드로어는 TXT 에서 **배제 선언**이다(지도 §10.15 판정 J).

    근거: 드로어는 값 + **파일 이름** + 승인의 면인데 TXT 엔 파일 이름 축이 없고(§3.2),
    작업대가 이미 레코드 전수를 채운 모습으로 보여 주는 검토 표면이다. TXT 에 요구를
    세우면 작업대에서 눈으로 본 것을 「문서 만들기」에서 또 확인하라는 **이중 권위**가
    된다(§10.5 판정 단일 출처).

    배제를 **선언으로** 남기는 이유는 F5 판정 O·F7 판정 K 와 같다: 조용한 무시와 선언된
    배제는 다르다. 누군가 TXT 에 검토 축을 배선하면 이 테스트가 그 결정을 다시 꺼낸다.
    """
    ctrl, _ = _controller(tmp_path, reviewed=False)   # 한 번도 완주하지 않은 작업 = 요구 있음
    _txt_job(ctrl, tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("select_job", {"name": "공고서"})
    assert ctrl.snapshot()["review"]["required"] is True, "hwpx 쪽 요구가 서지 않으면 대조가 무의미"
    ctrl.dispatch("select_job", {"name": "발주요청_기안"})
    snap = ctrl.snapshot()
    assert snap["review"] == {
        "required": False, "approved": False, "risk": "", "targets": [],
        "first_run": False, "unknown_baseline": False, "structure_changed": False,
    }
    assert snap["preview"]["can_open"] is False
    # 게이트 사유도 검토를 들먹이지 않는다 — TXT 게이트는 진입 자격만 센다.
    assert "확인" not in snap["gate"]["text"] or "검토" not in snap["gate"]["text"]
    # 드로어를 직접 열려는 발신은 **시끄럽게** 거절된다(표면 오발신 fail-closed). 문안은
    # 사실이어야 한다: TXT 는 작업이 선택된 채로 `vm` 이 없으므로 "작업을 선택하세요"는
    # 방금 고른 작업을 못 본 척하는 거짓 지시가 된다.
    with pytest.raises(ValueError, match="작업대"):
        ctrl.dispatch("preview_open", {})
    assert ctrl.snapshot()["preview"]["open"] is False


def test_txt_session_survives_rename_because_it_holds_no_job_copy(tmp_path):
    """이름 변경 뒤에도 작업대가 **지금 그 작업**을 연다(1R P2 근본 조치의 회귀).

    첫 판은 세션이 `txt_job: Job` 사본을 들었고, 그 순간 durable 사실의 제2 정본이 생겨
    이름 변경(`vm.job` 만 갱신)·재연결·재적재가 전부 조용한 구멍이 됐다. 사본을 없애고
    **쓰는 순간** 레지스트리에서 읽으니 이 경로들은 고칠 것이 없다 — 그게 요점이다.
    """
    ctrl, _ = _controller(tmp_path)
    _txt_job(ctrl, tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("select_job", {"name": "발주요청_기안"})
    ctrl.dispatch("rename_job", {"name": "발주요청_기안", "new": "발주요청_기안 v2"})
    assert ctrl.job_name == "발주요청_기안 v2" and ctrl.job_is_txt is True
    wb = WorkbenchController(
        ctrl.registry, lambda s, snap: None, target_font=TargetFontSetting())
    ctrl.workbench_open = wb.open
    assert ctrl.dispatch("open_workbench", {})["ok"] is True
    assert wb.job_name == "발주요청_기안 v2"


def test_txt_session_sees_rules_saved_elsewhere_on_re_entry(tmp_path):
    """다른 표면이 저장한 규칙이 재진입에 **반영**된다 — 들고 있는 사본이 없으므로."""
    ctrl, _ = _controller(tmp_path)
    _txt_job(ctrl, tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("select_job", {"name": "발주요청_기안"})
    ctrl.registry.mutate(
        "발주요청_기안",
        lambda j: setattr(j, "mapping", MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source="presmptPrce")])),
    )
    wb = WorkbenchController(
        ctrl.registry, lambda s, snap: None, target_font=TargetFontSetting())
    ctrl.workbench_open = wb.open
    ctrl.dispatch("open_workbench", {})
    assert wb.base_job is not None
    assert wb.base_job.mapping.mappings[0].source == "presmptPrce"


def test_open_workbench_is_loud_when_the_work_vanished(tmp_path):
    """그사이 삭제된 작업은 조용한 무동작이 아니라 사유와 함께 거절된다."""
    ctrl, _ = _controller(tmp_path)
    _txt_job(ctrl, tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("select_job", {"name": "발주요청_기안"})
    ctrl.registry.delete("발주요청_기안")
    ctrl.workbench_open = WorkbenchController(
        ctrl.registry, lambda s, snap: None, target_font=TargetFontSetting()).open
    res = ctrl.dispatch("open_workbench", {})
    assert res["ok"] is False and "읽을 수 없습니다" in res["error"]


def test_cross_media_relink_is_rejected_and_the_session_keeps_its_seat(tmp_path):
    """교차 재연결은 거절되고 활성 세션의 자리는 그대로다(§10.16 판정 C·E).

    종전 판(2R P2)은 「재연결로 매체가 갈리면 재착석한다」를 가드했다 — 매체 교차 relink
    가 열려 있던 시절의 방어 코드다. 게이트가 교차를 원천 차단한 지금은 재착석할 사건
    자체가 없고, 그 분기(`_reload_active_job` 의 seat-kind 대조)도 판정 E 로 회수됐다.
    거절이 durable 과 세션 어느 쪽도 건드리지 않는 것을 실제 디스패치 경로로 가드한다
    (종전 판의 레지스트리 직접 뮤테이션은 더는 제품 경로가 아니다).
    """
    ctrl, _ = _controller(tmp_path)
    _txt_job(ctrl, tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("select_job", {"name": "발주요청_기안"})
    assert ctrl.snapshot()["run_action"]["key"] == "workbench"

    res = ctrl.dispatch(
        "relink_template",
        {"name": "발주요청_기안", "path": str(tmp_path / "t.hwpx"), "confirm": True})
    assert res["ok"] is False and "삭제하고 새로 만드세요" in res["error"]
    ctrl.dispatch("refresh", {})
    assert ctrl.job_is_txt is True and ctrl.vm is None      # 자리 불변(재착석 사건 없음)
    assert ctrl.snapshot()["run_action"]["key"] == "workbench"
    assert ctrl.registry.load("발주요청_기안").template_path.endswith(".txt")


def test_workbench_entry_is_loud_when_the_template_is_not_utf8(tmp_path):
    """비-UTF-8 템플릿도 **화면 안에서** 사유를 말한다(6R).

    온나라 기안 txt 는 ANSI/CP949 로 저장돼 오기 쉽다. 파일은 실재하므로 게이트는 열려
    있고, 진입이 `UnicodeDecodeError`(`OSError` 아님)를 그대로 올리면 웹의 `.then` 이
    발화하지 않아 사용자는 누를 수 있는 버튼을 누르고 아무 설명도 못 듣는다.
    """
    ctrl, _ = _controller(tmp_path)
    _txt_job(ctrl, tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("select_job", {"name": "발주요청_기안"})
    (tmp_path / "발주요청_기안.txt").write_bytes("공고: {{공고명}}".encode("cp949"))
    assert ctrl.snapshot()["gate"]["enabled"] is True   # 파일은 실재한다
    ctrl.workbench_open = WorkbenchController(
        ctrl.registry, lambda s, n: None, target_font=TargetFontSetting()).open
    res = ctrl.dispatch("open_workbench", {})
    assert res["ok"] is False and "템플릿을 읽을 수 없습니다" in res["error"]


def test_an_unsupported_template_does_not_blow_up_the_screen(tmp_path):
    """hwpx 도 txt 도 아닌 경로로 갈린 활성 작업 — 재적재가 터지지 않고 사유를 말한다.

    relink 게이트가 새 매체 미상을 거절하므로(§10.16 판정 C) 이 상태는 제품 경로로는 못
    만든다 — 남는 실물은 JSON 손편집이다. 그래도 재적재는 자리를 다시 앉혀야 한다:
    「TXT 가 아니면 hwpx」로 갈면 `RunViewModel` 이 `require_hwpx` 에서 loud raise 하고,
    그 예외가 화면 전환마다 도는 재적재 밖으로 튄다. 복귀 방향(미상→txt)은 게이트가
    허용하는 **복구 전이**이기도 하다(판정 E 정정 — 리뷰 1R P2).
    """
    ctrl, _ = _controller(tmp_path)
    _txt_job(ctrl, tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("select_job", {"name": "발주요청_기안"})

    odd = tmp_path / "발주요청_기안.docx"
    odd.write_text("x", encoding="utf-8")
    ctrl.registry.mutate("발주요청_기안", lambda j: setattr(j, "template_path", str(odd)))
    ctrl.dispatch("refresh", {})                       # 예외 없이 자리를 다시 앉힌다
    assert ctrl.job_is_txt is False and ctrl.vm is None
    assert ctrl.job_unsupported is True

    snap = ctrl.snapshot()
    assert snap["has_job"] is True and snap["job_name"] == "발주요청_기안"
    # 「작업 미선택」 문안을 쓰지 않는다 — 이미 고른 사람에게 이행 불가능한 지시가 된다.
    assert snap["gate"]["enabled"] is False and snap["gate"]["level"] == "danger"
    assert "다시 연결" in snap["gate"]["text"]
    assert snap["template_name"] == "발주요청_기안.docx"

    # 되돌아오면 다시 작업대의 것이 된다(래치가 한 자리에서만 선다).
    ctrl.registry.mutate(
        "발주요청_기안",
        lambda j: setattr(j, "template_path", str(tmp_path / "발주요청_기안.txt")))
    ctrl.dispatch("refresh", {})
    assert (ctrl.job_is_txt, ctrl.job_unsupported) == (True, False)


def test_recovery_relink_reseats_the_active_session(tmp_path):
    """복구 재연결(미상→hwpx)이 화면 밖에서 커밋되면 재적재가 자리를 앉힌다(판정 E 정정, 리뷰 1R P2).

    미상 `.docx` 구작업의 relink 는 게이트가 **허용**하는 복구 경로다(판정 C — 유일 복구).
    라이브러리에서 복구하고 이 화면으로 돌아왔을 때 재착석 분기가 없으면, 화면은 유효해진
    템플릿을 재선택 전까지 unsupported 라고 계속 주장한다 — 지문 대조는 unsupported
    세션(vm 없음)을 못 보므로 대체가 아니다.
    """
    ctrl, _ = _controller(tmp_path)
    odd = tmp_path / "구양식.docx"
    odd.write_text("x", encoding="utf-8")
    ctrl.registry.save(Job(
        name="깨진작업", template_path=str(odd),
        mapping=ctrl.registry.load("공고서").mapping))
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("select_job", {"name": "깨진작업"})
    assert ctrl.job_unsupported is True and ctrl.vm is None

    # 라이브러리 복구 relink 의 화면 밖 durable 변경을 시뮬레이트(같은 게이트 경로는 T4 가 가드).
    ctrl.registry.mutate(
        "깨진작업", lambda j: setattr(j, "template_path", str(tmp_path / "t.hwpx")))
    ctrl.dispatch("refresh", {})
    assert ctrl.job_unsupported is False and ctrl.vm is not None
    assert ctrl.snapshot()["run_action"]["key"] == "generate"


def test_workbench_entry_is_blocked_and_loud_when_the_template_vanished(tmp_path):
    """템플릿이 사라졌으면 **버튼이 먼저 정직하고**, 그래도 눌리면 사유를 돌려준다(5R P2).

    게이트만으로는 부족하다(판정과 진입 사이에도 파일은 사라진다). 진입만으로도 부족하다
    (누를 수 있는 버튼이 아무 설명 없이 아무 일도 안 하는 것처럼 보인다). 둘 다 필요하다.
    """
    ctrl, _ = _controller(tmp_path)
    _txt_job(ctrl, tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("select_job", {"name": "발주요청_기안"})
    assert ctrl.snapshot()["gate"]["enabled"] is True
    (tmp_path / "발주요청_기안.txt").unlink()          # 다른 곳에서 템플릿이 사라졌다
    snap = ctrl.snapshot()
    assert snap["gate"]["enabled"] is False and "템플릿" in snap["gate"]["text"]
    ctrl.workbench_open = WorkbenchController(
        ctrl.registry, lambda s, n: None, target_font=TargetFontSetting()).open
    res = ctrl.dispatch("open_workbench", {})
    assert res["ok"] is False and "템플릿" in res["error"]


# --------------------------------------------- 휘발 「기안」 폐지 고지 ①(F6 PR-B)
def test_candidates_txt_note_speaks_only_to_the_volatile_draft_audience(tmp_path):
    """고지 ①(§10.15.15 판정 A) 3태 — 술어(txt 템플릿 有 ∧ txt 작업 0건)의 양단 고정.

    ① 템플릿 0: 침묵(순수 HWPX 사용자에 소음 금지) ② 템플릿 有·txt 작업 0: 발화(대체
    경로 = 저장 TXT 작업 경유를 재진술) ③ txt 작업이 서면: 침묵(이미 건너간 사용자).
    영속 플래그 없음 — 매 스냅샷 파생이라 상태가 바뀌면 문안이 저절로 걷힌다.
    """
    reg = _registry(tmp_path)                       # hwpx 작업 1개(공고서)
    txt_dir = tmp_path / "text_templates"
    ctrl = JobController(
        reg, lambda s, snap: None, text_registry=TextTemplateRegistry(txt_dir), **_deps(tmp_path)
    )
    _mount_all(ctrl, _data_csv(tmp_path))
    assert ctrl.snapshot()["candidates"]["txt_note"] == ""      # ① 템플릿 0 = 침묵
    txt_dir.mkdir()
    (txt_dir / "기안.txt").write_text("{{공고명}}", encoding="utf-8")
    note = ctrl.snapshot()["candidates"]["txt_note"]
    assert "저장" in note and "＋ 새 작업" in note               # ② 발화 = 대체 경로 재진술
    tpl = tmp_path / "기안틀.txt"
    tpl.write_text("{{공고명}}", encoding="utf-8")
    reg.save(Job(name="기안작업", template_path=str(tpl)))
    assert ctrl.snapshot()["candidates"]["txt_note"] == ""      # ③ txt 작업 有 = 침묵


def test_candidates_txt_note_is_silent_without_an_injected_registry(tmp_path):
    """레지스트리 미주입(테스트·CLI 소비자) — 실 홈 스캔 없이 항상 침묵(격리·결정성)."""
    ctrl, _ = _controller(tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))
    assert ctrl.snapshot()["candidates"]["txt_note"] == ""


def test_preview_open_at_restores_the_same_position_with_clamp(tmp_path):
    """deep-link 복귀의 같은 자리(§10.15.15 판정 C) — `at` 은 Python 스냅샷 값의 왕복이고
    Python 이 클램프한다(편집 중 선택이 줄어도 stale 인덱스로 남의 행을 그리지 않는다)."""
    ctrl, _ = _session(tmp_path)
    ctrl.dispatch("preview_open", {"at": 1})
    assert ctrl.snapshot()["preview"]["pos"] == 1               # 같은 자리 복귀
    ctrl.dispatch("preview_close", {})
    ctrl.dispatch("preview_open", {"at": 99})
    assert ctrl.snapshot()["preview"]["pos"] == 1               # 상한 클램프(총 2건)
    ctrl.dispatch("preview_close", {})
    ctrl.dispatch("preview_open", {})
    assert ctrl.snapshot()["preview"]["pos"] == 0               # 무인자 = 종전 거동(첫 행)
