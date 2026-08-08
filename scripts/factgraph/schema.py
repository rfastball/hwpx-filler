"""Fact Graph 공용 스키마 — stable symbol ID·fact·shard·merge·digest 계약.

P1(#511) 전수 계측이 공유하는 **어휘의 단일 출처**다. relation·증거 등급을 여기 등록하지
않고 쓰면 생성 시점에 시끄럽게 죽는다 — 오타난 어휘가 shard 에 조용히 섞여 중앙 합성
(P1-03)에서야 드러나는 길을 막는다(#512 불변식). 어휘 확장은 이 모듈의 변경으로만 한다.

설계 결정(#512 P-DESIGN-PACKET:v1):

- symbol identity 는 ``module:qualname#kind`` 다. 줄 번호는 identity 가 아니라 증거
  위치다 — 무관한 편집으로 줄이 밀려도 심볼은 같은 심볼이다.
- fact 는 증거 단위다. 같은 edge(src, rel, dst)에 증거가 여럿 설 수 있고, 정적·런타임
  증거가 둘 다 서면 edge 의 유효 등급이 ``STATIC_AND_RUNTIME_CONFIRMED`` 로 승급한다.
- shard 는 기준 SHA 의 측정 스냅숏이라 ``baseline_sha`` 를 품는다. 기준이 다른 shard 를
  섞는 merge 는 오류다 — 판정 대상이 다른 사실들의 조용한 혼합을 막는다.

fact 의 ``dst`` 문법(해석 결과를 형태로 드러낸다 — 미해결을 해석 완료처럼 적지 않는다):

- symbol ID ``module:qualname#kind`` — 폐포 안에서 해석 완료
- ``ext:<dotted>`` — 폐포 밖(표준 라이브러리·서드파티) 참조, 해석은 완료
- ``?:<범주>:<좌표>`` — 미해결. 범주는 수집기 규칙이 정하며 provenance 와 함께 남는다
- ``attr:<소유자>.<이름>`` — 심볼이 아닌 속성 좌표(인스턴스 필드·모듈 전역)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field

SCHEMA_VERSION = "factgraph/v1"

SYMBOL_KINDS: tuple[str, ...] = ("module", "class", "function", "method")

#: 기반 수집기(P1-01)가 방출하는 relation 전부. P1-02B~E 의 축(상태·효과·전송 등)은
#: 그 단계가 이 튜플을 **여기서** 확장한다 — shard 별 사설 어휘는 merge 가 거절한다.
RELATIONS: tuple[str, ...] = (
    "imports_module",
    "imports_symbol",
    "calls",
    "constructs",
    "writes_attribute",
    "reads_attribute",
    "dynamic_site",
)

#: 증거 등급 6종(#512). 정적 그래프에 없는 edge 를 곧바로 '없음'으로 판정하지 않기 위한
#: 어휘다 — 미해결은 UNKNOWN 으로, 코드가 스스로 동적임을 선언한 자리는 DECLARED_DYNAMIC
#: 으로 남는다.
GRADES: tuple[str, ...] = (
    "STATIC_CONFIRMED",
    "RUNTIME_CONFIRMED",
    "STATIC_AND_RUNTIME_CONFIRMED",
    "DECLARED_DYNAMIC",
    "INFERRED",
    "UNKNOWN",
)

_REF_PREFIXES = ("ext:", "?:", "attr:")


class FactGraphError(ValueError):
    """스키마 계약 위반 — 미등록 어휘·기준 불일치·형식 오류는 조용히 넘어가지 않는다."""


def symbol_id(module: str, qualname: str, kind: str) -> str:
    """``module:qualname#kind`` — 모듈 심볼은 qualname 이 빈 문자열이다."""
    if kind not in SYMBOL_KINDS:
        raise FactGraphError(f"미등록 symbol kind: {kind!r} (등록: {SYMBOL_KINDS})")
    if not module:
        raise FactGraphError("symbol ID 의 module 이 비었다")
    return f"{module}:{qualname}#{kind}"


def parse_symbol_id(sid: str) -> tuple[str, str, str]:
    """symbol ID 를 (module, qualname, kind) 로 되읽는다 — 독립 오러클용 역함수."""
    head, sep, kind = sid.rpartition("#")
    if not sep or kind not in SYMBOL_KINDS:
        raise FactGraphError(f"symbol ID 형식이 아니다: {sid!r}")
    module, sep, qualname = head.partition(":")
    if not sep or not module:
        raise FactGraphError(f"symbol ID 형식이 아니다: {sid!r}")
    return module, qualname, kind


def is_symbol_ref(dst: str) -> bool:
    """dst 가 폐포 안 symbol ID 인가(ext:/?:/attr: 참조가 아닌가) — 실제 파싱으로 판정한다.

    ``#`` 존재만 보면 ``garbage#junk`` 같은 오타가 shard 에 조용히 섞인다 — 형식 주장은
    역함수(parse)가 실제로 받아들이는지로만 성립한다.
    """
    if dst.startswith(_REF_PREFIXES):
        return False
    try:
        parse_symbol_id(dst)
    except FactGraphError:
        return False
    return True


@dataclass(frozen=True)
class Symbol:
    """폐포 안 심볼 하나. ``file``/``line`` 은 증거 위치일 뿐 identity 가 아니다."""

    module: str
    qualname: str  # 모듈 심볼은 ""
    kind: str
    file: str  # 저장소 상대 posix 경로
    line: int

    def __post_init__(self) -> None:
        if self.kind not in SYMBOL_KINDS:
            raise FactGraphError(f"미등록 symbol kind: {self.kind!r}")

    @property
    def id(self) -> str:
        return symbol_id(self.module, self.qualname, self.kind)


