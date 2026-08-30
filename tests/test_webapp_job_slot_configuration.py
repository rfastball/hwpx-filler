"""「문서 만들기」 S4 Working Slot Configuration 배선 가드(SX-02 #725) — 헤드리스 컨트롤러.

판정·token·projection 은 Product(#679·#678) 테스트가 소유한다. 여기가 잰다: 4개 command 가
**dispatch 경로**로 Product 에 도달하고, command outcome + fresh view 가 그대로 프런트로 관통하며
(local optimistic authority 0), stale/cross-Work 를 Product 규율대로 처리하고, snapshot 이 fresh
current view 를 실으며, 작업대 Observation 이 SX-02 축만 실사실로 채우고 나머지는 seam 으로 남는지.
"""
from __future__ import annotations

import dataclasses
import threading
from datetime import datetime
from pathlib import Path

import pytest

from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.application.document_creation_workbench import (
    DocumentCreationWorkbenchObservation,
)
from hwpxfiller.application.document_creation_vocabulary import BLOCKER_CODES
from hwpxfiller.application.slotless_run_bridge import SlotlessRunAdmissionError
from hwpxfiller.application.work_template_state import PREP_INTERRUPTED
from hwpxfiller.external.work_template_store import AtomicWorkTemplateStateStore
from hwpxfiller.data.factory import source_for_path, source_from_pool_item
from hwpxfiller.domain.job import Job
from hwpxfiller.external.dataset_store import DatasetPoolRegistry
from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.external.hwpx_package_io import write_hwpx_package
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.external.output_files import ensure_output_directory, existing_output_paths
from hwpxfiller.webapp.action_registry import validate_dispatch
from hwpxfiller.webapp.screen_job import JobController
from hwpxfiller.webapp.slot_configuration_product import (
    SlotConfigurationProduct,
    SlotConfigurationProductError,
)
from hwpxfiller.webapp.template_change import TemplateChangeCoordinator
from hwpxfiller.webapp.workbench_observation_product import WorkbenchObservationProduct

