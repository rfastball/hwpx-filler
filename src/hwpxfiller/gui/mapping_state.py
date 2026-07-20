"""매핑 위저드 행 상태 모델 — Qt 비의존 순수 파이썬(헤드리스 단위 테스트 대상).

``suggest_mappings`` 초안과 사람의 확정 사이를 잇는 계층. **명시성 원칙**
([[hwpx-filler-scope]]): 자동 제안은 초안일 뿐이므로 초안이 채워져 있어도 모든 행은
``confirmed=False`` 로 시작하고, 사람이 행별로 확정해야 ``is_complete()`` 가 True 가
된다 — 위저드는 이 게이트를 통과해야만 다음(저장) 단계로 넘어간다.

행 편집(소스/유형/상수 변경)은 확정을 해제한다 — 확정 후 바뀐 행은
다시 사람의 눈을 거쳐야 한다. 저장된 프로파일의 로드(``apply_profile``)만 예외로
확정 상태로 도착한다: 프로파일 자체가 과거에 사람이 확정한 산출물이기 때문이다.

**엄격한 1:1 계약**(코어 미러). 한 템플릿 필드는 정확히 한 소스 키(``source``)에서
값을 취한다 — N→1 결합·구분자(sep)는 없다. 날짜+시각처럼 예전에 두 키를 합치던
자리는 소스가 이미 합쳐진 단일 키를 주거나 각각 별도 필드로 매핑한다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..core.authoring import scan_tokens
from ..core.lint import similarity
from ..core.mapping import (
    TYPES,
    FieldMapping,
    MappingProfile,
    suggest_mappings,
)
from ..core.schema import FieldSpec, TemplateSchema, extract_schema
from ..core.template_status import CompileState, TemplateStatus, compile_status

# inferred_type → 기본 값 유형. 명시 없는 타입은 text(그대로).
_DEFAULT_TYPE = {"date": "date", "amount": "amount"}

# RAW(필드 0개) 차단 사유의 **단일 원천**(UD-21). 위저드 1단계와 PartialGate.message()
# 가 같은 문구를 쓰도록 여기 한 곳에서만 정의한다 — 뷰·VM 이중화(문구 드리프트) 금지.
RAW_BLOCK_MESSAGE = (
    "이 템플릿에는 누름틀 필드가 없습니다 — 채울 대상이 없어 진행할 수 없습니다.\n"
    "한글에서 누름틀을 삽입하거나 누름틀 변환(fieldize)으로 토큰을 바꾼 템플릿을 쓰세요."
)


def default_transform_for(inferred_type: str) -> str:
    """스키마의 의미 타입에서 기본 값 유형을 유도한다(date→date, amount→amount, 그 외 text)."""
    return _DEFAULT_TYPE.get(inferred_type, "text")


def profile_source_vocabulary(profile) -> "list[str]":
    """프로파일이 참조하는 소스 키 합집합 — 선언순·중복 제거(단일 출처).

    malformed blank+source(구/훼손 프로파일이 blank 선언에 source 를 남긴 경우)는
    어휘에 흘리지 않는다 — 유령 키가 소스 피커 후보로 오표시되는 것을 막는다.
    :meth:`MappingModel.from_profile` 과 에디터 편집 모드 복원(``load_job``)이 같은
    합집합을 써야 드롭다운 오표시가 표류하지 않아 여기 한 곳에 모은다.
    """
    seen: "dict[str, None]" = {}
    for m in profile.mappings:
        if not m.is_blank and m.source:
            seen.setdefault(m.source, None)
    return list(seen)


@dataclass
class RowState:
    """템플릿 필드 1개의 매핑 편집 상태 — 단일 ``source`` 를 ``type`` 으로 서식.

    ``confirmed=True`` 인데 채울 내용이 없으면(소스도 상수도 없음) **의도적 비움
    확정** — "이 필드는 채우지 않는다"를 사람이 명시한 상태다(``to_profile`` 이
    명시적 ``blank`` 선언으로 영속화 — L1).
    ``suggestion_score`` 는 자동 제안의 유사도(0=제안 없음) — 뷰가 신뢰도 툴팁에 쓴다.

    **소유권(칩-라이브 계약, R-flow 슬라이스 5 블록 2 결정 12)**: ``touched`` 는 사람이 소스/
    내용을 직접 골랐거나 편집했는가다. **미확정·미접촉**(``not confirmed and not touched``)
    = 시스템 소유 → 활성 헤더가 바뀌면 최선으로 **라이브 재제안**된다(조용). **수동(touched)·
    확정** = 사람 소유 → 칩 토글이 못 덮고, 매핑된 헤더가 꺼지면 **시끄러운 강등**(R4)한다.
    ``from_suggestions`` 초안은 ``touched=False``(제안일 뿐), 사람 편집·프로파일 복원은 True.
    """

    template_field: str
    spec: "FieldSpec | None" = None
    source: str = ""
    type: str = "text"
    const: str = ""
    fmt: str = ""  # 표시형 프리셋 키(유형 내). "" = 기본.
    confirmed: bool = False
    suggestion_score: float = 0.0
    touched: bool = False  # 사람이 소스/내용을 직접 정함(수동=사람 소유). 미접촉=시스템 소유.

    def is_system_owned(self) -> bool:
        """시스템 소유 행 — 미확정·미접촉이라 활성 헤더 따라 라이브 재제안 대상(결정 12)."""
        return not self.confirmed and not self.touched

    def is_human_owned(self) -> bool:
        """사람 소유 행(확정 또는 touched) — 소유권 술어의 단일 정의(리뷰: 3중 재진술이
        강등·재제안·이월을 어긋나게 하는 조용한 드리프트류). 강등 조건·이월 대상이 이걸 쓴다."""
        return not self.is_system_owned()

    def reset_to_system(self) -> None:
        """행을 갓 제안 전의 **시스템 소유 초기 상태**로 완전 리셋 — 강등·되돌리기의 단일 정의.

        소유권 해제(touched/confirmed)만으로는 부족하다(리뷰 R1 동류): 유형·상수·표시형이
        남으면 이후 재제안이 소스만 얹어 '제안 표시 ≠ 실제 출력(옛 상수 방출)' 하이브리드가
        된다. 두 강등 경로(``revert_to_auto``·``apply_active_sources`` R4)가 전부 이 정의로
        착지해 관문 간 상태 불일치를 막는다(구판 ``ignore_source`` 는 관문 단일화로 소멸).
        소스 재제안은 호출측 소관(단일 행=``resuggest_row``, 집합=다음 활성 변화)."""
        self.touched = False
        self.confirmed = False
        self.source = ""
        self.const = ""
        self.fmt = ""
        self.type = default_transform_for(self.spec.inferred_type if self.spec else "")
        self.suggestion_score = 0.0

    def has_content(self) -> bool:
        """매핑 내용이 있는가 — 소스가 있거나 비어 있지 않은 상수."""
        return bool(self.source) or (self.type == "const" and self.const != "")

    def is_empty_confirmed(self) -> bool:
        """의도적 비움 확정 — 확정됐지만 채울 내용이 없음."""
        return self.confirmed and not self.has_content()

    def to_mapping(self, *, blank: bool = False) -> FieldMapping:
        return FieldMapping(
            template_field=self.template_field,
            source="" if blank else self.source,
            type="blank" if blank else self.type,
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
        aliases: "dict[str, str] | None" = None,
    ) -> "MappingModel":
        """스키마 전 필드(문서순)에 행을 만들고 ``suggest_mappings`` 초안을 얹는다.

        미매칭 필드도 빈 행으로 포함한다(사람이 채우거나 비움 확정). 기본 유형은
        inferred_type 에서 유도(date→date, amount→amount, 그 외 text). 모든 행은
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
                type=default_transform_for(spec.inferred_type),
            )
            draft = drafts.get(spec.name)
            if draft is not None and draft.source:
                row.source = draft.source
                # 제안 점수는 suggest 와 동일 방식(alias 라벨 대상 유사도)으로 복원.
                row.suggestion_score = similarity(
                    spec.name, aliases.get(draft.source, draft.source)
                )
            rows.append(row)
        return cls(rows=rows, source_fields=source_fields, aliases=aliases)

    @classmethod
    def from_profile(cls, profile) -> "MappingModel":
        """저장된 프로파일(공유 베이스)에서 직접 행 모델을 구성한다 — 템플릿 없이.

        각 ``FieldMapping`` → **확정** ``RowState``(과거 사람 확정의 복원, ``apply_profile`` 선례).
        워크벤치가 베이스를 표시·재편집할 때 쓴다. ``source_fields`` 는 프로파일이 참조하는
        소스 키 합집합(테이블 소스 피커의 후보, :func:`profile_source_vocabulary` 공유 —
        유령 키 필터 문서화도 그쪽) — 별도 소스 주입 없이도 기존 매핑을 손본다.
        """
        rows: "list[RowState]" = []
        for m in profile.mappings:
            is_blank = m.is_blank
            rows.append(RowState(
                template_field=m.template_field,
                source="" if is_blank else m.source,
                type="text" if is_blank else m.type,
                const="" if is_blank else m.const,
                fmt="" if is_blank else m.fmt,
                confirmed=True,  # 베이스는 확정본
                touched=True,  # 사람 소유(과거 확정 산출물) — 라이브 재제안 비대상(결정 12)
            ))
        return cls(
            rows=rows, source_fields=profile_source_vocabulary(profile), aliases={}
        )

    # ------------------------------------------------------------ 행 편집 API
    # 사람의 편집은 모두 ``touched=True`` — 그 행은 사람 소유가 되어 활성 헤더 변화의 라이브
    # 재제안이 덮지 못한다(칩-라이브 결정 12). 자동 제안으로 되돌리려면 ``revert_to_auto``.
    def set_source(self, index: int, source: str) -> None:
        row = self.rows[index]
        row.source = source
        row.confirmed = False
        row.touched = True

    def set_type(self, index: int, type_: str) -> None:
        if type_ not in TYPES:
            raise ValueError(f"지원하지 않는 유형: {type_!r} (지원: {TYPES})")
        row = self.rows[index]
        row.type = type_
        row.fmt = ""  # 유형이 바뀌면 이전 표시형 키는 무효 → 기본으로.
        row.confirmed = False
        row.touched = True

    def set_fmt(self, index: int, fmt: str) -> None:
        """표시형(유형 내 프리셋) 변경 — 편집이므로 확정 해제."""
        row = self.rows[index]
        row.fmt = fmt
        row.confirmed = False
        row.touched = True

    def set_const(self, index: int, const: str) -> None:
        row = self.rows[index]
        row.const = const
        row.confirmed = False
        row.touched = True

    def revert_to_auto(self, index: int) -> None:
        """사람 소유(touched) 행을 시스템 소유로 **완전** 되돌린다 — 자동 제안에 다시 맡김(칩-라이브).

        소스뿐 아니라 사람이 손댄 유형·상수·표시형도 초기화한다(리뷰 R1): 소스만 풀면 재제안이
        새 소스를 얹어 '제안'으로 보이는데 type=const 가 남아 ``to_mapping`` 이 옛 상수를 그대로
        방출하는 하이브리드(제안 표시 ≠ 실제 출력)가 된다 — 되돌리기는 갓 제안된 행과 동형이어야
        한다. 소스는 여기서 세우지 않는다 — 호출측이 활성 집합으로 ``resuggest_row`` 를 돌려 그
        행만 라이브 재제안한다(무관 행 불건드림, 리뷰 R4). 리셋 정의는
        :meth:`RowState.reset_to_system` 단일 출처(강등 경로들과 동일 착지).
        """
        self.rows[index].reset_to_system()

    def set_confirmed(self, index: int, confirmed: bool = True) -> None:
        """사람의 행별 확정/해제 — 빈 행 확정은 '의도적 비움'을 뜻한다."""
        self.rows[index].confirmed = confirmed

    def confirm_all(self) -> None:
        for row in self.rows:
            row.confirmed = True

    def unconfirm_all(self) -> None:
        for row in self.rows:
            row.confirmed = False

    def _score_row(self, row: "RowState", m) -> None:
        """제안 결과(FieldMapping | None)를 행에 얹는다 — 소스·제안 점수(후보 없으면 비움).

        점수는 ``from_suggestions`` 와 같은 방식(alias 라벨 대상 유사도)으로 복원한다 —
        ``suggest_mappings`` 가 점수를 돌려주지 않아 재계산한다(리뷰 R8: from_suggestions 와
        동일 패턴, 필드·소스 수가 작아 무시 수준). 단일 출처화로 재제안 경로가 어긋나지 않는다.
        """
        if m is not None and m.source:
            row.source = m.source
            row.suggestion_score = similarity(row.template_field, self.aliases.get(m.source, m.source))
        else:
            row.source = ""
            row.suggestion_score = 0.0

    def _resuggest_system_rows(self, active_sources: "list[str]") -> None:
        """시스템 소유 행(미확정·미접촉)의 소스를 활성 헤더 중 최선으로 다시 세운다(라이브 재제안).

        칩-라이브 결정 12의 '미접촉 = 시스템 소유, 활성 헤더 따라 라이브 재제안'. ``suggest_mappings``
        를 활성 소스만으로 다시 돌려(from_suggestions 와 같은 산출) 시스템 행의 소스·제안 점수를
        갱신한다. 활성 중 맞는 후보가 없으면 ``source=""``(후보 없음). 사람 소유 행은 건드리지 않는다.
        """
        system_fields = [r.template_field for r in self.rows if r.is_system_owned()]
        if not system_fields:
            return
        drafts = {
            m.template_field: m
            for m in suggest_mappings(system_fields, active_sources, self.aliases)
        }
        for row in self.rows:
            if row.is_system_owned():
                self._score_row(row, drafts.get(row.template_field))

    def resuggest_row(self, index: int, active_sources: "list[str]") -> None:
        """**단일** 행만 활성 헤더 중 최선으로 재제안한다(``revert_to_auto`` 직후 — 리뷰 R4).

        전집합 ``apply_active_sources`` 를 쓰면 무관한 stale 사람 소유 행까지 강등돼 조용히
        파괴된다(되돌리기는 그 행 하나의 의사표시일 뿐) — 그 행만 다시 세운다. 사람 소유 행에는
        무영향(시스템 소유일 때만 동작)."""
        row = self.rows[index]
        if not row.is_system_owned():
            return
        drafts = {
            m.template_field: m
            for m in suggest_mappings([row.template_field], active_sources, self.aliases)
        }
        self._score_row(row, drafts.get(row.template_field))

    def apply_active_sources(
        self, active_sources: "list[str]", *, vocabulary: "list[str] | None" = None
    ) -> "list[str]":
        """활성 소스 집합 변경을 반영한다(칩-라이브 결정 12·13 — 헤더 사용/미사용의 단일 관문).

        - **시스템 소유 행**(미확정·미접촉): 활성 헤더 중 최선으로 **라이브 재제안**(조용).
        - **사람 소유 행**(확정·touched)의 소스가 **비활성이 되면 시끄러운 강등**(R4):
          ``source=""`` · ``confirmed=False`` · ``touched=False`` 로 되돌리고 이름을 반환한다.

        ``vocabulary``(현재 데이터의 전체 헤더)를 주면 강등은 **어휘 안 소스**로 한정된다
        (PR-3 리뷰 F1): 어휘 밖 소스를 겨눈 사람 소유 행(이월된 stale — 뷰가 「데이터에 없음」
        으로 이미 시끄럽게 표시)은 헤더 칩 조작과 무관하므로 건드리지 않는다 — 전집합 강등이면
        무관한 칩 토글 한 번에 이월 값이 소실되고 통지는 끈 적 없는 헤더를 지목한다(오귀속).
        None(기본)이면 종전 거동(활성 밖 전부 강등) — 어휘 개념이 없는 호출측 호환.

        **순서가 계약이다**(리뷰 R3): 재제안을 **먼저** 하고 강등을 **나중**에 한다. 그러면
        강등된 사람 소유 행은 ``source=""`` 로 **비어 남는다** — 재제안이 다른 그럴싸한 소스를
        얹어 사용자가 재확정 시 원래와 다른 열로 조용히 치환되는 것을 막고, 의식적 재선택을
        강제한다(구 ``ignore_source`` 의 안전 거동 복원). '항상 시스템이었던' 행만 재제안되고,
        이번에 강등된 행은 다음 활성 변화에서야 시스템 소유로 재제안된다.

        구 ``ignore_source``(헤더별 무차별 해제)의 대체 — 헤더/모델 정합을 한 번에 재계산해
        같은 파일 재겨눔 시 헤더 UI 와 모델이 어긋나던 창을 닫는다(리뷰 F3). 반환 = R4 강등 이름.

        강등은 **완전 리셋**(:meth:`RowState.reset_to_system`)이다: 소스·확정만 풀고 유형·
        상수를 남기면 강등 행이 시스템 소유가 된 뒤 다음 재제안이 소스를 얹어 '제안 표시 ≠
        옛 상수 방출' 하이브리드가 된다(``revert_to_auto`` 리뷰 R1 과 같은 근거 — 강등 경로만
        부분 리셋일 이유가 없다).
        """
        active_set = set(active_sources)
        vocab = set(vocabulary) if vocabulary is not None else None
        self._resuggest_system_rows(active_sources)  # 1) 항상 시스템이던 행만 재제안(강등 전)
        demoted: "list[str]" = []
        for row in self.rows:  # 2) 사람 소유 행 R4 강등 — 비운 채 남긴다(재제안 안 함)
            if (
                row.is_human_owned()
                and row.source
                and row.source not in active_set
                and (vocab is None or row.source in vocab)  # 어휘 밖 stale 은 불건드림(F1)
            ):
                row.reset_to_system()
                demoted.append(row.template_field)
        return demoted

    # 구판 ignore_source(헤더별 무차별 해제)는 칩-라이브 재배선으로 소비자가 소멸해 제거됐다
    # — 헤더 사용/미사용의 유일 관문은 apply_active_sources(결정 12·13).

    # --------------------------------------------------- 대량 확정 게이트(UD-05)
    # '모두 확정'은 ADR-D 의 '고신뢰 매칭 일괄 수락'만 담당한다: 내용 있는 행만
    # 즉시 확정하고, 내용 없는 미매칭 행의 **의도적 비움 승격**은 뷰가 이름 재진술
    # 확인(ADR-E)을 거쳐 confirm_fields 로 따로 확정한다(무경고 대량 우회 금지).
    def confirm_content_rows(self) -> int:
        """내용(소스/상수)이 있는 행만 확정한다 — 미매칭 빈 행은 건드리지 않는다.

        반환값은 이번에 새로 확정 상태가 된 행 수(이미 확정된 행 제외).
        """
        n = 0
        for row in self.rows:
            if row.has_content() and not row.confirmed:
                row.confirmed = True
                n += 1
        return n

    def unconfirmed_blank_fields(self) -> "list[str]":
        """미확정이면서 내용이 없는(미매칭) 행의 템플릿 필드 이름 — 문서순.

        '모두 확정' 시 **의도적 비움으로 승격될 후보**다. 뷰는 이 이름들을 재진술해
        사람에게 확인시킨 뒤에만 confirm_fields 로 확정한다(ADR-E 반사적 dismiss 봉쇄).
        """
        return [
            r.template_field
            for r in self.rows
            if not r.confirmed and not r.has_content()
        ]

    def confirm_fields(self, fields: "Iterable[str]") -> int:
        """이름으로 재진술·확인된 필드들만 확정한다(대량 비움 확정의 이름-게이트 경로)."""
        names = set(fields)
        n = 0
        for row in self.rows:
            if row.template_field in names and not row.confirmed:
                row.confirmed = True
                n += 1
        return n

    def confirmed_count(self) -> int:
        """확정된 행 수 — '모두 해제' 파괴 확인 게이트가 파기 규모를 진술하는 근거."""
        return sum(1 for r in self.rows if r.confirmed)

    # ------------------------------------------------------------- 상태 질의
    def is_schema_only(self) -> bool:
        """데이터 미연결(스키마온리) 세션인가 — 연결된 데이터 소스의 필드가 0개(UD-28).

        데이터 스텝을 건너뛰면(ADR-J 선택 플로우) ``source_fields`` 가 비어 애초에
        매칭할 데이터가 없다. 이때 내용 없는 행은 '미매칭'(데이터가 있는데 못 맞춘 것)이
        아니라 '데이터 미연결'이다 — 뷰가 빨강 경보를 중립으로 강등하고(오경보 방지),
        스키마온리 안내 배너를 띄우는 근거다. Qt 비의존이라 헤드리스로 검증한다.
        """
        return not self.source_fields

    def is_complete(self) -> bool:
        """전 행이 사람 확정을 받았는가 — 명시성 게이트. 행이 없으면 False."""
        return bool(self.rows) and all(r.confirmed for r in self.rows)

    def emits_any_value(self) -> bool:
        """확정된 행 중 실제 값을 방출하는 행이 하나라도 있는가 — '전부 비움' 저장 가드.

        전 행을 비움 확정하면 ``is_complete`` 는 통과하지만 ``to_profile`` 은 blank
        선언만 담아 어떤 누름틀에도 값을 주입하지 않는다(RC-08). blank 도 mappings 에
        영속화되므로(L1) 뷰는 자료구조 내부(``profile.mappings``)가 아니라 이 질의로
        무의미 작업 저장을 판단한다.
        """
        return any(r.confirmed and r.has_content() for r in self.rows)

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

    def preview_counts(self, record: "dict[str, object]") -> "tuple[int, int, int]":
        """미리보기 3상태 집계 ``(채움, 빈 값, 미매핑)`` — 합은 언제나 전체 행 수(UD-27).

        기존 요약은 '채움/빈 값' 2상태만 세어 미매핑(내용 없는) 행이 무집계로 빠져
        합계가 필드 수와 어긋났다(공란 규모 과소 진술). 세 항의 합 = ``len(rows)`` 로
        묶어 어떤 필드도 집계에서 사라지지 않게 한다(ADR-B '빈 공간으로 보이면 안 됨').
        """
        empties = self.preview_empties(record)
        content_rows = sum(1 for r in self.rows if r.has_content())
        filled = content_rows - len(empties)
        unmapped = len(self.rows) - content_rows
        return filled, len(empties), unmapped

    # ------------------------------------------------------- 프로파일 입출력
    def to_profile(self, name: str = "") -> MappingProfile:
        """확정된 전 행을 프로파일로. 빈 행은 명시적 ``blank`` 선언으로 영속화한다."""
        return MappingProfile(
            name=name,
            mappings=[
                r.to_mapping(blank=r.is_empty_confirmed())
                for r in self.rows if r.confirmed
            ],
        )

    def human_owned_rows(self) -> "list[RowState]":
        """사람 소유 행 — 확정됐거나 손댐(touched). 미접촉 제안(시스템 소유)은 제외."""
        return [r for r in self.rows if r.is_human_owned()]

    def carry_profile(self, name: str = "") -> MappingProfile:
        """데이터 교체 재초안 시 **이월용** 프로파일 — 사람 소유 행의 값(소스/유형/상수/서식).

        확정 전용 :meth:`to_profile` 과 달리 **touched 미확정 행도 담는다**(리뷰 F2: 미확정
        수동 편집도 '사람 소유'라 데이터를 바꿔도 조용히 소실시키지 않는다). 미접촉 제안(시스템
        소유)은 담지 않는다 — 새 데이터 기준으로 재제안돼야 하므로. ``apply_profile(confirm=False)``
        로 적용해 값만 이월하고 전 행 미확정으로 착지시킨다(사람 재검토 강제).

        단 **내용 없는 touched 미확정 행은 담지 않는다**(리뷰 반영): 비움 확정(blank 선언)도
        아니고 이월할 값도 없는데 담으면, ``apply_profile`` 이 touched 를 재날인해 그 필드가
        새 데이터에서 **영구히 라이브 재제안에서 제외**된다(조용한 동결). 그런 행은 시스템
        소유로 낙착시켜 새 데이터 기준 자동 제안을 다시 받게 한다.
        """
        return MappingProfile(
            name=name,
            mappings=[
                r.to_mapping(blank=r.is_empty_confirmed())
                for r in self.human_owned_rows()
                if r.confirmed or r.has_content()
            ],
        )

    def apply_profile(
        self,
        profile: MappingProfile,
        *,
        require_source: bool = False,
        confirm: bool = True,
    ) -> int:
        """저장 프로파일을 행에 반영 — 일치 필드는 값 복원 + ``confirmed=True`` 도착.

        프로파일에 없는 필드는 건드리지 않는다(미확정 유지 — 사람이 마저 확정).
        반영된 행 수(값이 복원되고 확정 자격이 있는 행)를 반환한다.

        ``require_source=True``: 복원한 행이 참조하는 소스 컬럼이 현재 소스 어휘
        (``source_fields``)에 **없으면 확정 도착시키지 않는다**(값은 복원하되 미확정 유지).
        데이터를 바꿔 이전 확정을 되살릴 때, 사라진 컬럼을 겨눈 행이 조용히 확정 상태로
        남아 저장 게이트(``is_complete``)를 통과하고 빈 값 문서를 찍는 함정을 막는다 —
        그런 행은 미확정으로 남아 사람 재검토를 강제한다(빈/const 행은 소스 의존이 없어
        영향 없음). 기본(False)은 종전 거동(전 일치 행 확정)이라 다른 호출측은 불변이다.

        ``confirm=False``: 값(소스/유형/상수/서식)만 이월하고 **어느 행도 확정 도착시키지
        않는다** — 전 행 미확정 초안. 템플릿/데이터 키가 바뀐 재초안 경로가 쓴다: 같은
        이름 컬럼이라도 새 데이터에선 의미가 다를 수 있어, 이전 확정을 확정 상태로 되살리면
        사람 검토 없이 ``is_complete`` 를 통과해 저장·실행까지 흐른다(조용한 게이트 우회).
        기본(True)은 종전 거동(프로파일 로드=사람 확정 산출물 복원)이라 다른 호출측은 불변.
        """
        available = set(self.source_fields)
        by_field = {m.template_field: m for m in profile.mappings}
        applied = 0
        for row in self.rows:
            m = by_field.get(row.template_field)
            if m is None:
                continue
            row.source = "" if m.is_blank else m.source
            row.type = "text" if m.is_blank else m.type
            row.const = "" if m.is_blank else m.const
            row.fmt = "" if m.is_blank else m.fmt
            # 프로파일 복원/이월된 행은 **사람 소유**(과거 확정 산출물 또는 touched 이월) —
            # touched=True 로 라이브 재제안이 덮지 못하게 한다(칩-라이브 결정 12). 확정 여부는
            # confirm 인자·missing_source 가 따로 결정한다(값 복원 ≠ 확정 도착).
            row.touched = True
            missing_source = (
                require_source
                and not m.is_blank
                and bool(m.source)
                and m.source not in available
            )
            row.confirmed = confirm and not missing_source
            if not missing_source:
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

    이름이 빈 사이트(예: ``{{   }}`` 공백뿐인 토큰 — ``compile_status`` 는 compilable 로
    세어 PARTIAL 로 트리거하지만 정제 이름은 "")도 대표 라벨로 반드시 열거한다. 그러지
    않으면 ``unmet_tokens`` 가 비어 ack 가 "0개 토큰" dead-end 가 되고, 열거가 PARTIAL
    트리거와 어긋난다(fail-closed 지만 진행 불가한 함정).
    """
    names: "list[str]" = []
    seen: "set[str]" = set()
    for s in sites:
        label = s.name or "(이름 없는 토큰)"  # 무명 토큰도 대표 라벨로 열거(트리거와 일치)
        if label not in seen:
            seen.add(label)
            names.append(label)
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
            return RAW_BLOCK_MESSAGE
        if st is not CompileState.PARTIAL:
            return ""
        names = ", ".join(self.unmet_tokens)
        if self.is_acked():
            return (
                f"확인함: 아래 {len(self.unmet_tokens)}개 토큰은 비우고 진행합니다 — {names}"
            )
        return (
            f"진행 차단: 값이 주입되지 않는 토큰 {len(self.unmet_tokens)}개가 남아 있습니다 — "
            f"{names}. [여기서 누름틀 변환]으로 누름틀로 바꾸거나, 비움을 명시 확인하세요."
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
