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

from _output_folder_pick import pick_output_folder
from tests.test_webapp_job import (
    _data_csv,
    _mount_all,
    _template_change_controller,
    _unreviewed_session,
)

from hwpxcore.package import MIMETYPE_NAME, MIMETYPE_VALUE, HwpxPackage
from hwpxfiller.application.prepare_orchestration import APPLY_INTEGRITY_ERROR, ApplyOutcome
from hwpxfiller.application.template_change_product import (
    PRODUCT_PREPARATION_STATUSES,
    TemplateChangeProjectionError,
    preparation_view,
    product_preparation_status,
    template_change_zone_actionable,
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
from hwpxfiller.domain.mapping import FieldMapping
from hwpxfiller.external.hwpx_package_io import write_hwpx_package
from hwpxfiller.external.job_store import JobRegistry
from hwpxfiller.external import template_change as tc
from hwpxfiller.external.template_change import (
    SUPPORTED_MEDIA,
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
    tpl = Path(load_job(reg, "공고서").template_path)
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
    tpl = Path(load_job(reg, "공고서").template_path)
    tpl.write_bytes(b"broken bytes")  # 앱 편집본 손상
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
    tpl = Path(load_job(reg, "안내문").template_path)
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
    tpl = Path(load_job(reg, "안내문").template_path)
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
    tpl = Path(load_job(reg, "안내문").template_path)
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


def test_applied_txt_uses_its_owned_copy_after_original_changes(tmp_path):
    reg, original = _seed_txt(tmp_path)
    coord = _coordinator(tmp_path, reg)
    assert coord.check("안내문", "k1")["preparation"]["status"] == "no_change"
    applied = Path(load_job(reg, "안내문").template_path)
    assert applied != original
    assert applied.name == original.name
    before = applied.read_bytes()

    original.write_text("외부 원본 수정 {{공고명}}", encoding="utf-8")
    assert coord.check("안내문", "k2")["preparation"]["status"] == "no_change"
    original.unlink()
    assert coord.zone("안내문", "txt", False)["actionable"] is False
    assert applied.read_bytes() == before


def test_applied_txt_edits_are_the_explicit_change_source(tmp_path):
    reg, _original = _seed_txt(tmp_path)
    coord = _coordinator(tmp_path, reg)
    coord.check("안내문", "k1")
    applied = Path(load_job(reg, "안내문").template_path)
    applied.write_text("앱 편집본 {{공고명}}\n추가 {{담당자}}", encoding="utf-8")
    coord = _coordinator(tmp_path, reg)  # 다시 열어도 미적용 편집분을 덮어쓰지 않는다.
    prepared = coord.check("안내문", "k2")["preparation"]
    assert prepared["status"] == "ready"
    assert coord.zone("안내문", "txt", False)["actionable"] is True
    assert coord.apply("안내문", prepared["change_token"])["status"] == "applied"
    assert applied.read_text(encoding="utf-8").startswith("앱 편집본")


def test_existing_work_migrates_from_applied_blob_without_old_file(tmp_path):
    reg, original = _seed_txt(tmp_path)
    coord = _coordinator(tmp_path, reg)
    coord.check("안내문", "k1")
    applied = Path(load_job(reg, "안내문").template_path)
    expected = applied.read_bytes()
    reg.relink_template("안내문", str(original))
    applied.unlink()
    original.unlink()

    reopened = _coordinator(tmp_path, reg)
    assert Path(load_job(reg, "안내문").template_path).read_bytes() == expected
    assert reopened.check("안내문", "k2")["preparation"]["status"] == "no_change"


def test_failed_applied_copy_retires_old_link_without_blocking_other_work(tmp_path, monkeypatch):
    reg, original = _seed_txt(tmp_path)
    healthy_source = tmp_path / "정상.txt"
    healthy_source.write_text("정상 {{공고명}}", encoding="utf-8")
    reg.save(Job(name="정상", template_path=str(healthy_source)))
    coord = _coordinator(tmp_path, reg)
    coord.check("안내문", "bad-k1")
    coord.check("정상", "good-k1")
    broken_asset = Path(load_job(reg, "안내문").template_path)
    healthy_asset = Path(load_job(reg, "정상").template_path)
    expected = healthy_asset.read_bytes()
    reg.relink_template("안내문", str(original))
    reg.relink_template("정상", str(healthy_source))
    broken_asset.unlink()
    healthy_asset.unlink()
    original.write_text("외부에서 바뀐 원본", encoding="utf-8")
    healthy_source.unlink()

    write_blob = tc.AppliedTemplateAsset._write_blob

    def fail_one(self, path, exact):
        if path == broken_asset:
            raise OSError("copy failed")
        write_blob(self, path, exact)

    monkeypatch.setattr(tc.AppliedTemplateAsset, "_write_blob", fail_one)
    reopened = _coordinator(tmp_path, reg)
    assert Path(load_job(reg, "안내문").template_path) == broken_asset
    assert not broken_asset.exists()
    assert original.read_text(encoding="utf-8") == "외부에서 바뀐 원본"
    assert healthy_asset.read_bytes() == expected
    with pytest.raises(FileNotFoundError):
        reopened.ensure_bootstrapped("안내문")


def test_zone_shows_only_pending_applied_work(tmp_path):
    reg, _original = _seed_txt(tmp_path)
    coord = _coordinator(tmp_path, reg)
    coord.check("안내문", "k1")
    assert coord.zone("안내문", "txt", False)["actionable"] is False
    assert "source_drift" not in coord.zone("안내문", "txt", False)


def test_template_change_zone_actionable_uses_preparation_status():
    for status in PRODUCT_PREPARATION_STATUSES:
        actionable = template_change_zone_actionable(
            supported=True, reason="", preparation_status=status,
        )
        assert actionable is (status not in {"no_change", "applied", "invalid", "rejected"})


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


def test_view_drops_change_token_unless_ready():
    view = preparation_view(
        _prep("READY"), CHANGE_APPLIED,
        preparation_token="pt", change_token="ct",
    )
    assert view["status"] == "applied" and view["change_token"] is None


# ─── 낮은 층위 branch — 권한·port 계약·진단 조회의 방어적 갈래 ─────────────────────────
def test_apply_with_a_non_local_actor_is_refused(tmp_path):
    """단일 사용자 데스크톱 — token 과 별개로 actor 를 매 요청 재확인한다."""
    _reg, _tpl, coord, token = _ready(tmp_path)
    with pytest.raises(TemplateChangeError):
        coord.apply("공고서", token, actor="다른사용자")
    # 거절은 상태를 바꾸지 않는다 — 같은 token 이 정상 actor 로는 그대로 적용된다.
    assert coord.apply("공고서", token)["status"] == "applied"


def test_work_state_read_port_returns_none_for_a_missing_aggregate(tmp_path):
    """#674 read Port 계약 — 없는 Work 는 예외가 아니라 None."""
    from hwpxfiller.external.work_template_store import AtomicWorkTemplateStateStore

    store = AtomicWorkTemplateStateStore(tmp_path / "works")
    from hwpxfiller.external.applied_template_asset import _WorkStateReadPort

    port = _WorkStateReadPort(store)
    assert port.load("missing-work-id") is None


def test_diagnostics_drop_a_missing_evidence_record_silently(tmp_path):
    """Preparation 이 가리키는 Evidence 가 store 에 없으면(회수·손상) 진단은 원본 사유만 남긴다."""
    import dataclasses

    reg, _tpl, coord, _token = _ready(tmp_path)
    work_id = reg.load("공고서").authority_id
    aggregate = coord._works.load(work_id)
    prep = aggregate.preparations[-1]
    tampered = dataclasses.replace(prep, evidence_id="missing-evidence-id")

    found = coord._diagnostics(tampered)

    assert found == tuple((str(d.get("reason", "")), "") for d in prep.diagnostics)


def test_current_preparation_view_is_none_before_any_preparation_exists(tmp_path):
    """current_template_preparation_id 가 없으면(예: 갓 만든 상태) 조회는 None."""
    import dataclasses

    reg, _tpl, coord, _token = _ready(tmp_path)
    work_id = reg.load("공고서").authority_id
    aggregate = coord._works.load(work_id)
    blank = dataclasses.replace(
        aggregate, work=dataclasses.replace(aggregate.work, current_template_preparation_id=None)
    )

    assert coord._current_preparation_view(blank, work_id) is None


def test_bootstrap_failure_diagnostics_tolerate_a_missing_evidence_record(tmp_path, monkeypatch):
    """bootstrap 실패 진단 조회도 같은 관용을 진다 — evidence 부재는 원본 사유만 남긴다."""
    from hwpxfiller.external.qualification_store import ObjectNotFound

    reg = JobRegistry(tmp_path / "jobs")
    tpl = tmp_path / "깨진.hwpx"
    tpl.write_bytes(b"not a zip")
    reg.save(Job(name="깨진작업", template_path=str(tpl)))
    coord = _coordinator(tmp_path, reg)

    def raise_not_found(*_a, **_k):
        raise ObjectNotFound("evidence 없음")

    monkeypatch.setattr(coord._quals, "get_evidence", raise_not_found)
    result = coord.check("깨진작업", "k1")
    assert result == {"ok": False, "reason": "initialization_required"}
    zone = coord.zone("깨진작업", "hwpx", False)
    assert zone["checkable"] is False and zone["diagnostics"]


def test_seating_refuses_when_authority_cannot_be_reconfirmed(tmp_path, monkeypatch):
    """방어적 갈래 — 방금 좌석한 권위가 재조회에서 다른 값으로 보이면 loud 하게 닫는다.

    정상 흐름에서는 나지 않는 경합 화해 실패라 ``seat_job_authority_id`` seam 하나만 주입해
    직접 잰다.
    """
    reg, _tpl = _seed(tmp_path)
    coord = _coordinator(tmp_path, reg)
    monkeypatch.setattr(tc, "seat_job_authority_id", lambda *_a, **_k: ("bogus-work-id", True))

    with pytest.raises(TemplateChangeError):
        coord.check("공고서", "k1")


def test_bootstrap_failure_does_not_release_authority_it_did_not_issue(tmp_path, monkeypatch):
    """방어적 갈래 — 이번 호출이 발급하지 않은 권위(``issued_now=False``)는 실패해도 돌려주지
    않는다. 정상 흐름은 이 권위를 이번 호출이 늘 발급하므로(초기 등록 실패는 즉시 롤백) 실물
    구성이 아니라 ``seat_job_authority_id`` 반환값 seam 하나만 흉내낸다.
    """
    tpl = tmp_path / "깨진.hwpx"
    tpl.write_bytes(b"not a zip")
    reg = JobRegistry(tmp_path / "jobs")
    reg.save(Job(name="깨진작업", template_path=str(tpl)))
    reg.assign_authority_id("깨진작업", "w-preexisting")
    coord = _coordinator(tmp_path, reg)

    monkeypatch.setattr(
        tc, "seat_job_authority_id", lambda *_a, **_k: ("w-preexisting", False)
    )
    released = []
    monkeypatch.setattr(
        tc,
        "release_job_authority_id",
        lambda *a, **k: released.append((a, k)) or reg.load("깨진작업"),
    )

    result = coord.check("깨진작업", "k1")
    assert result == {"ok": False, "reason": "initialization_required"}
    assert released == []  # issued_now=False — 이 호출은 발급하지 않았으니 돌려주지 않는다
    assert reg.load("깨진작업").authority_id == "w-preexisting"  # 좀비 롤백 대상이 아니다


def test_a_rule_change_no_longer_refuses_the_run(tmp_path):
    """규칙이 바뀌어도 실행은 열린다 — 고지가 그 사실을 말할 뿐이다(#957)."""
    ctrl, _ = _unreviewed_session(tmp_path)
    job = ctrl.registry.load("공고서")
    job.filename_pattern = "다른-{{seq:001}}"
    job.mapping.mappings[0] = FieldMapping(
        template_field="공고명", type="const", const="수정된 공고명",
    )
    ctrl.registry.save(job, allow_overwrite=True)
    ctrl.on_editor_mapping_saved("공고서")
    ctrl.dispatch("refresh", {})
    snap = ctrl.snapshot()
    assert snap["review"]["required"] is True           # 요구는 서고
    assert snap["template_change"]["actionable"] is False
    assert snap["gate"]["enabled"] is True              # 게이트는 열려 있다
    assert ctrl.generate()["ok"] is True


@pytest.mark.parametrize("adds_field", [False, True])
def test_template_apply_only_requires_missing_field_bindings(tmp_path, adds_field):
    """적용 후 재확인 없이 실행하며, 실제로 늘어난 필드의 미연결만 막는다."""
    ctrl, _ = _template_change_controller(tmp_path, managed=True)
    ctrl.dispatch("select_job", {"name": "공고서"})
    _mount_all(ctrl, _data_csv(tmp_path))
    out = tmp_path / "out"
    pick_output_folder(ctrl, out)
    ready = ctrl.refresh_panel()
    assert ready["managed_hwpx"] is True
    assert ready["workbench_observation"]["create_action"]["enabled"] is True

    template = Path(ctrl.registry.load("공고서").template_path)
    if adds_field:
        _write_template(template, ["공고명", "추정가격", "담당자"])
    else:
        template.write_bytes(template.read_bytes() + b"SAME-FIELDS-EDIT")
    preparation = ctrl.dispatch("template_check", {"request_id": "k2"})["preparation"]
    assert preparation["status"] == "ready"
    applied = ctrl.dispatch("template_apply", {"change_token": preparation["change_token"]})
    assert applied["status"] == "applied"

    if not adds_field:
        assert ctrl.snapshot()["template_change"]["actionable"] is False
        assert ctrl.snapshot()["gate"]["enabled"] is True
        assert ctrl.generate()["ok"] is True
        return

    blocked = ctrl.refresh_panel()
    assert blocked["workbench_observation"]["create_action"]["enabled"] is False
    assert "검증 완료. 생성할 수 있습니다." not in blocked["preflight"]["text"]
    refused = ctrl.generate()
    assert refused["ok"] is False, refused
    assert not list(out.glob("*.hwpx"))

    # 새 판본에 대한 연결 확정(편집기 저장과 같은 사건)이 생성을 다시 연다.
    ctrl.registry.mutate(
        "공고서",
        lambda job: job.mapping.mappings.append(
            FieldMapping(template_field="담당자", type="const", const="홍길동")
        ),
    )
    ctrl.on_editor_mapping_saved("공고서")
    reopened = ctrl.refresh_panel()
    assert reopened["workbench_observation"]["create_action"]["enabled"] is True
    made = ctrl.generate()
    assert made["ok"] is True and made["status"] == "completed", made
    assert len(list(out.glob("*.hwpx"))) == 2
