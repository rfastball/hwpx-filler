"""데이터셋 참조의 순수 값·수명·정체성 규칙.

파일 레지스트리와 JSON byte I/O는 External Adapter인
``hwpxfiller.external.dataset_store``가 소유한다(P2-22 #570). 이 모듈은 레코드나
비밀값이 아닌 소스 재연결 정보와 active/archived 수명만 표현한다.
"""

from __future__ import annotations

import copy
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


def pclm_identity(db: "str | Path", view: str) -> str:
    """계약 목록(pclm) 참조 정체성: **kind 접두** + 정규화 DB 경로 + 뷰.

    축은 엑셀과 같다(파일 하나 + 그 안의 면 하나 = 데이터 하나)라 계산은
    :func:`excel_identity` 를 그대로 쓰지만, 접두 없이 같은 문자열 공간을 쓰면 두 종류가
    **교차 충돌**한다: ``pclm.db`` 를 파일로 등록한 엑셀 참조와 뷰 이름이 시트 이름과
    겹치는 pclm 참조가 같은 데이터로 판정돼 등록이 거절되거나(``add``), 서로 다른 종류가
    한 중복 그룹으로 묶여 병합 확정에 섞인다(``resolve_duplicates``). 정체성은 「같은
    데이터인가」의 축이고 종류가 다르면 같은 데이터가 아니다.
    """
    return "pclm\x1f" + excel_identity(db, view)


def resolve_pclm_db(db: str) -> str:
    """계약 목록 DB 경로 해석 — 사용자가 적은 자리의 절대경로. 빈 값은 거절한다.

    등록(Application ``DatasetPoolViewModel.register_pclm``)과 그 전 중복 조회가 **같은
    자리**를 봐야 한다. 두 곳이 각자 상대경로를 해석하면 같은 데이터가 2건이 된다. 정체성
    (:func:`pclm_identity`)과 같은 정규화 축이라 이 모듈에 산다. 빈 값을 다른 프로그램의
    설치 자리로 추측하지 않는다 — 그 추측은 외부 프로그램의 배치에 기대는 조용한 기본값이라
    걷혔다(자리는 사용자가 고른 것뿐이다). 존재 검사는 하지 않는다 — 참조 등록은 파일을 열지
    않고, 끊김은 배지(Application ``reference_missing``)와 실행 시점 재읽기가 말한다.
    """
    if not db:
        raise ValueError("파일 경로가 비어 있습니다.")
    return os.path.abspath(db)


@dataclass
class DatasetReference:
    """소스를 다시 여는 순수 참조 값과 2상태 수명.

    ``opts``에는 파일 경로나 나라장터 쿼리만 들며 레코드와 ServiceKey는 들지 않는다.
    가산 필드는 ``from_dict`` 기본값으로 구 직렬화 형상을 계속 읽는다.

    ``filters`` 는 이 데이터에 붙은 **저장한 필터** ``[{"name", "state"}]`` 다(칩 순서). 행이
    아니라 조건의 선언이라 「데이터·행 미저장」 불변식 안이다. ``state`` 의 문법은 필터
    모델(:mod:`hwpxfiller.viewmodel.filter_state`)이 소유하고 여기는 형상만 지킨다. 비어
    있으면 직렬화하지 않아 구판 파일과 bytes 가 같다.
    """

    name: str
    kind: str
    opts: "dict[str, object]" = field(default_factory=dict)
    status: str = STATUS_ACTIVE
    created_at: str = ""
    note: str = ""
    version: int = 1
    filters: "list[dict]" = field(default_factory=list)
    sheet_filters: "dict[str, list[dict]]" = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError(f"알 수 없는 데이터셋 상태입니다: {self.status!r}")
        self.filters = filter_presets_shape(self.filters)
        reference_sheets(self)
        if not isinstance(self.sheet_filters, dict) or any(
            not isinstance(name, str) or not name for name in self.sheet_filters
        ):
            raise ValueError("시트별 필터 형식이 올바르지 않습니다.")
        self.sheet_filters = {
            name: filter_presets_shape(presets) for name, presets in self.sheet_filters.items()
        }

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
            **({"filters": copy.deepcopy(self.filters)} if self.filters else {}),
            **({"sheet_filters": copy.deepcopy(self.sheet_filters)} if self.sheet_filters else {}),
        }

    @classmethod
    def from_dict(cls, value: dict) -> Self:
        """구 retired 값을 archived로 무손실 정규화해 참조를 복원한다."""
        status = value.get("status", STATUS_ACTIVE)
        status = _LEGACY_STATUS_ALIASES.get(status, status)
        if not isinstance(status, str):
            raise ValueError(f"알 수 없는 데이터셋 상태입니다: {status!r}")
        return cls(
            name=value.get("name", ""),
            kind=value.get("kind", ""),
            opts=dict(value.get("opts", {})),
            status=status,
            created_at=value.get("created_at", ""),
            note=value.get("note", ""),
            version=value.get("version", 1),
            filters=value.get("filters", []),
            sheet_filters=value.get("sheet_filters", {}),
        )


