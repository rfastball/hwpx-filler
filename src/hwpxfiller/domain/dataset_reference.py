"""데이터셋 참조의 순수 값·수명·정체성 규칙.

파일 레지스트리와 JSON byte I/O는 External Adapter인
``hwpxfiller.core.dataset_pool``이 소유한다. 이 모듈은 레코드나 비밀값이 아닌
소스 재연결 정보와 active/archived 수명만 표현한다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self


STATUS_ACTIVE = "active"
STATUS_ARCHIVED = "archived"
_STATUSES = (STATUS_ACTIVE, STATUS_ARCHIVED)

# 구 ``.dataset.json`` 읽기 호환 전용. 새 값으로는 생성·저장하지 않는다.
STATUS_RETIRED = "retired"
_LEGACY_STATUS_ALIASES = {STATUS_RETIRED: STATUS_ARCHIVED}


def excel_identity(path: "str | Path", sheet: "str | None" = "") -> str:
    """엑셀/CSV 참조 정체성: 정규화 절대 경로 + 확정 시트."""
    return os.path.normcase(os.path.abspath(os.fspath(path))) + "\x1f" + (sheet or "")


@dataclass
class DatasetReference:
    """소스를 다시 여는 순수 참조 값과 2상태 수명.

    ``opts``에는 파일 경로나 나라장터 쿼리만 들며 레코드와 ServiceKey는 들지 않는다.
    가산 필드는 ``from_dict`` 기본값으로 구 직렬화 형상을 계속 읽는다.
    """

    name: str
    kind: str
    opts: "dict[str, object]" = field(default_factory=dict)
    status: str = STATUS_ACTIVE
    created_at: str = ""
    note: str = ""
    version: int = 1

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError(f"알 수 없는 데이터셋 상태입니다: {self.status!r}")

    def archive(self) -> None:
        self.status = STATUS_ARCHIVED

    def activate(self) -> None:
        self.status = STATUS_ACTIVE

    @property
    def is_active(self) -> bool:
        return self.status == STATUS_ACTIVE

    def to_dict(self) -> dict:
        """기존 레지스트리 JSON과 같은 순서·필드를 가진 값 사전."""
        return {
            "version": self.version,
            "name": self.name,
            "kind": self.kind,
            "opts": dict(self.opts),
            "status": self.status,
            "created_at": self.created_at,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, value: dict) -> Self:
        """구 retired 값을 archived로 무손실 정규화해 참조를 복원한다."""
        status = value.get("status", STATUS_ACTIVE)
        status = _LEGACY_STATUS_ALIASES.get(status, status)
        return cls(
            name=value.get("name", ""),
            kind=value.get("kind", ""),
            opts=dict(value.get("opts", {})),
            status=status,
            created_at=value.get("created_at", ""),
            note=value.get("note", ""),
            version=value.get("version", 1),
        )


def reference_identity(item: DatasetReference) -> "str | None":
    """경로가 있는 엑셀 참조의 데이터 정체성. 그 밖에는 ``None``."""
    if item.kind != "excel" or not isinstance(item.opts, dict):
        return None
    raw = item.opts.get("path")
    if not isinstance(raw, str) or not raw:
        return None
    raw_sheet = item.opts.get("sheet")
    sheet = raw_sheet if isinstance(raw_sheet, str) else ""
    return excel_identity(raw, sheet)


__all__ = [
    "STATUS_ACTIVE",
    "STATUS_ARCHIVED",
    "STATUS_RETIRED",
    "DatasetReference",
    "excel_identity",
    "reference_identity",
]
