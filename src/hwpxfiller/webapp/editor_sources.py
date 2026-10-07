"""편집기 세션의 두 재료 — 템플릿과 데이터가 **무엇이고 어디에 있는가**.

스냅샷과 로더가 읽는 재료 쪽 사실을 한 자리에 둔다. 상태를 바꾸지 않는다(조회 캐시는 세션에 둔다).

- 템플릿: 파일 하나를 읽어 필드 구성·부분 채움 관문·RAW 사유를 한 벌로 내는 것은
  :func:`read_template_intake` 다(HWPX·TXT 두 매체가 같은 모양으로 답한다). 편집기는 자기
  템플릿 목록을 들지 않는다(U6-E #979) — 소속 판정은 ``tpl`` 채널의 관문(``is_library_path``)
  하나에 위임하고 서식 폴더 좌표는 :class:`TemplateRoot` 가 소유한다.
  :class:`EditorTemplateLibrary` 는 그 둘을 이 세션의 템플릿 하나에 대어 읽는다 — 표시명·
  항목 상세 가부·저장 폴더 재진술이 같은 좌표를 본다.
- 데이터: 표시명·우 열의 「지금 선 행」·시트 탭·세션 행은 모두 같은 물음(이 결속이 풀에
  등록돼 있는가)의 답을 읽는다. 각자 풀을 조회하면 같은 폴더 스캔을 여러 번 지불하고, 그
  사이에 갈린 상태가 이름과 표시 행을 어긋나게 한다. 그래서 조회는 :class:`EditorDataIdentity`
  한 자리(세션 캐시 포함)가 지고 나머지는 그 답을 재진술한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..domain.job import template_media
from ..domain.schema import FieldSpec, TemplateSchema, extract_schema, infer_type
from ..domain.template_status import library_display_name
from ..domain.text_render import SEG_MISSING, render_segments, template_fields
from ..external.hwpx_package_io import read_hwpx_package
from ..external.template_root import TemplateRoot
from ..viewmodel.edit_session import EditSession
from ..viewmodel.mapping_state import RAW_BLOCK_MESSAGE, PartialGate, gate_for_template
from .output_folder_zone import output_folder_zone
from .pool_column import session_data_row
from .screens import (
    TXT_RAW_BLOCK,
    dataset_reference_identity,
    registered_dataset_entry,
    registered_sheet_tabs,
)

SESSION_DETAIL_OUTSIDE_TEXT = (
    "서식 폴더 밖의 템플릿이라 항목 상세를 열 수 없습니다. 설정에서 서식 폴더를 확인하세요."
)
SESSION_DETAIL_UNWIRED_TEXT = "템플릿 라이브러리 관문이 배선되지 않아 항목 상세를 열 수 없습니다."


@dataclass(frozen=True)
class TemplateIntake:
    """템플릿 하나를 읽은 한 벌 — 채울 필드가 없으면 ``schema`` 가 ``None`` 이고 사유가 선다."""

    schema: "TemplateSchema | None"
    gate: "PartialGate | None" = None
    gate_error: bool = False
    raw_block: str = ""


def txt_template_schema(path: str) -> "TemplateSchema | None":
    """TXT 템플릿의 필드 구성 — 토큰이 하나도 없으면 ``None``(RAW)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"TXT 템플릿을 읽을 수 없습니다: {exc}") from exc
    segments, _report = render_segments(text, {})
    occurrences: "dict[str, int]" = {}
    for seg in segments:
        if seg.kind == SEG_MISSING:
            occurrences[seg.name] = occurrences.get(seg.name, 0) + 1
    names = template_fields(text)
    if not names:
        return None
    return TemplateSchema(
        fields=[
            FieldSpec(
                name=n,
                inferred_type=infer_type(n),
                occurrences=occurrences.get(n, 1),
                in_table=False,
            )
            for n in names
        ]
    )


def read_template_intake(path: str) -> TemplateIntake:
    """템플릿 파일을 읽어 필드 구성·관문·RAW 사유를 낸다 — 읽기 실패는 그대로 올린다."""
    if template_media(path) == "txt":
        schema = txt_template_schema(path)
        return TemplateIntake(schema, raw_block="" if schema is not None else TXT_RAW_BLOCK)
    pkg = read_hwpx_package(path)
    schema = extract_schema(pkg)
    if not schema.fields:
        return TemplateIntake(None, raw_block=RAW_BLOCK_MESSAGE)
    try:
        return TemplateIntake(schema, gate=gate_for_template(pkg))
    except Exception:  # noqa: BLE001 — 관문을 모르면 진행 불가로 재진술한다(게이트 오류)
        return TemplateIntake(schema, gate_error=True)


