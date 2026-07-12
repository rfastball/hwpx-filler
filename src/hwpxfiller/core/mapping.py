"""매핑 계층 — 소스 레코드(DataSource) → 템플릿 필드 값. 취득과 문서생성 사이의 불변 계층.

취득(Excel/API/크롤)이 아무리 좋아져도 "어떤 소스 키를 어떤 템플릿 필드에 어떤 alias·
변환으로 꽂을지"는 사람이 관리한다. 그 결정을 재사용 가능한 영속 산출물(**프로파일**)로
고정한다. 같은 소스 스키마면 프로파일 1회 저작 후 영구 재사용(API/크롤의 결정적 이득).

실데이터(공공 API 등)가 드러낸 3요구를 담는다:
  1. **alias** — 소스 키가 영문코드라 한글 템플릿 필드명과 직접 안 맞음(소스가
     자기 어휘를 ``field_labels()`` 로 선언하면 퍼지 타겟이 된다 — 코어는 어휘-불가지).
  2. **N→1 합성** — 한 템플릿 필드가 여러 소스 키에서(날짜 키 + 시각 키 → 일시 필드).
  3. **값 변환** — 숫자→금액서식, 날짜 결합·서식.

그래서 프로파일은 ``{템플릿필드: {sources:[...], transform}}`` 형태다(단순 1:1 dict 불가).

**명시성 원칙**([[hwpx-filler-scope]]): ``suggest_mappings`` 는 퍼지 초안 제안일 뿐,
사람이 확정·수정한다. 자동으로 몰래 꽂지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import format_engine as _fe
from .lint import similarity

# 소스별 어휘(소스 키 → 한글 라벨)는 **코어가 소유하지 않는다**. 각 DataSource 가
# ``field_labels()`` 로 자기 어휘를 선언하고(예: ``data/nara.py`` 의 나라장터 36쌍),
# GUI 가 선택된 소스의 라벨을 ``suggest_mappings(..., aliases=...)`` 로 주입한다.
# 코어는 어휘-불가지: ``aliases`` 는 아래 서명에서 순수 범용 인자다.

# 지원 변환 종류. 이 중 amount/datetime 은 **결합(N→1) 후 표시형 서식**을 교체 가능한
# core/format_engine 에 위임한다(join/const 는 매핑 고유 결합자).
TRANSFORMS = ("join", "datetime", "amount", "const")


# ------------------------------------------------------------------ 변환
def apply_transform(
    kind: str, values: "list[str]", sep: str = " ", const: str = "", fmt: str = ""
) -> str:
    """소스 값 목록을 결합(N→1)한 뒤, 표시형(``fmt``)에 따라 서식 엔진으로 포맷.

    ``fmt`` 는 변환 안의 표시형 **서식 코드**("" = 기본, 예: ``"{:,}"``·``"%Y-%m-%d"``).
    코드 해석은 교체 가능한 `format_engine` 에 위임한다(현재 stdlib). amount/datetime 만
    표시형을 가지며, 없는 변환에선 ``fmt`` 는 무시된다.
    """
    if kind == "const":
        return const
    parts = [v.strip() for v in values if v and v.strip()]
    if kind == "amount":
        return _fe.render("amount", fmt, "".join(parts))
    if kind == "datetime":
        return _fe.render("datetime", fmt, " ".join(parts))
    # join(기본) — 결합 후 마스크/텍스트 표시형(fmt) 적용(fmt="" 이면 원문).
    return _fe.render("join", fmt, sep.join(parts))


# ------------------------------------------------------------------ 모델
@dataclass
class FieldMapping:
    """한 템플릿 필드를 어떻게 채울지. ``sources`` 를 ``transform`` 으로 합쳐 값 생성."""

    template_field: str
    sources: "list[str]" = field(default_factory=list)
    transform: str = "join"
    sep: str = " "
    const: str = ""
    fmt: str = ""  # 표시형 프리셋 키(변환 내). "" = 기본(하위호환).

    def value_for(self, record: "dict[str, object]") -> str:
        values = [str(record.get(s, "")) for s in self.sources]
        return apply_transform(self.transform, values, self.sep, self.const, self.fmt)

    def to_dict(self) -> dict:
        return {
            "template_field": self.template_field,
            "sources": list(self.sources),
            "transform": self.transform,
            "sep": self.sep,
            "const": self.const,
            "fmt": self.fmt,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "FieldMapping":
        return cls(
            template_field=d["template_field"],
            sources=list(d.get("sources", [])),
            transform=d.get("transform", "join"),
            sep=d.get("sep", " "),
            const=d.get("const", ""),
            fmt=d.get("fmt", ""),  # 구 프로파일엔 없을 수 있음 → 기본
        )


@dataclass
class MappingProfile:
    """템플릿+소스에 대한 매핑 프로파일 — 재사용 가능한 영속 산출물."""

    name: str = ""
    mappings: "list[FieldMapping]" = field(default_factory=list)

    def template_fields(self) -> "list[str]":
        return [m.template_field for m in self.mappings]

    def apply(self, record: "dict[str, object]") -> "dict[str, str]":
        """소스 레코드 1건 → {템플릿필드: 값}. 엔진/배치가 그대로 소비한다."""
        return {m.template_field: m.value_for(record) for m in self.mappings}

    def apply_all(self, records: "list[dict]") -> "list[dict[str, str]]":
        return [self.apply(r) for r in records]

    def to_dict(self) -> dict:
        return {"name": self.name, "mappings": [m.to_dict() for m in self.mappings]}

    @classmethod
    def from_dict(cls, d: dict) -> "MappingProfile":
        return cls(
            name=d.get("name", ""),
            mappings=[FieldMapping.from_dict(m) for m in d.get("mappings", [])],
        )

    def save(self, path: "str | Path") -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

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

    소스 키가 영문코드면 ``aliases``(키→한글 라벨)를 퍼지 타겟으로 쓴다. N→1 합성(일시 등)
    은 초안에서 1:1 로만 잡고, 나머지 소스는 사람이 덧붙인다(명시성 원칙).
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
            out.append(FieldMapping(tf, [best_key], transform="join"))
    return out
