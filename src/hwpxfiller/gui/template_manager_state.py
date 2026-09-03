"""템플릿 관리 워크숍 ViewModel — Qt 비의존(링1). 특정 Job 밖의 템플릿 라이브러리 관리면.

웹 템플릿·에디터 컨트롤러가 이 뷰모델을 들고
``rows()``·``actions_for(state)``·``scan_preview(path)``·``apply_fieldize(path)``·
``convert_preview(path)``·``apply_convert(path)``·``slot_view(path)`` 와 Slot 관리 동사 셋·
``lint(path, vocabulary=None)``·``drift(old,new)`` 로 **렌더·오케스트레이션만** 한다. 상태 판정(compile_status)·상태별
게이트 액션·2단계 fieldize(스캔 미리보기→적용)·구간 표기 변환·Slot 목록 투영·lint/drift 는
전부 여기 산다 — PySide6 임포트 없이 창 없이 테스트된다.

**새 코어 없음.** 전부 기존 코어 재사용:
- ``domain.template_status.compile_status`` — RAW/PARTIAL/COMPILED/FILLED 4-상태(호출마다 재산출).
- ``domain.authoring.scan_tokens``/``compile_document`` — 읽기 전용 스캔 미리보기 → 명시적 적용.
- ``domain.lint.lint_template``/``diff_schema`` — 위생 점검 + 판본 드리프트.
- ``domain.fields.read_fields`` — FILLED 값 미리보기.

**설계 원칙**("묻고 확정하게 하라, 아니면 시끄럽게 알려라"):
- fieldize 는 CLI 와 동일하게 **dry-run 기본**(scan_preview 는 파일을 만지지 않는다) →
  명시적 적용(apply_fieldize)에서만 컴파일·저장한다.
- 읽을 수 없는 파일은 조용히 감추지 않고 ``error`` 를 담은 행으로 **시끄럽게** 노출한다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..application.template_qualification import TemplateDiagnostic
from ..domain.authoring import CompileReport, StructureScan, TokenSite
from ..domain.fields import FillNote
from ..domain.lint import LintReport, SchemaDrift
from ..domain.schema import infer_type
from ..domain.slot import Slot
from ..domain.template_status import (
    CompileState,
    TemplateStatus,
    is_excluded_subtree,
    library_display_name,
)

# 상태 → 배지 (라벨, 레벨)은 :mod:`compile_badge` 가 단일 출처 — 홈 카드 배지와
# 같은 상태에 같은 심각도 신호를 낸다(RC-29, 이중화 금지).
from .compile_badge import badge_label as _badge_label
from .compile_badge import badge_level as _badge_level
from .result_errors import describe_precheck_note

# lint 심각도 → 사용자 대면 한국어(뷰가 영문 원시값을 노출하지 않게 링1이 성형).
_SEVERITY_KO: "dict[str, str]" = {"warning": "경고", "info": "정보", "error": "오류"}


@dataclass(frozen=True)
class TemplateInspection:
    """한 번 연 템플릿 스냅샷에서 계산한 판독 결과."""

    status: TemplateStatus
    precheck_notes: "tuple[FillNote, ...]"
    fields: "tuple[str, ...]" = ()
    slots: "tuple[Slot, ...]" = ()
    diagnostics: "tuple[TemplateDiagnostic, ...]" = ()


TemplateInspectPort = Callable[[str], TemplateInspection]


@dataclass(frozen=True)
class TemplateFileOps:
    """템플릿 **경로** 를 받는 파일 효과 포트 묶음(P2-19R, #576).

    Domain 프리미티브(scan_tokens·compile_document·lint_template·diff_schema·
    read_fields)는 열린 package 전용이 되어, 경로 열기/저장은 ring 2 가 결속해 주입한
    이 포트가 진다(concrete = external/template_inspection.HWPX_TEMPLATE_OPS).
    """

    scan_tokens: "Callable[[str], list[TokenSite]]"
    compile_file: "Callable[[str], CompileReport]"   # 같은 경로에 컴파일·저장(변경 시만)
    lint: "Callable[..., LintReport]"                # (path, vocabulary=None)
    #: 판독 + lint 를 **파일 한 번 열기**로 함께 낸다(U6-E 리뷰 7). 「자세히…」 한 번이
    #: `inspect` 와 `lint` 를 각각 열면 라이브러리가 클수록 그 왕복이 두 배로 든다 —
    #: 무엇보다 **두 스냅샷**을 한 시트에 얹게 되어 그 사이의 변경이 갈린 사실로 선다.
    inspect_and_lint: "Callable[..., tuple[TemplateInspection, LintReport]]"
    diff: "Callable[[str, str], SchemaDrift]"
    read_fields: "Callable[[str], dict[str, str]]"
    # 구간 표기 축(S8-03 #834). 컴파일 리포트·Slot 동사의 concrete 는 External 이 소유하고
    # 링1 은 **형체만** 안다(``modified``·``slots``·``refusal`` 읽기) — 링1 이 External 타입을
    # 임포트하면 링 경계가 뒤집힌다. Slot 동사 셋은 변이 뒤 제품 Slot 목록을 돌려준다.
    scan_structure: "Callable[[str], StructureScan]"
    compile_structure_file: "Callable[[str], object]"
    rename_slot_label: "Callable[[str, str, str | None], tuple[Slot, ...]]"
    decompile_slot: "Callable[[str, str], tuple[Slot, ...]]"
    #: 문서 전체판 풀기(U4-E3 #939) — 반환은 **되돌린** 선언 목록이라 단건 동사 셋의
    #: 「변이 뒤 남은 Slot」과 뜻이 다르다. 링1 은 수치를 여기서 받지 않고
    #: 재투영(:meth:`TemplateManagerViewModel.slot_view`)으로 다시 읽는다.
    decompile_structure: "Callable[[str], tuple[Slot, ...]]"
    remove_slot: "Callable[[str, str], tuple[Slot, ...]]"


class ResultLine(str):
    """결과 문구 + 심각도 레벨(UD-07) — 성과별 시각 위계의 단일 seam.

    lint 경고·실패 잔존 문구가 화면 최저 위계의 muted 회색으로 고정 렌더되던 결함을
    푼다. ``str`` 하위형이라 기존 문자열 계약(``"파일명" in result`` 포함검사·
    ``setText(result)``)을 그대로 지키면서, 표현 계층이 ``.level`` 을 시각 레벨
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
#   RAW      → [누름틀·구간 변환]
#   PARTIAL  → [마저 변환]
#   COMPILED → (없음)
#   FILLED   → (없음)
#
# RAW 라벨은 S8-03 에서 「누름틀 변환」→「누름틀·구간 변환」이 됐다: 같은 한 동사가 필드
# 토큰과 **구간 표기**를 함께 변환하므로(:meth:`TemplateManagerViewModel.apply_convert`)
# 라벨이 누름틀만 말하면 구간 마커가 조용히 바뀐 것처럼 보인다. PARTIAL 의 「마저 변환」은
# 그대로다 — 같은 동사의 이어하기라 대상을 다시 열거하지 않는다(COPY_STYLE_GUIDE §2:
# 버튼은 명사구·동사구, 상태 문맥은 배지가 이미 말한다).
#
# **U6-B(#976) — `preview`·`make_job` 퇴역**: 둘 다 살아 있는 표면에 소비자가 0 이었다.
# `preview` 는 #13 결정(10F2FF98-B)으로 처음부터 노출되지 않았고, `make_job` 은 편집기
# 1단계 항목 선택이 이미 지는 동사라 두 소비 표면(tpl 채널·편집기 피커)이 각자 필터
# (`_HIDDEN_ACTIONS`·`_PICKER_HIDDEN_ACTIONS`)로 걷고 있었다 — 링2 두 곳이 링1 목록을
# 다시 판정하던 자리다. 필터를 지우고 목록 자체를 줄였다.
#
# **U6-E(#979) — `review` 도 이 표에서 걷혔다**: U6-B 이후 COMPILED·FILLED 의 동사가 0 이
# 되면서 **완전 변환된 템플릿의 구간 항목에 닿을 길이 사라졌는데**(개명·표기로 되돌리기·
# 삭제는 전부 검토가 세우는 목록 위에 산다), 그 구멍을 메우는 것은 상태 동사가 아니라
# **「자세히…」 하나**다. 그 항목이 `tpl/review` 왕복을 지고 항목 상세 시트를 연다 —
# 같은 왕복을 부르는 메뉴 항목을 둘 두면 사람이 「검토」와 「자세히…」의 차이를 물어야 한다.
# 그래서 이 표는 **수선 동사만** 든다: 상태가 허용하는 것은 변환뿐이고, 「자세히…」는 상태와
# 무관하게 웹이 모든 행에 덧붙인다(:func:`libRowMenuItems`).
#: 변환 동사의 라벨 — 표가 정본이고 여기 이름을 붙이는 이유는 **밖에서 지목**하는 자리가
#: 있기 때문이다(U6-E #979): 가져오기 채택의 RAW 거절 문안이 「무엇을 거쳐야 하는가」로 이
#: 동사를 지목한다. 리터럴로 다시 쓰면 라벨을 고치는 날 그 문장만 옛말을 계속 한다.
CONVERT_ACTION_LABEL = "누름틀·구간 변환"

_STATE_ACTIONS: "dict[CompileState, tuple[TemplateAction, ...]]" = {
    CompileState.RAW: (TemplateAction("compile", CONVERT_ACTION_LABEL),),
    CompileState.PARTIAL: (TemplateAction("compile", "마저 변환"),),
    CompileState.COMPILED: (),
    CompileState.FILLED: (),
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
    (파편·복합 런)과 그 ``reason``. 표현 계층은 이걸 먼저 렌더하고, 사용자가 명시적으로
    적용을 누를 때만 :meth:`TemplateManagerViewModel.apply_fieldize` 가 실제 변환한다.
    """

    compilable: "list[TokenSite]" = field(default_factory=list)
    skipped: "list[TokenSite]" = field(default_factory=list)

    @property
    def has_compilable(self) -> bool:
        return bool(self.compilable)

    def summary(self) -> str:
        return f"변환 가능 {len(self.compilable)}개 · 건너뜀 {len(self.skipped)}개"


@dataclass(frozen=True)
class ConvertPreview:
    """「누름틀·구간 변환」 dry-run — 필드 토큰 축과 구간 표기 축을 **한 판정**으로(S8-03).

    두 축을 따로 보여 주면 사용자가 「무엇이 바뀌는가」를 두 번 조립해야 하고, 표면이
    그 합을 다시 계산하면 같은 상태를 두 곳이 판정한다. 판정은 여기 하나다:

    - :attr:`blocked` — 표기 진단이 1건이라도 있으면 **변환 불가**다(부분 변환 경로 없음).
    - :attr:`has_convertible` — 바꿀 것이 하나라도 있는가(필드 토큰 또는 구간 선언).
    """

    tokens: ScanPreview
    slots: int = 0
    options: int = 0
    diagnostics: "tuple[str, ...]" = ()

    @property
    def blocked(self) -> bool:
        """표기 진단 존재 = 변환 불가(확인을 묻지 않고 사유를 재진술한다)."""
        return bool(self.diagnostics)

    @property
    def has_convertible(self) -> bool:
        return bool(self.tokens.compilable) or self.slots > 0

    def summary(self) -> str:
        """「항목 n · 선택 m · 누름틀 k」 — 확인 왕복의 수치 재진술(#822 D7)."""
        return (
            f"항목 {self.slots}개 · 선택 {self.options}개 "
            f"· 누름틀 {len(self.tokens.compilable)}개"
        )


@dataclass(frozen=True)
class ConvertResult:
    """「누름틀·구간 변환」 적용 결과 — 두 축의 성과와 **구조 거절**을 함께 진다.

    ``refusals`` 가 비어 있지 않으면 구간 컴파일이 거절됐다는 뜻이다. 필드 변환이 이미
    저장됐더라도 그 사실을 지우지 않는다(조용한 부분 성공 금지 — 결과 문구가 둘 다 말한다).

    ``errors`` 는 구간 단계가 **거절이 아니라 예외**로 끝난 경우다(S8-F2 · #853 F-3).
    거절과 가르는 이유는 조치가 다르기 때문이다: 거절은 사용자가 고칠 선언 문제이고,
    예외는 예상 밖 실패라 사유를 그대로 실어 보여야 한다.

    ``mutated`` 는 이 호출이 **파일 bytes 를 실제로 바꿨는가** 하나다. 재정산 통지의
    판정 축이 이 필드 하나로 통일된다(#853 F-3·F-4 — 같은 상태를 두 곳이 판정하지 않는다).
    """

    fields: int = 0
    slots: int = 0
    options: int = 0
    refusals: "tuple[str, ...]" = ()
    errors: "tuple[str, ...]" = ()
    mutated: bool = False

    @property
    def refused(self) -> bool:
        return bool(self.refusals)

    @property
    def failed(self) -> bool:
        return bool(self.errors)


@dataclass(frozen=True)
class SlotRow:
    """컴파일된 Slot 1건의 표시 투영 — **판정 없음**(Slot 객체를 그대로 편다)."""

    id: str
    label: str
    option_count: int
    options: "tuple[str, ...]"

    @classmethod
    def from_slot(cls, slot: Slot) -> "SlotRow":
        return cls(
            id=slot.id,
            label=slot.label or "",
            option_count=len(slot.options),
            options=tuple(option.label or option.id for option in slot.options),
        )


@dataclass(frozen=True)
class SlotView:
    """한 템플릿의 Slot 목록 + 판독 진단(검토 결과 영역이 그릴 원료)."""

    path: str
    name: str
    rows: "tuple[SlotRow, ...]" = ()
    diagnostics: "tuple[str, ...]" = ()

    def summary(self) -> str:
        if self.diagnostics:
            return f"구간 구조를 읽을 수 없습니다: {self.name}"
        if not self.rows:
            return f"구간 항목이 없습니다: {self.name}"
        options = sum(row.option_count for row in self.rows)
        return f"항목 {len(self.rows)}개 · 선택 {options}개"

    def to_dict(self) -> dict:
        """웹 스냅샷 성형 — 이 투영의 **모양은 하나**다(U4-E2 #939 · U6-E #979).

        읽는 표면은 하나로 모였다: 항목 상세 시트의 구간 항목 표(`tpl` 채널 `detail.slots`).
        종전에는 편집기가 지금 연 템플릿의 읽기 전용 요약(`template_slots`)을 따로 들었고,
        그 존은 U6-E 에서 시트로 흡수됐다 — 동사는 편집 세션이 아니라 **풀 항목(파일)** 을
        겨누고, 세션과 같은 파일일 때의 무효화는 변이 seam 이 진다. 그래도 성형은 계속
        여기 하나다: 같은 뜻의 스키마를 프런트가 둘 배우지 않는다.
        """
        return {
            "path": self.path,
            "name": self.name,
            "summary": self.summary(),
            "rows": [
                {
                    "id": row.id,
                    "label": row.label,
                    "option_count": row.option_count,
                    "options": list(row.options),
                }
                for row in self.rows
            ],
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True)
class FieldRow:
    """상세 시트 필드 표의 한 줄 — 이름과 **추정 유형** 하나(판정 없음).

    유형은 링0 :func:`~hwpxfiller.domain.schema.infer_type` 이 낸다 — 편집기 1단계 스키마
    표가 쓰던 것과 **같은 함수**다(U6-E #979). 표면이 이름에서 유형을 되유추하면 같은
    필드가 두 화면에서 다른 유형으로 불린다.
    """

    name: str
    type_hint: str

    @classmethod
    def of(cls, name: str) -> "FieldRow":
        return cls(name=name, type_hint=infer_type(name))


@dataclass(frozen=True)
class TemplateDetail:
    """풀 항목 하나의 **상세 투영** — 「자세히…」 시트가 그릴 원료 한 벌(U6-E #979).

    편집기 고르기 존 아래에 흩어져 있던 관리 표면(선택 chip·작성 출처·스키마 표·구간 항목
    밴드·구간 요약)이 이 하나로 모였다. 모을 때의 규율은 **재조립 금지**다: 상태·배지·
    동사 목록은 :class:`TemplateRow` 와 같은 출처(`compile_status` → `_STATE_ACTIONS`)이고,
    구간 항목은 :class:`SlotView` 그대로이며, 필드 유형은 링0 추정 그대로다. 이 클래스가
    새로 판정하는 것은 하나도 없다 — 한 파일을 한 번 열어 본 결과를 한 모양으로 편다.

    ``media`` 는 :class:`TemplateRow` 와 같은 축이다: TXT 는 변환 축이 없어 상태·구간 항목이
    아예 서지 않고 필드 목록과 판독 실패 사유만 든다.
    """

    path: str
    name: str
    media: str
    state: "CompileState | None"
    badge_label: str
    badge_level: str
    fields: "tuple[FieldRow, ...]" = ()
    actions: "tuple[TemplateAction, ...]" = ()
    diagnostics: "tuple[str, ...]" = ()
    slots: "SlotView | None" = None
    error: str = ""

    def field_summary(self) -> str:
        """필드 표 머리 한 줄 — 나열식 요약(구 ``schema_summary``)의 승계처.

        나열은 하지 않는다(#16 판정): 이름을 여섯 개까지 늘어놓던 문장은 바로 아래 표가
        전부 말하는 것을 절반만 되풀이했다. 남는 질문은 **몇 개인가** 하나다.
        """
        if self.error:
            return f"읽기 실패: {self.error}"
        if not self.fields:
            return "채울 필드가 없습니다."
        return f"필드 {len(self.fields)}개"

    def to_dict(self) -> dict:
        """웹 스냅샷 성형 — 구간 항목은 :meth:`SlotView.to_dict` 하나를 지난다.

        ``slots`` 에서 ``path``·``name``·``diagnostics`` 를 다시 싣지 않는다: 셋 다 이
        투영의 최상위가 이미 든 사실이고, 두 자리에 두면 한쪽만 갱신되는 날이 온다.
        """
        slots = None
        if self.slots is not None:
            projected = self.slots.to_dict()
            slots = {"summary": projected["summary"], "rows": projected["rows"]}
        return {
            "path": self.path,
            "name": self.name,
            "media": self.media,
            "state": self.state.value if self.state is not None else "",
            "badge_label": self.badge_label,
            "badge_level": self.badge_level,
            "field_count": len(self.fields),
            "field_summary": self.field_summary(),
            "fields": [
                {"name": row.name, "type_hint": row.type_hint} for row in self.fields
            ],
            # 시트의 동사 줄이 읽는 목록 — 행 ⋯ 메뉴와 **같은 값**이다(같은 상태 두 곳 판정
            # 금지). 웹은 이 목록에서 자기가 지금 서 있는 「자세히…」만 걷어 그린다.
            "actions": [{"key": a.key, "label": a.label} for a in self.actions],
            "diagnostics": list(self.diagnostics),
            "slots": slots,
            "error": self.error,
        }

    @classmethod
    def from_text(
        cls,
        path: Path,
        fields: "tuple[str, ...] | list[str]" = (),
        error: str = "",
        *,
        root: "Path | None" = None,
    ) -> "TemplateDetail":
        """TXT 템플릿 1건 — 상태·배지·구간 항목이 없는 매체(:meth:`TemplateRow.from_text` 동형).

        배지를 비우는 이유도 같다: 매체 표지는 표면의 pill 이 지고 이 항목은 말할 상태 축이
        없다(없는 상태를 지어내지 않는다).
        """
        return cls(
            path=str(path),
            name=library_display_name(root, path),
            media="txt",
            state=None,
            badge_label="",
            badge_level="muted",
            fields=tuple(FieldRow.of(name) for name in fields),
            error=error,
        )


@dataclass
class TemplateRow:
    """라이브러리 템플릿 1건이 렌더할 성형 데이터 — 표현 계층은 이 필드만 읽는다.

    ``error`` 가 비어있지 않으면 읽기 실패 행(상태 없음·액션 없음) — 조용히 감추지 않고
    시끄럽게 노출한다.

    ``media`` 는 **변환 축이 있는 매체인가**를 가른다(U6-B #976 리뷰 8): TXT 는 누름틀이
    없어 컴파일 상태 자체가 없고, 그래서 ``state=None`` 이 hwpx 에서는 「읽을 수 없다」인데
    TXT 에서는 정상이다. 두 밴드가 같은 성형 함수(:meth:`detail_line` ·
    :meth:`select_block_reason`)를 지나야 문안이 갈리지 않으므로, 갈리는 그 한 축만 여기서
    든다 — 링2 가 매체별로 문장을 다시 지으면 같은 사실이 두 어휘를 갖는다.
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
    # 아직 native Slot 으로 바뀌지 않고 본문에 남은 구간 표기 마커 수(S8-04). 상태는 이미
    # PARTIAL 로 서지만, 배지만으로는 「무엇이 남았는가」를 알 수 없어 메타 줄이 병기한다.
    structure_marker_n: int = 0
    error: str = ""
    # 채움 완화 사전 고지(#154) — "채우면 무슨 일이 생기는가"의 점검 문안.
    fill_warns: "tuple[str, ...]" = ()
    #: 매체 — ``"hwpx"``(변환 축 있음) / ``"txt"``(없음). 위 클래스 독스트링이 근거를 진다.
    media: str = "hwpx"

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
            parts.append(f"남은 토큰 {self.stray_n}개")
        if self.structure_marker_n:
            # 「구간 표기」는 UI_VOCABULARY 의 표기 어휘 그대로(마커·sigil 노출 금지).
            parts.append(f"구간 표기 {self.structure_marker_n}개")
        return " · ".join(parts)

    def actions(self) -> "list[TemplateAction]":
        return available_actions(self.state)

    def select_block_reason(self) -> str:
        """이 템플릿으로 작업을 시작할 수 **없으면** 사유, 있으면 ``""`` (U6-B #976).

        판정도 문안도 여기 한 곳이 낸다 — 표면이 ``state``·``badge_label`` 로 다시 판정하면
        같은 상태가 두 어휘를 갖는다(데이터 풀의 ``select_block_reason`` 과 같은 문법).

        **변환 전(RAW·PARTIAL)은 고를 수 없다**(U6 §2.3): 숨기지 않고 비활성 + 사유로
        세운다 — 숨기면 사람이 넣어 둔 파일이 이유 없이 사라진 것으로 보이고, 그 침묵이
        이 라운드가 고치는 결함류다. 수선 동사(「누름틀·구간 변환」)는 같은 행의 ⋮ 에 있다.
        """
        if self.is_error:
            return f"읽을 수 없어 고를 수 없습니다: {self.error}"
        if self.media == "txt":
            # 변환 축이 없는 매체 — 판독에 성공했으면 그대로 고를 수 있다(리뷰 8).
            return ""
        if self.state is None:
            return "상태를 확인할 수 없어 고를 수 없습니다."
        if self.state in (CompileState.RAW, CompileState.PARTIAL):
            return "누름틀·구간 변환을 해야 고를 수 있습니다."
        return ""

    @classmethod
    def from_status(
        cls,
        path: Path,
        status: TemplateStatus,
        fill_warns: "tuple[str, ...]" = (),
        *,
        root: "Path | None" = None,
    ) -> "TemplateRow":
        return cls(
            name=library_display_name(root, path),
            path=str(path),
            state=status.state,
            badge_label=_badge_label(status.state),
            badge_level=_badge_level(status.state),
            field_count=status.field_n,
            compilable_n=status.compilable_n,
            skipped_n=status.skipped_n,
            stray_n=status.stray_n,
            structure_marker_n=status.structure_marker_n,
            fill_warns=fill_warns,
        )

    @classmethod
    def from_text(
        cls,
        path: Path,
        field_count: int,
        error: str = "",
        *,
        root: "Path | None" = None,
    ) -> "TemplateRow":
        """TXT 템플릿 1건 — hwpx 행과 **같은 성형 함수**를 지나는 자리(U6-B #976 리뷰 8).

        종전에는 링2 가 「필드 n개」·「읽기 실패: …」·「읽을 수 없어 고를 수 없습니다: …」를
        각자 리터럴로 지었다. 그 세 문장이 곧 :meth:`detail_line` ·
        :meth:`select_block_reason` 의 재구현이라, 링1 문안을 고치면 TXT 밴드만 옛말을
        계속 하게 된다. 배지는 비운다 — 매체 표지는 표면의 pill 이 지고 이 행은 상태를
        말할 축이 없다(없는 상태를 지어내지 않는다).
        """
        return cls(
            name=library_display_name(root, path),
            path=str(path),
            state=None,
            badge_label="",
            badge_level="muted",
            field_count=field_count,
            compilable_n=0,
            skipped_n=0,
            stray_n=0,
            error=error,
            media="txt",
        )

    @classmethod
    def from_error(
        cls, path: Path, message: str, *, root: "Path | None" = None,
    ) -> "TemplateRow":
        return cls(
            name=library_display_name(root, path),
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
    """템플릿 라이브러리 상태 + 오케스트레이션. 웹 컨트롤러는 결과를 읽어 렌더한다(Qt 비의존).

    ``library_dir`` 하위 ``*.hwpx`` 를 라이브러리로 삼는다(또는 ``paths`` 로 명시 주입).
    행·배지·상태별 액션은 계산값(compile_status)이고, fieldize 는 2단계
    (scan_preview→apply_fieldize)로 명시적이다.
    """

    def __init__(
        self,
        library_dir: "str | Path | Callable[[], Path] | None" = None,
        paths=None,
        *,
        inspect_template: TemplateInspectPort,
        file_ops: TemplateFileOps,
    ):
        # 루트는 **콜러블일 수 있다**(U6-A #975) — 서식 폴더가 설정으로 바뀌는 값이 되면서
        # 생성 시점 Path 를 굳혀 들면 재지정 뒤에도 옛 폴더를 나열한다(선언≠실제).
        self._library_dir = library_dir
        self._explicit_paths = [Path(p) for p in paths] if paths is not None else None
        self._inspect_template = inspect_template
        # 경로 기반 파일 효과(스캔·컴파일 저장·lint·드리프트·값 읽기)의 결속 포트(P2-19R).
        self._file_ops = file_ops
        self._rows: "list[TemplateRow]" = []
        self._subs: "list" = []
        self.refresh()

    # ---------------------------------------------------------- 변경 통지
    def subscribe(self, cb) -> None:
        """상태 변경 시 호출될 표현 계층 콜백을 등록한다."""
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
        라이브러리가 산출물로 오염되므로 ``Results`` 경로 성분이 있는 파일은 건너뛴다.

        **휴지통 하위폴더 제외**(#267 리뷰): 앱은 더 이상 ``.trash`` 를 만들지 않지만(U6-A
        #975 — 삭제 동사 퇴역) 옛 홈에 이미 있는 하위트리를 제외하지 않으면 지웠던 템플릿이
        개명된 채 즉시 재수집된다."""
        if self._explicit_paths is not None:
            return list(self._explicit_paths)
        root = self.library_dir  # 스캔 한 번에 한 번 읽는다(도중에 갈리지 않게)
        if root is not None and root.is_dir():
            return sorted(
                (
                    p
                    for p in root.rglob("*.hwpx")
                    if p.is_file()
                    and not is_excluded_subtree(p.relative_to(root).parts)
                ),
                key=lambda p: (p.name, str(p)),
            )
        return []

    @property
    def library_dir(self) -> "Path | None":
        """지금의 라이브러리 루트 — 콜러블 주입이면 **매번 평가**한다(사본 캐시 금지)."""
        source = self._library_dir
        if source is None:
            return None
        return Path(source() if callable(source) else source)

    def set_library_dir(self, library_dir: "str | Path | Callable[[], Path]") -> None:
        """라이브러리 폴더 재지정(사용자 폴더 선택) — 명시 경로 주입은 해제하고 재스캔."""
        self._library_dir = library_dir
        self._explicit_paths = None
        self.refresh()

    def empty_hint(self) -> str:
        """빈 목록의 원인 안내 — '폴더 없음'과 '빈 폴더'를 구분한다(RC-14 침묵 백지 방지).

        U6-A(#975) 이후 이 문안은 **hwpx·txt 두 밴드의 정본**이다 — 루트가 하나라 원인도
        하나이고, 표면이 매체마다 다른 말을 지어내면 같은 사실을 두 곳이 판정하게 된다.
        복구 동선도 하나로 고정한다: 「폴더 선택」 단추는 사라졌고 설정 모달이 그 자리다."""
        if self._explicit_paths is not None:
            return "표시할 템플릿이 없습니다."
        root = self.library_dir
        if root is None:
            return "서식 폴더가 지정되지 않았습니다.\n설정에서 서식 폴더를 지정하세요."
        if not root.is_dir():
            return f"서식 폴더가 없습니다: {root}\n설정에서 서식 폴더를 다시 지정하세요."
        return f"서식 폴더에 템플릿이 없습니다: {root}"

    def refresh(self) -> None:
        """라이브러리를 다시 스캔해 행을 성형하고 통지(compile_status 매번 재산출)."""
        rows: "list[TemplateRow]" = []
        root = self.library_dir  # 표시명(루트 상대경로)의 기준 — 스캔 한 번에 한 번 읽는다
        for path in self._discover():
            try:
                inspection = self._inspect_template(str(path))
                # 채움 완화 사전 판정(#154) — 점검 표면의 "사전에 알고" 쪽.
                warns = tuple(
                    describe_precheck_note(n) for n in inspection.precheck_notes
                )
            except Exception as exc:  # noqa: BLE001 — 읽기 실패는 시끄럽게 노출(감추지 않음)
                rows.append(TemplateRow.from_error(path, str(exc), root=root))
                continue
            rows.append(
                TemplateRow.from_status(
                    path, inspection.status, fill_warns=warns, root=root
                )
            )
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
        sites = self._file_ops.scan_tokens(str(path))
        return ScanPreview(
            compilable=[s for s in sites if s.compilable],
            skipped=[s for s in sites if not s.compilable],
        )

    def apply_fieldize(self, path: str):
        """명시적 적용 — 토큰을 누름틀로 컴파일하고 **같은 경로에 저장**, 행 갱신.

        저장 후 그 파일의 compile_status 는 진행한다(RAW/PARTIAL → COMPILED). 바뀐 게
        없으면(``modified=False``) 저장하지 않는다(저장 판정은 포트 concrete 소유).
        리포트를 반환한다.
        """
        report = self._file_ops.compile_file(str(path))
        if report.modified:
            self.refresh()
        return report

    # ------------------------------------ 누름틀·구간 변환 2단계(S8-03 #834)
    def convert_preview(self, path: str) -> ConvertPreview:
        """dry-run — 필드 토큰 + 구간 표기를 한 미리보기로. **파일 무변형**(읽기 전용)."""
        tokens = self.scan_preview(path)
        scan = self._file_ops.scan_structure(str(path))
        return ConvertPreview(
            tokens=tokens,
            slots=scan.summary.slots,
            options=scan.summary.options,
            diagnostics=tuple(item.message for item in scan.diagnostics),
        )

    def apply_convert(self, path: str) -> ConvertResult:
        """명시적 적용 — **필드 컴파일 먼저, 구간 컴파일 다음**. 행 갱신 후 결과 반환.

        **순서 근거(S8-02 실측)**: 구간을 먼저 컴파일하면 그 region 안의 ``{{필드}}`` 는
        depth>0 이 되어 필드 스캔·컴파일에서 제외된다. 즉 순서를 뒤집으면 구간 안의 필드가
        조용히 미변환으로 남는다.

        두 단계는 각자 제자리 저장하는 파일 동사다(원자적 단일 저장은 두 커널 경로를 한
        패키지 세션으로 묶는 별건이다). 그래서 구간 컴파일이 거절되면 **그 사실을 결과에
        싣는다** — 필드만 저장되고 구조 거절이 조용히 사라지는 경로를 만들지 않는다.

        같은 이유로 구간 단계의 **예외**도 여기서 결과로 바꾼다(S8-F2 · #853 F-3): 필드
        단계가 이미 파일을 저장한 뒤라, 예외가 그대로 올라가면 호출자는 변이 사실을 모른
        채 재정산 통지를 건너뛴다. 예외를 숨기는 것이 아니라 **사유를 실어 내리는 것**이고
        (결과 줄이 danger 로 재진술한다), 필드 단계 자체의 예외는 변이 전이라 그대로 raise
        한다.
        """
        report = self._file_ops.compile_file(str(path))
        structure = None
        errors: "tuple[str, ...]" = ()
        try:
            structure = self._file_ops.compile_structure_file(str(path))
        except Exception as exc:  # noqa: BLE001 — 예외를 result 로 바꾼다(숨기지 않는다)
            errors = (f"구간 변환 중 오류가 났습니다: {exc}",)
        refusal = getattr(structure, "refusal", None) or ()
        slots = getattr(structure, "slots", ()) or ()
        mutated = bool(report.modified) or bool(getattr(structure, "modified", False))
        result = ConvertResult(
            fields=len(report.compiled),
            slots=len(slots),
            options=getattr(structure, "options", 0),
            refusals=tuple(item.message for item in refusal),
            errors=errors,
            mutated=mutated,
        )
        if mutated:
            self.refresh()
        return result

    def format_convert_result(self, path: str, result: ConvertResult) -> ResultLine:
        """적용 결과 → 결과 문구. 구조 거절·오류가 있으면 그 사유가 같은 줄에 남는다."""
        name = Path(path).name
        parts = [f"누름틀 {result.fields}개"]
        if result.slots:
            parts.append(f"항목 {result.slots}개")
        if result.options:
            parts.append(f"선택 {result.options}개")
        if result.failed:
            # 예상 밖 실패는 거절보다 세게 말한다. 필드 단계가 이미 저장한 뒤면 그 사실을
            # 먼저 밝힌다 — 파일이 바뀌었는지 아닌지가 다음 행동을 가른다.
            head = (
                f"구간 변환이 중단됐습니다 {name}: 누름틀 {result.fields}개는 저장됐습니다."
                if result.mutated
                else f"구간 변환이 중단됐습니다 {name}: 파일은 바뀌지 않았습니다."
            )
            reasons = "\n".join(f"- {item}" for item in result.errors)
            return ResultLine(f"{head}\n{reasons}", "danger")
        text = f"변환 완료 {name}: " + " · ".join(parts)
        if not result.refused:
            return ResultLine(text, "ok")
        reasons = "\n".join(f"- {item}" for item in result.refusals)
        return ResultLine(f"{text}\n구간 변환은 하지 못했습니다:\n{reasons}", "warn")

    def format_convert_blocked_result(
        self, path: str, preview: ConvertPreview
    ) -> ResultLine:
        """표기 진단 → 변환 불가 통지(인라인, warn). 확인을 묻지 않는다."""
        reasons = "\n".join(f"- {item}" for item in preview.diagnostics)
        return ResultLine(
            f"변환할 수 없습니다 {Path(path).name}: 구간 표기를 고친 뒤 다시 시도하세요."
            f"\n{reasons}",
            "warn",
        )

    def format_convert_empty_result(self, path: str, preview: ConvertPreview) -> ResultLine:
        """바꿀 것이 없음 → 인라인 결과(UD-24 동형, warn)."""
        name = Path(path).name
        text = f"변환 {name}: 변환할 토큰과 구간이 없습니다"
        if preview.tokens.skipped:
            names = ", ".join(site.name for site in preview.tokens.skipped)
            text += f" (건너뜀 {len(preview.tokens.skipped)}개: {names})"
        return ResultLine(text, "warn")

    # ------------------------------------------- 컴파일된 Slot 목록·관리 동사
    def slot_view(self, path: str) -> SlotView:
        """한 템플릿의 Slot 목록 투영(읽기 전용) — 판정 재조립 없이 Slot 을 편다."""
        name = Path(path).name
        inspection = self._inspect_template(str(path))
        return SlotView(
            path=str(path),
            name=name,
            rows=tuple(SlotRow.from_slot(slot) for slot in inspection.slots),
            diagnostics=tuple(item.message for item in inspection.diagnostics),
        )

    def _detail_name(self, path: str) -> str:
        """상세 머리의 표시명 — 목록 행과 **같은 어휘**(루트 상대·확장자 없음)."""
        return library_display_name(self.library_dir, Path(str(path)))

    def _failed_detail(self, path: str, reason: str) -> TemplateDetail:
        """판독이 실패한 항목의 상세 — 감추지 않고 **사유를 단** 한 벌을 돌려준다.

        목록의 오류 행(:meth:`TemplateRow.from_error`)과 같은 처분이다: 그 행에서도
        「자세히…」는 서고, 시트가 답할 것은 사유 하나다. 빈 상세를 지어내면 그 행의 문은
        눌러도 아무 말이 없다.
        """
        return TemplateDetail(
            path=str(path), name=self._detail_name(path), media="hwpx", state=None,
            badge_label=_badge_label(None), badge_level=_badge_level(None),
            error=reason,
        )

    def _detail_of(self, path: str, inspection: TemplateInspection) -> TemplateDetail:
        """판독 결과 → 상세 투영(순수 성형) — 판정은 하나도 여기서 새로 하지 않는다."""
        target = str(path)
        name = self._detail_name(target)
        state = inspection.status.state
        diagnostics = tuple(item.message for item in inspection.diagnostics)
        return TemplateDetail(
            path=target,
            name=name,
            media="hwpx",
            state=state,
            badge_label=_badge_label(state),
            badge_level=_badge_level(state),
            fields=tuple(FieldRow.of(field) for field in inspection.fields),
            actions=tuple(available_actions(state)),
            diagnostics=diagnostics,
            slots=SlotView(
                path=target,
                name=name,
                rows=tuple(SlotRow.from_slot(slot) for slot in inspection.slots),
                diagnostics=diagnostics,
            ),
        )

    def detail_view(self, path: str) -> TemplateDetail:
        """한 템플릿의 **상세 투영**(읽기 전용) — 「자세히…」 시트가 그릴 원료 한 벌.

        **파일을 한 번만 연다**: 상태·배지·필드·구간 항목·진단이 전부 같은 판독 스냅샷에서
        나온다. 나눠 읽으면 시트 한 장 안에서 「필드는 있는데 상태는 없다」 같은 갈린 사실이
        설 수 있다.

        판독 예외는 여기서 **사유로 접는다**(:meth:`_failed_detail`). 이 자리가 그 접기의
        단일 지점인 이유는 호출자가 셋이기 때문이다(검토 진입·동사 뒤 재투영·시트 재당김) —
        갈래마다 접으면 한 갈래에서 예외가 봉투 밖으로 새어 시트가 영영 안 열린다.
        """
        try:
            inspection = self._inspect_template(str(path))
        except Exception as exc:  # noqa: BLE001 — 읽기 실패는 시끄럽게(빈 상세 금지)
            return self._failed_detail(path, str(exc))
        return self._detail_of(path, inspection)

    def review_view(
        self, path: str, vocabulary=None
    ) -> "tuple[TemplateDetail, LintReport | None]":
        """검토 한 왕복 — 상세와 lint 리포트를 **파일 한 번 열기**로 함께 낸다(리뷰 7).

        나눠 열면 두 가지를 잃는다: 같은 시트가 두 스냅샷을 얹게 되고(그 사이의 변경이 갈린
        사실로 선다), 라이브러리가 클수록 「자세히…」 한 번의 비용이 두 배가 된다.

        판독이 예외면 **lint 는 없다**(``None``): 못 읽은 파일을 위생 점검할 수는 없고, 그
        사실은 상세의 ``error`` 가 이미 말한다. 예외를 여기서 접는 것이 계약이다 —
        ``zipfile.BadZipFile`` 은 ``ValueError`` 가 아니라 dispatch 의 거절 봉투를 벗어난다.
        """
        try:
            inspection, report = self._file_ops.inspect_and_lint(
                str(path), vocabulary=vocabulary
            )
        except Exception as exc:  # noqa: BLE001 — 읽기 실패는 사유를 단 상세로(봉투 밖 금지)
            return self._failed_detail(path, str(exc)), None
        return self._detail_of(path, inspection), report

    def rename_slot(self, path: str, slot_id: str, label: "str | None") -> SlotView:
        """Slot label 변경(구조 무변형) — 저장 후 목록을 다시 투영한다."""
        self._file_ops.rename_slot_label(str(path), slot_id, label)
        self.refresh()
        return self.slot_view(path)

    def decompile_slot(self, path: str, slot_id: str) -> SlotView:
        """Slot 하나를 구간 표기로 되돌리고 저장 — 그 템플릿은 다시 미변환 상태가 된다."""
        self._file_ops.decompile_slot(str(path), slot_id)
        self.refresh()
        return self.slot_view(path)

    def decompile_all_slots(self, path: str) -> SlotView:
        """그 템플릿의 **전 항목**을 구간 표기로 되돌리고 저장(U4-E3 #939).

        단건 동사(:meth:`decompile_slot`)와 같은 결이고 대상만 파일 하나다 — External 이
        원자적으로 풀거나(전 항목) 원본을 그대로 남긴다(부분 성공 없음). 성공하면 그
        템플릿은 통째로 미변환 상태가 되므로 목록을 다시 투영해 돌려준다.
        """
        self._file_ops.decompile_structure(str(path))
        self.refresh()
        return self.slot_view(path)

    def remove_slot(self, path: str, slot_id: str) -> SlotView:
        """Slot 하나를 **내용째** 지우고 저장."""
        self._file_ops.remove_slot(str(path), slot_id)
        self.refresh()
        return self.slot_view(path)

    def format_slot_result(self, path: str, text: str, level: str = "ok") -> ResultLine:
        """Slot 동사 결과 문구 — 대상 템플릿명을 늘 병기한다(RC-14 규율)."""
        return ResultLine(f"{text}: {Path(path).name}", level)

    def confirm_decompile_text(self, path: str, slot_id: str) -> str:
        """표기로 풀기 확인 본문 — **전이의 결과**를 재진술한다(#822 D5).

        푸는 순간 그 구간은 미변환 표기로 돌아가므로, 다시 변환하기 전에는 이 템플릿으로
        문서를 만들 수 없다. 그 사실이 확인의 요점이다.
        """
        return (
            f"'{slot_id}' 항목을 구간 표기로 되돌립니다.\n"
            f"되돌린 뒤: '{Path(path).name}' 은(는) 다시 변환하기 전까지 문서를 만들 수 "
            "없습니다.\n한글에서 표기를 고친 뒤 '누름틀·구간 변환'을 다시 하세요."
        )

    def confirm_decompile_all_text(self, path: str) -> str:
        """전체판 풀기 확인 본문 — 단건(:meth:`confirm_decompile_text`) 문형 승계.

        다른 것은 **범위 한 줄**뿐이다: 대상이 항목 하나가 아니라 이 파일의 전 항목이라는
        사실과 그 개수. 뒤 두 줄(전이 결과 · 되살리는 길)은 글자 그대로 같다 — 같은 전이라
        같은 말을 해야 하고, 여기서 문안을 새로 지으면 두 동사가 다른 사실을 말하게 된다.
        """
        count = len(self.slot_view(path).rows)
        return (
            f"항목 {count}개를 전부 구간 표기로 되돌립니다.\n"
            f"되돌린 뒤: '{Path(path).name}' 은(는) 다시 변환하기 전까지 문서를 만들 수 "
            "없습니다.\n한글에서 표기를 고친 뒤 '누름틀·구간 변환'을 다시 하세요."
        )

    def confirm_remove_slot_text(self, path: str, slot_id: str) -> str:
        """항목 삭제 확인 본문 — **내용까지** 사라진다는 손실 재진술(파괴 확정)."""
        row = next(
            (item for item in self.slot_view(path).rows if item.id == slot_id), None
        )
        options = "" if row is None else f" · 선택 {row.option_count}개"
        return (
            f"'{slot_id}' 항목을 지웁니다.\n"
            f"사라지는 것: 항목 범위의 본문{options}\n"
            f"대상 파일: {Path(path).name}"
        )

    # ----------------------------------------------------------- lint/drift
    def lint(self, path: str, vocabulary=None) -> LintReport:
        """단일 템플릿 위생 점검(유사 필드명·미치환 토큰·어휘). 읽기 전용.

        ``vocabulary`` 는 코어 :func:`~hwpxfiller.domain.lint.lint_template` 의 통제 어휘
        그대로 전달한다(RC-14 시그니처 정렬 — CLI ``--vocab`` 과 위생 점검 범위 동등).
        """
        return self._file_ops.lint(str(path), vocabulary=vocabulary)

    def drift(self, old_path: str, new_path: str) -> SchemaDrift:
        """두 판본의 필드셋 드리프트(추가/삭제/개명 추정). 읽기 전용."""
        return self._file_ops.diff(str(old_path), str(new_path))

    # ------------------------------------------------------ 결과 문구 성형(링1)
    # 단일 결과 라벨이 lint/미리보기/드리프트/컴파일을 무맥락으로 덮어쓰던 것을(RC-14)
    # 대상 템플릿명을 포함한 성형으로 고정한다 — 표현 계층이 아니라 여기 살아야
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
            return ResultLine(f"템플릿 변경 {pair}: 필드셋 변화 없음.", "ok")
        parts = [f"템플릿 변경 {pair}:"]
        for n in drift.added:
            parts.append(f"+ 추가: {n}")
        for n in drift.removed:
            parts.append(f"- 삭제: {n}")
        for r in drift.renamed:
            parts.append(f"~ 개명(추정): {r['old']} → {r['new']} ({r['score']})")
        return ResultLine("\n".join(parts), "warn")

    # ----------------------------------------------------- FILLED 값 미리보기
    def filled_values(self, path: str) -> "dict[str, str]":
        """FILLED(또는 임의) 템플릿의 현재 누름틀 값 — C1 read_fields 포트 위임."""
        return self._file_ops.read_fields(str(path))
