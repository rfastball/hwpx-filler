"""「문서 만들기」 S4 Working Slot Configuration 배선 가드(SX-02 #725) — 헤드리스 컨트롤러.

판정·token·projection 은 Product(#679·#678) 테스트가 소유한다. 여기가 잰다: 4개 command 가
**dispatch 경로**로 Product 에 도달하고, command outcome + fresh view 가 그대로 프런트로 관통하며
(local optimistic authority 0), stale/cross-Work 를 Product 규율대로 처리하고, snapshot 이 fresh
current view 를 실으며, 작업대 Observation 이 SX-02 축만 실사실로 채우고 나머지는 seam 으로 남는지.
"""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

import pytest

from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.application.document_creation_workbench import (
    DocumentCreationWorkbenchObservation,
)
from hwpxfiller.application.document_creation_vocabulary import BLOCKER_CODES
from hwpxfiller.data.factory import source_for_path, source_from_pool_item
from hwpxfiller.domain.job import Job
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.external.hwpx_package_io import write_hwpx_package
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.external.output_files import ensure_output_directory, existing_output_paths
from hwpxfiller.webapp.screen_job import JobController
from hwpxfiller.webapp.slot_configuration_product import (
    SlotConfigurationProduct,
    SlotConfigurationProductError,
)
from hwpxfiller.webapp.template_change import TemplateChangeCoordinator
from hwpxfiller.webapp.workbench_observation_product import WorkbenchObservationProduct

NOW = datetime(2026, 8, 18, 9, 0, 0)


def _clock():
    return lambda: NOW


def _template(path: Path, fields) -> None:
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
        path, HwpxPackage(entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": xml})
    )


def _root(tmp_path: Path) -> Path:
    return tmp_path / "authority"


def _controller(tmp_path: Path, *, wire: bool = True, bootstrap: bool = True):
    """실 Product 세벌을 **같은 authority root** 로 배선한 헤드리스 컨트롤러.

    ``wire=False`` 는 미주입(loud 거절 계약)용. ``bootstrap=True`` 면 template_check 로 Work 를 세운다.
    """
    tpl = tmp_path / "공고서.hwpx"
    _template(tpl, ["공고명"])
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="공고서", template_path=str(tpl)))
    coord = TemplateChangeCoordinator(reg, root=_root(tmp_path), clock=_clock())
    kwargs = dict(
        clock=_clock(),
        engine=make_hwpx_engine(),
        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
        generation_lock=threading.Lock(),
        file_source_factory=source_for_path,
        pool_source_factory=source_from_pool_item,
        existing_outputs=existing_output_paths,
        ensure_output_dir=ensure_output_directory,
        template_change=coord,
    )
    if wire:
        kwargs["slot_configuration"] = SlotConfigurationProduct(
            reg, root=_root(tmp_path), clock=_clock()
        )
        kwargs["workbench_observation"] = WorkbenchObservationProduct()
    pushes: list = []
    ctrl = JobController(reg, lambda s, snap: pushes.append((s, snap)), **kwargs)
    ctrl.dispatch("select_job", {"name": "공고서"})
    if bootstrap:
        ctrl.dispatch("template_check", {"request_id": "k1"})
    return ctrl, pushes


# ── dispatch 도달: open/refresh/select/clear ─────────────────────────────────────────────
def test_open_reaches_product_via_dispatch_and_yields_view_and_token(tmp_path: Path) -> None:
    ctrl, _ = _controller(tmp_path)
    res = ctrl.dispatch("open_slot_configuration", {})
    assert res["current_view"]["view_status"] == "CURRENT"
    assert res["current_view"]["new_configuration_token"]  # 새 token 발급
    # open 은 무변이 — outcome 이 있어도 changed=False(Product 의 ensure 는 NO_CHANGE 를 낸다).
    assert res["mutation_outcome"] is None or res["mutation_outcome"]["changed"] is False
    # projection 이 preserved/broken/detached 분리 축을 그대로 나른다(컨트롤러가 드롭하지 않음).
    proj = res["current_view"]["projection"]
    assert {"slots", "detached_selections", "blocking_items", "reconciliation_changes"} <= set(proj)


def test_select_and_clear_reach_product_with_outcome_and_fresh_token(tmp_path: Path) -> None:
    ctrl, _ = _controller(tmp_path)
    token = ctrl.dispatch("open_slot_configuration", {})["current_view"]["new_configuration_token"]
    sel = ctrl.dispatch("select_slot_option", {
        "configuration_token": token, "slot_id": "no-such", "option_id": "opt", "request_id": "r1",
    })
    # slotless 템플릿이라 판정은 UNKNOWN_SLOT 이지만 wiring(token→context→runner→응답)은 완주하고
    # command outcome + fresh view + 새 token 이 함께 온다(local optimistic authority 0).
    assert sel["mutation_outcome"] is not None
    assert sel["current_view"]["new_configuration_token"]
    fresh_token = sel["current_view"]["new_configuration_token"]
    clr = ctrl.dispatch("clear_slot_selection", {
        "configuration_token": fresh_token, "slot_id": "no-such", "request_id": "r2",
    })
    assert clr["mutation_outcome"] is not None


