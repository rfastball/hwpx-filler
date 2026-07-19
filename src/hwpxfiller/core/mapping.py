"""매핑 계층 — 소스 레코드(DataSource) → 템플릿 필드 값. 취득과 문서생성 사이의 불변 계층.

취득(Excel/API/크롤)이 아무리 좋아져도 "어떤 소스 키를 어떤 템플릿 필드에 어떤 alias·
유형으로 꽂을지"는 사람이 관리한다. 그 결정을 재사용 가능한 영속 산출물(**프로파일**)로
고정한다. 같은 소스 스키마면 프로파일 1회 저작 후 영구 재사용(API/크롤의 결정적 이득).

**엄격한 1:1 계약.** 한 템플릿 필드는 정확히 한 소스 키에서 값을 취한다(N→1 결합·sep
없음). 날짜+시각처럼 예전에 두 키를 합치던 자리는 이제 소스가 이미 합쳐진 단일 키를
제공하거나(권장), 각각 별도 필드로 매핑한다. 결합 계층을 제거해 모델을 단순·검증가능하게
유지한다.

실데이터(공공 API 등)가 드러낸 요구를 담는다:
  1. **alias** — 소스 키가 영문코드라 한글 템플릿 필드명과 직접 안 맞음(소스가
     자기 어휘를 ``field_labels()`` 로 선언하면 퍼지 타겟이 된다 — 코어는 어휘-불가지).
  2. **값 유형** — 숫자→금액서식, 날짜/시각 서식, 상수 리터럴.

그래서 프로파일은 ``{템플릿필드: {source, type, fmt, const}}`` 형태다.

**명시성 원칙**([[hwpx-filler-scope]]): ``suggest_mappings`` 는 퍼지 초안 제안일 뿐,
사람이 확정·수정한다. 자동으로 몰래 꽂지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import format_engine as _fe
from .lint import similarity
from hwpxcore.atomic import write_text_atomic

# 소스별 어휘(소스 키 → 한글 라벨)는 **코어가 소유하지 않는다**. 각 DataSource 가
# ``field_labels()`` 로 자기 어휘를 선언하고(예: ``data/nara.py`` 의 나라장터 36쌍),
# GUI 가 선택된 소스의 라벨을 ``suggest_mappings(..., aliases=...)`` 로 주입한다.
# 코어는 어휘-불가지: ``aliases`` 는 아래 서명에서 순수 범용 인자다.

# 지원 값 유형. text/date/amount 는 단일 소스 값의 표시형 서식을 교체 가능한
# core/format_engine 에 위임하고, const 는 소스와 무관한 리터럴이다.
# ``blank`` 는 empty-confirmed 행의 내부 영속 마커라 공용 UI 목록에 노출하지 않는다.
TYPES = ("text", "date", "amount", "const")

# 원본 소스 값을 실제로 나르는 유형 — ``const`` 는 리터럴을 방출해 ``source`` 와 무관하다
# (:func:`apply_transform` 의 분기와 일치). '파일명이 이 열을 나르는가'(식별 요약 토큰 모드
# 등)를 묻는 곳의 단일 출처 — 화이트리스트를 곳곳에 재적지 않는다. ``blank`` 은 TYPES 에
# 없는 내부 마커라 자연히 제외된다.
SOURCE_CARRIER_TYPES = tuple(t for t in TYPES if t != "const")


# ------------------------------------------------------------------ 변환
def apply_transform(kind: str, value: str = "", const: str = "", fmt: str = "") -> str:
    """단일 소스 값을 유형(``kind``)·표시형(``fmt``)에 따라 서식 엔진으로 포맷.

    ``fmt`` 는 유형 안의 표시형 **서식 코드**("" = 기본, 예: ``"{:,}"``·``"%Y-%m-%d"``).
    코드 해석은 교체 가능한 `format_engine` 에 위임한다(현재 stdlib). text/date/amount 만
    표시형을 가지며, const 는 리터럴을, blank 는 언제나 빈 값을 낸다.
    """
    if kind == "blank":
        # 의도적 공란은 값 추론이 아니라 매핑 계약의 명시적 선언이다. 단독
        # FieldMapping 평가도 언제나 빈 값이어야 한다.
        return ""
    if kind == "const":
        return const
    if kind in ("text", "date", "amount"):
        return _fe.render(kind, fmt, value.strip())
    # 미지 유형을 조용히 폴백하면 서식 미적용 값이 무경고 주입된다(RC-10)
    # — 조용한 추측 대신 시끄럽게 실패한다(확인-또는-경보).
    raise ValueError(f"지원하지 않는 유형: {kind!r} (지원: {TYPES})")


# ------------------------------------------------------------------ 모델
@dataclass
class FieldMapping:
    """한 템플릿 필드를 어떻게 채울지 — 단일 ``source`` 를 ``type`` 으로 서식해 값 생성."""

    template_field: str
    source: str = ""
    type: str = "text"
    const: str = ""
    fmt: str = ""  # 표시형 프리셋 키(유형 내). "" = 기본.

    @property
    def is_blank(self) -> bool:
        """이 항목이 템플릿 필드를 의도적으로 비운다는 명시적 선언인가."""
        return self.type == "blank"

    def value_for(self, record: "dict[str, object]") -> str:
        return apply_transform(
            self.type, str(record.get(self.source, "")), self.const, self.fmt
        )

    def to_dict(self) -> dict:
        return {
            "template_field": self.template_field,
            "source": self.source,
            "type": self.type,
            "const": self.const,
            "fmt": self.fmt,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FieldMapping":
        type_ = d.get("type", "text")
        # 직렬화 경계 검증(RC-10): 손 편집·버전 스큐로 들어온 미지 유형을 조용히
        # 수용하면 뷰 크래시·서식 미적용 값 무경고 주입으로 이어진다 — 로드 시점에
        # 시끄럽게 거부한다(호출자의 '로드 실패' 경로가 수용). ``blank`` 는 명시적
        # 공란 선언의 내부 영속 마커라 허용한다.
        if type_ not in TYPES and type_ != "blank":
            raise ValueError(f"지원하지 않는 유형: {type_!r} (지원: {TYPES})")
        return cls(
            template_field=d["template_field"],
            source=d.get("source", ""),
            type=type_,
            const=d.get("const", ""),
            fmt=d.get("fmt", ""),
        )


@dataclass
class MappingProfile:
    """템플릿+소스에 대한 매핑 프로파일 — 재사용 가능한 영속 산출물."""

    name: str = ""
    mappings: "list[FieldMapping]" = field(default_factory=list)
    # 작성 출처 메타(#53-C) — **순수 설명·추적 메타**. 실행 경로에 무영향(엔진은 mappings 만
    # 소비)이며 실행 게이트는 여전히 라이브 검증(source_report·template_structure_drift)이다.
    # 파일 참조가 유일 실행 의존이 되지 않게, 이건 "어떤 템플릿·데이터 스키마에서 작성됐는가"
    # 를 나중에 되짚는 지문일 뿐이다. 키(모두 선택적 문자열): template·dataset·template_fields·
    # source_keys(스키마 지문, ' · ' 결합)·authored_at·updated_at.
    provenance: "dict[str, str]" = field(default_factory=dict)

    def template_fields(self) -> "list[str]":
        """실제로 값을 방출하는 필드(기존 엔진/ADR-E 계약).

        명시적 공란은 커버에는 속하지만 출력 데이터에는 없어야 한다. 따라서 기존
        호출자가 보던 이 메서드는 값 매핑만 반환하고, 구조 계약에는
        :meth:`cover_fields` 를 사용한다.
        """
        return [m.template_field for m in self.mappings if not m.is_blank]

    def mapped_fields(self) -> "list[str]":
        """값을 채우는 매핑 필드 집합(문서순, 중복 제거)."""
        return list(dict.fromkeys(self.template_fields()))

    def blank_fields(self) -> "list[str]":
        """사람이 명시적으로 '비움'을 선언한 필드 집합."""
        return list(dict.fromkeys(m.template_field for m in self.mappings if m.is_blank))

    def cover_fields(self) -> "list[str]":
        """매핑 계약이 전건 커버하는 필드(``mapped ∪ blank``), 선언순."""
        return list(dict.fromkeys(m.template_field for m in self.mappings))

    def coverage_set(self) -> "set[str]":
        """대칭차 드리프트 평가용 커버 집합."""
        return set(self.cover_fields())

    def coverage_conflicts(self) -> "list[str]":
        """값 매핑과 공란 선언이 동시에 존재하는 모순 필드(선언순)."""
        mapped = set(self.mapped_fields())
        blanks = set(self.blank_fields())
        return [f for f in self.cover_fields() if f in mapped and f in blanks]

    def apply(self, record: "dict[str, object]") -> "dict[str, str]":
        """소스 레코드 1건 → {템플릿필드: 값}. 엔진/배치가 그대로 소비한다.

        명시적 공란은 구조 계약에만 남고 출력 dict 에서는 빠진다. 이는 L1 이전의
        '미매핑 필드는 엔진에 전달하지 않아 누름틀을 그대로 둔다'는 동작을 보존한다.
        """
        return {
            m.template_field: m.value_for(record)
            for m in self.mappings
            if not m.is_blank
        }

    def apply_all(self, records: "list[dict]") -> "list[dict[str, str]]":
        return [self.apply(r) for r in records]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "mappings": [m.to_dict() for m in self.mappings],
            "provenance": dict(self.provenance),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MappingProfile":
        # 가산 필드 provenance(#53-C)는 .get 하위호환(구 JSON→{}) — 존재하는데 dict 가
        # 아니거나 축·값이 str 이 아니면 loud raise(Job.tags 선례, 조용한 오염 금지).
        raw = d.get("provenance", {})
        if not isinstance(raw, dict):
            raise ValueError(
                f"'provenance' 는 사전이어야 하는데 {type(raw).__name__} 입니다"
            )
        provenance: "dict[str, str]" = {}
        for k, v in raw.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ValueError("'provenance' 의 키·값은 모두 문자열이어야 합니다")
            provenance[k] = v
        return cls(
            name=d.get("name", ""),
            mappings=[FieldMapping.from_dict(m) for m in d.get("mappings", [])],
            provenance=provenance,
        )

    def save(self, path: "str | Path") -> None:
        # 원자 쓰기(RC-01) — 저장 중 실패가 기존 프로파일 JSON 을 파괴하지 않는다.
        write_text_atomic(path, json.dumps(self.to_dict(), ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: "str | Path") -> "MappingProfile":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# ------------------------------------------------------------------ 자동 제안
def suggest_mappings(
    template_fields: "list[str]",
    source_keys: "list[str]",
    aliases: "dict[str, str] | None" = None,
    threshold: float = 0.6,
) -> "list[FieldMapping]":
    """템플릿 필드 ↔ 소스 키를 퍼지로 1:1 자동 제안(초안). 사람이 확정·보정한다.

    소스 키가 영문코드면 ``aliases``(키→한글 라벨)를 퍼지 타겟으로 쓴다. 엄격한 1:1
    이므로 초안도 필드당 최선의 단일 소스만 잡고, 유형은 기본 ``text`` — 서식이 필요한
    필드는 사람이 date/amount 로 바꾼다(명시성 원칙).
    """
    aliases = aliases or {}
    labels = {k: aliases.get(k, k) for k in source_keys}
    out: "list[FieldMapping]" = []
    for tf in template_fields:
        best_key, best_score = None, 0.0
        for k in source_keys:
            s = similarity(tf, labels[k])
            if s > best_score:
                best_key, best_score = k, s
        if best_key is not None and best_score >= threshold:
            out.append(FieldMapping(tf, best_key, type="text"))
    return out
