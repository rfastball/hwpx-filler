"""「작업」 화면 컨트롤러 계약 가드 — pywebview/Qt 불필요(헤드리스).

패널 4존이 소비하는 링1 배선(부록 A-1)을 창 없이 되읽는다: 좌 목록 → 작업 선택 → 데이터 겨눔
→ 빈 값 승인 게이트(blank_set — U2 §2.13, 구 필드축 ack 의 승계) → 덮어쓰기 재진술(RC-02)
→ 생성 end-to-end. JobController가 링1 계약을 위임해 소비하는지 못박는다.
"""
from __future__ import annotations

import shutil
import sqlite3
import threading
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from _output_folder_pick import pick_output_folder

from hwpxfiller.domain.job import Job, rules_fingerprints
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.external.hwpx_package_io import read_hwpx_package, write_hwpx_package
from hwpxfiller.external.text_registry import TextTemplateRegistry
from hwpxfiller.external.output_files import ensure_output_directory, existing_output_paths
from hwpxfiller.external.settings import load_last_data_source, save_last_data_source
from hwpxfiller.data.factory import source_for_path, source_from_pool_item
from hwpxfiller.webapp.screen_library import LibraryController
from hwpxfiller.domain.mapping import FieldMapping, MappingProfile
from hwpxfiller.gui.review_state import review_requirement
from hwpxfiller.gui.run_state import RunViewModel
from hwpxfiller.gui.selection_state import SelectionModel
from hwpxfiller.gui.work_candidates import MAIN_TOP_N
from hwpxfiller.webapp import screen_job as screen_job_module
from hwpxfiller.webapp import template_change as template_change_module
from hwpxfiller.webapp.screen_job import JobController
from hwpxfiller.webapp.template_change import TemplateChangeCoordinator, TemplateChangeError
# TargetFontSetting 은 「기안」 사망(F6 PR-B)으로 작업대 모듈이 승계(동일 클래스·영속 키).
from hwpxfiller.webapp.screen_workbench import TargetFontSetting, WorkbenchController
from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage

MULTI_SHEET = Path(__file__).resolve().parents[0] / "fixtures" / "multi_sheet.xlsx"
_NOW = datetime(2026, 7, 21, 9, 0, 0)


def _clock():
    current = _NOW

    def tick():
        nonlocal current
        value = current
        current += timedelta(seconds=1)
        return value

    return tick


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
    write_hwpx_package(
        path,
        HwpxPackage(entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": xml}),
    )


def _data_csv_path(tmp_path) -> str:
    """이 파일의 기본 데이터 경로 — 파일을 쓰지 않고 **자리만** 답한다.

    `_registry` 는 컨트롤러보다 먼저 서고 데이터는 테스트가 필요할 때 쓴다. 그래서 결속
    재료는 경로 계산으로만 얻고, 실제 파일 생성은 `_data_csv` 가 진다(같은 자리 단일 출처).
    """
    return str(tmp_path / "d.csv")


def _bound_to(path: str, sheet: str = "", header_row: int = 0) -> dict:
    """데이터 결속 3성분 kwargs — `Job(...)` 생성 지점이 한 벌로 받는다(#932 U4-C).

    경로 하나만 넘기는 축약을 두지 않는다: 결속은 한 벌이고, 성분을 흘리면 테스트가
    사람이 고른 것과 다른 헤더에 결속된 작업을 만든다(#349 리뷰 2R 와 같은 규율).
    """
    return {"data_path": path, "data_sheet": sheet, "data_header_row": header_row}


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
        # 후보 축이 결속 역인덱스라(#932 U4-C) 픽스처 작업은 이 파일의 기본 데이터에
        # 결속돼 있어야 후보로 선다. 경로는 `_data_csv` 가 쓰는 자리와 같은 한 곳이다 —
        # 두 자리에 적으면 한쪽만 고쳐지는 날 후보가 조용히 0건이 된다.
        **_bound_to(_data_csv_path(tmp_path)),
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
    """구성 공통 주입 한 벌 — engine(P2-25)·pool_registry(#570)·
    generation_lock(P2-24)은 폴백 없이 **명시 주입**한다. ``lock`` 은 화면 간
    공유를 재는 테스트의 관통용."""
    return {
        **_FACTORIES,
        "clock": _clock(),
        "existing_outputs": existing_output_paths,
        "ensure_output_dir": ensure_output_directory,
        "engine": make_hwpx_engine(),
        "pool_registry": DatasetPoolRegistry(tmp_path / "pool"),
        "generation_lock": lock if lock is not None else threading.Lock(),
    }


def _controller(tmp_path, *, reviewed: bool = True, file_source_factory=source_for_path):
    pushes: list = []
    ctrl = JobController(
        _registry(tmp_path, reviewed=reviewed), lambda s, snap: pushes.append((s, snap)),
        clock=_clock(),
        existing_outputs=existing_output_paths,
        ensure_output_dir=ensure_output_directory,
        engine=make_hwpx_engine(),
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
    """마운트 + 명시 Work 재선택 + 전체 선택 — legacy 생성 시나리오의 공통 준비."""
    selected_work = ctrl.job_name
    ctrl.load_data_path(path, sheet=sheet)
    if selected_work and not ctrl.job_name:
        ctrl.dispatch("select_job", {"name": selected_work})
    ctrl.dispatch("set_all", {})


def _unbind(ctrl, name: str = "공고서") -> None:
    """작업의 결속을 지운다(#932 U4-C) — 결속 축이 아닌 것을 재는 테스트를 위한 헬퍼다.

    결속이 남아 있으면 결속 밖 데이터로의 전이마다 active Work가 RELEASE 되고,
    `_mount_all` 의 재선택이 `_mount_job_binding` 을 태워 그 작업의 결속 데이터로
    조용히 되튄다 — 방금 마운트한(결속과 다른) 데이터가 재선택 한 줄 만에 지워진다.
    결속을 비우면 재선택이 무동작이라(`_mount_job_binding` 의 「결속 없음」 분기) 이
    되튐이 없다. 결속 축을 재는 테스트가 아니라 자유 마운트 시나리오(가드·재적용
    선반 등)를 재는 테스트만 쓴다.
    """
    ctrl.registry.save(
        replace(ctrl.registry.load(name), **_bound_to("")), allow_overwrite=True,
    )


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
    ctrl.load_data_path(_data_csv(tmp_path))
    assert factory_calls == [(_data_csv(tmp_path), None)]  # 주입 factory 경유 1회
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["has_job"] is True and snap["job_name"] == "공고서"
    # 저장 폴더 기본값 = 템플릿 폴더/Results(실행 화면 동형).
    assert snap["out_dir"].endswith("Results")
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


def test_prework_gate_counts_only_available_candidates(tmp_path):
    """후보가 전부 needs_action 이면 "선택하세요"는 이행 불가능한 지시다(#302 리뷰 P2)
    — 게이트는 available 존재로만 선택을 권하고, 없으면 없다고 말한다.

    U4-C 뒤 이 상태의 뜻이 좁아졌다(#932): 후보 축이 결속이라 「확인 필요」는 **이 데이터에
    연결돼 있는데 쓰던 열이 사라진** 작업이다. 결속되지 않은 작업은 확인 필요가 아니라
    애초에 이 데이터의 후보가 아니다 — 그래서 표본을 「같은 파일에 결속 + 열 불일치」로
    세운다. 이 갈래가 사라지지 않는 이유가 곧 호환 판정을 남긴 이유다(열은 실제로 사라진다).
    """
    ctrl, _ = _controller(tmp_path)
    csv = tmp_path / "other.csv"
    csv.write_text("엉뚱한열" + chr(10) + "값" + chr(10), encoding="utf-8")
    bound_elsewhere = ctrl.registry.load("공고서")
    ctrl.registry.save(                                 # 결속만 이 파일로 옮긴다
        replace(bound_elsewhere, **_bound_to(str(csv))), allow_overwrite=True,
    )
    ctrl.load_data_path(str(csv))                       # '공고서' 필수 소스가 없는 데이터
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})
    snap = ctrl.snapshot()
    cands = snap["candidates"]
    assert cands["top"] == [] and cands["needs_count"] == 1        # 수치로 남는다
    # 확인 필요 **목록**은 문서 탐색 탭이 소유한다(슬라이스 3 이사).
    ctrl.dispatch("browse_tab", {"tab": "needs_action"})
    assert [r["name"] for r in ctrl.snapshot()["browse"]["rows"]] == ["공고서"]
    assert "연결된 문서 작업이 없습니다" in snap["gate"]["text"]


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
        engine=make_hwpx_engine(),
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
               sources=("bidNtceNm", "presmptPrce"), bound: bool = True) -> None:
    """같은 템플릿을 쓰는 추가 hwpx 작업 저장(순위 표본용).

    기본은 **기준 작업과 같은 데이터에 결속**이다(#932 U4-C): 후보 축이 결속 역인덱스라
    결속 없는 표본은 순위에 아예 서지 않아 순위·추천·즐겨찾기 테스트가 빈 목록을 잰다.
    결속을 base 에서 물려받는 이유는 자리를 두 곳에 적지 않기 위해서다. ``bound=False`` 는
    「다른 데이터에 결속된 작업은 이 데이터의 후보가 아니다」를 겨누는 테스트의 것이다.
    """
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
        **(_bound_to(base.data_path, base.data_sheet, base.data_header_row)
           if bound else {}),
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
    _mount_all(ctrl, str(csv))
    # DataTarget 전환은 호환되지 않는 active Work를 RELEASE한다(#760). 이 테스트가 재는
    # 것은 파일명 source 역해소이므로, 데이터 뒤 사용자가 Work를 명시 선택한다.
    ctrl.dispatch("select_job", {"name": "공고서"})
    # text·present 인 공고명(→bidNtceNm)만 나르는 열. const·blank·부재 source 는 배제.
    assert ctrl._filename_source_columns() == ["bidNtceNm"]


