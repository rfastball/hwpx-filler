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

from dataclasses import dataclass, field
from datetime import datetime

from . import format_engine as _fe
from .lint import similarity

# 소스별 어휘(소스 키 → 한글 라벨)는 **코어가 소유하지 않는다**. 각 DataSource 가
# ``field_labels()`` 로 자기 어휘를 선언하고(예: ``data/nara.py`` 의 나라장터 36쌍),
# GUI 가 선택된 소스의 라벨을 ``suggest_mappings(..., aliases=...)`` 로 주입한다.
# 코어는 어휘-불가지: ``aliases`` 는 아래 서명에서 순수 범용 인자다.

# 지원 값 유형. text/date/amount 는 단일 소스 값의 표시형 서식을 교체 가능한
# domain/format_engine 에 위임하고, const 는 소스와 무관한 리터럴이다. ``today`` 는
# 데이터 열 없이 **실행 시각의 날짜**를 내는 시스템 토큰(U4-E1 #939)이고 표시형은
# ``date`` 와 **같은 어휘**를 쓴다(:func:`apply_transform` 이 date 로 렌더).
# 「비워 둠」 표시형(옛 ``blank``)은 퇴역했다 — 비우려는 필드는 ``const`` 에 빈 문자열을
# 적는 것으로 표현하고, 그 자리는 누름틀을 건드리지 않는 대신 **빈 문자열을 써 넣는다**.
TYPES = ("text", "date", "amount", "const", "today")

# 원본 소스 값을 **나르지 않는** 유형 — 값이 ``source`` 와 무관하다. ``const`` 는 리터럴을,
# ``today`` 는 실행 시각을 방출한다(:func:`apply_transform` 의 분기와 일치). 부정 조건을
# 하드코딩(``t != "const"``)하면 새 비-carrier 유형이 조용히 carrier 로 분류되므로 **명시
# 열거**한다.
_NON_CARRIER_TYPES = ("const", "today")

# 원본 소스 값을 실제로 나르는 유형. '파일명이 이 열을 나르는가'(식별 요약 토큰 모드 등)를
# 묻는 곳의 단일 출처 — 화이트리스트를 곳곳에 재적지 않는다.
SOURCE_CARRIER_TYPES = tuple(t for t in TYPES if t not in _NON_CARRIER_TYPES)