def reference_sheets(item: DatasetReference) -> "list[str]":
    """등록된 시트 선언. 구판 단일 시트 참조는 그대로 한 장으로 읽는다."""
    if not isinstance(item.opts, dict):
        raise ValueError("등록 데이터 참조 형식이 올바르지 않습니다.")
    raw = item.opts.get("sheet") if item.kind == "excel" else item.opts.get("view")
    if item.kind not in {"excel", "pclm"} or "sheets" not in item.opts:
        return [raw] if isinstance(raw, str) and raw else []
    sheets = item.opts["sheets"]
    if (
        not isinstance(sheets, list) or not sheets
        or any(not isinstance(name, str) or not name for name in sheets)
        or len(set(sheets)) != len(sheets)
        or raw not in sheets
    ):
        raise ValueError("등록할 시트와 기본 시트를 확인하세요.")
    return list(sheets)


def reference_for_sheet(
    item: DatasetReference, sheet: "str | None" = None,
) -> DatasetReference:
    """등록 선언 안의 시트를 읽을 사본. 저장된 기본 시트는 바꾸지 않는다."""
    selected = copy.deepcopy(item)
    if sheet is None:
        return selected
    if sheet == "" and not reference_sheets(item):
        return selected
    if sheet not in reference_sheets(item):
        raise ValueError("등록된 시트를 선택하세요.")
    selected.filters = filters_for_sheet(item, sheet)
    selected.opts["sheet" if item.kind == "excel" else "view"] = sheet
    return selected


def filters_for_sheet(item: DatasetReference, sheet: "str | None" = None) -> "list[dict]":
    """기본 시트의 구판 필터와 다른 시트의 필터를 분리해 읽는다."""
    default = item.opts.get("sheet" if item.kind == "excel" else "view")
    if sheet is None or sheet == (default or "") or item.kind not in {"excel", "pclm"}:
        return copy.deepcopy(item.filters)
    if sheet not in reference_sheets(item):
        raise ValueError("등록된 시트를 선택하세요.")
    return copy.deepcopy(item.sheet_filters.get(sheet, []))


def excel_reference_opts(
    path: str, sheet: "str | None" = None, sheets: "list[str] | None" = None,
) -> "dict[str, object]":
    """엑셀 등록·재연결이 공유하는 참조 형상."""
    opts: "dict[str, object]" = {"path": path}
    if sheet:
        opts["sheet"] = sheet
    if sheets is not None:
        opts["sheets"] = list(sheets)
    DatasetReference(name="", kind="excel", opts=opts)
    return opts


def filter_presets_shape(value: object) -> "list[dict]":
    """저장한 필터 목록의 **형상**만 검사해 사본을 돌려준다 — 손상은 시끄럽게 거절한다.

    각 항목은 ``{"name": 비지 않은 문자열, "state": 사전}`` 이고 이름은 겹치지 않는다.
    조건 문법 검사는 필터 모델 소관이다(쓸 수 없는 저장본은 그 칩이 사유와 함께 막힌다).
    """
    if not isinstance(value, list):
        raise ValueError("저장한 필터 목록 형식이 올바르지 않습니다.")
    seen: "set[str]" = set()
    presets: "list[dict]" = []
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError("저장한 필터 항목 형식이 올바르지 않습니다.")
        name, state = entry.get("name"), entry.get("state")
        if not isinstance(name, str) or not name.strip() or not isinstance(state, dict):
            raise ValueError("저장한 필터 항목 형식이 올바르지 않습니다.")
        if name in seen:
            raise ValueError(f"저장한 필터 이름이 겹칩니다: {name}")
        seen.add(name)
        presets.append({"name": name, "state": copy.deepcopy(state)})
    return presets


def reference_identity(item: DatasetReference) -> "str | None":
    """파일을 가리키는 참조(엑셀·계약 목록)의 데이터 정체성. 그 밖에는 ``None``."""
    if not isinstance(item.opts, dict):
        return None
    if item.kind == "excel":
        raw = item.opts.get("path")
        if not isinstance(raw, str) or not raw:
            return None
        raw_sheet = item.opts.get("sheet")
        sheet = raw_sheet if isinstance(raw_sheet, str) else ""
        return excel_identity(raw, sheet)
    if item.kind == "pclm":
        # 손편집·구판 항목의 깨진 형은 추측해 고치지 않는다 — 정체성 없음(엑셀과 같은 규율).
        raw_db = item.opts.get("db")
        raw_view = item.opts.get("view")
        if not isinstance(raw_db, str) or not raw_db or not isinstance(raw_view, str):
            return None
        return pclm_identity(raw_db, raw_view)
    return None


__all__ = [
    "STATUS_ACTIVE",
    "STATUS_ARCHIVED",
    "STATUS_RETIRED",
    "DatasetReference",
    "excel_identity",
    "excel_reference_opts",
    "filters_for_sheet",
    "filter_presets_shape",
    "pclm_identity",
    "reference_identity",
    "resolve_pclm_db",
    "reference_sheets",
    "reference_for_sheet",
]
