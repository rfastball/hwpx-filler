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
from hwpxfiller.application.selection_compatibility import REVIEW_REQUIRED
from hwpxfiller.application.template_change_product import (
    PRODUCT_PREPARATION_STATUSES,
    SOURCE_DRIFT_CHANGED,
    SOURCE_DRIFT_UNCHANGED,
    SOURCE_DRIFT_UNKNOWN,
    TemplateChangeProjectionError,
    preparation_view,
    product_preparation_status,
    template_change_zone_actionable,
    workbench_template_change_verdict,
)
from hwpxfiller.application.work_template_state import (
    CHANGE_APPLIED,
    CHANGE_CONFLICTED,
    CHANGE_PREPARED,
    CHANGE_REJECTED,
    CHANGE_SUPERSEDED,
    TemplateChangePreparation,
)
from hwpxfiller.application.jobs import load_job
from hwpxfiller.domain.job import Job
from hwpxfiller.external.hwpx_package_io import write_hwpx_package
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.webapp import template_change as tc
from hwpxfiller.webapp.template_change import (
    NO_SOURCE_DRIFT_JUDGMENT,
    SUPPORTED_MEDIA,
    SourceDrift,
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


def test_unsupported_media_job_is_refused_and_zone_unsupported(tmp_path):
    """미지원 매체는 조용히 추측하지 않고 capability 를 감춘 채 시끄럽게 거절한다.

    지원 매체 집합(hwpx·txt)은 코디네이터 단일 출처라 이 테스트도 그것을 묻는다 —
    「hwpx 가 아니면 거절」을 재타이핑하면 TXT 인수(S10-02) 같은 확장에서 이 테스트가
    거짓 빨강을 낸다.
    """
    reg = JobRegistry(tmp_path / "jobs")
    other = tmp_path / "안내.docx"
    other.write_bytes(b"not a template")
    reg.save(Job(name="안내", template_path=str(other)))
    coord = _coordinator(tmp_path, reg)
    assert "" not in SUPPORTED_MEDIA  # 미상 매체는 지원 집합 밖(fail-closed)
    assert coord.zone("안내", "", False) == unsupported_zone()
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


# ─── TXT 매체 인수(S10-02 #859) ─────────────────────────────────────────────
# 사건 경계는 위 hwpx 왕복이 이미 소유한다 — 여기서 다시 세우지 않고, **매체가 갈리는
# 자리**만 본다: 자격 심사(qualification profile)와 그 진단, 그리고 캡처본이 원본 변이에
# 흔들리지 않는다는 Candidate 불변성.


def _seed_txt(tmp_path, *, name="안내문", body="본문 {{공고명}}\n"):
    tpl = tmp_path / "안내문.txt"
    tpl.write_text(body, encoding="utf-8")
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name=name, template_path=str(tpl)))
    return reg, tpl


def test_txt_check_and_apply_advance_the_same_lifecycle(tmp_path):
    reg, tpl = _seed_txt(tmp_path)
    coord = _coordinator(tmp_path, reg)
    first = coord.check("안내문", "k1")
    assert first["ok"] is True and first["preparation"]["status"] == "no_change"
    zone = coord.zone("안내문", "txt", False)
    assert zone["supported"] and zone["checkable"] and zone["epoch"] == 1

    tpl.write_text("본문 {{공고명}}\n덧붙임 {{담당자}}\n", encoding="utf-8")
    ready = coord.check("안내문", "k2")["preparation"]
    assert ready["status"] == "ready" and ready["change_token"]
    result = coord.apply("안내문", ready["change_token"])
    assert result == {
        "status": "applied",
        "current_template_application_epoch": 2,
        "is_current": True,
    }
    assert coord.zone("안내문", "txt", False)["epoch"] == 2


def test_txt_authority_id_is_issued_by_the_first_check(tmp_path):
    reg, _tpl = _seed_txt(tmp_path)
    coord = _coordinator(tmp_path, reg)
    assert load_job(reg, "안내문").authority_id == ""  # 조용한 migration 없음
    coord.check("안내문", "k1")
    issued = load_job(reg, "안내문").authority_id
    assert issued and coord.current_template_application_id(issued)


def test_txt_structure_marker_diagnostics_project_invalid_with_reasons(tmp_path):
    """구간 표기가 깨진 TXT 는 빈 구조로 통과하지 않고 사유를 재진술한다."""
    reg, tpl = _seed_txt(tmp_path)
    coord = _coordinator(tmp_path, reg)
    coord.check("안내문", "k1")  # bootstrap(정상 표기)
    tpl.write_text("{{#항목 s1 첨부}}\n내용 {{공고명}}\n", encoding="utf-8")  # 닫는 마커 없음
    view = coord.check("안내문", "k2")["preparation"]
    assert view["status"] == "invalid" and view["change_token"] is None
    # kind 는 코어 진단 어휘 그대로다 — 매체 어댑터가 다시 이름 짓지 않는다.
    assert {d["kind"] for d in view["diagnostics"]} == {"unbalanced_marker"}
    assert all(d["message"] for d in view["diagnostics"])  # 빈 fallback 금지
    assert coord.zone("안내문", "txt", False)["epoch"] == 1  # 기존 Work 계속 사용


