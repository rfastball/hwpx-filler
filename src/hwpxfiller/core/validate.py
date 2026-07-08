"""사전검증 — VBA ``modHWPgen`` 의 헤더 누락/빈 값 검사 포트.

GUI/CLI 가 생성 전에 사용자에게 경고를 띄우기 위한 구조화된 결과를 낸다.
원본의 MsgBox 로직은 표현 계층으로 분리하고, 여기서는 판정만 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ValidationReport:
    # 템플릿이 요구하나 데이터 컬럼(키) 자체가 없는 필드 — 치명적
    missing_columns: "list[str]" = field(default_factory=list)
    # 컬럼은 있으나 선택 레코드 중 빈 값이 하나라도 있는 필드 — 경고
    empty_valued: "list[str]" = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        return bool(self.missing_columns or self.empty_valued)


def validate(required_fields: "list[str]", records: "list[dict]") -> ValidationReport:
    """템플릿 요구 필드 대비 레코드 목록을 검증한다.

    - records: 문서 1건 = dict(필드명 -> 값)
    """
    report = ValidationReport()
    if not records:
        # 데이터가 없으면 모든 요구 필드를 누락으로 본다.
        report.missing_columns = list(required_fields)
        return report

    all_keys: set[str] = set()
    for rec in records:
        all_keys.update(rec.keys())

    for f in required_fields:
        if f not in all_keys:
            report.missing_columns.append(f)
            continue
        for rec in records:
            val = rec.get(f)
            if val is None or str(val).strip() == "":
                report.empty_valued.append(f)
                break
    return report
