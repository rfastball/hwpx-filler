"""소스 프로파일링 — 매핑이 읽을 소스 키의 **실제형 관측**(ADR L 축2).

헤더 이름만 보고 매핑하면 "날짜인 줄 알았는데 일시였다" 류의 형태 착오가 생성까지
조용히 통과한다. 여기서는 샘플 몇 건과 **잠정** 타입 라벨을 관측해 dry-run 매니페스트에
싣는다. 라벨은 서술적 *추정*이지 주장이 아니다 — 전 샘플이 한 패턴에 들어맞지 않으면
빈 문자열로 degrade 해 **샘플만** 남긴다(조용한 오판 금지, [[confirm-or-alarm-principle]]).
변환·검증 어디에도 이 라벨을 강제로 쓰지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: 기본 샘플 수 — 원장은 증거의 창이지 데이터 사본이 아니다(작게 유지).
SAMPLE_N = 3

# 잠정 타입 패턴(순서 = 구체성 우선). 전 샘플 일치일 때만 라벨을 낸다.
# 날짜형은 월·일·시각 범위까지 맞아야 한다 — 8·12자리 수(금액 등)를 날짜로
# 오추정하는 것보다 정수로 낮춰 부르는 쪽이 원장의 정직성에 맞다.
_MMDD = r"(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])"
_PATTERNS: "tuple[tuple[str, re.Pattern[str]], ...]" = (
    ("일시(YYYYMMDDHHMM 추정)", re.compile(r"^\d{4}" + _MMDD + r"([01]\d|2[0-3])[0-5]\d$")),
    ("날짜(YYYYMMDD 추정)", re.compile(r"^\d{4}" + _MMDD + r"$")),
    ("날짜(YYYY-MM-DD 추정)", re.compile(r"^\d{4}-\d{2}-\d{2}$")),
    ("금액(천단위 콤마 추정)", re.compile(r"^-?\d{1,3}(,\d{3})+$")),
    ("정수(추정)", re.compile(r"^-?\d+$")),
    ("숫자(추정)", re.compile(r"^-?\d+\.\d+$")),
    ("URL(추정)", re.compile(r"^https?://\S+$")),
)


@dataclass(frozen=True)
class FieldProfile:
    """소스 키 1개의 관측 결과 — 라벨(소스 어휘)·샘플·잠정 타입."""

    key: str
    label: str = ""                      # 소스가 선언한 사람 라벨(없으면 "")
    samples: "tuple[str, ...]" = ()      # 비어있지 않은 실값 샘플(중복 제거, 소수)
    tentative_type: str = ""             # ""=모름 — 샘플만 제시(추정 라벨, 주장 아님)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "samples": list(self.samples),
            "tentative_type": self.tentative_type,
        }


def tentative_type(values: "list[str]") -> str:
    """전 샘플이 단일 패턴에 들어맞을 때만 잠정 라벨. 혼재·빈 입력은 ""(degrade)."""
    vals = [v for v in (str(v).strip() for v in values) if v]
    if not vals:
        return ""
    for label, pattern in _PATTERNS:
        if all(pattern.match(v) for v in vals):
            return label
    return ""


def profile_fields(
    records: "list[dict]",
    keys: "list[str] | None" = None,
    *,
    labels: "dict[str, str] | None" = None,
    sample_n: int = SAMPLE_N,
) -> "list[FieldProfile]":
    """레코드 목록에서 키별 프로파일을 관측한다.

    ``keys`` 를 주면 그 키만(예: 매핑이 읽는 소스 키), 없으면 레코드 등장순 전체.
    ``labels`` 는 소스가 소유한 어휘(:meth:`DataSource.field_labels`)를 그대로 받는다.
    """
    labels = labels or {}
    if keys is None:
        seen: "dict[str, None]" = {}
        for rec in records:
            for k in rec:
                seen.setdefault(k)
        keys = list(seen)
    profiles: "list[FieldProfile]" = []
    for key in keys:
        non_empty = [
            v for v in (str(rec.get(key, "")).strip() for rec in records) if v
        ]
        samples = tuple(dict.fromkeys(non_empty))[:sample_n]
        profiles.append(
            FieldProfile(key, labels.get(key, ""), samples, tentative_type(non_empty))
        )
    return profiles
