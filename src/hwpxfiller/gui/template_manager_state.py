"""템플릿 관리 워크숍 ViewModel — Qt 비의존(링1). 특정 Job 밖의 템플릿 라이브러리 관리면.

위젯(:class:`~hwpxfiller.gui.template_manager.TemplateManagerPanel`)은 이 뷰모델을 들고
``rows()``·``actions_for(state)``·``scan_preview(path)``·``apply_fieldize(path)``·
``lint(path, vocabulary=None)``·``drift(old,new)`` 로 **렌더·오케스트레이션만** 한다. 상태 판정(compile_status)·상태별
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

from hwpxcore.package import HwpxPackage

from ..core.authoring import TokenSite, compile_document, scan_tokens
from ..core.fields import fill_precheck, read_fields
from ..core.lint import LintReport, SchemaDrift, diff_schema, lint_template
from ..core.template_status import (
    OUTPUT_SUBDIR_NAME,
    CompileState,
    TemplateStatus,
    compile_status,
)

# 상태 → 배지 (라벨, 레벨)은 :mod:`compile_badge` 가 단일 출처 — 홈 카드 배지와
# 같은 상태에 같은 심각도 신호를 낸다(RC-29, 이중화 금지).
from .compile_badge import badge_label as _badge_label
from .compile_badge import badge_level as _badge_level
from .result_errors import describe_precheck_note

# lint 심각도 → 사용자 대면 한국어(뷰가 영문 원시값을 노출하지 않게 링1이 성형).
_SEVERITY_KO: "dict[str, str]" = {"warning": "경고", "info": "정보", "error": "오류"}


class ResultLine(str):
    """결과 문구 + 심각도 레벨(UD-07) — 성과별 시각 위계의 단일 seam.

    lint 경고·실패 잔존 문구가 화면 최저 위계의 muted 회색으로 고정 렌더되던 결함을
    푼다. ``str`` 하위형이라 기존 문자열 계약(``"파일명" in result`` 포함검사·
    ``setText(result)``)을 그대로 지키면서, 위젯이 ``.level`` 을 style.mark 레벨
    (``"warn"``/``"danger"``/``"ok"``/``"muted"``)로 마킹한다 — 심각도 판정은 링1 소유.
    """

    level: str

    def __new__(cls, text: str, level: str = "muted") -> "ResultLine":
        obj = super().__new__(cls, text)
        obj.level = level
        return obj


@dataclass(frozen=True)
class TemplateAction:
    """상태 게이트가 허용하는 액션 하나 — ``key`` 는 안정 식별자, ``label`` 은 버튼 문구.

    ``label`` 이 상태 의존적인 경우가 있다(RAW 의 '누름틀 변환' vs PARTIAL 의 '마저 변환')
    — 같은 ``key``('compile')라도 문맥에 맞는 문구를 담는다.
    """

    key: str
    label: str


# 상태 → 허용 액션(순수 함수의 단일 출처). C5 수용기준 1이 이 표를 못박는다.
#   RAW      → [누름틀 변환]
#   PARTIAL  → [마저 변환] [검토]
#   COMPILED → [미리보기] [작업 만들기]
#   FILLED   → [미리보기]
_STATE_ACTIONS: "dict[CompileState, tuple[TemplateAction, ...]]" = {
    CompileState.RAW: (TemplateAction("compile", "누름틀 변환"),),
    CompileState.PARTIAL: (
        TemplateAction("compile", "마저 변환"),
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
        return f"변환 가능 {len(self.compilable)}개 · 건너뜀 {len(self.skipped)}개"


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
    # 채움 완화 사전 고지(#154) — "채우면 무슨 일이 생기는가"의 점검 문안.
    fill_warns: "tuple[str, ...]" = ()

    @property
    def is_error(self) -> bool:
        return bool(self.error)

    def detail_line(self) -> str:
        """스킵/잔존 상세를 담은 한 줄 메타(위생 신호)."""
        if self.is_error:
            return f"읽기 실패: {self.error}"
        # 카드 메타 수량은 분류사 '개'로 통일(UD-34) — '미컴파일'은 '미변환'으로(UD-18).
        parts = [f"필드 {self.field_count}개"]
        if self.compilable_n:
            parts.append(f"미변환 {self.compilable_n}개")
        if self.skipped_n:
            parts.append(f"수동 {self.skipped_n}개")
        if self.stray_n:
            parts.append(f"잔존 {self.stray_n}개")
        return " · ".join(parts)

    def actions(self) -> "list[TemplateAction]":
        return available_actions(self.state)

    @classmethod
    def from_status(
        cls,
        path: Path,
        status: TemplateStatus,
        fill_warns: "tuple[str, ...]" = (),
    ) -> "TemplateRow":
        return cls(
            name=path.name,
            path=str(path),
            state=status.state,
            badge_label=_badge_label(status.state),
            badge_level=_badge_level(status.state),
            field_count=status.field_n,
            compilable_n=status.compilable_n,
            skipped_n=status.skipped_n,
            stray_n=status.stray_n,
            fill_warns=fill_warns,
        )

    @classmethod
    def from_error(cls, path: Path, message: str) -> "TemplateRow":
        return cls(
            name=path.name,
            path=str(path),
            state=None,
            badge_label=_badge_label(None),
            badge_level=_badge_level(None),
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
        """라이브러리 파일 목록 — 명시 경로 우선, 아니면 디렉터리의 *.hwpx를 **재귀**로(이름순).

        비재귀 ``glob`` 은 탐색기로 하위폴더에 떨군 서식을 조용히 누락했다(R-info 2부 결정 5,
        confirm-or-alarm 위반) — ``rglob`` 으로 반드시 찾아 평평하게 올린다(하위폴더 = 조직이
        아니라 관용된 등장지). 하위폴더 동명은 경로로 안정 타이브레이크(둘 다 별개 행). 디렉터리가
        패턴에 걸려도(예: ``x.hwpx/``) 파일만 취해 오탐을 막는다.

        **산출물 하위폴더 제외**(#136 리뷰 F2): 작업 실행 기본 저장 폴더가 ``템플릿/Results`` 라
        라이브러리 루트 밑에 완성 문서가 쌓인다. 그 하위트리를 템플릿으로 재수집하면 실행할수록
        라이브러리가 산출물로 오염되므로 ``Results`` 경로 성분이 있는 파일은 건너뛴다."""
        if self._explicit_paths is not None:
            return list(self._explicit_paths)
        if self.library_dir is not None and self.library_dir.is_dir():
            return sorted(
                (
                    p
                    for p in self.library_dir.rglob("*.hwpx")
                    if p.is_file()
                    and OUTPUT_SUBDIR_NAME not in p.relative_to(self.library_dir).parts
                ),
                key=lambda p: (p.name, str(p)),
            )
        return []

    def set_library_dir(self, library_dir: "str | Path") -> None:
        """라이브러리 폴더 재지정(사용자 폴더 선택) — 명시 경로 주입은 해제하고 재스캔."""
        self.library_dir = Path(library_dir)
        self._explicit_paths = None
        self.refresh()

    def empty_hint(self) -> str:
        """빈 목록의 원인 안내 — '폴더 없음'과 '빈 폴더'를 구분한다(RC-14 침묵 백지 방지)."""
        if self._explicit_paths is not None:
            return "표시할 템플릿이 없습니다."
        if self.library_dir is None:
            return "템플릿 폴더가 지정되지 않았습니다.\n[폴더 선택]으로 라이브러리 폴더를 지정하세요."
        if not self.library_dir.is_dir():
            return f"템플릿 폴더가 없습니다: {self.library_dir}\n[폴더 선택]으로 다시 지정하세요."
        return f"폴더에 .hwpx 템플릿이 없습니다: {self.library_dir}"

    def refresh(self) -> None:
        """라이브러리를 다시 스캔해 행을 성형하고 통지(compile_status 매번 재산출)."""
        rows: "list[TemplateRow]" = []
        for path in self._discover():
            try:
                # 패키지를 한 번만 열어 상태·사전 판정이 같은 스냅샷을 본다 —
                # 경로 재열기는 I/O 2배 + 두 열기 사이 파일 교체 시 멀쩡한 행이
                # from_error 로 강등되는 TOCTOU 를 만든다(2라운드 리뷰 F5).
                pkg = HwpxPackage.open(str(path))
                status = compile_status(pkg)
                # 채움 완화 사전 판정(#154) — 점검 표면의 "사전에 알고" 쪽.
                warns = tuple(
                    describe_precheck_note(n) for n in fill_precheck(pkg)
                )
            except Exception as exc:  # noqa: BLE001 — 읽기 실패는 시끄럽게 노출(감추지 않음)
                rows.append(TemplateRow.from_error(path, str(exc)))
                continue
            rows.append(TemplateRow.from_status(path, status, fill_warns=warns))
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
    def lint(self, path: str, vocabulary=None) -> LintReport:
        """단일 템플릿 위생 점검(유사 필드명·미치환 토큰·어휘). 읽기 전용.

        ``vocabulary`` 는 코어 :func:`~hwpxfiller.core.lint.lint_template` 의 통제 어휘
        그대로 전달한다(RC-14 시그니처 정렬 — CLI ``--vocab`` 과 위생 점검 범위 동등).
        """
        return lint_template(str(path), vocabulary=vocabulary)

    def drift(self, old_path: str, new_path: str) -> SchemaDrift:
        """두 판본의 필드셋 드리프트(추가/삭제/개명 추정). 읽기 전용."""
        return diff_schema(str(old_path), str(new_path))

    # ------------------------------------------------------ 결과 문구 성형(링1)
    # 단일 결과 라벨이 lint/미리보기/드리프트/컴파일을 무맥락으로 덮어쓰던 것을(RC-14)
    # 대상 템플릿명을 포함한 성형으로 고정한다 — 뷰(위젯)가 아니라 여기 살아야
    # 헤드리스로 테스트되고 '얇은 렌더러' 계약이 지켜진다.
    def format_compile_result(self, path: str, report) -> ResultLine:
        """apply_fieldize 리포트 → 결과 문구(대상 템플릿명 포함) — 성공은 ok(UD-07)."""
        return ResultLine(
            f"누름틀 변환 완료 {Path(path).name}: 필드 {len(report.compiled)}개 추가", "ok"
        )

    def format_scan_empty_result(self, path: str, preview: "ScanPreview") -> ResultLine:
        """컴파일 스캔 결과 '변환 가능 토큰 없음' → 인라인 결과 문구(UD-24).

        같은 화면 다른 결과 4종과 대칭으로 lbl_result 에 싣는다(차단 모달 강등 —
        ADR-E: 모달은 파괴 확정에만). 진행 불가 통지이므로 warn 레벨.
        """
        name = Path(path).name
        text = f"누름틀 변환 {name}: 변환 가능한 토큰이 없습니다"
        if preview.skipped:
            names = ", ".join(s.name for s in preview.skipped)
            text += f" (건너뜀 {len(preview.skipped)}개: {names})"
        return ResultLine(text, "warn")

    def format_lint_result(self, path: str, report: LintReport) -> ResultLine:
        """lint 리포트 → 결과 문구(심각도 한국어·대상 템플릿명 포함).

        경고가 남으면 warn, 오류 심각도면 danger, 이슈 없으면 ok(UD-07) — VM 이 이미
        아는 심각도를 시각 채널로 파생한다.
        """
        name = Path(path).name
        if not report.findings:
            return ResultLine(f"검토 {name}: 이슈 없음.", "ok")
        severities = {f.severity for f in report.findings}
        level = "danger" if "error" in severities else "warn"
        lines = [f"검토 결과 {name}:"]
        lines.extend(
            f"[{_SEVERITY_KO.get(f.severity, f.severity)}] {f.message}"
            for f in report.findings
        )
        return ResultLine("\n".join(lines), level)

    def format_preview_result(self, path: str, values: "dict[str, str]") -> ResultLine:
        """FILLED 값 미리보기 → 결과 문구(대상 템플릿명 포함) — 정보성이므로 muted.

        빈 값 필드는 '필드명 = ' 뒤 무표시 공백으로 렌더돼 의도적 공란과 채우다 만 것을
        구별할 수 없었다(UD-26 F5) — 빈 값을 '(비움)' 으로 명시 재진술한다(ADR-B).
        """
        name = Path(path).name
        if not values:
            return ResultLine(f"미리보기 {name}: 누름틀 값이 없습니다.", "muted")
        return ResultLine(
            f"미리보기 {name}:\n"
            + "\n".join(f"{k} = {v if str(v).strip() else '(비움)'}" for k, v in values.items()),
            "muted",
        )

    def format_drift_result(
        self, old_path: str, new_path: str, drift: SchemaDrift
    ) -> ResultLine:
        """드리프트 결과 → 결과 문구(비교 판본 쌍 명시) — 변화 있으면 warn, 없으면 ok."""
        pair = f"{Path(old_path).name} → {Path(new_path).name}"
        if not drift.has_changes:
            return ResultLine(f"드리프트 {pair}: 필드셋 변화 없음.", "ok")
        parts = [f"드리프트 {pair}:"]
        for n in drift.added:
            parts.append(f"+ 추가: {n}")
        for n in drift.removed:
            parts.append(f"- 삭제: {n}")
        for r in drift.renamed:
            parts.append(f"~ 개명(추정): {r['old']} → {r['new']} ({r['score']})")
        return ResultLine("\n".join(parts), "warn")

    # ----------------------------------------------------- FILLED 값 미리보기
    def filled_values(self, path: str) -> "dict[str, str]":
        """FILLED(또는 임의) 템플릿의 현재 누름틀 값 — C1 read_fields 위임."""
        return read_fields(str(path))
