"""템플릿 관리 — lint(단일 템플릿 위생) + 필드 드리프트(판본 간 필드셋 변화).

저작 보조의 관리 절반. 프리미티브는 이미 있다: ``schema``(필드·타입)·``authoring``
(미치환 토큰)·``difflib``(퍼지). 여기서 작성자가 놓치기 쉬운 것들을 모아 신고한다:

- **유사 중복 필드명** — ``계약명`` vs ``계약 명`` 같은 공백/오타 변이(VBA modFuzzyMatch 역할).
- **미치환 토큰** — 아직 누름틀이 안 된 평문 ``{{X}}``(fieldize 권장) + 파편 토큰.
- **표준 어휘 밖 필드명**(선택) — 통제 어휘 사전을 주면 벗어난 이름 + 가장 가까운 표준 제안.

**필드 드리프트** — 템플릿이 연례 개정으로 재발행될 때 필드가 추가/삭제/개명됐는지.
``diff.py``(본문 내용 diff)와 다른 결: 필드셋 수준 비교라 관리에 적합. 개명은 삭제된
필드와 추가된 필드를 퍼지 매칭해 추정한다(삭제+추가 오인 방지).

의존: ``schema``·``authoring`` + stdlib ``difflib``(새 의존성 없음).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .authoring import scan_tokens
from .schema import extract_schema
from hwpxcore.text_extract import _to_package

_WS_RE = re.compile(r"\s+")
# 유사도 임계값 — 이 이상이면 near-duplicate/개명 후보로 본다.
# 실코퍼스 검증: 접미사 공유 필드(입찰개시일시/입찰마감일시 등)는 ~0.67 로 안 걸린다.
_SIMILARITY_THRESHOLD = 0.8


def _normalize(name: str) -> str:
    """비교용 정규화 — 모든 공백 제거(공백 변이를 동일시)."""
    return _WS_RE.sub("", name)


def similarity(a: str, b: str) -> float:
    """두 필드명의 유사도 0..1. 정규화 후 동일하면 1.0, 아니면 문자 시퀀스 비율."""
    na, nb = _normalize(a), _normalize(b)
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


# ------------------------------------------------------------------ lint 모델
@dataclass
class LintFinding:
    """lint 소견 하나. ``kind`` 는 분류, ``fields`` 는 관련 필드/토큰 이름."""

    kind: str  # near_duplicate | stray_token | split_token | off_vocabulary | no_fields
    severity: str  # warning | info
    message: str
    fields: "list[str]" = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
            "fields": list(self.fields),
        }


@dataclass
class LintReport:
    findings: "list[LintFinding]" = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        return any(f.severity == "warning" for f in self.findings)

    def to_dict(self) -> dict:
        return {"findings": [f.to_dict() for f in self.findings]}


def _near_duplicate_pairs(names: "list[str]") -> "list[tuple[str, str]]":
    """정규화(공백 제거) 후 동일한 서로 다른 필드명 쌍 — 공백/표기 변이.

    퍼지 비율(SequenceMatcher)은 ``세부품명`` vs ``세부품명번호`` 같은 부분 문자열
    관계(정당하게 구분되는 별개 필드)를 오탐하므로 lint 중복 판정엔 쓰지 않는다.
    정규화-동일만이 '같은 필드를 다르게 표기'한 고신뢰 신호다. 퍼지 비율은 개명
    추정(drift)·어휘 제안에만 쓴다(거기선 후보가 이미 별개임이 보장됨).
    """
    pairs: "list[tuple[str, str]]" = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            if a != b and _normalize(a) == _normalize(b):
                pairs.append((a, b))
    return pairs


def lint_template(
    pkg_or_path: object,
    vocabulary: "list[str] | set[str] | None" = None,
    threshold: float = _SIMILARITY_THRESHOLD,
) -> LintReport:
    """단일 템플릿 위생 점검. 워크북을 변형하지 않는다(읽기 전용)."""
    pkg = _to_package(pkg_or_path)  # 한 번만 열어 schema/scan 에 공유
    schema = extract_schema(pkg)
    names = schema.field_names()
    findings: "list[LintFinding]" = []

    if not names:
        findings.append(
            LintFinding("no_fields", "warning", "템플릿에 누름틀 필드가 없습니다.", [])
        )

    for a, b in _near_duplicate_pairs(names):
        findings.append(
            LintFinding(
                "near_duplicate",
                "warning",
                f"공백/표기만 다른 필드명: '{a}' vs '{b}'",
                [a, b],
            )
        )

    # 미치환 토큰 — authoring.scan_tokens 가 단일 진실원(fieldize 대상과 정확히 일치).
    for site in scan_tokens(pkg):
        if site.compilable:
            findings.append(
                LintFinding(
                    "stray_token",
                    "warning",
                    f"미치환 토큰(fieldize 가능): {{{{{site.name}}}}}",
                    [site.name],
                )
            )
        else:
            findings.append(
                LintFinding(
                    "split_token",
                    "warning",
                    f"수동 처리 필요 토큰: {site.name} — {site.reason}",
                    [site.name],
                )
            )

    if vocabulary:
        vocab = list(vocabulary)
        vocab_set = set(vocab)
        for n in names:
            if n in vocab_set:
                continue
            best = max(vocab, key=lambda v: similarity(n, v), default=None)
            hint = ""
            if best is not None and similarity(n, best) >= threshold:
                hint = f" (가까운 표준: '{best}')"
            findings.append(
                LintFinding(
                    "off_vocabulary", "warning", f"표준 어휘 밖 필드명: '{n}'{hint}", [n]
                )
            )

    return LintReport(findings)


# ------------------------------------------------------------- 필드 드리프트
@dataclass
class SchemaDrift:
    """판본 간 필드셋 변화. 개명은 삭제↔추가 퍼지 매칭으로 추정해 순수 추가/삭제와 분리."""

    added: "list[str]" = field(default_factory=list)
    removed: "list[str]" = field(default_factory=list)
    renamed: "list[dict]" = field(default_factory=list)  # {old, new, score}

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.renamed)

    def to_dict(self) -> dict:
        return {
            "added": list(self.added),
            "removed": list(self.removed),
            "renamed": [dict(r) for r in self.renamed],
        }


def diff_schema(
    old_pkg_or_path: object,
    new_pkg_or_path: object,
    threshold: float = _SIMILARITY_THRESHOLD,
) -> SchemaDrift:
    """두 템플릿의 필드셋을 비교해 추가/삭제/개명(추정)을 낸다."""
    old_names = extract_schema(old_pkg_or_path).field_names()
    new_names = extract_schema(new_pkg_or_path).field_names()
    old_set, new_set = set(old_names), set(new_names)

    added = [n for n in new_names if n not in old_set]
    removed = [n for n in old_names if n not in new_set]

    # 개명 추정: 삭제된 필드마다 가장 유사한(미사용) 추가 필드를 짝짓는다.
    renamed: "list[dict]" = []
    used_new: "set[str]" = set()
    for r in removed:
        best, best_score = None, 0.0
        for a in added:
            if a in used_new:
                continue
            s = similarity(r, a)
            if s > best_score:
                best, best_score = a, s
        if best is not None and best_score >= threshold:
            renamed.append({"old": r, "new": best, "score": round(best_score, 3)})
            used_new.add(best)

    ren_old = {x["old"] for x in renamed}
    ren_new = {x["new"] for x in renamed}
    added = [a for a in added if a not in ren_new]
    removed = [r for r in removed if r not in ren_old]
    return SchemaDrift(added=added, removed=removed, renamed=renamed)
