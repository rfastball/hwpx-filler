"""S4-09(#679) Product API: route-bound Work, HMAC token, fresh view/token 조립."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

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
    assert resp.current_view.context_error_message == (
        "템플릿 확인이 끝나지 않아 포함할 내용을 불러오지 못했습니다. 템플릿을 확인하세요."
    )
    assert resp.current_view.new_configuration_token is None
    assert resp.refresh_required is True

    passive = product.current_slot_configuration_view("공고서")
    assert passive.current_view.context_error_message == resp.current_view.context_error_message

    unknown = product._context_error_response("FUTURE_CONTEXT_ERROR")
    assert unknown.current_view.context_error == "FUTURE_CONTEXT_ERROR"
    assert unknown.current_view.context_error_message == (
        "포함할 내용을 불러오지 못했습니다. 문서 작업을 다시 열고 템플릿을 확인하세요."
    )


def test_every_known_context_error_has_specific_user_copy() -> None:
    import hwpxfiller.webapp.slot_configuration_product as mod

    from hwpxfiller.application.slot_configuration_context import (
        SlotConfigurationContextError,
    )

    known_codes = {
        error.code
        for error in SlotConfigurationContextError.__subclasses__()
        if error.__module__ == SlotConfigurationContextError.__module__
    }
    assert set(mod._CONTEXT_ERROR_MESSAGES) == known_codes
    assert all(code not in message for code, message in mod._CONTEXT_ERROR_MESSAGES.items())


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


# ── #744: read-only projection 은 durable S4 authority 를 mutate 하지 않는다 ─────────────────
def test_read_only_view_never_calls_ensure(tmp_path: Path, monkeypatch) -> None:
    # render/snapshot 경로가 쓰는 read-only projection 은 ensure_current_slot_configuration 을
    # 부르지 않는다 — stored config 부재 시 successor reconciliation 을 persist(CHANGED)하지 않는다.
    # ensure 는 명시적 open command 에만 남는다. spy 로 호출 유무를 직접 판정한다(결정론적).
    import hwpxfiller.webapp.slot_configuration_product as mod

    calls = {"ensure": 0}
    real = mod.ensure_current_slot_configuration

    def spy(*a, **k):
        calls["ensure"] += 1
        return real(*a, **k)

    monkeypatch.setattr(mod, "ensure_current_slot_configuration", spy)
    _reg, product = _bootstrapped(tmp_path)

    ro = product.current_slot_configuration_view("공고서")
    assert calls["ensure"] == 0  # read-only — ensure 미호출(durable mutation 없음)
    assert ro.mutation_outcome is None
    assert ro.current_view.view_status == "CURRENT"
    assert ro.current_view.new_configuration_token  # token 은 발급(편집 seam) — config 는 미저장

    product.open_slot_configuration("공고서")
    assert calls["ensure"] == 1  # 명시적 open 만 ensure 를 탄다


def test_read_only_view_matches_open_view_status_and_projection(tmp_path: Path) -> None:
    # read-only projection 이 낸 current view 는 명시적 open 이 낸 것과 같은 view_status·projection
    # 형상을 나른다(성형 공유) — 렌더 소비자는 두 경로에서 동일 계약을 본다.
    _reg, product = _bootstrapped(tmp_path)
    ro = product.current_slot_configuration_view("공고서")
    opened = product.open_slot_configuration("공고서")
    assert ro.current_view.view_status == opened.current_view.view_status == "CURRENT"
    assert (ro.current_view.projection is None) == (opened.current_view.projection is None)


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


# ── #777: successor 로 넘어간 뒤 **이전에 고른 것이 어떻게 됐는지** ──────────────────────
#
# SG-01(#733) compatibility gate 는 Template 이 바뀌면 의미 동일성을 exact 증명하지 못한 선택을
# successor 선언집합에 싣지 않는다 — fail-closed 설계이고 그건 옳다. 문제는 그 사실이 **아무
# 데도 안 남았다**는 것이다: 사용자가 고른 셋이 조용히 사라지고 화면은 「아직 선택 안 함」만
# 말했다. 여기서 재는 것은 셋이 서로 **다른 것으로** 드러나는가다(#728 H4).
_S_KEEP, _S_GONE = "s-keep", "s-gone"
_O_KEEP, _O_DROP, _O_ONLY = "o-keep", "o-drop", "o-only"


def _metatag(kind: str, identifier: str, label: str) -> str:
    return json.dumps(
        {"hwpxFiller": {"kind": kind, "id": identifier, "label": label}, "name": "#hf"},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _para(content: str) -> str:
    return f"<hp:p><hp:run>{content}</hp:run></hp:p>"


def _bm_begin(identifier: str, metatag: str) -> str:
    return (
        f'<hp:ctrl><hp:fieldBegin id="{identifier}" type="BOOKMARK" name="bm{identifier}">'
        f"<hp:metaTag>{escape(metatag)}</hp:metaTag>"
        "</hp:fieldBegin></hp:ctrl>"
    )


def _bm_end(identifier: str) -> str:
    return f'<hp:ctrl><hp:fieldEnd beginIDRef="{identifier}"/></hp:ctrl>'


def _named_field(name: str) -> str:
    return (
        f'<hp:ctrl><hp:fieldBegin name="{name}"/></hp:ctrl>'
        f"<hp:t>{{{{{name}}}}}</hp:t>"
        "<hp:ctrl><hp:fieldEnd/></hp:ctrl>"
    )


def _option(bookmark: str, option_id: str, label: str, field: str) -> str:
    return (
        _para(_bm_begin(bookmark, _metatag("slot_option", option_id, label)) + "<hp:t>o</hp:t>")
        + _para(_named_field(field))
        + _para("<hp:t>oe</hp:t>" + _bm_end(bookmark))
    )


def _two_slot_template(path: Path, *, successor: bool = False) -> None:
    """Slot 둘 · Option 셋. successor 는 Option 하나와 Slot 하나를 **동시에** 걷어낸다.

    셋이 한 fixture 에 같이 있어야 「같은 행동으로 뭉뚱그렸는가」를 실제로 물을 수 있다.

    ``s-keep``  Option ``o-keep`` 유지 · Option ``o-drop`` 제거   → 유지 / 고른 것이 사라짐
    ``s-gone``  Slot 통째 제거                                    → 항목 자체가 사라짐
    """
    body = _para(_named_field("공고명"))
    body += _para(_bm_begin("1", _metatag("slot", _S_KEEP, "공고 상세")) + "<hp:t>s</hp:t>")
    body += _option("2", _O_KEEP, "추정가격 표시", "추정가격")
    if not successor:
        body += _option("3", _O_DROP, "담당자 표시", "담당자")
    body += _para("<hp:t>se</hp:t>" + _bm_end("1"))
    if not successor:
        body += _para(_bm_begin("4", _metatag("slot", _S_GONE, "부가 안내")) + "<hp:t>s</hp:t>")
        body += _option("5", _O_ONLY, "안내 문단 포함", "안내문")
        body += _para("<hp:t>se</hp:t>" + _bm_end("4"))
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">' + body + "</hs:sec>"
    ).encode()
    write_hwpx_package(
        path,
        HwpxPackage(
            entries={MIMETYPE_NAME: MIMETYPE_VALUE, "Contents/section0.xml": xml},
            stored={MIMETYPE_NAME},
        ),
    )


def _slot_bearing_work(tmp_path: Path):
    """production Apply 로 Slot 둘짜리 Work 를 세운다 — store 직접 seed 0."""
    tpl = tmp_path / "공고서.hwpx"
    _two_slot_template(tpl)
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="공고서", template_path=str(tpl)))
    coord = TemplateChangeCoordinator(reg, root=_root(tmp_path), clock=_clock())
    coord.check("공고서", "k1")
    product = SlotConfigurationProduct(reg, root=_root(tmp_path), clock=_clock())
    return tpl, coord, product


def _advance_to_successor(tpl: Path, coord: TemplateChangeCoordinator) -> None:
    _two_slot_template(tpl, successor=True)
    ready = coord.check("공고서", "k2")["preparation"]
    coord.apply("공고서", ready["change_token"])


def _census(*roots: Path) -> "dict[str, bytes]":
    """트리 전체의 ``상대경로 → bytes``.

    ensure 호출 유무를 spy 로 세는 것으로는 부족하다 — store 를 직접 쓰는 경로는 그 그물을
    통과한다. 「무엇을 안 불렀는가」가 아니라 **「무엇이 안 바뀌었는가」** 를 센다.
    """
    manifest: "dict[str, bytes]" = {}
    for root in roots:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                manifest[f"{root.name}/{path.relative_to(root).as_posix()}"] = path.read_bytes()
    return manifest


def test_successor_view_tells_what_became_of_each_previous_selection(tmp_path: Path) -> None:
    """셋은 서로 **다른 것으로** 드러난다 — 유지 / 고른 것이 사라짐 / 항목이 사라짐(#728 H4).

    종전에는 셋이 똑같이 사라져 화면에서 구별되지 않았다. 「숨기는 대신 비활성 + 사유 병기」의
    정반대이고, 하필 법적 효력이 있는 문서의 내용 선택에서 그랬다.
    """
    tpl, coord, product = _slot_bearing_work(tmp_path)
    token = product.open_slot_configuration("공고서").current_view.new_configuration_token
    assert token is not None
    product.select_slot_option("공고서", token, _S_KEEP, _O_DROP, "r1")
    token = product.current_slot_configuration_view("공고서").current_view.new_configuration_token
    assert token is not None
    product.select_slot_option("공고서", token, _S_GONE, _O_ONLY, "r2")

    _advance_to_successor(tpl, coord)

    view = product.current_slot_configuration_view("공고서").current_view.projection
    assert view is not None
    fates = {r.slot_id: r for r in view.retained_selections}
    assert set(fates) == {_S_KEEP, _S_GONE}, "이전 선택이 조용히 사라졌습니다"

    kept = fates[_S_KEEP]
    assert kept.fate == "SELECTED_OPTION_REMOVED"  # slot 은 남고 고른 option 이 사라졌다
    assert kept.option_ids == (_O_DROP,)
    assert kept.slot_display_text == "공고 상세"  # 남은 Slot 은 이름을 댈 수 있다

    gone = fates[_S_GONE]
    assert gone.fate == "SLOT_REMOVED"  # 항목 자체가 사라졌다 — 정보일 뿐
    assert gone.slot_display_text is None

    # 셋을 한 값으로 뭉치지 않았는가 — 서로 다른 fate 여야 이 계약이 무언가를 지킨다.
    assert kept.fate != gone.fate
    # 그리고 자동 부활은 없다: 사라진 항목은 현재 구성의 일부가 아니다.
    assert all(slot.slot_id != _S_GONE for slot in view.slots)
    assert view.configuration_status == "NEEDS_SELECTION"


def test_a_surviving_previous_choice_is_named_not_silently_dropped(tmp_path: Path) -> None:
    """successor 에도 있는 선택은 **그대로 다시 고를 수 있다**고 이름과 함께 드러난다.

    자동 승계가 아니다 — Template 이 바뀌었으므로 확인은 사용자가 한다(SG-01 fail-closed).
    그러나 「내가 고른 게 무엇이었는지」까지 잃을 이유는 없다.
    """
    tpl, coord, product = _slot_bearing_work(tmp_path)
    token = product.open_slot_configuration("공고서").current_view.new_configuration_token
    assert token is not None
    product.select_slot_option("공고서", token, _S_KEEP, _O_KEEP, "r1")

    _advance_to_successor(tpl, coord)

    view = product.current_slot_configuration_view("공고서").current_view.projection
    assert view is not None
    (kept,) = [r for r in view.retained_selections if r.slot_id == _S_KEEP]
    assert kept.fate == "RESOLVED"
    assert kept.option_ids == (_O_KEEP,)
    # 그러나 effective 는 아니다 — 다시 확인해야 닫힌다(false AUTO_KEEP 금지).
    (slot,) = [s for s in view.slots if s.slot_id == _S_KEEP]
    assert slot.effective_option_ids == ()
    assert slot.status == "MISSING_REQUIRED_SELECTION"


def test_reading_the_successor_view_writes_no_configuration(tmp_path: Path) -> None:
    """passive view 는 durable S4 를 **바이트 하나** 안 건드린다(#744).

    ensure spy 만으로는 store 를 직접 쓰는 경로를 못 본다. 한 번 불러 create-once 부작용
    (authority_id·workspace·token secret)을 끝낸 뒤, 그다음부터 트리 전체를 바이트로 고정한다.
    """
    tpl, coord, product = _slot_bearing_work(tmp_path)
    token = product.open_slot_configuration("공고서").current_view.new_configuration_token
    assert token is not None
    product.select_slot_option("공고서", token, _S_KEEP, _O_DROP, "r1")
    _advance_to_successor(tpl, coord)

    product.current_slot_configuration_view("공고서")  # create-once 부작용을 여기서 끝낸다
    before = _census(_root(tmp_path), tmp_path / "jobs")
    assert before, "센 것이 0건이면 이 계약이 아무것도 안 지킵니다"

    for _ in range(3):
        assert product.current_slot_configuration_view("공고서").current_view.projection

    assert _census(_root(tmp_path), tmp_path / "jobs") == before
    # 음성 대조 — 명시적 open 은 **바꾼다**(이 검사가 항상 참이 아니다).
    product.open_slot_configuration("공고서")
    assert _census(_root(tmp_path), tmp_path / "jobs") != before


def test_a_current_configuration_leaves_no_room_for_a_previous_story(tmp_path: Path) -> None:
    """current Application 에 Configuration 이 있으면 그 선택이 곧 답이라 물을 것이 없다.

    두 이야기를 동시에 하면 「지금 골라져 있는 것」과 「이전에 골랐던 것」이 섞인다.
    """
    _tpl, _coord, product = _slot_bearing_work(tmp_path)
    token = product.open_slot_configuration("공고서").current_view.new_configuration_token
    assert token is not None
    product.select_slot_option("공고서", token, _S_KEEP, _O_KEEP, "r1")

    view = product.current_slot_configuration_view("공고서").current_view.projection
    assert view is not None and view.configuration_present is True
    assert view.retained_selections == ()


def test_answering_one_slot_does_not_erase_the_rest_of_the_story(tmp_path: Path) -> None:
    """첫 클릭 한 번이 나머지 사연을 지우지 않는다.

    successor 에서 한 칸을 고르는 순간 Configuration 이 생긴다. 그 **존재**를 「다 해결됐다」로
    읽으면, 아직 안 고른 항목도 사라진 항목도 함께 증발한다 — 사용자는 자기가 방금 무엇을
    잃었는지 영영 못 본다. 닫힘의 기준은 Configuration 유무가 아니라 **그 항목이 닫혔는가**다.
    """
    tpl, coord, product = _slot_bearing_work(tmp_path)
    token = product.open_slot_configuration("공고서").current_view.new_configuration_token
    assert token is not None
    product.select_slot_option("공고서", token, _S_KEEP, _O_KEEP, "r1")
    token = product.current_slot_configuration_view("공고서").current_view.new_configuration_token
    assert token is not None
    product.select_slot_option("공고서", token, _S_GONE, _O_ONLY, "r2")

    _advance_to_successor(tpl, coord)

    before = product.current_slot_configuration_view("공고서").current_view.projection
    assert before is not None
    assert {r.slot_id for r in before.retained_selections} == {_S_KEEP, _S_GONE}

    # successor 에서 s-keep 을 다시 고른다 → Configuration 이 생긴다.
    token = product.current_slot_configuration_view("공고서").current_view.new_configuration_token
    assert token is not None
    resp = product.select_slot_option("공고서", token, _S_KEEP, _O_KEEP, "r3")
    assert resp.mutation_outcome is not None and resp.mutation_outcome.changed is True

    after = product.current_slot_configuration_view("공고서").current_view.projection
    assert after is not None and after.configuration_present is True
    fates = {r.slot_id: r for r in after.retained_selections}
    assert _S_KEEP not in fates, "다시 고른 항목은 닫혔으므로 더 말하지 않는다"
    assert fates[_S_GONE].fate == "SLOT_REMOVED", "사라진 항목의 사연은 남아 있어야 한다"


def test_the_explicit_open_path_shows_the_story_too(tmp_path: Path) -> None:
    """명시적 open/refresh 도 같은 사연을 낸다.

    open 은 view 를 만들기 **전에** Configuration 을 물질화한다. 그러니 Configuration 존재로
    끊으면 하필 사용자가 「포함할 내용」을 여는 그 순간에 이 정보가 통째로 사라진다.
    """
    tpl, coord, product = _slot_bearing_work(tmp_path)
    token = product.open_slot_configuration("공고서").current_view.new_configuration_token
    assert token is not None
    product.select_slot_option("공고서", token, _S_GONE, _O_ONLY, "r1")

    _advance_to_successor(tpl, coord)

    opened = product.open_slot_configuration("공고서").current_view.projection
    assert opened is not None
    assert [(r.slot_id, r.fate) for r in opened.retained_selections] == [(_S_GONE, "SLOT_REMOVED")]

    # 그리고 두 경로가 같은 것을 본다 — 렌더와 command 응답이 갈라지지 않는다.
    passive = product.current_slot_configuration_view("공고서").current_view.projection
    assert passive is not None
    assert passive.retained_selections == opened.retained_selections