# ------------------------------------------------------------------ 변환
def apply_transform(
    kind: str, value: str = "", const: str = "", fmt: str = "",
    *, now: "datetime | None" = None,
) -> str:
    """단일 소스 값을 유형(``kind``)·표시형(``fmt``)에 따라 서식 엔진으로 포맷.

    ``fmt`` 는 유형 안의 표시형 **서식 코드**("" = 기본, 예: ``"{:,}"``·``"%Y-%m-%d"``).
    코드 해석은 교체 가능한 `format_engine` 에 위임한다(현재 stdlib). text/date/amount/today
    가 표시형을 가지며, const 는 리터럴을 낸다(빈 리터럴이면 빈 문자열).

    ``now`` 는 ``today`` 의 기준 시각이다. ``None`` 이면 ``datetime.now()`` 로 폴백한다
    (선례: :func:`~hwpxfiller.application.generation.direct_plan` 의 "now=None 은 생성
    시각"). 파일명 날짜 토큰과 **같은 값**을 넘겨야 확인 대상과 생성 대상이 하위-일
    경계에서 갈라지지 않는다(RC-02).
    """
    if kind == "const":
        return const
    if kind == "today":
        # date 의 서식 어휘·프리셋을 **무손실 재사용**한다(U4 §2.14 판정 1): 직렬화한
        # ``%Y-%m-%d %H:%M`` 를 `format_engine.parse_dt` 가 연·월·일·시·분 전부 되읽으므로
        # date 프리셋 9개가 그대로 성립한다. 새 서식 표를 만들면 두 벌이 갈린다.
        return _fe.render("date", fmt, (now or datetime.now()).strftime("%Y-%m-%d %H:%M"))
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
    def is_declared_empty(self) -> bool:
        """이 항목이 템플릿 필드를 **빈 문자열로 채운다**는 명시적 선언인가.

        옛 ``blank`` 유형(누름틀을 손대지 않는 키 누락)의 후계다. 비우려는 필드는
        「직접 입력(고정값)에 아무것도 적지 않는다」로 표현하고, 그 결과는 누름틀에
        빈 문자열이 실제로 써지는 것이다(S5 ``EXACT_BLANK_POLICY`` 와 같은 의미).
        """
        return self.type == "const" and self.const == ""

    def value_for(
        self, record: "dict[str, object]", *, now: "datetime | None" = None
    ) -> str:
        return apply_transform(
            self.type, str(record.get(self.source, "")), self.const, self.fmt, now=now
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
        """읽기 시점 마이그레이션: 옛 ``blank`` 유형은 빈 ``const`` 로 도착한다.

        디스크에 남은 옛 저장물(``type="blank"``)을 거부하면 그 작업을 열 수 없어진다 —
        이미 사람이 「이 필드는 비운다」고 확정한 선언이므로 같은 뜻의 현행 표현(빈 고정값)
        으로 옮겨 읽는다. 그 밖의 미지 유형은 여전히 시끄럽게 거부한다.
        """
        type_ = d.get("type", "text")
        if type_ == "blank":
            return cls(template_field=d["template_field"], type="const")
        # 직렬화 경계 검증(RC-10): 손 편집·버전 스큐로 들어온 미지 유형을 조용히
        # 수용하면 뷰 크래시·서식 미적용 값 무경고 주입으로 이어진다 — 로드 시점에
        # 시끄럽게 거부한다(호출자의 '로드 실패' 경로가 수용).
        if type_ not in TYPES:
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
        """**빈 값 검사가 요구하는** 필드(기존 엔진/ADR-E 계약).

        명시적 빈 고정값은 커버에는 속하지만 여기 들지 않는다 — 사람이 「이 필드는
        비운다」고 이미 답한 자리라 미입력·빈 값 경고의 대상이 아니다(데이터 구멍이
        아니다). 구조 계약에는 :meth:`cover_fields` 를 사용한다.
        """
        return [m.template_field for m in self.mappings if not m.is_declared_empty]

    def mapped_fields(self) -> "list[str]":
        """값을 채우는 매핑 필드 집합(문서순, 중복 제거)."""
        return list(dict.fromkeys(self.template_fields()))

    def declared_empty_fields(self) -> "list[str]":
        """사람이 명시적으로 '비움'(빈 고정값)을 선언한 필드 집합."""
        return list(
            dict.fromkeys(m.template_field for m in self.mappings if m.is_declared_empty)
        )

    def cover_fields(self) -> "list[str]":
        """매핑 계약이 전건 커버하는 필드, 선언순."""
        return list(dict.fromkeys(m.template_field for m in self.mappings))

    def coverage_set(self) -> "set[str]":
        """대칭차 드리프트 평가용 커버 집합."""
        return set(self.cover_fields())

    def coverage_conflicts(self) -> "list[str]":
        """한 필드를 두 항목이 겹쳐 선언한 모순 필드(선언순).

        1:1 계약이므로 같은 템플릿 필드에 매핑이 둘 이상이면 어느 쪽이 이기는지가
        선언에 없다 — 조용한 추측 대신 드리프트로 세운다.
        """
        seen: "dict[str, int]" = {}
        for m in self.mappings:
            seen[m.template_field] = seen.get(m.template_field, 0) + 1
        return [f for f in self.cover_fields() if seen[f] > 1]

    def apply(
        self, record: "dict[str, object]", *, now: "datetime | None" = None
    ) -> "dict[str, str]":
        """소스 레코드 1건 → {템플릿필드: 값}. 엔진/배치가 그대로 소비한다.

        **어떤 항목도 빠지지 않는다.** 명시적 빈 고정값도 키를 남겨 빈 문자열을 내므로
        누름틀에 빈 문자열이 실제로 써진다 — 「비우겠다」는 선언이 누름틀을 손대지 않는
        누락으로 새지 않는다.

        ``now`` 는 ``today`` 유형의 기준 시각(:func:`apply_transform`) — 호출측이 파일명
        날짜 토큰과 같은 값을 관통시킨다(RC-02).
        """
        return {
            m.template_field: m.value_for(record, now=now)
            for m in self.mappings
        }

    def apply_all(
        self, records: "list[dict]", *, now: "datetime | None" = None
    ) -> "list[dict[str, str]]":
        """배치 적용. ``now`` 는 **전 레코드가 공유**한다 — 레코드마다 다시 찍으면 한 배치
        안에서 「오늘 날짜」가 하위-일 경계를 넘어 갈린다."""
        return [self.apply(r, now=now) for r in records]

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

    # (save 는 P2-18(#566)에서 External 로 승계 —
    #  :func:`hwpxfiller.external.mapping_store.save_mapping_profile`.)

# ------------------------------------------------------------------ 자동 제안
# 퍼지 1:1 제안의 채택 임계. **반증 코퍼스로 캘리브레이션한 값**이지 감이 아니다(#908).
#
# 옛 값 0.6 은 의미 축이 다른 공유-접두 쌍을 통과시켰다: ``계약보증금`` ↔ ``계약금액``
# = 0.6667(정규화 후 공통 블록 '계약'+'금' 3자, 2*3/(5+4)). 보증금 자리에 계약금액이
# 꽂힌 초안은 법적 문서에서 위험한 오답이고, 「모두 확정」의 습관화가 그걸 실어 나른다
# (ADR E 습관화 논지). 그래서 임계는 그 근접쌍 **위**에 선다.
#
# 반대편 하한은 정당한 표기 변형이 정한다. ``similarity`` 가 공백을 먼저 지우므로
# 띄어쓰기·앞뒤 공백 변형(``공고 번호`` ↔ ``공고번호``)은 1.0 이고, 언더스코어는
# 0.8889(``계약_금액`` ↔ ``계약금액`` = 2*4/9), 괄호 단위는 0.7273
# (``추정가격(원)`` ↔ ``추정가격`` = 2*4/(7+4))이 최저다.
#
#   위험 근접쌍 최대 0.6667  <  0.7  <=  정당 변형 최소 0.7273
#
# 두 집합 사이 간극 0.0606 의 거의 중점(0.697)에 가장 가까운 값이라 양쪽 여유가
# 균형을 이룬다(아래 0.0333 · 위 0.0273). 0.72 는 괄호 단위 위로 0.0073 밖에 못 남겨
# 부동소수 한 올 차이로 그 류 전체를 잃는다.
#
# **단일 임계가 감당 못 하는 자리**: 괄호 주석이 어간만큼 긴 변형(``계약상대자(업체명)``
# ↔ ``계약상대자`` = 0.6667, ``계약금액(백만원)`` ↔ ``계약금액`` = 0.6154)은 길이비
# 인공물이라 위험 근접쌍과 **같은 구간에 겹친다**. 어떤 임계로도 안 갈리므로 이건
# 임계가 아니라 매칭 설계의 한계다. 옛 0.6 에서 그 류가 살아 있던 것은 우연이고,
# 그때도 ``계약보증금``→``계약금액`` 이 더 높은 점수로 앞섰다. 지금 계약은 제안이
# 없으면 행이 비어 사람이 채우거나 비움 확정하는 것이라, 놓친 변형은 조용히 틀리는
# 대신 시끄럽게 빈다. 코퍼스 정본은 ``tests/test_mapping.py`` 의 캘리브레이션 절이다.
SUGGEST_THRESHOLD = 0.7


def suggest_mappings(
    template_fields: "list[str]",
    source_keys: "list[str]",
    aliases: "dict[str, str] | None" = None,
    threshold: float = SUGGEST_THRESHOLD,
) -> "list[FieldMapping]":
    """템플릿 필드 ↔ 소스 키를 퍼지로 1:1 자동 제안(초안). 사람이 확정·보정한다.

    소스 키가 영문코드면 ``aliases``(키→한글 라벨)를 퍼지 타겟으로 쓴다. 엄격한 1:1
    이므로 초안도 필드당 최선의 단일 소스만 잡고, 유형은 기본 ``text`` — 서식이 필요한
    필드는 사람이 date/amount 로 바꾼다(명시성 원칙).

    ``threshold`` 기본값은 :data:`SUGGEST_THRESHOLD` 이고, 그 위 주석이 왜 그 값인지의
    산술을 진다. 낮춰 부르면 위험 근접쌍이 되살아나므로 호출측이 임의로 완화하지 않는다.
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