def test_txt_encoding_failure_is_a_loud_diagnostic_not_an_empty_structure(tmp_path):
    reg, tpl = _seed_txt(tmp_path)
    coord = _coordinator(tmp_path, reg)
    coord.check("안내문", "k1")
    tpl.write_bytes("본문 {{공고명}}".encode("cp949"))  # 온나라 기안 txt 의 흔한 인코딩
    view = coord.check("안내문", "k2")["preparation"]
    assert view["status"] == "invalid"
    assert any(d["kind"] == "txt_encoding" for d in view["diagnostics"])


def test_txt_bootstrap_failure_disables_check_until_repaired(tmp_path):
    reg = JobRegistry(tmp_path / "jobs")
    tpl = tmp_path / "깨진.txt"
    tpl.write_bytes(b"\xff\xfe\x00\x00")  # UTF-8 아님
    reg.save(Job(name="깨진안내", template_path=str(tpl)))
    coord = _coordinator(tmp_path, reg)
    assert coord.check("깨진안내", "k1") == {"ok": False, "reason": "initialization_required"}
    zone = coord.zone("깨진안내", "txt", False)
    assert zone["checkable"] is False and zone["diagnostics"]  # 비활성 + 사유 병기
    tpl.write_text("고쳤습니다 {{공고명}}\n", encoding="utf-8")
    assert coord.zone("깨진안내", "txt", False)["checkable"] is True
    assert coord.check("깨진안내", "k2")["preparation"]["status"] == "no_change"


def test_txt_applied_work_survives_later_source_edits_with_a_loud_note(tmp_path):
    """적용 뒤 원본을 고쳐도 Work 는 안 움직이고, 그 사실을 시끄럽게 알린다(#681 F1 동형)."""
    reg, tpl = _seed_txt(tmp_path)
    coord = _coordinator(tmp_path, reg)
    coord.check("안내문", "k1")
    assert coord.source_drift("안내문") == SourceDrift(SOURCE_DRIFT_UNCHANGED, None)
    tpl.write_text("본문 {{공고명}}\n덧붙임 {{담당자}}\n", encoding="utf-8")
    token = coord.check("안내문", "k2")["preparation"]["change_token"]
    coord.apply("안내문", token)
    staged_before = coord.zone("안내문", "txt", False)["epoch"]

    tpl.write_text("적용 뒤 다시 고침 {{공고명}}\n", encoding="utf-8")
    assert coord.zone("안내문", "txt", False)["epoch"] == staged_before  # Work 무변경
    drift = coord.source_drift("안내문")
    assert drift.state == SOURCE_DRIFT_CHANGED
    assert drift.note and "캡처" in drift.note


# ─── 존 노출 술어(#932 B5) ─────────────────────────────────────────────────


def test_unbootstrapped_work_has_no_drift_judgment(tmp_path):
    """미부트스트랩은 「안 갈렸다」가 아니라 **판정 불성립**이다 — 대조할 캡처본이 없다."""
    reg, _tpl = _seed_txt(tmp_path)
    coord = _coordinator(tmp_path, reg)
    assert coord.source_drift("안내문") is NO_SOURCE_DRIFT_JUDGMENT


def test_zone_stands_down_once_the_source_is_unchanged(tmp_path):
    """U4 12번의 실제 요구 — 준비를 마쳤고 원본 그대로면 존은 자기 발로 내려온다."""
    reg, _tpl = _seed_txt(tmp_path)
    coord = _coordinator(tmp_path, reg)
    coord.check("안내문", "k1")
    zone = coord.zone("안내문", "txt", False)
    assert zone["preparation"]["status"] == "no_change"
    assert zone["source_drift"] == SOURCE_DRIFT_UNCHANGED
    assert zone["actionable"] is False


def test_zone_stands_when_the_source_was_edited(tmp_path):
    """확인을 **누르지 않아도** 존이 스스로 선다 — B5 가 요구한 「앱이 알아서 안다」."""
    reg, tpl = _seed_txt(tmp_path)
    coord = _coordinator(tmp_path, reg)
    coord.check("안내문", "k1")
    tpl.write_text("한글에서 고친 본문 {{공고명}}\n", encoding="utf-8")
    zone = coord.zone("안내문", "txt", False)
    assert zone["source_drift"] == SOURCE_DRIFT_CHANGED
    assert zone["actionable"] is True


