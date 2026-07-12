"""매핑 위저드 행 상태 모델 — Qt 비의존 순수 파이썬(헤드리스 단위 테스트 대상).

``suggest_mappings`` 초안과 사람의 확정 사이를 잇는 계층. **명시성 원칙**
([[hwpx-filler-scope]]): 자동 제안은 초안일 뿐이므로 초안이 채워져 있어도 모든 행은
``confirmed=False`` 로 시작하고, 사람이 행별로 확정해야 ``is_complete()`` 가 True 가
된다 — 위저드는 이 게이트를 통과해야만 생성 스텝으로 넘어간다.

행 편집(소스/변환/구분자/상수 변경)은 확정을 해제한다 — 확정 후 바뀐 행은
다시 사람의 눈을 거쳐야 한다. 저장된 프로파일의 로드(``apply_profile``)만 예외로
확정 상태로 도착한다: 프로파일 자체가 과거에 사람이 확정한 산출물이기 때문이다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..core.authoring import scan_tokens
from ..core.lint import similarity
from ..core.mapping import (
    NARA_ALIASES,
    TRANSFORMS,
    FieldMapping,
    MappingProfile,
    suggest_mappings,
)
from ..core.schema import FieldSpec, TemplateSchema, extract_schema
from ..core.template_status import CompileState, TemplateStatus, compile_status

# inferred_type → 기본 변환. 명시 없는 타입은 join(그대로).
_DEFAULT_TRANSFORM = {"date": "datetime", "amount": "amount"}


def default_transform_for(inferred_type: str) -> str:
    """스키마의 의미 타입에서 기본 변환을 유도한다."""
    return _DEFAULT_TRANSFORM.get(inferred_type, "join")


@dataclass
class RowState:
    """템플릿 필드 1개의 매핑 편집 상태.

    ``confirmed=True`` 인데 채울 내용이 없으면(소스도 상수도 없음) **의도적 비움
    확정** — "이 필드는 채우지 않는다"를 사람이 명시한 상태다(``to_profile`` 제외).
    ``suggestion_score`` 는 자동 제안의 유사도(0=제안 없음) — 뷰가 신뢰도 툴팁에 쓴다.
    """

    template_field: str
    spec: "FieldSpec | None" = None
    sources: "list[str]" = field(default_factory=list)
    transform: str = "join"
    sep: str = " "
    const: str = ""
    fmt: str = ""  # 표시형 프리셋 키(변환 내). "" = 기본.
    confirmed: bool = False
    suggestion_score: float = 0.0

    def has_content(self) -> bool:
        """매핑 내용이 있는가 — 소스가 있거나 비어 있지 않은 상수."""
        return bool(self.sources) or (self.transform == "const" and self.const != "")

    def is_empty_confirmed(self) -> bool:
        """의도적 비움 확정 — 확정됐지만 채울 내용이 없음."""
        return self.confirmed and not self.has_content()

    def to_mapping(self) -> FieldMapping:
        return FieldMapping(
            template_field=self.template_field,
            sources=list(self.sources),
            transform=self.transform,
            sep=self.sep,
            const=self.const,
            fmt=self.fmt,
        )


class MappingModel:
    """위저드 매핑 스텝의 전체 행 모델 — 뷰(mapping_table)는 이 API 만 호출한다."""

    def __init__(
        self,
        rows: "list[RowState] | None" = None,
        source_fields: "list[str] | None" = None,
        aliases: "dict[str, str] | None" = None,
    ):
        self.rows: "list[RowState]" = list(rows or [])
        self.source_fields: "list[str]" = list(source_fields or [])
        self.aliases: "dict[str, str]" = dict(aliases or {})

    # ------------------------------------------------------------- 초안 생성
    @classmethod
    def from_suggestions(
        cls,
        schema: TemplateSchema,
        source_fields: "list[str]",
        aliases: "dict[str, str] | None" = NARA_ALIASES,
    ) -> "MappingModel":
        """스키마 전 필드(문서순)에 행을 만들고 ``suggest_mappings`` 초안을 얹는다.

        미매칭 필드도 빈 행으로 포함한다(사람이 채우거나 비움 확정). 기본 변환은
        inferred_type 에서 유도(date→datetime, amount→amount, 그 외 join). 모든 행은
        confirmed=False 로 시작한다 — 초안은 초안이다(명시성 원칙).
        """
        aliases = dict(aliases or {})
        drafts = {
            m.template_field: m
            for m in suggest_mappings(schema.field_names(), source_fields, aliases)
        }
        rows: "list[RowState]" = []
        for spec in schema.fields:
            row = RowState(
                template_field=spec.name,
                spec=spec,
                transform=default_transform_for(spec.inferred_type),
            )
            draft = drafts.get(spec.name)
            if draft is not None:
                row.sources = list(draft.sources)
                # 제안 점수는 suggest 와 동일 방식(alias 라벨 대상 유사도)으로 복원.
                row.suggestion_score = max(
                    (similarity(spec.name, aliases.get(s, s)) for s in draft.sources),
                    default=0.0,
                )
            rows.append(row)
        return cls(rows=rows, source_fields=source_fields, aliases=aliases)

    # ------------------------------------------------------------ 행 편집 API
    def set_sources(self, index: int, sources: "list[str]") -> None:
        row = self.rows[index]
        row.sources = list(sources)
        row.confirmed = False

    def set_transform(self, index: int, transform: str) -> None:
        if transform not in TRANSFORMS:
            raise ValueError(f"지원하지 않는 변환: {transform!r} (지원: {TRANSFORMS})")
        row = self.rows[index]
        row.transform = transform
        row.fmt = ""  # 변환이 바뀌면 이전 표시형 키는 무효 → 기본으로.
        row.confirmed = False

    def set_fmt(self, index: int, fmt: str) -> None:
        """표시형(변환 내 프리셋) 변경 — 편집이므로 확정 해제."""
        row = self.rows[index]
        row.fmt = fmt
        row.confirmed = False

    def set_sep(self, index: int, sep: str) -> None:
        row = self.rows[index]
        row.sep = sep
        row.confirmed = False

    def set_const(self, index: int, const: str) -> None:
        row = self.rows[index]
        row.const = const
        row.confirmed = False

    def set_confirmed(self, index: int, confirmed: bool = True) -> None:
        """사람의 행별 확정/해제 — 빈 행 확정은 '의도적 비움'을 뜻한다."""
        self.rows[index].confirmed = confirmed

    def confirm_all(self) -> None:
        for row in self.rows:
            row.confirmed = True

    def unconfirm_all(self) -> None:
        for row in self.rows:
            row.confirmed = False

    # ------------------------------------------------------------- 상태 질의
    def is_complete(self) -> bool:
        """전 행이 사람 확정을 받았는가 — 명시성 게이트. 행이 없으면 False."""
        return bool(self.rows) and all(r.confirmed for r in self.rows)

    def preview(self, record: "dict[str, object]") -> "dict[str, str]":
        """행별 현재 매핑을 레코드 1건에 적용한 미리보기 값(확정 여부 무관)."""
        return {r.template_field: r.to_mapping().value_for(record) for r in self.rows}

    def preview_empties(self, record: "dict[str, object]") -> "list[str]":
        """내용은 매핑됐으나 이 레코드에선 값이 빈 필드 — validate.py 의 empty_valued 를
        단건화한 것. 의도적 비움(내용 없음) 행은 제외한다."""
        return [
            r.template_field
            for r in self.rows
            if r.has_content() and r.to_mapping().value_for(record) == ""
        ]

    # ------------------------------------------------------- 프로파일 입출력
    def to_profile(self, name: str = "") -> MappingProfile:
        """확정됐고 내용 있는 행만 프로파일로. 비움 확정 행은 제외한다."""
        return MappingProfile(
            name=name,
            mappings=[
                r.to_mapping() for r in self.rows if r.confirmed and r.has_content()
            ],
        )

    def apply_profile(self, profile: MappingProfile) -> int:
        """저장 프로파일을 행에 반영 — 일치 필드는 값 복원 + ``confirmed=True`` 도착.

        프로파일에 없는 필드는 건드리지 않는다(미확정 유지 — 사람이 마저 확정).
        반영된 행 수를 반환한다.
        """
        by_field = {m.template_field: m for m in profile.mappings}
        applied = 0
        for row in self.rows:
            m = by_field.get(row.template_field)
            if m is None:
                continue
            row.sources = list(m.sources)
            row.transform = m.transform
            row.sep = m.sep
            row.const = m.const
            row.fmt = m.fmt
            row.confirmed = True
            applied += 1
        return applied


# ============================================================= PARTIAL 확정 게이트
# 위저드 1단계(TemplatePage)의 위험 상태 게이트를 Qt 비의존 순수 파이썬으로 뽑아
# 헤드리스 단위 테스트가 가능하게 한다(위젯은 이 결정을 그대로 그린다).
def _leftover_token_names(
    sites: "list", strays: "list[str]"
) -> "list[str]":
    """PARTIAL 게이트가 재진술할 **미해결 토큰 이름** — 문서순·중복 제거.

    ``scan_tokens`` 사이트(컴파일 가능/파편 skip)의 이름 + 스키마의 본문 평문 잔존
    (``stray_tokens``)을 합친다. 이 이름들이 "값이 주입되지 않는다"를 사람에게 구체적으로
    재진술하는 대상이다(범용 메시지 금지 — ADR-E 반사적 dismiss 봉쇄의 전제).
    """
    names: "list[str]" = []
    seen: "set[str]" = set()
    for s in sites:
        if s.name and s.name not in seen:
            seen.add(s.name)
            names.append(s.name)
    for t in strays:
        if t and t not in seen:
            seen.add(t)
            names.append(t)
    return names


@dataclass
class PartialGate:
    """PARTIAL "다 된 것 같지만 아닌" 상태의 확정 게이트(Qt 비의존, 헤드리스 테스트 대상).

    ``compile_status`` 상태 + 미해결 토큰 이름에서 '진행 가부'를 파생한다:
    - ``RAW``(필드 0개): 차단(채울 대상 없음 — 상위 페이지가 이미 필드 없는 템플릿을 거부).
    - ``PARTIAL``(필드 有 + skip/파편/평문 잔존): **명시 ack 또는 인라인 컴파일 전까지 차단**
      — 값이 조용히 누락되는 위험을 소리 나게 세운다(confirm-or-alarm).
    - ``COMPILED``/``FILLED``: 통과.

    **반사적 dismiss 봉쇄(ADR-E).** ack 는 *정확히 재진술된 미해결 이름 전체*를 확인해야
    성립한다(``acknowledge`` 가 받은 이름 집합이 ``unmet_tokens`` 와 일치할 때만). 다른/부분/
    오래된 확인으로는 게이트가 열리지 않아, 이름을 안 보고 누르는 한 번-클릭 해제를 막는다.
    """

    status: TemplateStatus
    unmet_tokens: "list[str]" = field(default_factory=list)
    _acked: "set[str]" = field(default_factory=set)

    @property
    def state(self) -> CompileState:
        return self.status.state

    def needs_gate(self) -> bool:
        """PARTIAL 만 확정 게이트가 닫힌다(RAW 는 상위에서 차단, COMPILED/FILLED 는 통과)."""
        return self.status.state is CompileState.PARTIAL

    def acknowledge(self, confirmed: "Iterable[str]") -> None:
        """사용자가 재진술된 미해결 토큰을 직접 확인 — 확인한 **이름 집합**을 기록한다.

        위젯은 정확히 ``unmet_tokens`` 를 넘겨 확인시킨다. 부분/엉뚱한 이름을 넘기면
        ``is_acked`` 가 불성립이라 게이트가 열리지 않는다(반사적 확인 무력화).
        """
        self._acked = set(confirmed)

    def is_acked(self) -> bool:
        """미해결 토큰 **전체**를 정확히 확인했는가(부분·오래된·빈 확인은 불성립)."""
        return bool(self.unmet_tokens) and self._acked == set(self.unmet_tokens)

    def can_proceed(self) -> bool:
        """이 상태에서 다음 단계로 넘어가도 되는가 — 게이트의 최종 판정."""
        st = self.status.state
        if st is CompileState.RAW:
            return False
        if st is CompileState.PARTIAL:
            return self.is_acked()
        return True  # COMPILED / FILLED

    def message(self) -> str:
        """사람이 볼 게이트 메시지 — PARTIAL 은 구체 토큰 이름을 재진술한다."""
        st = self.status.state
        if st is CompileState.RAW:
            return (
                "이 템플릿에는 누름틀 필드가 없습니다 — 채울 대상이 없어 진행할 수 없습니다."
            )
        if st is not CompileState.PARTIAL:
            return ""
        names = ", ".join(self.unmet_tokens)
        if self.is_acked():
            return (
                f"확인함: 아래 {len(self.unmet_tokens)}개 토큰은 채우지 않고 진행합니다 — {names}"
            )
        return (
            f"진행 차단: 값이 주입되지 않는 토큰 {len(self.unmet_tokens)}개가 남아 있습니다 — "
            f"{names}. [여기서 컴파일]로 누름틀로 바꾸거나, 채우지 않음을 명시 확인하세요."
        )


def gate_for_template(pkg_or_path: object) -> PartialGate:
    """경로/바이트/패키지에서 컴파일 상태 + 미해결 토큰 이름을 읽어 게이트를 만든다.

    전부 읽기 전용(``compile_status``/``extract_schema``/``scan_tokens`` 는 무변형). 위저드와
    테스트가 공유하는 진입점 — PARTIAL 게이트가 겨누는 실제 파생을 한자리에 모은다.
    """
    status = compile_status(pkg_or_path)
    schema = extract_schema(pkg_or_path)
    unmet = _leftover_token_names(scan_tokens(pkg_or_path), schema.stray_tokens)
    return PartialGate(status=status, unmet_tokens=unmet)
