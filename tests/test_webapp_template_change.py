"""템플릿 변경 확인·적용 코디네이터(S3-09 #659) — opaque Product Contract 의 경계 가드.

실파일 스토어(tmp_path) 위에서 사용자 능력 둘([변경사항 확인]·[변경사항 적용])의 왕복을
되읽는다. 지키는 것: 내부 ID·revision 비노출, ready 에서만 change_token, token 은 권한이
아니다(cross-Work·추측 거절 + 상태 무변경), bootstrap 실패의 비활성+사유, 세션 중단의
INTERRUPTED 수렴, 개명의 권위 인덱스 추종. 내부 status → 제품 status 투영표(순수)도 이
파일이 소유한다 — 같은 경계의 두 층이라 한 파일에 둔다.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.application.prepare_orchestration import APPLY_INTEGRITY_ERROR, ApplyOutcome
from hwpxfiller.application.template_change_product import (
    TemplateChangeProjectionError,
    preparation_view,
    product_preparation_status,
)
from hwpxfiller.application.work_template_state import (
    CHANGE_APPLIED,
    CHANGE_CONFLICTED,
    CHANGE_PREPARED,
    CHANGE_REJECTED,
    CHANGE_SUPERSEDED,
    TemplateChangePreparation,
)
from hwpxfiller.domain.job import Job
from hwpxfiller.external.hwpx_package_io import write_hwpx_package
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.webapp import template_change as tc
from hwpxfiller.webapp.template_change import (
    TemplateChangeCoordinator,
    TemplateChangeError,
    unsupported_zone,
)

_NOW = datetime(2026, 8, 15, 9, 0, 0)


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


def _seed(tmp_path, *, name="공고서", template="공고서.hwpx", fields=("공고명",)):
    tpl = tmp_path / template
    _write_template(tpl, list(fields))
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name=name, template_path=str(tpl)))
    return reg, tpl


def _coordinator(tmp_path, reg) -> TemplateChangeCoordinator:
    return TemplateChangeCoordinator(reg, root=tmp_path / "authority", clock=_clock())


def _ready(tmp_path):
    """bootstrap(무변경) → 원본 수정 → READY change_token 까지 세운 공용 전제."""
    reg, tpl = _seed(tmp_path)
    coord = _coordinator(tmp_path, reg)
    first = coord.check("공고서", "k1")
    assert first["preparation"]["status"] == "no_change"
    _write_template(tpl, ["공고명", "추정가격"])  # 실물 수정(크기 변화)
    ready = coord.check("공고서", "k2")["preparation"]
    assert ready["status"] == "ready" and ready["change_token"]
    return reg, tpl, coord, ready["change_token"]


# ─── prepare: capability·bootstrap·멱등 ─────────────────────────────────────


def test_non_hwpx_job_is_refused_and_zone_unsupported(tmp_path):
    reg = JobRegistry(tmp_path / "jobs")
    txt = tmp_path / "안내.txt"
    txt.write_text("본문", encoding="utf-8")
    reg.save(Job(name="안내", template_path=str(txt)))
    coord = _coordinator(tmp_path, reg)
    assert coord.zone("안내", "txt", False) == unsupported_zone()
    with pytest.raises(TemplateChangeError):
        coord.check("안내", "k1")


def test_first_check_bootstraps_current_bytes_to_no_change(tmp_path):
    reg, _tpl = _seed(tmp_path)
    coord = _coordinator(tmp_path, reg)
    result = coord.check("공고서", "k1")
    view = result["preparation"]
    assert result["ok"] is True
    assert view["status"] == "no_change"
    assert view["change_token"] is None  # ready 에서만 존재
    zone = coord.zone("공고서", "hwpx", False)
    assert zone["supported"] and zone["checkable"] and zone["epoch"] == 1


def test_same_request_key_is_idempotent_new_key_is_new_intent(tmp_path):
    reg, _tpl = _seed(tmp_path)
    coord = _coordinator(tmp_path, reg)
    a = coord.check("공고서", "k1")["preparation"]
    b = coord.check("공고서", "k1")["preparation"]  # 재전송 — 같은 Preparation
    c = coord.check("공고서", "k2")["preparation"]  # 새 intent
    assert a["preparation_token"] == b["preparation_token"]
    assert c["preparation_token"] != a["preparation_token"]


def test_bootstrap_failure_disables_check_until_template_repaired(tmp_path):
    reg = JobRegistry(tmp_path / "jobs")
    tpl = tmp_path / "깨진.hwpx"
    tpl.write_bytes(b"not a zip")
    reg.save(Job(name="깨진작업", template_path=str(tpl)))
    coord = _coordinator(tmp_path, reg)
    result = coord.check("깨진작업", "k1")
    assert result == {"ok": False, "reason": "initialization_required"}
    zone = coord.zone("깨진작업", "hwpx", False)
    assert zone["reason"] == "initialization_required"
    assert zone["checkable"] is False and zone["diagnostics"]  # 비활성 + 사유 병기
    _write_template(tpl, ["공고명"])  # 실물 수리(레지스트리 무접촉 — 한글에서 고친 경로)
    assert coord.zone("깨진작업", "hwpx", False)["checkable"] is True
    assert coord.check("깨진작업", "k2")["preparation"]["status"] == "no_change"


# ─── ready → apply 왕복 ─────────────────────────────────────────────────────


def test_edited_template_reaches_ready_without_internal_identity(tmp_path):
    _reg, tpl, coord, _token = _ready(tmp_path)
    zone = coord.zone("공고서", "hwpx", False)
    view = zone["preparation"]
    assert set(view) == {
        "preparation_token", "status", "change_token", "diagnostics", "prepared_at",
    }
    # token 은 난수라 부분열 대조에서 **빼고** 본다 — 남는 것이 전부 계약 필드다.
    masked = dict(zone, preparation=dict(view, preparation_token="", change_token=""))
    serialized = json.dumps(masked, ensure_ascii=False)
    for forbidden in (
        "revision", "evidence", "profile", "base_application", "generation",
        str(tpl), "w-",  # 내부 work_id 접두도 밖으로 안 나간다
    ):
        assert forbidden not in serialized


def test_apply_advances_epoch_and_restates_current(tmp_path):
    _reg, _tpl, coord, token = _ready(tmp_path)
    result = coord.apply("공고서", token)
    assert result == {
        "status": "applied",
        "current_template_application_epoch": 2,
        "is_current": True,
    }
    assert coord.zone("공고서", "hwpx", False)["epoch"] == 2
    assert coord.get_current_template_change_preparation("공고서")["status"] == "applied"


def test_apply_resend_is_already_applied(tmp_path):
    _reg, _tpl, coord, token = _ready(tmp_path)
    coord.apply("공고서", token)
    again = coord.apply("공고서", token)  # 응답 유실 후 재요청 경로
    assert again["status"] == "already_applied"
    assert again["current_template_application_epoch"] == 2


def test_restored_prepared_change_applies_after_restart(tmp_path):
    # 재시작 세션에서 durable PREPARED change 를 zone() 로 재발급한 token 의 restored-apply 가
    # check 없이 성공한다. (R2-05a: mutable Profile admission gate 가 사라져 STATE_MISSING 으로
    # 막힐 여지 자체가 없다 — apply 는 exact qualification evidence + Work-local currentness 로 닫힌다.)
    reg, _tpl, _coord, _token = _ready(tmp_path)
    restarted = _coordinator(tmp_path, reg)  # 재시작 — 세션 token map 비어 있음
    view = restarted.zone("공고서", "hwpx", False)["preparation"]  # check 없이 token 재발급
    assert view["status"] == "ready" and view["change_token"]
    result = restarted.apply("공고서", view["change_token"])
    assert result["status"] == "applied"
    assert result["current_template_application_epoch"] == 2


def test_newer_check_supersedes_old_token_without_mutation(tmp_path):
    _reg, _tpl, coord, old_token = _ready(tmp_path)
    newer = coord.check("공고서", "k3")["preparation"]  # 같은 bytes — 새 intent 가 이긴다
    result = coord.apply("공고서", old_token)
    assert result["status"] == "superseded"
    assert result["current_template_application_epoch"] == 1  # Work 무변경
    assert newer["status"] == "ready"
    assert coord.apply("공고서", newer["change_token"])["status"] == "applied"


def test_cross_work_token_is_rejected_and_change_survives(tmp_path):
    reg, tpl, coord, token = _ready(tmp_path)
    other = tmp_path / "다른.hwpx"
    _write_template(other, ["기관명"])
    reg.save(Job(name="다른작업", template_path=str(other)))
    coord.check("다른작업", "b1")  # 다른 Work 도 세워 둔다
    with pytest.raises(TemplateChangeError):
        coord.apply("다른작업", token)  # cross-Work misuse
    # 두 Work·정상 Change 전부 무변경 — 원 Work 에서 같은 token 이 그대로 적용된다.
    assert coord.zone("다른작업", "hwpx", False)["epoch"] == 1
    assert coord.apply("공고서", token)["status"] == "applied"


def test_guessed_token_cannot_apply(tmp_path):
    _reg, _tpl, coord, _token = _ready(tmp_path)
    with pytest.raises(TemplateChangeError):
        coord.apply("공고서", "guessed-token")
    assert coord.zone("공고서", "hwpx", False)["epoch"] == 1


def test_integrity_failure_is_loud_not_a_domain_status(tmp_path, monkeypatch):
    _reg, _tpl, coord, token = _ready(tmp_path)
    monkeypatch.setattr(
        tc, "apply_prepared_change",
        # public entry 는 (outcome, committed_aggregate) 튜플을 돌려준다(#675) — 무결성
        # 오류는 aggregate 사용 전에 raise 하므로 view 는 None 이어도 된다.
        lambda *a, **k: (ApplyOutcome(APPLY_INTEGRITY_ERROR, None), None),
    )
    with pytest.raises(TemplateChangeError):
        coord.apply("공고서", token)


# ─── 실패·중단·개명 ─────────────────────────────────────────────────────────


def test_qualification_failure_projects_invalid_with_diagnostics(tmp_path):
    reg, tpl = _seed(tmp_path)
    coord = _coordinator(tmp_path, reg)
    coord.check("공고서", "k1")  # bootstrap
    tpl.write_bytes(b"broken bytes")  # 원본이 hwpx 가 아니게 손상
    view = coord.check("공고서", "k2")["preparation"]
    assert view["status"] == "invalid"
    assert view["diagnostics"]  # Candidate 유래 진단 재진술(빈 fallback 금지)
    assert view["change_token"] is None
    assert coord.zone("공고서", "hwpx", False)["epoch"] == 1  # 기존 Work 계속 사용


def test_crashed_session_preparation_recovers_as_interrupted(tmp_path, monkeypatch):
    reg, _tpl = _seed(tmp_path)
    crashed = _coordinator(tmp_path, reg)
    monkeypatch.setattr(
        tc, "run_capture_stage", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("죽음"))
    )
    with pytest.raises(RuntimeError):
        crashed.check("공고서", "k1")
    monkeypatch.undo()
    fresh = _coordinator(tmp_path, reg)  # 새 process 세션
    assert fresh.get_current_template_change_preparation("공고서")["status"] == "interrupted"


def test_rename_follows_work_identity(tmp_path):
    """identity 는 Job durable 필드라 개명을 저절로 따라간다 — 옮길 인덱스·훅이 없다."""
    reg, _tpl, coord, token = _ready(tmp_path)
    reg.rename("공고서", "공고서2")
    assert coord.zone("공고서2", "hwpx", False)["epoch"] == 1
    assert coord.apply("공고서2", token)["status"] == "applied"  # 이력·token 생존


def test_recycled_name_is_a_fresh_work_and_inherits_nothing(tmp_path):
    """삭제된 작업의 이름을 새 작업이 재사용해도 남의 권위 이력·token 을 물려받지 않는다."""
    reg, tpl, coord, token = _ready(tmp_path)
    reg.delete("공고서")
    _write_template(tpl, ["기관명"])
    reg.save(Job(name="공고서", template_path=str(tpl)))  # 같은 이름, 다른 작업
    zone = coord.zone("공고서", "hwpx", False)
    assert zone["epoch"] is None and zone["preparation"] is None  # 이력 미승계
    with pytest.raises(TemplateChangeError):
        coord.apply("공고서", token)  # 죽은 작업의 token 은 새 작업에 못 앉는다
    assert coord.check("공고서", "n1")["preparation"]["status"] == "no_change"  # 새 Work 로 시작


def test_bootstrap_failure_survives_restart(tmp_path):
    """실패 기록은 durable — 재시작해도 같은 실물이면 비활성+사유가 유지된다."""
    reg = JobRegistry(tmp_path / "jobs")
    tpl = tmp_path / "깨진.hwpx"
    tpl.write_bytes(b"not a zip")
    reg.save(Job(name="깨진작업", template_path=str(tpl)))
    first = _coordinator(tmp_path, reg)
    assert first.check("깨진작업", "k1")["ok"] is False
    restarted = _coordinator(tmp_path, reg)  # 새 process
    zone = restarted.zone("깨진작업", "hwpx", False)
    assert zone["checkable"] is False and zone["diagnostics"]


# ─── 내부 → 제품 status 투영(순수) ──────────────────────────────────────────


def _prep(status: str) -> TemplateChangePreparation:
    return TemplateChangePreparation(
        preparation_id="P1", work_id="W1", prepare_request_id="R1", prepare_seq=1,
        base_application_id="A1", source_binding_id="SB1", source_binding_generation=1,
        qualification_profile_id="PR1", execution_session_id="S1", status=status,
        started_at="t0",
    )


@pytest.mark.parametrize(
    ("status", "change", "expected"),
    [
        ("CAPTURING", None, "checking"),
        ("QUALIFYING", None, "checking"),
        ("NO_CHANGE", None, "no_change"),
        ("CAPTURE_ERROR", None, "error"),
        ("QUALIFICATION_ERROR", None, "error"),
        ("QUALIFICATION_FAILED", None, "invalid"),
        ("INTERRUPTED", None, "interrupted"),
        ("SOURCE_BINDING_CHANGED", None, "source_changed"),
        ("BASE_CHANGED", None, "changed_while_checking"),
        ("PROFILE_REVOKED", None, "rejected"),
        ("SUPERSEDED", None, "superseded"),
        ("READY", CHANGE_PREPARED, "ready"),
        ("READY", CHANGE_APPLIED, "applied"),
        ("READY", CHANGE_SUPERSEDED, "superseded"),
        ("READY", CHANGE_CONFLICTED, "conflict"),
        ("READY", CHANGE_REJECTED, "rejected"),
    ],
)
def test_projection_table(status, change, expected):
    assert product_preparation_status(_prep(status), change) == expected


def test_projection_refuses_ready_without_change_and_unknown_change():
    with pytest.raises(TemplateChangeProjectionError):
        product_preparation_status(_prep("READY"), None)
    with pytest.raises(TemplateChangeProjectionError):
        product_preparation_status(_prep("READY"), "몰라")


def test_view_drops_change_token_unless_ready():
    view = preparation_view(
        _prep("READY"), CHANGE_APPLIED,
        preparation_token="pt", change_token="ct",
    )
    assert view["status"] == "applied" and view["change_token"] is None