def test_unreadable_source_is_unknown_and_still_stands(tmp_path):
    """「모른다」를 「없다」로 접지 않는다 — 읽지 못한 원본은 존을 세우고 사유를 든다."""
    reg, tpl = _seed_txt(tmp_path)
    coord = _coordinator(tmp_path, reg)
    coord.check("안내문", "k1")
    tpl.unlink()  # 원본이 사라져 값싸게 대조할 수 없다
    drift = coord.source_drift("안내문")
    assert drift.state == SOURCE_DRIFT_UNKNOWN
    assert drift.note  # 재진술 없는 침묵 금지
    assert coord.zone("안내문", "txt", False)["actionable"] is True


def test_zone_stands_while_a_prepared_change_waits(tmp_path):
    """``ready`` 는 종결이 아니다 — 적용이라는 미이행 동사가 남아 있으면 숨기지 않는다."""
    _reg, _tpl, coord, _token = _ready(tmp_path)
    zone = coord.zone("공고서", "hwpx", False)
    assert zone["preparation"]["status"] == "ready"
    assert zone["actionable"] is True


def test_every_zone_branch_carries_the_same_keys(tmp_path):
    """키 부재 분기 금지 — 표면이 ``"actionable" in z`` 로 갈리면 갈래 하나가 조용히 사라진다."""
    reg = JobRegistry(tmp_path / "jobs")
    tpl = tmp_path / "깨진.txt"
    tpl.write_bytes(b"\xff\xfe\x00\x00")
    reg.save(Job(name="깨진안내", template_path=str(tpl)))
    coord = _coordinator(tmp_path, reg)
    coord.check("깨진안내", "k1")  # bootstrap 실패 기록
    branches = [
        unsupported_zone(),
        coord.zone("깨진안내", "txt", False),          # initialization_required
        coord.zone("깨진안내", "없는매체", False),      # unsupported
    ]
    for zone in branches:
        assert {"actionable", "source_drift"} <= set(zone), zone


def test_initialization_failure_zone_still_stands(tmp_path):
    """비활성 + 사유 병기가 이 존의 몫이라, 숨기면 왜 안 도는지 물을 자리가 사라진다."""
    reg = JobRegistry(tmp_path / "jobs")
    tpl = tmp_path / "깨진.txt"
    tpl.write_bytes(b"\xff\xfe\x00\x00")
    reg.save(Job(name="깨진안내", template_path=str(tpl)))
    coord = _coordinator(tmp_path, reg)
    coord.check("깨진안내", "k1")
    zone = coord.zone("깨진안내", "txt", False)
    assert zone["reason"] == "initialization_required"
    assert zone["checkable"] is False and zone["actionable"] is True


def test_new_product_statuses_default_to_standing():
    """어휘가 늘면 기본은 **세움**이다 — 등록을 잊은 status 가 구획을 조용히 지우지 않는다."""
    settled = {"no_change", "applied", "invalid", "rejected"}
    for status in PRODUCT_PREPARATION_STATUSES:
        actionable = template_change_zone_actionable(
            supported=True, reason="", preparation_status=status,
            source_drift=SOURCE_DRIFT_UNCHANGED,
        )
        assert actionable is (status not in settled), status


def test_unsupported_media_never_stands():
    """capability 밖은 술어 이전의 문제다 — drift 가 무엇이든 존은 없다."""
    for drift in (SOURCE_DRIFT_CHANGED, SOURCE_DRIFT_UNKNOWN, None):
        assert template_change_zone_actionable(
            supported=False, reason="unsupported_media",
            preparation_status=None, source_drift=drift,
        ) is False


# ─── 자동 준비(#932 B5) ────────────────────────────────────────────────────


def test_ensure_bootstrapped_seats_authority_once(tmp_path):
    """선택이 준비를 진다 — 「변경사항 확인」을 누르지 않아도 권위가 서고, 두 번 서지 않는다."""
    reg, _tpl = _seed_txt(tmp_path)
    coord = _coordinator(tmp_path, reg)
    assert not load_job(reg, "안내문").authority_id

    first = coord.ensure_bootstrapped("안내문")
    assert first["ok"] is True and first["bootstrapped"] is True
    assert load_job(reg, "안내문").authority_id  # 구간·실행면이 설 수 있는 상태

    again = coord.ensure_bootstrapped("안내문")
    assert again["ok"] is True and again["bootstrapped"] is False  # 작업당 1회


