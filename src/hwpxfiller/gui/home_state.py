"""홈 화면 ViewModel — Qt 비의존 프레젠테이션 상태(작업 목록·메타 성형·선택).

위젯(:class:`~hwpxfiller.gui.home.JobListHome`)은 이 뷰모델을 들고 ``rows()``·``is_empty()``·
``count_label()`` 로 **렌더만** 한다. 레지스트리 접근, 카드 메타 문자열, 최근집행 포맷, 선택
상태가 여기 산다 — 변경 통지는 Qt 시그널이 아니라 순수 옵저버 콜백(``subscribe``)이라
QApplication 없이 헤드리스로 테스트된다(링1 규율: PySide6 임포트 금지).

이 뷰모델의 공개 표면(``JobRow`` 필드 + 메서드)이 목업(``docs/UI_PROTOTYPE_APPB.html`` 홈)이
겨누는 seam 계약이다.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from ..core.job import Job, JobRegistry


def _fmt_iso(ts: str) -> str:
    """ISO-8601 → 'YYYY-MM-DD HH:MM' (파싱 실패 시 원문)."""
    try:
        return datetime.fromisoformat(ts).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts


@dataclass
class JobRow:
    """카드 1건이 렌더할 성형된 데이터 — 위젯은 이 필드만 읽는다(Job 을 직접 안 만진다)."""

    name: str
    template_name: str
    template_missing: bool
    field_count: int
    filename_pattern: str
    last_run_display: str

    @classmethod
    def from_job(cls, job: Job) -> "JobRow":
        tpath = job.template_path
        return cls(
            name=job.name,
            template_name=(Path(tpath).name or "—") if tpath else "—",
            # 집행 화면의 템플릿 가드를 홈에서 선고지(비차단).
            template_missing=bool(tpath) and not Path(tpath).exists(),
            field_count=len(job.mapping.mappings),
            filename_pattern=job.filename_pattern,
            last_run_display=(
                f"최근 집행 {_fmt_iso(job.last_run_at)}" if job.last_run_at else "아직 집행 안 함"
            ),
        )

    def meta_line(self) -> str:
        return (
            f"템플릿 {self.template_name} · 필드 {self.field_count}개 · "
            f"파일명 {self.filename_pattern}"
        )


class HomeViewModel:
    """작업 목록 상태 + 레지스트리 어댑터. 위젯은 구독해서 렌더한다."""

    def __init__(self, registry: JobRegistry):
        self.registry = registry
        self._rows: "list[JobRow]" = []
        self._selected: "str | None" = None
        self._subs: "list" = []
        self.refresh()

    # ---------------------------------------------------------- 변경 통지
    def subscribe(self, cb) -> None:
        """상태 변경 시 호출될 콜백 등록(위젯의 렌더 메서드)."""
        self._subs.append(cb)

    def _notify(self) -> None:
        for cb in self._subs:
            cb()

    # ---------------------------------------------------------- 데이터
    def refresh(self) -> None:
        """레지스트리에서 다시 읽어 행을 성형하고 통지(선택은 살아있으면 보존)."""
        self._rows = [JobRow.from_job(j) for j in self.registry.list_jobs()]
        if self._selected not in {r.name for r in self._rows}:
            self._selected = None
        self._notify()

    def rows(self) -> "list[JobRow]":
        return list(self._rows)

    def is_empty(self) -> bool:
        return not self._rows

    def count_label(self) -> str:
        return f"{len(self._rows)}건" if self._rows else ""

    # ---------------------------------------------------------- 선택
    @property
    def selected_name(self) -> "str | None":
        return self._selected

    def select(self, name: "str | None") -> None:
        """선택 갱신 — 값싸므로 재렌더 통지는 하지 않는다(위젯이 버튼만 동기화)."""
        self._selected = name if name in {r.name for r in self._rows} else None

    def has_selection(self) -> bool:
        return self._selected is not None

    def delete(self, name: str) -> None:
        """작업 삭제 후 목록 갱신(확인 UI 는 위젯/컨트롤러 몫)."""
        self.registry.delete(name)
        if self._selected == name:
            self._selected = None
        self.refresh()