from tests.test_slot_configuration_product import _two_slot_template

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
    ``bootstrap=False`` 는 **준비 이전** 상태를 쓰는 갈래인데, 선택이 준비를 지게 된 뒤로
    (#932 B5) 착석만으로는 그 상태가 안 남는다 — 그 갈래를 쓰는 테스트가 재는 것이 「준비
    전」 계약이므로 여기서 명시로 되만든다(전제가 바뀌었을 때 단언을 지우지 않는다).
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
    else:
        reg.mutate("공고서", lambda job: setattr(job, "authority_id", ""))
        if ctrl.vm is not None:
            ctrl.vm.job.authority_id = ""
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
    # 이전 선택의 운명(#777)도 같은 축이다 — 키가 사라지면 프런트가 그릴 근거를 잃는다.
    proj = res["current_view"]["projection"]
    assert {
        "slots",
        "detached_selections",
        "blocking_items",
        "reconciliation_changes",
        "retained_selections",
    } <= set(proj)


def test_select_reaches_product_with_outcome_and_fresh_token(tmp_path: Path) -> None:
    ctrl, _ = _controller(tmp_path)
    token = ctrl.dispatch("open_slot_configuration", {})["current_view"]["new_configuration_token"]
    sel = ctrl.dispatch("select_slot_option", {
        "configuration_token": token, "slot_id": "no-such", "option_id": "opt", "request_id": "r1",
    })
    # slotless 템플릿이라 판정은 UNKNOWN_SLOT 이지만 wiring(token→context→runner→응답)은 완주하고
    # command outcome + fresh view + 새 token 이 함께 온다(local optimistic authority 0).
    assert sel["mutation_outcome"] is not None
    assert sel["current_view"]["new_configuration_token"]


def test_clear_slot_selection_is_not_a_registered_action(tmp_path: Path) -> None:
    """#903: 선택 해제 제품 동사는 없다 — 미등록 액션으로 시끄럽게 거절된다.

    유일한 트리거였던 detached 정리 버튼은 SG-01(#733) 이후 렌더될 수 없었고(승계 선언집합은
    AUTO_KEEP 만 싣는데 AUTO_KEEP 은 그 Option 이 target 에 있어야 성립한다), EXACTLY_ONE
    제어면에서 「선택 비우기」는 완성 상태를 blocked 로 되돌릴 뿐이라 대체 트리거도 없다.
    """
    ctrl, _ = _controller(tmp_path)
    token = ctrl.dispatch("open_slot_configuration", {})["current_view"]["new_configuration_token"]
    # 컨트롤러(핸들러 부재)와 dispatch 계약(액션 미등록) 양쪽에서 사라졌다.
    with pytest.raises(ValueError, match="알 수 없는 작업 화면 액션"):
        ctrl.dispatch("clear_slot_selection", {
            "configuration_token": token, "slot_id": "no-such", "request_id": "r2",
        })
    with pytest.raises(ValueError, match="등록되지 않은"):
        validate_dispatch("job", "clear_slot_selection", {
            "configuration_token": token, "slot_id": "no-such", "request_id": "r2",
        })


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
    assert zone["error"] is None
    assert zone["current_view"]["view_status"] == "CURRENT"
    assert zone["current_view"]["new_configuration_token"]


def test_snapshot_projects_slot_initialization_failure_and_read_only_recovery(
    tmp_path: Path,
) -> None:
    ctrl, _ = _controller(tmp_path)
    ctrl.snapshot()  # token secret 생성
    secret_path = _root(tmp_path) / "slot_token_secret.json"
    original = secret_path.read_text("utf-8")
    secret_path.write_text("{corrupt", "utf-8")

    expected_error = {
        "code": "INVALID_CONFIGURATION_TOKEN",
        "message": "포함할 내용을 불러오지 못했습니다. 다시 불러오세요.",
        "action": {"key": "refresh", "label": "다시 불러오기"},
    }
    zone = ctrl.snapshot()["slot_configuration"]
    assert zone["supported"] is True and zone["initialized"] is False
    assert zone["current_view"] is None
    assert zone["error"] == expected_error
    assert "token secret" not in repr(zone["error"])
    assert ctrl.snapshot()["slot_configuration"]["error"] == expected_error

    secret_path.write_text(original, "utf-8")
    recovered = ctrl.snapshot()["slot_configuration"]
    assert recovered["initialized"] is True
    assert recovered["error"] is None
    assert recovered["current_view"]["view_status"] == "CURRENT"


def test_snapshot_render_paths_never_mutate_durable_s4(tmp_path: Path, monkeypatch) -> None:
    # #744: passive 렌더(스냅샷 slot_configuration 존 + workbench_observation)는 read-only
    # projection 을 써야 한다 — open(ensure)의 successor reconciliation 물질화로 durable S4 를
    # 바꾸지 않는다. ensure 호출을 spy 해 렌더 경로가 0, 명시적 command 만 ensure 를 타는지 판정한다.
    import hwpxfiller.webapp.slot_configuration_product as mod

    calls = {"ensure": 0}
    real = mod.ensure_current_slot_configuration

    def spy(*a, **k):
        calls["ensure"] += 1
        return real(*a, **k)

    monkeypatch.setattr(mod, "ensure_current_slot_configuration", spy)
    ctrl, _ = _controller(tmp_path)

    snap = ctrl.snapshot()  # slot_configuration 존 + workbench_observation 존을 함께 조립
    assert snap["slot_configuration"]["current_view"]["view_status"] == "CURRENT"
    assert snap["workbench_observation"]["supported"] is True
    ctrl.workbench_observation()  # 관찰 경로 직접 호출도 렌더다
    assert calls["ensure"] == 0  # 렌더 경로 어디서도 ensure 를 부르지 않는다

    ctrl.dispatch("open_slot_configuration", {})  # 명시적 command 만 ensure 를 탄다
    assert calls["ensure"] == 1


def test_snapshot_zone_before_bootstrap_does_not_mint_durable_id(tmp_path: Path) -> None:
    """초기화 전(템플릿 확인 전) 스냅샷은 Product 를 부르지 않는다 — write-on-read 로 Work id 를
    발급하지 않는다(렌더 부작용 0). 지원은 하되 아직 미초기화로 선다."""
    from hwpxfiller.application.jobs import load_job

    ctrl, _ = _controller(tmp_path, bootstrap=False)
    zone = ctrl.snapshot()["slot_configuration"]
    assert zone["supported"] is True and zone["initialized"] is False
    assert zone["current_view"] is None
    assert zone["error"] is None
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


def test_slot_mutation_rejected_while_generating(tmp_path: Path) -> None:
    # #725 리뷰 P1: 생성 중 durable 구성 변경은 다른 실행-입력 변경과 같이 시끄럽게
    # 거절한다 — 실행 중 배치가 고정한 immutable 입력과 화면 구성이 어긋나지 않게. 조용한 통과 0.
    ctrl, _ = _controller(tmp_path)
    token = ctrl.dispatch("open_slot_configuration", {})["current_view"]["new_configuration_token"]
    acquired = ctrl._generation_lock.acquire(blocking=False)
    assert acquired  # 테스트가 생성 중 상태를 만든다
    try:
        with pytest.raises(ValueError, match="문서 생성이 진행 중"):
            ctrl.dispatch("select_slot_option", {
                "configuration_token": token, "slot_id": "no-such", "option_id": "opt",
                "request_id": "r1",
            })
    finally:
        ctrl._generation_lock.release()


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


# ── 「포함할 내용」 구획 노출 술어(U4 13번 · #932) ────────────────────────────────────────
def test_snapshot_zone_hides_itself_when_there_is_nothing_to_choose(tmp_path: Path) -> None:
    """slot 없는 작업에서 이 구획은 서지 않는다 — 「선택할 내용이 없습니다」가 상주하던 자리다.

    술어는 projection 이 낸 값 하나이고(``zone_actionable``), 링2 는 그것을 실어 나르기만 한다.
    """
    ctrl, _ = _controller(tmp_path)  # slotless Work
    projection = ctrl.snapshot()["slot_configuration"]["current_view"]["projection"]
    assert not projection["slots"]  # asdict 는 tuple 을 보존한다(JSON 직렬화에서 배열이 된다)
    assert projection["zone_actionable"] is False
    assert projection["savable_selection"] is False
    # 같은 상태에서 Preset 두 구획도 서지 않는다(보관 0 · 손상 0 · 저장할 선택 0).
    presets = ctrl.snapshot()["content_presets"]
    assert presets["list_actionable"] is False and presets["save_actionable"] is False


def test_choose_content_never_points_at_a_zone_that_is_not_standing(tmp_path: Path) -> None:
    """``CHOOSE_CONTENT`` 가 설 때 그 복구 동사의 구획이 **반드시** 선다는 불변식.

    이 blocker 의 복구 동사는 구획 안의 갈래 라디오(``.cs-option-input`` —
    :mod:`~hwpxfiller.webapp.blocker_affordance`)다. 구획이 사라지는 변경이라 「없는 자리를
    가리키는 지시」(#912 결함류)를 우리 손으로 만들지 않았음을 여기가 증언한다.
    """
    ctrl, _reg, _tpl = _slot_bearing_controller(tmp_path)
    obs = ctrl.workbench_observation()
    assert isinstance(obs, DocumentCreationWorkbenchObservation)
    assert "CHOOSE_CONTENT" in obs.blockers  # 필수 Slot 미선택 상태로 선다
    projection = ctrl.snapshot()["slot_configuration"]["current_view"]["projection"]
    assert projection["zone_actionable"] is True


# ── blocker 어휘 계약(구조 회귀 감지) ─────────────────────────────────────────────────────
def test_blocker_codes_include_choose_content_axis(tmp_path: Path) -> None:
    # SX-02 content 축이 소비하는 blocker 가 vocabulary 정본에 존재한다(드리프트 조기 감지).
    assert "CHOOSE_CONTENT" in BLOCKER_CODES
    assert "REVIEW_DELIVERY" in BLOCKER_CODES


# ── S6G-00 R2·R3: S6 cutover 가 설 자리와 복제 경로를 실사실로 고정한다(#806) ──────────────
def _slot_bearing_controller(tmp_path: Path):
    """Slot 둘짜리 Template 으로 세운 managed Work — `_controller` 의 slotless 짝.

    fixture 는 production Apply 경로를 타는 `_two_slot_template`(test_slot_configuration_product)
    를 그대로 쓴다. store 직접 seed 를 하지 않아야 「slot-bearing 이라는 사실」이 실제 판정 경로에서
    나온다.
    """
    tpl = tmp_path / "공고서.hwpx"
    _two_slot_template(tpl)
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="공고서", template_path=str(tpl)))
    coord = TemplateChangeCoordinator(reg, root=_root(tmp_path), clock=_clock())
    ctrl = JobController(
        reg, lambda s, snap: None,
        clock=_clock(),
        engine=make_hwpx_engine(),
        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
        generation_lock=threading.Lock(),
        file_source_factory=source_for_path,
        pool_source_factory=source_from_pool_item,
        existing_outputs=existing_output_paths,
        ensure_output_dir=ensure_output_directory,
        template_change=coord,
        slot_configuration=SlotConfigurationProduct(reg, root=_root(tmp_path), clock=_clock()),
        workbench_observation=WorkbenchObservationProduct(),
    )
    ctrl.dispatch("select_job", {"name": "공고서"})
    ctrl.dispatch("template_check", {"request_id": "k1"})
    return ctrl, reg, tpl


