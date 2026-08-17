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
# SG-03(#735) C8 — cross-Work/route mismatch token 은 거절된다. 아래 네 테스트가 그 계약이다:
#   test_cross_work_token_rejected · test_cross_workspace_token_rejected ·
#   test_actor_binding_mismatch_rejected · test_missing_work_ref_is_authorization_failure.
# token 은 route 가 정한 expected Work·workspace·actor 와 **독립 비교**되고, 어긋나면 서명이
# 유효해도 CROSS_WORK/CROSS_WORKSPACE/ACTOR_BINDING/AUTHORIZATION 으로 거절된다(신규 테스트 없음).
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


def test_corrupt_secret_normalized_to_invalid_token(tmp_path: Path) -> None:
    # F3: secret 파일 손상은 외부 store 오류를 새지 않고 INVALID_CONFIGURATION_TOKEN 으로.
    _reg, product = _bootstrapped(tmp_path)
    token = product.open_slot_configuration("공고서").current_view.new_configuration_token
    (_root(tmp_path) / "slot_token_secret.json").write_text("{corrupt", "utf-8")
    with pytest.raises(SlotConfigurationProductError) as ei:
        product.select_slot_option("공고서", token or "x", "s", "o", "r")
    assert ei.value.code == "INVALID_CONFIGURATION_TOKEN"


def test_view_and_token_come_from_one_read(tmp_path: Path) -> None:
    # F1: 발급 token 의 claims 가 표시 projection 과 같은 스냅샷(version·application)이다.
    from hwpxfiller.application.slot_token import open_configuration_token

    _reg, product = _bootstrapped(tmp_path)
    token = product.open_slot_configuration("공고서").current_view.new_configuration_token
    resp = product.select_slot_option("공고서", token or "x", "no-slot", "o", "r1")
    new_token = resp.current_view.new_configuration_token
    assert new_token is not None and resp.current_view.projection is not None
    claims = open_configuration_token(new_token, _secret(tmp_path))
    assert claims.configuration_version == resp.current_view.projection.configuration_version
    assert claims.configuration_presence == resp.current_view.projection.configuration_present


def test_stale_template_mutation_shows_fresh_current_view(tmp_path: Path) -> None:
    # F2: old-application token 의 mutation 은 STALE outcome 이지만 current_view 는 새 application 을
    # CURRENT 로 투영하고 fresh token 을 낸다(context error 가 아니다).
    tpl = tmp_path / "공고서.hwpx"
    _template(tpl, ["공고명"])
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="공고서", template_path=str(tpl)))
    coord = TemplateChangeCoordinator(reg, root=_root(tmp_path), clock=_clock())
    coord.check("공고서", "k1")  # bootstrap A_old
    product = SlotConfigurationProduct(reg, root=_root(tmp_path), clock=_clock())
    old_token = product.open_slot_configuration("공고서").current_view.new_configuration_token
    assert old_token is not None
    _template(tpl, ["공고명", "추정가격"])  # 원본 수정
    ready = coord.check("공고서", "k2")["preparation"]
    coord.apply("공고서", ready["change_token"])  # A_new 로 current 전진

    resp = product.select_slot_option("공고서", old_token, "s", "o", "r")
    assert resp.mutation_outcome.outcome_code == "STALE_TEMPLATE_APPLICATION"
    assert resp.mutation_outcome.request_relation == "STALE_TEMPLATE_APPLICATION"
    assert resp.current_view.view_status == "CURRENT"  # 새 application, context error 아님
    assert resp.current_view.new_configuration_token  # 새 상태용 fresh token
    assert resp.refresh_required is True


