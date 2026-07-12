"""홈 화면 ViewModel — Qt 비의존 프레젠테이션 상태(작업 목록·메타 성형·선택).

위젯(:class:`~hwpxfiller.gui.home.JobListHome`)은 이 뷰모델을 들고 ``rows()``·``is_empty()``·
``count_label()`` 로 **렌더만** 한다. 레지스트리 접근, 카드 메타 문자열, 최근실행 포맷, 선택
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
from ..core.template_status import CompileState, compile_status

# 카드 컴파일 상태 배지 어휘(C2 파생) — 기존 '템플릿 없음' pill 을 대체가 아니라 확장한다.
# 이모지 접두로 한눈에 "실행 준비 vs 손봐야 함" 을 가른다.
BADGE_MISSING = "❌ 템플릿 없음"        # 경로 있으나 파일 부재(compile_status 호출 안 함)
BADGE_RAW = "✏ 원문·컴파일 필요"       # CompileState.RAW(진짜 필드 없음, 평문 토큰)
BADGE_READY = "✅ 실행 준비"           # COMPILED/FILLED(잔존 토큰 0)
BADGE_ERROR = "⚠ 템플릿 오류"          # 손상 템플릿 — 조용한 ✅ 금지, 시끄럽게 알림


def _partial_badge(n: int) -> str:
    """PARTIAL 배지 — N = 미확인(잔존) 토큰 수."""
    return f"⚠ 미확인 토큰 {n}개"


def _derive_compile(tpath: str, template_missing: bool) -> "tuple[CompileState | None, str]":
    """(compile_state, compile_badge) 를 C2 ``compile_status`` 에서 파생한다.

    비용 주의: 템플릿이 존재하면 매 refresh 마다 .hwpx 를 파싱해 상태를 **재계산**한다
    (한글 재편집으로 COMPILED→PARTIAL 드리프트가 나므로 저장·캐시하지 않는다 — C2 의
    compute-not-store 원칙). 손상 템플릿이 홈 목록을 죽이지 않도록 예외를 가드하되,
    조용히 ✅ 로 통과시키지 않고 시끄럽게 오류 배지로 강등한다.
    """
    if not tpath:
        return None, ""                       # 템플릿 경로 없음 → 배지 없음(부재 아님)
    if template_missing:
        return None, BADGE_MISSING            # 부재 경로엔 compile_status 를 부르지 않는다
    try:
        st = compile_status(tpath)
    except Exception:
        return None, BADGE_ERROR              # 손상/파싱 실패 → 시끄럽게 강등(never silent ✅)
    if st.state == CompileState.RAW:
        return st.state, BADGE_RAW
    if st.state == CompileState.PARTIAL:
        # N = 미확인(잔존) 토큰 총합: skip 채널 + 본문 stray + 미컴파일(compilable).
        n = st.skipped_n + st.stray_n + st.compilable_n
        return st.state, _partial_badge(n)
    return st.state, BADGE_READY              # COMPILED 또는 FILLED(잔존 토큰 0)


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
    last_run_at: str = ""  # 원시 ISO(KPI '최근 실행' 계산용, ""=미실행)
    # C2 파생 컴파일 상태(seam) — refresh 마다 재계산(저장·캐시 없음). None = 배지 없음/부재/오류.
    compile_state: "CompileState | None" = None
    compile_badge: str = ""

    @classmethod
    def from_job(cls, job: Job) -> "JobRow":
        tpath = job.template_path
        # 실행 화면의 템플릿 가드를 홈에서 선고지(비차단).
        template_missing = bool(tpath) and not Path(tpath).exists()
        compile_state, compile_badge = _derive_compile(tpath, template_missing)
        return cls(
            name=job.name,
            template_name=(Path(tpath).name or "—") if tpath else "—",
            template_missing=template_missing,
            field_count=len(job.mapping.mappings),
            filename_pattern=job.filename_pattern,
            last_run_display=(
                f"최근 실행 {_fmt_iso(job.last_run_at)}" if job.last_run_at else "아직 실행 안 함"
            ),
            last_run_at=job.last_run_at,
            compile_state=compile_state,
            compile_badge=compile_badge,
        )

    def meta_line(self) -> str:
        return (
            f"템플릿 {self.template_name} · 필드 {self.field_count}개 · "
            f"파일명 {self.filename_pattern}"
        )


@dataclass
class TxtRow:
    """txt 기안 템플릿 1건(대시보드 txt 트랙 목록)."""

    name: str
    field_count: int


@dataclass
class DashboardKpi:
    """대시보드 요약 — 전부 실재 데이터(레지스트리·실행 이력·템플릿 상태·txt 루트)."""

    job_count: int
    recent_run: str            # "MM-DD · 작업명" 또는 "—"
    missing_template_count: int
    txt_template_count: int


class HomeViewModel:
    """작업 목록 상태 + 레지스트리 어댑터. 위젯은 구독해서 렌더한다."""

    def __init__(self, registry: JobRegistry, text_registry=None):
        self.registry = registry
        self.text_registry = text_registry  # TextTemplateRegistry | None (txt 트랙)
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

    # ---------------------------------------------------------- 대시보드
    def kpi(self) -> DashboardKpi:
        """대시보드 KPI — 실재 데이터만(가짜 지표 없음)."""
        runs = [r for r in self._rows if r.last_run_at]
        if runs:
            latest = max(runs, key=lambda r: r.last_run_at)
            recent = f"{_fmt_iso(latest.last_run_at)[5:10]} · {latest.name}"
        else:
            recent = "—"
        return DashboardKpi(
            job_count=len(self._rows),
            recent_run=recent,
            missing_template_count=sum(1 for r in self._rows if r.template_missing),
            txt_template_count=self.text_registry.count() if self.text_registry else 0,
        )

    def txt_rows(self) -> "list[TxtRow]":
        """txt 기안 템플릿 목록(정해진 루트). 레지스트리 없으면 빈 목록."""
        if self.text_registry is None:
            return []
        return [
            TxtRow(t.name, len(t.fields())) for t in self.text_registry.list_templates()
        ]

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