def _interrupt_current_preparation(tmp_path: Path, work_id: str) -> None:
    """직전 세션이 확인을 못 끝내고 죽은 상태를 durable 하게 세운다(``recover_session`` 산출물).

    seam 을 스텁하지 않는다 — 권위 저장소의 값만 그 상태로 두고, 읽는 쪽은 실 coordinator ·
    실 컨트롤러 · 실 composer 가 그대로 지난다.
    """
    store = AtomicWorkTemplateStateStore(_root(tmp_path) / "works")
    with store.update(work_id) as txn:
        aggregate = txn.aggregate
        current = aggregate.work.current_template_preparation_id
        assert current is not None
        txn.aggregate = dataclasses.replace(
            aggregate,
            aggregate_version=aggregate.aggregate_version + 1,
            preparations=tuple(
                dataclasses.replace(prep, status=PREP_INTERRUPTED)
                if prep.preparation_id == current
                else prep
                for prep in aggregate.preparations
            ),
        )


def test_unsettled_template_check_stands_in_the_workbench_observation(tmp_path: Path) -> None:
    """확인이 종결되지 않은 사실이 **작업대 관찰에** 선다(#912 D2).

    `template_change_verdict` 는 정의·소비·통로가 다 있었는데 프로덕션 전달자가 0 이라
    `REVIEW_TEMPLATE_CHANGE` 축이 사문이었다. 그래서 「다시 확인하세요」는 템플릿 구획에만
    서고 작업대는 아무 말도 안 했으며, 사용자는 생성을 눌러 실패한 뒤에야 그것을 알았다.
    """
    ctrl, _reg, _tpl = _slot_bearing_controller(tmp_path)
    work_id = ctrl.registry.load("공고서").authority_id
    assert work_id

    settled = ctrl.workbench_observation()
    assert isinstance(settled, DocumentCreationWorkbenchObservation)
    assert "REVIEW_TEMPLATE_CHANGE" not in settled.blockers  # 종결 상태에선 안 선다

    _interrupt_current_preparation(tmp_path, work_id)
    unsettled = ctrl.workbench_observation()
    assert isinstance(unsettled, DocumentCreationWorkbenchObservation)
    assert "REVIEW_TEMPLATE_CHANGE" in unsettled.blockers
    # 그 blocker 가 겨누는 곳은 템플릿 확인 구획이고, 그 구획의 확인 동사는 실제로 활성이다
    # (지시만 있고 수단이 없는 상태를 만들지 않는다).
    routes = {t.blocker_code: t.route for t in unsettled.deep_link_targets}
    assert routes["REVIEW_TEMPLATE_CHANGE"] == "workbench.template_change"
    zone = ctrl._template_change.zone("공고서", "hwpx", False)
    assert zone["checkable"] is True
    assert zone["preparation"]["status"] == "interrupted"
    # 그리고 그 구획이 **실제로 선다**(#932 B5): 존 노출을 드리프트가 판정하게 된 뒤로
    # 「비활성이 아니라 아예 없는 자리를 가리키는 지시」가 새 결함류로 가능해졌다 —
    # 미종결 확인은 원본이 그대로여도 존을 세운다는 것이 그 자리를 막는 불변식이다.
    assert zone["source_drift"] == "unchanged" and zone["actionable"] is True


