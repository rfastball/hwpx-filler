"""HWPX 템플릿 엔진 — 요구 필드 판독(사전검증·CLI ``--fields``·실행뷰).

종전 이 자리는 VBA ``modHWPXEngine`` 포트인 legacy 생성(``generate`` → ``GenerateResult``)도
소유했다. 문서 생성은 managed materialization 하나가 되어(#1081 PR3) 그 갈래는 퇴역했고,
남은 것은 필드 판독뿐이다.
"""

from __future__ import annotations

from typing import Callable

from hwpxcore.text_extract import PackageLike

from .fields import FieldDocument, field_xml_names


class HwpxEngine[PackageT: PackageLike]:
    """템플릿 경로 → 요구 누름틀 이름.

    경로 읽기는 주입된 ``read_package`` 가 소유한다(P3-03, #591 — 의미론 층은 concrete IO 를
    개시하지 않는다). concrete 결속은 :func:`hwpxfiller.external.hwpx_engine.make_hwpx_engine`
    이 조립한다.
    """

    def __init__(self, read_package: "Callable[[str], PackageT]"):
        self._read_package = read_package

    def required_fields(self, template_path: str) -> "list[str]":
        """템플릿이 요구하는 누름틀 이름 전체(사전검증용)."""
        pkg = self._read_package(template_path)
        seen: dict[str, None] = {}
        for name in field_xml_names(pkg):
            for f in FieldDocument(pkg.entries[name], entry=name).required_fields():
                seen.setdefault(f, None)
        return list(seen)