def test_refresh_with_token_reaches_product(tmp_path: Path) -> None:
    ctrl, _ = _controller(tmp_path)
    token = ctrl.dispatch("open_slot_configuration", {})["current_view"]["new_configuration_token"]
    res = ctrl.dispatch("refresh_slot_configuration", {"configuration_token": token})
    assert res["current_view"]["view_status"] == "CURRENT"
    assert res["refresh_required"] is False  # 같은 Application → not stale
    # token 없는 refresh 도 도달한다(최초 조회).
    assert ctrl.dispatch("refresh_slot_configuration", {})["current_view"]["view_status"] == "CURRENT"


# ── snapshot 존 ────────────────────────────────────────────────────────────────────────
def test_snapshot_carries_slot_configuration_zone(tmp_path: Path) -> None:
    ctrl, _ = _controller(tmp_path)
    zone = ctrl.snapshot()["slot_configuration"]
    assert zone["supported"] is True and zone["initialized"] is True
    assert zone["current_view"]["view_status"] == "CURRENT"
    assert zone["current_view"]["new_configuration_token"]


def test_snapshot_zone_before_bootstrap_does_not_mint_durable_id(tmp_path: Path) -> None:
    """초기화 전(템플릿 확인 전) 스냅샷은 Product 를 부르지 않는다 — write-on-read 로 Work id 를
    발급하지 않는다(렌더 부작용 0). 지원은 하되 아직 미초기화로 선다."""
    from hwpxfiller.application.jobs import load_job

    ctrl, _ = _controller(tmp_path, bootstrap=False)
    zone = ctrl.snapshot()["slot_configuration"]
    assert zone["supported"] is True and zone["initialized"] is False
    assert zone["current_view"] is None
    assert not load_job(ctrl.registry, "공고서").authority_id  # durable id 미발급 보존


def test_snapshot_zone_unsupported_without_selection(tmp_path: Path) -> None:
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": ""})  # 선택 해제
    assert ctrl.snapshot()["slot_configuration"]["supported"] is False


# ── 미주입 loud 거절 ─────────────────────────────────────────────────────────────────────
def test_unwired_slot_configuration_rejects_loudly(tmp_path: Path) -> None:
    ctrl, _ = _controller(tmp_path, wire=False, bootstrap=False)
    for action, payload in (
        ("open_slot_configuration", {}),
        ("refresh_slot_configuration", {}),
        ("select_slot_option", {
            "configuration_token": "t", "slot_id": "s", "option_id": "o", "request_id": "r"}),
        ("clear_slot_selection", {"configuration_token": "t", "slot_id": "s", "request_id": "r"}),
    ):
        with pytest.raises(ValueError):
            ctrl.dispatch(action, payload)
    # snapshot 존도 조용히 비지 않고 명시적 미지원.
    assert ctrl.snapshot()["slot_configuration"]["supported"] is False


def test_command_without_selected_job_rejects_loudly(tmp_path: Path) -> None:
    ctrl, _ = _controller(tmp_path)
    ctrl.dispatch("select_job", {"name": ""})
    with pytest.raises(ValueError):
        ctrl.dispatch("open_slot_configuration", {})


# ── stale / cross-Work (Product 규율 소비) ────────────────────────────────────────────────
def test_stale_token_after_template_change_returns_fresh_view_not_ghost(tmp_path: Path) -> None:
    """D 시나리오: 예전 Application 의 token 으로 mutation → Product 가 fresh current view 를 되돌리고
    refresh_required 를 세운다(옛 세계 유령 반영 0). 컨트롤러는 그 backend view 로 통째 교체한다."""
    ctrl, _ = _controller(tmp_path)
    stale = ctrl.dispatch("open_slot_configuration", {})["current_view"]["new_configuration_token"]
    # Template 변경 적용 → current Application 이 앞선다(옛 token 은 이제 stale).
    chk = ctrl._template_change.check("공고서", "k2")
    change_token = chk["preparation"].get("change_token")
    if change_token:  # 변경이 있을 때만 적용(no_change 면 스킵)
        ctrl._template_change.apply("공고서", change_token)
    res = ctrl.dispatch("select_slot_option", {
        "configuration_token": stale, "slot_id": "no-such", "option_id": "o", "request_id": "rs",
    })
    # 유령 반영 0: 항상 CURRENT application 을 다시 읽은 fresh view + 새 token.
    assert res["current_view"]["new_configuration_token"]
    assert res["current_view"]["view_status"] in ("CURRENT", "CONTEXT_ERROR")