def test_source_drift_stands_in_the_workbench_observation(tmp_path: Path) -> None:
    """앱 밖에서 원본을 고치면 **생성이 막힌다**(#932 B5) — 조용한 오생성 0.

    존이 조치가 있을 때만 서게 된 뒤로, 한글에서 템플릿을 고친 사용자가 그 사실을 못 본 채
    생성을 누를 창이 생겼다. 생성은 캡처된 bytes 를 쓰므로(#681 F1) 그 창은 「검토한 편집분이
    반영 안 된 문서」로 착지한다. 그래서 드리프트를 실행 게이트로 올린다 — 좌초시키지는
    않는다: 이 blocker 의 복구 동사(`#jobTplCheck`)는 같은 판정이 세우는 존 안에 있다.
    """
    ctrl, _reg, tpl = _slot_bearing_controller(tmp_path)
    settled = ctrl.workbench_observation()
    assert isinstance(settled, DocumentCreationWorkbenchObservation)
    assert "REVIEW_TEMPLATE_CHANGE" not in settled.blockers
    assert ctrl.snapshot()["template_change"]["actionable"] is False

    _template(tpl, ["공고명"])  # 한글에서 고친 셈 — 앱 밖 편집(미가져오기)

    drifted = ctrl.workbench_observation()
    assert isinstance(drifted, DocumentCreationWorkbenchObservation)
    assert "REVIEW_TEMPLATE_CHANGE" in drifted.blockers
    # 지시가 겨누는 자리가 실제로 선다 — 없는 자리를 가리키지 않는다(#912 결함류).
    zone = ctrl.snapshot()["template_change"]
    assert zone["source_drift"] == "changed" and zone["actionable"] is True
    assert zone["checkable"] is True


def test_workbench_observation_reads_template_change_without_issuing_authority(
    tmp_path: Path,
) -> None:
    """관찰은 읽기다(#804 규율) — verdict 파생이 durable 권위를 발급·변조하지 않는다."""
    ctrl, reg, _tpl = _slot_bearing_controller(tmp_path)
    before = (reg.load("공고서").authority_id, _aggregate_bytes(tmp_path, reg))
    ctrl.workbench_observation()
    assert (reg.load("공고서").authority_id, _aggregate_bytes(tmp_path, reg)) == before


def _aggregate_bytes(tmp_path: Path, reg) -> bytes:
    work_id = reg.load("공고서").authority_id
    return (_root(tmp_path) / "works" / f"{work_id}.json").read_bytes()


