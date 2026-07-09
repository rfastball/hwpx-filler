"""백그라운드 일괄 생성 워커 — QThread 에 태워 UI 블로킹을 막는다.

집행 화면(run_view)이 쓴다. 생성 로직은 :func:`batch.generate_batch` 에 위임하고
(파일명·연번·충돌 처리 단일화), 레코드 단위 진행률만 시그널로 중계한다.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class GenerateWorker(QObject):
    """백그라운드 일괄 생성 워커 (UI 블로킹 방지)."""

    progress = Signal(int, int)  # done, total
    finished = Signal(object)    # BatchResult
    failed = Signal(str)

    def __init__(self, template, records, out_dir, pattern):
        super().__init__()
        self.template = template
        self.records = records
        self.out_dir = out_dir
        self.pattern = pattern

    def run(self):
        try:
            from ..batch import generate_batch

            batch = generate_batch(
                self.template,
                self.records,
                self.out_dir,
                self.pattern,
                progress=self.progress.emit,
            )
            self.finished.emit(batch)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