class EditorTemplateLibrary:
    """세션 템플릿과 서식 폴더·라이브러리 관문·저장 폴더 기억 사이의 대응을 소유한다."""

    def __init__(
        self,
        edit: EditSession,
        *,
        template_root: "TemplateRoot | None" = None,
        is_library_path: "Callable[[str, str], bool] | None" = None,
        remembered_output_directory: "Callable[[], str] | None" = None,
    ) -> None:
        self.edit = edit
        self._root_holder = template_root
        self._is_library_path = is_library_path
        self._remembered_output_directory = remembered_output_directory

    def root(self) -> TemplateRoot:
        """서식 폴더 좌표 — 주입이 없으면 처음 물을 때 기본 좌표를 세운다."""
        if self._root_holder is None:
            self._root_holder = TemplateRoot()
        return self._root_holder

    def display_name(self) -> str:
        """사람이 읽는 템플릿 이름(서식 폴더 상대) — 템플릿이 없으면 ``""``."""
        if not self.edit.template_path:
            return ""
        return library_display_name(self.root().path(), self.edit.template_path)

    def is_live(self, path: str) -> bool:
        """``path`` 가 지금 라이브러리 목록에 있는가 — 관문이 없으면 시끄럽게 거절한다."""
        gate = self._is_library_path
        if gate is None:
            raise ValueError("템플릿 라이브러리 관문이 배선되지 않아 경로를 확인할 수 없습니다.")
        return bool(gate(template_media(path), path))

    def session_detail(self) -> dict:
        """이 세션 템플릿의 항목 상세를 열 수 있는가 — 경로 단위로 캐시한다."""
        if not self.edit.template_path:
            return {"available": False, "reason": ""}
        cached = self.edit.session_detail_cache
        if cached is not None and cached[0] == self.edit.template_path:
            return cached[1]
        value = self._detail_availability()
        self.edit.session_detail_cache = (self.edit.template_path, value)
        return value

    def _detail_availability(self) -> dict:
        gate = self._is_library_path
        if gate is None:
            return {"available": False, "reason": SESSION_DETAIL_UNWIRED_TEXT}
        try:
            live = bool(gate(template_media(self.edit.template_path), self.edit.template_path))
        except Exception:  # noqa: BLE001 — 관문 실패는 「열 수 없음」으로 재진술한다
            live = False
        if live:
            return {"available": True, "reason": ""}
        return {"available": False, "reason": SESSION_DETAIL_OUTSIDE_TEXT}

    def output_folder(self) -> "dict[str, str] | None":
        """「이름·저장」의 저장 폴더 재진술 — TXT 작업은 파일을 만들지 않아 ``None``."""
        if not self.edit.template_path or template_media(self.edit.template_path) == "txt":
            return None
        remembered = self._remembered_output_directory
        return output_folder_zone(
            template_path=self.edit.template_path,
            remembered_directory=remembered() if remembered is not None else "",
        )


class EditorDataIdentity:
    """세션 데이터 결속(경로·시트·종류)과 등록 풀 사이의 대응을 소유한다."""

    def __init__(self, edit: EditSession, *, pool_registry=None) -> None:
        self.edit = edit
        self._pool_registry = pool_registry

    def registered_entry(self) -> "tuple[str, str]":
        """이 결속의 ``(슬롯 키, 등록명)`` — 등록이 아니면 ``("", "")``.

        결속 정체성으로 캐시한다(``edit.data_name_cache``). 데이터가 바뀌면 정체성이
        바뀌므로 캐시를 지우지 않아도 낡은 답을 내지 않는다.
        """
        if self._pool_registry is None:
            return ("", "")
        ident = dataset_reference_identity(
            path=self.edit.data_path, sheet=self.edit.data_sheet, kind=self.edit.data_kind
        )
        if not ident:
            return ("", "")
        cached = self.edit.data_name_cache
        if cached is not None and cached[0] == ident:
            return (cached[1], cached[2])
        key, name = registered_dataset_entry(
            self._pool_registry,
            path=self.edit.data_path,
            sheet=self.edit.data_sheet,
            kind=self.edit.data_kind,
        )
        self.edit.data_name_cache = (ident, key, name)
        return (key, name)

    def display_name(self) -> str:
        """사람이 읽는 데이터 이름 — 등록명이 있으면 그것, 없으면 파일 이름."""
        if not self.edit.data_path:
            return ""
        return self.registered_entry()[1] or Path(self.edit.data_path).stem

    def sheet_tabs(self) -> list[dict]:
        """「연결 확인」의 시트 탭 — 작업 화면과 같은 투영이다.

        풀 겨눔 표지가 없으면(저장본을 다시 열었거나 파일로 연 데이터) 등록 정체성으로 찾은
        슬롯이 그 자리를 잇는다 — 우 열의 「지금 선 행」(``pairing.data_key``)과 같은 조회다.
        """
        return registered_sheet_tabs(
            self._pool_registry,
            self.edit.data_pool_key or self.registered_entry()[0],
            path=self.edit.data_path,
            sheet=self.edit.data_sheet,
            kind=self.edit.data_kind,
        )

    def session_row(self) -> "dict | None":
        """우 열 맨 위의 세션 행 — 풀에 없는 데이터(파일로 연 데이터)일 때만 선다."""
        if not self.edit.data_path or self.registered_entry()[0]:
            return None
        return session_data_row(
            name=self.display_name(),
            kind=self.edit.data_kind,
            path=self.edit.data_path,
            sheet=self.edit.data_sheet,
            header_row=self.edit.data_header_row,
            record_count=len(self.edit.records),
        )


__all__ = [
    "EditorDataIdentity",
    "EditorTemplateLibrary",
    "SESSION_DETAIL_OUTSIDE_TEXT",
    "SESSION_DETAIL_UNWIRED_TEXT",
    "TemplateIntake",
    "read_template_intake",
    "txt_template_schema",
]