def test_slot_bearing_generate_refusal_has_an_owner_below_the_authority_guard(
    tmp_path: Path,
) -> None:
    """slot-bearing 거절은 `authority_id` 가드가 **없어도** 제 사유로 난다.

    오늘 `_generate_with_token` 은 `job.authority_id` 만 보고 먼저 거절한다(SX-03 #750). 그 가드가
    앞에 서 있는 동안 **그 아래가 실제로 무엇을 하는지 확인된 적이 없다** — #807 S6-05 가 가드를
    걷을 때 무엇이 남는지가 이 테스트의 산출물이다.

    남는 것은 admission 이다: `resolve_generation_template_for_seated_context` →
    `admit_managed_slotless_run` → `admit_slotless_run` 이 `SlotConfigurationSnapshot`(slot-bearing)을
    무조건 `SLOT_CONFIGURATION_EXECUTION_NOT_AVAILABLE` 로 거절한다. 단위 층은
    `test_slotless_run_bridge.py` 가 이미 덮으므로 여기서는 **컨트롤러 층 도달**만 잰다.
    """
    ctrl, _reg, _tpl = _slot_bearing_controller(tmp_path)

    # (1) 오늘의 표면 — 가드가 먼저 서서 managed 사유로 닫는다.
    guarded = ctrl.generate()
    assert guarded["ok"] is False

    # (2) 가드 아래 — 같은 작업을 admission 이 **제 사유로** 거절한다(가드가 없어도 안전).
    reject = ctrl._resolve_managed_template(ctrl.vm)
    assert reject is not None, "slot-bearing 은 legacy generator 로 통과되면 안 된다"
    assert reject["ok"] is False
    # (3) 사유는 실사유여야 한다(#907·#912). 「아직 지원하지 않습니다」는 S5/S6 미출하 시절의
    # 전제라 S6 완주 이후로는 거짓이고, 다음 행동도 주지 못했다.
    assert reject["error"] == (
        "이 작업의 문서 구성이 아직 확립되지 않았습니다. "
        "'템플릿 변경사항 확인'을 먼저 실행한 뒤 다시 시도하세요."
    )
    assert "지원하지 않습니다" not in reject["error"]


def test_cloned_slot_bearing_work_reaches_initialization_through_template_check(
    tmp_path: Path,
) -> None:
    """복제본은 **선택만으로** 초기화에 도달한다 — #804 의 막다른 길은 여기서 안 난다.

    #804 는 실 WebView2 관측이고 스스로 「결정적 재현으로 확정하지 않았다」고 적었다. 이 테스트가
    그 재현 시도이고 결과는 **음성**이다. 종전에는 복제본의 `authority_id` 미계승(S3-09) 때문에
    존이 `initialized=False` 로 섰다가 화면이 시키는 「변경사항 확인」이 그걸 풀었는데, 그
    겸직이 #932 B5 에서 끊겼다 — 준비는 착석이 지므로 복제본은 **막힌 적이 없다**.

    복제 자체는 그러니 결백하다 — 확정된 원인은 **준비가 실패했을 때**의 세 자리이고, 아래 두
    테스트가 그 자리를 잰다(좀비 권위 롤백·수리 뒤 재개방).
    """
    ctrl, reg, _tpl = _slot_bearing_controller(tmp_path)
    assert ctrl.snapshot()["slot_configuration"]["initialized"] is True

    clone = reg.clone("공고서")
    assert reg.load(clone).authority_id == ""  # 겪지 않은 권위 역사를 지어내지 않는다(S3-09)

    ctrl.dispatch("select_job", {"name": clone})
    assert reg.load(clone).authority_id != ""  # 착석이 준비를 졌다(#932 B5)
    assert ctrl.snapshot()["slot_configuration"]["initialized"] is True

    # 확인은 겸직을 잃었을 뿐 자기 일은 그대로 한다(변경 0건 = 종결).
    assert ctrl.dispatch("template_check", {"request_id": "k2"})["ok"] is True
    assert ctrl.snapshot()["slot_configuration"]["initialized"] is True


# ── #804: 확인이 **실패**하면 무엇이 남는가 — 좀비 권위 금지 ──────────────────────────────
def test_failed_initialization_releases_the_authority_it_just_issued(tmp_path: Path) -> None:
    """초기 등록에 실패한 확인은 방금 발급한 권위를 되돌린다 — 막다른 길의 재료를 안 남긴다.

    id-first 계약(S3-09)은 발급을 bootstrap **앞**에 둔다. 그래서 bootstrap 이 자격 심사에서
    거절되면 「권위는 있는데 Work 상태 집합은 없다」는 좀비가 남고, 슬롯 존이 그 좀비를 보고
    `initialized=True` + `CONTEXT_ERROR/TEMPLATE_INITIALIZATION_REQUIRED` 로 서서 「템플릿을
    확인하세요」만 되풀이한다 — 시킨 대로 눌러도 같은 자리로 돌아오는 막다른 길(#804).

    되돌린 뒤의 상태는 **복제 직후와 같다**: 존은 미초기화로 접히고 안내는 실패 기록을 든
    template_change 존 한 곳이 진다. 겪지 않은 권위를 지우는 것이므로 역사를 지어내지 않는다.
    """
    ctrl, reg, tpl = _slot_bearing_controller(tmp_path)
    clone = reg.clone("공고서")
    # 실물을 **착석 전에** 깬다: 준비를 착석이 지게 된 뒤로(#932 B5) 초기 등록은 여기서
    # 시도되고 거절된다 — 뒤에 깨면 이미 준비를 마친 뒤라 이 자리가 안 재진다.
    tpl.write_bytes(b"not a zip")  # 자격 심사가 거절할 실물(복제본은 아직 미부트스트랩)
    ctrl.dispatch("select_job", {"name": clone})

    assert ctrl.dispatch("template_check", {"request_id": "k2"}) == {
        "ok": False, "reason": "initialization_required",
    }
    assert reg.load(clone).authority_id == ""  # 좀비 권위 부재
    assert reg.load("공고서").authority_id != ""  # 이미 겪은 권위는 무사하다

    snap = ctrl.snapshot()
    zone = snap["slot_configuration"]
    assert zone["supported"] is True and zone["initialized"] is False
    assert zone["current_view"] is None  # CONTEXT_ERROR 막다른 길이 서지 않는다
    tpl_zone = snap["template_change"]
    assert tpl_zone["reason"] == "initialization_required"
    assert tpl_zone["checkable"] is False and tpl_zone["diagnostics"]  # 비활성 + 사유 병기