# ── SG-03(#735) C7 — valid HMAC 만으로 authorization/currentness 우회 불가 ────────────
def test_valid_token_cannot_bypass_stale_currentness(tmp_path: Path) -> None:
    """서명·binding 이 모두 유효한 token 이라도 currentness/version gate 를 대신하지 못한다.

    token 은 정상 발급분(같은 Work·workspace·actor)이라 ``_verify_token`` 을 통과한다 —
    cross-work/workspace/actor 거절이 아니다. 그런데 template 이 새 application(version bump)
    으로 전진한 뒤 이 token 으로 mutation 을 걸면, 유효성과 **독립인** currentness gate 가
    STALE 로 삼켜 **적용되지 않는다**(``changed is False``). HMAC = context integrity 이지
    currentness 승인이 아니다.
    """
    tpl = tmp_path / "공고서.hwpx"
    _template(tpl, ["공고명"])
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="공고서", template_path=str(tpl)))
    coord = TemplateChangeCoordinator(reg, root=_root(tmp_path), clock=_clock())
    coord.check("공고서", "k1")
    product = SlotConfigurationProduct(reg, root=_root(tmp_path), clock=_clock())
    token = product.open_slot_configuration("공고서").current_view.new_configuration_token
    assert token is not None

    _template(tpl, ["공고명", "추정가격"])  # 원본 수정 → 새 application
    ready = coord.check("공고서", "k2")["preparation"]
    coord.apply("공고서", ready["change_token"])  # current 를 A_new 로 전진

    resp = product.select_slot_option("공고서", token, "s", "o", "r")
    # 유효 token 이 거절(INVALID/CROSS_*)된 게 아니라, currentness gate 가 STALE 로 막았다.
    assert resp.mutation_outcome is not None
    assert resp.mutation_outcome.outcome_code == "STALE_TEMPLATE_APPLICATION"
    assert resp.mutation_outcome.changed is False  # 유효 서명에도 미적용
    assert resp.refresh_required is True


def test_valid_token_cannot_bypass_same_application_stale_configuration(
    tmp_path: Path,
) -> None:
    """같은 template application 안에서 Configuration version 이 v→v+1 로 전진하면, 그 이전 version 을
    본 유효 token 은 STALE_CONFIGURATION 으로 거절된다(적용 안 됨).

    위 ``…stale_currentness`` 는 **다른** application 으로 전진해 STALE_TEMPLATE_APPLICATION 만
    탄다 — ``_command_context`` 가 ``claims.configuration_version`` 을 무시/치환해도 통과하는 gap 이
    남는다. 이 테스트는 그 축을 겨눈다: application 은 그대로 두고 config version 만 올린 뒤 옛
    version token 을 재제출하면 CAS(``_config_version_cas``)가 STALE_CONFIGURATION 을 낸다.
    ``_command_context`` 가 token version 을 그대로 실어야만 이 거절이 성립한다.
    """
    tpl = tmp_path / "공고서.hwpx"
    tpl.write_bytes(Path("tests/corpus/slots/canonical.hwpx").read_bytes())
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="공고서", template_path=str(tpl)))
    coord = TemplateChangeCoordinator(reg, root=_root(tmp_path), clock=_clock())
    coord.check("공고서", "k1")  # bootstrap → 단일 application (전진 없음)
    product = SlotConfigurationProduct(reg, root=_root(tmp_path), clock=_clock())

    slot, opt_a, opt_b = "추가 지급 안내", "성과급 안내", "특별수당 안내"
    token_a = product.open_slot_configuration("공고서").current_view.new_configuration_token
    assert token_a is not None
    first = product.select_slot_option("공고서", token_a, slot, opt_a, "r1")
    assert first.mutation_outcome is not None and first.mutation_outcome.changed  # config v1
    token_v1 = first.current_view.new_configuration_token  # v1 을 본 유효 token
    assert token_v1 is not None

    second = product.select_slot_option("공고서", token_v1, slot, opt_b, "r2")
    assert second.mutation_outcome is not None and second.mutation_outcome.changed  # config v2

    # v1 을 본 token 을 같은 application 에 재제출 → version CAS 가 STALE_CONFIGURATION 으로 막는다.
    resp = product.select_slot_option("공고서", token_v1, slot, opt_a, "r3")
    assert resp.mutation_outcome is not None
    assert resp.mutation_outcome.outcome_code == "STALE_CONFIGURATION"
    assert resp.mutation_outcome.changed is False  # 유효 서명에도 미적용
    assert resp.mutation_outcome.request_relation == "STALE_CONFIGURATION"


def test_valid_token_does_not_grant_authorization(tmp_path: Path) -> None:
    """암호적으로 유효한 token 을 쥐어도 route authorization 을 대신할 수 없다.

    authorization 은 ``_route`` 의 job load 가 지고 token 검증(``_verify_token``)보다 **앞선다**.
    유효 서명 token 을 부재 work_ref 로 제출하면 token 을 들여다보기 전에 AUTHORIZATION_FAILURE
    로 거절된다 — HMAC 은 authorization 경계가 아니다.
    """
    _reg, product = _bootstrapped(tmp_path)
    product.open_slot_configuration("공고서")  # ws·secret 확립
    valid_token = _forged(tmp_path, work_authority_id="some-work")  # 실 secret 서명 = 유효
    with pytest.raises(SlotConfigurationProductError) as ei:
        product.select_slot_option("없는작업", valid_token, "s", "o", "r")
    assert ei.value.code == "AUTHORIZATION_FAILURE"


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
