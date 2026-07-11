"""GUI 진입점 — 작업(Job) 목록 홈을 기동하고 능력들을 라우팅한다.

    python -m hwpxfiller.gui.app

홈(:class:`~hwpxfiller.gui.home.JobListHome`)이 오케스트레이터다: 새 작업은 에디터
(:class:`~hwpxfiller.gui.job_editor.JobEditorWizard`)로, 집행은 집행 화면
(:class:`~hwpxfiller.gui.run_view.RunView`)으로 보낸다. 자식 창의 수명은 여기서 소유한다
(Qt GC 방지). 초기엔 자식 창 — 임베드(QStackedWidget)는 후속 리팩터.
"""

from __future__ import annotations

import sys


class _AppController:
    """홈 + 자식 창들의 배선·수명 소유자. QApplication 과 분리해 테스트 가능."""

    def __init__(self, registry):
        from .home import JobListHome

        self.registry = registry
        self.home = JobListHome(registry)
        self._children: "list[object]" = []  # Qt GC 방지 — 자식 창 참조 유지

        self.home.new_job_requested.connect(self._open_editor_new)
        self.home.edit_job_requested.connect(self._open_editor_edit)
        self.home.run_job_requested.connect(self._open_run)
        self.home.delete_job_requested.connect(self._delete_job)
        # txt 트랙 라우팅(트랙 이원성) — 템플릿 열기 / 새 기안.
        self.home.open_txt_requested.connect(self._open_txt)
        self.home.new_txt_requested.connect(lambda: self._open_txt(None))

    # ------------------------------------------------------------------ 라우팅
    def _open_editor_new(self) -> None:
        from .job_editor import JobEditorWizard

        wiz = JobEditorWizard(self.registry)
        wiz.job_saved.connect(lambda _name: self.home.refresh())
        self._track(wiz)
        wiz.show()

    def _open_editor_edit(self, name: str) -> None:
        from .job_editor import JobEditorWizard

        # 기존 작업 프리로드: 템플릿 자동 로드 + 매핑 프리시드 + 이름/패턴 프리필.
        # 이름을 바꿔 저장하면 구명 작업은 별개로 남는다(자동 삭제는 발명 — 삭제는 사용자 몫).
        wiz = JobEditorWizard(self.registry, initial_job=self.registry.load(name))
        wiz.job_saved.connect(lambda _name: self.home.refresh())
        self._track(wiz)
        wiz.show()

    def _open_run(self, name: str) -> None:
        from .run_view import RunView

        job = self.registry.load(name)
        view = RunView(job)
        # 성공 집행 → 작업 사용 메타(last_run_at) 갱신. RunView 는 레지스트리를 모른다
        # (뷰 계약 유지) — 시그널 수신자만 추가.
        view.run_finished.connect(lambda batch: self._record_run(name, batch))
        self._track(view)
        view.show()

    def _record_run(self, name: str, batch) -> None:
        from datetime import datetime

        if getattr(batch, "succeeded", 0) <= 0 or not self.registry.exists(name):
            return
        job = self.registry.load(name)
        job.last_run_at = datetime.now().isoformat(timespec="seconds")
        self.registry.save(job)
        self.home.refresh()

    def _open_txt(self, name: "str | None" = None) -> None:
        from .txt_view import TxtDraftView

        view = TxtDraftView(self.home.text_registry)
        if name:
            view.select_template(name)
        self._track(view)
        view.show()

    def _delete_job(self, name: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        if QMessageBox.question(
            self.home, "삭제", f"작업 '{name}' 을(를) 삭제할까요?"
        ) == QMessageBox.Yes:
            self.registry.delete(name)
            self.home.refresh()

    def _track(self, win) -> None:
        self._children.append(win)
        win.destroyed.connect(lambda *_: self._children.remove(win) if win in self._children else None)


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from ..core.job import JobRegistry, default_jobs_dir

    app = QApplication(sys.argv)
    controller = _AppController(JobRegistry(default_jobs_dir()))
    controller.home.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