def test_repairing_the_template_reopens_the_check_round_trip(tmp_path: Path) -> None:
    """실패 기록은 실물이 바뀌면 지워지고, 그 뒤 재확인이 초기화까지 **완주한다**.

    실패 기록의 키가 Work 였을 때는 이 왕복이 성립하지 않았다: 권위를 되돌리면 사유를 말하던
    유일한 자리가 함께 사라지기 때문이다. 기록은 작업 이름이 지고 표시 자격은 템플릿 실물
    서명이 가른다 — 이 테스트가 그 두 사실의 합이다(#804 결함 2).
    """
    ctrl, reg, tpl = _slot_bearing_controller(tmp_path)
    clone = reg.clone("공고서")
    tpl.write_bytes(b"not a zip")  # 착석 전에 깬다(#932 B5 — 준비는 착석이 진다)
    ctrl.dispatch("select_job", {"name": clone})
    ctrl.dispatch("template_check", {"request_id": "k2"})
    stuck = ctrl.snapshot()["template_change"]
    assert stuck["checkable"] is False and stuck["diagnostics"]
    # 기다리는 동안에도 슬롯 존은 막다른 길이 아니라 **미초기화**로 서 있다.
    assert ctrl.snapshot()["slot_configuration"]["initialized"] is False

    _two_slot_template(tpl)  # 안내대로 원본을 고친다 — 실물 서명이 달라진다
    reopened = ctrl.snapshot()["template_change"]
    assert reopened["checkable"] is True and reopened["diagnostics"] == []

    assert ctrl.dispatch("template_check", {"request_id": "k3"})["ok"] is True
    assert reg.load(clone).authority_id != ""  # 이제 겪은 권위가 선다
    assert ctrl.snapshot()["slot_configuration"]["initialized"] is True


def test_failed_initialization_on_the_generate_path_releases_the_authority_too(
    tmp_path: Path,
) -> None:
    """생성 경로의 초기 등록 실패도 **같은 규율**로 롤백한다 — 문을 하나만 닫지 않는다.

    확인 경로만 고치면 같은 좀비가 「문서 만들기」로 다시 만들어지고 막다른 길이 그대로
    열린다(#804 잔여). 두 경로가 같은 use case(`seat_job_authority_id`/`release_job_
    authority_id`)를 공유하는지를 여기서 잰다.

    겨눔은 `resolve_generation_template` 이다: 그 위 `generate` 가드는 slot-bearing 을 **다른
    사유**로 먼저 닫으므로(같은 파일의 `_resolve_managed_template` 테스트와 같은 이유) 가드
    아래 실제 문에 대고 물어야 이 규율이 확인된다.
    """
    ctrl, reg, tpl = _slot_bearing_controller(tmp_path)
    clone = reg.clone("공고서")
    tpl.write_bytes(b"not a zip")  # 자격 심사가 거절할 실물(착석 전 — #932 B5)
    ctrl.dispatch("select_job", {"name": clone})

    with pytest.raises(SlotlessRunAdmissionError):
        ctrl._template_change.resolve_generation_template(clone)

    assert reg.load(clone).authority_id == ""  # 좀비 권위 부재
    assert reg.load("공고서").authority_id != ""  # 이미 겪은 권위는 무사하다

    zone = ctrl.snapshot()["slot_configuration"]
    assert zone["supported"] is True and zone["initialized"] is False
    assert zone["current_view"] is None  # CONTEXT_ERROR 막다른 길이 서지 않는다


def test_clone_of_a_work_with_durable_selection_opens_its_own_zone(tmp_path: Path) -> None:
    """durable 선택을 가진 원본의 복제도 확인 한 번으로 자기 존을 연다(음성 대조).

    #804 관측이 「선택까지 해 둔 작업을 복제했다」였으므로 그 조건을 실제로 세워 재현을
    시도한다. 결과는 음성이다 — 막힘은 선택 유무가 아니라 **확인의 실패**가 만든다.
    """
    ctrl, reg, _tpl = _slot_bearing_controller(tmp_path)
    token = ctrl.dispatch("open_slot_configuration", {})["current_view"][
        "new_configuration_token"
    ]
    selected = ctrl.dispatch("select_slot_option", {
        "configuration_token": token, "slot_id": "s-keep",
        "option_id": "o-keep", "request_id": "r1",
    })
    assert selected["mutation_outcome"]["changed"] is True

    origin = reg.load("공고서").authority_id
    clone = reg.clone("공고서")
    assert reg.load(clone).authority_id == ""  # 선택은 원본 Work 의 것이라 미계승(S3-09)

    ctrl.dispatch("select_job", {"name": clone})
    assert ctrl.dispatch("template_check", {"request_id": "k2"})["ok"] is True
    assert reg.load(clone).authority_id not in ("", origin)
    view = ctrl.snapshot()["slot_configuration"]["current_view"]
    assert view["view_status"] == "CURRENT" and view["projection"]["slots"]


