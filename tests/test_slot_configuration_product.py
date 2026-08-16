"""S4-09(#679) Product API: route-bound Work, HMAC token, fresh view/token 조립."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.application.slot_token import (
    TOKEN_PURPOSE,
    TOKEN_SCHEMA_VERSION,
    ConfigurationTokenClaims,
    actor_binding_digest,
    sign_configuration_token,
)
from hwpxfiller.domain.job import Job
from hwpxfiller.external.hwpx_package_io import write_hwpx_package
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.external.slot_token_secret import SlotTokenSecretStore
from hwpxfiller.external.work_configuration_store import WorkspaceMetadataStore
from hwpxfiller.webapp.slot_configuration_product import (
    LOCAL_ACTOR,
    SlotConfigurationProduct,
    SlotConfigurationProductError,
)
from hwpxfiller.webapp.template_change import TemplateChangeCoordinator

NOW = datetime(2026, 8, 16, 0, 0, 0)


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


def _bootstrapped(tmp_path: Path, name="공고서") -> tuple[JobRegistry, SlotConfigurationProduct]:
    tpl = tmp_path / f"{name}.hwpx"
    _template(tpl, ["공고명"])
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name=name, template_path=str(tpl)))
    coord = TemplateChangeCoordinator(reg, root=_root(tmp_path), clock=_clock())
    coord.check(name, "k1")  # bootstrap → S3 current application
    product = SlotConfigurationProduct(reg, root=_root(tmp_path), clock=_clock())
    return reg, product


# ── init-required (adapter NotFound→None) ─────────────────────────────────────
def test_unbootstrapped_work_is_initialization_required(tmp_path: Path) -> None:
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="공고서", template_path=str(tmp_path / "공고서.hwpx")))
    product = SlotConfigurationProduct(reg, root=_root(tmp_path), clock=_clock())
    resp = product.open_slot_configuration("공고서")
    assert resp.current_view.view_status == "CONTEXT_ERROR"
    assert resp.current_view.context_error == "TEMPLATE_INITIALIZATION_REQUIRED"
    assert resp.current_view.new_configuration_token is None
    assert resp.refresh_required is True


def test_missing_work_ref_is_authorization_failure(tmp_path: Path) -> None:
    reg = JobRegistry(tmp_path / "jobs")
    product = SlotConfigurationProduct(reg, root=_root(tmp_path), clock=_clock())
    with pytest.raises(SlotConfigurationProductError) as ei:
        product.open_slot_configuration("없는작업")
    assert ei.value.code == "AUTHORIZATION_FAILURE"


# ── happy wiring: open → token → command ──────────────────────────────────────
def test_open_yields_current_view_and_token(tmp_path: Path) -> None:
    _reg, product = _bootstrapped(tmp_path)
    resp = product.open_slot_configuration("공고서")
    assert resp.current_view.view_status == "CURRENT"
    assert resp.current_view.new_configuration_token  # 발급됨
    assert resp.refresh_required is False


def test_select_with_issued_token_runs_and_reissues(tmp_path: Path) -> None:
    _reg, product = _bootstrapped(tmp_path)
    token = product.open_slot_configuration("공고서").current_view.new_configuration_token
    assert token is not None
    resp = product.select_slot_option("공고서", token, "no-such-slot", "opt", "r1")
    # slotless 템플릿이라 mutation 은 UNKNOWN_SLOT 이지만 wiring(토큰→context→runner→응답)은 완주.
    assert resp.mutation_outcome is not None
    assert resp.mutation_outcome.request_relation == "CURRENT"
    assert resp.current_view.new_configuration_token  # 새 token 재발급


def test_replay_same_request_returns_first_outcome(tmp_path: Path) -> None:
    _reg, product = _bootstrapped(tmp_path)
    token = product.open_slot_configuration("공고서").current_view.new_configuration_token
    assert token is not None
    first = product.select_slot_option("공고서", token, "no-such-slot", "opt", "rX")
    replay = product.select_slot_option("공고서", token, "no-such-slot", "opt", "rX")
    assert replay.mutation_outcome.outcome_code == first.mutation_outcome.outcome_code
    assert replay.mutation_outcome.outcome_replayed is True


# ── route-bound Work verification ─────────────────────────────────────────────
def _secret(tmp_path: Path) -> bytes:
    return SlotTokenSecretStore(_root(tmp_path)).load_or_create_active_secret()


def _ws(tmp_path: Path) -> str:
    ws = WorkspaceMetadataStore(_root(tmp_path)).read()
    assert ws is not None
    return ws


def _forged(tmp_path: Path, **over) -> str:
    base = dict(
        token_schema_version=TOKEN_SCHEMA_VERSION, token_purpose=TOKEN_PURPOSE,
        workspace_instance_id=_ws(tmp_path), work_authority_id="W-forge",
        template_application_id="A", selection_semantic_contract_id="slot-selection/v1",
        configuration_presence=False, configuration_version=None,
        actor_binding_digest=actor_binding_digest(LOCAL_ACTOR, _ws(tmp_path)),
        issued_at="2026-08-16T00:00:00",
    )
    base.update(over)
    return sign_configuration_token(ConfigurationTokenClaims(**base), _secret(tmp_path))


def test_cross_work_token_rejected(tmp_path: Path) -> None:
    _reg, product = _bootstrapped(tmp_path)
    product.open_slot_configuration("공고서")  # ws·secret 확립
    token = _forged(tmp_path, work_authority_id="some-other-work")
    with pytest.raises(SlotConfigurationProductError) as ei:
        product.select_slot_option("공고서", token, "s", "o", "r")
    assert ei.value.code == "CROSS_WORK_CONFIGURATION_TOKEN"
    # 무변경: 정상 open 은 여전히 동작
    assert product.open_slot_configuration("공고서").current_view.view_status == "CURRENT"


def test_cross_workspace_token_rejected(tmp_path: Path) -> None:
    _reg, product = _bootstrapped(tmp_path)
    product.open_slot_configuration("공고서")
    # actor binding 은 current ws 로 맞추고 workspace claim 만 어긋나게 → CROSS_WORKSPACE.
    token = _forged(
        tmp_path, workspace_instance_id="other-ws",
        actor_binding_digest=actor_binding_digest(LOCAL_ACTOR, _ws(tmp_path)),
    )
    with pytest.raises(SlotConfigurationProductError) as ei:
        product.select_slot_option("공고서", token, "s", "o", "r")
    assert ei.value.code == "CROSS_WORKSPACE_CONFIGURATION_TOKEN"


def test_actor_binding_mismatch_rejected(tmp_path: Path) -> None:
    _reg, product = _bootstrapped(tmp_path)
    product.open_slot_configuration("공고서")
    token = _forged(tmp_path, actor_binding_digest="sha256:wrong-actor")
    with pytest.raises(SlotConfigurationProductError) as ei:
        product.select_slot_option("공고서", token, "s", "o", "r")
    assert ei.value.code == "TOKEN_ACTOR_BINDING_MISMATCH"


def test_invalid_token_rejected(tmp_path: Path) -> None:
    _reg, product = _bootstrapped(tmp_path)
    product.open_slot_configuration("공고서")
    with pytest.raises(SlotConfigurationProductError) as ei:
        product.select_slot_option("공고서", "hfslot1.tampered.sig", "s", "o", "r")
    assert ei.value.code == "INVALID_CONFIGURATION_TOKEN"


def test_name_reuse_does_not_inherit_token(tmp_path: Path) -> None:
    # 같은 name 이라도 authority_id 가 identity — old token 의 Work 는 새 Work 와 다르다.
    _reg, product = _bootstrapped(tmp_path)
    token = product.open_slot_configuration("공고서").current_view.new_configuration_token
    assert token is not None
    # authority_id 를 담은 token 을 다른 work_authority 로 위조하면 cross-work.
    forged = _forged(tmp_path, work_authority_id="recycled-name-new-work")
    with pytest.raises(SlotConfigurationProductError) as ei:
        product.select_slot_option("공고서", forged, "s", "o", "r")
    assert ei.value.code == "CROSS_WORK_CONFIGURATION_TOKEN"
