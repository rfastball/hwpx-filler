"""템플릿 관리 워크숍 ViewModel — Qt 비의존(링1). 특정 Job 밖의 템플릿 라이브러리 관리면.

위젯(:class:`~hwpxfiller.gui.template_manager.TemplateManagerPanel`)은 이 뷰모델을 들고
``rows()``·``actions_for(state)``·``scan_preview(path)``·``apply_fieldize(path)``·``lint(path)``·
``drift(old,new)`` 로 **렌더·오케스트레이션만** 한다. 상태 판정(compile_status)·상태별
게이트 액션·2단계 fieldize(스캔 미리보기→적용)·lint/drift 는 전부 여기 산다 — PySide6 임포트
없이 헤드리스로 테스트된다(홈의 home_state↔home 분리를 그대로 미러링).

**새 코어 없음.** 전부 기존 코어 재사용:
- ``core.template_status.compile_status`` — RAW/PARTIAL/COMPILED/FILLED 4-상태(호출마다 재산출).
- ``core.authoring.scan_tokens``/``compile_document`` — 읽기 전용 스캔 미리보기 → 명시적 적용.
- ``core.lint.lint_template``/``diff_schema`` — 위생 점검 + 판본 드리프트.
- ``core.fields.read_fields`` — FILLED 값 미리보기.

**설계 원칙**("묻고 확정하게 하라, 아니면 시끄럽게 알려라"):
- fieldize 는 CLI 와 동일하게 **dry-run 기본**(scan_preview 는 파일을 만지지 않는다) →
  명시적 적용(apply_fieldize)에서만 컴파일·저장한다.
- 읽을 수 없는 파일은 조용히 감추지 않고 ``error`` 를 담은 행으로 **시끄럽게** 노출한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..core.authoring import TokenSite, compile_document, scan_tokens
from ..core.fields import read_fields
from ..core.lint import LintReport, SchemaDrift, diff_schema, lint_template
from ..core.template_status import CompileState, TemplateStatus, compile_status

# 상태 → 사람이 읽는 배지 라벨(단일 출처).
_BADGE_LABELS: "dict[CompileState, str]" = {
    CompileState.RAW: "원문",
    CompileState.PARTIAL: "부분 컴파일",
    CompileState.COMPILED: "컴파일됨",
    CompileState.FILLED: "채워짐",
}

# 상태 → QSS 배지 레벨(style.py 의 QLabel[level=...] 팔레트와 통일).
_BADGE_LEVELS: "dict[CompileState, str]" = {
    CompileState.RAW: "muted",
    CompileState.PARTIAL: "warn",
    CompileState.COMPILED: "ok",
    CompileState.FILLED: "ok",
}


@dataclass(frozen=True)
class TemplateAction:
    """상태 게이트가 허용하는 액션 하나 — ``key`` 는 안정 식별자, ``label`` 은 버튼 문구.

    ``label`` 이 상태 의존적인 경우가 있다(RAW 의 '컴파일' vs PARTIAL 의 '마저 컴파일')
    — 같은 ``key``('compile')라도 문맥에 맞는 문구를 담는다.
    """

    key: str
    label: str


# 상태 → 허용 액션(순수 함수의 단일 출처). C5 수용기준 1이 이 표를 못박는다.
#   RAW      → [컴파일]
#   PARTIAL  → [마저 컴파일] [검토]
#   COMPILED → [미리보기] [작업 만들기]
#   FILLED   → [미리보기]
_STATE_ACTIONS: "dict[CompileState, tuple[TemplateAction, ...]]" = {
    CompileState.RAW: (TemplateAction("compile", "컴파일"),),
    CompileState.PARTIAL: (
        TemplateAction("compile", "마저 컴파일"),
        TemplateAction("review", "검토"),
    ),
    CompileState.COMPILED: (
        TemplateAction("preview", "미리보기"),
        TemplateAction("make_job", "작업 만들기"),
    ),
    CompileState.FILLED: (TemplateAction("preview", "미리보기"),),
}


def available_actions(state: "CompileState | None") -> "list[TemplateAction]":
    """상태별 게이트 액션 목록(순수). 알 수 없는/오류 상태는 액션 없음."""
    if state is None:
        return []
    return list(_STATE_ACTIONS.get(state, ()))


@dataclass
class ScanPreview:
    """fieldize dry-run 결과 — 무엇을 바꿀지 먼저 보여준다(파일 무변형).

    ``compilable`` 은 누름틀로 바꿀 수 있는 토큰 사이트, ``skipped`` 는 못 바꾸는 토큰
    (파편·복합 런)과 그 ``reason``. 위젯은 이걸 먼저 렌더하고, 사용자가 명시적으로
    적용을 누를 때만 :meth:`TemplateManagerViewModel.apply_fieldize` 가 실제 변환한다.
    """

    compilable: "list[TokenSite]" = field(default_factory=list)
    skipped: "list[TokenSite]" = field(default_factory=list)

    @property
    def has_compilable(self) -> bool:
        return bool(self.compilable)

    def summary(self) -> str:
        return f"컴파일 가능 {len(self.compilable)}개 · 건너뜀 {len(self.skipped)}개"


@dataclass
class TemplateRow:
    """라이브러리 템플릿 1건이 렌더할 성형 데이터 — 위젯은 이 필드만 읽는다.

    ``error`` 가 비어있지 않으면 읽기 실패 행(상태 없음·액션 없음) — 조용히 감추지 않고
    시끄럽게 노출한다.
    """

    name: str
    path: str
    state: "CompileState | None"
    badge_label: str
    badge_level: str
    field_count: int
    compilable_n: int
    skipped_n: int
    stray_n: int
    error: str = ""

    @property
    def is_error(self) -> bool:
        return bool(self.error)

    def detail_line(self) -> str:
        """스킵/잔존 상세를 담은 한 줄 메타(위생 신호)."""
        if self.is_error:
            return f"읽기 실패: {self.error}"
        parts = [f"필드 {self.field_count}개"]
        if self.compilable_n:
            parts.append(f"미컴파일 {self.compilable_n}")
        if self.skipped_n:
            parts.append(f"수동 {self.skipped_n}")
        if self.stray_n:
            parts.append(f"잔존 {self.stray_n}")
        return " · ".join(parts)

    def actions(self) -> "list[TemplateAction]":
        return available_actions(self.state)

    @classmethod
    def from_status(cls, path: Path, status: TemplateStatus) -> "TemplateRow":
        return cls(
            name=path.name,
            path=str(path),
            state=status.state,
            badge_label=_BADGE_LABELS.get(status.state, status.state.value),
            badge_level=_BADGE_LEVELS.get(status.state, "muted"),
            field_count=status.field_n,
            compilable_n=status.compilable_n,
            skipped_n=status.skipped_n,
            stray_n=status.stray_n,
        )

    @classmethod
    def from_error(cls, path: Path, message: str) -> "TemplateRow":
        return cls(
            name=path.name,
            path=str(path),
            state=None,
            badge_label="오류",
            badge_level="danger",
            field_count=0,
            compilable_n=0,
            skipped_n=0,
            stray_n=0,
            error=message,
        )


class TemplateManagerViewModel:
    """템플릿 라이브러리 상태 + 오케스트레이션. 위젯은 구독해 렌더한다(Qt 비의존).

    ``library_dir`` 하위 ``*.hwpx`` 를 라이브러리로 삼는다(또는 ``paths`` 로 명시 주입).
    행·배지·상태별 액션은 계산값(compile_status)이고, fieldize 는 2단계
    (scan_preview→apply_fieldize)로 명시적이다.
    """

    def __init__(self, library_dir: "str | Path | None" = None, paths=None):
        self.library_dir = Path(library_dir) if library_dir is not None else None
        self._explicit_paths = [Path(p) for p in paths] if paths is not None else None
        self._rows: "list[TemplateRow]" = []
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
    def _discover(self) -> "list[Path]":
        """라이브러리 파일 목록 — 명시 경로 우선, 아니면 디렉터리의 *.hwpx(이름순)."""
        if self._explicit_paths is not None:
            return list(self._explicit_paths)
        if self.library_dir is not None and self.library_dir.is_dir():
            return sorted(self.library_dir.glob("*.hwpx"), key=lambda p: p.name)
        return []

    def refresh(self) -> None:
        """라이브러리를 다시 스캔해 행을 성형하고 통지(compile_status 매번 재산출)."""
        rows: "list[TemplateRow]" = []
        for path in self._discover():
            try:
                status = compile_status(str(path))
            except Exception as exc:  # noqa: BLE001 — 읽기 실패는 시끄럽게 노출(감추지 않음)
                rows.append(TemplateRow.from_error(path, str(exc)))
                continue
            rows.append(TemplateRow.from_status(path, status))
        self._rows = rows
        self._notify()

    def rows(self) -> "list[TemplateRow]":
        return list(self._rows)

    def is_empty(self) -> bool:
        return not self._rows

    def count_label(self) -> str:
        return f"{len(self._rows)}건" if self._rows else ""

    def row_for(self, path: str) -> "TemplateRow | None":
        for r in self._rows:
            if r.path == path:
                return r
        return None

    # -------------------------------------------------- 상태별 게이트 액션
    def actions_for(self, state: "CompileState | None") -> "list[TemplateAction]":
        """상태별 허용 액션(순수 리졸버) — 수용기준 1이 이 표를 못박는다."""
        return available_actions(state)

    # ------------------------------------------------ fieldize 2단계(스캔→적용)
    def scan_preview(self, path: str) -> ScanPreview:
        """dry-run — 컴파일 가능/건너뜀 토큰을 미리 보여준다. **파일 무변형**(읽기 전용)."""
        sites = scan_tokens(str(path))
        return ScanPreview(
            compilable=[s for s in sites if s.compilable],
            skipped=[s for s in sites if not s.compilable],
        )

    def apply_fieldize(self, path: str):
        """명시적 적용 — 토큰을 누름틀로 컴파일하고 **같은 경로에 저장**, 행 갱신.

        저장 후 그 파일의 compile_status 는 진행한다(RAW/PARTIAL → COMPILED). 바뀐 게
        없으면(``modified=False``) 저장하지 않는다. 리포트를 반환한다.
        """
        pkg, report = compile_document(str(path))
        if report.modified:
            pkg.save(str(path))
            self.refresh()
        return report

    # ----------------------------------------------------------- lint/drift
    def lint(self, path: str) -> LintReport:
        """단일 템플릿 위생 점검(유사 필드명·미치환 토큰·어휘). 읽기 전용."""
        return lint_template(str(path))

    def drift(self, old_path: str, new_path: str) -> SchemaDrift:
        """두 판본의 필드셋 드리프트(추가/삭제/개명 추정). 읽기 전용."""
        return diff_schema(str(old_path), str(new_path))

    # ----------------------------------------------------- FILLED 값 미리보기
    def filled_values(self, path: str) -> "dict[str, str]":
        """FILLED(또는 임의) 템플릿의 현재 누름틀 값 — C1 read_fields 위임."""
        return read_fields(str(path))