# ── S10-03(#860): 「포함할 내용」이 TXT 작업에서도 선다 ────────────────────────────────────
# 판정·token·projection·Preset 은 위 hwpx 인수와 **같은 기계**가 진다(S4 아래 어디에도 매체가
# 없다). 여기가 재는 것은 그 기계가 TXT 매체에서 **도달 가능한가** 하나다: 존이 열리고,
# durable 선택 왕복이 성사되고, 라벨이 저작한 이름 그대로 온다.

#: 항목 1(선택 2) + 항목 밖·직속 문구를 가진 TXT 템플릿. 좌표는 줄 번호다(#856 D2).
_TXT_SLOT_TEMPLATE = "\n".join(
    [
        "수신: {{수신}}",
        "{{#항목 첨부 첨부 서류}}",
        "담당자: {{담당자}}",
        "{{#선택 계약서 계약서}}",
        "계약서를 첨부합니다. {{건명}}",
        "{{/선택}}",
        "{{#선택 견적서 견적서}}",
        "견적서를 첨부합니다.",
        "{{/선택}}",
        "{{/항목}}",
        "끝.",
        "",
    ]
)


def _txt_slot_bearing_controller(tmp_path: Path, *, body: str = _TXT_SLOT_TEMPLATE):
    """구간 표기가 있는 TXT 작업으로 세운 헤드리스 컨트롤러 — hwpx 짝과 같은 조립.

    seal 서비스는 주입하지 않는다: 자동 확인(S5)은 HWPX 실행 계획의 축이고 TXT 물질화는
    S10-04 소관이다(미주입 = 표면 부재의 정직한 얼굴).
    """
    tpl = tmp_path / "안내문.txt"
    tpl.write_text(body, encoding="utf-8")
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="안내문", template_path=str(tpl)))
    coord = TemplateChangeCoordinator(reg, root=_root(tmp_path), clock=_clock())
    ctrl = JobController(
        reg, lambda s, snap: None,
        clock=_clock(),
        engine=make_hwpx_engine(),
        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
        generation_lock=threading.Lock(),
        file_source_factory=source_for_path,
        pool_source_factory=source_from_pool_item,
        existing_outputs=existing_output_paths,
        ensure_output_dir=ensure_output_directory,
        template_change=coord,
        slot_configuration=SlotConfigurationProduct(reg, root=_root(tmp_path), clock=_clock()),
        workbench_observation=WorkbenchObservationProduct(),
    )
    ctrl.dispatch("select_job", {"name": "안내문"})
    ctrl.dispatch("template_check", {"request_id": "k1"})
    return ctrl, reg, tpl


def test_txt_work_opens_the_content_selection_zone_with_authored_labels(
    tmp_path: Path,
) -> None:
    ctrl, _reg, _tpl = _txt_slot_bearing_controller(tmp_path)

    zone = ctrl.snapshot()["slot_configuration"]
    assert zone["supported"] is True and zone["initialized"] is True and zone["error"] is None
    assert zone["current_view"]["view_status"] == "CURRENT"
    assert zone["current_view"]["configuration_status"] == "NEEDS_SELECTION"

    slots = zone["current_view"]["projection"]["slots"]
    assert [s["slot_id"] for s in slots] == ["첨부"]
    # 저작한 이름이 그대로 온다 — 라벨을 잃으면 화면에 내부 ID 가 뜬다.
    assert slots[0]["display_text"] == "첨부 서류"
    assert [(o["option_id"], o["display_text"]) for o in slots[0]["options"]] == [
        ("계약서", "계약서"), ("견적서", "견적서"),
    ]
    # 필드 소유권도 줄 좌표에서 유도된 그대로다(항목 직속 = 공유, 선택 안 = 그 선택).
    assert slots[0]["shared_field_ids"] == ("담당자",)
    assert slots[0]["options"][0]["structurally_associated_field_ids"] == ("건명",)


def test_txt_selection_round_trip_is_durable_without_extra_machinery(
    tmp_path: Path,
) -> None:
    """선택·재선택이 hwpx 와 **같은 dispatch 동사**로 성사되고 스냅샷에 남는다(추가 기계 0).

    EXACTLY_ONE 이라 결정을 무르는 길은 「비우기」가 아니라 **다시 고르기**다(#903 —
    비우기 제품 동사는 없다).
    """
    ctrl, _reg, _tpl = _txt_slot_bearing_controller(tmp_path)
    token = ctrl.dispatch("open_slot_configuration", {})["current_view"][
        "new_configuration_token"
    ]

    picked = ctrl.dispatch("select_slot_option", {
        "configuration_token": token, "slot_id": "첨부",
        "option_id": "견적서", "request_id": "r1",
    })
    assert picked["mutation_outcome"]["outcome_code"] == "CHANGED"
    view = picked["current_view"]["projection"]
    assert view["configuration_status"] == "SLOT_SELECTIONS_COMPLETE"
    assert view["slots"][0]["effective_option_ids"] == ("견적서",)
    # 스냅샷(별도 조회)도 같은 사실을 본다 — durable 이지 세션 사본이 아니다.
    zone = ctrl.snapshot()["slot_configuration"]
    assert zone["current_view"]["projection"]["slots"][0]["effective_option_ids"] == ("견적서",)

    fresh = picked["current_view"]["new_configuration_token"]
    reselected = ctrl.dispatch("select_slot_option", {
        "configuration_token": fresh, "slot_id": "첨부",
        "option_id": "계약서", "request_id": "r2",
    })
    assert reselected["mutation_outcome"]["changed"] is True
    assert reselected["current_view"]["projection"]["slots"][0]["effective_option_ids"] == (
        "계약서",
    )


