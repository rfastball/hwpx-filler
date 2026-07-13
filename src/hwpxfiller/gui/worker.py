"""백그라운드 워커 — QThread 에 태워 UI 블로킹을 막는다.

- :class:`GenerateWorker` / :class:`MatrixGenerateWorker`: 일괄 생성(레코드 단위 진행률·
  협조적 취소(RC-06)·원장 검증 꼬리(RC-07)).
- :class:`TaskWorker`: 나라 취득/연결시험/풀 복원 같은 "블로킹 호출 1개"의 범용
  백그라운드화(RC-12) — 생성 워커와 같은 시그널 계약(finished/failed).

생성 로직은 :mod:`hwpxfiller.batch` 에 위임한다(파일명·연번·충돌·드리프트 게이트 단일화).
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal


class GenerateWorker(QObject):
    """백그라운드 일괄 생성 워커 (UI 블로킹 방지).

    입력은 :class:`~hwpxfiller.gui.run_state.GenerationPlan` **스냅샷 하나**(RC-07) —
    실행 중 위젯/VM 이 어떻게 바뀌어도 생성·원장은 계획만 소비한다. ``plan.ledger``
    가 켜져 있으면 원장 검증(전 산출물 되읽기)·export 를 **워커 꼬리에서** 수행한다
    — 완료 순간 UI 스레드 동기 되읽기로 대배치가 무응답이 되지 않도록. 결과는
    :attr:`ledger_path` / :attr:`ledger_error` 로 남고 뷰가 finished 처리 때 표면화한다.
    """

    progress = Signal(int, int)  # done, total
    stage = Signal(str)          # 진행률 밖 단계 고지(예: '원장 검증 중')
    finished = Signal(object)    # BatchResult (cancelled 플래그 포함)
    failed = Signal(str)

    def __init__(self, plan):
        super().__init__()
        self.plan = plan
        # 협조적 취소(RC-06) — UI 스레드가 cancel() 로 세우는 스레드-세이프 플래그.
        self._cancel = threading.Event()
        self.ledger_path: "str | None" = None
        self.ledger_error: "str | None" = None

    def cancel(self) -> None:
        """취소 요청(스레드-세이프) — 생성 루프가 다음 레코드 경계에서 중단한다."""
        self._cancel.set()

    def run(self):
        try:
            from ..batch import generate_batch

            plan = self.plan
            batch = generate_batch(
                plan.template,
                list(plan.records),
                plan.out_dir,
                plan.pattern,
                progress=self.progress.emit,
                now=plan.now,  # 확인·계획과 같은 시각 — 하위-일 날짜 토큰 대상 일치(RC-02)
                overwrite=plan.overwrite,
                mapping=plan.mapping,
                cancelled=self._cancel.is_set,
            )
            if plan.ledger:
                # 증거 저장 실패는 생성 성공을 뒤엎지 않되 조용히 삼키지도 않는다 —
                # ledger_error 로 남겨 뷰가 시끄럽게 표면화한다.
                self.stage.emit("원장 검증 중 — 산출물 되읽기")
                try:
                    from .run_state import export_plan_ledger

                    self.ledger_path = export_plan_ledger(plan, batch)
                except Exception as exc:  # noqa: BLE001
                    self.ledger_error = str(exc)
            self.finished.emit(batch)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class MatrixGenerateWorker(QObject):
    """백그라운드 매트릭스 생성 워커 — M 작업 × 공유 데이터(N행).

    생성 로직은 :func:`batch.generate_matrix` 에 위임한다(작업별 하위폴더·교차 충돌 차단·
    빈값 표식 단일화). 진행률은 M×N 누적으로 중계한다. datasource 는 이미 겨눠진 상태로
    받는다(나라는 키 없는 스냅샷) — 워커는 키·저장소를 모른다. ``cancel()`` 은
    :class:`GenerateWorker` 와 동일한 협조적 취소(RC-06)다.
    """

    progress = Signal(int, int)  # done, grand_total
    finished = Signal(object)    # MatrixResult (cancelled 플래그 포함)
    failed = Signal(str)

    def __init__(self, jobs, datasource, indices, out_dir, *, overwrite=False, now=None):
        super().__init__()
        self.jobs = jobs
        self.datasource = datasource
        self.indices = indices
        self.out_dir = out_dir
        self.overwrite = overwrite  # GenerateWorker 와 동일 계약(RC-02)
        # 덮어쓰기 확인에 쓴 시각을 그대로 생성에 넘겨 하위-일 날짜 토큰 대상 일치(RC-02).
        self.now = now
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """취소 요청(스레드-세이프) — 작업·레코드 경계에서 중단한다."""
        self._cancel.set()

    def run(self):
        try:
            from ..batch import generate_matrix

            result = generate_matrix(
                self.jobs,
                self.datasource,
                self.indices,
                self.out_dir,
                progress=self.progress.emit,
                now=self.now,  # 확인과 같은 시각 — 하위-일 날짜 토큰 대상 일치(RC-02)
                overwrite=self.overwrite,
                cancelled=self._cancel.is_set,
            )
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class TaskWorker(QObject):
    """단일 블로킹 호출 워커(RC-12) — 동기 함수 1개를 QThread 에서 실행한다.

    나라장터 취득·연결시험·풀 복원처럼 '결과 1개 or 예외' 형태의 네트워크/IO 호출이
    UI 스레드를 동결시키지 않도록, 생성 워커와 같은 패턴으로 백그라운드화한다.
    함수는 UI 상태를 만지지 않는 순수 호출이어야 한다(결과 커밋은 뷰가 finished
    슬롯 — UI 스레드 — 에서 수행).
    """

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            self.finished.emit(self._fn())
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))