# ---------------------------------------------------------------- 게이트·생성(링1 계약)
def test_blank_values_are_announced_but_do_not_block_generation(tmp_path):
    """#957 — 빈 값은 **알리되 막지 않는다**(U4 §34 「게이트 유지 확정」의 명시적 뒤집기).

    구 blank_set 게이트의 자리다: 종전에는 승인해야 생성이 열렸고, 이제는 사전검증이
    어느 필드가 비었는지 지목한 채 생성이 그대로 열린다 — 확인은 결과 문서에서 한다.
    빈 값이 조용히 새지 않는 근거는 승인이 아니라 문서에 박히는 표식이다.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    out = tmp_path / "out"
    pick_output_folder(ctrl, out)

    snap = ctrl.snapshot()
    assert snap["gate"]["enabled"] is True and snap["gate"]["reason"] == ""
    assert "[경고] 빈 값 필드" in snap["preflight"]["text"]
    assert "추정가격" in snap["preflight"]["text"]           # 어느 필드인지 지목한다

    res = ctrl.generate()
    assert res["ok"] is True and res["succeeded"] == 2
    assert "빈 값 표시 필드 1개(추정가격)." in res["summary"]
    made = sorted(p.name for p in out.glob("*.hwpx"))
    assert made == ["doc-001.hwpx", "doc-002.hwpx"]


def test_generate_writes_documents_and_marks_missing(tmp_path):
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    out = tmp_path / "out"
    pick_output_folder(ctrl, out)

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
    pick_output_folder(ctrl, tmp_path / "out")

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


def test_generation_stamps_last_run_at(tmp_path, monkeypatch):
    """완주 = 역사(#129) — 영속된 최신 Job 전체가 세션 사본도 갱신한다."""
    ctrl, _ = _controller(tmp_path)
    stamped_jobs = []
    stamp_last_run = ctrl.registry.stamp_last_run

    def capture_stamp(*args, **kwargs):
        stamped_jobs.append(stamp_last_run(*args, **kwargs))
        return stamped_jobs[-1]

    monkeypatch.setattr(ctrl.registry, "stamp_last_run", capture_stamp)
    assert ctrl.registry.load("공고서").last_run_at == ""      # 선조건: 미실행
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    pick_output_folder(ctrl, tmp_path / "out")

    res = ctrl.generate()
    assert res["ok"] is True and res["level"] == "ok"
    stamped = ctrl.registry.load("공고서").last_run_at
    # 소비처(home_state·screen_library)가 fromisoformat 파싱 + 원시 문자열 정렬로 쓴다.
    assert datetime.fromisoformat(stamped)
    assert len(stamped) == len("2026-07-21T09:00:00")           # 초 단위 고정폭 = 정렬 가능
    assert ctrl.vm.job is stamped_jobs[0]                       # 필드 목록 없이 최신 사본 전체 승계


def test_generation_stamp_does_not_clobber_disk_edits(tmp_path, monkeypatch):
    """생성 중 최신 규칙을 보존하되 옛 규칙의 완주 증거는 버린다."""
    import hwpxfiller.application.generation as appgen

    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("toggle_record", {"index": 0, "value": True})
    pick_output_folder(ctrl, tmp_path / "out")
    assert ctrl.snapshot()["guard"]["armed"] is True

    generate_batch = appgen.generate_batch

    def edit_midflight(*args, **kwargs):
        edited = ctrl.registry.load("공고서")
        edited.filename_pattern = "edited-{{seq:001}}"
        ctrl.registry.save(edited, allow_overwrite=True)
        return generate_batch(*args, **kwargs)

    monkeypatch.setattr(appgen, "generate_batch", edit_midflight)

    assert ctrl.generate()["ok"] is True
    after = ctrl.registry.load("공고서")
    assert after.filename_pattern == "edited-{{seq:001}}"       # 디스크 편집 보존
    assert after.last_run_at != ""                              # 그리고 스탬프도 남는다
    assert ctrl.vm.job.filename_pattern == after.filename_pattern  # 최신 Job 전체 승계
    assert ctrl._last_generated is None                          # 새 규칙은 실행되지 않았다
    assert ctrl.snapshot()["guard"]["armed"] is True             # 수작업 선택 보호 복구


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
    pick_output_folder(ctrl, tmp_path / "out")

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
    pick_output_folder(ctrl, tmp_path / "out")

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
    pick_output_folder(ctrl, out)

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
    pick_output_folder(ctrl, tmp_path / "out")

    assert ctrl.generate()["failed"] == 1
    assert ctrl.registry.load("공고서").last_run_at == ""       # 미완주 = 역사 없음


def test_overwrite_confirm_flow(tmp_path):
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    pick_output_folder(ctrl, tmp_path / "out")
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
    pick_output_folder(ctrl, tmp_path / "out")

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
    pick_output_folder(ctrl, tmp_path / "out")

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
    pick_output_folder(ctrl, tmp_path / "out")

    assert ctrl.generate(run_token="run-9")["ok"] is True
    assert ctrl._run is None


def test_progress_delta_carries_the_run_token(tmp_path):
    """진행 델타는 direct 반환과 다른 채널이라 payload 안에 주인이 있어야 한다."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    pick_output_folder(ctrl, tmp_path / "out")
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
        pick_output_folder(ctrl, home / "out")
        res = ctrl.generate() if token is None else ctrl.generate(run_token=token)
        assert res["ok"] is True
        assert res["run_token"] == expected


# ---------------------------------------------- 위험 배너·빈 값 표식의 재료
def _mirror_job(tmp_path) -> JobRegistry:
    """빈 값·드리프트 케이스용 작업 — 채움(text)·미입력(amount, rec0 빈값)·의도적 빈칸 3필드."""
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
    """표식이 붙는 필드 집합 — 빈 값 필드 **이름**만 싣는다: 값 집계(표본·행수 재진술)는
    표와 함께 죽었고, 의도적 빈칸(blank 선언)은 빈 값이 아니다(매핑이 키를 제외한다).

    화면은 이 사실을 사전검증 문안으로 읽지만(존 재편에서 요약 한 줄이 걷혔다), 이 축은
    **생성 입력**의 관측면이다 — 여기 든 이름이 곧 문서에 〘미입력·필드명〙 표식이 붙는
    자리이고, 그래서 표시와 생성이 한 술어를 공유하는지 여기서 잰다."""
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
    # 빈 값 축은 건강하다 — 이 danger 를 말할 표면은 배너 하나뿐이라는 뜻이다(신호 소실 방지).
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
    pick_output_folder(ctrl, tmp_path / "out")
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
from hwpxfiller.external.template_inspection import template_compile_status


def _pool_controller(
    tmp_path,
    *,
    pool_source_factory=source_from_pool_item,
    file_source_factory=source_for_path,
    registry=None,
    template_change=None,
):
    pool = DatasetPoolRegistry(tmp_path / "pool")
    pushes: list = []
    ctrl = JobController(
        registry or _registry(tmp_path), lambda s, snap: pushes.append((s, snap)),
        clock=_clock(),
        existing_outputs=existing_output_paths,
        ensure_output_dir=ensure_output_directory,
        engine=make_hwpx_engine(),
        pool_registry=pool,
        generation_lock=threading.Lock(),
        file_source_factory=file_source_factory,
        pool_source_factory=pool_source_factory,
        template_change=template_change,
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
    assert ref == {"path": str(xlsx), "sheet": "발주", "header_row": 2, "kind": ""}

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
# --------------------- 결속 없는 작업의 실행 차단·복구 동사(U4 §2.4 · #932 U4-C)
def test_an_unbound_job_cannot_generate_and_says_where_to_fix_it(tmp_path):
    """결속이 「필수」라면 실행 게이트도 그것을 요구한다.

    저장 게이트만 요구하면 「필수」는 한 자리에서만 참인 말이 되고, 구판 작업은 매 세션
    데이터를 다시 물으면서도 무엇이 잘못됐는지 말하지 않는다. 대신 좌초시키지 않는다 —
    고칠 자리(편집기)를 가리키는 동사가 같은 화면에 함께 선다(`job_data_unbound`).
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.registry.save(
        replace(ctrl.registry.load("공고서"), **_bound_to("")), allow_overwrite=True,
    )
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.dispatch("set_all", {})
    snap = ctrl.snapshot()
    assert snap["gate"]["enabled"] is False
    assert "연결된 데이터가 없습니다" in snap["gate"]["text"]
    # 복구 동사를 그릴 판정은 **여기 하나**다 — 표면이 라벨 유무로 유추하면 세션 마운트가
    # 서 있는 동안 「연결됐다」로 잘못 읽는다(그 둘은 다른 사실이다).
    assert snap["job_data_unbound"] is True
    assert snap["has_data"] is True          # 세션 데이터는 서 있다 — 축이 다르다


def test_a_bound_job_neither_blocks_nor_advertises_the_repair_verb(tmp_path):
    """대조군 — 결속이 있으면 이 축은 조용하다(없는 위험에 동사를 세우지 않는다)."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["job_data_unbound"] is False
    assert "연결된 데이터가 없습니다" not in snap["gate"]["text"]


def test_the_unbound_axis_is_a_work_fact_not_a_session_one(tmp_path):
    """작업을 놓으면 이 축도 함께 없어진다 — 물을 대상 자체가 없다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.registry.save(
        replace(ctrl.registry.load("공고서"), **_bound_to("")), allow_overwrite=True,
    )
    ctrl.dispatch("select_job", {"name": "공고서"})
    assert ctrl.snapshot()["job_data_unbound"] is True
    ctrl.dispatch("select_job", {"name": ""})          # 선택 해제
    assert ctrl.snapshot()["job_data_unbound"] is False


# ------------------------------- 현재 데이터 다시 읽기(U4 항목 5 · #932 U4-C)
def test_remount_reads_the_same_reference_again_and_picks_up_new_rows(tmp_path):
    """「다시 읽기」는 **같은 참조**를 디스크에서 새로 읽는다 — stale 판정이 아니다.

    앱에는 「파일이 바뀌었는가」를 답할 술어가 없다(mtime·해시 추적은 템플릿 축뿐).
    그래서 이 동사의 실체는 재마운트이고, 결속이 durable 이 된 뒤(§2.4) 같은 파일이
    갱신되는 것이 흔한 사건이 되므로 짝이 된다.
    """
    ctrl, _ = _controller(tmp_path)
    csv = Path(_data_csv(tmp_path))
    ctrl.load_data_path(str(csv))
    assert len(ctrl.records) == 2
    csv.write_text(
        "bidNtceNm,presmptPrce\n전산장비,\n사무비품,2000000\n추가건,3000000\n",
        encoding="utf-8",
    )

    res = ctrl.dispatch("remount_data", {})    # 선택 0건이라 확인 없이 곧바로 돈다
    assert res["ok"] is True and "needs_confirm" not in res
    assert len(ctrl.records) == 3


def test_remount_states_what_it_clears_before_it_clears_it(tmp_path):
    """고른 행이 있으면 **사라지는 집합을 수치로 재진술**한 뒤에만 다시 읽는다.

    재마운트는 마운트와 같은 seam 을 타 선택·필터 초안·열 선별이 초기화된다. 조용히
    지우면 그것이 곧 무확인 파괴다. 확인 없이 온 요청은 **상태를 바꾸지 않고** 확인을
    돌려준다 — 물어 놓고 이미 저지른 왕복은 확인이 아니다.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.dispatch("set_all", {})
    selected = ctrl.snapshot()["selected_count"]
    assert selected == 2

    first = ctrl.dispatch("remount_data", {})
    assert first["needs_confirm"] is True
    assert "2건" in first["confirm_text"]                  # 무엇을 잃는지 수치로
    assert ctrl.snapshot()["selected_count"] == 2         # 아직 아무것도 안 지웠다

    ctrl.dispatch("remount_data", {"confirm": True})
    assert ctrl.snapshot()["selected_count"] == 0         # 마운트와 같은 초기화


def test_remount_without_a_mount_is_refused_loudly(tmp_path):
    """다시 읽을 것이 없으면 조용한 무동작이 아니라 사유다."""
    ctrl, _ = _controller(tmp_path)
    res = ctrl.dispatch("remount_data", {})
    assert res["ok"] is False and "데이터를 먼저 고르세요" in res["error"]


def test_select_job_does_not_mount_any_data(tmp_path):
    """작업 선택은 데이터를 세우지 않는다 — 구 기본 데이터셋 자동 조준(#53-A)은 폐기됐다.

    구 JSON 이 default_dataset_ref 를 들고 있고 동명 풀 항목이 실재해도, 선택은 결속을
    읽지 않는다(마이그레이션이 아니라 폐기 — 데이터↔작업 결속은 어느 방향으로도 다시
    들이지 않는다).

    이 테스트가 재는 축은 결속(#932 U4-C)이 아니라 폐기된 legacy 키다 — 그래서 픽스처
    기본값의 결속(`_bound_to`)을 지워 「결속 없음」 상태로 되돌린 뒤 legacy 키만 얹는다.
    결속이 남아 있으면 `_mount_job_binding` 이 그 결속으로 마운트를 시도해 이 테스트가
    실제로 재려는 것(legacy 키 무시)과 무관하게 실패한다.

    결속이 **없다**는 사실 자체는 조용히 넘기지 않는다(#932 U4-C 마이그레이션) — 구
    legacy 키는 무시하되, 화면은 「이 작업에는 연결된 데이터가 없다」고 말하고 고치는
    자리(편집기)를 가리킨다. 침묵하면 사용자는 자기 작업이 왜 매번 데이터를 다시 묻는지
    영영 모른다.
    """
    import json as _json

    ctrl, pool = _pool_controller(tmp_path)
    _pool_add(pool, "7월공고", {"path": _data_csv(tmp_path)})
    ctrl.registry.save(
        replace(ctrl.registry.load("공고서"), **_bound_to("")), allow_overwrite=True,
    )
    path = ctrl.registry.path_for("공고서")
    payload = _json.loads(path.read_text(encoding="utf-8"))
    payload["default_dataset_ref"] = "7월공고"          # 구버전이 남긴 결속 키
    path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()
    assert snap["has_job"] is True
    assert snap["has_data"] is False                    # 자동 마운트 없음
    assert snap["data_source_label"] == ""
    # 구 키로 조준하지는 않되, 결속 부재는 사유로 말한다(조용한 빈 상태 금지).
    assert "7월공고" not in (snap["data_notice"] or {}).get("text", "")
    assert "연결된 데이터가 없습니다" in snap["data_notice"]["text"]
    assert snap["data_notice"]["level"] == "warn"


def test_dismiss_data_notice_clears_the_channel(tmp_path):
    """수동 소멸 통지에는 닫는 동사가 있다(U4 §2.12 · #945 F4).

    `data_notice` 는 매 변이 자동 소멸이 아니라 사유가 해소될 때까지 남는 채널인데,
    끄는 전이가 없어서 사용자가 읽고 이해한 뒤에도 화면 위에 영구히 남았다(#874
    `saveMessage`·#933 편집기 `notice` 와 같은 결함류). 세우는 전이는 그대로 두고 끄는
    문만 연다 — 사유가 다시 서면 같은 트리거가 통지도 다시 세운다.
    """
    ctrl, _pool = _pool_controller(tmp_path)
    ctrl.registry.save(
        replace(ctrl.registry.load("공고서"), **_bound_to("")), allow_overwrite=True,
    )
    ctrl.dispatch("select_job", {"name": "공고서"})
    assert "연결된 데이터가 없습니다" in ctrl.snapshot()["data_notice"]["text"]

    pushes: list = []
    ctrl._push_sink = lambda _screen, snapshot: pushes.append(snapshot)
    assert ctrl.dispatch("dismiss_data_notice", {}) is None

    # 스냅샷에서 사라지고(세션 상태), 그 사실이 push 로 화면까지 간다.
    assert ctrl.snapshot()["data_notice"] is None
    assert pushes and pushes[-1]["data_notice"] is None
    # 닫기는 통지 채널만 만진다 — 작업 선택·데이터 상태는 그대로다.
    assert ctrl.job_name == "공고서"


def test_mounted_session_data_survives_job_selection(tmp_path):
    """세션 소유 마운트 데이터는 작업 선택에서 생존한다(§18.2) — §5.3 완화 ⑴의 근거.

    재려는 것은 결속 축이 아니라 「선택이 세션 마운트를 밀어내지 않는다」다(#932 U4-C
    이후에도 유효). 그래서 「공고서」를 **지금 마운트할 데이터**에 결속시켜, 선택이
    `_mount_job_binding` 의 "이미 그 데이터가 서 있음" 분기(무변화)를 타게 한다 — 다른
    결속이면 선택이 재마운트를 시도해 이 테스트가 재려는 생존 여부를 가린다.
    """
    ctrl, _pool = _pool_controller(tmp_path)
    other = tmp_path / "직접.csv"
    other.write_text("bidNtceNm,presmptPrce\n수동데이터,900\n", encoding="utf-8")
    ctrl.registry.save(
        replace(ctrl.registry.load("공고서"), **_bound_to(str(other))), allow_overwrite=True,
    )
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
    stale 사본을 돌려주는 load 로 그 창을 재현해, 커밋의 재판정이 같은 문안으로 거절하고
    durable 이 불변임을 가드한다. 재판정의 거처는 P2-99(#542 F-1)에서 링2 콜백이 아니라
    포트의 semantic atomic op(``relink_template``)으로 옮겼다 — 재현 창과 판정 결과는 같다.
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

        def relink_template(self, name, path):
            return self._real.relink_template(name, path)

    txt = tmp_path / "경합.txt"
    txt.write_text("공고: {{공고명}}", encoding="utf-8")
    res = relink_job_template(
        _StaleLoad(ctrl.registry, stale), "경합작업", str(txt),
        engine=make_hwpx_engine(), confirm=True)
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


def test_overwrite_confirm_roundtrip_pins_the_timestamp(tmp_path):
    """덮어쓰기 확인 왕복은 **한 시각**으로 판정하고 생성한다(#957 delta 2).

    `{{date:SS}}` 류에서 확인창이 재진술한 파괴 집합과 실제 파괴 집합이 초 경계에서 갈리면
    확인창이 거짓이 된다. 그래서 `needs_overwrite` 를 낸 판정이 쓴 시각을 핀으로 남기고
    확인 재호출이 **소비하며 소거**한다. 표시(스냅샷)와 실행(런 진입)이 각자 시각을 찍는
    것은 정상이다 — 확인의 자리가 만들어진 문서로 옮겨졌기 때문이다.
    """
    ctrl, _ = _controller(tmp_path)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "doc-{{date:HHmmSS}}-{{seq}}"
    ctrl.registry.save(job, allow_overwrite=True)
    _rereview(ctrl)   # 파일명 규칙 변경의 검토 고지는 이 테스트의 대상이 아니다
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    out = tmp_path / "out"
    pick_output_folder(ctrl, out)

    # 시계를 손에 쥔다 — 왕복 사이의 초 경계를 결정적으로 넘겨야 핀이 관측 가능해진다.
    t1 = datetime(2026, 7, 21, 9, 0, 0)
    ctrl._clock = lambda: t1
    assert ctrl.generate()["ok"] is True
    first = sorted(p.name for p in out.glob("*.hwpx"))
    assert first == ["doc-090000-1.hwpx", "doc-090000-2.hwpx"]
    assert ctrl._overwrite_now_pin is None   # 파괴 없는 첫 실행은 핀을 세우지 않는다

    # 같은 시각·같은 폴더로 다시 — 파괴 집합이 서므로 확인 왕복이 열린다.
    asked = ctrl.generate()
    assert asked["needs_overwrite"] is True
    assert asked["total"] == 2 and asked["overwrite_count"] == 2 and asked["new_count"] == 0
    assert sorted(asked["conflict_names"]) == first and asked["conflict_more"] == 0
    assert ctrl._overwrite_now_pin is not None

    # 확인 재호출 **직전에 초 경계를 넘긴다**. 핀이 없으면 재호출은 새 시각으로 계획해
    # 아무것도 덮지 않고 새 파일 2건을 더 만든다 — 확인창이 거짓말이 되는 바로 그 자리다.
    ctrl._clock = lambda: datetime(2026, 7, 21, 9, 0, 30)
    ctrl.snapshot()                                    # 사이에 낀 임의 재렌더(표시 축은 새 시각)
    assert ctrl.generate(confirm_overwrite=True)["ok"] is True
    assert sorted(p.name for p in out.glob("*.hwpx")) == first, (
        "확인 재호출이 재진술한 집합과 다른 이름을 만들었습니다."
    )
    assert ctrl._overwrite_now_pin is None              # 소비했으면 놓는다


def test_the_overwrite_pin_is_dropped_when_the_zone_changes_between_the_roundtrip(tmp_path):
    """왕복 사이에 실행 입력이 바뀌면 그 핀은 **다른 세계의 것**이라 버린다(#957).

    되쓰면 사용자가 본 적 없는 이름을 만든다 — 확인창이 말한 집합과 실제 집합이 갈리는
    바로 그 결함류를 반대 방향으로 되살리는 꼴이다.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    out = tmp_path / "out"
    pick_output_folder(ctrl, out)
    assert ctrl.generate()["ok"] is True
    assert ctrl.generate()["needs_overwrite"] is True
    assert ctrl._overwrite_now_pin is not None

    ctrl.dispatch("toggle_record", {"index": 0, "value": False})   # 존 변이 — 선택이 갈렸다
    refused = ctrl.generate(confirm_overwrite=True)

    assert refused["ok"] is False and "needs_overwrite" not in refused
    assert "다시 받아야" in refused["error"] and refused["level"] == "warn"
    assert ctrl._overwrite_now_pin is None, "낡은 세계의 시각이 살아남았습니다."
    # 새 배치로 다시 물으면 왕복이 정상적으로 다시 열린다(막다른 거절이 아니다).
    assert ctrl.generate()["needs_overwrite"] is True


def test_the_display_timestamp_is_captured_once_per_snapshot(tmp_path):
    """표시 시각은 **스냅샷당 1회** 캡처다 — 한 스냅샷의 소비처가 서로 맞는다(#957).

    반대 방향도 함께 잰다: 스냅샷을 다시 그리면 새로 찍는다(오래 열어 둔 세션의 날짜가
    늙지 않게). 종전의 「보는 동안 얼린다」 규칙은 그 값에 기대던 확인 면과 함께 죽었다.
    """
    ctrl, _ = _controller(tmp_path)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "doc-{{date:HHmmSS}}-{{seq}}"
    ctrl.registry.save(job, allow_overwrite=True)
    _rereview(ctrl)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))

    ctrl._clock = lambda: datetime(2026, 7, 21, 9, 0, 0)
    snap = ctrl.snapshot()
    assert ctrl._names_now == datetime(2026, 7, 21, 9, 0, 0)
    # 한 스냅샷 안: 표 「문서」 열의 이름이 그 시각으로 계획된다(캡처가 1회라 서로 맞는다).
    assert [r["name"] for r in snap["records"]] == ["doc-090000-1.hwpx", "doc-090000-2.hwpx"]

    ctrl._names_now = datetime(2020, 1, 1)       # 늙은 값을 심는다
    ctrl.snapshot()
    assert ctrl._names_now != datetime(2020, 1, 1)


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


# (test_restate_origin_by_set_comparison 삭제 — 선택 유래 재진술 축(`restate`)은 그것을
#  그리던 인라인 블록과 함께 퇴역했다. 같은 수치(`in_def`·`extra`)를 파괴 확인 모달이
#  계속 쓰고, 그 축의 판정은 세션 가드(`guard`) 테스트가 진다.)


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
    pick_output_folder(ctrl, out)
    ctrl.dispatch("hide_column", {"column": "presmptPrce"})
    res = ctrl.generate()
    assert res["ok"] is True and res["succeeded"] == 2
    sections = [
        read_hwpx_package(p).entries["Contents/section0.xml"]
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
    """무장 술어(결정 27) — 전체/빈/정의-유래/완주 집합은 비무장, 수작업 열거만 무장.

    재는 축은 선택 집합 대 정의 비교이지 결속(#932 U4-C)이 아니다 — `_unbind` 로 결속을
    비워 `_data_csv3` 로의 마운트가 재선택 되튐 없이 그대로 서게 한다.
    """
    ctrl, _ = _session(tmp_path)
    _unbind(ctrl)
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
    """완료 이벤트 = 무장 해제(결정 27) — 내역은 완료 존이 담보. 재편집 시 재무장.

    재는 축은 완료 여부이지 결속(#932 U4-C)이 아니다 — `_unbind` 로 재선택 되튐을 끈다
    (`test_guard_armed_by_set_comparison` 과 같은 사유).
    """
    ctrl, _ = _session(tmp_path)
    _unbind(ctrl)
    _mount_all(ctrl, _data_csv3(tmp_path))
    pick_output_folder(ctrl, tmp_path / "out")
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
    pick_output_folder(ctrl, tmp_path / "out")
    ctrl.dispatch("set_none", {})
    ctrl.dispatch("toggle_record", {"index": 1, "value": True})  # 수작업 1행
    res = ctrl.generate()
    assert res["ok"] is True and res["failed"] == 1
    assert ctrl.dispatch("guard_state", {})["armed"] is True     # 무장 유지(재시도 보호)


# ------------------------------------------- 건 연속성(직전 필터 재적용, 결정 28)
def test_reapply_slot_written_on_session_death_and_source_gated(tmp_path):
    """슬롯 = 정의 가진 세션이 죽을 때 덮어씀 · 소스 일치 게이트(다른 소스엔 미제공).

    재는 축은 소스 키 비교이지 결속(#932 U4-C)이 아니다 — 결속이 있으면 d3.csv 로의
    마운트가 RELEASE 를 태우고 `_mount_all` 의 재선택이 `_mount_job_binding` 으로 d.csv
    로 조용히 되튀어(결속이 그 경로다), 방금 세운 d3.csv 소스가 사라진다. `_unbind` 로
    그 되튐을 끄고 이 테스트가 실제로 재는 소스 키 게이트만 남긴다.
    """
    ctrl, _ = _session(tmp_path)
    _unbind(ctrl)
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

    재는 축은 힌트 문안이지 결속(#932 U4-C)이 아니다 — `_unbind` 로 재선택 되튐을 끈다
    (`test_reapply_slot_written_on_session_death_and_source_gated` 와 같은 사유).
    """
    ctrl, _ = _session(tmp_path)
    _unbind(ctrl)
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
    """가지 소실 시 프루닝 복원 포기(리뷰 #2) — 거짓 「매치 없음」 빈 화면을 만들지 않는다.

    재는 축은 프루닝 포기 로직이지 결속(#932 U4-C)이 아니다 — 결속이 있으면 both.csv 로의
    반복 마운트마다 재선택이 `_mount_job_binding` 을 태워 그 작업의 결속 데이터(d.csv)로
    되튀어, 이 테스트가 both.csv 위에서 쌓아 올린 필터·프루닝 슬롯을 지운다. `_unbind` 로
    끈다.
    """
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _unbind(ctrl)
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
        target=lambda: relink_job_template(
            reg, "공고서", str(new_template), engine=make_hwpx_engine(), confirm=True
        )
    )
    linker.start()
    release.set()
    stamper.join(3)
    linker.join(3)

    saved = reg.load("공고서")
    assert saved.last_run_at == "2026-07-21T09:00:00"
    assert saved.template_path == str(new_template)


def test_describe_fill_note_names_field_and_kinds():
    """완화 노트 문안(#154) — 필드·제거 종류를 명명하고 미지 종류는 원문 관통."""
    from hwpxfiller.domain.fields import FillNote
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
        "<hp:run><hp:t>{{공고명}}<hp:markpenBegin/>X<hp:markpenEnd/></hp:t></hp:run>"
        '<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>'
        '<hp:run><hp:ctrl><hp:fieldBegin name="추정가격"/></hp:ctrl></hp:run>'
        "<hp:run><hp:t>{{추정가격}}</hp:t></hp:run>"
        '<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>'
        "</hp:p></hs:sec>"
    ).encode()
    write_hwpx_package(
        tmp_path / "t.hwpx",
        HwpxPackage(entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": sec}),
    )

    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    pick_output_folder(ctrl, tmp_path / "out")

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


@pytest.mark.parametrize("target", ["file", "pool"])
@pytest.mark.parametrize(
    (
        "case",
        "active_name",
        "expected_name",
        "restorable",
        "usable",
        "expected_application_ref",
        "notice",
    ),
    [
        ("compatible", "공고서", "공고서", True, True, None, None),
        (
            # #932 U4-C: 판정 축이 스키마 호환에서 결속으로 갈렸다 — 예전 "incompatible"
            # (이 데이터로 못 도는 매핑)이 아니라 "다른 데이터에 결속돼 있다"를 잰다.
            "bound_elsewhere",
            "계약서",
            "",
            True,
            False,
            None,
            "다른 데이터에 연결돼 있어",
        ),
        (
            "same_name_recreated",
            "공고서",
            "",
            False,
            True,
            None,
            "같은 작업인지 확인할 수 없어",
        ),
        (
            "authority_changed",
            "공고서",
            "",
            False,
            True,
            None,
            "같은 작업인지 확인할 수 없어",
        ),
        (
            "rules_changed",
            "공고서",
            "",
            False,
            True,
            None,
            "같은 작업인지 확인할 수 없어",
        ),
        (
            "revision_changed",
            "공고서",
            "",
            False,
            True,
            None,
            "같은 작업인지 확인할 수 없어",
        ),
        (
            "reload_error",
            "공고서",
            "",
            False,
            False,
            None,
            "다시 확인할 수 없어",
        ),
        (
            "identity_missing",
            "공고서",
            "",
            False,
            True,
            None,
            "같은 작업인지 확인할 수 없어",
        ),
        (
            "application_missing",
            "공고서",
            "",
            False,
            True,
            None,
            "다시 확인할 수 없어",
        ),
    ],
)
def test_successful_data_transition_uses_authoritative_active_work_decision(
    tmp_path,
    monkeypatch,
    target,
    case,
    active_name,
    expected_name,
    restorable,
    usable,
    expected_application_ref,
    notice,
):
    """file/pool 성공 전환은 exact authority KEEP/RELEASE와 같은 무효화 seam을 탄다."""
    registry = _incompatible_reg(tmp_path) if case == "bound_elsewhere" else _registry(tmp_path)
    if case != "identity_missing":
        registry.assign_authority_id(active_name, "authority-old")
    coordinator = (
        TemplateChangeCoordinator(
            registry, root=tmp_path / "authority", clock=_clock()
        )
        if case == "application_missing"
        else None
    )
    ctrl, pool = _pool_controller(
        tmp_path, registry=registry, template_change=coordinator
    )
    # 셋업 국면의 겨눔 경로(#932 U4-C) — "bound_elsewhere" 만 별도 파일(old.csv)에
    # 결속시켜 뒤의 관측 전환에서 결속이 어긋나게 **남긴다**(그 어긋남 자체가 그 케이스가
    # 재는 것). 나머지는 active_name 의 **기본 결속 경로**(`_data_csv_path` — `_registry`
    # 가 이미 묶어 둔 자리)에 그대로 "옛" 내용을 써서 겨눈다: 마운트 경로를 결속과 다르게
    # 두면(구판처럼 old.csv 를 따로 쓰면) 셋업 마운트마다 결속 밖 데이터로 읽혀 진짜(아직
    # monkeypatch 전) RELEASE 가 셋업 단계에서부터 터져 「관측된 전환 1건」·work_ref 단언이
    # 애초에 성립하지 않는다. 같은 경로 재읽기는 `test_data_mount_identity_changes_on_every_remount`
    # 가 이미 검증한 "같은 소스·바뀐 내용도 새 전환" 결의 시나리오라 결속은 그대로 두고
    # 내용만 바뀐 전환을 재현한다 — `data_path` 를 select 뒤에 다시 쓰면 그 자체가
    # `content_fingerprint` 에 실려(U4 §2.4) "외부에서 결속이 바뀐 작업"으로 오판돼
    # restorable 케이스들의 판정을 오염시키므로, 결속은 select **전**에 한 번만 정한다.
    old_path = (
        Path(tmp_path / "old.csv") if case == "bound_elsewhere"
        else Path(_data_csv_path(tmp_path))
    )
    old_path.write_text(
        "bidNtceNm,presmptPrce,없는열\n이전,100,old\n", encoding="utf-8"
    )
    if case == "bound_elsewhere":
        ctrl.registry.mutate(active_name, lambda job: setattr(job, "data_path", str(old_path)))
    if case in {"identity_missing", "application_missing"}:
        ctrl.load_data_path(str(old_path))
        ctrl.dispatch("select_job", {"name": active_name})
        if case == "application_missing":
            # 착석이 준비를 지게 된 뒤로(#932 B5) 선택 자체가 권위를 세운다. 이 케이스가 재는
            # 것은 「착석한 Work 의 Application 을 전환 시점에 다시 확인할 수 없다」는 상태라,
            # 착석 **다음**에 권위 저장소를 지워 그 상태를 만든다 — 선택 전에 비워 두면 자동
            # 준비가 도로 세워 이 축이 영영 안 재진다.
            shutil.rmtree(tmp_path / "authority")
    else:
        ctrl.dispatch("select_job", {"name": active_name})
        ctrl.load_data_path(str(old_path))
    ctrl.dispatch("set_all", {})
    picked_folder = pick_output_folder(ctrl, tmp_path / "managed-out")
    if case == "same_name_recreated":
        replacement = ctrl.registry.load(active_name)
        ctrl.registry.delete(active_name)
        replacement.authority_id = "authority-replacement"
        ctrl.registry.save(replacement)
    elif case == "authority_changed":
        ctrl.registry.mutate(
            active_name,
            lambda job: setattr(job, "authority_id", "authority-replacement"),
        )
    elif case == "rules_changed":
        ctrl.registry.mutate(
            active_name,
            lambda job: setattr(job, "filename_pattern", "새규칙-{{seq:001}}"),
        )
    elif case == "revision_changed":
        original = ctrl.registry.load(active_name).filename_pattern
        ctrl.registry.mutate(
            active_name,
            lambda job: setattr(job, "filename_pattern", "임시규칙-{{seq:001}}"),
        )
        ctrl.registry.mutate(
            active_name,
            lambda job: setattr(job, "filename_pattern", original),
        )

    old_records = ctrl.records
    old_observation = object()
    ctrl._last_fresh_observation = old_observation
    ctrl._current_record_preparation = object()
    ctrl._current_delivery_preparation = object()
    old_generation = ctrl._snapshot_gen
    calls = []
    decide = screen_job_module.decide_active_work_after_data_transition

    def recording_decision(context):
        calls.append(context)
        return decide(context)

    monkeypatch.setattr(
        screen_job_module, "decide_active_work_after_data_transition", recording_decision
    )
    if case == "reload_error":
        def fail_active_work_reload(store, name):
            raise ValueError("internal registry detail")

        monkeypatch.setattr(screen_job_module, "load_job", fail_active_work_reload)
    # "bound_elsewhere" 를 제외한 모든 케이스는 old_path 가 이미 active_name 의 기본
    # 결속 경로(`_data_csv_path`) 였다 — `_data_csv` 가 **같은 자리**에 새 내용을 덮어써
    # 결속은 그대로 둔 채 관측 전환만 새로 세운다(usable=True 를 결속 정직하게 재현).
    # "bound_elsewhere" 는 old_path(별도 파일)에 묶인 채 두어 new_path 와 계속 어긋난다.
    new_path = _data_csv(tmp_path)
    if target == "file":
        ctrl.load_data_path(new_path)
    else:
        key = _pool_add(pool, "새 데이터", {"path": new_path})
        assert ctrl.dispatch("load_pool", {"key": key})["ok"] is True

    assert len(calls) == 1
    assert calls[0].work_ref == active_name
    assert calls[0].template_application_ref == expected_application_ref
    assert calls[0].exact_context_restorable is restorable
    assert calls[0].bound_to_current_data is usable
    assert ctrl.job_name == expected_name
    assert ctrl.records is not old_records
    assert ctrl._snapshot_gen == old_generation + 1
    assert ctrl._current_record_preparation is None
    assert ctrl._current_delivery_preparation is None
    assert ctrl._last_fresh_observation is (old_observation if expected_name else None)
    # 저장 폴더는 **전역 설정**이라 작업이 풀려도 산다(전역화) — 종전 이 자리는 session-scoped
    # 명시 지정이 작업과 함께 죽는 것을 쟀고, 그 축 자체가 사라졌다.
    assert ctrl.out_dir == picked_folder
    snap = ctrl.snapshot()
    if notice is None:
        assert snap["data_notice"] is None
    else:
        assert notice in snap["data_notice"]["text"]
        assert "internal registry detail" not in snap["data_notice"]["text"]
        assert snap["data_notice"]["level"] == "warn"
    if case == "bound_elsewhere":
        assert snap["candidates"]["suggested"] == "공고서"
        assert ctrl.job_name == ""  # 유일 후보도 자동 활성화하지 않는다.


@pytest.mark.parametrize("target", ["file", "pool"])
def test_failed_data_transition_preserves_committed_data_and_work(tmp_path, target):
    """candidate read/load 실패는 commit 전 실패라 기존 session state를 건드리지 않는다."""
    def file_factory(path, *, sheet=None):
        if Path(path).name == "broken.csv":
            raise ValueError("broken file")
        return source_for_path(path, sheet=sheet)

    def pool_factory(item, *, secret_store=None, fetcher=None):
        if item.name == "깨진 데이터":
            raise ValueError("broken pool")
        return source_from_pool_item(item, secret_store=secret_store, fetcher=fetcher)

    ctrl, pool = _pool_controller(
        tmp_path,
        file_source_factory=file_factory,
        pool_source_factory=pool_factory,
    )
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.dispatch("set_all", {})
    observation = object()
    record_preparation = object()
    delivery_preparation = object()
    ctrl._last_fresh_observation = observation
    ctrl._current_record_preparation = record_preparation
    ctrl._current_delivery_preparation = delivery_preparation
    old_source = ctrl.datasource
    old_records = ctrl.records
    old_selection = ctrl.selection
    old_vm = ctrl.vm
    old_generation = ctrl._snapshot_gen

    if target == "file":
        with pytest.raises(ValueError, match="broken file"):
            ctrl.load_data_path(str(tmp_path / "broken.csv"))
    else:
        key = _pool_add(pool, "깨진 데이터", {"path": _data_csv(tmp_path)})
        result = ctrl.dispatch("load_pool", {"key": key})
        assert result["ok"] is False and "broken pool" in result["error"]

    assert ctrl.datasource is old_source
    assert ctrl.records is old_records
    assert ctrl.selection is old_selection
    assert ctrl.vm is old_vm
    assert ctrl.job_name == "공고서"
    assert ctrl._snapshot_gen == old_generation
    assert ctrl._last_fresh_observation is observation
    assert ctrl._current_record_preparation is record_preparation
    assert ctrl._current_delivery_preparation is delivery_preparation


@pytest.mark.parametrize("target", ["file", "pool"])
@pytest.mark.parametrize("applied_locally", [False, True])
def test_data_transition_uses_template_application_identity(
    tmp_path, monkeypatch, target, applied_locally,
):
    """명시 apply는 seated로 받고, 관측 밖 Application 교체만 RELEASE한다."""
    registry = _registry(tmp_path)
    coordinator = TemplateChangeCoordinator(
        registry, root=tmp_path / "authority", clock=_clock()
    )
    coordinator.check("공고서", "bootstrap")
    ctrl, pool = _pool_controller(
        tmp_path, registry=registry, template_change=coordinator
    )
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    authority_id = registry.load("공고서").authority_id
    seated_application_id = coordinator.current_template_application_id(authority_id)
    assert seated_application_id == ctrl._seated_template_application_id
    assert ctrl.job_name == "공고서"  # exact application은 KEEP

    template = Path(registry.load("공고서").template_path)
    _write_template(template, ["공고명", "추정가격", "비고"])
    prepared = coordinator.check("공고서", "external-change")["preparation"]
    if applied_locally:
        read_application = coordinator.current_template_application_id

        def fail_post_commit_read(_work_id):
            raise ValueError("post-commit store read failed")

        monkeypatch.setattr(
            coordinator, "current_template_application_id", fail_post_commit_read
        )
        result = ctrl.dispatch(
            "template_apply", {"change_token": prepared["change_token"]}
        )
        monkeypatch.setattr(
            coordinator, "current_template_application_id", read_application
        )
    else:
        result = coordinator.apply("공고서", prepared["change_token"])
    assert result["status"] == "applied"
    restored_application_id = coordinator.current_template_application_id(authority_id)
    assert restored_application_id != seated_application_id

    contexts = []
    decide = screen_job_module.decide_active_work_after_data_transition

    def recording_decision(context):
        contexts.append(context)
        return decide(context)

    monkeypatch.setattr(
        screen_job_module, "decide_active_work_after_data_transition", recording_decision
    )
    new_path = _data_csv(tmp_path)
    if target == "file":
        ctrl.load_data_path(new_path)
    else:
        key = _pool_add(pool, "새 데이터", {"path": new_path})
        assert ctrl.dispatch("load_pool", {"key": key})["ok"] is True

    assert contexts[0].template_application_ref == restored_application_id
    assert contexts[0].exact_context_restorable is applied_locally
    assert contexts[0].bound_to_current_data is True
    assert ctrl.job_name == ("공고서" if applied_locally else "")
    assert ctrl._seated_template_application_id == (
        restored_application_id if applied_locally else None
    )
    notice = ctrl.snapshot()["data_notice"]
    if applied_locally:
        assert notice is None
    else:
        assert "같은 작업인지 확인할 수 없어" in notice["text"]


@pytest.mark.parametrize("target", ["file", "pool"])
def test_lazy_template_bootstrap_refreshes_seated_identity_before_data_transition(
    tmp_path, target,
):
    """Seated 뒤 lazy bootstrap한 authority/Application은 다음 mount에서 KEEP한다."""
    registry = _registry(tmp_path)
    coordinator = TemplateChangeCoordinator(
        registry, root=tmp_path / "authority", clock=_clock()
    )
    ctrl, pool = _pool_controller(
        tmp_path, registry=registry, template_change=coordinator
    )
    ctrl.dispatch("select_job", {"name": "공고서"})
    _unprepared_after_select(ctrl)  # 확인이 최초 채택자인 경로(#932 B5)
    assert ctrl.vm is not None and not ctrl.vm.job.authority_id
    assert ctrl._seated_template_application_id is None

    result = ctrl.dispatch("template_check", {"request_id": "bootstrap"})
    restored = registry.load("공고서")
    assert result["ok"] is True and restored.authority_id
    assert ctrl.vm is not None and ctrl.vm.job.authority_id == restored.authority_id
    assert ctrl._seated_template_application_id == (
        coordinator.current_template_application_id(restored.authority_id)
    )

    new_path = _data_csv(tmp_path)
    if target == "file":
        ctrl.load_data_path(new_path)
    else:
        key = _pool_add(pool, "새 데이터", {"path": new_path})
        assert ctrl.dispatch("load_pool", {"key": key})["ok"] is True
    assert ctrl.job_name == "공고서"
    assert ctrl.snapshot()["data_notice"] is None


@pytest.mark.parametrize("action", ["check", "generate"])
def test_lazy_bootstrap_does_not_adopt_a_changed_same_name_work(
    tmp_path, action,
):
    """Authority 미발급 seat와 registry snapshot이 갈리면 새 identity를 섞지 않는다."""
    registry = _registry(tmp_path)
    coordinator = TemplateChangeCoordinator(
        registry, root=tmp_path / "authority", clock=_clock()
    )
    ctrl, _pool = _pool_controller(
        tmp_path, registry=registry, template_change=coordinator
    )
    pushes: list[dict] = []
    ctrl._push_sink = lambda _screen, snapshot: pushes.append(snapshot)
    ctrl.dispatch("select_job", {"name": "공고서"})
    if action == "generate":
        _mount_all(ctrl, _data_csv(tmp_path))
        pick_output_folder(ctrl, tmp_path / "out")
    registry.mutate(
        "공고서",
        lambda job: setattr(job, "filename_pattern", "교체-{{seq:001}}"),
    )
    _unprepared_after_select(ctrl)  # 채택은 아래 동사가 진다(#932 B5)
    pushes.clear()

    result = (
        ctrl.dispatch("template_check", {"request_id": "replacement"})
        if action == "check"
        else ctrl.generate()
    )

    assert result["ok"] is False and "변경되어 선택을 해제" in result["error"]
    assert registry.load("공고서").authority_id  # 새 registry Work는 bootstrap됨
    assert ctrl.job_name == "" and ctrl.vm is None
    assert ctrl._seated_template_application_id is None
    assert "문서 작업이 변경되어 선택을 해제" in ctrl.snapshot()["data_notice"]["text"]
    if action == "generate":
        assert len(pushes) == 1
        assert pushes[-1]["has_job"] is False and pushes[-1]["job_name"] == ""
        assert pushes[-1] == ctrl.snapshot()


def test_applied_then_advanced_releases_instead_of_adopting_the_later_application(
    tmp_path,
):
    """재전송한 apply가 외부 최신 Application을 seated authority로 승격하지 않는다."""
    registry = _registry(tmp_path)
    coordinator = TemplateChangeCoordinator(
        registry, root=tmp_path / "authority", clock=_clock()
    )
    coordinator.check("공고서", "bootstrap")
    ctrl, _pool = _pool_controller(
        tmp_path, registry=registry, template_change=coordinator
    )
    ctrl.dispatch("select_job", {"name": "공고서"})
    template = Path(registry.load("공고서").template_path)

    _write_template(template, ["공고명", "추정가격", "비고1"])
    first = coordinator.check("공고서", "first")["preparation"]
    assert coordinator.apply("공고서", first["change_token"])["status"] == "applied"
    _write_template(template, ["공고명", "추정가격", "비고2"])
    second = coordinator.check("공고서", "second")["preparation"]
    assert coordinator.apply("공고서", second["change_token"])["status"] == "applied"

    result = ctrl.dispatch(
        "template_apply", {"change_token": first["change_token"]}
    )

    assert result["status"] == "applied_then_advanced"
    assert result["is_current"] is False
    assert ctrl.job_name == "" and ctrl.vm is None
    assert ctrl._seated_template_application_id is None
    assert "다른 변경이 이어져 선택을 해제" in ctrl.snapshot()["data_notice"]["text"]


def test_seating_identity_read_failure_does_not_split_the_active_work(
    tmp_path, monkeypatch,
):
    """Fallible authority 조회는 VM·매체·이름을 교체하기 전에 끝난다."""
    registry = _incompatible_reg(tmp_path)
    registry.assign_authority_id("공고서", "authority-a")
    registry.assign_authority_id("계약서", "authority-b")
    coordinator = TemplateChangeCoordinator(
        registry, root=tmp_path / "authority", clock=_clock()
    )
    ctrl, _ = _pool_controller(
        tmp_path, registry=registry, template_change=coordinator
    )
    ctrl.dispatch("select_job", {"name": "공고서"})
    old_vm = ctrl.vm
    old_seat = (
        ctrl.job_name,
        ctrl.job_is_txt,
        ctrl.job_unsupported,
        ctrl.out_dir,
        ctrl._seated_template_application_id,
    )

    def fail_identity_read(_work_id):
        raise ValueError("authority store broken")

    monkeypatch.setattr(
        coordinator, "current_template_application_id", fail_identity_read
    )
    with pytest.raises(ValueError, match="authority store broken"):
        ctrl.dispatch("select_job", {"name": "계약서"})

    assert ctrl.vm is old_vm
    assert (
        ctrl.job_name,
        ctrl.job_is_txt,
        ctrl.job_unsupported,
        ctrl.out_dir,
        ctrl._seated_template_application_id,
    ) == old_seat


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


def test_prefer_work_stores_then_requires_explicit_selection_after_mount(tmp_path):
    """결속 있는 작업은 무데이터에서도 prefer_work 자체가 즉시 승격이다(#932 U4-C).

    종전 「무데이터 = 항상 보관」은 결속 있는 작업에서 죽었다 — 그 작업이 자기 데이터를
    끌고 오므로 미룰 이유가 없다.

    **결속 없는 구판 작업의 판정 축은 스키마다.** 마이그레이션은 사용자를 가두지 않는다:
    결속이 없는 동안은 종전대로 「지금 데이터와 구조가 맞는가」가 답하고, 구조가 맞지
    않으면 보관 후 안내로 남는다. 결속 축으로 물으면 미결속 작업은 후보에 영영 못 서서
    이 승격이 도달 불가 분기가 되고 구판 작업이 편집기 수리 전까지 좌초한다.

    preferredWorkId 가 DataTarget 전환의 자동 선택 권위가 아니라는 원 취지(사용자가
    직접 고른다)는 구판 작업 축에서 그대로 산다.
    """
    ctrl, _ = _controller(tmp_path)
    _data_csv(tmp_path)  # 결속 경로(d.csv)에 실물을 둔다 — 안 두면 마운트 자체가 실패한다.
    # 결속 있는 작업 — 무데이터에서도 prefer_work 자체가 승격이자 마운트다.
    res = ctrl.dispatch("prefer_work", {"name": "공고서"})
    assert res == {"promoted": True, "name": "공고서"}
    assert ctrl.job_name == "공고서" and ctrl.preferred_work == ""
    assert ctrl.snapshot()["has_data"] is True  # 자기 결속 데이터를 끌고 왔다

    # 결속 없는 구판 작업 + 지금 데이터와 구조 불일치 → 보관 후 안내(활성 불변).
    _extra_job(ctrl, "구판", sources=("없는열A", "없는열B"), bound=False)
    res = ctrl.dispatch("prefer_work", {"name": "구판"})
    assert res == {"stored": True, "reason": "incompatible", "name": "구판"}
    assert ctrl.job_name == "공고서" and ctrl.preferred_work == "구판"  # 활성 작업 불변

    other = tmp_path / "other.csv"
    other.write_text("bidNtceNm,presmptPrce\n다른데이터,1\n", encoding="utf-8")
    ctrl.load_data_path(str(other))
    assert ctrl.preferred_work == ""              # 1회 소비
    snap = ctrl.snapshot()
    # 결속 축 후보에는 영영 서지 않는다 — 그래서 안내도 「아래 후보」가 아니라
    # 「문서 작업」을 가리킨다(없는 자리를 가리키는 지시는 이행 불가능하다).
    assert "구판" not in [row["name"] for row in snap["candidates"]["top"]]
    assert "구판" in snap["data_notice"]["text"]
    assert "구조가 맞지 않습니다" in snap["data_notice"]["text"]
    assert "문서 작업" in snap["data_notice"]["text"]
    assert snap["data_notice"]["level"] == "warn"


def test_preferred_outside_top_reaches_exact_work_through_full_browser(tmp_path):
    """결속 있는 작업은 순위 밖이어도 prefer_work 가 순위와 무관하게 즉시 승격한다(#932 U4-C).

    종전(U4-C 이전)에는 순위 밖 preferred 작업이 데이터 마운트 뒤에도 곧장 승격되지
    않고 라이브러리의 명시 선택으로만 닿았다 — 순위가 유일한 후보 통로였기 때문이다.
    지금은 후보 축이 결속 역인덱스이고(§2.4) prefer_work 는 결속 있는 작업을 순위와
    무관하게 즉시 승격한다 — top-N 밖이라는 사실이 승격 성사에 아무 영향도 주지 않는다는
    것이 이 테스트가 지금 재는 것이다. 라이브러리의 「문서 만들기에서 사용」 행 선택 →
    명시 prefer_work 왕복은 여전히 유효한 사용자 여정이라 함께 남긴다.
    """
    ctrl, _ = _controller(tmp_path)
    for i in range(MAIN_TOP_N + 1):
        _extra_job(ctrl, f"작업{i}", last_run_at=f"2026-07-2{i}T09:00:00")

    ctrl.load_data_path(_data_csv(tmp_path))
    snap = ctrl.snapshot()
    top = [row["name"] for row in snap["candidates"]["top"]]
    ranked = [row.name for row in ctrl._ranked_now()]
    assert top == ranked[:MAIN_TOP_N] == ["작업5", "작업4", "작업3", "작업2", "작업1"]
    assert "공고서" not in top  # 결속은 있지만 순위 밖(§2.4 — 순위는 후보 통로가 아니다)
    assert snap["candidates"]["more"] == len(ranked) - MAIN_TOP_N == 2

    library = LibraryController(
        ctrl.registry, TextTemplateRegistry(tmp_path / "txt"), lambda _s, _snap: None,
        engine=make_hwpx_engine(),
        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
        generation_lock=ctrl._generation_lock,
    )
    library.dispatch("set_query", {"text": "공고서"})
    visible = [
        row for section in library.snapshot()["sections"] for row in section["rows"]
    ]
    assert [row["name"] for row in visible] == ["공고서"]
    library.dispatch("select_work", {"name": "공고서"})
    primary = library.snapshot()["detail"]["primary"]
    assert primary == {"target": "job", "label": "문서 만들기에서 사용", "hint": ""}
    assert ctrl.job_name == ""  # 라이브러리 행 선택은 active authority가 아니다.

    assert ctrl.dispatch("prefer_work", {"name": "공고서"}) == {
        "promoted": True, "name": "공고서",
    }
    assert ctrl.job_name == "공고서"


@pytest.mark.parametrize("target", ["file", "pool"])
def test_preferred_lookup_failure_keeps_the_successful_data_commit_loud(
    tmp_path, monkeypatch, target,
):
    """후보 조회 실패는 성공한 file/pool 마운트를 partial failure로 되돌리지 않는다.

    재는 축은 후보 조회 실패의 격리이지 결속(#932 U4-C)이 아니다 — "공고서"가 결속돼
    있으면 prefer_work 가 즉시 승격해 `preferred_work` 가 애초에 저장되지 않으므로
    (마운트 시점에 재판정할 보관분이 없다) `_unbind` 로 결속을 지워 구판 시나리오를
    재현한다.
    """
    ctrl, pool = _pool_controller(tmp_path)
    _unbind(ctrl)
    ctrl.dispatch("prefer_work", {"name": "공고서"})

    def fail_registry_list(_store):
        raise ValueError("internal candidate detail")

    monkeypatch.setattr(screen_job_module, "list_jobs", fail_registry_list)
    new_path = _data_csv(tmp_path)
    if target == "file":
        ctrl.load_data_path(new_path)
        assert ctrl.data_source == "file" and ctrl.data_label == Path(new_path).name
    else:
        key = _pool_add(pool, "새 데이터", {"path": new_path})
        assert ctrl.dispatch("load_pool", {"key": key}) == {
            "ok": True,
            "label": "등록 데이터: 새 데이터",
        }
        assert ctrl.data_source == "pool" and ctrl.data_pool_key == key

    assert ctrl.records and ctrl.selection.selected_count() == 0
    assert ctrl.preferred_work == ""
    notice = ctrl.snapshot()["data_notice"]
    assert notice["level"] == "warn"
    assert "고른 '공고서' 작업을 다시 확인할 수 없습니다" in notice["text"]
    assert "문서 작업 목록을 다시 확인할 수 없습니다" in notice["text"]
    assert "internal candidate detail" not in notice["text"]


def test_snapshot_registry_warning_composes_and_clears_on_recovery(
    tmp_path, monkeypatch,
):
    """Registry 경고는 기존 notice와 합성하되 복구 뒤 영속하지 않는다."""
    ctrl, _ = _controller(tmp_path)
    list_jobs = screen_job_module.list_jobs
    registry_warning = (
        "문서 작업 목록을 다시 확인할 수 없습니다. 잠시 뒤 다시 시도하세요."
    )

    def fail_registry_list(_store):
        raise ValueError("internal registry detail")

    assert ctrl.snapshot()["data_notice"] is None
    monkeypatch.setattr(screen_job_module, "list_jobs", fail_registry_list)
    assert ctrl.snapshot()["data_notice"] == {
        "level": "warn", "text": registry_warning,
    }
    monkeypatch.setattr(screen_job_module, "list_jobs", list_jobs)
    assert ctrl.snapshot()["data_notice"] is None

    existing_notices = (
        (
            "이전에 고른 '공고서' 작업을 사용할 수 있습니다. "
            "아래 후보에서 직접 고르세요.",
            "ok",
        ),
        (
            "이전 문서 작업은 이 데이터로 실행할 수 없어 선택을 해제했습니다. "
            "아래 후보를 선택하거나 「확인 필요」에서 사유를 확인하세요.",
            "warn",
        ),
    )
    for existing_text, existing_level in existing_notices:
        ctrl.data_notice_text = existing_text
        ctrl.data_notice_level = existing_level
        monkeypatch.setattr(screen_job_module, "list_jobs", fail_registry_list)
        assert ctrl.snapshot()["data_notice"] == {
            "level": "warn", "text": f"{existing_text} {registry_warning}",
        }
        assert (ctrl.data_notice_text, ctrl.data_notice_level) == (
            existing_text, existing_level,
        )
        monkeypatch.setattr(screen_job_module, "list_jobs", list_jobs)
        assert ctrl.snapshot()["data_notice"] == {
            "level": existing_level, "text": existing_text,
        }


@pytest.mark.parametrize("target", ["file", "pool"])
def test_release_notice_preserves_the_pending_preferred_work_restatement(
    tmp_path, target,
):
    """A RELEASE 사유가 preferred B 안내를 덮지 않고 **합성**한다.

    #932 U4-C 이후 A(공고서)의 해제 사유는 「다른 데이터에 연결돼 있어」다 — 판정 축이
    스키마 호환에서 결속으로 갈렸기 때문이다. B(계약서)는 결속 없는 구판 작업이라 판정
    축이 **스키마**이고, 새 마운트(`없는열` 한 칸)가 마침 그 작업이 요구하는 열이라 이
    데이터로 쓸 수 있다 — 그래도 **자동으로 열리지는 않는다**(§18.3 개정: 추천은 표지일
    뿐 전이가 아니다).

    이 테스트가 재는 것은 두 사실이 **한 문안에 함께 선다**는 합성 규율이다 — 한쪽이
    다른 쪽을 덮으면 사용자는 왜 작업이 사라졌는지 또는 B 가 어떻게 됐는지 둘 중 하나를
    영영 못 듣는다.
    """
    registry = _incompatible_reg(tmp_path)
    registry.assign_authority_id("공고서", "authority-a")
    ctrl, pool = _pool_controller(tmp_path, registry=registry)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    assert ctrl.dispatch("prefer_work", {"name": "계약서"}) == {
        "stored": True,
        "reason": "incompatible",
        "name": "계약서",
    }

    new_path = tmp_path / "contract.csv"
    new_path.write_text("없는열\n새 계약\n", encoding="utf-8")
    if target == "file":
        ctrl.load_data_path(str(new_path))
    else:
        key = _pool_add(pool, "계약 데이터", {"path": str(new_path)})
        assert ctrl.dispatch("load_pool", {"key": key})["ok"] is True

    assert ctrl.job_name == "" and ctrl.preferred_work == ""
    notice = ctrl.snapshot()["data_notice"]
    assert "공고서" not in notice["text"]
    assert "다른 데이터에 연결돼 있어 선택을 해제했습니다" in notice["text"]
    assert "계약서" in notice["text"]
    assert "이 데이터로 쓸 수 있습니다" in notice["text"]  # 다만 자동 선택은 없다


def test_prefer_work_without_data_always_stores_and_guides(tmp_path):
    """무데이터 「문서 만들기에서 사용」은 언제나 「보관 후 안내」 하나다(§5.3 판정 D) —
    **결속 없는** 작업에 한해서다(#932 U4-C, `reason` 은 `no_binding`).

    구 default_data 분기(작업의 기본 데이터 참조 자동 마운트 — F2 PR-B 판정 I)는 U4-C 이전
    결속 폐기와 함께 죽었다: 구 JSON 이 그 legacy 키(`default_dataset_ref`)를 들고 있고
    동명 풀 항목이 실재해도 데이터 선택을 반드시 지난다. 이 테스트가 재는 축은 그 legacy
    키의 무효화이지 U4-C 의 새 `data_path` 결속이 아니다 — 그래서 픽스처 기본 결속을
    `_unbind` 로 비운다(안 비우면 결속 있는 작업이라 select_job 이 곧바로 도는
    새 분기를 타 이 테스트가 재는 것과 무관하게 즉시 승격된다).
    """
    import json as _json

    ctrl, pool = _pool_controller(tmp_path)
    _pool_add(pool, "7월공고", {"path": _data_csv(tmp_path)})
    _unbind(ctrl)
    path = ctrl.registry.path_for("공고서")
    payload = _json.loads(path.read_text(encoding="utf-8"))
    payload["default_dataset_ref"] = "7월공고"          # 구버전이 남긴 결속 키
    path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    res = ctrl.dispatch("prefer_work", {"name": "공고서"})
    assert res == {"stored": True, "reason": "no_binding", "name": "공고서"}
    assert ctrl.job_name == "" and ctrl.preferred_work == "공고서"  # 보관 — 자동 마운트 없음
    assert ctrl.snapshot()["has_data"] is False
    # 데이터를 명시로 골라도 active Work 선택은 **별도 명시 사건**이다(§18.3 개정) —
    # 보관분은 소비되지만 자동 선택은 없고, 쓸 수 있다는 사실만 재진술한다. 결속 없는
    # 구판 작업의 판정 축은 스키마라 이 데이터로는 실제로 쓸 수 있다(#932 U4-C).
    ctrl.load_data_path(_data_csv(tmp_path))
    assert ctrl.job_name == "" and ctrl.preferred_work == ""
    notice = ctrl.snapshot()["data_notice"]["text"]
    assert "이 데이터로 쓸 수 있습니다" in notice and "공고서" in notice
    # 결속 축 후보에는 못 서므로 안내는 「아래 후보」가 아니라 「문서 작업」을 가리킨다.
    assert "문서 작업" in notice and "아래 후보" not in notice


def test_prefer_work_keeps_the_active_work_and_says_so(tmp_path):
    """§18.3 2행 — 이미 열린 작업은 밀어내지 않는다. 대신 못 바꿨다는 사실을 말한다.

    조용히 아무 일도 안 일어나면 사용자는 자기가 누른 버튼이 무엇을 했는지 알 수 없다.
    """
    ctrl, _ = _controller(_p := tmp_path)
    ctrl.registry.assign_authority_id("공고서", "authority-old")
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
    "계약서"는 결속 없는 작업이라(`_incompatible_reg`) 판정 축이 스키마인데(#932 U4-C),
    그 스키마가 이 데이터와 맞지 않는다 — 문안도 그 사실("구조가 맞지 않는다")로 수렴하고
    결속 유무는 여기서 겹쳐 말하지 않는다(그 축은 선택 뒤 게이트가 진다).
    """
    pushes: list = []
    ctrl = JobController(
        _incompatible_reg(tmp_path), lambda s, snap: pushes.append((s, snap)), **_deps(tmp_path)
    )
    ctrl.dispatch("prefer_work", {"name": "계약서"})
    ctrl.load_data_path(_data_csv(tmp_path))
    snap = ctrl.snapshot()
    assert ctrl.job_name == "" and ctrl.preferred_work == ""
    assert "구조가 맞지 않습니다" in snap["data_notice"]["text"]
    assert "직접 선택하세요" not in snap["data_notice"]["text"]
    assert snap["data_notice"]["level"] == "warn"


def test_stored_preference_pointing_at_a_deleted_work_is_loud(tmp_path):
    """그사이 삭제·개명된 작업을 겨눈 보관분은 유령을 열지 않고 사실을 말한다.

    재는 축은 삭제된 유령 참조 처리이지 결속(#932 U4-C)이 아니다 — "공고서"가 결속돼
    있으면 prefer_work 가 즉시 승격해 `preferred_work` 가 저장되지 않으므로(삭제 전에
    이미 소비돼 마운트 시점엔 겨눌 보관분이 없다) `_unbind` 로 결속을 지워 구판
    시나리오를 재현한다.
    """
    ctrl, _ = _controller(tmp_path)
    _unbind(ctrl)
    ctrl.dispatch("prefer_work", {"name": "공고서"})
    ctrl.registry.delete("공고서")
    ctrl.load_data_path(_data_csv(tmp_path))
    snap = ctrl.snapshot()
    assert ctrl.job_name == "" and ctrl.preferred_work == ""
    assert "더는 없습니다" in snap["data_notice"]["text"]
    assert "선택하세요" not in snap["data_notice"]["text"]


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
    pick_output_folder(ctrl, tmp_path / "out")
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
    """한 스냅샷이 말하는 순서 3벌 — 전부 같은 축이어야 한다(넷째였던 재진술 표본은
    그 재진술 축과 함께 퇴역했다)."""
    return {
        "records": [r["index"] for r in snap["records"]],
        "table": [r["index"] for r in snap["table"]["rows"]],
        "strip": [r["index"] for r in snap["table"]["hidden_selected"]],
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


# ------------------------- 전문 범위 편집기 초안(재작성 F3, 지도 §10.11 판정 A·B·D·F·J)
def _draft_session(tmp_path):
    """3행 + 작업 선택 + 저장 폴더 — 초안이 게이트·거울과 갈리는지 보려면 실행 세션이 필요하다."""
    ctrl, pushes = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv3(tmp_path))
    pick_output_folder(ctrl, tmp_path / "out")
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
    assert snap["table"]["hidden_selected"] != [], "필터 밖 선택 2행이 스트립에 안 섰습니다"
    ctrl.dispatch("set_selected_only", {"value": True})
    snap = ctrl.snapshot()
    assert [r["index"] for r in snap["table"]["rows"]] == [2, 1, 0]   # 선택 전부, 표시순
    assert snap["filter"]["active"] is True and snap["filter"]["search"] == "책상"
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
    pick_output_folder(ctrl, tmp_path / "out")
    return ctrl, pushes


def test_new_job_is_neither_blocked_nor_announced(tmp_path):
    """#957 이 차단을 고지로 낮췄고, 간소화 라운드가 그 고지마저 걷었다.

    첫 실행이라는 사실은 사용자가 이미 안다 — 그리고 결과 문서를 열어 확인하는 것은 첫
    실행이든 아니든 상수라, 알림이 바꾸는 행동이 없다. 그래서 새 작업의 표면은 **조용히
    열려 있다**: 게이트도 닫히지 않고 사전검증도 첫 실행을 들먹이지 않는다.
    """
    ctrl, _ = _unreviewed_session(tmp_path)
    snap = ctrl.snapshot()
    assert snap["gate"]["enabled"] is True and snap["gate"]["reason"] == ""
    assert ctrl._review().first_run          # 사실 판정은 그대로 산다
    assert "첫 실행" not in snap["preflight"]["text"]
    # 없는 실행을 들먹이는 일반 문안으로 새지도 않는다.
    assert "마지막 실행" not in snap["preflight"]["text"]
    assert "승인" not in snap["preflight"]["text"]


def test_no_gate_reason_names_a_review_anymore(tmp_path):
    """`gate.reason` 에서 `review_required` 가 사라졌다 — 표지가 「승인 필요」를 말할 자리가 없다.

    승인이 게이트를 여는 사건이 아니게 됐으므로, 그 이름을 남겨 두면 표면이 존재하지 않는
    상태를 그리는 분기를 계속 든다(링2 에서 죽은 서열을 재조립하는 자리).
    """
    ctrl, _ = _unreviewed_session(tmp_path)
    assert ctrl.snapshot()["gate"] == {"enabled": True, "level": "", "text": "", "reason": ""}
    assert ctrl._review().required      # 요구 판정 자체는 그대로 산다(고지 입력)


def test_review_payload_has_no_approval_axis(tmp_path):
    """스냅샷의 검토 몫은 **요구의 사실**만 싣는다(#957).

    종전에는 `approved` 가 함께 실려 표면이 「승인했다」를 그렸다. 승인 사건이 사라진 뒤에도
    그 키를 남기면 값이 언제나 거짓이라 표면이 거짓으로 갈라진다 — 없는 상태를 키로 두지
    않는 것이 「조용히 틀리지 않는다」의 스냅샷 판이다.
    """
    ctrl, _ = _unreviewed_session(tmp_path)
    review = ctrl.snapshot()["review"]
    assert "approved" not in review
    assert review["required"] is True and review["risk"] != ""
    # 선택·순서를 바꿔도 「승인」이라는 상태가 없으므로 되살아날 것도 없다.
    ctrl.dispatch("toggle_record", {"index": 0, "value": False})
    assert "approved" not in ctrl.snapshot()["review"]


def test_a_completed_run_stamps_the_baseline_so_the_repeat_run_is_quiet(tmp_path):
    """완주가 기준선을 세워 다음 실행의 고지가 조용해진다.

    빈 값 없는 데이터를 쓴다 — 빈 값이 있으면 blank_set(§2.13)이 반복 실행에도 서는
    것이 계약이라(침묵 금지), 「조용한 반복」의 전제가 데이터 축에서 갈린다.
    """
    ctrl, _ = _controller(tmp_path, reviewed=False)
    ctrl.dispatch("select_job", {"name": "공고서"})
    clean = tmp_path / "clean.csv"
    clean.write_text("bidNtceNm,presmptPrce\n전산장비,1000\n사무비품,2000000\n", encoding="utf-8")
    _mount_all(ctrl, str(clean))
    pick_output_folder(ctrl, tmp_path / "out")
    assert ctrl.snapshot()["review"]["required"] is True
    ctrl.generate()
    assert ctrl.registry.load("공고서").reviewed_rules  # 완주 스탬프가 기준선을 세웠다
    snap = ctrl.snapshot()
    assert snap["review"]["required"] is False
    assert snap["gate"]["enabled"] is True


def test_an_old_job_without_a_baseline_does_not_claim_it_never_ran(tmp_path):
    """판정 N — 수백 번 실행한 작업에 「아직 한 번도 만들지 않았습니다」는 거짓말이다."""
    ctrl, _ = _controller(tmp_path, reviewed=False)
    ctrl.registry.stamp_last_run("공고서", "2026-07-01T09:00:00")
    ctrl.registry.mutate("공고서", lambda j: setattr(j, "reviewed_rules", {}))  # 구 버전 작업
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    pick_output_folder(ctrl, tmp_path / "out")
    text = ctrl.snapshot()["preflight"]["text"]
    assert "[알림] 마지막 실행에 쓴 규칙을 확인할 수 없습니다." in text
    assert "한 번도" not in text


def test_the_generated_value_preview_surface_is_gone(tmp_path):
    """생성 값 미리보기의 **5액션 전부**가 사라졌다(#957 슬라이스 ③).

    선언으로 남기는 이유는 F5 판정 O 와 같다: 조용한 무시와 선언된 철거는 다르다. 누군가
    이 축을 되살리면 이 테스트가 그 결정을 다시 꺼낸다. 액션 레지스트리 밖의 발신은
    시끄럽게 거절된다(fail-closed) — 조용한 no-op 이 아니다.
    """
    ctrl, _ = _session(tmp_path)
    for action in ("preview_open", "preview_close", "preview_move",
                   "preview_blank_only", "preview_approve"):
        with pytest.raises(ValueError, match="알 수 없는"):
            ctrl.dispatch(action, {})
    assert "preview" not in ctrl.snapshot()


# ---------------- 리뷰 1R 조치의 영구 가드(P1×2·P2×1) ----------------
def test_generation_has_no_review_backstop_left(tmp_path):
    """#957 — 승인 없는 실행은 이제 **정상 경로**다(구 1R P1 백스톱의 퇴역 자리).

    백스톱이 있던 이유는 「버튼 비활성은 표면의 사실이지 계약이 아니다」였고, 그 계약
    자체가 없어졌다. 남는 백스톱은 구조 가드(`validate_generate`)뿐이라 여기서 확인할
    것은 「승인 없이도 문서가 나온다」와 「빈 값이 표식으로 남는다」다.
    """
    ctrl, _ = _unreviewed_session(tmp_path)
    res = ctrl.generate()          # 화면을 거치지 않고 곧바로 호출
    assert res["ok"] is True and res["succeeded"] == 2
    assert "빈 값 표시 필드" in res["summary"]
    made = sorted(p.name for p in (tmp_path / "out").glob("*.hwpx"))
    assert made == ["doc-001.hwpx", "doc-002.hwpx"]


def test_a_rule_change_no_longer_refuses_the_run(tmp_path):
    """규칙이 바뀌어도 실행은 열린다 — 고지가 그 사실을 말할 뿐이다(#957)."""
    ctrl, _ = _unreviewed_session(tmp_path)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "다른-{{seq:001}}"
    ctrl.registry.save(job, allow_overwrite=True)
    ctrl.vm.job.filename_pattern = "다른-{{seq:001}}"   # 세션이 편집 결과를 받은 상태
    snap = ctrl.snapshot()
    assert snap["review"]["required"] is True           # 요구는 서고
    assert snap["gate"]["enabled"] is True              # 게이트는 열려 있다
    assert ctrl.generate()["ok"] is True


def test_completed_run_stamps_the_rules_it_used_not_the_disk(tmp_path):
    """1R P1 — 배치 중 착지한 에디터 저장이 **한 번도 실행된 적 없는 규칙**을 검토받은
    것으로 만들면 안 된다(조용한 승계). 런의 규칙을 찍으면 요구가 그대로 선다."""
    ctrl, _ = _unreviewed_session(tmp_path)
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


def test_planned_names_match_what_generation_will_write(tmp_path):
    """1R P2 — 빈칸은 문서에 **표식 문자열**로 들어간다. 파일명 패턴이 그 필드를 참조하면
    표식 없는 값으로 그린 이름 계획은 **생성될 것과 다른 이름**을 화면에 세운다.

    #957 이후 그 계획을 말하는 표면은 표 「문서」 열 하나다(확인 면이 아니라).
    """
    ctrl, _ = _controller(tmp_path, reviewed=True)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "{{추정가격}}"    # 빈 값이 나는 필드를 이름이 참조한다
    ctrl.registry.save(job, allow_overwrite=True)
    _rereview(ctrl)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    pick_output_folder(ctrl, tmp_path / "out")
    shown = {r["name"] for r in ctrl.snapshot()["records"]}
    assert ctrl.generate()["ok"] is True
    written = {p.name for p in (tmp_path / "out").glob("*.hwpx")}
    assert shown == written, f"계획한 이름 {shown!r} 가 생성물 {written!r} 과 다릅니다."


def test_the_marker_appears_whenever_blanks_exist(tmp_path):
    """`_run_marker` 재정의(U2 §2.13) — 조건은 「빈 값이 있으면」 하나다.

    구 「확인 안 된 빈 값 = 표식 없음」 중간 상태는 ack 폐기와 함께 사라졌다: 표시와 생성이
    같은 술어를 쓰므로 표 「문서」 열의 이름에도 처음부터 표식이 선다.
    """
    ctrl, _ = _controller(tmp_path, reviewed=True)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "{{추정가격}}"
    ctrl.registry.save(job, allow_overwrite=True)
    _rereview(ctrl)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    names = [r["name"] for r in ctrl.snapshot()["records"]]
    assert any("미입력" in name for name in names), names


def test_blank_fields_count_blanks_not_markers(tmp_path):
    """빈 값 표지는 표식 **없는** 판에서 센다 — 표식(생성 입력)을 세면 언제나 0건이 되어
    표지가 거짓이 된다. 두 판이 같은 사실을 다른 각도로 말한다."""
    ctrl, _ = _session(tmp_path)
    assert ctrl.snapshot()["blank_fields"] == ["추정가격"]


# ---------------- 리뷰 2R·3R 조치의 승계(#957 재조준) ----------------
def test_the_display_timestamp_is_shared_across_one_snapshot(tmp_path):
    """2R P2 — 게이트 감사(refresh)와 표 「문서」 열이 각자 시각을 찍으면 `{{date:SS}}`
    가 초 경계를 넘는 순간 한 화면이 두 이름을 말한다. 캡처는 스냅샷당 1회다."""
    ctrl, _ = _controller(tmp_path, reviewed=True)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "doc-{{date:HHmmSS}}-{{seq}}"
    ctrl.registry.save(job, allow_overwrite=True)
    _rereview(ctrl)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    snap = ctrl.snapshot()
    stamp = ctrl._names_now
    assert stamp is not None
    marker = stamp.strftime("doc-%H%M%S-")
    assert all(r["name"].startswith(marker) for r in snap["records"]), snap["records"]


def test_run_entry_captures_its_own_timestamp_once(tmp_path):
    """3R 승계 — 한 런의 이름·본문·충돌 판정은 **한 시각**을 쓴다(#957).

    표시 축(`_names_now`)은 스냅샷의 것이고 실행은 진입 시점에 자기 시각을 1회 캡처한다.
    두 축이 갈리는 것은 결함이 아니지만, **런 안에서** 갈리면 같은 배치의 문서가 서로 다른
    초를 이름에 달게 된다 — 그것을 여기서 막는다.
    """
    ctrl, _ = _controller(tmp_path, reviewed=True)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "doc-{{date:HHmmSS}}-{{seq}}"
    ctrl.registry.save(job, allow_overwrite=True)
    _rereview(ctrl)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    out = tmp_path / "out"
    pick_output_folder(ctrl, out)

    ctrl.snapshot()                       # 표시 축이 한 시각을 소비한다
    assert ctrl.generate()["ok"] is True
    made = sorted(p.name for p in out.glob("*.hwpx"))
    stamps = {name.split("-")[1] for name in made}
    assert len(made) == 2 and len(stamps) == 1, made


def test_new_blanks_on_new_data_are_announced_and_marked(tmp_path):
    """침묵 금지(U2 §2.13 **최우선**) — 한 번 완주한 작업에 새 데이터를 올려 빈 값이
    새로 생기면 그 사실이 **말해진다**.

    #957 이후 그 말하기는 게이트가 아니라 ①사전검증 경고 ②문서에 박히는 표식 ③완료 요약의
    병기 셋이다. 조용한 생성은 여전히 없다 — 없어진 것은 승인을 받아야 열리는 문 하나다.
    """
    ctrl, _ = _controller(tmp_path)                       # 기준선 있는 작업(완주 자격)
    ctrl.dispatch("select_job", {"name": "공고서"})
    clean = tmp_path / "clean.csv"
    clean.write_text("bidNtceNm,presmptPrce\n전산장비,1000\n사무비품,2000000\n", encoding="utf-8")
    _mount_all(ctrl, str(clean))
    pick_output_folder(ctrl, tmp_path / "out")
    snap = ctrl.snapshot()
    assert snap["gate"]["enabled"] is True                # 빈 값 없음 = 조용한 반복 실행
    assert "빈 값" not in snap["preflight"]["text"]
    assert ctrl.generate()["ok"] is True                  # 완주 — 기준선이 다시 선다

    _mount_all(ctrl, _data_csv(tmp_path))                 # 다음 달 데이터 — 빈 값 신규 발생
    pick_output_folder(ctrl, tmp_path / "out")         # RELEASE 뒤 명시 Work·저장 위치 재선택
    snap = ctrl.snapshot()
    assert snap["gate"]["enabled"] is True
    assert "[경고] 빈 값 필드: 추정가격" in snap["preflight"]["text"], (
        "새 빈 값인데 아무 말도 하지 않습니다(조용한 표식 생성)."
    )
    # 같은 폴더 재생성이라 덮어쓰기 확인(RC-02)이 먼저 선다 — 확인 뒤 생성이 열린다.
    assert ctrl.generate()["needs_overwrite"] is True
    res = ctrl.generate(confirm_overwrite=True)
    assert res["ok"] is True and "빈 값 표시 필드 1개(추정가격)." in res["summary"]


# ------------------------------------------- TXT 합류와 작업대 진입 (재작성 F6 PR-A)
def _txt_job(ctrl, tmp_path, *, name: str = "발주요청_기안") -> None:
    """같은 데이터에 결속된 TXT 작업을 하나 저장한다(후보 판정은 hwpx 와 같은 술어).

    결속은 매체를 가리지 않는다(#932 U4-C): TXT 작업도 레코드를 읽어 기안을 세우므로
    후보로 서려면 이 데이터에 연결돼 있어야 한다.
    """
    tpl = tmp_path / f"{name}.txt"
    tpl.write_text("공고: {{공고명}}", encoding="utf-8")
    ctrl.registry.save(Job(
        name=name, template_path=str(tpl),
        mapping=MappingProfile(mappings=[
            FieldMapping(template_field="공고명", source="bidNtceNm")]),
        **_bound_to(_data_csv_path(tmp_path)),
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
    # 검토 요구는 배제 선언(판정 J) — 골격만 선다.
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
        ctrl.registry, lambda s, snap: None, clock=datetime.now,
        target_font=TargetFontSetting())
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


def test_candidate_card_does_not_carry_run_history(tmp_path):
    """후보 카드는 「이 데이터로 무엇을 만들 수 있는가」만 말한다(U4 계열2-31).

    실행 이력은 그 판단에 들지 않는데 카드마다 「성공한 실행 없음」이 서서 정보 밀도만
    깎았다. 매체별 술어 문안 자체(§19.4)는 죽지 않았다 — 라이브러리 목록이 계속 쓴다.
    """
    ctrl, _ = _controller(tmp_path)
    _txt_job(ctrl, tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))
    for card in ctrl.snapshot()["candidates"]["top"]:
        assert "last_run_label" not in card


def test_browse_rows_section_inside_the_tab_not_across_it(tmp_path):
    """§19.5 — 탭이 primary classification 이고 방식은 탭 **안**에서만 구획한다."""
    ctrl, _ = _controller(tmp_path)
    _txt_job(ctrl, tmp_path)
    _mount_all(ctrl, _data_csv(tmp_path))
    b = ctrl.snapshot()["browse"]
    assert b["tab"] == "available"
    assert {s["mode"] for s in b["sections"]} == {"hwpx_generate", "text_review_copy"}
    assert all("mode_label" in r for r in b["rows"])


def test_review_is_declared_out_of_scope_for_txt(tmp_path):
    """검토 요구는 TXT 에서 **배제 선언**이다(지도 §10.15 판정 J).

    근거: 작업대가 이미 레코드 전수를 채운 모습으로 보여 주는 검토 표면이다. TXT 에 요구를
    세우면 작업대에서 눈으로 본 것을 「문서 만들기」에서 또 확인하라는 **이중 권위**가
    된다(§10.5 판정 단일 출처). 종전 함께 배제되던 미리보기 드로어는 #957 에서 매체와
    무관하게 통째로 철거됐다.

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
        "required": False, "risk": "", "targets": [],
        "first_run": False, "unknown_baseline": False, "structure_changed": False,
    }
    # 게이트 사유도 검토를 들먹이지 않는다 — TXT 게이트는 진입 자격만 센다.
    assert "확인" not in snap["gate"]["text"] or "검토" not in snap["gate"]["text"]


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
        ctrl.registry, lambda s, snap: None, clock=datetime.now,
        target_font=TargetFontSetting())
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
        ctrl.registry, lambda s, snap: None, clock=datetime.now,
        target_font=TargetFontSetting())
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
        ctrl.registry, lambda s, snap: None, clock=datetime.now,
        target_font=TargetFontSetting()).open
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
        ctrl.registry, lambda s, n: None, clock=datetime.now,
        target_font=TargetFontSetting()).open
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
        ctrl.registry, lambda s, n: None, clock=datetime.now,
        target_font=TargetFontSetting()).open
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


# ─── 템플릿 변경 확인·적용 배선(S3-09 #659) — 판정은 코디네이터 테스트가 소유 ───


def _template_change_controller(tmp_path):
    """공용 `_controller` + 실 코디네이터 주입 — 존·동사의 **배선**만 잰다."""
    reg = _registry(tmp_path)
    coordinator = TemplateChangeCoordinator(
        reg, root=tmp_path / "authority", clock=_clock()
    )
    pushes: list = []
    ctrl = JobController(
        reg, lambda s, snap: pushes.append((s, snap)),
        clock=_clock(),
        existing_outputs=existing_output_paths,
        ensure_output_dir=ensure_output_directory,
        engine=make_hwpx_engine(),
        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
        generation_lock=threading.Lock(),
        file_source_factory=source_for_path,
        pool_source_factory=source_from_pool_item,
        template_change=coordinator,
    )
    return ctrl, pushes


def _unprepared_after_select(ctrl, name="공고서"):
    """작업이 든 권위 참조만 걷어 **생성이 최초 채택자**인 상태를 되만든다.

    선택이 준비를 지게 된 뒤로(#932 B5) 그 상태는 「선택 때 준비가 거절됐고 그 뒤 템플릿이
    수리된」 경우에만 남는다. 아래 테스트들이 재는 것은 그 lazy 채택 경로의 계약(발급 순간의
    사본 대조·push 규율)이고 그 계약은 그대로 살아 있다 — 사라진 것은 **도달 방법**이라
    여기서 명시로 만든다(전제가 바뀌었을 때 단언을 지우지 않고 새 계약으로 옮긴다).
    """
    ctrl.registry.mutate(name, lambda job: setattr(job, "authority_id", ""))
    if ctrl.vm is not None:
        ctrl.vm.job.authority_id = ""
    ctrl._seated_template_application_id = None


def test_selecting_a_job_prepares_it_without_a_button(tmp_path):
    """#932 B5 — 「변경사항 확인」의 겸직 해소. 선택만으로 권위가 서고 구간 표면이 열린다.

    종전에는 갓 저장한 작업이 이름이 전혀 다른 단추를 누르기 전까지 「포함할 내용」을 못
    세웠다 — 구간이 서려면 준비가 필요하고 생성이 열리려면 구간이 필요한 교착이었다.
    """
    ctrl, _pushes = _template_change_controller(tmp_path)
    assert ctrl.registry.load("공고서").authority_id == ""

    ctrl.dispatch("select_job", {"name": "공고서"})

    assert ctrl.registry.load("공고서").authority_id  # 클릭 0회로 준비됐다
    # 준비를 마쳤고 원본도 그대로다 — 존은 자기 발로 내려온다(U4 12번).
    snap = ctrl.snapshot()
    assert snap["template_change"]["actionable"] is False
    assert snap["template_change"]["source_drift"] == "unchanged"


def test_template_change_zone_rides_snapshot_and_verbs_route(tmp_path):
    ctrl, pushes = _template_change_controller(tmp_path)
    # 작업 미선택 — 존은 부재가 아니라 명시적 unsupported 다(분기별 키 동형).
    assert ctrl.snapshot()["template_change"]["supported"] is False
    ctrl.dispatch("select_job", {"name": "공고서"})
    seated_job = ctrl.vm.job
    # 착석이 준비를 진다(#932 B5) — 정체는 여기서 이미 서고, 확인은 그것을 흔들지 않는다.
    assert seated_job.authority_id == ctrl.registry.load("공고서").authority_id != ""
    seated_application = ctrl._seated_template_application_id
    assert seated_application
    zone = ctrl.snapshot()["template_change"]
    assert zone["supported"] is True and zone["checkable"] is True
    assert zone["actionable"] is False  # 준비를 마쳤고 원본 그대로 — 존은 내려온다
    result = ctrl.dispatch("template_check", {"request_id": "k1"})
    assert result["ok"] is True
    assert result["preparation"]["status"] == "no_change"
    final_job = ctrl.registry.load("공고서")
    assert seated_job.authority_id == final_job.authority_id
    assert ctrl._seated_template_application_id == seated_application
    # 비-query 동사라 push 가 일어나 존이 최신 Preparation 을 실었다.
    assert pushes[-1][1]["template_change"]["preparation"]["status"] == "no_change"
    # 개명이 권위 인덱스를 추종한다 — epoch 이 살아 있으면 재-bootstrap 이 아니다.
    ctrl.dispatch("rename_job", {"name": "공고서", "new": "공고서갱신"})
    assert ctrl.snapshot()["template_change"]["epoch"] == 1


def test_txt_job_snapshot_seats_the_same_template_change_zone(tmp_path):
    """TXT 분기도 같은 존을 싣는다(S10-02 #859) — 매체 특례가 아니라 같은 배선이다.

    종전 TXT 분기는 기본값 ``unsupported_zone()`` 을 그대로 두고 반환해, 존이 **구조적으로**
    닿을 수 없었다(판정이 아니라 배선 부재). 판정·token·epoch 은 여전히 코디네이터 소유라
    여기서는 존이 서고 동사가 라우팅되는지만 본다.
    """
    ctrl, pushes = _template_change_controller(tmp_path)
    txt = tmp_path / "안내문.txt"
    txt.write_text("본문 {{공고명}}\n", encoding="utf-8")
    ctrl.registry.save(Job(name="안내문", template_path=str(txt)))
    ctrl.dispatch("select_job", {"name": "안내문"})
    assert ctrl.job_is_txt and ctrl.vm is None  # TXT 는 hwpx 실행뷰를 세우지 않는다

    snap = ctrl.snapshot()
    zone = snap["template_change"]
    assert zone["supported"] is True and zone["checkable"] is True
    # 드리프트 사실은 **존 하나**가 든다(#932 B5 — 종전 top-level 사본은 소비자 0 이었다).
    # TXT 도 착석이 준비를 지므로 대조가 성립하고, 원본 그대로면 존은 서지 않는다.
    assert zone["source_drift"] == "unchanged" and zone["source_drift_note"] is None
    assert zone["actionable"] is False
    assert ctrl.registry.load("안내문").authority_id != ""  # 착석이 권위를 발급했다

    result = ctrl.dispatch("template_check", {"request_id": "t1"})
    assert result["ok"] is True and result["preparation"]["status"] == "no_change"
    assert pushes[-1][1]["template_change"]["epoch"] == 1

    txt.write_text("본문 {{공고명}}\n덧붙임 {{담당자}}\n", encoding="utf-8")
    ready = ctrl.dispatch("template_check", {"request_id": "t2"})["preparation"]
    assert ready["status"] == "ready"
    applied = ctrl.dispatch("template_apply", {"change_token": ready["change_token"]})
    assert applied["status"] == "applied"
    assert ctrl.snapshot()["template_change"]["epoch"] == 2


# ── S6G-00 R1: generate-once 트랩을 오늘의 사실로 고정한다(#806) ──────────────────────────
def test_slotless_hwpx_generate_mints_authority_then_second_run_succeeds(tmp_path):
    """**#806 R1 의 뒤집힘 — S6-05(#812)가 트랩을 구조로 해소했다.**

    S6G-00(#806)이 재현으로 고정한 generate-once 트랩: 1회차 generate 가 스스로
    ``authority_id`` 를 발급하고(S4-11), 2회차가 그 발급물 때문에 managed 로 읽혀 거절됐다
    (SX-03 가드). S6-05 는 곱의 반대편 항을 제거했다 — 실행 경로 선택(의미 4)은
    ``bool(authority_id)`` 가 아니라 slot-bearing 사실에서 갈리므로, slotless 작업은 발급
    뒤에도 legacy 갈래로 흘러 **2회차도 같은 갈래에서 성공한다**(같은 입력 = 같은 갈래).
    발급 자체(의미 1·2)는 그대로 옳다 — 발급이 트랩이 아니라 곱이 트랩이었다.
    """
    ctrl, _ = _template_change_controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    pick_output_folder(ctrl, tmp_path / "out")
    _unprepared_after_select(ctrl)  # 1회차 generate 가 최초 발급자인 상태(#932 B5)
    assert ctrl.registry.load("공고서").authority_id == ""

    assert ctrl.generate()["ok"] is True
    # 1회차가 Work identity 를 발급했다(의미 1·2 — lazy 발급은 그대로 옳다).
    minted = ctrl.registry.load("공고서").authority_id
    assert minted != ""
    assert minted.startswith("w-")  # 발급 형태 단일화(S6-05)

    # 2회차: 발급물이 있어도 slotless 는 legacy 갈래 그대로 — 트랩이 구조로 사라졌다.
    second = ctrl.generate(confirm_overwrite=True)
    assert second["ok"] is True, second
    assert second.get("needs_overwrite") is not True
    assert ctrl.registry.load("공고서").authority_id == minted


def test_template_check_validation_failure_precedes_durable_commit(tmp_path):
    """Commit 전 validation 실패는 authority/Application과 seated identity를 바꾸지 않는다."""
    ctrl, pushes = _template_change_controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    old_vm = ctrl.vm
    push_count = len(pushes)
    # 기준선은 **착석 직후 상태**다(#932 B5): 선택이 준비를 지게 되며 「durable 이 비어
    # 있다」는 더 이상 이 테스트의 전제가 아니고, 재는 것은 애초에 「실패한 확인이 그것을
    # 움직이지 않는다」였다 — 기준선을 상수에서 관측으로 바꾼다.
    baseline_authority = ctrl.registry.load("공고서").authority_id
    baseline_works = sorted((tmp_path / "authority" / "works").glob("*"))
    baseline_application = ctrl._seated_template_application_id

    with pytest.raises(TemplateChangeError, match="잘못된 확인 요청 키"):
        ctrl.dispatch("template_check", {"request_id": "한글키"})

    assert ctrl.registry.load("공고서").authority_id == baseline_authority
    assert sorted((tmp_path / "authority" / "works").glob("*")) == baseline_works
    assert ctrl.vm is old_vm
    assert ctrl._seated_template_application_id == baseline_application
    assert len(pushes) == push_count


def test_template_check_does_not_reread_registry_after_durable_commit(
    tmp_path, monkeypatch,
):
    """Commit 뒤 registry 관찰 실패는 성공을 뒤집지 않고 retry도 같은 상태로 수렴한다."""
    from hwpxfiller.external.work_template_store import AtomicWorkTemplateStateStore

    ctrl, pushes = _template_change_controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _unprepared_after_select(ctrl)  # 확인 한 바퀴만 재는 자리(#932 B5)
    coordinator = ctrl._template_change
    assert coordinator is not None
    state = {"in_check": False, "committed": False, "post_commit_reads": 0}
    final_job_snapshots = []
    advance = coordinator._advance
    check = coordinator.check_for_seated_context
    load_job = template_change_module.load_job

    def record_commit(*args, **kwargs):
        result = advance(*args, **kwargs)
        final_job_snapshots.append(result.final_job_snapshot)
        state["committed"] = True
        return result

    def mark_check(*args, **kwargs):
        state["committed"] = False
        state["in_check"] = True
        try:
            return check(*args, **kwargs)
        finally:
            state["in_check"] = False

    def fail_post_commit_read(*args, **kwargs):
        if state["in_check"] and state["committed"]:
            state["post_commit_reads"] += 1
            raise OSError("post-commit registry observation failed")
        return load_job(*args, **kwargs)

    monkeypatch.setattr(coordinator, "_advance", record_commit)
    monkeypatch.setattr(coordinator, "check_for_seated_context", mark_check)
    monkeypatch.setattr(template_change_module, "load_job", fail_post_commit_read)

    result = ctrl.dispatch("template_check", {"request_id": "commit-truth"})
    assert result["ok"] is True and result["preparation"]["status"] == "no_change"
    assert "error" not in result

    durable_job = ctrl.registry.load("공고서")
    durable = AtomicWorkTemplateStateStore(
        tmp_path / "authority" / "works"
    ).load(durable_job.authority_id)
    application_id = durable.work.current_template_application_id
    assert len(durable.applications) == 1 and len(durable.preparations) == 1
    assert ctrl.vm is not None and ctrl.vm.job.authority_id == durable_job.authority_id
    assert ctrl._seated_template_application_id == application_id
    assert state["post_commit_reads"] == 0
    assert final_job_snapshots[-1] is not None
    assert pushes[-1][1]["template_change"]["preparation"]["status"] == "no_change"

    retried = ctrl.dispatch("template_check", {"request_id": "commit-truth"})
    durable_after_retry = AtomicWorkTemplateStateStore(
        tmp_path / "authority" / "works"
    ).load(durable_job.authority_id)
    assert retried["preparation"]["preparation_token"] == (
        result["preparation"]["preparation_token"]
    )
    assert durable_after_retry == durable
    assert state["post_commit_reads"] == 0
    assert final_job_snapshots[-1] is None  # no gate면 stale initial 반환 0


def test_template_check_returns_the_job_snapshot_seen_by_final_gate(
    tmp_path, monkeypatch,
):
    """Capture gate 뒤 바뀐 B를 admission gate가 보면 caller도 exact B를 받는다."""
    ctrl, _pushes = _template_change_controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    coordinator = ctrl._template_change
    assert coordinator is not None
    admit = template_change_module.admit_preparation
    favorite_at = "2026-08-21T16:00:00+09:00"

    def change_before_final_gate(*args, **kwargs):
        ctrl.registry.set_favorite("공고서", True, favorite_at)
        return admit(*args, **kwargs)

    monkeypatch.setattr(
        template_change_module, "admit_preparation", change_before_final_gate
    )

    result, final_job, application_id = coordinator.check_for_seated_context(
        "공고서", "final-witness"
    )

    assert result["ok"] is True and result["preparation"]["status"] == "no_change"
    assert final_job is not None and final_job.favorited_at == favorite_at
    assert application_id is not None


def test_template_check_returns_the_application_seen_by_final_gate(
    tmp_path, monkeypatch,
):
    """Admission 뒤 다른 coordinator가 B를 적용해도 caller에는 gate의 A만 돌아간다."""
    ctrl, _pushes = _template_change_controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    coordinator = ctrl._template_change
    assert coordinator is not None
    other = TemplateChangeCoordinator(
        ctrl.registry, root=tmp_path / "authority", clock=_clock()
    )
    admit = template_change_module.admit_preparation
    nested = {"active": False}
    later_application_ids = []

    def apply_after_final_gate(*args, **kwargs):
        admitted = admit(*args, **kwargs)
        if nested["active"]:
            return admitted
        nested["active"] = True
        try:
            _write_template(
                Path(ctrl.registry.load("공고서").template_path),
                ["공고명", "추정가격", "비고"],
            )
            prepared = other.check("공고서", "later-application")["preparation"]
            assert other.apply("공고서", prepared["change_token"])["status"] == "applied"
            work_id = ctrl.registry.load("공고서").authority_id
            later_application_ids.append(other.current_template_application_id(work_id))
        finally:
            nested["active"] = False
        return admitted

    monkeypatch.setattr(
        template_change_module, "admit_preparation", apply_after_final_gate
    )

    result = ctrl.dispatch("template_check", {"request_id": "application-race"})

    assert result["ok"] is True and ctrl._seated_template_application_id
    assert ctrl._seated_template_application_id != later_application_ids[0]
    ctrl.load_data_path(_data_csv(tmp_path))
    assert ctrl.job_name == "" and ctrl.vm is None
    assert "같은 작업인지 확인할 수 없어" in ctrl.snapshot()["data_notice"]["text"]


def test_template_check_releases_when_rules_change_before_final_gate(
    tmp_path, monkeypatch,
):
    """같은 authority라도 final gate B의 규칙/판본이 seated A와 다르면 채택하지 않는다."""
    ctrl, _pushes = _template_change_controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _unprepared_after_select(ctrl)  # 확인이 최초 채택자인 경로(#932 B5)
    seated_job = ctrl.vm.job
    coordinator = ctrl._template_change
    assert coordinator is not None
    admit = template_change_module.admit_preparation

    def change_before_final_gate(*args, **kwargs):
        ctrl.registry.mutate(
            "공고서",
            lambda job: setattr(job, "filename_pattern", "교체-{{seq:001}}"),
        )
        return admit(*args, **kwargs)

    monkeypatch.setattr(
        template_change_module, "admit_preparation", change_before_final_gate
    )

    result = ctrl.dispatch("template_check", {"request_id": "rules-race"})

    assert result["ok"] is False and result["reason"] == "work_context_changed"
    assert seated_job.authority_id == ""  # B identity adoption 0
    assert ctrl.registry.load("공고서").binding_revision > seated_job.binding_revision
    assert ctrl.job_name == "" and ctrl.vm is None
    assert "변경되어 선택을 해제" in ctrl.snapshot()["data_notice"]["text"]


def test_template_check_releases_same_name_recreation_seen_by_final_gate(
    tmp_path, monkeypatch,
):
    """Capture 뒤 동명 A→B 재생성은 final gate B를 돌려 loud RELEASE한다."""
    ctrl, _pushes = _template_change_controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _unprepared_after_select(ctrl)  # 확인이 최초 채택자인 경로(#932 B5)
    seated_job = ctrl.vm.job
    coordinator = ctrl._template_change
    assert coordinator is not None
    admit = template_change_module.admit_preparation

    def recreate_before_final_gate(*args, **kwargs):
        replacement = ctrl.registry.load("공고서")
        ctrl.registry.delete("공고서")
        replacement.authority_id = "authority-replacement"
        ctrl.registry.save(replacement)
        return admit(*args, **kwargs)

    monkeypatch.setattr(
        template_change_module, "admit_preparation", recreate_before_final_gate
    )

    result = ctrl.dispatch("template_check", {"request_id": "recreation-race"})

    assert result["ok"] is False and result["reason"] == "work_context_changed"
    assert seated_job.authority_id == ""  # replacement identity adoption 0
    assert ctrl.registry.load("공고서").authority_id == "authority-replacement"
    assert ctrl.job_name == "" and ctrl.vm is None
    assert ctrl._seated_template_application_id is None


def test_template_check_final_gate_read_failure_prevents_admission_commit(
    tmp_path, monkeypatch,
):
    """Admission transaction의 final Job read 실패는 그 commit을 허가하지 않는다."""
    ctrl, pushes = _template_change_controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _unprepared_after_select(ctrl)  # 확인이 최초 채택자인 경로(#932 B5)
    seated_job = ctrl.vm.job
    coordinator = ctrl._template_change
    assert coordinator is not None
    admit = template_change_module.admit_preparation
    load_job = template_change_module.load_job
    state = {"in_final_gate": False}
    before_gate = []

    def fail_final_gate(*args, **kwargs):
        work_id = kwargs["work_id"]
        before_gate.append(coordinator._works.load(work_id))
        state["in_final_gate"] = True
        try:
            return admit(*args, **kwargs)
        finally:
            state["in_final_gate"] = False

    def fail_final_read(*args, **kwargs):
        if state["in_final_gate"]:
            raise OSError("final-gate registry observation failed")
        return load_job(*args, **kwargs)

    monkeypatch.setattr(template_change_module, "admit_preparation", fail_final_gate)
    monkeypatch.setattr(template_change_module, "load_job", fail_final_read)
    push_count = len(pushes)

    with pytest.raises(OSError, match="final-gate registry observation failed"):
        ctrl.dispatch("template_check", {"request_id": "final-gate-failure"})

    work_id = ctrl.registry.load("공고서").authority_id
    assert coordinator._works.load(work_id) == before_gate[0]
    assert before_gate[0].prepared_changes == ()
    assert seated_job.authority_id == "" and ctrl._seated_template_application_id is None
    assert ctrl.vm is not None and len(pushes) == push_count


def test_managed_generation_routes_through_exact_applied_bytes_no_regression(tmp_path):
    """#681 G11 무회귀: 코디네이터가 배선된 managed 생성이 mutable template_path 직독 대신
    bootstrap→admission gate→exact staged bytes 로 정상 문서를 만든다(핵심 제품 기능 생존).

    재는 축은 managed 생성 배선이지 결속(#932 U4-C)이 아니다 — 결말의 KEEP 단언
    (`ctrl.job_name == "공고서"`)이 성립하려면 clean.csv 가 이 작업의 결속이어야 한다.
    기본 결속(`_registry` 의 d.csv, 이 테스트엔 없는 경로)에 남아 있으면 재마운트마다
    RELEASE 된다. select 전에 결속해야 seated 지문이 그 결속으로 시작해 이후 재마운트가
    `content_fingerprint`(U4 §2.4)의 결속 3성분과 계속 일치한다.
    """
    ctrl, pushes = _template_change_controller(tmp_path)
    clean = tmp_path / "clean.csv"
    clean.write_text("bidNtceNm,presmptPrce\n전산장비,1000\n사무비품,2000000\n", encoding="utf-8")
    ctrl.registry.save(
        replace(ctrl.registry.load("공고서"), **_bound_to(str(clean))), allow_overwrite=True,
    )
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, str(clean))
    pick_output_folder(ctrl, tmp_path / "out")
    pushes.clear()
    res = ctrl.generate()
    assert res["ok"] is True, res
    snapshots = [snapshot for _screen, snapshot in pushes if "has_job" in snapshot]
    assert len(snapshots) == 1 and snapshots[0] == ctrl.snapshot()
    assert len(list((tmp_path / "out").glob("*.hwpx"))) == 2  # 실제 산출물
    restored = ctrl.registry.load("공고서")
    assert ctrl.vm is not None and ctrl.vm.job.authority_id == restored.authority_id
    assert ctrl._seated_template_application_id is not None
    pushes.clear()
    assert ctrl.generate()["ok"] is False
    assert pushes == []  # visible identity 무변경 rejection은 extra push 0
    ctrl.load_data_path(str(clean))
    assert ctrl.job_name == "공고서"  # generate lazy bootstrap도 다음 mount에서 KEEP


def test_managed_generation_pushes_adopted_identity_before_a_plan_rejection(tmp_path):
    """Lazy bootstrap 뒤 plan 거절도 새 managed identity를 한 번 밀어야 한다.

    거절 사유는 #957 이후 구조 가드다 — 검토 거절 갈래가 사망했으므로 살아 있는 가드
    (선택 0건)로 같은 순서를 잰다.
    """
    ctrl, pushes = _template_change_controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    pick_output_folder(ctrl, tmp_path / "out")
    ctrl.dispatch("set_none", {})
    assert ctrl.snapshot()["managed_hwpx"] is False

    _unprepared_after_select(ctrl)  # 채택은 generate 안에서 일어난다(#932 B5)
    pushes.clear()
    rejected = ctrl.generate()

    assert rejected["ok"] is False and "최소 1건" in rejected["error"]
    current = ctrl.snapshot()
    # S6-05(#812): managed_hwpx 는 slot-bearing 파생이라 slotless 발급 작업은 False 다 —
    # 채택된 identity(authority_id) push 는 그대로 한 번 일어난다.
    assert current["managed_hwpx"] is False
    assert ctrl.registry.load("공고서").authority_id != ""
    assert len(pushes) == 1 and pushes[0][1] == current


def test_managed_generation_uses_applied_bytes_not_edited_source(tmp_path):
    """#681 drift 음성대조: 적용된 A bytes 뒤 source 를 B 로 고쳐도(미적용) 생성 입력은
    A 의 exact Candidate bytes(staged) 다 — bridge 는 source 가 아니라 Candidate store 를 읽는다."""
    from hwpxfiller.application.candidate_revision import blob_digest
    from hwpxfiller.application.jobs import load_job

    ctrl, _ = _template_change_controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    job = load_job(ctrl.registry, "공고서")
    applied_bytes = Path(job.template_path).read_bytes()  # A
    coord = ctrl._template_change
    staged_a = coord.resolve_generation_template("공고서")  # bootstrap A + stage
    # source 를 B 로 오염(미적용) — staged 는 여전히 A digest 여야 한다.
    Path(job.template_path).write_bytes(applied_bytes + b"DRIFT-B")  # B != A
    staged_again = coord.resolve_generation_template("공고서")
    assert Path(staged_again).read_bytes() == applied_bytes            # A, not B
    assert blob_digest(Path(staged_again).read_bytes()) == blob_digest(applied_bytes)
    assert Path(staged_a).read_bytes() == applied_bytes                # 첫 스테이징도 A


def test_managed_generation_rejects_unqualifiable_template_loudly(tmp_path):
    """#681 confirm-or-alarm: bootstrap qualification 이 실패하는 템플릿은 조용히
    template_path 로 fallback 하지 않고 시끄러운 거절(TEMPLATE_INITIALIZATION_REQUIRED 문안)."""
    ctrl, _ = _template_change_controller(tmp_path)
    bad = tmp_path / "안됨.hwpx"
    bad.write_bytes(b"not a real hwpx zip")     # qualify 실패
    ctrl.registry.save(Job(name="깨진작업", template_path=str(bad)))
    ctrl.dispatch("select_job", {"name": "깨진작업"})
    clean = tmp_path / "c.csv"
    clean.write_text("bidNtceNm,presmptPrce\n전산장비,1000\n", encoding="utf-8")
    _mount_all(ctrl, str(clean))
    pick_output_folder(ctrl, tmp_path / "out2")
    res = ctrl.generate()
    assert res["ok"] is False and res["level"] == "warn"
    assert "초기화" in res["error"]  # TEMPLATE_INITIALIZATION_REQUIRED 문안
    assert not list((tmp_path / "out2").glob("*.hwpx"))  # 산출물 0 (fallback 없음)


def test_managed_generation_clears_staging_after_run(tmp_path):
    """#681 F2: run 이 끝나면 staged 사본을 정리한다 — 판본별 read-only 사본이 영구 누적되지 않는다."""
    ctrl, _ = _template_change_controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    clean = tmp_path / "clean.csv"
    clean.write_text("bidNtceNm,presmptPrce\n전산장비,1000\n", encoding="utf-8")
    _mount_all(ctrl, str(clean))
    pick_output_folder(ctrl, tmp_path / "out")
    assert ctrl.generate()["ok"] is True
    staging = tmp_path / "authority" / "run_staging"
    assert not staging.exists() or not list(staging.iterdir())  # 누적 없음


@pytest.mark.parametrize("target", ["file", "pool"])
def test_managed_generation_maps_incomplete_slot_config_to_status(
    tmp_path, monkeypatch, target,
):
    """#681 F3: capture 가 SLOT_CONFIGURATION_INCOMPLETE 로 던지면 raw 예외로 새지 않고
    구조화된 제품 상태(ok:False)로 거절한다.

    재는 축은 admission 거절 뒤 KEEP 배선이지 결속(#932 U4-C)이 아니다 — 결말의
    `ctrl.job_name == "공고서"` 단언이 성립하려면 c.csv 가 이 작업의 결속이어야 한다
    (`test_managed_generation_routes_through_exact_applied_bytes_no_regression` 과 같은 사유).
    """
    import hwpxfiller.webapp.template_change as tc
    from hwpxfiller.application.slot_selection_input import SlotSelectionCaptureError

    ctrl, pushes = _template_change_controller(tmp_path)
    clean = tmp_path / "c.csv"
    clean.write_text("bidNtceNm,presmptPrce\n전산장비,1000\n", encoding="utf-8")
    ctrl.registry.save(
        replace(ctrl.registry.load("공고서"), **_bound_to(str(clean))), allow_overwrite=True,
    )
    ctrl.dispatch("select_job", {"name": "공고서"})

    def boom(*_a, **_k):
        raise SlotSelectionCaptureError("SLOT_CONFIGURATION_INCOMPLETE", "미완")

    monkeypatch.setattr(tc, "admit_managed_slotless_run", boom)
    _mount_all(ctrl, str(clean))
    pick_output_folder(ctrl, tmp_path / "out3")
    _unprepared_after_select(ctrl)  # 채택은 generate 안에서 일어난다(#932 B5)
    pushes.clear()
    res = ctrl.generate()
    assert res["ok"] is False and res["level"] == "warn"  # 구조화된 거절, raw 예외 아님
    assert len(pushes) == 1 and pushes[-1][1] == ctrl.snapshot()
    restored = ctrl.registry.load("공고서")
    assert ctrl.vm is not None and ctrl.vm.job.authority_id == restored.authority_id
    assert ctrl._seated_template_application_id is not None
    if target == "file":
        ctrl.load_data_path(str(clean))
    else:
        key = _pool_add(ctrl.pool_registry, "거절 뒤 데이터", {"path": str(clean)})
        assert ctrl.dispatch("load_pool", {"key": key})["ok"] is True
    assert ctrl.job_name == "공고서"  # admission 거절 뒤에도 같은 seated Work는 KEEP


@pytest.mark.parametrize("failpoint", ["manifest", "workspace", "staging"])
def test_managed_generation_exception_pushes_only_changed_identity(
    tmp_path, monkeypatch, failpoint,
):
    """Invocation 중 실제 identity가 바뀐 예외 종료만 fresh snapshot을 한 번 민다."""
    import hwpxfiller.external.slot_command_runner as slot_command_runner

    ctrl, pushes = _template_change_controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    coordinator = ctrl._template_change
    assert coordinator is not None and ctrl.vm is not None
    _mount_all(ctrl, _data_csv(tmp_path))
    pick_output_folder(ctrl, tmp_path / "out")

    def boom(*_a, **_k):
        raise OSError(f"{failpoint} I/O failed")

    if failpoint == "manifest":
        monkeypatch.setattr(coordinator, "_ensure_manifest", boom)
    elif failpoint == "workspace":
        monkeypatch.setattr(coordinator._workspace, "get_or_create", boom)
    else:
        monkeypatch.setattr(slot_command_runner, "stage_exact_applied_bytes", boom)
    # `adopted` 축이 살아 있으려면 채택이 generate 안에서 일어나야 한다(#932 B5) — 착석이
    # 이미 채택해 버리면 세 failpoint 가 전부 같은 답을 내 축이 vacuous 해진다.
    _unprepared_after_select(ctrl)
    pushes.clear()

    with pytest.raises(OSError, match=rf"{failpoint} I/O failed"):
        ctrl.generate()

    adopted = failpoint != "manifest"
    current = ctrl.snapshot()
    # S6-05(#812): slotless 는 발급(채택) 뒤에도 managed_hwpx=False — 채택 여부는
    # authority_id 로 직접 확인한다(push 계약은 그대로).
    assert current["managed_hwpx"] is False
    assert (ctrl.registry.load("공고서").authority_id != "") is adopted
    assert len(pushes) == int(adopted)
    if adopted:
        restored = ctrl.registry.load("공고서")
        assert ctrl.vm is not None and ctrl.vm.job.authority_id == restored.authority_id
        assert ctrl._seated_template_application_id is not None
        assert pushes[-1][1] == current
    assert ctrl._run is None and ctrl.vm is not None
    assert ctrl.vm._managed_template is None
    assert ctrl._generation_lock.acquire(blocking=False)
    ctrl._generation_lock.release()
    staging = tmp_path / "authority" / "run_staging"
    assert not staging.exists() or not list(staging.iterdir())


def test_release_then_cleanup_exception_pushes_released_snapshot_once(tmp_path):
    """RELEASE 뒤 cleanup 예외도 has_job=false를 한 번만 밀고 원래 예외를 유지한다."""
    ctrl, pushes = _template_change_controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    run_vm = ctrl.vm
    assert run_vm is not None
    _mount_all(ctrl, _data_csv(tmp_path))
    pick_output_folder(ctrl, tmp_path / "out")
    ctrl.registry.mutate(
        "공고서",
        lambda job: setattr(job, "filename_pattern", "교체-{{seq:001}}"),
    )

    class ReleaseErrorLock:
        def __init__(self):
            self.lock = threading.Lock()
            self.released = False

        def acquire(self, *, blocking=True):
            return self.lock.acquire(blocking=blocking)

        def release(self):
            self.lock.release()
            self.released = True
            raise OSError("generation lock cleanup failed")

    lock = ReleaseErrorLock()
    ctrl._generation_lock = lock
    _unprepared_after_select(ctrl)  # RELEASE 는 발급 순간의 대조에서 난다(#932 B5)
    pushes.clear()

    with pytest.raises(OSError, match="generation lock cleanup failed"):
        ctrl.generate()

    current = ctrl.snapshot()
    assert current["has_job"] is False and current["job_name"] == ""
    assert len(pushes) == 1 and pushes[-1][1] == current
    assert ctrl._run is None and run_vm._managed_template is None
    assert lock.released is True


def test_generation_recovers_after_repairing_bad_template(tmp_path):
    """#681 F4: bootstrap 이 qualification 에서 실패한 뒤 템플릿을 고쳐 다시 부르면 fresh id 로
    재부트스트랩돼 staged 경로를 낸다(고정 id 의 ObjectAlreadyExists 회복 불가 차단). 코디네이터
    메서드 단위 — 상위 review 게이트 소음 없이 F4 의 회복 자체를 잰다."""
    import shutil

    from hwpxfiller.application.jobs import load_job
    from hwpxfiller.application.slotless_run_bridge import SlotlessRunAdmissionError

    reg = _registry(tmp_path)
    coord = TemplateChangeCoordinator(reg, root=tmp_path / "authority", clock=_clock())
    bad = tmp_path / "bad.hwpx"
    bad.write_bytes(b"not a real hwpx zip")             # qualify 실패
    reg.save(Job(name="고칠작업", template_path=str(bad)))
    with pytest.raises(SlotlessRunAdmissionError):     # 최초: TEMPLATE_INITIALIZATION_REQUIRED
        coord.resolve_generation_template("고칠작업")
    shutil.copyfile(load_job(reg, "공고서").template_path, bad)  # 정상 hwpx 로 수리
    staged = coord.resolve_generation_template("고칠작업")       # fresh id → 재부트스트랩 성공
    assert Path(staged).exists()


def _drift(ctrl):
    """스냅샷이 실은 드리프트 (상태, 문안) — 존이 그 사실의 단일 자리다(#932 B5)."""
    zone = ctrl.snapshot()["template_change"]
    return zone["source_drift"], zone["source_drift_note"]


def test_source_drift_is_flagged_loudly_in_snapshot(tmp_path):
    """#681 F1: 부트스트랩된 Work 의 원본을 앱 밖에서 편집하면 스냅샷이 시끄럽게 표식한다
    — 생성은 캡처본을 쓰므로 「검토한 편집분이 조용히 안 반영」을 막는다(confirm-or-alarm)."""
    from hwpxfiller.application.jobs import load_job

    ctrl, _ = _template_change_controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.dispatch("template_check", {"request_id": "k1"})   # lazy bootstrap(캡처 확립)
    assert _drift(ctrl) == ("unchanged", None)              # 무편집 = 일관, 경고 없음
    tp = load_job(ctrl.registry, "공고서").template_path
    Path(tp).write_bytes(Path(tp).read_bytes() + b"EXTERNAL-EDIT")  # 앱 밖 편집(미가져오기)
    state, note = _drift(ctrl)
    assert state == "changed" and note and "캡처된 버전" in note   # 시끄러운 표식
    assert ctrl.snapshot()["template_change"]["actionable"] is True  # 존이 스스로 선다


def test_unbootstrapped_work_shows_no_source_drift(tmp_path):
    """미부트스트랩 Work 는 원본이 곧 실행본이라 일관 — 경고 없음(그리고 seat 에서 비싼
    resolve/stage 를 하지 않는다: applied-work 회귀 방지)."""
    ctrl, _ = _template_change_controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _unprepared_after_select(ctrl)                          # 미부트스트랩 상태(#932 B5)
    assert _drift(ctrl) == (None, None)                     # 판정 불성립 — 「없다」가 아니다


def test_managed_generation_reaches_execution_provenance_guard_live(tmp_path, monkeypatch):
    """#681: managed 생성이 evaluate_execution_provenance 를 **실제로** 호출한다(정적 name-ref
    가 아니라 라이브 도달) — S3-99 가 지적한 죽은 seam 이 실행 경로에서 살아 있음을 증명."""
    import hwpxfiller.application.slotless_run_bridge as bridge

    seen: list = []
    real = bridge.evaluate_execution_provenance

    def spy(base, current):
        seen.append((base, current))
        return real(base, current)

    monkeypatch.setattr(bridge, "evaluate_execution_provenance", spy)
    ctrl, _ = _template_change_controller(tmp_path)
    ctrl.dispatch("select_job", {"name": "공고서"})
    clean = tmp_path / "clean.csv"
    clean.write_text("bidNtceNm,presmptPrce\n전산장비,1000\n", encoding="utf-8")
    _mount_all(ctrl, str(clean))
    pick_output_folder(ctrl, tmp_path / "out")
    assert ctrl.generate()["ok"] is True
    assert seen, "generate 가 execution provenance guard 를 부르지 않았다(seam 죽음)"
    base, current = seen[0]
    assert base == current  # bootstrap base == current → EXECUTION_ALLOWED


def test_template_change_without_assembly_is_loud_not_silent(tmp_path):
    ctrl, _ = _controller(tmp_path)  # 미주입(테스트·CLI 소비자 기본)
    ctrl.dispatch("select_job", {"name": "공고서"})
    assert ctrl.snapshot()["template_change"]["supported"] is False
    with pytest.raises(ValueError):
        ctrl.dispatch("template_check", {"request_id": "k1"})
    with pytest.raises(ValueError):
        ctrl.dispatch("template_apply", {"change_token": "tok"})


# ============ 잔존 구간 표기의 생성 admission 차단(S8-04 #835 — D5 음성 대조) ============
def _write_notation_template(path, fields, markers=("{{#항목 특약 특약 사항}}", "{{/항목}}")):
    """누름틀은 컴파일됐는데 구간 표기가 남은 템플릿 — 실행되면 마커가 산출물에 샌다."""
    body = "".join(
        f'<hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>' for text in markers
    )
    field_runs = "".join(
        f'<hp:run><hp:ctrl><hp:fieldBegin name="{name}"/></hp:ctrl></hp:run>'
        f'<hp:run><hp:t>{{{{{name}}}}}</hp:t></hp:run>'
        '<hp:run><hp:ctrl><hp:fieldEnd/></hp:ctrl></hp:run>'
        for name in fields
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        f'{body}<hp:p>{field_runs}</hp:p></hs:sec>'
    ).encode()
    write_hwpx_package(
        path,
        HwpxPackage(entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": xml}),
    )


def test_generation_is_refused_while_structure_notation_is_uncompiled(tmp_path):
    """생성 admission 이 **실행 시점 bytes** 를 보고 잔존 표기를 시끄럽게 거절한다.

    상태 배지만으로는 실행이 막히지 않는다(홈은 알리고 admission 이 막는다). 통과하면
    산출물에 모든 선택지 + 마커 텍스트가 실린 구조적으로 틀린 문서가 나온다(#822 D5).
    """
    from hwpxfiller.application.slotless_run_bridge import (
        STRUCTURE_NOTATION_UNCOMPILED,
        SlotlessRunAdmissionError,
    )
    from hwpxfiller.domain.template_status import CompileState
    from hwpxfiller.webapp.screen_job import _ADMISSION_REJECT_TEXT

    reg = _registry(tmp_path)
    template = tmp_path / "notation.hwpx"
    _write_notation_template(template, ["공고명"])
    reg.save(Job(name="표기작업", template_path=str(template)))
    status = template_compile_status(str(template))
    assert (status.state, status.structure_marker_n) == (CompileState.PARTIAL, 2)

    coord = TemplateChangeCoordinator(reg, root=tmp_path / "authority", clock=_clock())
    with pytest.raises(SlotlessRunAdmissionError) as exc:
        coord.resolve_generation_template("표기작업")

    assert exc.value.code == STRUCTURE_NOTATION_UNCOMPILED
    # 코드 → 문안 맵이 이 거절을 재진술한다(조용한 fallback 「생성을 진행할 수 없습니다」 금지).
    text = _ADMISSION_REJECT_TEXT[exc.value.code]
    assert "구간 표기" in text and "변환" in text


def test_generation_proceeds_when_no_notation_is_left(tmp_path):
    """양성 대조 — 표기가 없는 같은 모양의 템플릿은 그대로 staged 경로를 낸다.

    새 검문이 「항상 빨강」이 아님을 못박는다. 표기를 실제로 변환한 뒤(S8-02)의 실행은
    slot-bearing 실행 자격이라는 **다른 게이트**의 소관이라 여기서 겨누지 않는다.
    """
    reg = _registry(tmp_path)
    template = tmp_path / "clean.hwpx"
    _write_notation_template(template, ["공고명"], markers=("계약 일반사항",))
    reg.save(Job(name="표기없음", template_path=str(template)))
    assert template_compile_status(str(template)).structure_marker_n == 0

    coord = TemplateChangeCoordinator(reg, root=tmp_path / "authority", clock=_clock())
    staged = coord.resolve_generation_template("표기없음")
    assert Path(staged).exists()


# ------------------- 마지막 사용 데이터의 부팅 자동 마운트(U3-07 · #880)
def test_file_mount_is_remembered_in_settings(tmp_path):
    """마운트 성공 = 기억 기록. 성분은 세션이 그때 포획한 한 벌 그대로다."""
    ctrl, _ = _controller(tmp_path)
    path = _data_csv(tmp_path)

    ctrl.load_data_path(path)

    assert load_last_data_source() == {
        "source": "file", "path": path, "sheet": "", "header_row": 0, "pool_key": "",
    }


def test_pool_mount_is_remembered_by_slot_key(tmp_path):
    """풀 겨눔도 같은 한 자리를 부른다 — 정체는 슬롯 키다(§5.3)."""
    ctrl, pool = _pool_controller(tmp_path)
    key = _pool_add(pool, "7월공고", {"path": _data_csv(tmp_path), "header_row": 1})

    assert ctrl.dispatch("load_pool", {"key": key})["ok"] is True

    remembered = load_last_data_source()
    assert remembered["source"] == "pool" and remembered["pool_key"] == key
    assert remembered["header_row"] == 1


def test_restart_mounts_the_remembered_file_on_the_first_snapshot(tmp_path):
    """재시작(새 컨트롤러)의 **첫 스냅샷**에 데이터가 이미 서 있다. 선택은 0건."""
    ctrl, _ = _controller(tmp_path)
    path = _data_csv(tmp_path)
    ctrl.load_data_path(path)

    fresh, pushes = _controller(tmp_path)
    assert fresh.snapshot()["has_data"] is False  # 마운트는 initial 이 한다
    snap = fresh.initial()

    assert snap["has_data"] is True and snap["record_count"] == 2
    assert snap["selected_count"] == 0 and snap["data_label"] == Path(path).name
    assert snap["data_notice"] is None
    # 작업 선택·실행 상태는 건드리지 않는다(자동 마운트는 「파일 다시 고르기」의 대역).
    assert snap["has_job"] is False and snap["last_run_job"] == ""
    # 결과는 첫 스냅샷 자체로 간다 — 그 전에 미는 푸시는 없다.
    assert pushes == []


def test_restart_mounts_the_remembered_pool_slot(tmp_path):
    """풀 기억도 같은 자리에서 산다 — 슬롯을 그때 다시 읽는다(재연결 반영)."""
    ctrl, pool = _pool_controller(tmp_path)
    key = _pool_add(pool, "7월공고", {"path": _data_csv(tmp_path)})
    assert ctrl.dispatch("load_pool", {"key": key})["ok"] is True

    fresh, _ = _pool_controller(tmp_path)
    snap = fresh.initial()

    assert snap["data_source_label"] == "등록 데이터: 7월공고"
    assert snap["record_count"] == 2 and snap["selected_count"] == 0
    assert snap["data_notice"] is None


def test_boot_mount_happens_once_and_does_not_undo_a_live_mount(tmp_path):
    """재진입(``initial`` 재호출)이 사용자가 지금 고른 데이터를 되돌리지 않는다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_data_csv(tmp_path))

    fresh, _ = _controller(tmp_path)
    fresh.initial()
    other = tmp_path / "다른.csv"
    other.write_text("bidNtceNm,presmptPrce\n한건,1\n", encoding="utf-8")
    fresh.load_data_path(str(other))

    assert fresh.initial()["data_label"] == "다른.csv"


def test_missing_remembered_file_leaves_an_empty_state_with_a_loud_reason(tmp_path):
    """소실은 조용한 빈 상태가 아니다 — 첫 화면이 사유를 싣고, 기억은 남아 재시도한다."""
    ctrl, _ = _controller(tmp_path)
    path = Path(_data_csv(tmp_path))
    ctrl.load_data_path(str(path))
    path.unlink()  # 외장 드라이브 분리·파일 이동

    fresh, _ = _controller(tmp_path)
    snap = fresh.initial()

    assert snap["has_data"] is False and snap["data_label"] == ""
    assert snap["data_notice"] == {
        "level": "warn",
        "text": (
            f"지난번에 사용한 데이터 파일을 찾을 수 없습니다: {path}. "
            "데이터를 다시 고르세요."
        ),
    }
    # 기억은 지우지 않는다 — 드라이브가 돌아오면 다음 부팅이 그대로 세운다.
    assert load_last_data_source()["path"] == str(path)
    path.write_text("bidNtceNm,presmptPrce\n돌아옴,1\n", encoding="utf-8")
    assert _controller(tmp_path)[0].initial()["record_count"] == 1


def test_deleted_pool_slot_restates_the_existing_refusal_text(tmp_path):
    """풀 실패는 기존 로드 관문의 문장을 그대로 이어 붙인다(새 문안 발명 금지)."""
    ctrl, pool = _pool_controller(tmp_path)
    key = _pool_add(pool, "7월공고", {"path": _data_csv(tmp_path)})
    assert ctrl.dispatch("load_pool", {"key": key})["ok"] is True
    pool.delete(key)

    fresh, _ = _pool_controller(tmp_path)
    snap = fresh.initial()

    assert snap["has_data"] is False
    assert snap["data_notice"] == {
        "level": "warn",
        "text": (
            "지난번에 사용한 데이터를 다시 불러오지 못했습니다. "
            "등록 데이터를 찾을 수 없습니다(이미 삭제된 항목)."
        ),
    }
    assert load_last_data_source()["pool_key"] == key  # 기억 유지


def test_no_memory_boots_exactly_as_before(tmp_path):
    """이 키가 없는 기존 ``settings.json`` 은 그대로 빈 부팅으로 산다."""
    ctrl, pushes = _controller(tmp_path)

    snap = ctrl.initial()

    assert load_last_data_source() is None
    assert snap["has_data"] is False and snap["data_notice"] is None
    assert pushes == []


def test_remembered_descriptor_rejects_half_written_components(tmp_path):
    """반쪽 descriptor 는 조용히 저장되지 않는다 — 손상 저장분은 미저장과 같이 다룬다."""
    with pytest.raises(ValueError):
        save_last_data_source(source="file", path="  ")
    with pytest.raises(ValueError):
        save_last_data_source(source="pool", pool_key="")
    with pytest.raises(ValueError):
        save_last_data_source(source="registry", path="x")
    assert load_last_data_source() is None


# ------------------------------- 계약 목록(pclm) 마운트 세 길(#937)
#
# 세션 소스 축에 ``pclm`` 이 늘었다. 그 축이 서는 길은 셋이고 전부 여기서 잰다: 풀
# 겨눔(슬롯 정체는 그대로 pool) · 작업 결속(durable, 종류가 갈래를 가른다) · 부팅 복원과
# 재마운트(기억은 db+뷰 한 벌).
_PCLM_VIEW = "v_통합_v1"
# 라벨·통지가 지는 것은 **제목**이다 — 내부 이름은 성분(경로·시트·키)에만 산다.
_PCLM_TITLE = "통합"


def _pclm_db(
    tmp_path,
    *,
    name: str = "pclm.db",
    rows=(("전산장비", ""), ("사무비품", "2000000")),
    view: str = _PCLM_VIEW,
) -> str:
    """pclm 이 내는 모양을 흉내 낸 SQLite — 표 하나 위에 계약면 뷰를 얹는다.

    열 이름을 이 파일의 픽스처 작업 소스 키에 맞춘다: 계약 목록도 엑셀과 **같은 후보·호환
    판정**을 지나므로(열 이름이 곧 어휘), 다른 이름을 쓰면 재는 축이 조용히 호환 판정으로
    바뀐다.
    """
    db = tmp_path / name
    connection = sqlite3.connect(db)
    connection.execute('CREATE TABLE 계약 ("bidNtceNm" TEXT, "presmptPrce" TEXT);')
    connection.executemany("INSERT INTO 계약 VALUES (?, ?);", rows)
    connection.execute(f'CREATE VIEW "{view}" AS SELECT * FROM 계약;')
    connection.commit()
    connection.close()
    return str(db)


def _bind_pclm(registry, db: str, *, name: str = "공고서", view: str = _PCLM_VIEW) -> None:
    """작업의 durable 결속을 계약 목록 한 벌로 갈아 끼운다(db=경로 · 뷰=시트 · 0 · pclm)."""
    registry.save(
        replace(
            registry.load(name),
            data_path=db, data_sheet=view, data_header_row=0, data_kind="pclm",
        ),
        allow_overwrite=True,
    )


def test_pool_targeting_a_pclm_reference_captures_the_kind_with_the_reference(tmp_path):
    """풀 겨눔의 정체는 그대로 슬롯(``pool``)이고, 갈리는 것은 **가리키는 종류**다.

    두 축을 한 값으로 뭉개면(출처를 ``pclm`` 으로 세우면) 재마운트가 슬롯을 잃고, 종류를
    흘리면 결속 판정이 같은 경로 문자열로 엑셀과 계약 목록을 뭉갠다.
    """
    ctrl, pool = _pool_controller(tmp_path)
    db = _pclm_db(tmp_path)
    key = _pool_add(pool, "계약목록", {"db": db, "view": _PCLM_VIEW}, kind="pclm")

    res = ctrl.dispatch("load_pool", {"key": key})

    assert res == {"ok": True, "label": "등록 데이터: 계약목록"}
    assert ctrl.data_source == "pool" and ctrl.data_pool_key == key
    assert (ctrl.data_path, ctrl.data_sheet, ctrl.data_header_row, ctrl.data_kind) == (
        db, _PCLM_VIEW, 0, "pclm",
    )
    snap = ctrl.snapshot()
    assert snap["record_count"] == 2 and snap["selected_count"] == 0
    assert snap["data_target"] == {
        "path": db, "sheet": _PCLM_VIEW, "origin": "pool", "kind": "pclm",
    }


def test_mount_pclm_seats_every_session_component(tmp_path):
    """직접 마운트 — 성분 한 벌·라벨·소스 키·선택 초기화가 파일 마운트와 **같은 순서**다."""
    ctrl, _ = _controller(tmp_path)
    db = _pclm_db(tmp_path)

    ctrl._mount_pclm(db, _PCLM_VIEW)

    assert ctrl.data_source == "pclm" and ctrl.data_pool_key == ""
    assert (ctrl.data_path, ctrl.data_sheet, ctrl.data_header_row, ctrl.data_kind) == (
        db, _PCLM_VIEW, 0, "pclm",
    )
    # 라벨은 면을 병기한다 — db 하나에 계약면이 넷이라 파일 이름만으론 무엇이 섰는지 모른다.
    # 병기하는 것은 제목이다: 사람이 읽는 한 줄이라 내부 이름(v_…)이 새면 안 된다.
    assert ctrl.data_label == f"pclm.db · {_PCLM_TITLE}"
    snap = ctrl.snapshot()
    assert snap["data_source_label"] == f"계약 목록: pclm.db · {_PCLM_TITLE}"
    assert "v_" not in snap["data_source_label"]
    assert snap["record_count"] == 2 and snap["selected_count"] == 0
    assert snap["data_target"]["kind"] == "pclm"
    # 소스 일치 키는 파일 접두와 갈린다(결정 28) — 종류가 정체의 성분이다.
    assert ctrl._data_key.startswith("pclm:") and _PCLM_VIEW in ctrl._data_key


def test_mount_pclm_refuses_an_empty_view_before_destroying_the_current_mount(tmp_path):
    """0행은 조용한 빈 세션이 아니다 — 거절이고, 서 있던 데이터는 그대로 산다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.load_data_path(_data_csv(tmp_path))
    empty = _pclm_db(tmp_path, name="빈.db", rows=())

    with pytest.raises(ValueError, match="행이 없습니다"):
        ctrl._mount_pclm(empty, _PCLM_VIEW)

    assert ctrl.data_source == "file" and ctrl.snapshot()["record_count"] == 2


def test_mount_pclm_lets_a_missing_database_speak_for_itself(tmp_path):
    """읽기 실패는 삼키지 않고 그대로 올린다 — 호출자가 자기 채널로 재진술한다."""
    ctrl, _ = _controller(tmp_path)

    with pytest.raises(FileNotFoundError, match="찾지 못했습니다"):
        ctrl._mount_pclm(str(tmp_path / "없다.db"), _PCLM_VIEW)


def test_selecting_a_pclm_bound_job_mounts_its_view_and_then_stands_still(tmp_path):
    """작업 → 데이터 방향이 종류를 관통한다. 이미 서 있으면 다시 읽지 않는다."""
    ctrl, _ = _controller(tmp_path)
    db = _pclm_db(tmp_path)
    _bind_pclm(ctrl.registry, db)

    ctrl.dispatch("select_job", {"name": "공고서"})

    assert ctrl.data_kind == "pclm" and ctrl.records[0]["bidNtceNm"] == "전산장비"
    assert ctrl.snapshot()["data_notice"]["text"] == (
        f"이 작업에 연결된 데이터 'pclm.db · {_PCLM_TITLE}' 을(를) 불러왔습니다. "
        "항목 선택은 초기화됐습니다."
    )
    ctrl.dispatch("set_all", {})
    ctrl.dispatch("select_job", {"name": ""})
    ctrl.dispatch("select_job", {"name": "공고서"})
    # 같은 데이터가 서 있으면 재읽기가 없다 — 아무것도 안 바꾸는 마운트가 선택을 지우면
    # 그 자체가 조용한 파기다.
    assert ctrl.snapshot()["selected_count"] == 2
    assert ctrl.snapshot()["data_notice"] is None


def test_selecting_a_pclm_bound_job_with_a_missing_db_reuses_the_missing_text(tmp_path):
    """계약 목록 db 도 사라질 수 있는 파일이다 — 끊김 판정·문안은 같은 한 자리를 쓴다."""
    ctrl, _ = _controller(tmp_path)
    db = _pclm_db(tmp_path)
    _bind_pclm(ctrl.registry, db)
    Path(db).unlink()

    ctrl.dispatch("select_job", {"name": "공고서"})

    assert ctrl.data_source == ""  # 마운트 없음(작업 선택 자체는 성사)
    assert ctrl.snapshot()["data_notice"] == {
        "level": "warn",
        "text": (
            f"이 작업에 연결된 데이터 파일을 찾을 수 없습니다: {db}. "
            "데이터를 다시 고른 뒤 작업을 저장하세요."
        ),
    }


def test_binding_mount_refuses_an_unknown_kind_out_loud(tmp_path):
    """이름 없는 종류를 파일 갈래로 흘려보내지 않는다 — 사유가 그 자리에서 선다."""
    ctrl, _ = _controller(tmp_path)
    ctrl.registry.save(
        replace(
            ctrl.registry.load("공고서"),
            data_path=_data_csv(tmp_path), data_kind="미래소스",
        ),
        allow_overwrite=True,
    )

    ctrl.dispatch("select_job", {"name": "공고서"})

    assert ctrl.data_source == ""
    assert "알 수 없는 데이터 결속 종류입니다" in ctrl.snapshot()["data_notice"]["text"]


def test_remount_reruns_the_pclm_branch_with_the_captured_reference(tmp_path):
    """새로고침도 새 마운트 경로를 만들지 않는다 — 포획해 둔 db+뷰를 그대로 되돌려 준다."""
    ctrl, _ = _controller(tmp_path)
    db = _pclm_db(tmp_path)
    ctrl._mount_pclm(db, _PCLM_VIEW)

    connection = sqlite3.connect(db)
    connection.execute("INSERT INTO 계약 VALUES ('추가건', '3000');")
    connection.commit()
    connection.close()

    res = ctrl.dispatch("remount_data", {})

    assert res == {"ok": True, "label": f"계약 목록: pclm.db · {_PCLM_TITLE}"}
    assert ctrl.snapshot()["record_count"] == 3


def test_pclm_mount_is_remembered_and_restored_on_the_first_snapshot(tmp_path):
    """기억은 db+뷰 한 벌이고 출처 축이 어느 어댑터로 읽을지를 말한다."""
    ctrl, _ = _controller(tmp_path)
    db = _pclm_db(tmp_path)
    ctrl._mount_pclm(db, _PCLM_VIEW)

    assert load_last_data_source() == {
        "source": "pclm", "path": db, "sheet": _PCLM_VIEW,
        "header_row": 0, "pool_key": "",
    }

    fresh, pushes = _controller(tmp_path)
    snap = fresh.initial()

    assert snap["has_data"] is True and snap["record_count"] == 2
    assert snap["data_source_label"] == f"계약 목록: pclm.db · {_PCLM_TITLE}"
    assert snap["selected_count"] == 0 and snap["data_notice"] is None
    assert pushes == []  # 결과는 첫 스냅샷 자체가 나른다


def test_missing_remembered_pclm_db_restates_the_existing_reason(tmp_path):
    """부팅 복원의 실패도 새 채널을 만들지 않는다 — 파일 부재는 같은 술어·같은 문안."""
    ctrl, _ = _controller(tmp_path)
    db = _pclm_db(tmp_path)
    ctrl._mount_pclm(db, _PCLM_VIEW)
    Path(db).unlink()

    snap = _controller(tmp_path)[0].initial()

    assert snap["has_data"] is False
    assert snap["data_notice"] == {
        "level": "warn",
        "text": (
            f"지난번에 사용한 데이터 파일을 찾을 수 없습니다: {db}. 데이터를 다시 고르세요."
        ),
    }
    assert load_last_data_source()["path"] == db  # 기억은 지우지 않는다


def test_remembered_pclm_descriptor_needs_both_db_and_view(tmp_path):
    """반쪽 계약 목록 기억은 조용히 저장되지 않는다 — 뷰 없이는 무엇을 열지 모른다."""
    with pytest.raises(ValueError, match="DB 경로와 뷰"):
        save_last_data_source(source="pclm", path="C:/d/pclm.db", sheet="")
    with pytest.raises(ValueError, match="DB 경로와 뷰"):
        save_last_data_source(source="pclm", path="", sheet=_PCLM_VIEW)
    assert load_last_data_source() is None


def test_a_pclm_bound_job_is_no_candidate_for_an_excel_mount_of_the_same_path(tmp_path):
    """종류가 갈리면 다른 데이터다 — 경로 문자열이 같아도 후보에 섞이지 않는다(교차 불일치)."""
    ctrl, _ = _controller(tmp_path)
    db = _pclm_db(tmp_path)
    _bind_pclm(ctrl.registry, db)

    # 같은 경로를 엑셀 종류로 마운트한 것처럼 세션 성분만 세운다(파일 파싱은 이 축이 아니다).
    ctrl.load_data_path(_data_csv(tmp_path))
    ctrl.data_path, ctrl.data_sheet, ctrl.data_kind = db, _PCLM_VIEW, ""
    assert [j.name for j in ctrl._bound_jobs(list(ctrl.registry.list_jobs()))] == []

    ctrl.data_kind = "pclm"
    assert [j.name for j in ctrl._bound_jobs(list(ctrl.registry.list_jobs()))] == ["공고서"]


def test_a_pclm_bound_job_that_lost_a_column_stays_visible_as_needs_action(tmp_path):
    """호환 판정은 결속을 대신하지 않는다 — 열이 사라지면 「확인 필요」로 남는다(사라짐 금지)."""
    ctrl, _ = _controller(tmp_path)
    thin = tmp_path / "결손.db"
    connection = sqlite3.connect(thin)
    connection.execute('CREATE TABLE 계약 ("bidNtceNm" TEXT);')
    connection.execute("INSERT INTO 계약 VALUES ('전산장비');")
    connection.execute(f'CREATE VIEW "{_PCLM_VIEW}" AS SELECT * FROM 계약;')
    connection.commit()
    connection.close()
    _bind_pclm(ctrl.registry, str(thin))

    ctrl.dispatch("select_job", {"name": "공고서"})
    snap = ctrl.snapshot()

    assert snap["candidates"]["top"] == []
    assert snap["candidates"]["needs_count"] == 1