def test_slotless_txt_work_supports_the_zone_with_nothing_to_choose(tmp_path: Path) -> None:
    """마커 없는 기존 TXT 작업은 존을 열되 고를 것이 없다 — 회귀 축(무선언 = 무선택)."""
    ctrl, _reg, _tpl = _txt_slot_bearing_controller(
        tmp_path, body="수신: {{수신}}\n건명: {{건명}}\n"
    )
    zone = ctrl.snapshot()["slot_configuration"]
    assert zone["supported"] is True and zone["initialized"] is True
    assert zone["current_view"]["projection"]["slots"] == ()
    assert zone["current_view"]["configuration_status"] == "NOT_APPLICABLE"


def test_txt_check_seats_the_template_application_identity(tmp_path: Path) -> None:
    """S10-02 잔여 seam — 실행뷰가 없어도 확인이 세운 정체를 세션이 받는다(#860)."""
    tpl = tmp_path / "안내문.txt"
    tpl.write_text(_TXT_SLOT_TEMPLATE, encoding="utf-8")
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="안내문", template_path=str(tpl)))
    coord = TemplateChangeCoordinator(reg, root=_root(tmp_path), clock=_clock())
    ctrl = JobController(
        reg, lambda s, snap: None,
        clock=_clock(), engine=make_hwpx_engine(),
        pool_registry=DatasetPoolRegistry(tmp_path / "pool"),
        generation_lock=threading.Lock(),
        file_source_factory=source_for_path,
        pool_source_factory=source_from_pool_item,
        existing_outputs=existing_output_paths,
        ensure_output_dir=ensure_output_directory,
        template_change=coord,
    )
    ctrl.dispatch("select_job", {"name": "안내문"})
    assert ctrl.vm is None and ctrl.job_is_txt is True  # 실행뷰 없음(§F6 판정 D)
    # 착석이 준비를 진다(#932 B5) — TXT 도 같은 배선이라 여기서 이미 정체가 선다.
    # 이 테스트가 재는 것은 그 **매체 무관성**과 재확인의 무-흔들림이다: 종전 결함은
    # 채택이 `self.vm is not None` 아래 있어 실행뷰 없는 TXT 만 정체를 못 들던 것이었다.
    seated = ctrl._seated_template_application_id
    assert seated

    assert ctrl.dispatch("template_check", {"request_id": "k1"})["ok"] is True
    assert ctrl._seated_template_application_id == seated
    assert ctrl.job_name == "안내문"  # 조용한 해제 0
    # 재확인은 이미 선 정체를 흔들지 않는다(중복 채택 0).
    assert ctrl.dispatch("template_check", {"request_id": "k2"})["ok"] is True
    assert ctrl._seated_template_application_id == seated


def test_content_selection_reader_hands_the_workbench_effective_choices(
    tmp_path: Path,
) -> None:
    """앱 조립의 조회 포트가 실 Product 에서 「항목 → 고른 선택」만 뽑아 준다(S10-03 #860).

    작업대는 Product 의 형체를 모른 채 이 사전 하나로 투영한다. 실패는 삼키지 않고
    ``ValueError`` 로 올라간다 — 조용한 빈 사전은 「아무것도 안 골랐다」와 구별되지 않는다.
    """
    from hwpxfiller.webapp.app import _content_selection_reader

    ctrl, reg, _tpl = _txt_slot_bearing_controller(tmp_path)
    product = SlotConfigurationProduct(reg, root=_root(tmp_path), clock=_clock())
    read = _content_selection_reader(product, reg)

    assert read("안내문") == {"첨부": frozenset()}  # 아직 안 골랐다(항목은 있다)

    token = ctrl.dispatch("open_slot_configuration", {})["current_view"][
        "new_configuration_token"
    ]
    ctrl.dispatch("select_slot_option", {
        "configuration_token": token, "slot_id": "첨부",
        "option_id": "계약서", "request_id": "r1",
    })
    assert read("안내문") == {"첨부": frozenset({"계약서"})}

    # 확인 전(권위 미발급) Work 는 Product 를 부르지 않고 거절한다 — 렌더 부작용 0.
    reg.save(Job(name="미확인", template_path=str(tmp_path / "안내문.txt")))
    with pytest.raises(ValueError, match="TEMPLATE_INITIALIZATION_REQUIRED"):
        read("미확인")
    assert not reg.load("미확인").authority_id  # write-on-read 로 durable id 를 만들지 않았다
