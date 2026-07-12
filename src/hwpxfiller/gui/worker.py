"""백그라운드 일괄 생성 워커 — QThread 에 태워 UI 블로킹을 막는다.

실행 화면(run_view)이 쓴다. 생성 로직은 :func:`batch.generate_batch` 에 위임하고
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


class MatrixGenerateWorker(QObject):
    """백그라운드 매트릭스 생성 워커 — M 작업 × 공유 데이터(N행).

    생성 로직은 :func:`batch.generate_matrix` 에 위임한다(작업별 하위폴더·교차 충돌 차단·
    빈값 표식 단일화). 진행률은 M×N 누적으로 중계한다. datasource 는 이미 겨눠진 상태로
    받는다(나라는 키 없는 스냅샷) — 워커는 키·저장소를 모른다.
    """

    progress = Signal(int, int)  # done, grand_total
    finished = Signal(object)    # MatrixResult
    failed = Signal(str)

    def __init__(self, jobs, datasource, indices, out_dir):
        super().__init__()
        self.jobs = jobs
        self.datasource = datasource
        self.indices = indices
        self.out_dir = out_dir

    def run(self):
        try:
            from ..batch import generate_matrix

            result = generate_matrix(
                self.jobs,
                self.datasource,
                self.indices,
                self.out_dir,
                progress=self.progress.emit,
            )
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