def test_ensure_bootstrapped_does_not_retry_a_recorded_failure(tmp_path, monkeypatch):
    """자동 경로가 매 선택마다 실패하는 capture 를 되돌리지 않는다 — 사유는 존이 든다."""
    reg = JobRegistry(tmp_path / "jobs")
    tpl = tmp_path / "깨진.txt"
    tpl.write_bytes(b"\xff\xfe\x00\x00")
    reg.save(Job(name="깨진안내", template_path=str(tpl)))
    coord = _coordinator(tmp_path, reg)

    assert coord.ensure_bootstrapped("깨진안내") == {
        "ok": False, "bootstrapped": False, "reason": "initialization_required",
    }
    calls = []
    original = coord._bootstrap
    monkeypatch.setattr(
        coord, "_bootstrap",
        lambda *a, **k: (calls.append(1), original(*a, **k))[1],
    )
    assert coord.ensure_bootstrapped("깨진안내")["ok"] is False
    assert calls == []  # 같은 실물이면 되돌지 않는다
    assert coord.zone("깨진안내", "txt", False)["actionable"] is True  # 사유는 선다

    tpl.write_text("고쳤습니다 {{공고명}}\n", encoding="utf-8")
    assert coord.ensure_bootstrapped("깨진안내")["bootstrapped"] is True  # 수리하면 열린다


def test_ensure_bootstrapped_is_inert_without_a_template(tmp_path):
    """템플릿 실물이 없으면 준비할 것이 없다 — 복구 동사는 라이브러리 재연결이다."""
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="빈작업", template_path=str(tmp_path / "없다.txt")))
    coord = _coordinator(tmp_path, reg)
    result = coord.ensure_bootstrapped("빈작업")
    assert result["ok"] is True and result["bootstrapped"] is False
    assert not load_job(reg, "빈작업").authority_id  # 좀비 권위를 만들지 않는다


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


@pytest.mark.parametrize(
    ("product_status", "expected"),
    [
        # 확인이 결론 없이 끝난 여섯 — 다시 확인하면 지워진다.
        ("error", REVIEW_REQUIRED),
        ("interrupted", REVIEW_REQUIRED),
        ("conflict", REVIEW_REQUIRED),
        ("source_changed", REVIEW_REQUIRED),
        ("changed_while_checking", REVIEW_REQUIRED),
        ("superseded", REVIEW_REQUIRED),
        # 결론이 있는 것들 — 확인을 다시 시켜도 지워지지 않으므로 확인 요구로 세우지 않는다.
        ("ready", None),  # 해소 동사는 **적용**이다(확인 요구로 세우면 막다른 길).
        ("no_change", None),
        ("applied", None),
        ("invalid", None),
        ("rejected", None),
        ("checking", None),  # 진행 중 — 사용자 조치가 아니다.
        (None, None),  # 확인한 적 없음 — 대조할 변경이 없다.
    ],
)
def test_workbench_template_change_verdict_table(product_status, expected):
    """제품 status → 작업대 verdict(#912 D2). 기준은 「확인이 이 상태를 지우는가」 하나다."""
    assert workbench_template_change_verdict(product_status) == expected


def test_workbench_verdict_covers_every_product_status():
    """어휘가 늘면 이 판정도 함께 늘어야 한다 — 조용한 기본값으로 새 status 를 삼키지 않는다."""
    for status in PRODUCT_PREPARATION_STATUSES:
        assert workbench_template_change_verdict(status) in (REVIEW_REQUIRED, None)


@pytest.mark.parametrize(
    ("drift", "expected"),
    [
        (SOURCE_DRIFT_CHANGED, REVIEW_REQUIRED),   # 원본이 갈렸다 — 캡처본으로 조용히 밀지 않는다
        (SOURCE_DRIFT_UNKNOWN, REVIEW_REQUIRED),   # 모른다 — 모르는 채 미는 것이 곧 조용한 추측
        (SOURCE_DRIFT_UNCHANGED, None),
        (None, None),                              # 판정 불성립(미부트스트랩)
    ],
)
def test_source_drift_raises_the_same_review_requirement(drift, expected):
    """드리프트도 확인 요구를 세운다(#932 B5).

    존이 조치가 있을 때만 서게 된 뒤로 「원본을 고쳤는데 그 사실을 못 본 채 생성」할 창이
    생겼다 — 생성은 캡처된 bytes 를 쓰므로(#681 F1) 그 창이 곧 조용한 오생성이다. 막되
    좌초시키지 않는다: 복구 동사(`#jobTplCheck`)는 같은 판정이 세우는 존 안에 있다.
    """
    assert workbench_template_change_verdict(None, drift) == expected


def test_unsettled_status_stands_regardless_of_drift():
    """두 축은 독립이다 — 드리프트가 없어도 미종결 확인은 그대로 요구를 세운다."""
    assert workbench_template_change_verdict("error", SOURCE_DRIFT_UNCHANGED) == REVIEW_REQUIRED


def test_view_drops_change_token_unless_ready():
    view = preparation_view(
        _prep("READY"), CHANGE_APPLIED,
        preparation_token="pt", change_token="ct",
    )
    assert view["status"] == "applied" and view["change_token"] is None
