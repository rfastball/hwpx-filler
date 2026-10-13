"""Job 저장소의 공개 동시 변이 경계 — 기존 작업 화면 준비 helper를 재사용한다."""
from __future__ import annotations

import threading

import pytest

from hwpxfiller.external.hwpx_engine import make_hwpx_engine
from hwpxfiller.external.template_inspection import template_compile_status
from test_webapp_job import _controller, _write_template


class _CheckedThread(threading.Thread):
    error: BaseException | None = None

    def run(self):
        try:
            super().run()
        except BaseException as exc:  # noqa: BLE001 — 본 스레드에서 원래 실패를 다시 올린다.
            self.error = exc


def _pause_stamp(monkeypatch):
    """스탬프 저장을 잠금 안에서 한 번 멈춰 세우는 장치 — (진입 이벤트, 해제 이벤트)."""
    import hwpxfiller.external.job_store as job_store

    entered, release = threading.Event(), threading.Event()
    real_save = job_store.save_job
    fired = {"once": False}

    def slow_save(path, job, **kwargs):
        if not fired["once"] and job.last_run_at:    # 스탬프 저장만 붙잡는다
            fired["once"] = True
            entered.set()
            assert release.wait(timeout=30), "스탬프 저장 대기가 해제되지 않았습니다."
        return real_save(path, job, **kwargs)

    monkeypatch.setattr(job_store, "save_job", slow_save)
    return entered, release


def _finish_stamp_threads(release, *threads):
    release.set()
    for thread in threads:
        thread.join(timeout=30)
    alive = [thread.name for thread in threads if thread.is_alive()]
    assert not alive, f"스레드가 종료되지 않았습니다: {alive}"
    for thread in threads:
        if thread.error is not None:
            raise thread.error


def _await_stamp_entry(entered, release, stamper):
    if entered.wait(timeout=30):
        return
    _finish_stamp_threads(release, stamper)
    pytest.fail("스탬프 저장이 대기 지점에 도달하지 못했습니다.")


def _home_vm(registry):
    from hwpxfiller.viewmodel.home_state import HomeViewModel

    return HomeViewModel(
        registry, None, None,
        engine=make_hwpx_engine(), inspect_status=template_compile_status,
    )


def test_public_delete_during_stamp_does_not_resurrect_the_job(tmp_path, monkeypatch):
    """삭제 도중 스탬프가 끼어도 지운 작업이 되살아나지 않는다(리뷰 3R P1).

    잠금 밖 삭제라면: ①스탬프가 A 를 읽고 ②삭제가 파일을 지우고 성공을 반환하고 ③스탬프가
    사본을 저장해 **A 가 부활**한다. "지웠다"고 말한 뒤 되살아나는 것은 조용한 소실의 거울상이다.
    """
    ctrl, _ = _controller(tmp_path)
    reg = ctrl.registry
    vm = _home_vm(reg)
    entered, release = _pause_stamp(monkeypatch)

    stamper = _CheckedThread(target=lambda: reg.stamp_last_run("공고서", "2026-07-21T09:00:00"))
    stamper.start()
    _await_stamp_entry(entered, release, stamper)

    done = threading.Event()

    def delete_job():
        vm.delete("공고서")      # 홈 카드 「삭제」가 타는 실제 경로
        done.set()

    deleter = _CheckedThread(target=delete_job)
    deleter.start()
    try:
        assert not done.wait(0.2), "삭제가 스탬프의 임계구역 안으로 끼어들었습니다."
    finally:
        _finish_stamp_threads(release, stamper, deleter)
    assert not reg.exists("공고서"), "지운 작업이 스탬프 저장으로 되살아났습니다."


def test_public_set_tags_during_stamp_keeps_both_changes(tmp_path, monkeypatch):
    """태그 편집과 스탬프가 겹쳐도 둘 다 남는다 — 늦은 저장이 상대를 되돌리지 않는다."""
    ctrl, _ = _controller(tmp_path)
    reg = ctrl.registry
    vm = _home_vm(reg)
    entered, release = _pause_stamp(monkeypatch)

    stamper = _CheckedThread(target=lambda: reg.stamp_last_run("공고서", "2026-07-21T09:00:00"))
    stamper.start()
    _await_stamp_entry(entered, release, stamper)
    tagger = _CheckedThread(target=lambda: vm.set_tags("공고서", {"부서": "계약"}))
    tagger.start()
    _finish_stamp_threads(release, stamper, tagger)

    saved = reg.load("공고서")
    assert saved.last_run_at == "2026-07-21T09:00:00"   # 태그 저장이 시각을 지우지 않았다
    assert saved.tags == {"부서": "계약"}                # 스탬프가 태그를 되돌리지 않았다


def test_public_relink_during_stamp_keeps_both_changes(tmp_path, monkeypatch):
    """템플릿 재연결과 스탬프가 겹쳐도 둘 다 남는다(확인 왕복이 있어 창이 특히 넓은 경로)."""
    from hwpxfiller.webapp.screens import relink_job_template

    ctrl, _ = _controller(tmp_path)
    reg = ctrl.registry
    new_template = tmp_path / "새서식.hwpx"
    _write_template(new_template, ["공고명", "추정가격"])
    entered, release = _pause_stamp(monkeypatch)

    stamper = _CheckedThread(target=lambda: reg.stamp_last_run("공고서", "2026-07-21T09:00:00"))
    stamper.start()
    _await_stamp_entry(entered, release, stamper)
    linker = _CheckedThread(
        target=lambda: relink_job_template(
            reg, "공고서", str(new_template), engine=make_hwpx_engine(), confirm=True
        )
    )
    linker.start()
    _finish_stamp_threads(release, stamper, linker)

    saved = reg.load("공고서")
    assert saved.last_run_at == "2026-07-21T09:00:00"
    assert saved.template_path == str(new_template)