@dataclass(frozen=True)
class Evidence:
    """사실의 좌표. anchor 는 진단용 원문 조각(선택)이다."""

    file: str
    line: int
    anchor: str = ""

    def __post_init__(self) -> None:
        if not self.file:
            raise FactGraphError("evidence.file 이 비었다")
        if self.line < 0:
            raise FactGraphError(f"evidence.line 이 음수다: {self.line}")


@dataclass(frozen=True)
class Provenance:
    """이 사실을 누가 어떤 규칙으로 냈는가 — 미해결·동적 표기의 후속 확인 경로."""

    collector: str
    rule: str

    def __post_init__(self) -> None:
        if not self.collector or not self.rule:
            raise FactGraphError("provenance 의 collector/rule 은 비울 수 없다")


@dataclass(frozen=True)
class Fact:
    src: str  # symbol ID
    rel: str
    dst: str
    grade: str
    evidence: Evidence
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.rel not in RELATIONS:
            raise FactGraphError(f"미등록 relation: {self.rel!r} (등록: {RELATIONS})")
        if self.grade not in GRADES:
            raise FactGraphError(f"미등록 grade: {self.grade!r} (등록: {GRADES})")
        if not is_symbol_ref(self.src):
            raise FactGraphError(f"fact.src 는 유효한 symbol ID 여야 한다: {self.src!r}")
        if not self.dst:
            raise FactGraphError("fact.dst 가 비었다")
        if not (self.dst.startswith(_REF_PREFIXES) or is_symbol_ref(self.dst)):
            raise FactGraphError(f"fact.dst 문법이 아니다: {self.dst!r}")

    def sort_key(self) -> tuple:
        return (
            self.src,
            self.rel,
            self.dst,
            self.grade,
            self.evidence.file,
            self.evidence.line,
            self.evidence.anchor,
            self.provenance.collector,
            self.provenance.rule,
        )


@dataclass(frozen=True)
class Shard:
    """한 계측 축의 산출 단위. ``make_shard`` 로만 만든다(정렬·중복 제거·검증)."""

    shard_id: str
    producer: str
    baseline_sha: str
    symbols: tuple[str, ...]
    facts: tuple[Fact, ...] = field(repr=False)

    @property
    def digest(self) -> str:
        return _digest(
            {
                "schema": SCHEMA_VERSION,
                "shard_id": self.shard_id,
                "producer": self.producer,
                "baseline_sha": self.baseline_sha,
                "symbols": list(self.symbols),
                "facts": [asdict(f) for f in self.facts],
            }
        )


def make_shard(
    shard_id: str,
    producer: str,
    baseline_sha: str,
    symbols: "list[str] | tuple[str, ...]",
    facts: "list[Fact] | tuple[Fact, ...]",
) -> Shard:
    if not shard_id or not producer or not baseline_sha:
        raise FactGraphError("shard_id/producer/baseline_sha 는 비울 수 없다")
    for sid in symbols:
        parse_symbol_id(sid)  # 형식 위반이면 여기서 죽는다
    ordered_symbols = tuple(sorted(set(symbols)))
    ordered_facts = tuple(sorted(set(facts), key=Fact.sort_key))
    return Shard(shard_id, producer, baseline_sha, ordered_symbols, ordered_facts)


@dataclass(frozen=True)
class MergedGraph:
    baseline_sha: str
    symbols: tuple[str, ...]
    facts: tuple[Fact, ...] = field(repr=False)

    @property
    def digest(self) -> str:
        return _digest(
            {
                "schema": SCHEMA_VERSION,
                "baseline_sha": self.baseline_sha,
                "symbols": list(self.symbols),
                "facts": [asdict(f) for f in self.facts],
            }
        )


def merge_shards(shards: "list[Shard] | tuple[Shard, ...]") -> MergedGraph:
    """결정론 merge — 정렬·중복 제거. 기준 SHA 가 갈리면 시끄럽게 거절한다."""
    if not shards:
        raise FactGraphError("merge 할 shard 가 없다")
    baselines = sorted({s.baseline_sha for s in shards})
    if len(baselines) != 1:
        raise FactGraphError(f"baseline_sha 가 갈린 shard 를 merge 할 수 없다: {baselines}")
    symbols = tuple(sorted({sid for s in shards for sid in s.symbols}))
    facts = tuple(sorted({f for s in shards for f in s.facts}, key=Fact.sort_key))
    return MergedGraph(baselines[0], symbols, facts)


def edge_grades(facts: "tuple[Fact, ...] | list[Fact]") -> "dict[tuple[str, str, str], str]":
    """edge(src, rel, dst)별 유효 등급 — 정적+런타임 증거가 둘 다 서면 승급한다."""
    grouped: dict[tuple[str, str, str], set[str]] = {}
    for f in facts:
        grouped.setdefault((f.src, f.rel, f.dst), set()).add(f.grade)
    out: dict[tuple[str, str, str], str] = {}
    for edge, grades in grouped.items():
        if "STATIC_AND_RUNTIME_CONFIRMED" in grades or (
            "STATIC_CONFIRMED" in grades and "RUNTIME_CONFIRMED" in grades
        ):
            out[edge] = "STATIC_AND_RUNTIME_CONFIRMED"
        else:
            # 앞선 등급이 더 강하다 — GRADES 등록 순서가 곧 우선순위다.
            out[edge] = next(g for g in GRADES if g in grades)
    return out


def _digest(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
