"""데이터 풀의 원자 저장 연산 계약."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from ..domain.dataset_reference import DatasetReference

if TYPE_CHECKING:
    from .dataset_pool import CorruptDatasetEntry


class DatasetPoolPort(Protocol):
    """Application 이 요구하는 데이터셋 레지스트리 효과의 semantic port(#570).

    구조적(덕타이핑) 계약이다: concrete 는
    :class:`hwpxfiller.external.dataset_store.DatasetPoolRegistry`, 테스트는 in-memory
    구현이 선다. 모든 쓰기 연산은 저장 매체 안에서 **원자적으로** 완결된다 — 호출자가
    잠금을 알 필요도, 잡을 방법도 없다. ``expected_basis`` 를 받는 연산은 지금 상태의
    지문(:func:`confirm_basis` × :func:`bound_state`)과 대조해 다르거나 미동봉이면
    :class:`StaleConfirmError` 로 fail-closed 한다.
    """

    def load(self, key: str) -> DatasetReference: ...

    def list_references(
        self, status: "str | None" = None
    ) -> "tuple[list[tuple[str, DatasetReference]], list[CorruptDatasetEntry]]": ...

    def find_identity_raw(
        self, ident: str
    ) -> "tuple[str, DatasetReference] | None": ...

    def find_identity(
        self, path: "str | Path", sheet: "str | None" = ""
    ) -> "tuple[str, DatasetReference] | None": ...

    def add(self, item: DatasetReference) -> str: ...

    def delete(self, key: str) -> None: ...

    def archive(self, key: str) -> DatasetReference: ...

    def activate(self, key: str) -> DatasetReference: ...

    def reorder_sheets(self, key: str, sheets: list[str]) -> DatasetReference: ...

    def relabel(self, key: str, name: str, *, note: str = "") -> DatasetReference: ...

    def set_filters(
        self, key: str, filters: "list[dict]", *, sheet: "str | None" = None,
    ) -> DatasetReference: ...

    def relink_excel(
        self, key: str, path: str, *,
        sheet: "str | None" = None, note: str = "", name: str = "",
        sheets: "list[str] | None" = None,
    ) -> DatasetReference: ...

    def relabel_confirmed_raw(
        self, ident: str, name: str, *,
        note: str = "", expected_basis: "str | None", sheets: "list[str] | None" = None,
    ) -> "tuple[str, DatasetReference]": ...

    def relabel_confirmed(
        self, path: str, sheet: "str | None", name: str, *,
        note: str = "", expected_basis: "str | None", sheets: "list[str] | None" = None,
    ) -> "tuple[str, DatasetReference]": ...

    def relink_confirmed(
        self, key: str, path: str, *,
        sheet: "str | None" = None, note: str = "", name: str = "",
        expected_basis: "str | None",
        sheets: "list[str] | None" = None,
    ) -> DatasetReference: ...

    def delete_confirmed(
        self, key: str, *, expected_basis: "str | None"
    ) -> DatasetReference: ...

    def resolve_duplicates(
        self, keep: str, *, expected_basis: "str | None"
    ) -> "tuple[str, int]": ...

