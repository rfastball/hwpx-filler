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

from dataclasses import dataclass, field

from ..core.lint import similarity
from ..core.mapping import (
    NARA_ALIASES,
    TRANSFORMS,
    FieldMapping,
    MappingProfile,
    suggest_mappings,
)
from ..core.schema import FieldSpec, TemplateSchema

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
            row.confirmed = True
            applied += 1
        return applied
