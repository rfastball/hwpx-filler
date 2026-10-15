"""덮어쓰지 않는 사본 이름 — 이름이 이미 있으면 ``이름 (2)``·``이름 (3)``… 를 고른다.

서식 폴더로 파일을 들일 때(:meth:`~hwpxfiller.external.template_files.TemplateFileStore.copy_into_library`)와
작업 꾸러미를 불러올 때(작업·선택 프리셋 이름, 새 템플릿 파일 이름)가 같은 규칙을 쓴다.
규칙이 두 벌이면 불러오기 확인 창이 미리 말한 이름과 실제로 생긴 이름이 갈린다.

순수 계산이다 — 「이미 있는가」는 호출자가 술어로 넘긴다(I/O 없음).
"""

from __future__ import annotations

from collections.abc import Callable

from .output_name import is_reserved_device_name


def numbered_label(name: str, number: int) -> str:
    """``number`` 번째 후보 이름 — 1 은 원래 이름, 2 부터 ``이름 (n)``."""
    return name if number == 1 else f"{name} ({number})"


def numbered_file_name(name: str, number: int) -> str:
    """파일 이름의 ``number`` 번째 후보 — 번호는 확장자 앞에 든다(``계약 (2).hwpx``)."""
    if number == 1:
        return name
    stem, dot, suffix = name.rpartition(".")
    if not dot or not stem:
        return f"{name} ({number})"
    return f"{stem} ({number}).{suffix}"


def first_free(candidate: Callable[[int], str], taken: Callable[[str], bool]) -> str:
    """``candidate(1)``·``candidate(2)``… 가운데 처음으로 ``taken`` 이 아닌 이름."""
    number = 1
    while taken(name := candidate(number)):
        number += 1
    return name


def device_safe_file_name(name: str) -> str:
    """Windows 예약 장치 이름(``CON.hwpx`` 등)이면 첫 마디 뒤에 ``_`` 를 붙여 파일 이름으로 만든다.

    예약 이름은 파일이 아니라 장치를 열므로 그대로 쓸 수 없다. 그 밖의 이름은 그대로 둔다.
    """
    if not is_reserved_device_name(name):
        return name
    head, dot, rest = name.partition(".")
    return f"{head}_{dot}{rest}"


__all__ = ["device_safe_file_name", "first_free", "numbered_file_name", "numbered_label"]
