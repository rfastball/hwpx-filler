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
    # 이전 선택의 운명(#777)도 같은 축이다 — 키가 사라지면 프런트가 그릴 근거를 잃는다.
    proj = res["current_view"]["projection"]
    assert {
        "slots",
        "detached_selections",
        "blocking_items",
        "reconciliation_changes",
        "retained_selections",
    } <= set(proj)


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


def test_slot_mutation_rejected_while_generating(tmp_path: Path) -> None:
    # #725 리뷰 P1: 생성 중 durable 구성 변경(select/clear)은 다른 실행-입력 변경과 같이 시끄럽게
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
        with pytest.raises(ValueError, match="문서 생성이 진행 중"):
            ctrl.dispatch("clear_slot_selection", {
                "configuration_token": token, "slot_id": "no-such", "request_id": "r2",
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
    assert reject["error"] == "이 템플릿의 슬롯 구성 실행은 아직 지원하지 않습니다."


def test_cloned_slot_bearing_work_reaches_initialization_through_template_check(
    tmp_path: Path,
) -> None:
    """복제본은 「변경사항 확인」으로 초기화에 **도달한다** — #804 의 막다른 길은 여기서 안 난다.

    #804 는 실 WebView2 관측이고 스스로 「결정적 재현으로 확정하지 않았다」고 적었다. 이 테스트가
    그 재현 시도다. 결과는 **음성**이다: 복제본의 `authority_id` 는 미계승(S3-09)이라 존이
    `initialized=False` 로 서지만, 화면이 시키는 확인이 durable id 를 발급해 존이 열린다.

    따라서 #804 의 원인은 이 층 **아래가 아니라 위**(ring2 렌더) 또는 이 fixture 가 갖지 못한
    실파일·기존 선택 쪽에 있다. 배선을 「고치지 않는다」는 판정의 근거가 이 테스트다.
    """
    ctrl, reg, _tpl = _slot_bearing_controller(tmp_path)
    assert ctrl.snapshot()["slot_configuration"]["initialized"] is True

    clone = reg.clone("공고서")
    assert reg.load(clone).authority_id == ""  # 겪지 않은 권위 역사를 지어내지 않는다(S3-09)

    ctrl.dispatch("select_job", {"name": clone})
    stuck = ctrl.snapshot()["slot_configuration"]
    assert stuck["supported"] is True and stuck["initialized"] is False

    # 화면이 지시하는 행동이 실제로 그 상태를 푼다.
    assert ctrl.dispatch("template_check", {"request_id": "k2"})["ok"] is True
    assert reg.load(clone).authority_id != ""
    assert ctrl.snapshot()["slot_configuration"]["initialized"] is True
