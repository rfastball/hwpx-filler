"""백그라운드 일괄 생성 워커 — QThread 에 태워 UI 블로킹을 막는다.

main_window 와 wizard 가 공유한다(main_window._Worker 에서 추출, 로직 동일).
generate_batch 와 동등한 루프에 레코드 단위 progress 시그널을 더한 형태.
"""

from __future__ import annotations

from pathlib import Path

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
            from ..batch import BatchResult
            from ..core.engine import HwpxEngine
            from ..naming import make_output_filename

            engine = HwpxEngine()
            out = Path(self.out_dir)
            out.mkdir(parents=True, exist_ok=True)

            batch = BatchResult(total=len(self.records))
            for i, rec in enumerate(self.records, 1):
                target = str(out / make_output_filename(self.pattern, rec))
                res = engine.generate(self.template, rec, target)
                batch.results.append(res)
                if res.ok:
                    batch.succeeded += 1
                self.progress.emit(i, batch.total)
            self.finished.emit(batch)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