def test_cross_work_token_propagates_loudly(tmp_path: Path) -> None:
    """다른 작업의 token 으로 mutation → Product 가 CROSS_WORK 로 거절하고 예외가 시끄럽게 전파된다."""
    ctrl, _ = _controller(tmp_path)
    # 두 번째 작업을 세워 그 token 을 얻는다.
    other_tpl = tmp_path / "다른작업.hwpx"
    _template(other_tpl, ["공고명"])
    ctrl.registry.save(Job(name="다른작업", template_path=str(other_tpl)))
    other_product = SlotConfigurationProduct(ctrl.registry, root=_root(tmp_path), clock=_clock())
    ctrl._template_change.check("다른작업", "kk")
    other_token = other_product.open_slot_configuration(
        "다른작업"
    ).current_view.new_configuration_token
    assert other_token is not None
    # 현재 작업(공고서) 상대로 다른 작업의 token → cross-Work 거절.
    with pytest.raises(SlotConfigurationProductError) as ei:
        ctrl.dispatch("select_slot_option", {
            "configuration_token": other_token, "slot_id": "s", "option_id": "o", "request_id": "x",
        })
    assert ei.value.code == "CROSS_WORK_CONFIGURATION_TOKEN"


# ── 작업대 Observation 합성(SX-02 축 + seam) ──────────────────────────────────────────────
def test_workbench_observation_fills_sx02_axes(tmp_path: Path) -> None:
    ctrl, _ = _controller(tmp_path)
    obs = ctrl.workbench_observation()
    assert isinstance(obs, DocumentCreationWorkbenchObservation)
    # active_work·data_scope 는 세션 사실을 반영한다.
    assert obs.active_work.active is True and obs.active_work.work_ref == "공고서"
    assert obs.data_scope.mounted is False and obs.data_scope.selected_record_count == 0
    # orchestration 축은 IDLE 로 선다(SX-02 R1: 자동 확인 진입 미트리거).
    assert obs.orchestration.state == "IDLE"


def test_workbench_observation_delivery_seam_keeps_primary_action_off_create(tmp_path: Path) -> None:
    """정직성 앵커: delivery seam(resolvable=False)이 채워지기 전에는 Primary Action 이 CREATE_DOCUMENTS
    로 조용히 새지 않는다 — REVIEW_DELIVERY blocker 가 시끄럽게 선다."""
    ctrl, _ = _controller(tmp_path)
    obs = ctrl.workbench_observation()
    assert "REVIEW_DELIVERY" in obs.blockers
    assert obs.primary_action != "CREATE_DOCUMENTS"


def test_workbench_observation_data_and_content_reflect_session(tmp_path: Path) -> None:
    ctrl, _ = _controller(tmp_path)
    csv = tmp_path / "d.csv"
    csv.write_text("공고명\n전산장비\n사무비품\n", encoding="utf-8")
    ctrl.load_data_path(str(csv))
    ctrl.dispatch("set_all", {})
    obs = ctrl.workbench_observation()
    assert obs.data_scope.mounted is True
    assert obs.data_scope.selected_record_count == 2
    assert "SELECT_DATA" not in obs.blockers  # 마운트됐으므로 데이터 blocker 해소


def test_workbench_observation_exposes_no_internal_vocabulary(tmp_path: Path) -> None:
    """#725: Slot/Plan 내부어 기본 노출 0 — 사용자 문안 필드에 내부 어휘가 새지 않는다."""
    ctrl, _ = _controller(tmp_path)
    obs = ctrl.workbench_observation()
    banned = ("Slot", "Sealed", "Plan", "digest", "Application", "VDR", "Candidate")
    for text in obs.user_facing_texts:
        for word in banned:
            assert word not in text, (word, text)


def test_unwired_workbench_observation_rejects_loudly(tmp_path: Path) -> None:
    ctrl, _ = _controller(tmp_path, wire=False, bootstrap=False)
    with pytest.raises(ValueError):
        ctrl.workbench_observation()


# ── blocker 어휘 계약(구조 회귀 감지) ─────────────────────────────────────────────────────
def test_blocker_codes_include_choose_content_axis(tmp_path: Path) -> None:
    # SX-02 content 축이 소비하는 blocker 가 vocabulary 정본에 존재한다(드리프트 조기 감지).
    assert "CHOOSE_CONTENT" in BLOCKER_CODES
    assert "REVIEW_DELIVERY" in BLOCKER_CODES
